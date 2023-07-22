<?php
// Replace this with your data source URL or PHP code to fetch the JSON data
$dataUrl = 'https://d2vz64kg7un9ye.cloudfront.net/data/500.json?v=18:24:11';
$jsonData = file_get_contents($dataUrl);

// Send the JSON response
header('Content-Type: application/json');
echo $jsonData;
?>
