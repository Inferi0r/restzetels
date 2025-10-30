// Auto-refresh controller shared across pages
// Configurable interval at the top.
const REFRESH_INTERVAL_SECONDS = 30; // changed from 10s to 30s

(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);

  let secondTickId = null;      // updates badge display once per second
  let fireTimeoutId = null;     // drives the actual refresh call
  let remaining = REFRESH_INTERVAL_SECONDS;
  let nextFireAt = 0;           // timestamp (ms) when the next refresh should fire
  let currentYear = null;
  let inProgress = false;
  let finalizedActive = false; // guard to prevent countdown UI in finalized years
  let countdownActive = false; // additional guard for mobile Safari visibility glitches
  let lastDisplayedRemaining = REFRESH_INTERVAL_SECONDS;
  let lastResetAt = 0;
  const DISPLAY_CLAMP_MS = 1500; // don't allow countdown to increase after this grace window

  let titleBaseText = 'Zetels - realtime ANP';

  function onZetelsPage(){ return !!document.getElementById('latestRestSeatImpactContainer'); }
  function setStaticTitle(){ document.title = titleBaseText; }
  // Title is always static now

  function getYear(){
    const params = new URLSearchParams(window.location.search);
    return params.get('year') || window.localStorage.getItem('selectedYear') || '2025';
  }

  async function loadJSON(url){
    try { const r = await fetch(url, { cache: 'no-store' }); if (!r.ok) throw new Error(r.status); return await r.json(); } catch(e){ return null; }
  }

  // Use shared finalized-year logic
  async function isFinalizedYear(year){
    return Data.isFinalizedYear(year);
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
    if (secondTickId) { clearInterval(secondTickId); secondTickId = null; }
    if (fireTimeoutId) { clearTimeout(fireTimeoutId); fireTimeoutId = null; }
    nextFireAt = 0;
    countdownActive = false;
  }

  function resetUI(){
    clearTimers();
    updateBadge('');
    setSoundVisible(false);
    setStaticTitle();
  }

  function startCountdown(onFire){
    clearTimers();
    if (finalizedActive) {
      // safety: never start countdown while finalized flag is set
      updateBadge("Alle kiesregio's compleet");
      setSoundVisible(false);
      return;
    }
    nextFireAt = Date.now() + (REFRESH_INTERVAL_SECONDS * 1000);
    countdownActive = true;
    lastResetAt = Date.now();
    lastDisplayedRemaining = REFRESH_INTERVAL_SECONDS;
    const computeRemaining = () => {
      const ms = Math.max(0, nextFireAt - Date.now());
      // ceil so we don't display 0s while time remains
      remaining = Math.ceil(ms / 1000);
    };
    computeRemaining();
    const updateCountdownDisplay = () => {
      // Monotonic countdown display: never increase unless just after a reset
      let show = remaining;
      if (show > lastDisplayedRemaining && (Date.now() - lastResetAt) > DISPLAY_CLAMP_MS) {
        show = lastDisplayedRemaining;
      } else {
        lastDisplayedRemaining = show;
      }
      updateBadge(`Volgende update: ${show}s`);
    };
    updateCountdownDisplay();

    // Second display tick — uses nextFireAt so it remains correct even if tab was hidden
    secondTickId = setInterval(() => {
      if (finalizedActive) { clearTimers(); updateBadge("Alle kiesregio's compleet"); setSoundVisible(false); return; }
      computeRemaining();
      updateCountdownDisplay();
    }, 1000);

    // Schedule the refresh using a timeout; reschedules itself
    const scheduleFire = () => {
      if (finalizedActive) { clearTimers(); updateBadge("Alle kiesregio's compleet"); setSoundVisible(false); return; }
      const delay = Math.max(0, nextFireAt - Date.now());
      fireTimeoutId = setTimeout(async () => {
        if (finalizedActive) { clearTimers(); updateBadge("Alle kiesregio's compleet"); setSoundVisible(false); return; }
        remaining = 0;
        updateCountdownDisplay();
        if (!inProgress) {
          inProgress = true;
          try { await onFire(); } catch(e) {} finally { inProgress = false; }
        }
        nextFireAt = Date.now() + (REFRESH_INTERVAL_SECONDS * 1000);
        lastResetAt = Date.now();
        lastDisplayedRemaining = REFRESH_INTERVAL_SECONDS;
        computeRemaining();
        updateCountdownDisplay();
        scheduleFire();
      }, delay);
    };
    scheduleFire();
  }

  async function evaluateAndRun(load){
    const year = currentYear;
    if (!year) return;
    const lastUpdate = await fetchLastUpdate(year);
    // Update title info with latest updated Gemeente (type 0)
    if (onZetelsPage()) { setStaticTitle(); }
    if (allGemeentesComplete(lastUpdate)) { finalizedActive = true; updateBadge("Alle kiesregio's compleet"); setSoundVisible(false); setStaticTitle(); clearTimers(); return; }
    if (await isFinalizedYear(year)) { finalizedActive = true; updateBadge("Alle kiesregio's compleet"); setSoundVisible(false); setStaticTitle(); clearTimers(); return; }
    // not complete -> start/restart countdown
    finalizedActive = false;
    setSoundVisible(true);
    startCountdown(() => load(year));
  }

  function setupVisibility(load){
    document.addEventListener('visibilitychange', async () => {
      if (document.hidden) return;
      // If finalized, ensure completed badge is shown
      if (finalizedActive) { updateBadge("Alle kiesregio's compleet"); setSoundVisible(false); return; }
      // If a countdown is active, refresh the displayed remaining without resetting schedule
      if (fireTimeoutId || countdownActive) {
        const ms = nextFireAt ? Math.max(0, nextFireAt - Date.now()) : 0;
        remaining = Math.ceil(ms / 1000);
        // Clamp display so it doesn't bounce upward after visibility changes
        let show = remaining;
        if (show > lastDisplayedRemaining && (Date.now() - lastResetAt) > DISPLAY_CLAMP_MS) {
          show = lastDisplayedRemaining;
        } else {
          lastDisplayedRemaining = show;
        }
        updateBadge(`Volgende update: ${show}s`);
        return;
      }
      // Otherwise evaluate (e.g., first load or after year change)
      await evaluateAndRun(load);
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
    // Keep static title on Zetels page
    if (onZetelsPage()) setStaticTitle();
    setupVisibility(load);
    setupYearChange(load);
    await evaluateAndRun(load);
  }

  window.AutoRefresh = { init };
})();
