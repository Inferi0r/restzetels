// zetels.js

// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {
    // Object to store party data by key
    let parties = {};
  
    // Function to populate the table with the fetched data
    function populateTable(data) {
      // The rest of the code remains unchanged from the previous "zetels.js" code
      // ...
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
  