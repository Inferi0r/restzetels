// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {
  // Object to store party data by key
  let parties = {};

  // Function to populate the table with the fetched data
  function populateTable(data) {
    var tableBody = document.getElementById('data-table').getElementsByTagName('tbody')[0];

    // Check if the data is an array
    if (!Array.isArray(data) || data.length === 0) {
      console.error('Invalid data format or empty data.');
      return;
    }

    // Loop through the data and create table rows
    data.forEach(function (item) {
      var newRow = document.createElement('tr');

      // Create cells for Label and Results Current Votes
      var labelCell = document.createElement('td');
      var resultsCurrentVotesCell = document.createElement('td');

      // Check if the necessary properties exist before accessing them
      if (item.key in parties) {
        labelCell.textContent = parties[item.key].label;
      } else {
        labelCell.textContent = 'N/A'; // Use a fallback value if the label is not available
      }

      if ('results' in item && 'current' in item.results && 'votes' in item.results.current) {
        resultsCurrentVotesCell.textContent = item.results.current.votes;
      } else {
        resultsCurrentVotesCell.textContent = 'N/A'; // Use a fallback value if the votes data is not available
      }

      newRow.appendChild(labelCell);
      newRow.appendChild(resultsCurrentVotesCell);
      tableBody.appendChild(newRow);
    });
  }

  // Function to handle AJAX request and data population
  function fetchDataAndPopulateTable() {
    // Make an AJAX request to the PHP script to fetch the data
    fetch('/get_data.php?source=last_update') // Use the correct data source
      .then((response) => response.json())
      .then((data) => {
        // Check if the response data is an object with the 'parties' property
        if (!data || !data.parties || !Array.isArray(data.parties)) {
          console.error('Invalid response data:', data);
          return;
        }

        // Transform parties array into an object keyed by party key
        parties = data.parties.reduce((obj, party) => {
          obj[party.key] = party;
          return obj;
        }, {});

        // Call the populateTable function to update the table
        populateTable(data.parties);
      })
      .catch((error) => console.error('Error fetching data:', error));
  }

  // Call the fetchDataAndPopulateTable function when the DOM is fully loaded
  fetchDataAndPopulateTable();

  setInterval(fetchDataAndPopulateTable, 60000); // Update every minute
});
