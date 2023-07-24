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
const zetelverdelingHeader4 = document.createElement('th');
zetelverdelingHeader1.textContent = "Lijst";
zetelverdelingHeader2.textContent = "Partij";
zetelverdelingHeader3.textContent = "Volle zetels met kiesdeler";
zetelverdelingHeader4.textContent = "Restzetels";
zetelverdelingHeaderRow.appendChild(zetelverdelingHeader1);
zetelverdelingHeaderRow.appendChild(zetelverdelingHeader2);
zetelverdelingHeaderRow.appendChild(zetelverdelingHeader3);
zetelverdelingHeaderRow.appendChild(zetelverdelingHeader4);

// Store restzetels data for later use
let restzetelsMap = new Map();
let highestRestzetelsIndex = null;
let highestRestzetelsValue = 0;

// Populate table for zetelverdeling with data and calculate total seats
let totalSeats = 0;  // Add this line if you need to calculate totalSeats

votesData.parties.forEach((party, index) => {
    const votes = parseInt(party.results.current.votes);
    const seats = Math.floor(votes / kiesdeler);
    const average1 = Math.round(votes / (seats + 1));
    restzetelsMap.set(index, average1);

    if (average1 > highestRestzetelsValue) {
        highestRestzetelsValue = average1;
        highestRestzetelsIndex = index;
    }

    const row = zetelverdelingTbody.insertRow();
    const listCell = row.insertCell();
    const partyCell = row.insertCell();
    const seatsCell = row.insertCell();
    const restzetelsCell = row.insertCell();
    listCell.textContent = index + 1;
    partyCell.textContent = keyToLabel.get(party.key);
    seatsCell.textContent = seats;
    totalSeats += seats;  // Remove this line if you don't need to calculate totalSeats
});

votesData.parties.forEach((party, index) => {
    const row = zetelverdelingTbody.rows[index];
    const restzetelsCell = row.cells[3];  // Assuming restzetels is the 4th column
    restzetelsCell.textContent = index === highestRestzetelsIndex ? 1 : 0;
});


// Create container for zetelverdeling table
const zetelverdelingContainer = document.createElement('div');
zetelverdelingContainer.style.marginTop = '20px'; // Add margin to top of container
zetelverdelingContainer.appendChild(zetelverdelingTable);

// Create Restzetels total table and populate with data
const restzetelstotalTable = document.createElement('table');
const restzetelstotalTbody = restzetelstotalTable.createTBody();
const restzetelstotalRow = restzetelstotalTbody.insertRow();
const restzetelstotalLabelCell = restzetelstotalRow.insertCell();
const restzetelstotalCell = restzetelstotalRow.insertCell();
restzetelstotalLabelCell.textContent = "Restzetels:";
restzetelstotalCell.textContent = (150 - totalSeats).toLocaleString('nl-NL');

// Create container for Restzetels total table 
const restzetelstotalContainer = document.createElement('div');
restzetelstotalContainer.style.marginTop = '20px'; // Add margin to top of container
restzetelstotalContainer.appendChild(restzetelstotalTable);

// Create table for calculation data
const calculationDataTable = document.createElement('table');
const calculationDataTbody = calculationDataTable.createTBody();
const calculationDataHeaderRow = calculationDataTable.createTHead().insertRow();
const calculationDataHeader1 = document.createElement('th');
const calculationDataHeader2 = document.createElement('th');
const calculationDataHeader3 = document.createElement('th');
const calculationDataHeader4 = document.createElement('th'); // Add new header cell
calculationDataHeader1.textContent = "Lijst";
calculationDataHeader2.textContent = "Partij";
calculationDataHeader3.textContent = "Stemgemiddelde 1e restzetel";
calculationDataHeader4.textContent = "Stemgemiddelde 2e restzetel"; // Add text to new header cell
calculationDataHeaderRow.appendChild(calculationDataHeader1);
calculationDataHeaderRow.appendChild(calculationDataHeader2);
calculationDataHeaderRow.appendChild(calculationDataHeader3);
calculationDataHeaderRow.appendChild(calculationDataHeader4); // Add new header cell to header row

// Populate table with calculation data
votesData.parties.forEach((party, index) => {
    const votes = parseInt(party.results.current.votes);
    const seats = Math.floor(votes / kiesdeler);
    if (seats > 0) {
        const row = calculationDataTbody.insertRow();
        const listCell = row.insertCell();
        const partyCell = row.insertCell();
        const average1Cell = row.insertCell(); 
        const average2Cell = row.insertCell(); // Add new table cell
        listCell.textContent = index + 1;
        partyCell.textContent = keyToLabel.get(party.key);
        average1Cell.textContent = Math.round(votes / (seats + 1)).toLocaleString('nl-NL');
        average2Cell.textContent = Math.round(votes / (seats + 1)).toLocaleString('nl-NL'); // Add calculated value to new table cell
    }
});
  
// Create container for calculation data table
const calculationDataContainer = document.createElement('div');
calculationDataContainer.style.marginTop = '20px'; // Add margin to top of container
calculationDataContainer.appendChild(calculationDataTable);

// Append 3 tables to 3 containers
const tableContainer = document.getElementById('tableContainer');
tableContainer.appendChild(zetelverdelingContainer);
tableContainer.appendChild(restzetelstotalContainer);
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