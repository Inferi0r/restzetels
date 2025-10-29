<?php
// DigitalOcean Functions handler for election data proxy
// Provides ANP and NOS endpoints per year with clear key names and backwards-compatible aliases.
// Input (query params):
//   - year: 2021 | 2023 | 2025 (defaults to 2025)
//   - source: one of
//       New keys:   anp_votes | anp_last_update | nos_index | nos_gemeente
//       Aliases:    votes     | last_update     | nos       | gemeente
//   - cbs_code: required when source is nos_gemeente (or alias 'gemeente')

function get_header_from_args(array $args, string $name): ?string {
    $lname = strtolower($name);
    if (isset($args['__ow_headers']) && is_array($args['__ow_headers'])) {
        $h = array_change_key_case($args['__ow_headers'], CASE_LOWER);
        return $h[$lname] ?? null;
    }
    if (isset($args['headers']) && is_array($args['headers'])) {
        $h = array_change_key_case($args['headers'], CASE_LOWER);
        return $h[$lname] ?? null;
    }
    if (isset($_SERVER)) {
        $key = 'HTTP_' . strtoupper(str_replace('-', '_', $name));
        return $_SERVER[$key] ?? null;
    }
    return null;
}

function json_response(array $body, int $status = 200, array $extraHeaders = []) : array {
    $json = json_encode($body);
    $etag = 'W/"' . sha1($json) . '"';
    $headers = array_merge([
        'Content-Type' => 'application/json; charset=utf-8',
        'Cache-Control' => 'public, max-age=10, s-maxage=10, stale-while-revalidate=30',
        'ETag' => $etag
    ], $extraHeaders);
    // 304 handling via If-None-Match
    $ifNoneMatch = get_header_from_args($GLOBALS['__fn_args__'] ?? [], 'If-None-Match');
    if ($ifNoneMatch && trim($ifNoneMatch) === $etag) {
        return [ 'statusCode' => 304, 'headers' => $headers ];
    }
    return [ 'statusCode' => $status, 'headers' => $headers, 'body' => $body ];
}

function fetch_with_cache(string $cacheKey, string $url, int $ttl = 10) : ?array {
    $cacheDir = sys_get_temp_dir() . '/restzetels_cache';
    if (!is_dir($cacheDir)) { @mkdir($cacheDir, 0777, true); }
    $cachePath = $cacheDir . '/' . $cacheKey . '.json';
    if (file_exists($cachePath) && (time() - filemtime($cachePath) < $ttl)) {
        $jsonData = @file_get_contents($cachePath);
        if ($jsonData !== false) return json_decode($jsonData, true);
    }
    $jsonData = @file_get_contents($url);
    if ($jsonData === false) {
        if (file_exists($cachePath)) {
            $stale = @file_get_contents($cachePath);
            if ($stale !== false) return json_decode($stale, true);
        }
        return null;
    }
    @file_put_contents($cachePath, $jsonData);
    return json_decode($jsonData, true);
}

function main(array $args) : array
{
    // Make args available to helpers (for ETag check)
    $GLOBALS['__fn_args__'] = $args;
    // Default to latest cycle
    $year = 2025;
    if (!empty($args['year'])) {
        $year = intval($args['year']);
    }

    // Per-year sources with descriptive keys
    $dataSources = [
        2021 => [
            'anp_votes'       => 'https://d2vz64kg7un9ye.cloudfront.net/data/500.json',
            'anp_last_update' => 'https://d2vz64kg7un9ye.cloudfront.net/data/index.json',
            'nos_index'       => 'https://voteflow.api.nos.nl/TK21/index.json',
            'nos_gemeente'    => 'https://voteflow.api.nos.nl/TK21/gemeente/',
        ],
        2023 => [
            'anp_votes'       => 'https://d1nxan4hfcgbsv.cloudfront.net/data/rh3xjs/500.json',
            'anp_last_update' => 'https://d1nxan4hfcgbsv.cloudfront.net/data/rh3xjs/index.json',
            'nos_index'       => 'https://voteflow.api.nos.nl/TK23/index.json',
            'nos_gemeente'    => 'https://voteflow.api.nos.nl/TK23/gemeente/',
        ],
        2025 => [
            'anp_votes'       => 'https://widgets.verkiezingsdienst.anp.nl/tk25/data/rh3xjs/500.json',
            'anp_last_update' => 'https://widgets.verkiezingsdienst.anp.nl/tk25/data/rh3xjs/index.json',
            'nos_index'       => 'https://voteflow.api.nos.nl/TK25/index.json',
            'nos_gemeente'    => 'https://voteflow.api.nos.nl/TK25/gemeente/',
        ],
    ];

    // Only accept new descriptive keys or 'all' bundle
    $requested = !empty($args['source']) ? $args['source'] : 'anp_votes';
    $sourceKey = $requested;

    if ($sourceKey === 'all') {
        // Bundle: anp_votes + anp_last_update + nos_index
        $bundleKey = sha1($year . '|all');
        $ttl = 10;
        $cacheDir = sys_get_temp_dir() . '/restzetels_cache';
        if (!is_dir($cacheDir)) { @mkdir($cacheDir, 0777, true); }
        $cachePath = $cacheDir . '/' . $bundleKey . '.json';
        if (file_exists($cachePath) && (time() - filemtime($cachePath) < $ttl)) {
            $cached = @file_get_contents($cachePath);
            if ($cached !== false) {
                $body = json_decode($cached, true);
                return json_response($body);
            }
        }
        $anpVotes = fetch_with_cache(sha1($year.'|anp_votes'), $dataSources[$year]['anp_votes']);
        $anpLast  = fetch_with_cache(sha1($year.'|anp_last_update'), $dataSources[$year]['anp_last_update']);
        $nosIndex = fetch_with_cache(sha1($year.'|nos_index'), $dataSources[$year]['nos_index']);
        if ($anpVotes === null && $anpLast === null && $nosIndex === null) {
            return json_response([ 'error' => 'Upstream fetch failed' ], 502);
        }
        $body = [ 'year' => $year, 'anp_votes' => $anpVotes, 'anp_last_update' => $anpLast, 'nos_index' => $nosIndex ];
        @file_put_contents($cachePath, json_encode($body));
        return json_response($body);
    }

    if (!isset($dataSources[$year][$sourceKey])) {
        return json_response([ 'error' => 'Unknown source or year' ], 400);
    }

    $url = $dataSources[$year][$sourceKey];
    if ($sourceKey === 'nos_gemeente') {
        if (empty($args['cbs_code'])) {
            return json_response([ 'error' => 'Missing cbs_code for nos_gemeente' ], 400);
        }
        $url .= $args['cbs_code'] . '.json';
    }

    $ttl = 10;
    $cacheKey = sha1($year . '|' . $sourceKey . '|' . ($args['cbs_code'] ?? ''));
    $data = fetch_with_cache($cacheKey, $url, $ttl);
    if ($data === null) {
        return json_response([ 'error' => 'Upstream fetch failed' ], 502);
    }
    return json_response($data);
}
