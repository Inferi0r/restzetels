function loadDataFor2023() {
    // Clear existing content
    document.getElementById('statsTableContainer').innerHTML = '';
    document.getElementById('tableContainer').innerHTML = '';

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
        currentRow.insertCell().textContent = votesData.voters.current;
        currentRow.insertCell().textContent = votesData.turnout.current;
        currentRow.insertCell().textContent = votesData.turnoutCount.current;
        currentRow.insertCell().textContent = votesData.invalid.current;
        currentRow.insertCell().textContent = votesData.blank.current;

        // Row for previous data
        const previousRow = tbody.insertRow();
        previousRow.insertCell().textContent = "17 maart 2021";
        previousRow.insertCell().textContent = votesData.voters.previous;
        previousRow.insertCell().textContent = votesData.turnout.previous;
        previousRow.insertCell().textContent = votesData.turnoutCount.previous;
        previousRow.insertCell().textContent = votesData.invalid.previous;
        previousRow.insertCell().textContent = votesData.blank.previous;

        return table;
    }

    function createMainTable() {
        // Create and populate the main "ANP Stemmen per partij" table
        const table = document.createElement('table');
        const thead = table.createTHead();
        const tbody = table.createTBody();
        const headerRow = thead.insertRow();

        // Define headers for the main table
        const headers = [
            "Key",
            "Label",
            "Results Previous Votes",
            "Results Previous Percentage",
            "Results Previous Seats",
            "Results Current Votes",
            "Results Current Percentage",
            "Results Current Seats",
            "Results Diff Votes",
            "Results Diff Percentage",
            "Results Diff Seats"
        ];

        headers.forEach(headerText => {
            const header = document.createElement('th');
            header.textContent = headerText;
            headerRow.appendChild(header);
        });
    
        votesData.parties.forEach((party) => {
            const row = tbody.insertRow();
    
            const cellsData = [
                party.key,
                keyToLabel.get(party.key),
                Number(party.results.previous.votes).toLocaleString('nl-NL'),
                party.results.previous.percentage,
                Number(party.results.previous.seats).toLocaleString('nl-NL'),
                Number(party.results.current.votes).toLocaleString('nl-NL'),
                party.results.current.percentage,
                Number(party.results.current.seats).toLocaleString('nl-NL'),
                Number(party.results.diff.votes).toLocaleString('nl-NL'),
                party.results.diff.percentage,
                Number(party.results.diff.seats).toLocaleString('nl-NL')
            ];
    
            cellsData.forEach(cellData => {
                const cell = row.insertCell();
                cell.textContent = cellData;
            });
        });
    
        return table;
    }

    function updateFields() {
        // Update additional fields (e.g., last update)
        document.getElementById('lastUpdate').textContent = new Date(votesData.updated * 1000).toLocaleString();
        // ... update other fields if needed ...
    }

    fetch('get_data_2021.php?source=last_update')
        .then(response => response.json())
        .then(data => {
            data.parties.forEach(party => {
                keyToLabel.set(party.key, party.label);
            });

            fetch('get_data_2023.php?source=votes')
                .then(response => response.json())
                .then(data => {
                    votesData = data;
                    const statsTable = createStatsTable();
                    const mainTable = createMainTable();
                    document.getElementById('statsTableContainer').appendChild(statsTable);
                    document.getElementById('tableContainer').appendChild(mainTable);
                    updateFields();
                });
        });
}


