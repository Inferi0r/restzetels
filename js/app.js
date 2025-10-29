// Unified year-aware loader for seat distribution (restzetels) across 2021, 2023, 2025

(function () {
  const DO_BASE = 'https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata';

  async function safeFetchJSON(url) {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  async function fetchPartyLabels(year) {
    // unified partylabels.json with per-year arrays
    const url = `partylabels.json`;
    const data = await safeFetchJSON(url);
    if (!data) return { list: [], keyToLabelShort: new Map(), keyToLabelLong: new Map(), keyToNOS: new Map(), keyToListNumber: new Map() };
    const list = Array.isArray(data) ? data : (data[String(year)] || []);
    const keyToLabelShort = new Map();
    const keyToLabelLong = new Map();
    const keyToNOS = new Map();
    const keyToListNumber = new Map();
    list.forEach((p, idx) => {
      keyToLabelShort.set(p.key, p.labelShort);
      keyToLabelLong.set(p.key, p.labelLong);
      if (p.labelShortNOS) keyToNOS.set(p.key, p.labelShortNOS);
      keyToListNumber.set(p.key, idx + 1);
    });
    return { list, keyToLabelShort, keyToLabelLong, keyToNOS, keyToListNumber };
  }

  let __kiesraadIndex = null;
  async function isFinalizedYear(year){
    const y = String(year);
    if (!__kiesraadIndex) {
      __kiesraadIndex = await safeFetchJSON(`votes_kiesraad.json`);
    }
    if (!__kiesraadIndex) return false;
    const entry = Array.isArray(__kiesraadIndex) ? __kiesraadIndex : __kiesraadIndex[y];
    return Array.isArray(entry) && entry.length > 0;
  }

  async function fetchANPVotes(year) {
    const y = String(year);
    if (await isFinalizedYear(y)) return await safeFetchJSON(`data/${y}/anp_votes.json`);
    return await safeFetchJSON(`${DO_BASE}?year=${encodeURIComponent(y)}&source=anp_votes`);
  }

  async function fetchANPLastUpdate(year) {
    const y = String(year);
    if (await isFinalizedYear(y)) return await safeFetchJSON(`data/${y}/anp_last_update.json`);
    return await safeFetchJSON(`${DO_BASE}?year=${encodeURIComponent(y)}&source=anp_last_update`);
  }

  async function fetchNOSIndex(year) {
    const y = String(year);
    if (await isFinalizedYear(y)) return await safeFetchJSON(`data/${y}/nos_index.json`);
    return await safeFetchJSON(`${DO_BASE}?year=${encodeURIComponent(y)}&source=nos_index`);
  }

  async function tryFetchKiesraadVotes(year) {
    // Unified local file with per-year keys
    const url = `votes_kiesraad.json`;
    const data = await safeFetchJSON(url);
    if (!data) return null;
    if (Array.isArray(data)) return data; // backward compat if ever array
    return data[String(year)] || null;
  }

  function mapKiesraadDataToANPFormat(kiesraadData, partyLabelsList) {
    // Assumes partyLabelsList order corresponds to list numbers (1-based)
    return {
      parties: kiesraadData.map(item => {
        const party = partyLabelsList[item.lijstnummer - 1];
        const key = party ? party.key : (item.lijstnummer - 1);
        return {
          key,
          results: {
            previous: { votes: '0', percentage: '0,0', seats: '0' },
            current: { votes: item.votes, percentage: '0,0', seats: '0' },
            diff: { votes: '0', percentage: '0,0', seats: '0' }
          }
        };
      })
    };
  }

  function sumVotes(anpLikeData) {
    if (!anpLikeData || !anpLikeData.parties) return 0;
    return anpLikeData.parties.reduce((acc, p) => acc + parseInt(p.results.current.votes || 0, 10), 0);
  }

  // Math helpers
  function gcd(a, b) { return b ? gcd(b, a % b) : a; }
  function decimalToFraction(decimal) {
    const tolerance = 1e-6;
    let numerator = decimal;
    let denominator = 1;
    let simplified = false;
    while (!simplified && denominator < 100) {
      denominator++;
      numerator = decimal * denominator;
      if (Math.abs(Math.round(numerator) - numerator) < tolerance) {
        simplified = true;
        numerator = Math.round(numerator);
      }
    }
    const div = gcd(numerator, denominator);
    numerator /= div; denominator /= div;
    if (denominator === 100) {
      numerator *= 0.99; denominator *= 0.99;
      const d2 = gcd(numerator, denominator);
      numerator /= d2; denominator /= d2;
    }
    return `${Math.round(numerator)}/${Math.round(denominator)}`;
  }
  function createFractionHTML(numerator, denominator) {
    if (!numerator || !denominator) return '';
    return (
      `<div style="display: inline-block; text-align: center; font-size: smaller;">` +
      `<span style="display: block; border-bottom: 1px solid; padding-bottom: 2px;">${numerator}</span>` +
      `<span style="display: block; padding-top: 2px;">${denominator}</span>` +
      `</div>`
    );
  }
  function extractFraction(htmlString) {
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = htmlString;
    const n = tempDiv.querySelector('span:first-child');
    const d = tempDiv.querySelector('span:last-child');
    if (!n || !d) return 0;
    return (parseFloat(n.textContent) || 0) / (parseFloat(d.textContent) || 1);
  }

  function calculateFullAndRestSeats(votesData) {
    let totalVotes = 0;
    votesData.parties.forEach(party => totalVotes += parseInt(party.results.current.votes));
    const kiesdeler = totalVotes / 150;
    votesData.parties.forEach(party => {
      const fullSeats = Math.floor(party.results.current.votes / kiesdeler);
      party.fullSeats = fullSeats;
      party.restSeats = new Map();
    });
    const total_fullSeats = votesData.parties.reduce((acc, p) => acc + p.fullSeats, 0);
    const total_restSeats = 150 - total_fullSeats;
    return { votesData, total_restSeats };
  }

  function assignRestSeats({ votesData, total_restSeats }) {
    for (let i = 1; i <= total_restSeats; i++) {
      let maxVoteAverage = 0;
      let partyWithMaxVoteAverage = null;
      votesData.parties.forEach(party => {
        if (party.fullSeats > 0) {
          const restSeatsCount = Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
          const voteAverage = Math.round(party.results.current.votes / (party.fullSeats + restSeatsCount + 1));
          if (voteAverage > maxVoteAverage) { maxVoteAverage = voteAverage; partyWithMaxVoteAverage = party; }
        }
      });
      if (partyWithMaxVoteAverage) partyWithMaxVoteAverage.restSeats.set(i, 1);
    }
    return votesData;
  }

  function createVoteAverageTableData(votesData, keyToLabel, total_restSeats) {
    const tableData = [];
    votesData.parties.forEach(party => {
      if (party.fullSeats > 0) {
        const row = { 'Partij': keyToLabel.get(party.key) };
        for (let i = 1; i <= total_restSeats; i++) {
          const prevRest = Array.from(party.restSeats.keys()).filter(k => k < i).reduce((a, k) => a + party.restSeats.get(k), 0);
          const voteAverage = party.results.current.votes / (party.fullSeats + prevRest + 1);
          const fraction = decimalToFraction(voteAverage);
          row[`${i}e`] = createFractionHTML(...fraction.split('/'));
        }
        tableData.push(row);
      }
    });
    return tableData;
  }

  const sortStates = {};
  function sortTableData(data, column, defaultOrder = 'asc', excludeLastRow = false) {
    Object.keys(sortStates).forEach(k => { if (k !== column) sortStates[k] = null; });
    if (!sortStates[column]) sortStates[column] = defaultOrder; else sortStates[column] = (sortStates[column] === 'asc' ? 'desc' : 'asc');
    const dataToSort = excludeLastRow ? data.slice(0, -1) : [...data];
    dataToSort.sort((a, b) => {
      let A = a[column], B = b[column];
      if (column === 'Stemmen over' || column === 'Stemmen tekort') {
        A = parseInt((A || '').toString().replace(/[\.,]/g, ''), 10) || 0;
        B = parseInt((B || '').toString().replace(/[\.,]/g, ''), 10) || 0;
      }
      if (A < B) return sortStates[column] === 'asc' ? -1 : 1;
      if (A > B) return sortStates[column] === 'asc' ? 1 : -1;
      return 0;
    });
    return excludeLastRow ? [...dataToSort, data[data.length - 1]] : dataToSort;
  }

  function renderTable(containerId, data) {
    if (!data || data.length === 0) { document.getElementById(containerId).innerHTML = ''; return; }
    const columns = Object.keys(data[0]);
    const header = columns.map(col => {
      let icon = '';
      if (sortStates[col] === 'asc') icon = '&#9650;'; else if (sortStates[col] === 'desc') icon = '&#9660;';
      return `<th data-column="${col}">${col} <span class="sort-icon">${icon}</span></th>`;
    }).join('');
    const rows = data.map((row, i) => {
      const cells = Object.values(row).map(cell => `<td>${cell}</td>`).join('');
      const rowClass = i === data.length - 1 ? 'total-row' : '';
      return `<tr class="${rowClass}">${cells}</tr>`;
    }).join('');
    const html = `<table><thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table>`;
    document.getElementById(containerId).innerHTML = html;
    document.querySelectorAll(`#${containerId} th`).forEach(th => {
      th.addEventListener('click', () => {
        const column = th.getAttribute('data-column');
        const excludeLastRow = containerId === 'seatsSummaryContainer';
        const sortedData = sortTableData(data, column, 'asc', excludeLastRow);
        renderTable(containerId, sortedData);
      });
    });
  }

  function createRestSeatsTable(votesData, keyToLabel, total_restSeats) {
    const rows = [];
    for (let i = 1; i <= total_restSeats; i++) {
      const party = votesData.parties.find(p => p.restSeats.get(i) === 1);
      if (party) rows.push({ 'Restzetel': i, 'Partij': keyToLabel.get(party.key) });
    }
    renderTable('restSeatContainer', rows);
  }

  function calculateVotesShortAndSurplus(votesData) {
    const votesShortData = new Map();
    const surplusVotesData = new Map();
    const total_restSeats = 150 - votesData.parties.reduce((acc, p) => acc + p.fullSeats, 0);
    const total_votes = votesData.parties.reduce((acc, p) => acc + parseInt(p.results.current.votes), 0);
    const votes_per_seat = total_votes / 150;
    const avgNext = new Map();
    let maxAvgLastRest = 0;
    votesData.parties.forEach(p => {
      if (p.fullSeats === 0) {
        votesShortData.set(p.key, votes_per_seat - p.results.current.votes);
      } else {
        const curTotalSeats = p.fullSeats + Array.from(p.restSeats.values()).reduce((a, b) => a + b, 0);
        const nextAvg = p.results.current.votes / (curTotalSeats + 1);
        if (p.restSeats.get(total_restSeats) === 1) {
          maxAvgLastRest = p.results.current.votes / curTotalSeats;
          avgNext.set(p.key, maxAvgLastRest);
        } else {
          avgNext.set(p.key, nextAvg);
        }
      }
    });
    avgNext.forEach((nextAvg, key) => {
      const party = votesData.parties.find(pp => pp.key === key);
      const curTotalSeats = party.fullSeats + Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
      if (nextAvg < maxAvgLastRest) {
        const votesNeeded = (maxAvgLastRest - nextAvg) * (curTotalSeats + 1);
        const surplus = party.results.current.votes - (curTotalSeats * maxAvgLastRest);
        surplusVotesData.set(key, surplus);
        votesShortData.set(key, votesNeeded);
      } else {
        const secondHighest = Array.from(avgNext.values()).sort((a, b) => b - a)[1] || nextAvg;
        const avgCurrentLast = (party.results.current.votes / curTotalSeats);
        const surplus = Math.floor((avgCurrentLast - secondHighest) * curTotalSeats);
        const votesNeed = Math.ceil((secondHighest + 1) * (curTotalSeats + 1)) - party.results.current.votes;
        surplusVotesData.set(key, surplus);
        votesShortData.set(key, votesNeed);
      }
    });
    return { votesShortData, surplusVotesData };
  }

function createSeatsSummaryTable(votesData, keyToLabelLong, keyToListNumber, opts = {}) {
    const hasVotes = opts.hasVotes !== false;
    const calc = hasVotes ? calculateVotesShortAndSurplus(votesData) : { votesShortData: new Map(), surplusVotesData: new Map() };
    const votesShortData = calc.votesShortData;
    const surplusVotesData = calc.surplusVotesData;
    const rows = [];
    let totalFull = 0, totalRest = 0;
    votesData.parties.forEach(p => {
      const name = keyToLabelLong.get(p.key) || keyToLabelLong.get(p.key?.toString?.()) || 'Onbekend';
      if (!name.toUpperCase().includes('OVERIG')) {
        const listNumber = keyToListNumber.get(p.key) || '';
        let full = '', restCount = '', totalSeats = '', surplus = '', shortv = '';
        if (hasVotes) {
          restCount = Array.from(p.restSeats.values()).reduce((a, b) => a + b, 0);
          full = p.fullSeats;
          totalFull += full; totalRest += restCount;
          const sRaw = (full === 0 && restCount === 0) ? parseInt(p.results.current.votes) : Math.ceil(surplusVotesData.get(p.key) || 0);
          const shRaw = Math.ceil(votesShortData.get(p.key) || 0);
          totalSeats = full + restCount;
          surplus = (typeof sRaw === 'number' && !isNaN(sRaw) && sRaw !== 0) ? sRaw.toLocaleString('nl-NL') : '';
          shortv = (typeof shRaw === 'number' && !isNaN(shRaw) && shRaw !== 0) ? shRaw.toLocaleString('nl-NL') : '';
        }
        rows.push({
          'Lijst': listNumber,
          'Partij': name,
          'Volle zetels': full,
          'Rest zetels': restCount,
          'Totaal zetels': totalSeats,
          'Stemmen over': surplus,
          'Stemmen tekort': shortv
        });
      }
    });
    if (hasVotes) rows.push({ 'Lijst': '', 'Partij': 'Totaal', 'Volle zetels': totalFull, 'Rest zetels': totalRest, 'Totaal zetels': totalFull + totalRest });
    function customSort(data) {
      if (!hasVotes) return data;
      return data.slice(0, -1).sort((a, b) => {
        const aVS = a['Totaal zetels'], bVS = b['Totaal zetels'];
        if (aVS > bVS) return -1; if (aVS < bVS) return 1;
        const av = parseInt((a['Stemmen tekort'] || '').toString().replace(/[\.,]/g, ''), 10) || 0;
        const bv = parseInt((b['Stemmen tekort'] || '').toString().replace(/[\.,]/g, ''), 10) || 0;
        if (av < bv) return -1; if (av > bv) return 1; return 0;
      }).concat(data[data.length - 1]);
    }
    renderTable('seatsSummaryContainer', customSort(rows));
  }

  function showLatestRestSeatImpact(votesData, keyToLabelShort) {
    let latestParty = null, highest = 0;
    votesData.parties.forEach(p => {
      p.restSeats.forEach((v, k) => { if (k > highest) { highest = k; latestParty = p; } });
    });
    const lastName = latestParty ? keyToLabelShort.get(latestParty.key) : '';
    const { votesShortData } = calculateVotesShortAndSurplus(votesData);
    let lowest = Number.MAX_SAFE_INTEGER, losing = '';
    votesShortData.forEach((votesShort, key) => {
      if (votesShort != null && votesShort < lowest) { lowest = votesShort; losing = keyToLabelShort.get(key); }
    });
    const msg = `Laatste restzetel gaat naar: <span style="font-weight: bold; color: green;">${lastName || '-'}</span>, dit gaat ten koste van: <span style="font-weight: bold; color: red;">${losing || '-'}</span>`;
    document.getElementById('latestRestSeatImpactContainer').innerHTML = msg;
  }

  // Note: top badge (Alle kiesregio's compleet / countdown) is managed by AutoRefresh

  function showLatestUpdateFromNos(nosData, prefix = 'NOS') {
    if (nosData && nosData.gemeentes && nosData.gemeentes.length > 0) {
      const sorted = nosData.gemeentes.sort((a, b) => new Date(b.publicatie_datum_tijd) - new Date(a.publicatie_datum_tijd));
      const latest = sorted[0];
      const ts = new Date(latest.publicatie_datum_tijd).toLocaleString();
      const name = latest.gemeente.naam;
      const status = latest.status;
      const el = document.getElementById('latestUpdateFromNos');
      if (el) el.textContent = `Laatste update ${prefix}: ${ts} uit ${name} (${status})`;
    }
  }

  async function loadZetels(year) {
    // Clear containers
    ['seatsSummaryContainer','restSeatContainer','voteAverageContainer','latestRestSeatImpactContainer','latestUpdateFromNos'].forEach(id => {
      const el = document.getElementById(id); if (el) el.innerHTML = '';
    });
    const completedEl = document.getElementById('completedRegionsCount'); if (completedEl) completedEl.innerHTML = '';

    // Fetch labels and data
    const { list: partyLabelsList, keyToLabelShort, keyToLabelLong, keyToListNumber } = await fetchPartyLabels(year);
    const [anpVotes, lastUpdate, nosIndex, kiesraadData] = await Promise.all([
      fetchANPVotes(year), fetchANPLastUpdate(year), fetchNOSIndex(year), tryFetchKiesraadVotes(year)
    ]);
    // Badge visibility is centralized in AutoRefresh; do not set here
    if (nosIndex) showLatestUpdateFromNos(nosIndex);

    let votesData = anpVotes;
    if (kiesraadData && Array.isArray(kiesraadData)) {
      const mapped = mapKiesraadDataToANPFormat(kiesraadData, partyLabelsList);
      const totalANP = sumVotes(anpVotes);
      const totalKR = sumVotes(mapped);
      if (totalKR > totalANP) votesData = mapped;
    }

    // Check if we have any votes at all; if not, render blanks instead of 0/NaN
    const totalVotes = sumVotes(votesData);
    if (totalVotes > 0) {
      // Compute seats
      let { votesData: updatedData, total_restSeats } = calculateFullAndRestSeats(votesData);
      updatedData = assignRestSeats({ votesData: updatedData, total_restSeats });

      // Vote average table with highlight
      let tableData = createVoteAverageTableData(updatedData, keyToLabelShort, total_restSeats);
      const maxValues = {};
      for (let i = 1; i <= total_restSeats; i++) {
        maxValues[`${i}e`] = Math.max(...tableData.map(row => extractFraction(row[`${i}e`])));
      }
      tableData.forEach(row => {
        for (let i = 1; i <= total_restSeats; i++) {
          const dec = extractFraction(row[`${i}e`]);
          const frac = dec % 1 > 0 ? decimalToFraction(dec % 1) : '';
          const [num, den] = (frac || '/').split('/');
          const html = `
            <div class="averagevotetable-cell">
              <span style="margin-right: 5px;">${Math.floor(dec)}</span>
              ${frac ? createFractionHTML(num, den) : ''}
            </div>`;
          row[`${i}e`] = html;
          if (dec === maxValues[`${i}e`]) row[`${i}e`] = `<div class='highest-value'>${row[`${i}e`]}</div>`;
        }
      });
      renderTable('voteAverageContainer', tableData);

      // Rest seats table
      createRestSeatsTable(updatedData, keyToLabelShort, total_restSeats);

      // Seats summary
      createSeatsSummaryTable(updatedData, keyToLabelLong, keyToListNumber, { hasVotes: true });

      // Latest rest seat impact
      showLatestRestSeatImpact(updatedData, keyToLabelShort);
    } else {
      // No votes yet: clear detail tables and render summary with blanks
      ['voteAverageContainer','restSeatContainer'].forEach(id => { const el=document.getElementById(id); if (el) el.innerHTML=''; });
      const impactEl = document.getElementById('latestRestSeatImpactContainer');
      if (impactEl) impactEl.innerHTML = `Laatste restzetel gaat naar: <span style="font-weight: bold; color: green;">-</span>, dit gaat ten koste van: <span style=\"font-weight: bold; color: red;\">-</span>`;
      createSeatsSummaryTable(votesData, keyToLabelLong, keyToListNumber, { hasVotes: false });
    }
  }

  // Expose
  window.RestzetelsApp = { loadZetels };
})();
