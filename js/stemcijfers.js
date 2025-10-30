// Unified Stemcijfers (votes per party) across years
(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);
  const lastRenderSigByYear = new Map();
  let renderedYear = null; // which year is currently rendered

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
    const data = await Data.safeJSON(`data/votes_kiesraad.json`);
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

  function renderStatsTable(stats, anpNulstand=false, year){
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const headerRow = thead.insertRow();
    ["", "Stemgerechtigden", "Opkomst", "Totale stemmen", "Ongeldige stemmen", "Blanco stemmen"].forEach(h => { const th = document.createElement('th'); th.textContent = h; headerRow.appendChild(th); });
    const cur = tbody.insertRow();
    // Row labels: TKYY for current and previous cycle (e.g., TK25 vs TK23; TK21 vs TK17)
    let curLabel = 'Huidig';
    let prevLabel = 'Vorige';
    try {
      const yNum = parseInt(String(year||''), 10);
      if (!isNaN(yNum) && yNum>0) {
        curLabel = `TK${String(yNum).slice(-2)}`;
        let prevYear = (yNum === 2021) ? 2017 : (yNum - 2);
        prevLabel = `TK${String(prevYear).slice(-2)}`;
      }
    } catch(e){}
    const curLblCell = cur.insertCell();
    try { curLblCell.innerHTML = `<strong>${curLabel}</strong>`; } catch(e) { curLblCell.textContent = curLabel; }
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
    prev.insertCell().textContent = prevLabel;
    prev.insertCell().textContent = Number(stats.voters.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = stats.turnout.previous || '';
    prev.insertCell().textContent = Number(stats.turnoutCount.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = Number(stats.invalid.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = Number(stats.blank.previous || 0).toLocaleString('nl-NL');
    return table;
  }

  function updateLastUpdates(lastUpdateData, nosData, votesData, year){
    const container = document.getElementById('metaCards');
    if (!container) return;
    const cards = [];
    // Helpers
    const relTime = (ms) => {
      if (!ms) return '';
      const s = Math.max(0, Math.floor((Date.now() - ms)/1000));
      if (s < 60) return `${s}s geleden`;
      const m = Math.floor(s/60); if (m < 60) return `${m}m geleden`;
      const h = Math.floor(m/60); if (h < 24) return `${h}u geleden`;
      const d = Math.floor(h/24); return `${d}d geleden`;
    };
    // Both past (… geleden) and future (over …) relative time
    const relTimeSigned = (ms) => {
      if (!ms) return '';
      const now = Date.now();
      const past = now >= ms; const diffS = Math.abs(Math.floor((now - ms)/1000));
      if (diffS < 60) return past ? `${diffS}s geleden` : `over ${diffS}s`;
      const m = Math.floor(diffS/60); if (m < 60) return past ? `${m}m geleden` : `over ${m}m`;
      const h = Math.floor(m/60); if (h < 24) return past ? `${h}u geleden` : `over ${h}u`;
      const d = Math.floor(h/24); return past ? `${d}d geleden` : `over ${d}d`;
    };
    const pad2 = (n) => String(n).padStart(2,'0');
    const formatDateTimeNL = (ms, opts = {}) => {
      if (!ms) return '';
      const d = new Date(ms);
      const dd = pad2(d.getDate());
      const mm = pad2(d.getMonth()+1);
      const yyyy = d.getFullYear();
      const HH = pad2(d.getHours());
      const MM = pad2(d.getMinutes());
      const SS = pad2(d.getSeconds());
      const showSeconds = (opts.seconds === 'always') ? true : (opts.seconds === 'never' ? false : (SS !== '00'));
      return `${dd}-${mm}-${yyyy} ${HH}:${MM}${showSeconds ? ':'+SS : ''}`;
    };
    const statusMap = new Map([[0,'Nulstand'],[2,'Tussenstand'],[4,'Eindstand']]);

    // 1) Kiesraad (static per year)
    const kiesraadDates = {
      '2021': '26-03-2021 12:00',
      '2023': '01-12-2023 10:00 (2e zitting: 04-12-2023)',
      '2025': '07-11-2025 10:00'
    };
    const krLabel = kiesraadDates[String(year)] || '';
    // Parse first date/time portion (dd-mm-yyyy HH:MM[:SS]) to compute relative
    const parseNLDateTime = (str) => {
      if (!str) return 0;
      const m = str.match(/^(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
      if (!m) return 0;
      const dd = Number(m[1]), mm = Number(m[2]) - 1, yyyy = Number(m[3]);
      const HH = Number(m[4]), MM = Number(m[5]);
      const SS = m[6] ? Number(m[6]) : 0;
      return new Date(yyyy, mm, dd, HH, MM, SS).getTime();
    };
    const krTs = parseNLDateTime(krLabel);
    if (krLabel) {
      cards.push(
        `<div class="meta-card" title="Uitslag Kiesraad">
           <div class="meta-row">
             <span class="chip chip--kiesraad">Kiesraad</span>
             <span class="meta-title">Uitslag</span>
           </div>
           <div class="meta-row">
             <span class="meta-exact">${krLabel}</span>
             ${krTs ? '<span class="ticker-dot">•</span>' : ''}
             ${krTs ? `<span class=\"muted small\">${relTimeSigned(krTs)}</span>` : ''}
           </div>
         </div>`
      );
    }

    // 2) ANP latest gemeente
    const anpViews = Array.isArray(lastUpdateData?.views) ? lastUpdateData.views : [];
    const anpGemeenten = anpViews.filter(v => v && v.type === 0);
    if (anpGemeenten.length) {
      const latestAnp = anpGemeenten.slice().sort((a,b)=> (b.updated||0)-(a.updated||0))[0];
      const tsMs = (latestAnp.updated||0) * 1000;
      const statusText = statusMap.get(latestAnp.status) || 'Onbekend';
      cards.push(
        `<div class="meta-card" title="Laatste gemeente via ANP">
           <div class="meta-row">
             <span class="chip chip--source chip--source-anp">ANP</span>
             <span class="chip ${statusText==='Eindstand'?'chip--eindstand':(statusText==='Tussenstand'?'chip--tussenstand':'chip--nulstand')}"><span class="chip-dot"></span>${statusText}</span>
             <span class="meta-title">${latestAnp.label || ''}</span>
           </div>
           <div class="meta-row">
             <span class="meta-exact">${formatDateTimeNL(tsMs, { seconds: 'auto' })}</span>
             <span class="ticker-dot">•</span>
             <span class="muted small">${relTime(tsMs)}</span>
           </div>
         </div>`
      );
    }

    // 3) NOS latest gemeente
    const nosGemeenten = Array.isArray(nosData?.gemeentes) ? nosData.gemeentes : [];
    if (nosGemeenten.length) {
      const sorted = nosGemeenten.slice().sort((a,b)=> new Date(b.publicatie_datum_tijd)-new Date(a.publicatie_datum_tijd));
      const latest = sorted[0];
      const ts = latest.publicatie_datum_tijd ? new Date(latest.publicatie_datum_tijd) : null;
      const status = latest.status || '';
      cards.push(
        `<div class="meta-card" title="Laatste gemeente via NOS">
           <div class="meta-row">
             <span class="chip chip--source chip--source-nos">NOS</span>
             <span class="chip ${status.toLowerCase().indexOf('eind')===0?'chip--eindstand':(status.toLowerCase().indexOf('tussen')===0?'chip--tussenstand':'chip--nulstand')}"><span class="chip-dot"></span>${status}</span>
             <span class="meta-title">${latest?.gemeente?.naam || ''}</span>
           </div>
           <div class="meta-row">
             <span class="meta-exact">${ts ? formatDateTimeNL(ts.getTime(), { seconds: 'auto' }) : ''}</span>
             <span class="ticker-dot">•</span>
             <span class="muted small">${ts ? relTime(ts.getTime()) : ''}</span>
           </div>
         </div>`
      );
    }

    container.innerHTML = cards.join('');
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

  function renderStemcijfersTable({containerId, votesData, nosVotesMap, kiesraadVotesMap, maps, anpNulstand=false, nosHasData=false, prevYear}){
    const { keyToLabelLong, keyToLabelShort, keyToNOS, keyToListNumber } = maps;
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const headerRow = thead.insertRow();
    const yy = typeof prevYear === 'number' ? String(prevYear).slice(-2) : '';
    const headers = [
      {text:'Lijst', id:'lijst'},
      {text:'Partij', id:'key'},
      {text:'Stemcijfers ANP', id:'votes'},
      {text:'Stemcijfers NOS', id:'nosVotes'},
      {text:'Stemcijfers Kiesraad', id:'kiesraadVotes'},
      {text:'% Stemmen', id:'percentage'},
      {text:'# Verschil', id:'voteDiff'},
      {text:'% Verschil', id:'percentageDiff'}
    ];
    const numCols = new Set(['lijst','votes','nosVotes','kiesraadVotes','percentage','voteDiff','percentageDiff']);
    headers.forEach(h=>{ const th=document.createElement('th'); th.dataset.sort=h.id; th.style.cursor='pointer'; th.innerHTML = `${h.text} <span class=\"sort-icon\"></span>`; if (numCols.has(h.id)) th.classList.add('num'); headerRow.appendChild(th); });

    // decorate parties with mapped values
    votesData.parties.forEach((p, i)=>{
      p.__origIndex = i + 1; // fallback list number
      const nosKey = keyToNOS.get(p.key);
      p.__nosVotes = nosKey ? (nosVotesMap.get(nosKey) || 0) : 0;
      const listNumber = keyToListNumber.get(p.key);
      p.__kiesraadVotes = listNumber ? (kiesraadVotesMap.get(listNumber) || 0) : 0;
    });

    // Choose default sort column:
    // - If Kiesraad totals known, sort by Kiesraad votes (desc)
    // - Else sort by the source with the highest total votes between ANP and NOS (ties -> ANP)
    const totalANP_init = votesData.parties.reduce((t,p)=>t + (parseInt(p.results.current.votes)||0), 0);
    const totalNOS_init = Array.from(nosVotesMap.values()).reduce((t,v)=>t + (v||0), 0);
    const totalKR_init  = Array.from(kiesraadVotesMap.values()).reduce((t,v)=>t + (v||0), 0);
    let sortColumn = 'votes', sortOrder = 'desc', lastSortedColumn = 'votes';
    if (totalKR_init > 0) { sortColumn = 'kiesraadVotes'; lastSortedColumn = 'kiesraadVotes'; }
    else if (totalNOS_init > totalANP_init) { sortColumn = 'nosVotes'; lastSortedColumn = 'nosVotes'; }
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
        const shortLbl = (keyToLabelShort && keyToLabelShort.get(p.key)) || '';
        const isOverig = /overig/i.test(shortLbl);
        if (isOverig && anpVotes === 0) { try { tbody.removeChild(row); } catch(e){} return; }
        const rawPerc = p.results.current.percentage || '';
        const diffVotes = parseInt(p.results.diff.votes)||0;
        let percDiff;
        const prev = parseInt(p.results.previous.votes)||0; const curr = anpVotes;
        // If the party did not compete previously (prev === 0), show '-'
        if (prev === 0) {
          percDiff = '-';
        } else {
          percDiff = (((curr - prev) / prev) * 100).toFixed(1).replace('.', ',');
        }

        const cells = [
          { id:'lijst', val: listNumber },
          { id:'key', val: partij },
          { id:'votes', val: (anpNulstand && anpVotes === 0) ? '' : anpVotes.toLocaleString('nl-NL') },
          { id:'nosVotes', val: nosHasData ? nosVotes.toLocaleString('nl-NL') : (nosVotes ? nosVotes.toLocaleString('nl-NL') : '') },
          { id:'kiesraadVotes', val: krVotes ? krVotes.toLocaleString('nl-NL') : '' },
          { id:'percentage', val: (anpNulstand && anpVotes === 0) ? '' : rawPerc },
          { id:'voteDiff', val: (anpNulstand && diffVotes === 0) ? '' : diffVotes.toLocaleString('nl-NL') },
          { id:'percentageDiff', val: anpNulstand ? '' : percDiff }
        ];
        cells.forEach(({id,val})=>{ const c=row.insertCell(); if (numCols.has(id)) c.classList.add('num'); c.textContent = val; });
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
    // Add total row (emphasized)
    const totalRow = tbody.insertRow();
    totalRow.classList.add('total-row');
    totalRow.insertCell().textContent = '';
    const totalLbl = totalRow.insertCell(); totalLbl.textContent = 'Totaal aantal geldige stemmen op lijsten:';
    const totalAnpCell = totalRow.insertCell(); totalAnpCell.classList.add('num'); totalAnpCell.textContent = (anpNulstand && totalANP === 0) ? '' : totalANP.toLocaleString('nl-NL');
    const totalNosCell = totalRow.insertCell(); totalNosCell.classList.add('num'); totalNosCell.textContent = nosHasData ? totalNOS.toLocaleString('nl-NL') : (totalNOS ? totalNOS.toLocaleString('nl-NL') : '');
    const totalKrCell  = totalRow.insertCell(); totalKrCell.classList.add('num');  totalKrCell.textContent  = totalKR ? totalKR.toLocaleString('nl-NL') : '';
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

    // Align total row numeric cells
    try {
      if (totalRow && totalRow.cells && totalRow.cells.length >= 5) {
        totalRow.cells[2].classList.add('num');
        totalRow.cells[3].classList.add('num');
        totalRow.cells[4].classList.add('num');
      }
    } catch(e){}

    // Build separate summary table for Kiesdeler and Voorkeurdrempel (single chosen source)
    try {
      const summary = document.createElement('table');
      summary.className = 'summary-table';
      const sBody = summary.createTBody();

      // Choose source: Kiesraad if available; else higher of ANP/NOS (ties -> ANP)
      const chosenTotal = (totalKR && totalKR > 0)
        ? totalKR
        : ((totalNOS > totalANP) ? totalNOS : totalANP);
      const chosenKiesdeler = chosenTotal ? (chosenTotal / 150) : 0;

      // Kiesdeler row (no header)
      const r1 = sBody.insertRow();
      const r1Lbl = r1.insertCell(); r1Lbl.textContent = 'Kiesdeler:';
      const r1Val = r1.insertCell(); r1Val.classList.add('num');
      if (chosenTotal) {
        r1Val.innerHTML = `<div style=\"display:flex;align-items:center;justify-content:flex-end;height:100%;\"><span style=\"margin-right:5px;\">${Math.trunc(chosenKiesdeler).toLocaleString('nl-NL')}</span>${createFractionHTML(Math.round((chosenKiesdeler%1)*150),150)}</div>`;
      } else {
        r1Val.textContent = '';
      }

      // Voorkeurdrempel row (25% van kiesdeler)
      const r2 = sBody.insertRow();
      const r2Lbl = r2.insertCell(); r2Lbl.textContent = 'Voorkeurdrempel:';
      const r2Val = r2.insertCell(); r2Val.classList.add('num');
      r2Val.textContent = chosenTotal ? Math.floor(0.25 * chosenKiesdeler).toLocaleString('nl-NL') : '';
      // Remove rows from main table and append summary table
      try { tbody.removeChild(kiesRow); } catch(e){}
      try { tbody.removeChild(vRow); } catch(e){}
      const containerEl = document.getElementById(containerId);
      const spacer = document.createElement('div'); spacer.style.height = '6px';
      containerEl.appendChild(spacer);
      containerEl.appendChild(summary);
    } catch(e){}
  }

  async function loadStemcijfers(year){
    const [{ list, keyToLabelLong, keyToLabelShort, keyToNOS, keyToListNumber }, bundle, kiesraad] = await Promise.all([
      fetchPartyLabels(year), (window.Data && typeof Data.fetchBundle==='function' ? Data.fetchBundle(year) : Promise.resolve({ anp_votes:null, anp_last_update:null, nos_index:null })), fetchKiesraadVotes(year)
    ]);
    const anpVotes = bundle.anp_votes; const lastUpdate = bundle.anp_last_update; const nosIndex = bundle.nos_index;
    // Signature: ANP max updated and NOS max ts
    let anpMaxTs = 0; try {
      const views = Array.isArray(lastUpdate && lastUpdate.views) ? lastUpdate.views : [];
      anpMaxTs = views.reduce((m,v)=> Math.max(m, Number(v && v.updated)||0), 0);
    } catch(e){}
    let nosMaxTs = 0; try {
      const luTs = Date.parse(nosIndex && nosIndex.landelijke_uitslag && nosIndex.landelijke_uitslag.publicatie_datum_tijd) || 0;
      let gmTs = 0; const listG = Array.isArray(nosIndex && nosIndex.gemeentes) ? nosIndex.gemeentes : [];
      for (const g of listG) { const t = Date.parse(g && g.publicatie_datum_tijd) || 0; if (t > gmTs) gmTs = t; }
      nosMaxTs = Math.max(luTs, gmTs);
    } catch(e){}
    const sig = `${anpMaxTs}|${nosMaxTs}`;
    const yKey = String(year);
    if (lastRenderSigByYear.get(yKey) === sig && renderedYear === yKey) return; // unchanged for current year -> avoid DOM work
    lastRenderSigByYear.set(yKey, sig);
    renderedYear = yKey;
    // Clear
    ['statsTableContainer','tableContainer','lastUpdateANP','lastUpdatedLocalRegionANP','latestUpdateFromNos'].forEach(id=>{ const el=document.getElementById(id); if (el) el.innerHTML=''; });
    // Stats (ANP values with NOS landelijke_uitslag fallback when missing)
    const statsObj = buildStats(anpVotes, nosIndex);
    const rijkView = lastUpdate && Array.isArray(lastUpdate.views) ? lastUpdate.views.find(v=>v.type===2) : null;
    const anpNulstand = rijkView ? (rijkView.status === 0) : false;
    const statsEl = renderStatsTable(statsObj, anpNulstand, year);
    const sc = document.getElementById('statsTableContainer'); if (sc) sc.appendChild(statsEl);
    updateLastUpdates(lastUpdate, nosIndex, anpVotes, year);
    // NOS national votes map
    const nosVotesMap = new Map();
    const landelijke = nosIndex && nosIndex.landelijke_uitslag && nosIndex.landelijke_uitslag.partijen;
    if (Array.isArray(landelijke)) {
      landelijke.forEach(p=>{ const code = p.partij?.short_name; const votes = p.huidig?.stemmen || 0; if (code!=null) nosVotesMap.set(code, votes||0); });
    }
    const nosHasData = nosVotesMap.size > 0;
    // Kiesraad map
    const kiesraadVotesMap = new Map();
    if (Array.isArray(kiesraad)) kiesraad.forEach(item=>{ kiesraadVotesMap.set(item.lijstnummer, item.votes); });
    // Determine previous election year label for headers
    const yNum = parseInt(year, 10) || 0;
    let prevYear = (yNum ? yNum - 2 : undefined);
    if (yNum === 2021) prevYear = 2017; else if (yNum === 2023) prevYear = 2021; else if (yNum === 2025) prevYear = 2023;
    // Render table
    renderStemcijfersTable({containerId:'tableContainer', votesData: anpVotes, nosVotesMap, kiesraadVotesMap, maps:{keyToLabelLong, keyToLabelShort, keyToNOS, keyToListNumber}, anpNulstand, nosHasData, prevYear});
  }

  window.StemcijfersApp = { loadStemcijfers };
})();
