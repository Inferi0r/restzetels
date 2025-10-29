// Auto-refresh controller shared across pages
// Configurable interval at the top.
const REFRESH_INTERVAL_SECONDS = 30; // change here if needed

(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);
  let channel;
  try { channel = new BroadcastChannel('restzetels-refresh'); } catch(e) { channel = null; }

  let timerId = null;
  let secondTickId = null;
  let remaining = REFRESH_INTERVAL_SECONDS;
  let currentYear = null;
  let finalizedCache = null;
  let inProgress = false;

  function getYear(){
    const params = new URLSearchParams(window.location.search);
    return params.get('year') || window.localStorage.getItem('selectedYear') || '2023';
  }

  async function loadJSON(url){
    try { const r = await fetch(url, { cache: 'no-store' }); if (!r.ok) throw new Error(r.status); return await r.json(); } catch(e){ return null; }
  }

  async function isFinalizedYear(year){
    if (!finalizedCache) finalizedCache = await loadJSON('votes_kiesraad.json');
    if (!finalizedCache) return false;
    const entry = Array.isArray(finalizedCache) ? finalizedCache : finalizedCache[String(year)];
    return Array.isArray(entry) && entry.length > 0;
  }

  async function fetchLastUpdate(year){
    // Prefer shared bundle to avoid an extra request and share cache
    if (window.Data && typeof Data.fetchBundle === 'function') {
      const b = await Data.fetchBundle(year);
      return b ? b.anp_last_update : null;
    }
    if (await isFinalizedYear(year)) return await loadJSON(`data/${year}/anp_last_update.json`);
    return await loadJSON(`${DO_BASE}?year=${encodeURIComponent(year)}&source=anp_last_update`);
  }

  function allGemeentesComplete(lastUpdate){
    const views = (lastUpdate && Array.isArray(lastUpdate.views)) ? lastUpdate.views : [];
    const gemeenten = views.filter(v => v.type === 0);
    return gemeenten.length > 0 && gemeenten.every(v => v.status === 4);
  }

  function updateBadge(text){
    const el = document.getElementById('completedBadge');
    if (!el) return;
    if (!text) { el.style.display = 'none'; el.textContent = ''; return; }
    el.textContent = text;
    el.style.display = 'inline-block';
  }

  function setSoundVisible(show){
    const wrap = document.getElementById('soundWrap');
    if (!wrap) return; // only on Zetels page
    wrap.style.display = show ? 'inline-flex' : 'none';
  }

  function clearTimers(){
    if (timerId) { clearInterval(timerId); timerId = null; }
    if (secondTickId) { clearInterval(secondTickId); secondTickId = null; }
  }

  function resetUI(){
    clearTimers();
    updateBadge('');
    setSoundVisible(false);
  }

  function startCountdown(onFire){
    clearTimers();
    remaining = REFRESH_INTERVAL_SECONDS;
    updateBadge(`Volgende update: ${remaining}s`);
    // Second display tick
    secondTickId = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) remaining = 0;
      updateBadge(`Volgende update: ${remaining}s`);
    }, 1000);
    // Fire loader at interval
    timerId = setInterval(async () => {
      // show 0s during refresh
      remaining = 0;
      updateBadge(`Volgende update: ${remaining}s`);
      if (!inProgress) {
        inProgress = true;
        try { await onFire(); } catch(e) {} finally { inProgress = false; }
      }
      remaining = REFRESH_INTERVAL_SECONDS;
      updateBadge(`Volgende update: ${remaining}s`);
    }, REFRESH_INTERVAL_SECONDS * 1000);
  }

  async function evaluateAndRun(load){
    const year = currentYear;
    if (!year) return;
    const lastUpdate = await fetchLastUpdate(year);
    if (allGemeentesComplete(lastUpdate)) { updateBadge("Alle kiesregio's compleet"); setSoundVisible(false); clearTimers(); return; }
    if (await isFinalizedYear(year)) { updateBadge("Alle kiesregio's compleet"); setSoundVisible(false); clearTimers(); return; }
    // not complete -> start/restart countdown
    setSoundVisible(true);
    startCountdown(() => load(year));
  }

  function setupVisibility(load){
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) return; // pause; timers keep decrementing via code but we gate fire
      // when becoming visible, refresh countdown display
      updateBadge(`Volgende update: ${remaining}s`);
    });
  }

  function setupYearChange(load){
    const sel = document.getElementById('yearSelect');
    if (!sel) return;
    sel.addEventListener('change', async () => {
      currentYear = sel.value || getYear();
      resetUI();
      await evaluateAndRun(load);
    });
  }

  async function init(opts){
    const load = typeof opts.load === 'function' ? opts.load : function(){};
    currentYear = getYear();
    // ensure no stale UI from previous page/year
    resetUI();
    setupVisibility(load);
    setupYearChange(load);
    await evaluateAndRun(load);
  }

  window.AutoRefresh = { init };
})();
