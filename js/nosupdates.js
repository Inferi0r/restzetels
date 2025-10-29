// Unified NOS updates table
(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);
  async function fetchNOS(year){
    // Prefer bundle to reduce calls
    if (window.Data && typeof Data.fetchBundle==='function') {
      const b = await Data.fetchBundle(year); return b && b.nos_index ? b.nos_index : null;
    }
    const y = String(year);
    if (await Data.isFinalizedYear(y)) return await Data.safeJSON(`data/${y}/nos_index.json`);
    return await Data.safeJSON(`${DO_BASE}?year=${y}&source=nos_index`);
  }

  // finalized year provided by Data


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
    function statusChip(text){
      const t = (text||'').toString().toLowerCase();
      let cls = 'chip--nulstand';
      if (t.indexOf('tussen')===0) cls = 'chip--tussenstand';
      else if (t.indexOf('eind')===0) cls = 'chip--eindstand';
      return `<span class="chip ${cls}"><span class="chip-dot"></span>${text||''}</span>`;
    }

    function relTime(ms){
      if (!ms) return '';
      const s = Math.max(0, Math.floor((Date.now() - ms)/1000));
      if (s < 60) return `${s}s geleden`;
      const m = Math.floor(s/60); if (m < 60) return `${m}m geleden`;
      const h = Math.floor(m/60); if (h < 24) return `${h}u geleden`;
      const d = Math.floor(h/24); return `${d}d geleden`;
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
        cols.forEach(k=>{
          const td=tr.insertCell();
          if (k === 'Status') {
            td.innerHTML = statusChip(r[k] || '');
          } else if (k === 'Laatste') {
            const rel = relTime(r.LaatsteTs);
            td.innerHTML = `${r.LaatsteDisplay || ''} <span class="muted small">${rel ? '('+rel+')' : ''}</span>`;
          } else if (k === 'InwonersGemeente' || k === 'InwonersProvincie') {
            td.classList.add('num');
            const val = r[k];
            td.textContent = (val || val===0) ? Number(val).toLocaleString('nl-NL') : '';
          } else {
            const val = (k==='Laatste') ? r.LaatsteDisplay : r[k];
            td.textContent = val || '';
          }
        });
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
