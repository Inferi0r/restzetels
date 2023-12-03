function loadDataFor2023() {
    // Clear existing content
    document.getElementById('tableContainer').innerHTML = '';
    const keyToLabel = new Map();
    const keyToNOSLabel = new Map(); // New map for NOS labels
    let votesData;
    let partyKeyToListNumber = new Map();
    let nosVotesMap = new Map();
    let kiesraadVotesMap = new Map(); // New map

 
    function gcd(a, b) {
        return b ? gcd(b, a % b) : a;
    }

    // Function for converting a decimal to a fraction
    function decimalToFraction(decimal) {
        // Round to three decimal places before converting to a fraction
        decimal = Math.round(decimal * 1000) / 1000;
        
        const len = decimal.toString().length - 2;
        let denominator = Math.pow(10, len);
        let numerator = decimal * denominator;
        const divisor = gcd(numerator, denominator);

        numerator /= divisor;
        denominator /= divisor;
        return `${numerator}/${denominator}`;
    }

    function createFractionHTML(numerator, denominator) {
        return `
            <div style="display: inline-block; text-align: center; font-size: smaller;">
                <span style="display: block; border-bottom: 1px solid; padding-bottom: 2px;">${numerator}</span>
                <span style="display: block; padding-top: 2px;">${denominator}</span>
            </div>`;
    }
    
    function sortTableData(data, sortColumn, sortOrder = 'asc', lastSortedColumn = 'votes') {
        return data.sort((a, b) => {
            let valueA, valueB;
    
            if (lastSortedColumn === 'lijst') {
                valueA = partyKeyToListNumber.get(a.key);
                valueB = partyKeyToListNumber.get(b.key);
            } else if (sortColumn === 'votes' || sortColumn === 'voteDiff') {
                valueA = parseInt(a.results.current.votes);
                valueB = parseInt(b.results.current.votes);
                if (sortColumn === 'voteDiff') {
                    valueA = parseInt(a.results.diff.votes);
                    valueB = parseInt(b.results.diff.votes);
                }
            } else if (sortColumn === 'nosVotes') {
                const partyShortNOSLabelA = keyToNOSLabel.get(a.key);
                const partyShortNOSLabelB = keyToNOSLabel.get(b.key);
                valueA = parseInt(nosVotesMap.get(partyShortNOSLabelA) || 0);
                valueB = parseInt(nosVotesMap.get(partyShortNOSLabelB) || 0);
            } else if (sortColumn === 'kiesraadVotes') {
                const listNumberA = partyKeyToListNumber.get(a.key);
                const listNumberB = partyKeyToListNumber.get(b.key);
                valueA = parseInt(kiesraadVotesMap.get(listNumberA) || 0);
                valueB = parseInt(kiesraadVotesMap.get(listNumberB) || 0);
            } else if (sortColumn === 'key' && keyToLabel.size > 0) {
                valueA = keyToLabel.get(a.key);
                valueB = keyToLabel.get(b.key);
            } else if (sortColumn === 'percentage' || sortColumn === 'percentageDiff') {
                // Handle percentages
                valueA = parseFloat(a.results.current.percentage.replace(',', '.'));
                valueB = parseFloat(b.results.current.percentage.replace(',', '.'));
                if (sortColumn === 'percentageDiff') {
                    // Special handling for percentage difference
                    let diffA = a.results.diff.votes;
                    let diffB = b.results.diff.votes;
                    let votesA = a.results.current.votes;
                    let votesB = b.results.current.votes;
                    valueA = diffA === '∞' ? -Infinity : parseFloat((parseInt(diffA) / parseInt(votesA) * 100).toFixed(1));
                    valueB = diffB === '∞' ? -Infinity : parseFloat((parseInt(diffB) / parseInt(votesB) * 100).toFixed(1));
                }
            } else {
                valueA = a[sortColumn];
                valueB = b[sortColumn];
            }
    
            // Compare logic
            if (['lijst', 'votes', 'voteDiff', 'percentageDiff', 'nosVotes', 'kiesraadVotes'].includes(sortColumn)) {
                return sortOrder === 'asc' ? valueA - valueB : valueB - valueA;
            } else {
                valueA = valueA ? valueA.toString() : '';
                valueB = valueB ? valueB.toString() : '';
                return sortOrder === 'asc' ? valueA.localeCompare(valueB, undefined, { numeric: true }) : valueB.localeCompare(valueA, undefined, { numeric: true });
            }
        });
    }
    
    
    

    function createTable(sortColumn = 'votes', sortOrder = 'desc', lastSortedColumn = 'votes') {
        document.getElementById('tableContainer').innerHTML = '';

        const table = document.createElement('table');
        const thead = table.createTHead();
        const tbody = table.createTBody();
        const headerRow = thead.insertRow();

        const headers = {
            'Lijst': { dataProperty: 'key', sortIdentifier: 'lijst' },
            'Partij': { dataProperty: 'key', sortIdentifier: 'partij' },
            'Stemcijfer ANP': { dataProperty: 'votes', sortIdentifier: 'votes' },
            'Stemcijfer NOS': { dataProperty: 'nosVotes', sortIdentifier: 'nosVotes' },
            'Stemcijfer Kiesraad': { dataProperty: 'kiesraadVotes', sortIdentifier: 'kiesraadVotes' }, // New column
            'Percentage ANP': { dataProperty: 'percentage', sortIdentifier: 'percentage' },
            '# Verschil ANP': { dataProperty: 'voteDiff', sortIdentifier: 'voteDiff' },
            '% Verschil ANP': { dataProperty: 'percentageDiff', sortIdentifier: 'percentageDiff' }
        };

        Object.entries(headers).forEach(([headerText, { dataProperty, sortIdentifier }]) => {
            const header = document.createElement('th');
            header.innerHTML = `${headerText} <span class="sort-icon"></span>`;

            // Add the click event listener to each header
            header.addEventListener('click', () => {
                const newSortOrder = lastSortedColumn === sortIdentifier && sortOrder === 'asc' ? 'desc' : 'asc';
                createTable(dataProperty, newSortOrder, sortIdentifier);
            });

            if (lastSortedColumn === sortIdentifier) {
                const sortIcon = sortOrder === 'asc' ? '&#9650;' : '&#9660;';
                header.querySelector('.sort-icon').innerHTML = sortIcon;
            }

            headerRow.appendChild(header);
        });

        votesData.parties = sortTableData(votesData.parties, sortColumn, sortOrder, lastSortedColumn);

        votesData.parties.forEach(party => {
            const row = tbody.insertRow();

            const partyLabel = keyToLabel.get(party.key); // For "Partij" column
            const partyShortNOSLabel = keyToNOSLabel.get(party.key); // For NOS votes
            const nosVotes = nosVotesMap.get(partyShortNOSLabel) || 0;
        
            const partyName = keyToLabel.get(party.key);

            const voteDiff = party.results.diff.votes;
            
            const currentVotes = parseInt(party.results.current.votes);
            const previousVotes = parseInt(party.results.previous.votes);
            if (previousVotes === 0 && currentVotes > 0) {
                percentageDiff = '∞';
            } else {
                const voteDifference = currentVotes - previousVotes;
                percentageDiff = (voteDifference / previousVotes * 100).toFixed(1).replace('.', ',');
            }
        
            if (!partyName.toUpperCase().includes('OVERIG')) {
                // Use the mapping to display the list number
                const listNumberCell = row.insertCell();
                listNumberCell.textContent = partyKeyToListNumber.get(party.key);
        
                const partyNameCell = row.insertCell();
                partyNameCell.textContent = partyName;
        
                const votesCell = row.insertCell();
                votesCell.textContent = parseInt(party.results.current.votes).toLocaleString('nl-NL');
        
                const nosVotesCell = row.insertCell();
                nosVotesCell.textContent = nosVotes.toLocaleString('nl-NL');

                const kiesraadVotesCell = row.insertCell(); // New cell for Stemcijfer Kiesraad
                const listNumber = partyKeyToListNumber.get(party.key); // Get the list number using the party key
                const kiesraadVotes = kiesraadVotesMap.get(listNumber); // Use list number to get Kiesraad votes
                kiesraadVotesCell.textContent = kiesraadVotes ? kiesraadVotes.toLocaleString('nl-NL') : '';
            
                const percentageCell = row.insertCell();
                percentageCell.textContent = party.results.current.percentage;

                const voteDiffCell = row.insertCell();
                voteDiffCell.textContent = parseInt(voteDiff).toLocaleString('nl-NL');
    
                const percentageDiffCell = row.insertCell();
                percentageDiffCell.textContent = percentageDiff;
            }
            
        });

        document.getElementById('tableContainer').appendChild(table);

        // Add white space under the table
        const whitespaceRow = tbody.insertRow();
        const whitespaceCell = whitespaceRow.insertCell();
        whitespaceCell.colSpan = 3;
        whitespaceCell.innerHTML = "&nbsp;";

        const totalANPVotes = votesData.parties.reduce((total, party) => total + parseInt(party.results.current.votes), 0);
        const totalNOSVotes = Array.from(nosVotesMap.values()).reduce((total, votes) => total + votes, 0);
        const totalKiesraadVotes = Array.from(kiesraadVotesMap.values()).reduce((total, votes) => total + votes, 0);

        const kiesdelerANP = totalANPVotes / 150;
        const kiesdelerNOS = totalNOSVotes / 150;
        const kiesdelerKiesraad = totalKiesraadVotes / 150;

        // Create total row
        const totalRow = tbody.insertRow();
        const totalLabelCell = totalRow.insertCell();
        totalLabelCell.colSpan = 2;
        totalLabelCell.textContent = "Totaal aantal geldige stemmen op lijsten:";

        // ANP votes total
        const totalANPCell = totalRow.insertCell();
        totalANPCell.textContent = totalANPVotes.toLocaleString('nl-NL');

        // NOS votes total
        const totalNOSCell = totalRow.insertCell();
        totalNOSCell.textContent = totalNOSVotes.toLocaleString('nl-NL');

        // Kiesraad votes total
        const totalKiesraadCell = totalRow.insertCell();
        totalKiesraadCell.textContent = totalKiesraadVotes.toLocaleString('nl-NL');

        // Create Kiesdeler row for each column
        const kiesdelerRow = tbody.insertRow();
        const kiesdelerLabelCell = kiesdelerRow.insertCell();
        kiesdelerLabelCell.colSpan = 2;
        kiesdelerLabelCell.textContent = "Kiesdeler:";

        // Function to display Kiesdeler with fraction
        function displayKiesdeler(kiesdelerValue, cell) {
            const kiesdelerWhole = Math.trunc(kiesdelerValue);
            const kiesdelerFraction = decimalToFraction(kiesdelerValue % 1);
            const [numerator, denominator] = kiesdelerFraction.split('/');
            const kiesdelerFractionHTML = createFractionHTML(numerator, denominator);
            cell.innerHTML = `<div style="display: flex; align-items: center; justify-content: flex-start; height: 100%;">
                <span style="margin-right: 5px;">${kiesdelerWhole.toLocaleString('nl-NL')}</span>
                ${kiesdelerFractionHTML}
            </div>`;
        }

        // Display Kiesdeler for each column
        const kiesdelerANPCell = kiesdelerRow.insertCell();
        displayKiesdeler(kiesdelerANP, kiesdelerANPCell);

        const kiesdelerNOSCell = kiesdelerRow.insertCell();
        displayKiesdeler(kiesdelerNOS, kiesdelerNOSCell);

        const kiesdelerKiesraadCell = kiesdelerRow.insertCell();
        displayKiesdeler(kiesdelerKiesraad, kiesdelerKiesraadCell);

    }

    fetch('partylabels_2023.json')
    .then(response => response.json())
    .then(data => {
        data.forEach((party, index) => {
            keyToLabel.set(party.key, party.labelLong); // For "Partij" column
            keyToNOSLabel.set(party.key, party.labelShortNOS); // For NOS votes
            partyKeyToListNumber.set(party.key, index + 1);
        });
    
        // Fetch NOS votes data
        return fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=nos');
    })
    .then(response => response.json())
    .then(nosData => {
        // Process NOS data
        nosData.landelijke_uitslag.partijen.forEach(party => {
            const nosKey = party.partij.short_name; // Adjust as needed for mapping
            nosVotesMap.set(nosKey, party.huidig.stemmen);
        });
    
        // After processing NOS data, fetch Kiesraad votes data
        return fetch('votes-kiesraad_2023.js'); // Ensure the file path is correct
    })
    .then(response => response.json())
    .then(kiesraadData => {
        // Process Kiesraad data
        kiesraadData.forEach(item => {
            kiesraadVotesMap.set(item.lijstnummer, item.votes);
        });
    
        // After processing Kiesraad data, fetch ANP votes data
        return fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=votes');
    })
    .then(response => response.json())
    .then(anpData => {
        // Process ANP data
        votesData = anpData;
        votesData.totalVotes = votesData.parties.reduce((total, party) => total + parseInt(party.results.current.votes), 0);
        votesData.kiesdeler = votesData.totalVotes / 150;
    
        createTable(); // This will now create the table with the Kiesraad data included
    })
    .catch(error => {
        console.error('Error:', error);
    });
    

}

loadDataFor2023();