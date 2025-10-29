<?php
// DigitalOcean Functions handler for election data proxy
// Provides ANP and NOS endpoints per year with clear key names and backwards-compatible aliases.
// Input (query params):
//   - year: 2021 | 2023 | 2025 (defaults to 2025)
//   - source: one of
//       New keys:   anp_votes | anp_last_update | nos_index | nos_gemeente
//       Aliases:    votes     | last_update     | nos       | gemeente
//   - cbs_code: required when source is nos_gemeente (or alias 'gemeente')

function main(array $args) : array
{
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

    // Only accept new descriptive keys
    $requested = !empty($args['source']) ? $args['source'] : 'anp_votes';
    $sourceKey = $requested;

    if (!isset($dataSources[$year][$sourceKey])) {
        return [ 'statusCode' => 400, 'body' => [ 'error' => 'Unknown source or year' ] ];
    }

    $url = $dataSources[$year][$sourceKey];

    if ($sourceKey === 'nos_gemeente') {
        if (empty($args['cbs_code'])) {
            return [ 'statusCode' => 400, 'body' => [ 'error' => 'Missing cbs_code for nos_gemeente' ] ];
        }
        $url .= $args['cbs_code'] . '.json';
    }

    $jsonData = @file_get_contents($url);
    if ($jsonData === false) {
        return [ 'statusCode' => 502, 'body' => [ 'error' => 'Upstream fetch failed' ] ];
    }

    return [ 'body' => json_decode($jsonData, true) ];
}
