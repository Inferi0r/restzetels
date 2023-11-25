function loadDataFor2023() {
    document.getElementById('tableContainer').innerHTML = ''; // Clear existing content

    // Function to create a table header row
    function createHeaderRow(headers) {
        const thead = document.createElement('thead');
        const headerRow = thead.insertRow();

        headers.forEach(header => {
            const th = document.createElement('th');
            th.textContent = header;
            headerRow.appendChild(th);
        });

        return thead;
    }

// Function to create a table body and populate it with data
function createTableBody(data) {
    const tbody = document.createElement('tbody');

    data.gemeentes.forEach(item => {
        const row = tbody.insertRow();

        // Define the order of columns based on your JSON structure
        const columns = [
            'status',
            'publicatie_datum_tijd',
            'gemeente.naam',
       //     'gemeente.cbs_code',       
            'gemeente.aantal_inwoners',
            'gemeente.kieskring',
            'gemeente.provincie.naam',
            'gemeente.provincie.aantal_inwoners',
            'eerste_partij.short_name',
       //     'eerste_partij.name',
            'tweede_partij.short_name',
       //     'tweede_partij.name',
            'huidige_verkiezing.opkomst_promillage',
            'vorige_verkiezing.opkomst_promillage',
        ];

        columns.forEach(column => {
            const cell = row.insertCell();
            const keys = column.split('.');
            let value = item;

            keys.forEach(key => {
                if (value && key in value) {
                    value = value[key];
                } else {
                    value = null;
                }
            });

            if (column === 'huidige_verkiezing.opkomst_promillage' || column === 'vorige_verkiezing.opkomst_promillage') {
                // Format Opkomst Promillage
                value = formatPercentage(value);
            } else if (column === 'gemeente.aantal_inwoners' || column === 'gemeente.provincie.aantal_inwoners') {
                // Format Aantal Inwoners Gemeente and Aantal Inwoners Provincie
                value = formatNumber(value);
            } else if (column === 'publicatie_datum_tijd') {
                // Format Publicatie Datum Tijd
                value = formatDate(value);
            }

            cell.textContent = value !== null ? value.toString() : '';
        });
    });

    return tbody;
}



// Function to format a number with a dot as thousands separator
function formatNumber(number) {
    if (typeof number === 'number') {
        return number.toLocaleString('nl-NL');
    }
    return '';
}

// Function to format a percentage with one decimal place and a percentage sign
function formatPercentage(percentage) {
    if (typeof percentage === 'number') {
        return (percentage / 10).toFixed(1) + '%';
    }
    return '';
}

// Function to format a date and time as 'DD-MM-YYYY HH:mm:ss'
function formatDate(dateTime) {
    if (typeof dateTime === 'string') {
        const dateObj = new Date(dateTime);
        const options = {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        };
        return dateObj.toLocaleString('nl-NL', options).replace(/(\d{2})-(\d{2})-(\d{4}) (\d{2}:\d{2}:\d{2})/, '$2-$1-$3 $4');
    }
    return '';
}

function createAndPopulateTable(data) {
    // Sort the data by "Laatste Update" in descending order
    data.gemeentes.sort((a, b) => {
        return new Date(b.publicatie_datum_tijd) - new Date(a.publicatie_datum_tijd);
    });

    const headers = [
        'Status',
        'Laatste Update',
        'Gemeente',
   //     'CBS Code Gemeente',
        'Inwoners Gemeente',
        'Kieskring',
        'Provincie',
        'Inwoners Provincie',
        '1e Partij',
   //     '1e Partij (lang)',
        '2e Partij',
   //     '2e Partij (lang)',
        'Opkomst (huidig)',
        'Opkomst (vorige)'
    ];

    const table = document.createElement('table');
    table.appendChild(createHeaderRow(headers));
    table.appendChild(createTableBody(data));

    return table;
}



    
    async function fetchData() {
        try {
            const response = await fetch('https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata?year=2023&source=nos');
            const data = await response.json();

            const table = createAndPopulateTable(data);

            document.getElementById('tableContainer').appendChild(table);
        } catch (error) {
            console.error('Error fetching or parsing data:', error);
        }
    }

    // Call the fetchData function to populate the table
    fetchData();
}
