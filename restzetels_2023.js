function loadDataFor2023() {
    // Clear existing content
    document.getElementById('seatsSummaryContainer').innerHTML = '';
    document.getElementById('restSeatContainer').innerHTML = '';
    document.getElementById('voteAverageContainer').innerHTML = '';
    document.getElementById('latestRestSeatImpactContainer').innerHTML = '';
    document.getElementById('latestUpdateFromNos').textContent = '';
    // document.getElementById('latestUpdateFromANP').textContent = '';

    // Global variable to hold party labels
    let globalPartyLabelsData = [];
    let keyToLabel = new Map(); // Declare keyToLabel here

    // Fetch party labels from partylabels_2023.json
    fetch('partylabels_2023.json')
        .then(response => response.json())
        .then(partyLabelsData => {
            globalPartyLabelsData = partyLabelsData; // Store data globally
            keyToLabel = new Map(partyLabelsData.map(p => [p.key, p.labelShort])); // Initialize keyToLabel here

            // Fetch both ANP and Kiesraad vote data
            return Promise.all([
                fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=votes').then(res => res.json()),
                fetch('votes-kiesraad_2023.js').then(res => res.json())
            ]);
        })
        .then(([anpData, kiesraadData]) => {
            // Calculate total votes for each source
            const totalANPVotes = anpData.parties.reduce((total, party) => total + parseInt(party.results.current.votes), 0);
            const totalKiesraadVotes = kiesraadData.reduce((total, item) => total + item.votes, 0);

            // Choose the source with the higher total votes and map Kiesraad data if necessary
            let votesData = totalKiesraadVotes > totalANPVotes ? mapKiesraadDataToANPFormat(kiesraadData, globalPartyLabelsData) : anpData;

            let total_restSeats = createVoteAverageTable(votesData, keyToLabel);
            createRestSeatsTable(votesData, keyToLabel, total_restSeats);
            createSeatsSummaryTable(votesData, keyToLabel, total_restSeats);
            showLatestRestSeatImpact(votesData, keyToLabel);
        });

    // Fetch last update data
    fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=last_update')
        .then(response => response.json())
        .then(lastUpdateData => {
            // showLatestUpdateFromANP(lastUpdateData);
            showCompletedRegionsCount(lastUpdateData);
        });

    // Fetch NOS data
    fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=nos')
        .then(response => response.json())
        .then(nosData => {
            showLatestUpdateFromNos(nosData);
        });


    function showCompletedRegionsCount(lastUpdateData) {
        const totalRegionsData = lastUpdateData.views.find(view => view.type === 2); // Assuming type 2 is the correct type for total regions data
        if (totalRegionsData && totalRegionsData.countStatus) {
            const completed = totalRegionsData.countStatus.completed;
            const total = totalRegionsData.countStatus.total;
    
            if (completed === null && total === null) {
                // Both completed and total are null, so display "Alle kiesregio's compleet"
                document.getElementById('completedRegionsCount').innerHTML = "Alle kiesregio's compleet";
            } else {
                // Display the count of completed regions out of total
                document.getElementById('completedRegionsCount').innerHTML = `<b>${completed}</b> / <b>${total}</b> kiesregio's compleet`;
            }
        }
    }
    
    
/*
function showLatestUpdateFromANP(data) {
    const localRegion = data.views.find(view => view.type === 0);
    if (localRegion) {
        const timestamp = new Date(localRegion.updated * 1000).toLocaleString();
        document.getElementById('latestUpdateFromANP').textContent = `Laatste update: ${timestamp} (${localRegion.label})`;
    }
}
*/

function mapKiesraadDataToANPFormat(kiesraadData, globalPartyLabelsData) {
    return {
        parties: kiesraadData.map(item => {
            // Find the party in globalPartyLabelsData with the corresponding index
            let party = globalPartyLabelsData[item.lijstnummer - 1]; // "-1" because array indexes start at 0

            return {
                key: party.key, // Use the key from partylabels_2023.json
                results: {
                    current: {
                        votes: item.votes
                        // Add other necessary properties if needed
                    }
                }
            };
        })
    };
}


function showLatestUpdateFromNos(nosData) {
    if (nosData && nosData.gemeentes && nosData.gemeentes.length > 0) {
        const sortedGemeentes = nosData.gemeentes.sort((a, b) => 
            new Date(b.publicatie_datum_tijd) - new Date(a.publicatie_datum_tijd)
        );

        const latestEntry = sortedGemeentes[0];
        const timestamp = new Date(latestEntry.publicatie_datum_tijd).toLocaleString();
        const localRegionName = latestEntry.gemeente.naam;
        const status = latestEntry.status; // Extracting the status

        document.getElementById('latestUpdateFromNos').textContent = `Laatste update NOS: ${timestamp} uit ${localRegionName} (${status})`;
    }
}


function gcd(a, b) {
    return b ? gcd(b, a % b) : a;
}

// Function for converting a decimal to a fraction with a maximum denominator of 2 digits
function decimalToFraction(decimal) {
    const tolerance = 1E-6; // Tolerance for floating point comparison
    let numerator = decimal;
    let denominator = 1;
    let simplified = false;

    // Increase the denominator, attempting to simplify the fraction
    while (!simplified && denominator < 100) {
        denominator++;
        numerator = decimal * denominator;

        // Check if the numerator is nearly an integer
        if (Math.abs(Math.round(numerator) - numerator) < tolerance) {
            simplified = true;
            numerator = Math.round(numerator);
        }
    }

    // Simplify the fraction
    const divisor = gcd(numerator, denominator);
    numerator /= divisor;
    denominator /= divisor;

    // If denominator is still 100, try reducing it one step further
    if (denominator === 100) {
        numerator *= 0.99;
        denominator *= 0.99;
        const newDivisor = gcd(numerator, denominator);
        numerator /= newDivisor;
        denominator /= newDivisor;
    }

    return `${Math.round(numerator)}/${Math.round(denominator)}`;
}





function createFractionHTML(numerator, denominator) {
    return `
        <div style="display: inline-block; text-align: center; font-size: smaller;">
            <span style="display: block; border-bottom: 1px solid; padding-bottom: 2px;">${numerator}</span>
            <span style="display: block; padding-top: 2px;">${denominator}</span>
        </div>`;
}

function extractFraction(htmlString) {
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = htmlString;
    const numerator = tempDiv.querySelector('span:first-child').textContent;
    const denominator = tempDiv.querySelector('span:last-child').textContent;
    return numerator / denominator;
}

function calculateFullAndRestSeats(votesData) {
    let totalVotes = 0;
    votesData.parties.forEach(party => {
        totalVotes += parseInt(party.results.current.votes);
    });

    let kiesdeler = totalVotes / 150;

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
        if (party.fullSeats > 0) {
            let rowData = {
                'Partij': keyToLabel.get(party.key)
            };
            for (let i = 1; i <= total_restSeats; i++) {
                let restSeatsCount = Array.from(party.restSeats.keys())
                    .filter(key => key < i)
                    .reduce((a, key) => a + party.restSeats.get(key), 0);
                let voteAverage = party.results.current.votes / (party.fullSeats + restSeatsCount + 1);
                let fraction = decimalToFraction(voteAverage);
                rowData[`${i}e`] = createFractionHTML(...fraction.split('/'));
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
        maxValues[`${i}e`] = Math.max(...tableData.map(row => extractFraction(row[`${i}e`])));
    }

    tableData.forEach(rowData => {
        for (let i = 1; i <= total_restSeats; i++) {
            let voteAverageDecimal = extractFraction(rowData[`${i}e`]);
            let fraction = voteAverageDecimal % 1 > 0 ? decimalToFraction(voteAverageDecimal % 1) : '';

            let [numerator, denominator] = fraction.split('/');
            let fractionHTML = createFractionHTML(numerator, denominator);

            rowData[`${i}e`] = `
                <div class="averagevotetable-cell">
                    <span style="margin-right: 5px;">${Math.floor(voteAverageDecimal)}</span>
                    ${fraction ? fractionHTML : ''}
                </div>`;

            // Check if the current cell should be highlighted
            if (voteAverageDecimal === maxValues[`${i}e`]) {
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
    const votes_per_seat = total_votes / 150;

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
            const averageVotesForNextSeat = party.results.current.votes / (currentNumberOfTotalSeats + 1);

            if (party.restSeats.get(total_restSeats) === 1) {
                maxAverageForLastRestSeat = party.results.current.votes / currentNumberOfTotalSeats;
                averageVotesForNextSeatPerParty.set(party.key, maxAverageForLastRestSeat);
            } else {
                averageVotesForNextSeatPerParty.set(party.key, averageVotesForNextSeat);
            }
        }
    });

    averageVotesForNextSeatPerParty.forEach((averageVotesForNextSeat, partyKey) => {
        const partyData = votesData.parties.find(party => party.key === partyKey);
        const currentNumberOfTotalSeatsWithRestSeat = partyData.fullSeats + Array.from(partyData.restSeats.values()).reduce((a, b) => a + b, 0);

        if (averageVotesForNextSeat < maxAverageForLastRestSeat) {

            const votesNeeded = (maxAverageForLastRestSeat - averageVotesForNextSeat) * (currentNumberOfTotalSeatsWithRestSeat + 1);
            const surplusVotes = partyData.results.current.votes - (currentNumberOfTotalSeatsWithRestSeat * maxAverageForLastRestSeat);

            surplusVotesData.set(partyKey, surplusVotes);
            votesShortData.set(partyKey, votesNeeded);
        } else {

            //get second highest value from averageVotesForNextSeatPerParty
            const secondHighestAverageVotesForNextSeat = Array.from(averageVotesForNextSeatPerParty.values()).sort((a, b) => b - a)[1];
            const averageVotesForCurrentLastSeat = (partyData.results.current.votes / currentNumberOfTotalSeatsWithRestSeat);

            const surplusVotes = Math.floor((averageVotesForCurrentLastSeat - secondHighestAverageVotesForNextSeat) * currentNumberOfTotalSeatsWithRestSeat);
            const votesNeed = Math.ceil((secondHighestAverageVotesForNextSeat + 1) * (currentNumberOfTotalSeatsWithRestSeat + 1)) - partyData.results.current.votes;

            surplusVotesData.set(partyKey, surplusVotes);
            votesShortData.set(partyKey, votesNeed);
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

    let totalVotes = votesData.totalVotes || votesData.parties.reduce((acc, party) => acc + parseInt(party.results.current.votes), 0);
    const kiesdeler = totalVotes / 150;

    votesData.parties.forEach(party => {
        const partyLabelData = globalPartyLabelsData.find(p => p.key === party.key);
        let partyName = partyLabelData ? partyLabelData.labelLong : "Onbekend";
    
        if (!partyName.toUpperCase().includes('OVERIG')) {
            let fullSeats = party.fullSeats;
            let restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
            totalFullSeats += fullSeats;
            totalRestSeats += restSeatsCount;
    
            let surplusVotes = fullSeats === 0 && restSeatsCount === 0 ? parseInt(party.results.current.votes) : Math.ceil(surplusVotesData.get(party.key));
            let votesShort = Math.ceil(votesShortData.get(party.key));
    
            let rowData = {
                'Lijst': listNumber++,
                'Partij': partyName,
                'Volle zetels': fullSeats,
                'Rest zetels': restSeatsCount,
                'Totaal zetels': fullSeats + restSeatsCount,
                'Stemmen over': typeof surplusVotes === 'number' && !isNaN(surplusVotes) ? surplusVotes.toLocaleString('nl-NL') : '-',
                'Stemmen tekort': typeof votesShort === 'number' ? votesShort.toLocaleString('nl-NL') : '-'
            };
    
            seatsSummaryTableData.push(rowData);
        }
    });

    // Add the total row without the first cell
    seatsSummaryTableData.push({
        'Lijst': '',
        'Partij': 'Totaal',
        'Volle zetels': totalFullSeats,
        'Rest zetels': totalRestSeats,
        'Totaal zetels': totalFullSeats + totalRestSeats
    });

    // Set the initial sort states
    sortStates['Totaal zetels'] = 'desc';
    sortStates['Stemmen tekort'] = 'asc';

    // Custom function to sort based on two columns
    function customSort(data) {
        return data.slice(0, -1).sort((a, b) => {
            // Convert formatted numbers back to integers for comparison
            let aVotesShort = parseInt(a['Stemmen tekort'].replace(/\./g, ''), 10);
            let bVotesShort = parseInt(b['Stemmen tekort'].replace(/\./g, ''), 10);

            // Primary sort on 'Totaal zetels'
            if (a['Totaal zetels'] > b['Totaal zetels']) return -1;
            if (a['Totaal zetels'] < b['Totaal zetels']) return 1;

            // Secondary sort on 'Stemmen tekort'
            if (aVotesShort < bVotesShort) return -1;
            if (aVotesShort > bVotesShort) return 1;

            return 0;
        }).concat(data[data.length - 1]); // Re-add the summary row at the end
    }

    // Apply the custom sorting and render the table
    seatsSummaryTableData = customSort(seatsSummaryTableData);
    renderTable('seatsSummaryContainer', seatsSummaryTableData);
}





function showLatestRestSeatImpact(votesData, keyToLabel) {
    // Find the party receiving the latest rest seat
    let latestRestSeatParty = null;
    let highestRestSeatNumber = 0;
    votesData.parties.forEach(party => {
        party.restSeats.forEach((value, key) => {
            if (key > highestRestSeatNumber) {
                highestRestSeatNumber = key;
                latestRestSeatParty = party;
            }
        });
    });
    let partyLastrestSeat = keyToLabel.get(latestRestSeatParty.key);

    // Find the party with the lowest number in the "Stemmen tekort" column
    let { votesShortData } = calculateVotesShortAndSurplus(votesData);
    let lowestVotesShort = Number.MAX_SAFE_INTEGER;
    let partyLackingVotes = '';

    votesShortData.forEach((votesShort, key) => {
        if (votesShort < lowestVotesShort && votesShort != null) {
            lowestVotesShort = votesShort;
            partyLackingVotes = keyToLabel.get(key);
        }
    });

    // Construct and display the message
    let message = `Laatste restzetel gaat naar: <span style="font-weight: bold; color: green;">${partyLastrestSeat}</span>, dit gaat ten koste van: <span style="font-weight: bold; color: red;">${partyLackingVotes}</span>`;
    document.getElementById('latestRestSeatImpactContainer').innerHTML = message;
}

let sortStates = {};




function sortTableData(data, column, defaultOrder = 'asc', excludeLastRow = false) {
    // Reset sort states for all columns except the current one
    Object.keys(sortStates).forEach(key => {
        if (key !== column) {
            sortStates[key] = null;
        }
    });

    // Set or toggle the sort state for the current column
    if (!sortStates[column]) {
        sortStates[column] = defaultOrder;
    } else if (sortStates[column] === 'asc') {
        sortStates[column] = 'desc';
    } else {
        sortStates[column] = 'asc';
    }

    // Clone and sort the array
    let dataToSort = excludeLastRow ? data.slice(0, -1) : [...data];
    dataToSort.sort((a, b) => {
        let valueA = a[column];
        let valueB = b[column];

        // Parse string to number for specific columns
        if (column === 'Stemmen over' || column === 'Stemmen tekort') {
            valueA = parseInt(valueA.replace(/[\.,]/g, ''), 10); // Replace comma/dot and parse to int
            valueB = parseInt(valueB.replace(/[\.,]/g, ''), 10);
        }

        if (valueA < valueB) {
            return sortStates[column] === 'asc' ? -1 : 1;
        }
        if (valueA > valueB) {
            return sortStates[column] === 'asc' ? 1 : -1;
        }
        return 0;
    });

    return excludeLastRow ? [...dataToSort, data[data.length - 1]] : dataToSort;
}




function renderTable(containerId, data) {
    if (data.length === 0) return;

    const columns = Object.keys(data[0]);
    const header = columns.map(colName => {
        // Use Unicode characters for sorting icons
        let sortIcon = '';
        if (sortStates[colName] === 'asc') {
            sortIcon = '&#9650;'; // Unicode for triangle pointing up
        } else if (sortStates[colName] === 'desc') {
            sortIcon = '&#9660;'; // Unicode for triangle pointing down
        }

        return `<th data-column="${colName}">${colName} <span class="sort-icon">${sortIcon}</span></th>`;
    }).join("");

    const rows = data.map((rowData, index) => {
        const cells = Object.values(rowData).map(cellData => `<td>${cellData}</td>`).join("");
        const rowClass = index === data.length - 1 ? 'total-row' : '';
        return `<tr class="${rowClass}">${cells}</tr>`;
    }).join("");

    const tableHTML = `
        <table>
            <thead>
                <tr>${header}</tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        </table>
    `;

    document.getElementById(containerId).innerHTML = tableHTML;

    document.querySelectorAll(`#${containerId} th`).forEach(th => {
        th.addEventListener('click', () => {
            const column = th.getAttribute('data-column');
            const excludeLastRow = containerId === 'seatsSummaryContainer';
            const sortedData = sortTableData(data, column, 'asc', excludeLastRow);
            renderTable(containerId, sortedData);
        });
    });
}








}
loadDataFor2023();