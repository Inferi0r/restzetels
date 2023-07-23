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
        var tbody = document.querySelector('#anp_updates-table tbody');

        // Clear any existing rows
        while (tbody.firstChild) {
            tbody.firstChild.remove();
        }

        // Construct a map from party keys to labels
        var partyMap = {};
        data.parties.forEach(function(party) {
            partyMap[party.key] = party.label;
        });

        // Populate table with views
        data.views.forEach(function(item) {
            var row = document.createElement('tr');

            // Include 'key', 'type', 'cbsCode', 'label', 'status', 'updated', 'parent' properties in this order
            ['key', 'type', 'cbsCode', 'label', 'status', 'updated', 'parent'].forEach(function(property) {
                var cell = document.createElement('td');
                cell.textContent = item[property];
                row.appendChild(cell);
            });

            // Translate 'topPartiesCurrent' and 'topPartiesPrevious' to party labels
            ['topPartiesCurrent', 'topPartiesPrevious'].forEach(function(property) {
                var cell = document.createElement('td');
                cell.textContent = item[property].map(function(partyKey) {
                    return partyMap[partyKey];
                }).join(', ');
                row.appendChild(cell);
            });

            tbody.appendChild(row);
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
