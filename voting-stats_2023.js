function loadDataFor2023() {

    // Clear existing content
    document.getElementById('statsTableContainer').innerHTML = '';

    function updateFields() {
        // Update additional fields (e.g., last update)
        document.getElementById('lastUpdate').textContent = new Date(votesData.updated * 1000).toLocaleString();
        // ... update other fields if needed ...
    }

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
        const headers = ["", "Stemgerechtigden", "Opkomst", "Totale stemmen", "Ongeldige stemmen", "Blanco stemmen"];

        headers.forEach(headerText => {
            const header = document.createElement('th');
            header.textContent = headerText;
            headerRow.appendChild(header);
        });

        // Row for current data
        const currentRow = tbody.insertRow();
        currentRow.insertCell().textContent = "22 november 2023";
        currentRow.insertCell().textContent = Number(votesData.voters.current).toLocaleString('nl-NL');
        currentRow.insertCell().textContent = votesData.turnout.current;
        currentRow.insertCell().textContent = Number(votesData.turnoutCount.current).toLocaleString('nl-NL');
        currentRow.insertCell().textContent = Number(votesData.invalid.current).toLocaleString('nl-NL');
        currentRow.insertCell().textContent = Number(votesData.blank.current).toLocaleString('nl-NL');

        // Row for previous data
        const previousRow = tbody.insertRow();
        previousRow.insertCell().textContent = "17 maart 2021";
        previousRow.insertCell().textContent = Number(votesData.voters.previous).toLocaleString('nl-NL');
        previousRow.insertCell().textContent = votesData.turnout.previous;
        previousRow.insertCell().textContent = Number(votesData.turnoutCount.previous).toLocaleString('nl-NL');
        previousRow.insertCell().textContent = Number(votesData.invalid.previous).toLocaleString('nl-NL');
        previousRow.insertCell().textContent = Number(votesData.blank.previous).toLocaleString('nl-NL');

        return table;
    }

    fetch('partylabels_2023.json')
        .then(response => response.json())
        .then(data => {
            data.forEach(party => {
                keyToLabel.set(party.key, party.labelShort); // Use labelLong here
            });

            // Fetch votes data
            fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=votes')
                .then(response => response.json())
                .then(data => {
                    votesData = data;
                    const statsTable = createStatsTable();
                    document.getElementById('statsTableContainer').appendChild(statsTable);
                    updateFields();
                });

        });

    // Fetch last update data
    fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=last_update')
        .then(response => response.json())
        .then(lastUpdateData => {
            showLastUpdatedLocalRegion(lastUpdateData);
        });
}