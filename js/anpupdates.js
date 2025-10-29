// Unified ANP updates table
(function(){
  const DO_BASE = 'https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata';

  async function safeFetchJSON(url){ try{ const r=await fetch(url); if(!r.ok) throw new Error(r.status); return await r.json(); } catch(e){ return null; } }
  async function fetchPartyLabels(year){ const d=await safeFetchJSON(`partylabels.json`); const list=Array.isArray(d)?d:(d[String(year)]||[]); return new Map(list.map(p=>[p.key, p.labelShort])); }
  async function fetchLastUpdate(year){ return await safeFetchJSON(`${DO_BASE}?year=${year}&source=last_update`); }

  function createTypeMap(){ return new Map([[0,'Gemeente'],[1,'Provincie'],[2,'Rijk']]); }
  function createStatusMap(){ return new Map([[0,'Nulstand'],[2,'Tussenstand'],[4,'Eindstand']]); }

  function populateTable(data, partyLabels){
    const table = document.createElement('table');
    const thead = table.createTHead(); const tbody = table.createTBody();
    const hr = thead.insertRow();
    ["Key","Type","CBS Code","Label","Status","Laatste Update","Parent","Grootste partijen (huidig)","Grootste partijen (vorige)"]
      .forEach(h=>{ const th=document.createElement('th'); th.textContent=h; hr.appendChild(th); });
    const viewMap = new Map((data.views||[]).map(v=>[v.key, v.label]));
    const typeMap = createTypeMap(); const statusMap = createStatusMap();

    (data.views||[]).forEach(item=>{
      const row = document.createElement('tr');
      const cols = [
        item.key,
        typeMap.get(item.type) || item.type,
        item.cbsCode || '',
        item.label || '',
        statusMap.get(item.status) || item.status,
        item.updated ? new Date(item.updated*1000).toLocaleString('nl-NL') : '',
        item.parent ? (viewMap.get(item.parent) || item.parent) : ''
      ];
      cols.forEach(v=>{ const td=document.createElement('td'); td.textContent=v; row.appendChild(td); });
      // top parties current/previous mapped to labels
      ['topPartiesCurrent','topPartiesPrevious'].forEach(prop=>{
        const td = document.createElement('td');
        const arr = item[prop] || [];
        td.textContent = arr.map(k => partyLabels.get(k) || k).join(', ');
        row.appendChild(td);
      });
      // Removed source/progress columns as requested
      tbody.appendChild(row);
    });
    return table;
  }

  async function loadANPUpdates(year){
    const [partyLabelsMap, lastUpdateData] = await Promise.all([fetchPartyLabels(year), fetchLastUpdate(year)]);
    const container = document.getElementById('tableContainer');
    container.innerHTML='';
    const table = populateTable(lastUpdateData || {views:[]}, partyLabelsMap);
    container.appendChild(table);
  }

  window.ANPUpdatesApp = { loadANPUpdates };
})();
