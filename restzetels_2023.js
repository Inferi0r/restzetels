function loadDataFor2023() {
    // Clear existing content
    document.getElementById('seatsSummaryContainer').innerHTML = '';
    document.getElementById('restSeatContainer').innerHTML = '';
    document.getElementById('voteAverageContainer').innerHTML = '';

    // Fetch party labels from partylabels_2023.json
    fetch('partylabels_2023.json')
        .then(response => response.json())
        .then(partyLabelsData => {
            const keyToLabel = new Map(partyLabelsData.map(p => [p.key, p.labelShort])); // Map keys to labelShort

            // Fetch the votes data
            fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=votes')
                .then(response => response.json())
                .then(votesData => {
                    let total_restSeats = createVoteAverageTable(votesData, keyToLabel);
                    createRestSeatsTable(votesData, keyToLabel, total_restSeats);
                    createSeatsSummaryTable(votesData, keyToLabel, total_restSeats);
                });
        });

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
    let listNumber = 1;

    votesData.parties.forEach(party => {
        if(party.fullSeats > 0) {
            let rowData = {
                'Lijst': listNumber++, // Increment list number
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

function calculateVotesShortAndSurplus(votesData) {
    let votesShortData = new Map();
    let surplusVotesData = new Map();

    const total_restSeats = 150 - votesData.parties.reduce((acc, party) => acc + party.fullSeats, 0);
    const total_votes = votesData.parties.reduce((acc, party) => acc + parseInt(party.results.current.votes), 0);
    const votes_per_seat = Math.floor(total_votes / 150);

    //calculate number of average votes required for last rest seat for each party
    //get number of average votes for each party for restSeat after last rest seat received

    const averageVotesForNextSeatPerParty = new Map();
    let maxAverageForLastRestSeat = 0;

    votesData.parties.forEach(party => {

        //if part.fullSeats == 0 then votesShort = votes_per_seat - party.results.current.votes
        if (party.fullSeats === 0) {
            votesShortData.set(party.key, votes_per_seat - party.results.current.votes);
        } else {
            const currentNumberOfTotalSeats = party.fullSeats + Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
            const averageVotesForNextSeat = Math.floor(party.results.current.votes / (currentNumberOfTotalSeats + 1));

            if (party.restSeats.get(total_restSeats) === 1) {
                maxAverageForLastRestSeat = Math.floor(party.results.current.votes / currentNumberOfTotalSeats);
                averageVotesForNextSeatPerParty.set(party.key, maxAverageForLastRestSeat);
            } else {
                averageVotesForNextSeatPerParty.set(party.key, averageVotesForNextSeat);
            }
        }
    });

    averageVotesForNextSeatPerParty.forEach((averageVotesForNextSeat, partyKey) => {
        if (averageVotesForNextSeat < maxAverageForLastRestSeat) {
            const partyData = votesData.parties.find(party => party.key === partyKey);
            const currentNumberOfTotalSeatsWithRestSeat = partyData.fullSeats + Array.from(partyData.restSeats.values()).reduce((a, b) => a + b, 0) + 1;
            const votesNeeded = (maxAverageForLastRestSeat - averageVotesForNextSeat) * currentNumberOfTotalSeatsWithRestSeat;

            const surplusVotes = (currentNumberOfTotalSeatsWithRestSeat * maxAverageForLastRestSeat) - partyData.results.current.votes;

            surplusVotesData.set(partyKey, surplusVotes);
            votesShortData.set(partyKey, votesNeeded);
        }
    });

    return {votesShortData, surplusVotesData};
}


function createSeatsSummaryTable(votesData, keyToLabel) {
    let { votesShortData, surplusVotesData } = calculateVotesShortAndSurplus(votesData);

    let seatsSummaryTableData = [];
    let listNumber = 1;
    let totalFullSeats = 0;
    let totalRestSeats = 0;

    votesData.parties.forEach(party => {
        let partyName = keyToLabel.get(party.key);

        if(partyName !== 'OVERIG') {
            let fullSeats = party.fullSeats;
            let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
            totalFullSeats += fullSeats;
            totalRestSeats += restSeatsCount;

            // let surplusVotes = party.surplusVotes || party.results.current.votes; // Use surplusVotes from party or total votes if not calculated
            let votesShort = votesShortData.get(party.key);
            let surplusVotes = surplusVotesData.get(party.key);

            seatsSummaryTableData.push({
                'Lijst': listNumber++, // Increment list number
                'Partij': partyName,
                'Volle zetels': fullSeats,
                'Rest zetels': restSeatsCount,
                'Totaal zetels': fullSeats + restSeatsCount,
                'Stemmen over': typeof surplusVotes === 'number' ? surplusVotes.toLocaleString('nl-NL') : '-',
                'Stemmen tekort': typeof votesShort === 'number' ? votesShort.toLocaleString('nl-NL') : '-'
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
    if (data.length == 0)
        return;

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
}
loadDataFor2023();