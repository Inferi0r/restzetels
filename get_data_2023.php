<?php
    // Define the data sources
    $dataSources = [
        'votes' => 'https://d1nxan4hfcgbsv.cloudfront.net/data/rh3xjs/500.json',
        'last_update' => 'https://d1nxan4hfcgbsv.cloudfront.net/data/rh3xjs/index.json'
    ];

    // Get the URL of the requested data source
    $dataUrl = $dataSources[$_GET['source']];

    // Fetch the JSON data
    $jsonData = file_get_contents($dataUrl);

    // Parse JSON data into a PHP array
    $data = json_decode($jsonData, true);

    // Send the JSON response
    header('Content-Type: application/json');
    echo json_encode($data);
?>
