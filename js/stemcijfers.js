// Unified Stemcijfers (votes per party) across years
(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);

  async function fetchPartyLabels(year){
    return Data.fetchPartyLabels(year);
  }

  async function fetchANPVotes(year){
    const y = String(year);
    if (await Data.isFinalizedYear(y)) return await Data.safeJSON(`data/${y}/anp_votes.json`);
    return await Data.safeJSON(`${DO_BASE}?year=${y}&source=anp_votes`);
  }
  async function fetchANPLastUpdate(year){
    const y = String(year);
    if (await Data.isFinalizedYear(y)) return await Data.safeJSON(`data/${y}/anp_last_update.json`);
    return await Data.safeJSON(`${DO_BASE}?year=${y}&source=anp_last_update`);
  }
  async function fetchNOSIndex(year){
    const y = String(year);
    if (await Data.isFinalizedYear(y)) return await Data.safeJSON(`data/${y}/nos_index.json`);
    return await Data.safeJSON(`${DO_BASE}?year=${y}&source=nos_index`);
  }

  // Finalized logic is provided by Data
  async function fetchKiesraadVotes(year){
    const data = await Data.safeJSON(`votes_kiesraad.json`);
    if (!data) return null;
    if (Array.isArray(data)) return data; // backward compat
    return data[String(year)] || null;
  }

  function createFractionHTML(numerator, denominator){
    return (window.UI && UI.createFractionHTML) ? UI.createFractionHTML(numerator, denominator) : `${numerator}/${denominator}`;
  }

  function buildStats(anpVotes, nosIndex){
    const stats = {
      voters: { current: 0, previous: 0 },
      turnout: { current: '', previous: '' },
      turnoutCount: { current: 0, previous: 0 },
      invalid: { current: 0, previous: 0 },
      blank: { current: 0, previous: 0 }
    };
    const lu = nosIndex && nosIndex.landelijke_uitslag;
    const hv = lu && lu.huidige_verkiezing ? lu.huidige_verkiezing : null;
    const pv = lu && lu.vorige_verkiezing ? lu.vorige_verkiezing : null;
    // Helper for percentage from promillage
    const fmtPerc = (promi) => (typeof promi === 'number') ? (promi/10).toFixed(1).replace('.', ',') : '';

    // Current
    stats.voters.current = anpVotes?.voters?.current || (hv?.kiesgerechtigden || 0);
    stats.turnout.current = anpVotes?.turnout?.current || fmtPerc(hv?.opkomst_promillage);
    stats.turnoutCount.current = anpVotes?.turnoutCount?.current || (hv?.opkomst || 0);
    stats.invalid.current = anpVotes?.invalid?.current || (hv?.ongeldig || 0);
    stats.blank.current = anpVotes?.blank?.current || (hv?.blanco || 0);

    // Previous
    stats.voters.previous = anpVotes?.voters?.previous || (pv?.kiesgerechtigden || 0);
    stats.turnout.previous = anpVotes?.turnout?.previous || fmtPerc(pv?.opkomst_promillage);
    stats.turnoutCount.previous = anpVotes?.turnoutCount?.previous || (pv?.opkomst || 0);
    stats.invalid.previous = anpVotes?.invalid?.previous || (pv?.ongeldig || 0);
    stats.blank.previous = anpVotes?.blank?.previous || (pv?.blanco || 0);

    return stats;
  }

  function renderStatsTable(stats, anpNulstand=false){
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const headerRow = thead.insertRow();
    ["", "Stemgerechtigden", "Opkomst", "Totale stemmen", "Ongeldige stemmen", "Blanco stemmen"].forEach(h => { const th = document.createElement('th'); th.textContent = h; headerRow.appendChild(th); });
    const cur = tbody.insertRow();
    cur.insertCell().textContent = "Huidig";
    const curVoters = Number(stats.voters.current || 0);
    const curTurnout = stats.turnout.current || '';
    const curTurnoutCount = Number(stats.turnoutCount.current || 0);
    const curInvalid = Number(stats.invalid.current || 0);
    const curBlank = Number(stats.blank.current || 0);
    cur.insertCell().textContent = (anpNulstand && curVoters === 0) ? '' : curVoters.toLocaleString('nl-NL');
    cur.insertCell().textContent = (anpNulstand && (curTurnout === '' || curTurnout === '0,0')) ? '' : curTurnout;
    cur.insertCell().textContent = (anpNulstand && curTurnoutCount === 0) ? '' : curTurnoutCount.toLocaleString('nl-NL');
    cur.insertCell().textContent = (anpNulstand && curInvalid === 0) ? '' : curInvalid.toLocaleString('nl-NL');
    cur.insertCell().textContent = (anpNulstand && curBlank === 0) ? '' : curBlank.toLocaleString('nl-NL');
    const prev = tbody.insertRow();
    prev.insertCell().textContent = "Vorige";
    prev.insertCell().textContent = Number(stats.voters.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = stats.turnout.previous || '';
    prev.insertCell().textContent = Number(stats.turnoutCount.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = Number(stats.invalid.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = Number(stats.blank.previous || 0).toLocaleString('nl-NL');
    return table;
  }

  function updateLastUpdates(lastUpdateData, nosData, votesData, year){
    // ANP last update (global timestamp)
    const lu = document.getElementById('lastUpdateANP');
    if (lu) {
      const kiesraadDates = {
        '2021': '26/03/2021, 12:00',
        '2023': '01/12/2023, 10:00 (2e zitting: 04/12/2023)',
        '2025': '07/11/2025, 10:00'
      };
      const label = kiesraadDates[String(year)] || '';
      lu.textContent = label ? `Uitslag Kiesraad: ${label}` : '';
    }
    // ANP latest local region
    const statusMap = new Map([[0,'Nulstand'],[2,'Tussenstand'],[4,'Eindstand']]);
    const localRegion = lastUpdateData?.views?.find(v => v.type === 0);
    if (localRegion) {
      const ts = new Date(localRegion.updated * 1000).toLocaleString();
      const statusText = statusMap.get(localRegion.status) || 'Onbekend';
      const el = document.getElementById('lastUpdatedLocalRegionANP');
      if (el) el.textContent = `Laatste gemeente via ANP: ${ts} uit ${localRegion.label} (${statusText})`;
    }
    // NOS latest update
    if (nosData?.gemeentes?.length) {
      const sorted = nosData.gemeentes.slice().sort((a,b)=>new Date(b.publicatie_datum_tijd)-new Date(a.publicatie_datum_tijd));
      const latest = sorted[0];
      const ts = new Date(latest.publicatie_datum_tijd).toLocaleString();
      const name = latest.gemeente?.naam;
      const status = latest.status;
      const el = document.getElementById('latestUpdateFromNos');
      if (el) el.textContent = `Laatste gemeente via NOS: ${ts} uit ${name} (${status})`;
    }
  }

  function sortTableData(parties, sortColumn, sortOrder, lastSortedColumn, maps){
    const { keyToLabelLong, keyToNOS, keyToListNumber } = maps;
    return parties.sort((a,b)=>{
      let A,B;
      if (lastSortedColumn === 'lijst') { A = keyToListNumber.get(a.key); B = keyToListNumber.get(b.key); }
      else if (sortColumn === 'votes' || sortColumn === 'voteDiff') {
        A = parseInt(a.results.current.votes); B = parseInt(b.results.current.votes);
        if (sortColumn === 'voteDiff') { A = parseInt(a.results.diff.votes); B = parseInt(b.results.diff.votes); }
      } else if (sortColumn === 'nosVotes') {
        // Handled in caller with mapped values
        A = a.__nosVotes || 0; B = b.__nosVotes || 0;
      } else if (sortColumn === 'kiesraadVotes') {
        A = a.__kiesraadVotes || 0; B = b.__kiesraadVotes || 0;
      } else if (sortColumn === 'key') {
        A = keyToLabelLong.get(a.key) || ''; B = keyToLabelLong.get(b.key) || '';
      } else if (sortColumn === 'percentage' || sortColumn === 'percentageDiff') {
        A = parseFloat((a.results.current.percentage||'0').toString().replace(',', '.'));
        B = parseFloat((b.results.current.percentage||'0').toString().replace(',', '.'));
        if (sortColumn === 'percentageDiff') {
          const dA = parseInt(a.results.diff.votes), vA = parseInt(a.results.current.votes);
          const dB = parseInt(b.results.diff.votes), vB = parseInt(b.results.current.votes);
          A = vA === 0 ? -Infinity : parseFloat(((dA / vA) * 100).toFixed(1));
          B = vB === 0 ? -Infinity : parseFloat(((dB / vB) * 100).toFixed(1));
        }
      } else { A = a[sortColumn]; B = b[sortColumn]; }
      if ([ 'lijst','votes','voteDiff','percentageDiff','nosVotes','kiesraadVotes'].includes(sortColumn)) return (sortOrder==='asc' ? (A-B) : (B-A));
      A = (A||'').toString(); B = (B||'').toString();
      return sortOrder==='asc' ? A.localeCompare(B, undefined, {numeric:true}) : B.localeCompare(A, undefined, {numeric:true});
    });
  }

  function renderStemcijfersTable({containerId, votesData, nosVotesMap, kiesraadVotesMap, maps, anpNulstand=false}){
    const { keyToLabelLong, keyToNOS, keyToListNumber } = maps;
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const headerRow = thead.insertRow();
    const headers = [
      {text:'Lijst', id:'lijst'},
      {text:'Partij', id:'key'},
      {text:'Stemcijfers ANP', id:'votes'},
      {text:'Stemcijfers NOS', id:'nosVotes'},
      {text:'Stemcijfers Kiesraad', id:'kiesraadVotes'},
      {text:'% ANP', id:'percentage'},
      {text:'Verschil stemmen', id:'voteDiff'},
      {text:'% verschil', id:'percentageDiff'}
    ];
    headers.forEach(h=>{ const th=document.createElement('th'); th.dataset.sort=h.id; th.style.cursor='pointer'; th.innerHTML = `${h.text} <span class="sort-icon"></span>`; headerRow.appendChild(th); });

    // decorate parties with mapped values
    votesData.parties.forEach((p, i)=>{
      p.__origIndex = i + 1; // fallback list number
      const nosKey = keyToNOS.get(p.key);
      p.__nosVotes = nosKey ? (nosVotesMap.get(nosKey) || 0) : 0;
      const listNumber = keyToListNumber.get(p.key);
      p.__kiesraadVotes = listNumber ? (kiesraadVotesMap.get(listNumber) || 0) : 0;
    });

    // default sort by ANP votes desc
    let sortColumn = 'votes', sortOrder = 'desc', lastSortedColumn = 'votes';
    function updateHeaderIcons(){
      Array.from(headerRow.children).forEach(th => {
        const id = th.dataset.sort;
        const icon = th.querySelector('.sort-icon');
        if (!icon) return;
        if (id === sortColumn) icon.innerHTML = (sortOrder === 'asc' ? '&#9650;' : '&#9660;'); else icon.innerHTML = '';
      });
    }
    const renderBody = () => {
      tbody.innerHTML = '';
      const sorted = sortTableData(votesData.parties.slice(), sortColumn, sortOrder, lastSortedColumn, maps);
      sorted.forEach(p=>{
        const row = tbody.insertRow();
        const listNumber = keyToListNumber.get(p.key) || p.__origIndex || '';
        const partij = keyToLabelLong.get(p.key) || '';
        const anpVotes = parseInt(p.results.current.votes)||0;
        const nosVotes = p.__nosVotes || 0;
        const krVotes = p.__kiesraadVotes || 0;
        const rawPerc = p.results.current.percentage || '';
        const diffVotes = parseInt(p.results.diff.votes)||0;
        let percDiff;
        const prev = parseInt(p.results.previous.votes)||0; const curr = anpVotes;
        percDiff = prev === 0 && curr > 0 ? '∞' : ((curr - prev) / (prev || 1) * 100).toFixed(1).replace('.', ',');

        const anpVotesDisplay = (anpNulstand && anpVotes === 0) ? '' : anpVotes.toLocaleString('nl-NL');
        const nosVotesDisplay = nosVotes ? nosVotes.toLocaleString('nl-NL') : '';
        const krVotesDisplay = krVotes ? krVotes.toLocaleString('nl-NL') : '';
        const percDisplay = (anpNulstand && anpVotes === 0) ? '' : rawPerc;
        const diffVotesDisplay = (anpNulstand && diffVotes === 0) ? '' : diffVotes.toLocaleString('nl-NL');
        const percDiffDisplay = anpNulstand ? '' : percDiff;

        [listNumber, partij, anpVotesDisplay, nosVotesDisplay, krVotesDisplay, percDisplay, diffVotesDisplay, percDiffDisplay].forEach(val=>{ const c=row.insertCell(); c.textContent = val; });
      });
    };
    renderBody();
    updateHeaderIcons();

    // header click sorting
    thead.querySelectorAll('th').forEach(th=>{
      th.addEventListener('click',()=>{
        const id = th.dataset.sort;
        if (sortColumn === id) sortOrder = sortOrder==='asc'?'desc':'asc'; else { sortColumn = id; sortOrder = 'asc'; lastSortedColumn = id; }
        renderBody();
        updateHeaderIcons();
      });
    });
    const container = document.getElementById(containerId);
    container.innerHTML = '';
    container.appendChild(table);

    // Totals + kiesdeler rows
    const totalANP = votesData.parties.reduce((t,p)=>t+parseInt(p.results.current.votes),0);
    const totalNOS = Array.from(nosVotesMap.values()).reduce((t,v)=>t+v,0);
    const totalKR = Array.from(kiesraadVotesMap.values()).reduce((t,v)=>t+v,0);
    const kANP = totalANP/150, kNOS = totalNOS/150, kKR = totalKR/150;
    const vANP = Math.floor(0.25*kANP), vNOS = Math.floor(0.25*kNOS), vKR = Math.floor(0.25*kKR);
    // Add total row
    const totalRow = tbody.insertRow();
    totalRow.insertCell().textContent = '';
    totalRow.insertCell().textContent = 'Totaal aantal geldige stemmen op lijsten:';
    totalRow.insertCell().textContent = (anpNulstand && totalANP === 0) ? '' : totalANP.toLocaleString('nl-NL');
    totalRow.insertCell().textContent = totalNOS ? totalNOS.toLocaleString('nl-NL') : '';
    totalRow.insertCell().textContent = totalKR ? totalKR.toLocaleString('nl-NL') : '';
    totalRow.insertCell(); totalRow.insertCell(); totalRow.insertCell();
    // Kiesdeler row
    const kiesRow = tbody.insertRow();
    kiesRow.insertCell();
    kiesRow.insertCell().textContent = 'Kiesdeler:';
    const anpCell = kiesRow.insertCell();
    const nosCell = kiesRow.insertCell();
    const krCell = kiesRow.insertCell();
    const fixedDen = 150; const anpNum = Math.round((kANP%1)*fixedDen), nosNum = Math.round((kNOS%1)*fixedDen), krNum = Math.round((kKR%1)*fixedDen);
    anpCell.innerHTML = (anpNulstand && totalANP === 0) ? '' : `<div style="display:flex;align-items:center;justify-content:flex-start;height:100%;"><span style="margin-right:5px;">${Math.trunc(kANP).toLocaleString('nl-NL')}</span>${createFractionHTML(anpNum,fixedDen)}</div>`;
    nosCell.innerHTML = totalNOS ? `<div style="display:flex;align-items:center;justify-content:flex-start;height:100%;"><span style=\"margin-right:5px;\">${Math.trunc(kNOS).toLocaleString('nl-NL')}</span>${createFractionHTML(nosNum,fixedDen)}</div>` : '';
    krCell.innerHTML = totalKR ? `<div style="display:flex;align-items:center;justify-content:flex-start;height:100%;"><span style=\"margin-right:5px;\">${Math.trunc(kKR).toLocaleString('nl-NL')}</span>${createFractionHTML(krNum,fixedDen)}</div>` : '';
    kiesRow.insertCell(); kiesRow.insertCell(); kiesRow.insertCell();
    // Voorkeurdrempel row
    const vRow = tbody.insertRow();
    vRow.insertCell(); vRow.insertCell().textContent='Voorkeurdrempel:';
    vRow.insertCell().textContent = (anpNulstand && totalANP === 0) ? '' : vANP.toLocaleString('nl-NL');
    vRow.insertCell().textContent = totalNOS ? vNOS.toLocaleString('nl-NL') : '';
    vRow.insertCell().textContent = totalKR ? vKR.toLocaleString('nl-NL') : '';
    vRow.insertCell(); vRow.insertCell(); vRow.insertCell();
  }

  async function loadStemcijfers(year){
    // Clear
    ['statsTableContainer','tableContainer','lastUpdateANP','lastUpdatedLocalRegionANP','latestUpdateFromNos'].forEach(id=>{ const el=document.getElementById(id); if (el) el.innerHTML=''; });
    const [{ list, keyToLabelLong, keyToLabelShort, keyToNOS, keyToListNumber }, bundle, kiesraad] = await Promise.all([
      fetchPartyLabels(year), (window.Data && typeof Data.fetchBundle==='function' ? Data.fetchBundle(year) : Promise.resolve({ anp_votes:null, anp_last_update:null, nos_index:null })), fetchKiesraadVotes(year)
    ]);
    const anpVotes = bundle.anp_votes; const lastUpdate = bundle.anp_last_update; const nosIndex = bundle.nos_index;
    // Stats (ANP values with NOS landelijke_uitslag fallback when missing)
    const statsObj = buildStats(anpVotes, nosIndex);
    const rijkView = lastUpdate && Array.isArray(lastUpdate.views) ? lastUpdate.views.find(v=>v.type===2) : null;
    const anpNulstand = rijkView ? (rijkView.status === 0) : false;
    const statsEl = renderStatsTable(statsObj, anpNulstand);
    const sc = document.getElementById('statsTableContainer'); if (sc) sc.appendChild(statsEl);
    updateLastUpdates(lastUpdate, nosIndex, anpVotes, year);
    // NOS national votes map
    const nosVotesMap = new Map();
    const landelijke = nosIndex && nosIndex.landelijke_uitslag && nosIndex.landelijke_uitslag.partijen;
    if (Array.isArray(landelijke)) {
      landelijke.forEach(p=>{ const code = p.partij?.short_name; const votes = p.huidig?.stemmen || 0; if (code) nosVotesMap.set(code, votes); });
    }
    // Kiesraad map
    const kiesraadVotesMap = new Map();
    if (Array.isArray(kiesraad)) kiesraad.forEach(item=>{ kiesraadVotesMap.set(item.lijstnummer, item.votes); });
    // Render table
    renderStemcijfersTable({containerId:'tableContainer', votesData: anpVotes, nosVotesMap, kiesraadVotesMap, maps:{keyToLabelLong, keyToNOS, keyToListNumber}, anpNulstand});
  }

  window.StemcijfersApp = { loadStemcijfers };
})();
