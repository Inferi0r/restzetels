function loadDataFor2023() {
    // Clear existing content
    document.getElementById('tableContainer').innerHTML = '';
const keyToLabel = new Map();
let votesData;

function createTable() {
    // Create table
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const headerRow = thead.insertRow();

    // Create headers
    const header1 = document.createElement('th');
    const header2 = document.createElement('th');
    const header3 = document.createElement('th');
    header1.textContent = "Lijst";
    header2.textContent = "Partij";
    header3.textContent = "Stemcijfers ANP";
    headerRow.appendChild(header1);
    headerRow.appendChild(header2);
    headerRow.appendChild(header3);

    // Populate table with data
    let totalVotes = 0;
    votesData.parties.forEach((party, index) => {
        const row = tbody.insertRow();
        const listCell = row.insertCell();
        const partyCell = row.insertCell();
        const votesCell = row.insertCell();
        listCell.textContent = index + 1;
        partyCell.textContent = keyToLabel.get(party.key);
        votesCell.textContent = parseInt(party.results.current.votes).toLocaleString('nl-NL');
        totalVotes += parseInt(party.results.current.votes);
    });

    // Create empty row
    const emptyRow = tbody.insertRow();
    const emptyCell = emptyRow.insertCell();
    emptyCell.colSpan = 3;
    emptyCell.innerHTML = "&nbsp;";

    // Create total row
    const totalRow = tbody.insertRow();
    const totalLabelCell = totalRow.insertCell();
    const totalCell = totalRow.insertCell();
    totalLabelCell.colSpan = 2;
    totalLabelCell.textContent = "Totaal aantal geldige stemmen op lijsten:";
    totalCell.textContent = totalVotes.toLocaleString('nl-NL');

    // Create Kiesdeler row
    const kiesdelerRow = tbody.insertRow();
    const kiesdelerLabelCell = kiesdelerRow.insertCell();
    const kiesdelerCell = kiesdelerRow.insertCell();
    kiesdelerLabelCell.colSpan = 2;
    kiesdelerLabelCell.textContent = "Kiesdeler:";
    kiesdelerCell.textContent = Math.floor(totalVotes / 150).toLocaleString('nl-NL');

    document.getElementById('tableContainer').appendChild(table);
}

    // Fetch label data from partylabels_2023.json
    fetch('partylabels_2023.json')
        .then(response => response.json())
        .then(data => {
            data.forEach(party => {
                keyToLabel.set(party.key, party.labelLong); // Use labelLong here
            });

            // Fetch votes data
            fetch('get_data_2023.php?source=votes')
                .then(response => response.json())
                .then(data => {
                    votesData = data;
                    createTable();
                });
        });
}