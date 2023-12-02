function loadDataFor2023() {
    // Clear existing content
    document.getElementById('tableContainer').innerHTML = '';
    let votesData;
    let currentSort = { column: 'stemmen', order: 'desc' }; // Default

    function calculatePercentageDiff(currentVotes, previousVotes) {
        if (previousVotes === 0) {
            return currentVotes > 0 ? '∞' : '0,0';
        } else {
            return ((currentVotes - previousVotes) / previousVotes * 100).toFixed(1).replace('.', ',');
        }
    }

    function calculatePercentageOfTotal(currentVotes, totalVotes) {
        return (currentVotes / totalVotes * 100).toFixed(1).replace('.', ',');
    }

    function sortTableData(data, sortColumn, sortOrder = 'desc') {
        return data.sort((a, b) => {
            let valueA, valueB;
    
            switch (sortColumn) {
                case 'name':
                    // Sort by party name
                    valueA = a.partij.name.toLowerCase();
                    valueB = b.partij.name.toLowerCase();
                    break;
                case 'stemmen':
                    // Sort by vote count for "TK23"
                    valueA = a.huidig.verkiezing_code === "TK23" ? a.huidig.stemmen : 0;
                    valueB = b.huidig.verkiezing_code === "TK23" ? b.huidig.stemmen : 0;
                    break;
                case 'percentage':
                case 'percentageDiff':
                    // Convert to float for sorting
                    valueA = a[sortColumn] === '∞' ? Infinity : parseFloat(a[sortColumn].replace(',', '.'));
                    valueB = b[sortColumn] === '∞' ? Infinity : parseFloat(b[sortColumn].replace(',', '.'));
                    break;
                default:
                    // Handle other numeric fields
                    valueA = parseInt(a[sortColumn]);
                    valueB = parseInt(b[sortColumn]);
            }
    
            // Numeric and string sorting logic
            if (sortOrder === 'asc') {
                return valueA > valueB ? 1 : valueA < valueB ? -1 : 0;
            } else {
                return valueA < valueB ? 1 : valueA > valueB ? -1 : 0;
            }
        });
    }
    
    

    function createTable() {
        document.getElementById('tableContainer').innerHTML = '';
        const table = document.createElement('table');
        const thead = table.createTHead();
        const tbody = table.createTBody();
        const headerRow = thead.insertRow();

        const headers = ['Partij', 'Stemcijfer', 'Percentage', '# Verschil', '% Verschil'];
        const dataProperties = ['name', 'stemmen', 'percentage', 'stemmenDiff', 'percentageDiff'];

        headers.forEach((headerText, index) => {
            const header = document.createElement('th');
            header.innerHTML = headerText;

            header.addEventListener('click', () => {
                if (currentSort.column === dataProperties[index]) {
                    currentSort.order = currentSort.order === 'asc' ? 'desc' : 'asc';
                } else {
                    currentSort.column = dataProperties[index];
                    currentSort.order = 'asc'; // Reset to ascending when switching columns
                }
                createTable();
            });

            if (currentSort.column === dataProperties[index]) {
                const sortIcon = currentSort.order === 'asc' ? '&#9650;' : '&#9660;';
                header.innerHTML += ` <span class="sort-icon">${sortIcon}</span>`;
            }

            headerRow.appendChild(header);
        });

        // Calculate total valid votes
        const totalValidVotes = votesData.landelijke_uitslag.partijen.reduce((total, party) => total + party.huidig.stemmen, 0);

        votesData.landelijke_uitslag.partijen.forEach(party => {
            const huidig = party.huidig;
            const vorig = party.vorig;

            party.stemmenDiff = huidig.stemmen - vorig.stemmen;
            party.percentageDiff = calculatePercentageDiff(huidig.stemmen, vorig.stemmen);
            party.percentage = calculatePercentageOfTotal(huidig.stemmen, totalValidVotes);

            const row = tbody.insertRow();
            row.insertCell().textContent = party.partij.name;
            row.insertCell().textContent = huidig.stemmen.toLocaleString('nl-NL');
            row.insertCell().textContent = party.percentage;
            row.insertCell().textContent = party.stemmenDiff.toLocaleString('nl-NL');
            row.insertCell().textContent = party.percentageDiff;
        });

        votesData.landelijke_uitslag.partijen = sortTableData(votesData.landelijke_uitslag.partijen, currentSort.column, currentSort.order);

        document.getElementById('tableContainer').appendChild(table);
    }

    fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=nos')
        .then(response => response.json())
        .then(data => {
            votesData = data;
            createTable();
        })
        .catch(error => {
            console.error('Error fetching NOS data:', error);
            // Handle the error appropriately
        });
}

loadDataFor2023();

