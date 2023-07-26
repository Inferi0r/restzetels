let keyToLabel = new Map();
let votesData = null;
let total_restSeats = null;

fetch('get_data.php?source=last_update')
    .then(response => response.json())
    .then(data => {
        data.parties.forEach(party => keyToLabel.set(party.key, party.label));
        return fetch('get_data.php?source=votes');
    })
    .then(response => response.json())
    .then(data => {
        votesData = data;
        createVoteAverageTable();
        createRestSeatsTable();
    });

function createVoteAverageTable() {
    let tableData = [];

    let totalVotes = 0;
    votesData.parties.forEach(party => {
        totalVotes += parseInt(party.results.current.votes);
    });

    let kiesdeler = Math.floor(totalVotes / 150);

    votesData.parties.forEach(party => {
        let fullSeats = Math.floor(party.results.current.votes / kiesdeler);
        party.fullSeats = fullSeats; 
        party.restSeats = new Map(); 
        if(fullSeats > 0) {
            tableData.push({
                'Lijst': party.key,
                'Partij': keyToLabel.get(party.key)
            });
        }
    });

    let total_fullSeats = votesData.parties.reduce((acc, party) => acc + party.fullSeats, 0);
    total_restSeats = 150 - total_fullSeats;

    for (let i = 1; i <= total_restSeats; i++) {
        let maxVoteAverage = 0;
        let partyWithMaxVoteAverage = null;

        votesData.parties.forEach(party => {
            if(party.fullSeats > 0) {
                let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
                let voteAverage = Math.round(party.results.current.votes / (party.fullSeats + restSeatsCount + 1));
                if(voteAverage > maxVoteAverage) {
                    maxVoteAverage = voteAverage;
                    partyWithMaxVoteAverage = party;
                }
            }
        });

        if (partyWithMaxVoteAverage) {
            partyWithMaxVoteAverage.restSeats.set(i, 1);
        }
    }

    tableData.forEach(rowData => {
        let party = votesData.parties.find(p => p.key === rowData.Lijst);
        for (let i = 1; i <= total_restSeats; i++) {
            let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
            rowData[`Stemgemiddelde voor ${i}e restzetel`] = Math.round(party.results.current.votes / (party.fullSeats + restSeatsCount + 1));
        }
    });

    let table = document.createElement('table');
    let thead = document.createElement('thead');
    let headerRow = document.createElement('tr');
    ['Lijst', 'Partij'].concat(
        Array.from({length: total_restSeats}, (_, i) => `Stemgemiddelde voor ${i+1}e restzetel`)
    ).forEach(headerText => {
        let header = document.createElement('th');
        header.appendChild(document.createTextNode(headerText));
        headerRow.appendChild(header);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    let tbody = document.createElement('tbody');
    tableData.forEach(rowData => {
        let row = document.createElement('tr');
        Object.keys(rowData).forEach(key => {
            if (!key.startsWith('Restzetel')) {
                let cell = document.createElement('td');
                cell.appendChild(document.createTextNode(rowData[key]));
                row.appendChild(cell);
            }
        });
        tbody.appendChild(row);
    });
    table.appendChild(tbody);

    document.getElementById('voteAverageContainer').appendChild(table);
}

function createRestSeatsTable() {
    let restSeatsTableData = [];
    for (let i = 1; i <= total_restSeats; i++) {
        let party = votesData.parties.find(p => p.restSeats.get(i) === 1);
        if (party) {
            restSeatsTableData.push({
                'Restzetel': i,
                'Partij': keyToLabel.get(party.key),
            });
        }
    }

    let table = document.createElement('table');
    let thead = document.createElement('thead');
    let headerRow = document.createElement('tr');
    ['Restzetel', 'Partij'].forEach(headerText => {
        let header = document.createElement('th');
        header.appendChild(document.createTextNode(headerText));
        headerRow.appendChild(header);
    });
    thead.appendChild(headerRow);
    table.appendChild(thead);

    let tbody = document.createElement('tbody');
    restSeatsTableData.forEach(rowData => {
        let row = document.createElement('tr');
        Object.values(rowData).forEach(cellData => {
            let cell = document.createElement('td');
            cell.appendChild(document.createTextNode(cellData));
            row.appendChild(cell);
        });
        tbody.appendChild(row);
    });
    table.appendChild(tbody);

    document.getElementById('restSeatContainer').innerHTML = '';
    document.getElementById('restSeatContainer').appendChild(table);
}
