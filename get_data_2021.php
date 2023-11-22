<?php
    // Define the data sources
    $dataSources = [
        'votes' => 'https://d2vz64kg7un9ye.cloudfront.net/data/500.json',
        'last_update' => 'https://d2vz64kg7un9ye.cloudfront.net/data/index.json'
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
