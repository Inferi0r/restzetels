function loadDataFor2023() {
    document.getElementById('tableContainer').innerHTML = ''; // Clear existing content

    // Function to construct a map from view keys to labels
    function createViewMap(views) {
        let viewMap = new Map();
        views.forEach(view => {
            viewMap.set(view.key, view.label);
        });
        return viewMap;
    }

    // Function to create a map from type codes to labels
    function createTypeMap() {
        return new Map([
            [0, 'Gemeente'],
            [1, 'Provincie'],
            [2, 'Rijk']
        ]);
    }

    function createStatusMap() {
        return new Map([
            [0, 'In Afwachting'],
            [2, 'Gedeeltelijk'],
            [4, 'Compleet']
        ]);
    }
    // Function to create a table
    function createTable() {
        const table = document.createElement('table');
        const thead = table.createTHead();
        const tbody = table.createTBody();
        const headerRow = thead.insertRow();

        const headers = [
            "Key",
            "Type",
            "Cbscode",
            "Label",
            "Status",
            "Updated",
            "Parent",
            "Top Parties Current",
            "Top Parties Previous",
            "Source",
            "Count Status"
        ];

        headers.forEach(header => {
            const th = document.createElement("th");
            const text = document.createTextNode(header);
            th.appendChild(text);
            headerRow.appendChild(th);
        });

        return {table, tbody};
    }

    // Function to populate the table with the fetched data
    function populateTable(data, tbody, partyLabels) {
        const viewMap = createViewMap(data.views);
        const typeMap = createTypeMap();
        const statusMap = createStatusMap();

        data.views.forEach(function (item) {
            const row = document.createElement('tr');

            ['key', 'type', 'cbsCode', 'label', 'status', 'updated'].forEach(property => {
                const cell = document.createElement('td');
                if (property === 'updated') {
                    const date = new Date(item[property] * 1000);
                    cell.textContent = date.toLocaleString('nl-NL');
                } else if (property === 'type') {
                    cell.textContent = typeMap.get(item[property]);
                } else if (property === 'status') {
                    // Gebruik de statusMap voor de 'status' property
                    cell.textContent = statusMap.get(item[property]) || item[property];
                } else {
                    cell.textContent = item[property];
                }
                row.appendChild(cell);
            });

            const parentCell = document.createElement('td');
            parentCell.textContent = item['parent'] ? viewMap.get(item['parent']) : null;
            row.appendChild(parentCell);

            ['topPartiesCurrent', 'topPartiesPrevious'].forEach(property => {
                const cell = document.createElement('td');
                cell.textContent = item[property]
                    .map(key => partyLabels.get(key) || key)
                    .join(', ');
                row.appendChild(cell);
            });

            const sourceCell = document.createElement('td');
            sourceCell.textContent = item['source'];
            row.appendChild(sourceCell);

            const countStatusCell = document.createElement('td');
            countStatusCell.textContent = `Total: ${item.countStatus.total}, Completed: ${item.countStatus.completed}`;
            row.appendChild(countStatusCell);

            tbody.appendChild(row);
        });
    }

    // Function to handle data fetch and population
    async function fetchData() {
        try {
            const partyLabelsResponse = await fetch('partylabels_2023.json');
            const partyLabelsData = await partyLabelsResponse.json();
            const partyLabels = new Map(partyLabelsData.map(p => [p.key, p.labelShort]));

            const response = await fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=last_update');
            const data = await response.json();

            const {table, tbody} = createTable();

            document.getElementById('tableContainer').appendChild(table);

            populateTable(data, tbody, partyLabels);
        } catch (error) {
            console.error('Error fetching or parsing data:', error);
        }
    }

    // Call the fetchData function to populate the table
    fetchData();
}
