<?php
function main(array $args) : array {
    if (isset($args['year']) && isset($args['action']) && $args['action'] === 'fetchTotalKiesgerechtigden') {
        $year = $args['year'];
        return fetchTotalKiesgerechtigden($year);
    } else {
        return ['body' => 'Invalid or missing parameters'];
    }
}

function fetchTotalKiesgerechtigden($year) : array {
    $shortYear = substr($year, -2);
    $indexUrl = "https://voteflow.api.nos.nl/TK{$shortYear}/index.json";
    $indexJson = file_get_contents($indexUrl);

    if (!$indexJson) {
        return ['body' => 'Failed to fetch index.json'];
    }

    $indexData = json_decode($indexJson, true);
    $totalKiesgerechtigden = 0;

    foreach ($indexData['gemeentes'] as $gemeente) {
        $cbsCode = $gemeente['gemeente']['cbs_code'];
        $gemeenteUrl = "https://voteflow.api.nos.nl/TK{$shortYear}/gemeente/{$cbsCode}.json";
        $gemeenteJson = file_get_contents($gemeenteUrl);

        if ($gemeenteJson) {
            $gemeenteData = json_decode($gemeenteJson, true);
            if (isset($gemeenteData['huidige_verkiezing']) && $gemeenteData['huidige_verkiezing']['verkiezing_code'] === "TK{$shortYear}") {
                $totalKiesgerechtigden += $gemeenteData['huidige_verkiezing']['kiesgerechtigden'];
            }
        }
    }

    return ['body' => $totalKiesgerechtigden];
}

header('Content-Type: application/json');
echo json_encode(main($_GET));