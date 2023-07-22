// AJAX function to fetch data from the server and update the table
function updateTable() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', 'get_data.php', true);

    xhr.onreadystatechange = function() {
        if (xhr.readyState === 4 && xhr.status === 200) {
            var data = JSON.parse(xhr.responseText);
            var tableBody = document.querySelector('#results-table tbody');
            tableBody.innerHTML = '';

            data.forEach(function(row) {
                var tableRow = document.createElement('tr');
                Object.values(row).forEach(function(cell) {
                    var tableCell = document.createElement('td');
                    tableCell.textContent = cell;
                    tableRow.appendChild(tableCell);
                });
                tableBody.appendChild(tableRow);
            });
        }
    };

    xhr.send();
}

// Update the table every 1 minute (60000 milliseconds)
setInterval(updateTable, 60000);

// Initial table update on page load
updateTable();
