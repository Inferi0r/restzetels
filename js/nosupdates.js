// Unified NOS updates table
(function(){
  const DO_BASE = 'https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata';

  async function safeFetchJSON(url){ try{ const r=await fetch(url); if(!r.ok) throw new Error(r.status); return await r.json(); } catch(e){ return null; } }
  async function fetchNOS(year){ return await safeFetchJSON(`${DO_BASE}?year=${year}&source=nos`); }

  function formatNumber(num){ return (typeof num==='number') ? num.toLocaleString('nl-NL') : ''; }
  function formatPercentage(promillage){ return (typeof promillage==='number') ? (promillage/10).toFixed(1)+'%' : ''; }
  function formatDate(dt){ if (typeof dt!=='string') return ''; const d=new Date(dt); return d.toLocaleString('nl-NL'); }

  function createHeaderRow(headers){ const thead=document.createElement('thead'); const tr=thead.insertRow(); headers.forEach(h=>{ const th=document.createElement('th'); th.textContent=h; tr.appendChild(th); }); return thead; }

  function createTableBody(data){
    const tbody=document.createElement('tbody');
    (data.gemeentes||[]).forEach(item=>{
      const row=tbody.insertRow();
      const columns=[
        'status','publicatie_datum_tijd','gemeente.naam','gemeente.aantal_inwoners','gemeente.kieskring','gemeente.provincie.naam','gemeente.provincie.aantal_inwoners','eerste_partij.short_name','tweede_partij.short_name','huidige_verkiezing.opkomst_promillage','vorige_verkiezing.opkomst_promillage'
      ];
      columns.forEach(col=>{
        const cell=row.insertCell();
        const keys=col.split('.'); let val=item; keys.forEach(k=>{ val = (val && k in val) ? val[k] : null; });
        if (col.endsWith('opkomst_promillage')) val = formatPercentage(val);
        else if (col.endsWith('aantal_inwoners')) val = formatNumber(val);
        else if (col==='publicatie_datum_tijd') val = formatDate(val);
        cell.textContent = val!=null ? val.toString() : '';
      });
    });
    return tbody;
  }

  function createAndPopulateTable(data){
    const copy = { gemeentes: (data.gemeentes||[]).slice().sort((a,b)=> new Date(b.publicatie_datum_tijd) - new Date(a.publicatie_datum_tijd)) };
    const headers=['Status','Laatste Update','Gemeente','Inwoners Gemeente','Kieskring','Provincie','Inwoners Provincie','1e Partij','2e Partij','Opkomst (huidig)','Opkomst (vorige)'];
    const table=document.createElement('table');
    table.appendChild(createHeaderRow(headers));
    table.appendChild(createTableBody(copy));
    return table;
  }

  async function loadNOSUpdates(year){
    const container = document.getElementById('tableContainer');
    container.innerHTML='';
    const nosData = await fetchNOS(year);
    const table = createAndPopulateTable(nosData || {gemeentes:[]});
    container.appendChild(table);
  }

  window.NOSUpdatesApp = { loadNOSUpdates };
})();

