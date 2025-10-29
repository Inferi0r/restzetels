// Unified ANP Stemmen per partij across years
(function(){
  const DO_BASE = 'https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata';

  async function safeFetchJSON(url){ try{ const r=await fetch(url); if(!r.ok) throw new Error(r.status); return await r.json(); } catch(e){ return null; } }

  async function fetchPartyLabels(year){
    const data = await safeFetchJSON(`partylabels.json`);
    const list = Array.isArray(data) ? data : (data[String(year)] || []);
    const keyToLabelShort = new Map();
    list.forEach(p=> keyToLabelShort.set(p.key, p.labelShort || p.labelLong || ''));
    return keyToLabelShort;
  }
  async function fetchANPVotes(year){
    const y = String(year);
    if (await isFinalizedYear(y)) return await safeFetchJSON(`data/${y}/anp_votes.json`);
    return await safeFetchJSON(`${DO_BASE}?year=${y}&source=anp_votes`);
  }
  async function fetchANPLastUpdate(year){
    const y = String(year);
    if (await isFinalizedYear(y)) return await safeFetchJSON(`data/${y}/anp_last_update.json`);
    return await safeFetchJSON(`${DO_BASE}?year=${y}&source=anp_last_update`);
  }

  let __kiesraadIndex = null;
  async function isFinalizedYear(year){
    const y = String(year);
    if (!__kiesraadIndex) __kiesraadIndex = await safeFetchJSON(`votes_kiesraad.json`);
    if (!__kiesraadIndex) return false;
    const entry = Array.isArray(__kiesraadIndex) ? __kiesraadIndex : __kiesraadIndex[y];
    return Array.isArray(entry) && entry.length > 0;
  }

  function createStatsTable(votesData, year){
    const table=document.createElement('table');
    const thead=table.createTHead(); const tbody=table.createTBody();
    const hr=thead.insertRow();
    ["", "Stemgerechtigden", "Opkomst", "Totale stemmen", "Ongeldige stemmen", "Blanco stemmen"].forEach(h=>{ const th=document.createElement('th'); th.textContent=h; hr.appendChild(th); });
    const cur=tbody.insertRow();
    const currentLabels = { '2021': '17 maart 2021', '2023': '22 november 2023', '2025': '29 oktober 2025' };
    const previousLabels = { '2021': 'Vorige', '2023': '17 maart 2021', '2025': '22 november 2023' };
    cur.insertCell().textContent = currentLabels[String(year)] || 'Huidig';
    cur.insertCell().textContent = Number(votesData.voters?.current || 0).toLocaleString('nl-NL');
    cur.insertCell().textContent = votesData.turnout?.current || '';
    cur.insertCell().textContent = Number(votesData.turnoutCount?.current || 0).toLocaleString('nl-NL');
    cur.insertCell().textContent = Number(votesData.invalid?.current || 0).toLocaleString('nl-NL');
    cur.insertCell().textContent = Number(votesData.blank?.current || 0).toLocaleString('nl-NL');
    const prev=tbody.insertRow();
    prev.insertCell().textContent = previousLabels[String(year)] || 'Vorige';
    prev.insertCell().textContent = Number(votesData.voters?.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = votesData.turnout?.previous || '';
    prev.insertCell().textContent = Number(votesData.turnoutCount?.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = Number(votesData.invalid?.previous || 0).toLocaleString('nl-NL');
    prev.insertCell().textContent = Number(votesData.blank?.previous || 0).toLocaleString('nl-NL');
    return table;
  }

  function createMainTable(votesData, keyToLabelShort){
    const table=document.createElement('table');
    const thead=table.createTHead(); const tbody=table.createTBody();
    const hr=thead.insertRow();
    const headers=[
      "Key","Label",
      "Results Previous Votes","Results Previous Percentage","Results Previous Seats",
      "Results Current Votes","Results Current Percentage","Results Current Seats",
      "Results Diff Votes","Results Diff Percentage","Results Diff Seats"
    ];
    headers.forEach(h=>{ const th=document.createElement('th'); th.innerHTML = `${h} <span class="sort-icon"></span>`; th.style.cursor='pointer'; hr.appendChild(th); });

    const rows = (votesData.parties||[]).map(p=>({
      Key: p.key,
      Label: keyToLabelShort.get(p.key) || '',
      PrevVotes: Number(p.results.previous.votes||0),
      PrevPerc: p.results.previous.percentage||'',
      PrevSeats: Number(p.results.previous.seats||0),
      CurrVotes: Number(p.results.current.votes||0),
      CurrPerc: p.results.current.percentage||'',
      CurrSeats: Number(p.results.current.seats||0),
      DiffVotes: Number(p.results.diff.votes||0),
      DiffPerc: p.results.diff.percentage||'',
      DiffSeats: Number(p.results.diff.seats||0)
    }));
    const cols = ['Key','Label','PrevVotes','PrevPerc','PrevSeats','CurrVotes','CurrPerc','CurrSeats','DiffVotes','DiffPerc','DiffSeats'];
    let sortState = { key:'CurrVotes', dir:'desc' };

    function updateHeaderIcons(){
      Array.from(hr.children).forEach((th, idx)=>{
        const icon = th.querySelector('.sort-icon');
        if (!icon) return;
        const key = cols[idx];
        if (key === sortState.key) icon.innerHTML = sortState.dir==='asc'?'&#9650;':'&#9660;'; else icon.innerHTML = '';
      });
    }

    function draw(){
      tbody.innerHTML='';
      const sorted = rows.slice().sort((a,b)=>{
        let A=a[sortState.key], B=b[sortState.key];
        if (typeof A==='number' && typeof B==='number') return sortState.dir==='asc'?(A-B):(B-A);
        A=(A||'').toString(); B=(B||'').toString();
        return sortState.dir==='asc'? A.localeCompare(B,undefined,{numeric:true}) : B.localeCompare(A,undefined,{numeric:true});
      });
      sorted.forEach(r=>{
        const tr=tbody.insertRow();
        const cells=[
          r.Key,
          r.Label,
          r.PrevVotes.toLocaleString('nl-NL'),
          r.PrevPerc,
          r.PrevSeats.toLocaleString('nl-NL'),
          r.CurrVotes.toLocaleString('nl-NL'),
          r.CurrPerc,
          r.CurrSeats.toLocaleString('nl-NL'),
          r.DiffVotes.toLocaleString('nl-NL'),
          r.DiffPerc,
          r.DiffSeats.toLocaleString('nl-NL')
        ];
        cells.forEach(val=>{ const td=tr.insertCell(); td.textContent=val; });
      });
    }
    draw();
    updateHeaderIcons();
    Array.from(hr.children).forEach((th, idx)=>{
      th.addEventListener('click', ()=>{
        const key = cols[idx];
        if (sortState.key===key) sortState.dir = (sortState.dir==='asc'?'desc':'asc'); else { sortState.key=key; sortState.dir='asc'; }
        draw();
        updateHeaderIcons();
      });
    });
    return table;
  }

  function updateLastUpdateFields(lastUpdateData, votesData){
    const lastUpdateEl = document.getElementById('lastUpdate');
    if (votesData?.updated && lastUpdateEl) lastUpdateEl.textContent = new Date(votesData.updated*1000).toLocaleString();
    const localRegion = lastUpdateData?.views?.find(v=>v.type===0);
    if (localRegion) {
      const ts=new Date(localRegion.updated*1000).toLocaleString();
      const el = document.getElementById('lastUpdatedLocalRegion');
      if (el) el.textContent = `Laatste gemeente: ${localRegion.label} (${ts})`;
    }
  }

  async function loadANPStemmen(year){
    // Clear
    ['statsTableContainer','tableContainer','lastUpdate','lastUpdatedLocalRegion'].forEach(id=>{ const el=document.getElementById(id); if (el) el.innerHTML=''; });
    const [labelsMap, votesData, lastUpdateData] = await Promise.all([
      fetchPartyLabels(year), fetchANPVotes(year), fetchANPLastUpdate(year)
    ]);
    if (votesData){ const stats=createStatsTable(votesData, year); const sc=document.getElementById('statsTableContainer'); if (sc) sc.appendChild(stats); }
    updateLastUpdateFields(lastUpdateData, votesData);
    const mainTable = createMainTable(votesData||{parties:[]}, labelsMap);
    const tc=document.getElementById('tableContainer'); if (tc){ tc.innerHTML=''; tc.appendChild(mainTable); }
  }

  window.ANPStemmenApp = { loadANPStemmen };
})();
