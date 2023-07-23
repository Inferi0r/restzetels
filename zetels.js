const keyToLabel = new Map();
let votesData;

function createTable() {
    // Create table
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const headerRow = thead.insertRow();

    // Create header
    const header1 = document.createElement('th');
    const header2 = document.createElement('th');
    header1.textContent = "Partij";
    header2.textContent = "Stemmen";
    headerRow.appendChild(header1);
    headerRow.appendChild(header2);

    // Populate table with data
    votesData.parties.forEach((party) => {
        const row = tbody.insertRow();
        const partyCell = row.insertCell();
        const votesCell = row.insertCell();
        partyCell.textContent = keyToLabel.get(party.key);
        votesCell.textContent = party.results.current.votes;
    });

    document.getElementById('tableContainer').appendChild(table);
}

// Fetch label data
fetch('get_data.php?source=last_update')
    .then(response => response.json())
    .then(data => {
        data.parties.forEach(party => {
            keyToLabel.set(party.key, party.label);
        });

        // Fetch votes data
        fetch('get_data.php?source=votes')
            .then(response => response.json())
            .then(data => {
                votesData = data;
                createTable();
            });
    });
