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
        computeSeats();
        createVoteAverageTable();
        createRestSeatsTable();
    });

function computeSeats() {
    const totalVotes = votesData.parties.reduce((sum, party) => sum + parseInt(party.results.current.votes), 0);
    const kiesdeler = Math.floor(totalVotes / 150);

    votesData.parties.forEach(party => {
        party.fullSeats = Math.floor(party.results.current.votes / kiesdeler);
        party.restSeats = new Map();
    });

    total_restSeats = 150 - votesData.parties.reduce((sum, party) => sum + party.fullSeats, 0);

    for (let i = 1; i <= total_restSeats; i++) {
        let maxVoteAverage = 0;
        let partyWithMaxVoteAverage = null;

        votesData.parties.forEach(party => {
            if (party.fullSeats > 0) {
                let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
                let voteAverage = Math.round(party.results.current.votes / (party.fullSeats + restSeatsCount + 1));

                if (voteAverage > maxVoteAverage) {
                    maxVoteAverage = voteAverage;
                    partyWithMaxVoteAverage = party;
                }
            }
        });

        if (partyWithMaxVoteAverage) {
            partyWithMaxVoteAverage.restSeats.set(i, 1);
        }
    }
}

function createVoteAverageTable() {
    let tableData = votesData.parties.filter(party => party.fullSeats > 0).map(party => {
        let rowData = {
            'Lijst': party.key,
            'Partij': keyToLabel.get(party.key)
        };
        for (let i = 1; i <= total_restSeats; i++) {
            let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
            rowData[`Stemgemiddelde ${i}e restzetel`] = Math.round(party.results.current.votes / (party.fullSeats + restSeatsCount));
        }
        return rowData;
    });

    let headers = ['Lijst', 'Partij', ...Array.from({length: total_restSeats}, (_, i) => `Stemgemiddelde ${i+1}e restzetel`)];
    let voteAverageTable = createHTMLTable(headers, tableData);
    document.getElementById('voteAverageContainer').appendChild(voteAverageTable);
}

function createRestSeatsTable() {
    let restSeatsTableData = Array.from({length: total_restSeats}, (_, i) => {
        let party = votesData.parties.find(p => p.restSeats.get(i+1) === 1);
        return party ? { 'Restzetel': i+1, 'Partij': keyToLabel.get(party.key) } : {};
    });

    let headers = ['Restzetel', 'Partij'];
    let restSeatTable = createHTMLTable(headers, restSeatsTableData);
    document.getElementById('restSeatContainer').innerHTML = '';
    document.getElementById('restSeatContainer').appendChild(restSeatTable);
}

function createHTMLTable(headers, data) {
    let table = document.createElement('table');
    let thead = document.createElement('thead');
    let headerRow = document.createElement('tr');

    headers.forEach(headerText => {
        let header = document.createElement('th');
        header.appendChild(document.createTextNode(headerText));
        headerRow.appendChild(header);
    });

    thead.appendChild(headerRow);
    table.appendChild(thead);

    let tbody = document.createElement('tbody');
    data.forEach(rowData => {
        let row = document.createElement('tr');
        Object.entries(rowData).forEach(([key, value]) => {
            let cell = document.createElement('td');
            cell.appendChild(document.createTextNode(value));
            row.appendChild(cell);
        });
        tbody.appendChild(row);
    });

    table.appendChild(tbody);
    return table;
}
