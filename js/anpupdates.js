// Unified ANP updates table
(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);
  const lastRenderSigByYear = new Map();

  async function fetchPartyLabels(year){
    const labels = await Data.fetchPartyLabels(year);
    return labels.keyToLabelShort;
  }
  async function fetchLastUpdate(year){
    // Prefer bundle to reduce calls
    if (window.Data && typeof Data.fetchBundle==='function') {
      const b = await Data.fetchBundle(year); return b && b.anp_last_update ? b.anp_last_update : null;
    }
    const y = String(year);
    if (await Data.isFinalizedYear(y)) return await Data.safeJSON(`data/${y}/anp_last_update.json`);
    return await Data.safeJSON(`${DO_BASE}?year=${y}&source=anp_last_update`);
  }

  // finalized year provided by Data

  // Time formatting helpers for uniform Dutch numeric style
  function pad2(n){ return String(n).padStart(2,'0'); }
  function formatDateTimeNL(ms, opts = {}){
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
  }

  function createTypeMap(){ return new Map([[0,'Gemeente'],[1,'Provincie'],[2,'Rijk']]); }
  function createStatusMap(){ return new Map([[0,'Nulstand'],[2,'Tussenstand'],[4,'Eindstand']]); }

  function buildRows(data, partyLabels){
    const viewMap = new Map((data.views||[]).map(v=>[v.key, v.label]));
    const typeMap = createTypeMap(); const statusMap = createStatusMap();
    return (data.views||[]).map(item => {
      const updatedTs = item.updated ? (item.updated*1000) : 0;
      return {
        Key: item.key,
        Type: typeMap.get(item.type) || item.type,
        CBS: item.cbsCode || '',
        Label: item.label || '',
        Lijsten: (typeof item.countParties === 'number') ? item.countParties : '',
        Status: statusMap.get(item.status) || item.status,
        Updated: updatedTs,
        UpdatedDisplay: updatedTs ? formatDateTimeNL(updatedTs, { seconds: 'auto' }) : '',
        Parent: item.parent ? (viewMap.get(item.parent) || item.parent) : '',
        Huidig: (item.topPartiesCurrent||[]).map(k=>partyLabels.get(k)||k).join(', '),
        Vorige: (item.topPartiesPrevious||[]).map(k=>partyLabels.get(k)||k).join(', ')
      };
    });
  }

  function renderSortableTable(container, rows){
    let columns = [
      {key:'Status', label:'Status'},
      {key:'Updated', label:'Laatste Update', display:'UpdatedDisplay'},
      {key:'Type', label:'Type'},
      {key:'CBS', label:'CBS Code'},
      {key:'Label', label:'Label'},
      {key:'Lijsten', label:'Aantal lijsten'},
      {key:'Parent', label:'Parent'},
      {key:'Huidig', label:'Grootste partijen (huidig)'},
      {key:'Vorige', label:'Grootste partijen (vorige)'}
    ];
    const hasLijsten = rows && rows.some(r => r && r.Lijsten !== '' && r.Lijsten != null);
    if (!hasLijsten) {
      columns = columns.filter(c => c.key !== 'Lijsten');
    }
    let sortState = { key:'Updated', dir:'desc' };
    const table = document.createElement('table');
    const thead = table.createTHead();
    const tbody = table.createTBody();
    const hr = thead.insertRow();
    columns.forEach(col => {
      const th = document.createElement('th');
      th.dataset.key = col.key;
      th.style.cursor = 'pointer';
      th.innerHTML = `${col.label} <span class="sort-icon"></span>`;
      th.addEventListener('click', () => {
        if (sortState.key === col.key) {
          sortState.dir = (sortState.dir === 'asc') ? 'desc' : 'asc';
        } else {
          sortState.key = col.key; sortState.dir = 'asc';
        }
        updateHeaderIcons();
        drawBody();
      });
      hr.appendChild(th);
    });

    function updateHeaderIcons(){
      Array.from(hr.children).forEach(th => {
        const key = th.dataset.key;
        const icon = th.querySelector('.sort-icon');
        if (!icon) return;
        if (key === sortState.key) {
          icon.innerHTML = sortState.dir === 'asc' ? '&#9650;' : '&#9660;';
        } else {
          icon.innerHTML = '';
        }
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

    function drawBody(){
      tbody.innerHTML = '';
      const sorted = rows.slice().sort((a,b)=>{
        let A = a[sortState.key]; let B = b[sortState.key];
        // numeric for timestamp Updated and numeric-ish keys
        if (sortState.key === 'Updated') { /* keep as number */ }
        else if ([ 'Key' ].includes(sortState.key)) {
          const na = parseInt(A,10); const nb = parseInt(B,10);
          if (!isNaN(na) && !isNaN(nb)) { A = na; B = nb; }
        }
        if (typeof A === 'number' && typeof B === 'number') return sortState.dir==='asc' ? (A-B) : (B-A);
        A = (A||'').toString(); B = (B||'').toString();
        return sortState.dir==='asc' ? A.localeCompare(B, undefined, {numeric:true}) : B.localeCompare(A, undefined, {numeric:true});
      });
      sorted.forEach(r => {
        const tr = tbody.insertRow();
        columns.forEach(col => {
          const td = tr.insertCell();
          const val = col.display ? r[col.display] : r[col.key];
          if (col.key === 'Status') {
            td.innerHTML = statusChip(val);
          } else if (col.key === 'Updated') {
            const rel = relTime(r.Updated);
            td.innerHTML = `${r.UpdatedDisplay || ''} <span class="muted small">${rel ? '('+rel+')' : ''}</span>`;
          } else if (col.key === 'CBS' || col.key === 'Lijsten') {
            td.classList.add('num');
            td.textContent = (val!=null) ? val.toString() : '';
          } else {
            td.textContent = (val!=null) ? val.toString() : '';
          }
        });
      });
    }
    updateHeaderIcons();
    drawBody();
    container.innerHTML = '';
    container.appendChild(table);
  }

  async function loadANPUpdates(year){
    const [partyLabelsMap, lastUpdateData] = await Promise.all([fetchPartyLabels(year), fetchLastUpdate(year)]);
    // Compute signature: max updated across views
    let maxTs = 0;
    try {
      const views = Array.isArray(lastUpdateData && lastUpdateData.views) ? lastUpdateData.views : [];
      maxTs = views.reduce((m,v)=> Math.max(m, Number(v && v.updated)||0), 0);
    } catch(e){}
    const yKey = String(year);
    const sig = String(maxTs);
    if (lastRenderSigByYear.get(yKey) === sig) return; // no changes — skip DOM work
    lastRenderSigByYear.set(yKey, sig);
    const container = document.getElementById('tableContainer');
    const rows = buildRows(lastUpdateData || {views:[]}, partyLabelsMap);
    renderSortableTable(container, rows);
  }

  window.ANPUpdatesApp = { loadANPUpdates };
})();
