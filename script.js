// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {
    // Function to populate the table with the fetched data
    function populateTable(data) {
        var tableBody = document.getElementById('data-table').getElementsByTagName('tbody')[0];

        // Check if the data is an array
        if (!Array.isArray(data)) {
            console.error('Data is not an array:', data);
            return;
        }

        // Check if the data array is not empty
        if (data.length === 0) {
            console.warn('Data array is empty.');
            return;
        }

        // Loop through the data and create table rows
        data.forEach(function (row) {
            var newRow = document.createElement('tr');
            newRow.innerHTML = `
                <td>${row['Key']}</td>
                <td>${row['Results Previous Votes']}</td>
                <td>${row['Results Previous Percentage']}</td>
                <td>${row['Results Previous Seats']}</td>
                <!-- Add other table cells here -->
            `;
            tableBody.appendChild(newRow);
        });
    }

    // Function to handle AJAX request and data population
    function fetchData() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', 'get_data.php', true);
        xhr.setRequestHeader('Content-type', 'application/json');

        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var responseData = JSON.parse(xhr.responseText);

                    // Check if the response data is an array
                    if (!Array.isArray(responseData)) {
                        console.error('Response data is not an array:', responseData);
                        return;
                    }

                    // Call the populateTable function to update the table
                    populateTable(responseData);
                } catch (error) {
                    console.error('Error parsing JSON data:', error);
                }
            } else {
                // Handle error if AJAX request fails
                console.error('Error fetching data:', xhr.statusText);
            }
        };

        xhr.onerror = function () {
            // Handle error if there's an issue with the AJAX request
            console.error('Error fetching data.');
        };

        xhr.send();
    }

    // Call the fetchData function to populate the table
    fetchData();
});
