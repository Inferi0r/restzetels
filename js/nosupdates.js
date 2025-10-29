// Unified NOS updates table
(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);

  async function safeFetchJSON(url){ try{ const r=await fetch(url); if(!r.ok) throw new Error(r.status); return await r.json(); } catch(e){ return null; } }
  async function fetchNOS(year){
    // Prefer bundle to reduce calls
    if (window.Data && typeof Data.fetchBundle==='function') {
      const b = await Data.fetchBundle(year); return b && b.nos_index ? b.nos_index : null;
    }
    const y = String(year);
    if (await isFinalizedYear(y)) return await safeFetchJSON(`data/${y}/nos_index.json`);
    return await safeFetchJSON(`${DO_BASE}?year=${y}&source=nos_index`);
  }

  let __kiesraadIndex = null;
  async function isFinalizedYear(year){
    const y = String(year);
    if (!__kiesraadIndex) __kiesraadIndex = await safeFetchJSON(`votes_kiesraad.json`);
    if (!__kiesraadIndex) return false;
    const entry = Array.isArray(__kiesraadIndex) ? __kiesraadIndex : __kiesraadIndex[y];
    return Array.isArray(entry) && entry.length > 0;
  }


  function createHeaderRow(headers){ const thead=document.createElement('thead'); const tr=thead.insertRow(); headers.forEach((h,idx)=>{ const th=document.createElement('th'); th.innerHTML = `${h} <span class="sort-icon"></span>`; th.dataset.idx = idx; th.style.cursor='pointer'; tr.appendChild(th); }); return thead; }

  function extractRows(data){
    return (data.gemeentes||[]).map(item=>{
      const g = (path) => path.split('.').reduce((acc,k)=> (acc && k in acc) ? acc[k] : null, item);
      const opmH = g('huidige_verkiezing.opkomst_promillage');
      const opmV = g('vorige_verkiezing.opkomst_promillage');
      const iso = g('publicatie_datum_tijd');
      const d = iso ? new Date(iso) : null;
      const pad = (n) => String(n).padStart(2,'0');
      const lastDisp = d ? `${d.getDate()}-${d.getMonth()+1}-${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` : '';
      const row = {
        Status: g('status') || '',
        Laatste: iso || '',
        LaatsteTs: d ? d.getTime() : 0,
        LaatsteDisplay: lastDisp,
        Gemeente: g('gemeente.naam') || '',
        InwonersGemeente: g('gemeente.aantal_inwoners') || 0,
        Kieskring: g('gemeente.kieskring') || '',
        Provincie: g('gemeente.provincie.naam') || '',
        InwonersProvincie: g('gemeente.provincie.aantal_inwoners') || 0,
        Eerste: g('eerste_partij.short_name') || '',
        Tweede: g('tweede_partij.short_name') || '',
        OpkomstHuidig: (typeof opmH==='number') ? (opmH/10).toFixed(1).replace('.', ',')+'%' : '',
        OpkomstVorige: (typeof opmV==='number') ? (opmV/10).toFixed(1).replace('.', ',')+'%' : ''
      };
      return row;
    });
  }

  function renderSortable(container, rows){
    const headers = ['Status','Laatste Update','Gemeente','Inwoners Gemeente','Kieskring','Provincie','Inwoners Provincie','1e Partij','2e Partij','Opkomst (huidig)','Opkomst (vorige)'];
    const cols = ['Status','Laatste','Gemeente','InwonersGemeente','Kieskring','Provincie','InwonersProvincie','Eerste','Tweede','OpkomstHuidig','OpkomstVorige'];
    let sortState = { key:'Laatste', dir:'desc' };
    const table = document.createElement('table');
    const thead = createHeaderRow(headers);
    const tbody = document.createElement('tbody');
    table.appendChild(thead); table.appendChild(tbody);
    const ths = Array.from(thead.querySelectorAll('th'));
    function updateHeaderIcons(){
      ths.forEach((th,i)=>{
        const icon = th.querySelector('.sort-icon');
        const key = cols[i];
        if (!icon) return;
        if (key === sortState.key) icon.innerHTML = sortState.dir==='asc'?'&#9650;':'&#9660;'; else icon.innerHTML = '';
      });
    }
    function draw(){
      tbody.innerHTML = '';
      const sorted = rows.slice().sort((a,b)=>{
        let A=a[sortState.key], B=b[sortState.key];
        if (sortState.key==='Laatste') { A=a.LaatsteTs; B=b.LaatsteTs; }
        if (['InwonersGemeente','InwonersProvincie'].includes(sortState.key)) { A=Number(A)||0; B=Number(B)||0; return sortState.dir==='asc'?(A-B):(B-A); }
        if (typeof A==='number' && typeof B==='number') return sortState.dir==='asc'?(A-B):(B-A);
        A=(A||'').toString(); B=(B||'').toString();
        return sortState.dir==='asc'? A.localeCompare(B,undefined,{numeric:true}) : B.localeCompare(A,undefined,{numeric:true});
      });
      sorted.forEach(r=>{
        const tr = tbody.insertRow();
        cols.forEach(k=>{ const td=tr.insertCell(); const val = (k==='Laatste') ? r.LaatsteDisplay : r[k]; td.textContent = val || ''; });
      });
    }
    // attach sort handlers
    ths.forEach((th, idx)=>{
      th.addEventListener('click', ()=>{
        const key = cols[idx];
        if (sortState.key === key) sortState.dir = (sortState.dir==='asc'?'desc':'asc'); else { sortState.key=key; sortState.dir='asc'; }
        draw();
        updateHeaderIcons();
      });
    });
    draw();
    updateHeaderIcons();
    container.innerHTML = '';
    container.appendChild(table);
  }

  function createAndPopulateTable(container, data){
    const rows = extractRows(data);
    renderSortable(container, rows);
  }

  async function loadNOSUpdates(year){
    const container = document.getElementById('tableContainer');
    container.innerHTML='';
    const nosData = await fetchNOS(year);
    createAndPopulateTable(container, nosData || {gemeentes:[]});
  }

  window.NOSUpdatesApp = { loadNOSUpdates };
})();
