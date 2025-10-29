// Unified year-aware loader for seat distribution (restzetels) across 2021, 2023, 2025

(function () {
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);
  const lastStateByYear = new Map(); // year -> { totalVotes, seats: Map(key->count) }
  let __restImpactSinceInterval = null; // updates the "sinds" label

  async function tryFetchKiesraadVotes(year) {
    // Unified local file with per-year keys
    const url = `data/votes_kiesraad.json`;
    const data = await Data.safeJSON(url);
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

  // Fraction helpers: keep original fraction behavior for exact same output
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
  const createFractionHTML = (n, d) => (window.UI && UI.createFractionHTML) ? UI.createFractionHTML(n, d) : `${n}/${d}`;

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
    // Track per-party rest count to avoid repeated Map reductions
    votesData.parties.forEach(p => { p._restCount = 0; });
    for (let i = 1; i <= total_restSeats; i++) {
      let maxVoteAverage = -Infinity;
      let partyWithMax = null;
      for (let idx = 0; idx < votesData.parties.length; idx++) {
        const p = votesData.parties[idx];
        if (p.fullSeats > 0) {
          const denom = p.fullSeats + p._restCount + 1;
          const va = Math.round(p.results.current.votes / denom);
          if (va > maxVoteAverage) { maxVoteAverage = va; partyWithMax = p; }
        }
      }
      if (partyWithMax) { partyWithMax._restCount += 1; partyWithMax.restSeats.set(i, 1); }
    }
    return votesData;
  }

  function createVoteAverageTableData(votesData, keyToLabel, total_restSeats) {
    const tableData = [];
    votesData.parties.forEach(party => {
      if (party.fullSeats > 0) {
        const row = { 'Partij': keyToLabel.get(party.key), _votes: parseInt(party.results.current.votes)||0 };
        const positions = Array.from(party.restSeats.keys()).sort((a,b)=>a-b);
        let taken = 0;
        for (let i = 1; i <= total_restSeats; i++) {
          while (taken < positions.length && positions[taken] < i) taken++;
          const voteAverage = party.results.current.votes / (party.fullSeats + taken + 1);
          row[`_num_${i}e`] = voteAverage;
          row[`${i}e`] = '';
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
      if (/^\d+e$/.test(column)) {
        const key = `_num_${column}`;
        const A = typeof a[key] === 'number' ? a[key] : 0;
        const B = typeof b[key] === 'number' ? b[key] : 0;
        return sortStates[column] === 'asc' ? (A - B) : (B - A);
      }
      if (column === 'Totaal zetels') {
        const A = typeof a._totalSeats === 'number' ? a._totalSeats : parseInt((a[column]||'').toString(),10) || 0;
        const B = typeof b._totalSeats === 'number' ? b._totalSeats : parseInt((b[column]||'').toString(),10) || 0;
        return sortStates[column] === 'asc' ? (A - B) : (B - A);
      }
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
    const columns = Object.keys(data[0]).filter(k => !k.startsWith('_'));
    // Right-align numeric columns for known tables
    const numericCols = new Set();
    if (containerId === 'seatsSummaryContainer') {
      ['Lijst','Volle zetels','Rest zetels','Totaal zetels','Stemmen over','Stemmen tekort'].forEach(c=>numericCols.add(c));
    } else if (containerId === 'restSeatContainer') {
      ['Restzetel'].forEach(c=>numericCols.add(c));
    }
    const header = columns.map(col => {
      let icon = '';
      if (sortStates[col] === 'asc') icon = '&#9650;'; else if (sortStates[col] === 'desc') icon = '&#9660;';
      const cls = numericCols.has(col) ? ' class="num"' : '';
      return `<th data-column="${col}"${cls}>${col} <span class="sort-icon">${icon}</span></th>`;
    }).join('');
    const rows = data.map((row, i) => {
      const cells = columns.map(col => {
        const val = row[col];
        const display = (val === undefined || val === null) ? '' : val;
        const isNum = numericCols.has(col);
        const needsSeatTotalCls = (containerId === 'seatsSummaryContainer' && col === 'Totaal zetels');
        let cls = '';
        let extra = '';
        if (isNum) cls += ' num';
        if (needsSeatTotalCls) cls += ' seat-total-td';
        if (needsSeatTotalCls && row._totalSeatsTitle) {
          // Immediate hover tooltip via CSS using data-tip (avoid native title delay)
          extra += ` data-tip="${String(row._totalSeatsTitle).replace(/"/g,'&quot;')}"`;
        }
        const classAttr = cls ? ` class=\"${cls.trim()}\"` : '';
        return `<td${classAttr}${extra}>${display}</td>`;
      }).join('');
      // Mark total row only when explicitly labeled (avoids mislabeling when there is no total row)
      const rowClass = (containerId === 'seatsSummaryContainer' && String(row['Partij']||'').trim() === 'Totaal') ? 'total-row' : '';
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

  function updateSeatStripTooltip(votesData, keyToLabelShort, total_restSeats) {
    const container = document.getElementById('seatStripTooltip');
    if (!container) return;
    const parts = [];
    parts.push('<ul class="seat-list">');
    for (let i = 1; i <= total_restSeats; i++) {
      const party = votesData.parties.find(p => p.restSeats.get(i) === 1);
      if (!party) continue;
      const label = keyToLabelShort.get(party.key) || '';
      const title = `${i}e: ${label}`;
      parts.push(`<li class="seat-list-item" data-key="${String(party.key)}" title="${title}">`+
                 `<span class="seat-index">${i}e</span>`+
                 `<span class="chip chip--party">${label}</span>`+
                 `</li>`);
    }
    parts.push('</ul>');
    container.innerHTML = parts.join('');

    container.querySelectorAll('.seat-list-item').forEach(el => {
      el.addEventListener('click', () => {
        const key = el.getAttribute('data-key');
        const label = keyToLabelShort.get(key) || '';
        const rows = document.querySelectorAll('#voteAverageContainer tbody tr');
        for (const tr of rows) {
          const first = tr.querySelector('td');
          if (first && first.textContent.trim() === label) {
            tr.scrollIntoView({ behavior: 'smooth', block: 'center' });
            tr.classList.add('row-pulse');
            setTimeout(()=> tr.classList.remove('row-pulse'), 1200);
            break;
          }
        }
      });
    });
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
        const restCount = (typeof p._restCount === 'number') ? p._restCount : Array.from(p.restSeats.values()).reduce((a, b) => a + b, 0);
        const curTotalSeats = p.fullSeats + restCount;
        const nextAvg = p.results.current.votes / (curTotalSeats + 1);
        if (p.restSeats.get(total_restSeats) === 1) {
          maxAvgLastRest = p.results.current.votes / curTotalSeats;
          avgNext.set(p.key, maxAvgLastRest);
        } else {
          avgNext.set(p.key, nextAvg);
        }
      }
    });
    // Precompute global second-highest next average once
    const sortedAvgs = Array.from(avgNext.values()).sort((a, b) => b - a);
    const globalSecond = (sortedAvgs.length > 1) ? sortedAvgs[1] : (sortedAvgs[0] || 0);
    avgNext.forEach((nextAvg, key) => {
      const party = votesData.parties.find(pp => pp.key === key);
      const restCount = (typeof party._restCount === 'number') ? party._restCount : Array.from(party.restSeats.values()).reduce((a, b) => a + b, 0);
      const curTotalSeats = party.fullSeats + restCount;
      if (nextAvg < maxAvgLastRest) {
        const votesNeeded = (maxAvgLastRest - nextAvg) * (curTotalSeats + 1);
        const surplus = party.results.current.votes - (curTotalSeats * maxAvgLastRest);
        surplusVotesData.set(key, surplus);
        votesShortData.set(key, votesNeeded);
      } else {
        const secondHighest = globalSecond || nextAvg;
        const avgCurrentLast = (party.results.current.votes / curTotalSeats);
        const surplus = Math.floor((avgCurrentLast - secondHighest) * curTotalSeats);
        const votesNeed = Math.ceil((secondHighest + 1) * (curTotalSeats + 1)) - party.results.current.votes;
        surplusVotesData.set(key, surplus);
        votesShortData.set(key, votesNeed);
      }
    });
    return { votesShortData, surplusVotesData };
  }

function createSeatsSummaryTable(votesData, keyToLabelLong, keyToListNumber, keyToLabelShort, opts = {}) {
    const hasVotes = opts.hasVotes !== false;
    const exitLatest = (opts && opts.exitLatest) || null; // Map normalized short -> seats (latest)
    const exitSeries = (opts && opts.exitSeries) || null; // Map normalized short -> [{t,seats}]
    const safeData = votesData && Array.isArray(votesData.parties) ? votesData : { parties: [] };
    const calc = hasVotes ? calculateVotesShortAndSurplus(safeData) : { votesShortData: new Map(), surplusVotesData: new Map() };
    const votesShortData = calc.votesShortData;
    const surplusVotesData = calc.surplusVotesData;
    const rows = [];
    let totalFull = 0, totalRest = 0;
    safeData.parties.forEach(p => {
      let rowTotalSeatsNum; // ensure per-row numeric total for correct sorting
      let rowTotalSeatsTitle; // optional hover title for td
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
          const tsNum = full + restCount;
          totalSeats = tsNum;
          surplus = (typeof sRaw === 'number' && !isNaN(sRaw) && sRaw !== 0) ? sRaw.toLocaleString('nl-NL') : '';
          shortv = (typeof shRaw === 'number' && !isNaN(shRaw) && shRaw !== 0) ? shRaw.toLocaleString('nl-NL') : '';
          // Exitpoll diff rendering + hover title
          if (exitLatest && keyToLabelShort) {
            const norm = (s) => (s||'').toString().trim().toUpperCase();
            const shortLabel = keyToLabelShort.get(p.key) || keyToLabelShort.get(p.key?.toString?.()) || '';
            const expected = exitLatest.get(norm(shortLabel));
            if (typeof expected === 'number' && !isNaN(expected)) {
              const diff = (tsNum || 0) - expected;
              // Build full timestamp list for tooltip if available (multiline)
              let tooltipText = '';
              if (exitSeries && exitSeries.has(norm(shortLabel))) {
                const series = exitSeries.get(norm(shortLabel));
                const lines = ['Exitpoll Ipsos'];
                series.forEach(it => { lines.push(`${it.t} ${it.seats} zetels`); });
                tooltipText = lines.join('\n');
              } else {
                tooltipText = `Exitpoll Ipsos\nlatest ${expected} zetels`;
              }
              const title = 'Exitpoll Ipsos';
              if (diff !== 0) {
                const cls = diff > 0 ? 'seat-diff seat-diff--pos' : 'seat-diff seat-diff--neg';
                const sign = diff > 0 ? '+' : '';
                const diffHtml = `<span class=\"${cls}\">(${sign}${diff})</span>`;
                totalSeats = `<span class=\"seat-total-wrap\" title=\"${title}\">${tsNum} ${diffHtml}</span>`;
              } else {
                totalSeats = `<span class=\"seat-total-wrap\" title=\"${title}\">${tsNum}</span>`;
              }
              // Store full multiline tooltip on the row; td will render instant tooltip from data-tip
              rowTotalSeatsTitle = tooltipText;
            }
          }
          // keep numeric for sorting
          rowTotalSeatsNum = tsNum;
        }
        const outRow = {
          'Lijst': listNumber,
          'Partij': name,
          'Volle zetels': full,
          'Rest zetels': restCount,
          'Totaal zetels': totalSeats,
          'Stemmen over': surplus,
          'Stemmen tekort': shortv
        };
        if (typeof rowTotalSeatsNum !== 'undefined') outRow._totalSeats = rowTotalSeatsNum;
        if (rowTotalSeatsTitle) outRow._totalSeatsTitle = rowTotalSeatsTitle;
        rows.push(outRow);
      }
    });
    if (hasVotes) rows.push({ 'Lijst': '', 'Partij': 'Totaal', 'Volle zetels': totalFull, 'Rest zetels': totalRest, 'Totaal zetels': totalFull + totalRest });
    function customSort(data) {
      if (!hasVotes) return data;
      return data.slice(0, -1).sort((a, b) => {
        const aVS = (typeof a._totalSeats === 'number') ? a._totalSeats : parseInt((a['Totaal zetels']||'').toString(),10) || 0;
        const bVS = (typeof b._totalSeats === 'number') ? b._totalSeats : parseInt((b['Totaal zetels']||'').toString(),10) || 0;
        if (aVS > bVS) return -1; if (aVS < bVS) return 1;
        const av = parseInt((a['Stemmen tekort'] || '').toString().replace(/[\.,]/g, ''), 10) || 0;
        const bv = parseInt((b['Stemmen tekort'] || '').toString().replace(/[\.,]/g, ''), 10) || 0;
        if (av < bv) return -1; if (av > bv) return 1; return 0;
      }).concat(data[data.length - 1]);
    }
    renderTable('seatsSummaryContainer', customSort(rows));
  }
  // (legacy simple rest-impact function removed)


  // Enhanced rest-seat impact: persistent signature and live "sinds" timer
  function showLatestRestSeatImpactSince(year, votesData, keyToLabelShort, finalized) {
    const impactEl = document.getElementById('latestRestSeatImpactContainer');
    if (!impactEl || !votesData || !votesData.parties) return;
    let latestParty = null, highest = 0;
    votesData.parties.forEach(p => {
      const rs = p && p.restSeats;
      if (rs && typeof rs.forEach === 'function') {
        rs.forEach((v, k) => { if (k > highest) { highest = k; latestParty = p; } });
      }
    });
    const winnerKey = latestParty ? latestParty.key : '';
    const winnerName = winnerKey ? (keyToLabelShort.get(winnerKey) || '') : '';
    const { votesShortData } = calculateVotesShortAndSurplus(votesData);
    let lowest = Number.MAX_SAFE_INTEGER, losingKey = null;
    votesShortData.forEach((votesShort, key) => {
      if (votesShort != null && votesShort < lowest) { lowest = votesShort; losingKey = key; }
    });
    const losingName = (losingKey != null && losingKey !== '') ? (keyToLabelShort.get(losingKey) || '') : '';
    const hasParties = !!(winnerKey || (losingKey != null && losingKey !== ''));

    const y = String(year);
    const sigKey = `restImpactSig:v1:${y}`;
    const sinceKey = `restImpactSince:v1:${y}`;
    const sig = `${winnerKey || ''}|${(losingKey != null ? losingKey : '') || ''}|${highest || 0}`;
    const prevSig = window.localStorage.getItem(sigKey) || '';
    let sinceTs = parseInt(window.localStorage.getItem(sinceKey) || '0', 10) || 0;
    if (sig !== prevSig || !sinceTs) {
      sinceTs = Date.now();
      try {
        window.localStorage.setItem(sigKey, sig);
        window.localStorage.setItem(sinceKey, String(sinceTs));
      } catch(e){}
    }
    const relTime = (ms) => {
      if (!ms) return '';
      const s = Math.max(0, Math.floor((Date.now() - ms) / 1000));
      if (s < 60) return `${s}s geleden`;
      const m = Math.floor(s/60); if (m < 60) return `${m}m geleden`;
      const h = Math.floor(m/60); if (h < 24) return `${h}u geleden`;
      const d = Math.floor(h/24); return `${d}d geleden`;
    };
    // Show since only when not finalized and we have parties; otherwise show single line without since
    if (finalized || !hasParties) {
      impactEl.innerHTML = `
        <div class="impact-main">Laatste restzetel gaat naar: <span style="font-weight: bold; color: green;">${winnerName || '-'}</span>, dit gaat ten koste van: <span style="font-weight: bold; color: red;">${losingName || '-'}</span></div>
      `;
      if (__restImpactSinceInterval) { clearInterval(__restImpactSinceInterval); __restImpactSinceInterval = null; }
    } else {
      impactEl.innerHTML = `
        <div class="impact-main">Laatste restzetel gaat naar: <span style="font-weight: bold; color: green;">${winnerName || '-'}</span>, dit gaat ten koste van: <span style="font-weight: bold; color: red;">${losingName || '-'}</span></div>
        <div class="impact-since muted small">(sinds <span id="restImpactSinceSpan"></span>)</div>
      `;
      const sinceSpan = document.getElementById('restImpactSinceSpan');
      const updateSince = () => { if (sinceSpan) sinceSpan.textContent = relTime(sinceTs); };
      updateSince();
      if (__restImpactSinceInterval) { clearInterval(__restImpactSinceInterval); __restImpactSinceInterval = null; }
      __restImpactSinceInterval = setInterval(updateSince, 1000);
    }
  }

  // Note: top badge (Alle kiesregio's compleet / countdown) is managed by AutoRefresh

  function showLatestUpdateFromNos(nosData, prefix = 'NOS') {
    if (nosData && nosData.gemeentes && nosData.gemeentes.length > 0) {
      const sorted = nosData.gemeentes.slice().sort((a, b) => new Date(b.publicatie_datum_tijd) - new Date(a.publicatie_datum_tijd));
      const latest = sorted[0];
      const pad2=(n)=>String(n).padStart(2,'0'); const fmt=(ms)=>{const d=new Date(ms);const dd=pad2(d.getDate());const mm=pad2(d.getMonth()+1);const yyyy=d.getFullYear();const HH=pad2(d.getHours());const MM=pad2(d.getMinutes());const SS=pad2(d.getSeconds());return `${dd}-${mm}-${yyyy} ${HH}:${MM}${SS!=='00'?':'+SS:''}`;}; const ts = latest.publicatie_datum_tijd ? fmt(new Date(latest.publicatie_datum_tijd).getTime()) : '';
      const name = latest.gemeente.naam;
      const status = latest.status;
      const el = document.getElementById('latestUpdateFromNos');
      if (el) el.textContent = `Laatste update ${prefix}: ${ts} uit ${name} (${status})`;
    }
  }

  function buildRestzetelShare(year, data, maps, finalized){
    const { keyToLabelShort } = maps;
    let latestParty = null, highest = 0;
    (data.parties||[]).forEach(p => {
      const rs = p && p.restSeats;
      if (rs && typeof rs.forEach === 'function') { rs.forEach((v,k)=>{ if (k>highest){ highest=k; latestParty=p; } }); }
    });
    const winnerKey = latestParty ? latestParty.key : '';
    const winnerName = winnerKey ? (keyToLabelShort.get(winnerKey) || '') : '-';
    const { votesShortData, surplusVotesData } = calculateVotesShortAndSurplus(data);
    let lowest = Number.MAX_SAFE_INTEGER, losingKey = null;
    votesShortData.forEach((v,k)=>{ if (v!=null && v<lowest){ lowest=v; losingKey=k; } });
    const loserName = (losingKey!=null) ? (keyToLabelShort.get(losingKey) || '') : '-';
    const over = (winnerKey && surplusVotesData.get(winnerKey)) ? Math.ceil(surplusVotesData.get(winnerKey)).toLocaleString('nl-NL') : '-';
    const tekort = (losingKey!=null && votesShortData.get(losingKey)) ? Math.ceil(votesShortData.get(losingKey)).toLocaleString('nl-NL') : '-';
    const y = String(year);
    const sinceKey = `restImpactSince:v1:${y}`;
    const sinceTs = parseInt(window.localStorage.getItem(sinceKey)||'0',10)||0;
    // Twitter/WA intent: include summary text
    const text = `Laatste restzetel gaat naar: ${winnerName} (stemmen over: ${over}), dit gaat ten koste van: ${loserName} (stemmen tekort: ${tekort})\n\nLive updates via wiekrijgtderestzetel.nl`;
    return { text };
  }

  function buildSeatsShare(year, data, maps){
    const { keyToLabelLong } = maps;
    const { votesShortData, surplusVotesData } = calculateVotesShortAndSurplus(data);
    const rows = [];
    (data.parties||[]).forEach(p => {
      const name = keyToLabelLong.get(p.key) || keyToLabelLong.get(p.key?.toString?.()) || '';
      if (!name || name.toUpperCase().includes('OVERIG')) return;
      const rest = Array.from(p.restSeats?.values?.() || []).reduce((a,b)=>a+b,0);
      const full = p.fullSeats || 0;
      const total = full + rest;
      if (total <= 0) return;
      const over = Math.ceil(surplusVotesData.get(p.key) || 0);
      const tekort = Math.ceil(votesShortData.get(p.key) || 0);
      rows.push({ name, full, rest, over, tekort, total });
    });
    rows.sort((a,b)=> b.total - a.total || (a.tekort - b.tekort));
    const lines = rows.slice(0, 10).map(r => `${r.name}: ${r.full}v, ${r.rest}r (over ${r.over>0?r.over.toLocaleString('nl-NL'):'-'}, tekort ${r.tekort>0?r.tekort.toLocaleString('nl-NL'):'-'})`);
    if (rows.length > 10) lines.push('…');
    const header = 'Zeteloverzicht:';
    const text = [header].concat(lines).join('\n');
    const url = buildShareURL();
    return { text, url };
  }

  function setupShareHandlers(year, data, maps, finalized){
    const impactX = document.getElementById('impactShareX');
    const impactWeb = document.getElementById('impactShareWeb');
    const impactWA = document.getElementById('impactShareWA');
    const rest = buildRestzetelShare(year, data, maps, finalized);
    const seats = buildSeatsShare(year, data, maps);
    const openTwitter = (payload) => {
      const q = new URLSearchParams({ text: payload.text || '' });
      const tw = `https://x.com/intent/post?${q.toString()}`;
      try { window.open(tw, '_blank', 'noopener'); } catch(e) { window.location.href = tw; }
    };
    const doShare = (payload) => {
      if (navigator.share) {
        navigator.share({ title: 'Wie krijgt de restzetel?', text: payload.text || '', url: 'https://wiekrijgtderestzetel.nl' }).catch(()=>{});
      } else {
        openTwitter(payload);
      }
    };
    if (impactX) impactX.onclick = () => { openTwitter(rest); };
    if (impactWeb) impactWeb.onclick = async () => {
      try {
        const f = await buildShareImageFile(year, data, maps, finalized);
        if (navigator.canShare && navigator.canShare({ files:[f] })) {
          try { await navigator.share({ files:[f], title:'Wie krijgt de restzetel?', text: buildShareURL() }); } catch(e) {}
          return;
        }
      } catch(e) {}
      doShare(rest);
    };
    if (impactWA) impactWA.onclick = () => {
      const wa = `https://wa.me/?text=${encodeURIComponent(rest.text || 'wiekrijgtderestzetel.nl')}`;
      try { window.open(wa, '_blank', 'noopener'); } catch(e) { window.location.href = wa; }
    };
  }

  async function buildShareImageFile(year, data, maps, finalized){
    const { keyToLabelShort, keyToLabelLong } = maps;
    const canvas = document.createElement('canvas');
    const W = 1200, H = 630; canvas.width = W; canvas.height = H; const ctx = canvas.getContext('2d');
    // Background
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0,0,W,H);
    // Title + year chip
    ctx.fillStyle = '#0f172a'; ctx.font = '600 44px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    ctx.fillText('Wie krijgt de restzetel?', 40, 70);
    ctx.fillStyle = '#e5e7eb'; ctx.fillRect(40, 84, 130, 28);
    ctx.fillStyle = '#374151'; ctx.font = '600 18px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    ctx.fillText(`Jaar ${year}`, 50, 104);
    // Restzetel status
    let latestParty = null, highest = 0;
    (data.parties||[]).forEach(p => { const rs = p && p.restSeats; if (rs && typeof rs.forEach==='function'){ rs.forEach((v,k)=>{ if (k>highest){ highest=k; latestParty=p; } }); } });
    const winnerKey = latestParty ? latestParty.key : '';
    const winnerName = winnerKey ? (keyToLabelShort.get(winnerKey) || '') : '-';
    const { votesShortData, surplusVotesData } = calculateVotesShortAndSurplus(data);
    let lowest = Number.MAX_SAFE_INTEGER, losingKey = null;
    votesShortData.forEach((v,k)=>{ if (v!=null && v<lowest){ lowest=v; losingKey=k; } });
    const loserName = (losingKey!=null) ? (keyToLabelShort.get(losingKey) || '') : '-';
    const over = (winnerKey && surplusVotesData.get(winnerKey)) ? Math.ceil(surplusVotesData.get(winnerKey)).toLocaleString('nl-NL') : '-';
    const tekort = (losingKey!=null && votesShortData.get(losingKey)) ? Math.ceil(votesShortData.get(losingKey)).toLocaleString('nl-NL') : '-';
    ctx.fillStyle = '#111827'; ctx.font = '600 28px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    ctx.fillText(`Laatste restzetel: ${winnerName} → ${loserName}`, 40, 150);
    ctx.fillStyle = '#059669'; ctx.font = '600 22px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    ctx.fillText(`Over: ${over}`, 40, 185);
    ctx.fillStyle = '#b91c1c'; ctx.fillText(`Tekort: ${tekort}`, 220, 185);
    // Sinds
    const sinceKey = `restImpactSince:v1:${String(year)}`;
    const sinceTs = parseInt(window.localStorage.getItem(sinceKey)||'0',10)||0;
    if (!finalized && winnerKey) { ctx.fillStyle = '#6b7280'; ctx.font = '500 18px system-ui, -apple-system, Segoe UI, Roboto, sans-serif'; ctx.fillText(`Sinds ${relTime(sinceTs)}`, 40, 210); }
    // Seats mini table
    const rows = [];
    (data.parties||[]).forEach(p => {
      const name = keyToLabelLong.get(p.key) || keyToLabelLong.get(p.key?.toString?.()) || '';
      if (!name || name.toUpperCase().includes('OVERIG')) return;
      const rest = Array.from(p.restSeats?.values?.() || []).reduce((a,b)=>a+b,0);
      const full = p.fullSeats || 0; const total = full + rest; if (total<=0) return;
      const overv = Math.ceil((surplusVotesData.get(p.key)||0));
      const tekortv = Math.ceil((votesShortData.get(p.key)||0));
      rows.push({ name, full, rest, over: overv, tekort: tekortv, total });
    });
    rows.sort((a,b)=> b.total - a.total || (a.tekort - b.tekort));
    const tableX = 40, tableY = 250, rowH = 34; const maxRows = 10; // fits
    ctx.fillStyle = '#6b7280'; ctx.font = '600 18px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    const cols = [
      { label:'Partij',   w: 480, align:'left'  },
      { label:'Zetels',  w: 100, align:'right' },
      { label:'Stemmen', w: 180, align:'right' },
      { label:'Over',    w: 160, align:'right' },
      { label:'Tekort',  w: 160, align:'right' }
    ];
    let x = tableX, y = tableY;
    cols.forEach(c=>{ if (c.align==='right'){ ctx.textAlign='right'; ctx.fillText(c.label, x + c.w, y); ctx.textAlign='left'; } else { ctx.fillText(c.label, x, y);} x += c.w; });
    ctx.font = '500 20px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    rows.slice(0, maxRows).forEach((r,i)=>{
      let cx = tableX; const yy = y + (i+1)*rowH;
      // Partij
      ctx.fillStyle = '#111827';
      // truncate name if too long
      const nm = r.name.length>34 ? (r.name.slice(0,31)+'…') : r.name;
      ctx.fillText(nm, cx, yy); cx += cols[0].w;
      // numbers
      ctx.textAlign='right'; ctx.fillStyle='#111827';
      ctx.fillText(String(r.total), cx + cols[1].w, yy); cx += cols[1].w;
      ctx.fillText(r.votes>0 ? r.votes.toLocaleString('nl-NL') : '0', cx + cols[2].w, yy); cx += cols[2].w;
      ctx.fillStyle = '#065f46'; ctx.fillText(r.over>0 ? r.over.toLocaleString('nl-NL') : '-', cx + cols[3].w, yy); cx += cols[3].w;
      ctx.fillStyle = '#b91c1c'; ctx.fillText(r.tekort>0 ? r.tekort.toLocaleString('nl-NL') : '-', cx + cols[4].w, yy);
      ctx.textAlign='left'; ctx.fillStyle='#111827';
    });
    // Footer URL
    ctx.fillStyle = '#6b7280'; ctx.font = '500 18px system-ui, -apple-system, Segoe UI, Roboto, sans-serif';
    ctx.fillText('wiekrijgtderestzetel.nl', 40, H-24);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
    return new File([blob], 'restzetel.png', { type: 'image/png' });
  }
  async function loadZetels(year) {
    // Clear containers
    ['seatsSummaryContainer','seatStripTooltip','voteAverageContainer','latestRestSeatImpactContainer','latestUpdateFromNos'].forEach(id => {
      const el = document.getElementById(id); if (el) el.innerHTML = '';
    });
    if (__restImpactSinceInterval) { try { clearInterval(__restImpactSinceInterval); } catch(e){} __restImpactSinceInterval = null; }
    const completedEl = document.getElementById('completedRegionsCount'); if (completedEl) completedEl.innerHTML = '';

    // Fetch labels and data
    const { list: partyLabelsList, keyToLabelShort, keyToLabelLong, keyToListNumber } = await Data.fetchPartyLabels(year);
    const [bundle, kiesraadData] = await Promise.all([
      window.Data && typeof Data.fetchBundle==='function' ? Data.fetchBundle(year) : Promise.resolve({ anp_votes:null, anp_last_update:null, nos_index:null }),
      tryFetchKiesraadVotes(year)
    ]);
    const anpVotes = bundle.anp_votes;
    const lastUpdate = bundle.anp_last_update;
    const nosIndex = bundle.nos_index;
    // Badge visibility is centralized in AutoRefresh; do not set here
    if (nosIndex) { showLatestUpdateFromNos(nosIndex); }
    if (window.Ticker) { try { Ticker.update({ nosIndex, anpLastUpdate: lastUpdate }); } catch(e){} }

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

      // Sound triggers: detect vote increases and seat changes vs last state
      try {
        const y = String(year);
        const prev = lastStateByYear.get(y);
        const nowSeats = new Map();
        updatedData.parties.forEach(p => {
          const rest = Array.from(p.restSeats.values()).reduce((a,b)=>a+b,0);
          nowSeats.set(p.key, (p.fullSeats||0) + rest);
        });
        const nowState = { totalVotes, seats: nowSeats };
        if (prev) {
          let anySeatChanged = false;
          for (const [key, cnt] of nowSeats.entries()) {
            const prevCnt = prev.seats.get(key) || 0;
            if (cnt !== prevCnt) { anySeatChanged = true; break; }
          }
          const votesIncreased = totalVotes > (prev.totalVotes || 0);
          if (window.Sound && Sound.isEnabled()) {
            if (anySeatChanged) Sound.playSeatChange();
            else if (votesIncreased) Sound.playNewVotes();
          }
        }
        lastStateByYear.set(y, nowState);
      } catch(e) { /* ignore sound errors */ }

      // Vote average table with highlight
      let tableData = createVoteAverageTableData(updatedData, keyToLabelShort, total_restSeats);
      // Default sort: by total ANP votes (desc)
      tableData.sort((a,b)=> (b._votes||0) - (a._votes||0));
      const maxValues = {};
      const secondValues = {};
      for (let i = 1; i <= total_restSeats; i++) {
        const key = `_num_${i}e`;
        const vals = tableData.map(row => (typeof row[key] === 'number') ? row[key] : 0);
        const max = Math.max(...vals);
        maxValues[`${i}e`] = max;
        // second highest strictly less than max (0 if none)
        const second = vals.filter(v => v < max).sort((a,b)=>b-a)[0] || 0;
        secondValues[`${i}e`] = second;
      }
      tableData.forEach(row => {
        for (let i = 1; i <= total_restSeats; i++) {
          const dec = row[`_num_${i}e`] || 0;
          const frac = dec % 1 > 0 ? decimalToFraction(dec % 1) : '';
          const [num, den] = (frac || '/').split('/');
          const html = `
            <div class="averagevotetable-cell">
              <span style="margin-right: 5px;">${Math.floor(dec)}</span>
              ${frac ? `<span class="fraction-wrap">${createFractionHTML(num, den)}</span>` : ''}
            </div>`;
          row[`${i}e`] = html;
          if (dec === maxValues[`${i}e`]) {
            row[`${i}e`] = `<div class='highest-value'>${row[`${i}e`]}</div>`;
          } else if (dec === secondValues[`${i}e`] && dec > 0) {
            row[`${i}e`] = `<div class='second-highest-value'>${row[`${i}e`]}</div>`;
          }
        }
      });
      renderTable('voteAverageContainer', tableData);
      // Ensure highlight covers full cell height uniformly
      try {
        const tbl = document.querySelector('#voteAverageContainer table');
        if (tbl) {
          tbl.querySelectorAll('td').forEach(td => {
            const hv = td.querySelector('.highest-value');
            if (hv) {
              td.classList.add('highest-td');
              hv.classList.remove('highest-value');
            }
            const sv = td.querySelector('.second-highest-value');
            if (sv) {
              td.classList.add('second-highest-td');
              sv.classList.remove('second-highest-value');
            }
          });
        }
      } catch(e) {}

      // Rest seats: build tooltip content for averages header
      updateSeatStripTooltip(updatedData, keyToLabelShort, total_restSeats);

      // Exitpoll latest + full series (for tooltip); compute diff from latest
      let exitLatest = null, exitSeries = null;
      try {
        const xp = await Data.fetchExitpoll(year);
        if (xp && xp.latestByParty && xp.allByParty) {
          exitLatest = xp.latestByParty; exitSeries = xp.allByParty;
        } else if (Array.isArray(xp) && xp.length) {
          // Backward compatibility
          exitLatest = new Map(); exitSeries = new Map();
          const norm = (s) => (s||'').toString().trim().toUpperCase();
          xp.forEach(it => { if (it && typeof it.seats === 'number') { const p = norm(it.party); exitLatest.set(p, it.seats); exitSeries.set(p, [{ t:'latest', seats: it.seats }]); } });
        }
      } catch(e){}
      // Seats summary
      createSeatsSummaryTable(updatedData, keyToLabelLong, keyToListNumber, keyToLabelShort, { hasVotes: true, exitLatest, exitSeries });

      // Latest rest seat impact — always visible with persistent since-timer
      let finalizedFlag=false; try{ finalizedFlag = await Data.isFinalizedYear(year); }catch(e){ finalizedFlag=false; }
      showLatestRestSeatImpactSince(year, updatedData, keyToLabelShort, finalizedFlag);
      try { setupShareHandlers(year, updatedData, { keyToLabelShort, keyToLabelLong }, finalizedFlag); } catch(e) {}
    } else {
      // No votes yet: clear detail tables and render summary with blanks, but keep impact banner visible with placeholders
      ['voteAverageContainer','seatStripTooltip'].forEach(id => { const el=document.getElementById(id); if (el) el.innerHTML=''; });
      createSeatsSummaryTable(votesData, keyToLabelLong, keyToListNumber, keyToLabelShort, { hasVotes: false });
      const impactEl = document.getElementById('latestRestSeatImpactContainer');
      if (impactEl) {
        impactEl.innerHTML = `
          <div class="impact-main">Laatste restzetel gaat naar: <span style="font-weight: bold; color: green;">-</span>, dit gaat ten koste van: <span style="font-weight: bold; color: red;">-</span></div>
        `;
        if (__restImpactSinceInterval) { try { clearInterval(__restImpactSinceInterval); } catch(e){} __restImpactSinceInterval = null; }
      }
      try { setupShareHandlers(year, votesData || { parties: [] }, { keyToLabelShort, keyToLabelLong }, true); } catch(e) {}
    }
  }

  // Expose
  window.RestzetelsApp = { loadZetels };
})();
  function buildShareURL(/* year, utm */) {
    // Hardcode canonical domain for all shares as requested
    return 'https://wiekrijgtderestzetel.nl/';
  }

  function relTime(ms){
    if (!ms) return '';
    const s = Math.max(0, Math.floor((Date.now() - ms)/1000));
    if (s < 60) return `${s}s geleden`;
    const m = Math.floor(s/60); if (m < 60) return `${m}m geleden`;
    const h = Math.floor(m/60); if (h < 24) return `${h}u geleden`;
    const d = Math.floor(h/24); return `${d}d geleden`;
  }
