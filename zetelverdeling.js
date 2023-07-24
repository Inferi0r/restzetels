const keyToLabel = new Map();
let votesData;

function createTable() {
// Calculate total votes
let totalVotes = 0;
votesData.parties.forEach(party => {
    totalVotes += parseInt(party.results.current.votes);
});

// Calculate kiesdeler
const kiesdeler = Math.floor(totalVotes / 150);

// Create table for zetelverdeling 
const zetelverdelingTable = document.createElement('table');
const zetelverdelingTbody = zetelverdelingTable.createTBody();
const zetelverdelingHeaderRow = zetelverdelingTable.createTHead().insertRow();
const zetelverdelingHeader1 = document.createElement('th');
const zetelverdelingHeader2 = document.createElement('th');
const zetelverdelingHeader3 = document.createElement('th');
zetelverdelingHeader1.textContent = "Lijst";
zetelverdelingHeader2.textContent = "Partij";
zetelverdelingHeader3.textContent = "Volle zetels met kiesdeler";
zetelverdelingHeaderRow.appendChild(zetelverdelingHeader1);
zetelverdelingHeaderRow.appendChild(zetelverdelingHeader2);
zetelverdelingHeaderRow.appendChild(zetelverdelingHeader3);

// Populate table for zetelverdeling with data and calculate total seats
let totalSeats = 0;
votesData.parties.forEach((party, index) => {
    const seats = Math.floor(parseInt(party.results.current.votes) / kiesdeler);
    const row = zetelverdelingTbody.insertRow();
    const listCell = row.insertCell();
    const partyCell = row.insertCell();
    const seatsCell = row.insertCell();
    listCell.textContent = index + 1;
    partyCell.textContent = keyToLabel.get(party.key);
    seatsCell.textContent = seats;
    totalSeats += seats;
});

// Create container for zetelverdeling table
const zetelverdelingContainer = document.createElement('div');
zetelverdelingContainer.style.marginTop = '20px'; // Add margin to top of container
zetelverdelingContainer.appendChild(zetelverdelingTable);

// Create Restzetels table and populate with data
const restzetelsTable = document.createElement('table');
const restzetelsTbody = restzetelsTable.createTBody();
const restzetelsRow = restzetelsTbody.insertRow();
const restzetelsLabelCell = restzetelsRow.insertCell();
const restzetelsCell = restzetelsRow.insertCell();
restzetelsLabelCell.textContent = "Restzetels:";
restzetelsCell.textContent = (150 - totalSeats).toLocaleString('nl-NL');

// Create container for Restzetels table 
const restzetelsContainer = document.createElement('div');
restzetelsContainer.style.marginTop = '20px'; // Add margin to top of container
restzetelsContainer.appendChild(restzetelsTable);

// Create calculation table
const calculationDataTable = document.createElement('table');
const calculationDataTbody = calculationDataTable.createTBody();
const calculationDataHeaderRow = calculationDataTable.createTHead().insertRow();
const calculationDataHeader1 = document.createElement('th');
const calculationDataHeader2 = document.createElement('th');
calculationDataHeader1.textContent = "Lijst";
calculationDataHeader2.textContent = "Partij";
calculationDataHeaderRow.appendChild(calculationDataHeader1);
calculationDataHeaderRow.appendChild(calculationDataHeader2);

// Populate table with calculation data
votesData.parties.forEach((party, index) => {
    const seats = Math.floor(parseInt(party.results.current.votes) / kiesdeler);
    if (seats > 0) {
        const row = calculationDataTbody.insertRow();
        const listCell = row.insertCell();
        const partyCell = row.insertCell();
        listCell.textContent = index + 1;
        partyCell.textContent = keyToLabel.get(party.key);
    }
});

// Create container for calculation data table
const calculationDataContainer = document.createElement('div');
calculationDataContainer.style.marginTop = '20px'; // Add margin to top of container
calculationDataContainer.appendChild(calculationDataTable);

// Append 3 tables to containers
const tableContainer = document.getElementById('tableContainer');
tableContainer.appendChild(zetelverdelingContainer);
tableContainer.appendChild(restzetelsContainer);
tableContainer.appendChild(calculationDataContainer);
}

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