// This is your votes.js
document.addEventListener("DOMContentLoaded", function () {
    const fetchData = async () => {
        try {
            const response = await fetch("https://restzetels.td.co.nl/get_data.php?source=votes");
            const responseData = await response.json();

            console.log('Response Data:', responseData); // Log the entire response data

            const { updated, turnout } = responseData;
            console.log('Updated:', updated); // Log the updated timestamp
            console.log('Turnout:', turnout); // Log the turnout object

            document.getElementById("lastUpdate").textContent = new Date(updated * 1000).toLocaleString();
            document.getElementById("currentTurnout").textContent = turnout.current;
            document.getElementById("lastTurnout").textContent = turnout.previous;

            populateResults(responseData.parties);
        } catch (err) {
            console.error(err);
        }
    };

    const populateResults = (parties) => {
        const tableBody = document.getElementById("results");

        tableBody.innerHTML = ""; // Clear the table body

        // Loop through each party in the data
        parties.forEach((party) => {
            // Create new row and cells
            const row = document.createElement("tr");
            const nameCell = document.createElement("td");
            const votesCell = document.createElement("td");
            const percentCell = document.createElement("td");
            const seatsCell = document.createElement("td");

            // Set the text for each cell
            nameCell.textContent = party.name;
            votesCell.textContent = party.results.current.votes;
            percentCell.textContent = party.results.current.percentage;
            seatsCell.textContent = party.results.current.seats;

            // Append the cells to the row
            row.appendChild(nameCell);
            row.appendChild(votesCell);
            row.appendChild(percentCell);
            row.appendChild(seatsCell);

            // Append the row to the table body
            tableBody.appendChild(row);
        });
    };

    fetchData();
});
