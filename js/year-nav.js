// Shared year selector + persistence across pages
(function(){
  function withYear(href, year){
    try {
      const u = new URL(href, window.location.origin);
      u.searchParams.set('year', year);
      return u.pathname + u.search;
    } catch(e){
      // fallback for plain relative paths
      const hasQuery = href.includes('?');
      const base = href.split('?')[0];
      return base + (hasQuery ? '&' : '?') + 'year=' + encodeURIComponent(year);
    }
  }

  function updateNavLinks(year){
    document.querySelectorAll('nav .nav-center a').forEach(a => {
      a.href = withYear(a.getAttribute('href'), year);
    });
  }

  function currentYear(defaultYear){
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get('year');
    const fromStore = window.localStorage.getItem('selectedYear');
    return fromUrl || fromStore || defaultYear || '2023';
  }

  function setUrlYear(year){
    const url = new URL(window.location.href);
    url.searchParams.set('year', year);
    window.history.replaceState({}, '', url.pathname + url.search);
  }

  function populateSelect(select, years, year){
    select.innerHTML = '';
    years.forEach(y => {
      const opt = document.createElement('option');
      opt.value = y; opt.textContent = `Verkiezingen ${y}`;
      select.appendChild(opt);
    });
    if (years.includes(year)) select.value = year; else select.value = years[0];
  }

  function init(opts){
    const years = opts.years || ['2021','2023','2025'];
    const def = opts.defaultYear || '2023';
    const load = typeof opts.load === 'function' ? opts.load : function(){};
    const select = document.getElementById('yearSelect');
    const year = currentYear(def);
    populateSelect(select, years, year);
    setUrlYear(year);
    updateNavLinks(year);
    window.localStorage.setItem('selectedYear', year);
    // callback to load page data
    load(year);
    select.addEventListener('change', function(){
      const y = this.value;
      window.localStorage.setItem('selectedYear', y);
      setUrlYear(y);
      updateNavLinks(y);
      load(y);
    });
  }

  window.YearNav = { init };
})();

