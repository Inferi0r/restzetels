// Shared year selector + persistence across pages
(function(){
  function withYear(href, year){
    try {
      const u = new URL(href, window.location.origin);
      u.searchParams.set('year', `TK${year}`);
      return u.pathname + u.search;
    } catch(e){
      // fallback for plain relative paths
      const hasQuery = href.includes('?');
      const base = href.split('?')[0];
      return base + (hasQuery ? '&' : '?') + 'year=' + encodeURIComponent(`TK${year}`);
    }
  }

  function updateNavLinks(year){
    document.querySelectorAll('nav .nav-center a').forEach(a => {
      a.href = withYear(a.getAttribute('href'), year);
    });
  }


  function setUrlYear(year){
    const url = new URL(window.location.href);
    url.searchParams.set('year', `TK${year}`);
    window.history.replaceState({}, '', url.pathname + url.search);
  }

  function populateSelect(select, years, year){
    select.innerHTML = '';
    years.forEach(y => {
      const opt = document.createElement('option');
      opt.value = y; opt.textContent = `TK ${y}`;
      select.appendChild(opt);
    });
    if (years.includes(year)) select.value = year; else select.value = years[0];
  }

  async function discoverYears(){
    if (window.Data && typeof Data.discoverYears === 'function') return Data.discoverYears();
    // Fallback if Data isn't available yet
    try {
      const res = await fetch('data/partylabels.json', { cache: 'no-store' });
      if (!res.ok) throw new Error('no partylabels');
      const data = await res.json();
      if (Array.isArray(data)) return ['2021','2023','2025'];
      const years = Object.keys(data||{}).filter(k=>/^\d{4}$/.test(k));
      if (years.length) return years.sort((a,b)=>parseInt(a,10)-parseInt(b,10));
    } catch(e) {}
    return ['2021','2023','2025'];
  }

  function init(opts){
    (async () => {
      const load = typeof opts.load === 'function' ? opts.load : function(){};
      const select = document.getElementById('yearSelect');
      const years = (opts.years && opts.years.length) ? opts.years : await discoverYears();
      // Determine default as latest year if no URL or stored selection
      const params = new URLSearchParams(window.location.search);
      const fromUrl = params.get('year');
      // If someone uses plain numeric year in URL, bounce to home as requested
      if (fromUrl && /^\d{4}$/.test(fromUrl)) { try { window.location.href = '/'; return; } catch(e){} }
      const fromUrlNum = fromUrl ? (String(fromUrl).match(/\d{4}/)||[])[0] : null;
      const fromStore = window.localStorage.getItem('selectedYear');
      const latest = String(Math.max.apply(null, years.map(y=>parseInt(y,10))));
      const year = fromUrlNum || fromStore || latest;
      populateSelect(select, years, year);
      setUrlYear(year);
      updateNavLinks(year);
      window.localStorage.setItem('selectedYear', year);
      try { window.CURRENT_YEAR = String(year); } catch(e){}
      // callback to load page data
      load(year);
      select.addEventListener('change', function(){
        const y = this.value;
        window.localStorage.setItem('selectedYear', y);
        setUrlYear(y);
        updateNavLinks(y);
        try { window.CURRENT_YEAR = String(y); } catch(e){}
        load(y);
      });
    })();
  }

  window.YearNav = { init };
})();
