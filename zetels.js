// zetels.js

// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {
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
  
        // Create cells for Label, Results Current Votes, and party colors
        var labelCell = document.createElement('td');
        var resultsCurrentVotesCell = document.createElement('td');
        var partyColorCell = document.createElement('td');
  
        // Check if the necessary properties exist before accessing them
        if (item.key in parties) {
          labelCell.textContent = parties[item.key].label;
          partyColorCell.style.backgroundColor = parties[item.key].color;
        } else {
          labelCell.textContent = 'N/A'; // Use a fallback value if the label is not available
          partyColorCell.style.backgroundColor = 'transparent'; // Use a fallback color if party color is not available
        }
  
        if ('results' in item && 'current' in item.results && 'votes' in item.results.current) {
          resultsCurrentVotesCell.textContent = item.results.current.votes;
        } else {
          resultsCurrentVotesCell.textContent = 'N/A'; // Use a fallback value if the votes data is not available
        }
  
        newRow.appendChild(labelCell);
        newRow.appendChild(resultsCurrentVotesCell);
        newRow.appendChild(partyColorCell);
        tableBody.appendChild(newRow);
      });
    }
  
    // Function to handle AJAX request and data population
    function fetchDataAndPopulateTable() {
      // Make an AJAX request to the PHP script to fetch the data
      fetch('/get_data.php?source=votes')
        .then((response) => response.json())
        .then((data) => {
          // Check if the response data is an object with the 'parties' property
          if (!data || !data.parties || !Array.isArray(data.parties)) {
            console.error('Invalid response data:', data);
            return;
          }
  
          // Transform parties array into an object keyed by party key
          var parties = data.parties.reduce((obj, party) => {
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
  