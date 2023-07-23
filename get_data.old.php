<?php
try {
    // Use HTTPS for fetching the JSON data
    $dataUrl = 'https://d2vz64kg7un9ye.cloudfront.net/data/500.json';
    $jsonData = file_get_contents($dataUrl);

    // Check if JSON data is fetched successfully
    if ($jsonData === false) {
        throw new Exception('Error fetching JSON data.');
    }

    // Parse JSON data into a PHP array
    $data = json_decode($jsonData, true);

    // Check if JSON data is parsed successfully
    if ($data === null) {
        throw new Exception('Error parsing JSON data.');
    }

    // Send the JSON response
    header('Content-Type: application/json');
    echo json_encode($data); // Optional: Return the parsed JSON data as response
} catch (Exception $e) {
    // Handle any errors that occur during the data fetching or parsing process
    $errorMessage = 'Error: ' . $e->getMessage();
    // You can log the error or display an appropriate error message as needed
    echo $errorMessage;
}
?>



