function loadDataFor2023() {
    // Clear existing content
    document.getElementById('tableContainer').innerHTML = '';
    const keyToLabel = new Map();
    let votesData;
    let partyKeyToListNumber = new Map();

    function sortTableData(data, sortColumn, sortOrder = 'asc', lastSortedColumn = 'votes') {
        return data.sort((a, b) => {
            let valueA, valueB;

            if (lastSortedColumn === 'lijst') {
                valueA = partyKeyToListNumber.get(a.key);
                valueB = partyKeyToListNumber.get(b.key);
            } else if (sortColumn === 'votes') {
                valueA = parseInt(a.results.current.votes);
                valueB = parseInt(b.results.current.votes);
            } else if (sortColumn === 'key' && keyToLabel.size > 0) {
                valueA = keyToLabel.get(a.key);
                valueB = keyToLabel.get(b.key);
            } else {
                valueA = a[sortColumn];
                valueB = b[sortColumn];
            }

            if (lastSortedColumn === 'lijst') {
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
            'Stemcijfers ANP': { dataProperty: 'votes', sortIdentifier: 'votes' }
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

        // Populate table body
        votesData.parties.forEach(party => {
            const row = tbody.insertRow();

            // Use the mapping to display the list number
            const listNumberCell = row.insertCell();
            listNumberCell.textContent = partyKeyToListNumber.get(party.key);

            const partyNameCell = row.insertCell();
            partyNameCell.textContent = keyToLabel.get(party.key);

            const votesCell = row.insertCell();
            votesCell.textContent = parseInt(party.results.current.votes).toLocaleString('nl-NL');
        });

        document.getElementById('tableContainer').appendChild(table);

        // Add white space under the table
        const whitespaceRow = tbody.insertRow();
        const whitespaceCell = whitespaceRow.insertCell();
        whitespaceCell.colSpan = 3;
        whitespaceCell.innerHTML = "&nbsp;";

        // Create total row
        const totalRow = tbody.insertRow();
        const totalLabelCell = totalRow.insertCell();
        const totalCell = totalRow.insertCell();
        totalLabelCell.colSpan = 2;
        totalLabelCell.textContent = "Totaal aantal geldige stemmen op lijsten:";
        totalCell.textContent = votesData.totalVotes.toLocaleString('nl-NL');

        // Create Kiesdeler row
        const kiesdelerRow = tbody.insertRow();
        const kiesdelerLabelCell = kiesdelerRow.insertCell();
        const kiesdelerCell = kiesdelerRow.insertCell();
        kiesdelerLabelCell.colSpan = 2;
        kiesdelerLabelCell.textContent = "Kiesdeler:";
        kiesdelerCell.textContent = votesData.kiesdeler.toLocaleString('nl-NL');
    }

    // Fetch label data and votes data, then create table
    fetch('partylabels_2023.json')
        .then(response => response.json())
        .then(data => {
            data.forEach((party, index) => {
                keyToLabel.set(party.key, party.labelLong);
                partyKeyToListNumber.set(party.key, index + 1); // Assign list numbers starting from 1
            });

            // Fetch votes data
            fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=votes')
                .then(response => response.json())
                .then(data => {
                    votesData = data;
                    votesData.totalVotes = votesData.parties.reduce((total, party) => total + parseInt(party.results.current.votes), 0);
                    votesData.kiesdeler = Math.floor(votesData.totalVotes / 150);
                    createTable();
                });
        });
}

loadDataFor2023();
