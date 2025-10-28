<?php
function main(array $args) : array
{
    $year = 2021;

    if(!empty($args['year']))
        $year = $args['year'];

    $dataSources = [
        2021 => [
            'votes' => 'https://d2vz64kg7un9ye.cloudfront.net/data/500.json',
            'last_update' => 'https://d2vz64kg7un9ye.cloudfront.net/data/index.json',
            'nos' => 'https://voteflow.api.nos.nl/TK21/index.json'
        ],
        2023 => [
            'votes' => 'https://d1nxan4hfcgbsv.cloudfront.net/data/rh3xjs/500.json',
            'last_update' => 'https://d1nxan4hfcgbsv.cloudfront.net/data/rh3xjs/index.json',
            'nos' => 'https://voteflow.api.nos.nl/TK23/index.json',
			'gemeente' => 'https://voteflow.api.nos.nl/TK23/gemeente/',
        ]
    ];

    $dataSources = $dataSources[$year];
    
    $url = $dataSources['votes'];

    if(!empty($args['source'])) {
		$url = $dataSources[$args['source']];
		
		if($args['source'] === 'gemeente') {
			$url = $url.$args['cbs_code'].'.json';
		}
	}


    // Fetch the JSON data
    $jsonData = file_get_contents($url);

    return [
        'body' => json_decode($jsonData, true)
    ];
}