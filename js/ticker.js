(function(){
  const prefersReduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function relTime(ms){
    if (!ms) return '';
    const s = Math.max(0, Math.floor((Date.now() - ms)/1000));
    if (s < 60) return `${s}s geleden`;
    const m = Math.floor(s/60); if (m < 60) return `${m}m geleden`;
    const h = Math.floor(m/60); if (h < 24) return `${h}u geleden`;
    const d = Math.floor(h/24); return `${d}d geleden`;
  }

  function statusClass(text){
    const t = (text||'').toString().toLowerCase();
    if (t.indexOf('tussen')===0) return 'chip--tussenstand';
    if (t.indexOf('eind')===0) return 'chip--eindstand';
    return 'chip--nulstand';
  }

  function buildItemsFromNos(nosIndex){
    const rows = Array.isArray(nosIndex?.gemeentes) ? nosIndex.gemeentes.slice() : [];
    rows.sort((a,b)=> new Date(b.publicatie_datum_tijd) - new Date(a.publicatie_datum_tijd));
    return rows.map(g => {
      const name = g?.gemeente?.naam || '';
      const status = g?.status || '';
      const ts = g?.publicatie_datum_tijd ? new Date(g.publicatie_datum_tijd).getTime() : 0;
      return { name, status, ts, source: 'NOS' };
    });
  }

  function buildItemsFromAnp(anp){
    const views = Array.isArray(anp?.views) ? anp.views.slice() : [];
    // type 0 = gemeente
    const gemeenten = views.filter(v => v && v.type === 0);
    gemeenten.sort((a,b)=> (b.updated||0) - (a.updated||0));
    const mapStatus = (n) => (n===4?'Eindstand':(n===2?'Tussenstand':'Nulstand'));
    return gemeenten.map(v => ({ name: v.label || '', status: mapStatus(v.status), ts: (v.updated||0)*1000, source: 'ANP' }));
  }

  function renderChips(track, items){
    const html = items.map(it => {
      const when = relTime(it.ts);
      const cls = statusClass(it.status);
      const sourceCls = it.source === 'ANP' ? 'chip--source-anp' : 'chip--source-nos';
      const sourceLabel = it.source;
      return `<div class="ticker-chip">`+
             `<span class="chip chip--source ${sourceCls}">${sourceLabel}</span>`+
             `<span class="chip ${cls}"><span class="chip-dot"></span>${it.status}</span>`+
             `<span class="ticker-name">${it.name}</span>`+
             `<span class="ticker-dot">•</span>`+
             `<span class="ticker-when muted small">${when}</span>`+
             `</div>`;
    }).join('');
    // duplicate to make seamless loop
    track.innerHTML = html + html;
  }

  function startScroll(container){
    if (prefersReduce) return; // respect reduced motion
    const track = container.querySelector('.ticker-track');
    if (!track) return;
    let x = 0; let lastTs = performance.now();
    const speed = 60; // px/sec (doubled)
    let paused = false; let rafId = 0;

    function step(ts){
      const dt = (ts - lastTs)/1000; lastTs = ts;
      if (!paused) {
        x += speed * dt;
        const half = track.scrollWidth / 2; // since we duplicated
        if (x >= half) x -= half;
        track.style.transform = `translateX(${-x}px)`;
      }
      rafId = requestAnimationFrame(step);
    }
    const onEnter = ()=>{ paused = true; };
    const onLeave = ()=>{ paused = false; };
    container.addEventListener('mouseenter', onEnter);
    container.addEventListener('focusin', onEnter);
    container.addEventListener('mouseleave', onLeave);
    container.addEventListener('focusout', onLeave);
    rafId = requestAnimationFrame(step);
  }

  function update(opts){
    const nosIndex = opts && opts.nosIndex;
    const anp = opts && opts.anpLastUpdate;
    const container = document.getElementById('nosTickerContainer');
    if (!container) return;
    if (!container.querySelector('.ticker-track')) {
      const track = document.createElement('div');
      track.className = 'ticker-track';
      container.appendChild(track);
    }
    const track = container.querySelector('.ticker-track');
    const items = ([])
      .concat(buildItemsFromNos(nosIndex))
      .concat(buildItemsFromAnp(anp))
      .sort((a,b)=> b.ts - a.ts)
      .slice(0,5);
    if (!items.length) { container.style.display='none'; return; }
    container.style.display='block';
    renderChips(track, items);
    startScroll(container);
  }

  // Back-compat: if older call used
  function updateFromNosIndex(nosIndex){ update({ nosIndex }); }

  window.Ticker = { update, updateFromNosIndex };
})();
