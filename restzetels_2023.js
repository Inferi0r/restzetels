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

/*
function calculateSurplusVotes(votesData, total_restSeats) {
    let surplusVotesData = new Map();

    votesData.parties.forEach(party => {
        let originalVotes = party.results.current.votes;
        let originalFullSeats = party.fullSeats;
        let originalRestSeats = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
        let originalTotalSeats = originalFullSeats + originalRestSeats;
        
        for (let surplusVotes = 0; surplusVotes <= originalVotes; surplusVotes++) {
            party.results.current.votes = originalVotes - surplusVotes;

            let { votesData: updatedData, total_restSeats: updatedTotalRestSeats } = calculateFullAndRestSeats(votesData);
            updatedData = assignRestSeats({ votesData: updatedData, total_restSeats: updatedTotalRestSeats });

            let updatedFullSeats = party.fullSeats;
            let updatedRestSeats = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
            let updatedTotalSeats = updatedFullSeats + updatedRestSeats;

            if (updatedTotalSeats < originalTotalSeats) {
                surplusVotesData.set(party.key, surplusVotes - 1);
                break;
            }
        }

        // Reset the party's votes to the original number
        party.results.current.votes = originalVotes;
    });

    return surplusVotesData;
}


function calculateVotesShortForNextSeat(votesData, total_restSeats) {
    let votesShortData = new Map();

    votesData.parties.forEach(party => {
        let originalVotes = party.results.current.votes;
        let originalTotalSeats = party.fullSeats + Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);

        let currentVotes = originalVotes;
        let currentTotalSeats = originalTotalSeats;

        while (currentTotalSeats === originalTotalSeats) {
            currentVotes++;
            party.results.current.votes = currentVotes;

            let { votesData: updatedData, total_restSeats: updatedTotalRestSeats } = calculateFullAndRestSeats(votesData);
            updatedData = assignRestSeats({ votesData: updatedData, total_restSeats: updatedTotalRestSeats });

            let partyInUpdatedData = updatedData.parties.find(p => p.key === party.key);
            currentTotalSeats = partyInUpdatedData.fullSeats + Array.from(partyInUpdatedData.restSeats.values()).reduce((a, b) => a + b, 0);
        }

        votesShortData.set(party.key, currentVotes - originalVotes);

        party.results.current.votes = originalVotes;
    });

    return votesShortData;
}
*/


function createSeatsSummaryTable(votesData, keyToLabel, total_restSeats) {
    let seatsSummaryTableData = [];

    let totalFullSeats = 0;
    let totalRestSeats = 0;

   // let surplusVotesData = calculateSurplusVotes(votesData, total_restSeats);
  //  let votesShortData = calculateVotesShortForNextSeat(votesData, total_restSeats);
    

    votesData.parties.forEach(party => {
        let partyName = keyToLabel.get(party.key);

        if(partyName !== 'OVERIG') {
            let fullSeats = party.fullSeats;
            let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
 /*       
            let surplusVotes = surplusVotesData.get(party.key);
            let votesShort = votesShortData.get(party.key);

            // If the party has no seats and surplusVotes is undefined, use their total votes as surplus
            if (fullSeats === 0 && restSeatsCount === 0 && surplusVotes === undefined) {
                surplusVotes = party.results.current.votes;
            }
*/
            totalFullSeats += fullSeats;
            totalRestSeats += restSeatsCount;
    
            seatsSummaryTableData.push({
                'Lijst': party.key + 1,
                'Partij': partyName,
                'Volle zetels': fullSeats,
                'Rest zetels': restSeatsCount,
                'Totaal zetels': fullSeats + restSeatsCount,
      //          'Surplus votes': surplusVotes.toLocaleString('nl-NL'),
       //         'Votes short next seat': votesShort.toLocaleString('nl-NL')
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
