// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {
    // Function to populate the table with the fetched data
    function populateTable(data) {
        var tableBody = document.getElementById('data-table').getElementsByTagName('tbody')[0];

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
                var responseData = JSON.parse(xhr.responseText);
                populateTable(responseData);
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
