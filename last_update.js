// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {

    // Function to get the value from a nested object based on a dot-separated key
    function getNestedValue(obj, key) {
        var keys = key.split('.');
        var value = obj;
        for (var i = 0; i < keys.length; i++) {
            value = value[keys[i]];
            if (value === undefined) {
                return '';
            }
        }
        return value;
    }

    // Function to populate the table with the fetched data
    function populateTable(data) {
        var table = document.getElementById('data-table');

        // Check if the data is an array
        if (!Array.isArray(data) || data.length === 0) {
            console.error('Invalid data format or empty data.');
            return;
        }

        // Create table headers
        var headers = Object.keys(data[0]);
        var thead = table.createTHead();
        var headerRow = thead.insertRow();
        for (var h of headers) {
            var th = document.createElement('th');
            th.textContent = h;
            headerRow.appendChild(th);
        }

        // Create table rows
        var tbody = table.createTBody();
        data.forEach(function (item) {
            var row = tbody.insertRow();
            headers.forEach(function (header) {
                var cell = row.insertCell();
                cell.textContent = getNestedValue(item, header);
            });
        });
    }

    // Function to handle AJAX request and data population
    function fetchData() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/get_data.php?source=last_update', true); // Use the relative URL with 'source' parameter
        xhr.setRequestHeader('Content-type', 'application/json');

        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var responseData = JSON.parse(xhr.responseText);

                    // Check if the response data is an array
                    if (!responseData || !Array.isArray(responseData)) {
                        console.error('Invalid response data:', responseData);
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
