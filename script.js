// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {
    // Function to populate the table with the fetched data
    function populateTable(data) {
        var tableBody = document.getElementById('data-table').getElementsByTagName('tbody')[0];

        // Check if the data is an array
        if (!Array.isArray(data) || data.length === 0) {
            console.error('Invalid data format or empty data.');
            return;
        }

        // Loop through the data and create table rows
        data.forEach(function (item) {
            var newRow = document.createElement('tr');
            newRow.innerHTML = `
                <td>${item.key}</td>
                <td>${item.results.previous.votes}</td>
                <td>${item.results.previous.percentage}</td>
                <td>${item.results.previous.seats}</td>
                <!-- Add other table cells here -->
            `;
            tableBody.appendChild(newRow);
        });
    }

    // Function to handle AJAX request and data population
    function fetchData() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', 'https://arcovink.synology.me:8444/get_data.php', true);
        xhr.setRequestHeader('Content-type', 'application/json');

        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var responseData = JSON.parse(xhr.responseText);

                    // Check if the response data is an object with the 'parties' property
                    if (!responseData || !responseData.parties || !Array.isArray(responseData.parties)) {
                        console.error('Invalid response data:', responseData);
                        return;
                    }

                    // Call the populateTable function to update the table
                    populateTable(responseData.parties);
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
