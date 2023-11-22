function loadDataFor2023() {
    // Clear existing content
    document.getElementById('seatsSummaryContainer').innerHTML = '';
    document.getElementById('restSeatContainer').innerHTML = '';
    document.getElementById('voteAverageContainer').innerHTML = '';

function calculateFullAndRestSeats(votesData) {
    let totalVotes = 0;
    votesData.parties.forEach(party => {
        totalVotes += parseInt(party.results.current.votes);
    });

    let kiesdeler = Math.floor(totalVotes / 150);

    votesData.parties.forEach(party => {
        let fullSeats = Math.floor(party.results.current.votes / kiesdeler);
        party.fullSeats = fullSeats; 
        party.restSeats = new Map(); 
    });

    let total_fullSeats = votesData.parties.reduce((acc, party) => acc + party.fullSeats, 0);
    let total_restSeats = 150 - total_fullSeats;

    return { votesData, total_restSeats };
}

function assignRestSeats({ votesData, total_restSeats }) {
    for (let i = 1; i <= total_restSeats; i++) {
        let maxVoteAverage = 0;
        let partyWithMaxVoteAverage = null;

        votesData.parties.forEach(party => {
            if(party.fullSeats > 0) {
                let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
                
                if (party.key === 3) {
                console.log(`Rest Seats Count for party key 3: ${restSeatsCount}`);
                }
                
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

    return votesData;
}

function createVoteAverageTableData(votesData, keyToLabel, total_restSeats) {
    let tableData = [];

    votesData.parties.forEach(party => {
        if(party.fullSeats > 0) {
            let rowData = {
                'Lijst': party.key + 1,
                'Partij': keyToLabel.get(party.key)
            };

            for (let i = 1; i <= total_restSeats; i++) {
                let restSeatsCount = Array.from(party.restSeats.keys())
                    .filter(key => key < i)
                    .reduce((a, key) => a + party.restSeats.get(key), 0);

                rowData[`${i}e`] = Math.round(party.results.current.votes / (party.fullSeats + restSeatsCount + 1));
            }

            tableData.push(rowData);
        }
    });

    return tableData;
}

function createVoteAverageTable(votesData, keyToLabel) {
    let { votesData: updatedData, total_restSeats } = calculateFullAndRestSeats(votesData);
    updatedData = assignRestSeats({ votesData: updatedData, total_restSeats });
    let tableData = createVoteAverageTableData(updatedData, keyToLabel, total_restSeats);
    // Find the highest value in each column
    let maxValues = {};
    for (let i = 1; i <= total_restSeats; i++) {
        maxValues[`${i}e`] = Math.max(...tableData.map(row => row[`${i}e`]));
    }
    // Add a class to the cells with the highest value
    tableData.forEach(rowData => {
        for (let i = 1; i <= total_restSeats; i++) {
            if (rowData[`${i}e`] === maxValues[`${i}e`]) {
                rowData[`${i}e`] = `<div class='highest-value'>${rowData[`${i}e`]}</div>`;
            }
        }
    });

    renderTable('voteAverageContainer', tableData, total_restSeats);
    return total_restSeats;
}

function createRestSeatsTable(votesData, keyToLabel, total_restSeats) {
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

    renderTable('restSeatContainer', restSeatsTableData);
}

function createSeatsSummaryTable(votesData, keyToLabel, total_restSeats) {
    let totalVotes = votesData.parties.reduce((acc, party) => acc + parseInt(party.results.current.votes), 0);
    let kiesdeler = Math.floor(totalVotes / 150);
    let finalRestSeatAverage = 0;
    let partyWithFinalRestSeat;

    // Find the party with the final rest seat
    votesData.parties.forEach(party => {
        let restSeatCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
        if (party.restSeats.get(total_restSeats)) {
            finalRestSeatAverage = Math.round(party.results.current.votes / (party.fullSeats + restSeatCount + 1));
            partyWithFinalRestSeat = party;
        }
    });

    // Calculate surplus and shortage for each party
    votesData.parties.forEach(party => {
        if (party.fullSeats > 0) {
            let surplusVotes = party.results.current.votes - ((party.fullSeats + party.restSeats.size) * finalRestSeatAverage);
            party.surplusVotes = surplusVotes >= 0 ? surplusVotes : 0;
            party.shortVotes = 0; // Full seat parties do not have short votes for next seat
        } else {
            party.surplusVotes = party.results.current.votes; // All votes are surplus for parties without full seats
            party.shortVotes = kiesdeler - party.results.current.votes; // Short votes for the first seat
        }
    });
}

function createSeatsSummaryTable(votesData, keyToLabel, total_restSeats) {
    // Calculate totalVotes within the function
    let totalVotes = votesData.parties.reduce((acc, party) => acc + parseInt(party.results.current.votes), 0);
    let kiesdeler = Math.floor(totalVotes / 150);

    let seatsSummaryTableData = [];
    let totalFullSeats = 0;
    let totalRestSeats = 0;

    votesData.parties.forEach(party => {
        let partyName = keyToLabel.get(party.key);

        if(partyName !== 'OVERIG') {
            let fullSeats = party.fullSeats;
            let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
            totalFullSeats += fullSeats;
            totalRestSeats += restSeatsCount;

            let surplusVotes = party.surplusVotes || party.results.current.votes; // Use surplusVotes from party or total votes if not calculated
            let votesShort = (party.shortVotes !== undefined) ? party.shortVotes : (fullSeats > 0 ? 'N/A' : kiesdeler - party.results.current.votes); // Use shortVotes from party or calculate if not present

            seatsSummaryTableData.push({
                'Lijst': party.key + 1,
                'Partij': partyName,
                'Volle zetels': fullSeats,
                'Rest zetels': restSeatsCount,
                'Totaal zetels': fullSeats + restSeatsCount,
                'Surplus votes': surplusVotes.toLocaleString('nl-NL'),
                'Votes short next seat': typeof votesShort === 'number' ? votesShort.toLocaleString('nl-NL') : votesShort
            });
        }
    });

    seatsSummaryTableData.push({
        'Lijst': '',
        'Partij': 'Totaal',
        'Volle zetels': totalFullSeats,
        'Rest zetels': totalRestSeats,
        'Totaal zetels': totalFullSeats + totalRestSeats
    });

    renderTable('seatsSummaryContainer', seatsSummaryTableData);
}



function renderTable(containerId, data) {
    const columns = Object.keys(data[0]);
    const header = columns.map(colName => `<th>${colName}</th>`).join("");
    const rows = data.map(rowData => {
        const cells = Object.values(rowData).map(cellData => `<td>${cellData}</td>`).join("");
        return `<tr>${cells}</tr>`;
    }).join("");

    const table = `
        <table>
            <thead>
                <tr>${header}</tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    document.getElementById(containerId).innerHTML = table;
}

fetch('get_data_2021.php?source=last_update')
    .then(response => response.json())
    .then(data => fetch('get_data_2021.php?source=votes')
        .then(response => response.json())
        .then(votesData => {
            let keyToLabel = new Map();
            data.parties.forEach(party => keyToLabel.set(party.key, party.label));
            
            let total_restSeats = createVoteAverageTable(votesData, keyToLabel);
            createRestSeatsTable(votesData, keyToLabel, total_restSeats);
            createSeatsSummaryTable(votesData, keyToLabel);
        }));
}        
