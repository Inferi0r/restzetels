function loadDataFor2021() {
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

   // document.getElementById('tableContainer').appendChild(table);
}

// Fetch label data
fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2021&source=last_update')
    .then(response => response.json())
    .then(data => {
        data.parties.forEach(party => {
            keyToLabel.set(party.key, party.label);
        });

        // Fetch votes data
        fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2021&source=votes')
            .then(response => response.json())
            .then(data => {
                votesData = data;
                createTable();
            });
    });
}

loadDataFor2021();