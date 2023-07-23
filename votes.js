// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {

    // Object to store party data by key
    let parties = {};

    // Fetch parties data from index.json
    fetch('/get_data.php?source=last_update')
    .then(response => response.json())
    .then(data => {
        // Transform parties array into an object keyed by party key
        parties = data.parties.reduce((obj, party) => {
        obj[party.key] = party;
        return obj;
        }, {});
        // Fetch the votes data
        fetchData();
    })
    .catch(error => console.error('Error fetching index data:', error));

    // Function to populate the table with the fetched data
    function populateTable(data) {
        var tableBody = document.getElementById('data-table').getElementsByTagName('tbody')[0];

        // Check if the data is an array
        if (!Array.isArray(data) || data.length === 0) {
            console.error('Invalid data format or empty data.');
            return;
        }

        // Get the table headers
        var tableHeaders = document.querySelectorAll('#data-table th[data-field]');

        // Loop through the data and create table rows
        data.forEach(function (item) {
            var newRow = document.createElement('tr');

            // Loop through the table headers and extract corresponding data
            for (var i = 0; i < tableHeaders.length; i++) {
                var field = tableHeaders[i].getAttribute('data-field');
                var cellValue = getNestedValue(item, field);

                var newCell = document.createElement('td');
                newCell.textContent = cellValue;
                newRow.appendChild(newCell);
            }

            // If this row is for a party, create party label and color cells after the key cell
            if (parties.hasOwnProperty(item.key)) {
                let partyLabelCell = document.createElement('td');
                partyLabelCell.textContent = parties[item.key].label;
                newRow.insertBefore(partyLabelCell, newRow.children[1]); // Place the label cell at 2nd column

                let partyColorCell = document.createElement('td');
                partyColorCell.style.backgroundColor = parties[item.key].color;
                newRow.insertBefore(partyColorCell, newRow.children[2]); // Place the color cell at 3rd column
            }

            tableBody.appendChild(newRow);
        });
    }

    // Function to get the value from nested object based on a dot-separated key
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

    // Function to populate the update fields
    function populateUpdateFields(data) {
        document.getElementById('lastUpdate').textContent = new Date(data.updated * 1000).toLocaleString();
        document.getElementById('currentTurnout').textContent = data.turnout.current;
        document.getElementById('previousTurnout').textContent = data.turnout.previous;
    }

    // Function to handle AJAX request and data population
    function fetchData() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/get_data.php?source=votes', true);
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

                    // Call the populateUpdateFields function to update the fields
                    populateUpdateFields(responseData);
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

    setInterval(fetchData, 60000); // Update every minute
});
