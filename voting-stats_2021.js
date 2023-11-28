function loadDataFor2021() {
    // Clear existing content
    document.getElementById('statsTableContainer').innerHTML = '';

    function showLastUpdatedLocalRegion(data) {
        const localRegion = data.views.find(view => view.type === 0);
        if (localRegion) {
            const timestamp = new Date(localRegion.updated * 1000).toLocaleString();
            document.getElementById('lastUpdatedLocalRegion').textContent = `Laatste gemeente: ${localRegion.label} (${timestamp})`;
        }
    }

    let votesData = {};
    const keyToLabel = new Map();

    function createStatsTable() {
        // Create and populate the "Statistieken" table
        const table = document.createElement('table');
        const thead = table.createTHead();
        const tbody = table.createTBody();
        const headerRow = thead.insertRow();

        // Define headers for the "Statistieken" table
        const headers = ["", "Opkomst"];

        headers.forEach(headerText => {
            const header = document.createElement('th');
            header.textContent = headerText;
            headerRow.appendChild(header);
        });

        // Row for current data
        const currentRow = tbody.insertRow();
        currentRow.insertCell().textContent = "17 maart 2021";
        currentRow.insertCell().textContent = votesData.turnout.current;

        // Row for previous data
        const previousRow = tbody.insertRow();
        previousRow.insertCell().textContent = "15 maart 2017";
        previousRow.insertCell().textContent = votesData.turnout.previous;

        return table;
    }

    function updateFields() {
        // Update additional fields (e.g., last update)
        document.getElementById('lastUpdate').textContent = new Date(votesData.updated * 1000).toLocaleString();
        // ... update other fields if needed ...
    }

    fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2021&source=last_update')
        .then(response => response.json())
        .then(data => {
            // Process the last updated local region
            showLastUpdatedLocalRegion(data);

            data.parties.forEach(party => {
                keyToLabel.set(party.key, party.label);
            });

            // Fetch votes data
            return fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2021&source=votes');
        })
        .then(response => response.json())
        .then(data => {
            votesData = data;
            const statsTable = createStatsTable();
            document.getElementById('statsTableContainer').appendChild(statsTable);
            updateFields();
        });

}


