// Fetch data from get_data.php
async function fetchData(source) {
  const response = await fetch(`get_data.php?source=${source}`);
  const data = await response.json();
  return data;
}

// Get data from both sources
async function getData() {
  const votesData = await fetchData('votes');
  const updateData = await fetchData('last_update');

  // Map keys to party labels
  const keyToLabel = new Map();
  updateData.parties.forEach((party) => {
    keyToLabel.set(party.key, party.label);
  });

  // Create table
  const table = document.createElement('table');

  // Create table header
  const header = table.createTHead();
  const headerRow = header.insertRow();
  const partyHeader = headerRow.insertCell();
  const votesHeader = headerRow.insertCell();
  partyHeader.textContent = 'Partij';
  votesHeader.textContent = 'Stemmen';

  // Add table rows
  const body = table.createTBody();
  votesData.parties.forEach((party) => {
    const row = body.insertRow();
    const partyCell = document.createElement('th');
    const votesCell = row.insertCell();
    partyCell.textContent = keyToLabel.get(party.key);
    votesCell.textContent = party.results.current.votes;
    row.appendChild(partyCell);
    row.appendChild(votesCell);
});

  // Append table to document body (or another desired element)
  document.getElementById('tableContainer').appendChild(table);
}

// Get data when DOM is fully loaded
document.addEventListener('DOMContentLoaded', getData);
