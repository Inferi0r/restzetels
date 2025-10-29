(function(){
  const DO_BASE = (window.CONFIG && CONFIG.DO_BASE);
  let channel;
  try { channel = new BroadcastChannel('restzetels-bundle'); } catch(e) { channel = null; }

  const cache = new Map(); // year -> { ts, data, promise }
  const TTL_MS = 10 * 1000;

  function now(){ return Date.now(); }
  function isFresh(ts){ return (now() - (ts||0)) < TTL_MS; }

  // URL-level cache to soften errors and respect 304s
  const urlCache = new Map(); // url -> last JSON
  async function safeFetchJSON(url){
    try{
      const r = await fetch(url, { cache: 'no-store' });
      if (r.status === 304) {
        return urlCache.get(url) || null;
      }
      if (!r.ok) throw new Error(r.status);
      const j = await r.json();
      urlCache.set(url, j);
      return j;
    } catch(e){
      return urlCache.get(url) || null;
    }
  }

  // Finalized-year check centralization
  let __kiesraadIndex = null;
  async function isFinalizedYear(year){
    const y = String(year);
    if (!__kiesraadIndex) __kiesraadIndex = await safeFetchJSON('votes_kiesraad.json');
    if (!__kiesraadIndex) return false;
    const entry = Array.isArray(__kiesraadIndex) ? __kiesraadIndex : __kiesraadIndex[y];
    return Array.isArray(entry) && entry.length > 0;
  }

  // Party labels loader returning all common maps
  async function fetchPartyLabels(year){
    const y = String(year);
    const data = await safeFetchJSON('partylabels.json');
    const list = Array.isArray(data) ? data : (data && data[y]) || [];
    const keyToLabelShort = new Map();
    const keyToLabelLong = new Map();
    const keyToNOS = new Map();
    const keyToListNumber = new Map();
    list.forEach((p, idx) => {
      keyToLabelShort.set(p.key, p.labelShort || p.labelLong || '');
      keyToLabelLong.set(p.key, p.labelLong || p.labelShort || '');
      if (p.labelShortNOS) keyToNOS.set(p.key, p.labelShortNOS);
      keyToListNumber.set(p.key, idx + 1);
    });
    return { list, keyToLabelShort, keyToLabelLong, keyToNOS, keyToListNumber };
  }

  // Discover available years (from partylabels.json keys; fallback to known years)
  async function discoverYears(){
    try {
      const data = await safeFetchJSON('partylabels.json');
      if (Array.isArray(data)) return ['2021','2023','2025'];
      const years = Object.keys(data||{}).filter(k=>/^\d{4}$/.test(k));
      if (years.length) return years.sort((a,b)=>parseInt(a,10)-parseInt(b,10));
    } catch(e) {}
    return ['2021','2023','2025'];
  }

  async function fetchLocalBundle(year){
    const y = String(year);
    const [anp_votes, anp_last_update, nos_index] = await Promise.all([
      safeFetchJSON(`data/${y}/anp_votes.json`),
      safeFetchJSON(`data/${y}/anp_last_update.json`),
      safeFetchJSON(`data/${y}/nos_index.json`)
    ]);
    return { year: Number(y), anp_votes, anp_last_update, nos_index };
  }

  async function fetchRemoteBundle(year){
    const y = String(year);
    // Try bundled endpoint first
    let data = await safeFetchJSON(`${DO_BASE}?year=${encodeURIComponent(y)}&source=all`);
    // Fallback to individual endpoints if bundle unsupported on server
    if (!data || data.error) {
      const [anp_votes, anp_last_update, nos_index] = await Promise.all([
        safeFetchJSON(`${DO_BASE}?year=${encodeURIComponent(y)}&source=anp_votes`),
        safeFetchJSON(`${DO_BASE}?year=${encodeURIComponent(y)}&source=anp_last_update`),
        safeFetchJSON(`${DO_BASE}?year=${encodeURIComponent(y)}&source=nos_index`)
      ]);
      data = { year: Number(y), anp_votes, anp_last_update, nos_index };
    }
    return data || { year: Number(y), anp_votes: null, anp_last_update: null, nos_index: null };
  }

  async function fetchBundle(year){
    const y = String(year);
    const entry = cache.get(y);
    if (entry && entry.data && isFresh(entry.ts)) return entry.data;
    if (entry && entry.promise) return entry.promise;
    const p = (async () => {
      const finalized = await isFinalizedYear(y);
      const bundle = finalized ? await fetchLocalBundle(y) : await fetchRemoteBundle(y);
      cache.set(y, { ts: now(), data: bundle, promise: null });
      if (channel) { try{ channel.postMessage({ type:'bundle', year: y, ts: now(), data: bundle }); } catch(e){} }
      return bundle;
    })();
    cache.set(y, { ts: entry?.ts || 0, data: entry?.data || null, promise: p });
    return p;
  }

  if (channel) {
    channel.onmessage = (ev) => {
      const msg = ev.data || ev;
      if (!msg || msg.type !== 'bundle' || !msg.year) return;
      cache.set(String(msg.year), { ts: msg.ts || now(), data: msg.data, promise: null });
    };
  }

  window.Data = {
    fetchBundle,
    safeJSON: safeFetchJSON,
    isFinalizedYear,
    fetchPartyLabels,
    discoverYears
  };
})();
