// Unified ANP updates table
(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);

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
        Status: statusMap.get(item.status) || item.status,
        Updated: updatedTs,
        UpdatedDisplay: updatedTs ? new Date(updatedTs).toLocaleString('nl-NL') : '',
        Parent: item.parent ? (viewMap.get(item.parent) || item.parent) : '',
        Huidig: (item.topPartiesCurrent||[]).map(k=>partyLabels.get(k)||k).join(', '),
        Vorige: (item.topPartiesPrevious||[]).map(k=>partyLabels.get(k)||k).join(', ')
      };
    });
  }

  function renderSortableTable(container, rows){
    const columns = [
      {key:'Key', label:'Key'},
      {key:'Type', label:'Type'},
      {key:'CBS', label:'CBS Code'},
      {key:'Label', label:'Label'},
      {key:'Status', label:'Status'},
      {key:'Updated', label:'Laatste Update', display:'UpdatedDisplay'},
      {key:'Parent', label:'Parent'},
      {key:'Huidig', label:'Grootste partijen (huidig)'},
      {key:'Vorige', label:'Grootste partijen (vorige)'}
    ];
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
          td.textContent = (val!=null) ? val.toString() : '';
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
    const container = document.getElementById('tableContainer');
    const rows = buildRows(lastUpdateData || {views:[]}, partyLabelsMap);
    renderSortableTable(container, rows);
  }

  window.ANPUpdatesApp = { loadANPUpdates };
})();
