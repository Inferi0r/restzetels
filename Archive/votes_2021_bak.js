function loadDataFor2021() {
    document.getElementById('tableContainer').innerHTML = ''; // Clear existing content
let votesData = {};
const keyToLabel = new Map();

function createTable() {
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const headerRow = thead.insertRow();

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
    document.getElementById('lastUpdate').textContent = new Date(votesData.updated * 1000).toLocaleString();
    document.getElementById('currentTurnout').textContent = votesData.turnout.current;
    document.getElementById('previousTurnout').textContent = votesData.turnout.previous;
}

fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2021&source=last_update')
    .then(response => response.json())
    .then(data => {
        data.parties.forEach(party => {
            keyToLabel.set(party.key, party.label);
        });

        fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2021&source=votes')
            .then(response => response.json())
            .then(data => {
                votesData = data;
                const table = createTable();
                document.getElementById('tableContainer').appendChild(table);
                updateFields();
            });
    });
}