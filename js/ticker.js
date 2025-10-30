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

  function signature(items){
    return items.map(it => `${it.source}|${it.name}|${it.ts}`).join('||');
  }

  function refreshWhen(container, items){
    try {
      const track = container.querySelector('.ticker-track');
      if (!track) return;
      const spans = track.querySelectorAll('.ticker-when');
      if (!spans.length) return;
      const n = items.length;
      for (let loop=0; loop<2; loop++) {
        for (let i=0; i<n; i++) {
          const idx = loop*n + i;
          if (spans[idx]) spans[idx].textContent = relTime(items[i].ts);
        }
      }
    } catch(e){}
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
    const st = container._ticker || (container._ticker = { x:0, speed:60, paused:false, rafId:0, whenTimer:0, lastHalf:0, listenersAttached:false, sig:'' });
    if (st.rafId) return; // already running
    let lastTs = performance.now();
    function step(ts){
      const dt = (ts - lastTs)/1000; lastTs = ts;
      if (!st.paused) {
        st.x += st.speed * dt;
        const half = track.scrollWidth / 2; // since we duplicated
        st.lastHalf = half || st.lastHalf || 1;
        if (st.x >= st.lastHalf) st.x -= st.lastHalf;
        track.style.transform = `translateX(${-st.x}px)`;
      }
      st.rafId = requestAnimationFrame(step);
    }
    if (!st.listenersAttached) {
      const onEnter = ()=>{ st.paused = true; };
      const onLeave = ()=>{ st.paused = false; };
      container.addEventListener('mouseenter', onEnter);
      container.addEventListener('focusin', onEnter);
      container.addEventListener('mouseleave', onLeave);
      container.addEventListener('focusout', onLeave);
      st.listenersAttached = true;
    }
    st.rafId = requestAnimationFrame(step);
  }

  function update(opts){
    const nosIndex = opts && opts.nosIndex;
    const anp = opts && opts.anpLastUpdate;
    const targetYear = (opts && opts.year) ? String(opts.year) : null;
    const container = document.getElementById('nosTickerContainer');
    if (!container) return;
    // Ignore updates for a different year (e.g., late responses after a year switch)
    try {
      const selectedYear = (window.CURRENT_YEAR && String(window.CURRENT_YEAR)) || (document.getElementById('yearSelect')?.value) || (new URLSearchParams(window.location.search).get('year')) || window.localStorage.getItem('selectedYear') || targetYear;
      if (targetYear && String(selectedYear) !== String(targetYear)) return;
      // Persist the currently rendered year on the container to reject late updates
      container.dataset.year = String(selectedYear || '');
    } catch(e) {}
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
    if (!items.length) {
      container.style.display='none';
      const st = container._ticker;
      if (st) {
        try { if (st.rafId) cancelAnimationFrame(st.rafId); } catch(e){}
        st.rafId = 0;
        if (st.whenTimer) { clearInterval(st.whenTimer); st.whenTimer = 0; }
      }
      return;
    }
    container.style.display='block';
    const st = container._ticker || (container._ticker = { x:0, speed:60, paused:false, rafId:0, whenTimer:0, lastHalf:0, listenersAttached:false, sig:'' });
    const sig = signature(items);
    if (st.sig !== sig) {
      // preserve scroll progress relative to previous width
      const progress = st.lastHalf ? ((st.x % st.lastHalf) / st.lastHalf) : 0;
      renderChips(track, items);
      st.lastHalf = track.scrollWidth / 2;
      st.x = progress * (st.lastHalf || 1);
      st.sig = sig;
    } else {
      refreshWhen(container, items);
    }
    if (!st.whenTimer) st.whenTimer = setInterval(()=> refreshWhen(container, items), 1000);
    startScroll(container);
  }

  // Back-compat: if older call used
  function updateFromNosIndex(nosIndex){ update({ nosIndex }); }

  window.Ticker = { update, updateFromNosIndex };
})();
