let keyToLabel = new Map();
let votesData = null;

// Fetch label and votes data
fetch('get_data.php?source=last_update')
    .then(response => response.json())
    .then(data => {
        data.parties.forEach(party => {
            keyToLabel.set(party.key, party.label);
        });

        fetch('get_data.php?source=votes')
            .then(response => response.json())
            .then(data => {
                votesData = data;
                createTable();
            });
    });

function createTable() {
    let tableData = [];
    let totaal_stemmen = votesData.totaal;

    // Calculate values and populate tableData
    votesData.parties.forEach(party => {
        if(party.results.current.seats > 0) {
            let stemgemiddelde_1e_restzetel = party.results.current.votes / (party.results.current.seats + 1);
            let stemgemiddelde_2e_restzetel = party.results.current.votes / (party.results.current.seats + party.restzetels + 1);

            tableData.push({
                'Lijst': party.key,
                'Partij': keyToLabel.get(party.key),
                'Stemgemiddelde voor 1e restzetel': stemgemiddelde_1e_restzetel,
                'Stemgemiddelde voor 2e restzetel': stemgemiddelde_2e_restzetel
            });
        }
    });

    // Sort by 'Stemgemiddelde voor 2e restzetel'
    tableData.sort((a, b) => b['Stemgemiddelde voor 2e restzetel'] - a['Stemgemiddelde voor 2e restzetel']);

    // Populate the HTML table
    let table = document.createElement('table');
    let thead = document.createElement('thead');
    let headerRow = document.createElement('tr');
    ['Lijst', 'Partij', 'Stemgemiddelde voor 1e restzetel', 'Stemgemiddelde voor 2e restzetel'].forEach(headerText => {
        let header = document.createElement('th');
        header.appendChild(document.createTextNode(headerText));
        headerRow.appendChild(header);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    let tbody = document.createElement('tbody');
    tableData.forEach(rowData => {
        let row = document.createElement('tr');
        Object.values(rowData).forEach(cellData => {
            let cell = document.createElement('td');
            cell.appendChild(document.createTextNode(cellData));
            row.appendChild(cell);
        });
        tbody.appendChild(row);
    });
    table.appendChild(tbody);

    document.getElementById('mainContainer').appendChild(table);
}
