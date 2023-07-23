// zetels.js

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
        labelCell.textContent = parties[item.key].label; // Using the party key to access the label from the parties object
        newRow.appendChild(labelCell);
  
        var resultsCurrentVotesCell = document.createElement('td');
        resultsCurrentVotesCell.textContent = item.results.current.votes;
        newRow.appendChild(resultsCurrentVotesCell);
  
        // If you want to include the color cell (optional)
        // var partyColorCell = document.createElement('td');
        // partyColorCell.style.backgroundColor = parties[item.key].color;
        // newRow.appendChild(partyColorCell);
  
        tableBody.appendChild(newRow);
      });
    }
  
    // Function to populate the update fields
    function populateUpdateFields(data) {
      // The rest of the code remains unchanged from the previous "zetels.js" code
      // ...
    }
  
    // Function to handle AJAX request and data population
    function fetchDataAndPopulateTable() {
      // Transform parties array into an object keyed by party key
      parties = votes.parties.reduce((obj, party) => {
        obj[party.key] = party;
        return obj;
      }, {});
  
      // Fetch the votes data from "votes.js"
      var responseData = votes;
  
      // Check if the response data is an object with the 'parties' property
      if (!responseData || !responseData.parties || !Array.isArray(responseData.parties)) {
        console.error('Invalid response data:', responseData);
        return;
      }
  
      // Call the populateTable function to update the table
      populateTable(responseData.parties);
  
      // Call the populateUpdateFields function to update the fields
      populateUpdateFields(responseData);
    }
  
    // Call the fetchDataAndPopulateTable function when the DOM is fully loaded
    fetchDataAndPopulateTable();
  
    setInterval(fetchDataAndPopulateTable, 60000); // Update every minute
  });
  