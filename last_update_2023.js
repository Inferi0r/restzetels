document.addEventListener('DOMContentLoaded', async function () {
    // Function to construct a map from view keys to labels
    function createViewMap(views) {
        let viewMap = new Map();
        views.forEach(view => {
            viewMap.set(view.key, view.label);
        });
        return viewMap;
    }

    // Function to construct a map from party keys to labels
    // Note: Adjust this function based on the new structure of your parties data
    function createPartyMap(parties) {
        let partyMap = new Map();
        parties.forEach(party => {
            partyMap.set(party.key, party.label);
        });
        return partyMap;
    }

    // Function to create a map from type codes to labels
    function createTypeMap() {
        return new Map([
            [0, 'Gemeente'],
            [1, 'Provincie'],
            [2, 'Rijk']
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
    function populateTable(data, tbody) {
        const partyMap = createPartyMap(data.parties); // Adjust this line based on your new parties data
        const viewMap = createViewMap(data.views);
        const typeMap = createTypeMap();

        // Populate table with views
        data.views.forEach(function (item) {
            const row = document.createElement('tr');

            // Include 'key' property
            const keyCell = document.createElement('td');
            keyCell.textContent = item['key'];
            row.appendChild(keyCell);

            // Translate 'type' to its label
            const typeCell = document.createElement('td');
            typeCell.textContent = typeMap.get(item['type']);
            row.appendChild(typeCell);

            // Include 'cbsCode', 'label', 'status', 'updated' properties in this order
            ['cbsCode', 'label', 'status', 'updated'].forEach(function (property) {
                const cell = document.createElement('td');
                if (property === 'updated') {
                    const date = new Date(item[property] * 1000);
                    cell.textContent = date.toLocaleString('nl-NL');
                } else {
                    cell.textContent = item[property];
                }
                row.appendChild(cell);
            });

            // Translate 'parent' to its label
            const parentCell = document.createElement('td');
            parentCell.textContent = item['parent'] ? viewMap.get(item['parent']) : null;
            row.appendChild(parentCell);

            // Translate 'topPartiesCurrent' to party labels
            const topPartiesCurrentCell = document.createElement('td');
            topPartiesCurrentCell.textContent = item['topPartiesCurrent'].map(function (partyKey) {
                return partyMap.get(partyKey);
            }).join(', ');
            row.appendChild(topPartiesCurrentCell);

            // Handle 'source' property
            const sourceCell = document.createElement('td');
            sourceCell.textContent = item['source'];
            row.appendChild(sourceCell);

            // Handle 'countStatus' property
            const countStatusCell = document.createElement('td');
            countStatusCell.textContent = `Total: ${item.countStatus.total}, Completed: ${item.countStatus.completed}`;
            row.appendChild(countStatusCell);

            tbody.appendChild(row);
        });
    }

    // Function to handle data fetch and population
    async function fetchData() {
        try {
            const response = await fetch('/get_data_2023.php?source=last_update');
            const data = await response.json();

            const {table, tbody} = createTable();

            // Append table to the container
            document.getElementById('tableContainer').appendChild(table);

            // Call the populateTable function to update the table
            populateTable(data, tbody);
        } catch (error) {
            console.error('Error fetching or parsing data:', error);
        }
    }

    // Call the fetchData function to populate the table
    fetchData();
});
