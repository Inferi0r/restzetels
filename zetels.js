// zetels.js

// Wait for the DOM to finish loading before executing JavaScript
document.addEventListener('DOMContentLoaded', function () {
    // Object to store party data by key
    let parties = {};
  
    // Function to fetch parties data from "votes.js" and populate the table
    function fetchDataAndPopulateTable() {
      // Assuming "votes.js" has already been included before this script
      // and that it contains the required data in the global scope
  
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
  
    // ... (rest of the code from the original "script.js" except the last line)
  
    // Call the fetchDataAndPopulateTable function when the DOM is fully loaded
    fetchDataAndPopulateTable();
  
    setInterval(fetchDataAndPopulateTable, 60000); // Update every minute
  });
  