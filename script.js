// Function to populate the table dynamically with data fetched from get_data.php
function populateTable(data) {
    const tableBody = document.querySelector('#data-table tbody');
    
    // Clear existing table data
    tableBody.innerHTML = '';

    // Loop through the data and create rows
    data.forEach((item) => {
        const row = document.createElement('tr');

        // Hardcoded Party data (add more parties if needed)
        const partyCell = document.createElement('td');
        partyCell.textContent = getPartyName(item.key); // Function to get the party name based on the key
        row.appendChild(partyCell);

        // Loop through other columns and create cells
        Object.keys(item.results.previous).forEach((key) => {
            const cell = document.createElement('td');
            cell.textContent = item.results.previous[key];
            row.appendChild(cell);
        });

        Object.keys(item.results.current).forEach((key) => {
            const cell = document.createElement('td');
            cell.textContent = item.results.current[key];
            row.appendChild(cell);
        });

        Object.keys(item.results.diff).forEach((key) => {
            const cell = document.createElement('td');
            cell.textContent = item.results.diff[key];
            row.appendChild(cell);
        });

        // Append the row to the table
        tableBody.appendChild(row);
    });
}

// Function to get the party name based on the key (hardcoded party names)
function getPartyName(key) {
    const parties = {
        0: "VVD",
        1: "PVV",
        2: "CDA",
        // Add more parties here...
    };

    return parties[key] || "Unknown Party";
}

// Function to fetch data from get_data.php
function fetchData() {
    fetch('https://arcovink.synology.me:8444/get_data.php')
        .then((response) => response.json())
        .then((data) => populateTable(data))
        .catch((error) => console.error('Error fetching data:', error));
}

// Fetch data when the page loads
fetchData();
