// Service Worker: cache static assets and API bundle with stale-while-revalidate
// Bump CACHE_VERSION to invalidate old caches on deploys
const CACHE_VERSION = 'v2025-11-01-00';
const STATIC_CACHE = `static-${CACHE_VERSION}`;
const DATA_CACHE = `data-${CACHE_VERSION}`;
const API_CACHE = `api-${CACHE_VERSION}`;

// Minimal pre-cache of critical assets; others are cached on demand
const PRECACHE_URLS = [
  './',
  './index.html',
  './stemcijfers.html',
  './anpupdates.html',
  './nosupdates.html',
  './anpstemmen.html',
  './styles.css',
  './favicon.ico',
  // JS
  './js/config.js',
  './js/year-nav.js',
  './js/data.js',
  './js/ui.js',
  './js/auto_refresh.js',
  './js/app.js',
  './js/stemcijfers.js',
  './js/metrics.js',
  './js/anpupdates.js',
  './js/nosupdates.js',
  './js/anpstemmen.js',
  './js/sound.js',
  // Static datasets
  './data/partylabels.json',
  './data/votes_kiesraad.json',
  './data/TK2021/anp_votes.json',
  './data/TK2021/anp_last_update.json',
  './data/TK2021/nos_index.json',
  './data/TK2023/anp_votes.json',
  './data/TK2023/anp_last_update.json',
  './data/TK2023/nos_index.json',
  './data/TK2025/anp_votes.json',
  './data/TK2025/anp_last_update.json',
  './data/TK2025/nos_index.json'
];

self.addEventListener('install', event => {
  // Do not skipWaiting immediately — activation will be triggered
  // by the page after a short, user-friendly delay.
  event.waitUntil((async () => {
    try {
      const cache = await caches.open(STATIC_CACHE);
      // Bypass the HTTP cache when precaching to ensure fresh assets on version bump
      const requests = PRECACHE_URLS.map((url) => new Request(url, { cache: 'reload' }));
      const responses = await Promise.all(requests.map((req) => fetch(req)));
      await Promise.all(responses.map((res, i) => cache.put(requests[i], res.clone())));
    } catch(e) {
      // best effort
    }
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(
      keys.filter(k => ![STATIC_CACHE, DATA_CACHE, API_CACHE].includes(k))
          .map(k => caches.delete(k))
    );
    await self.clients.claim();
  })());
});

// Allow the page to request activation when convenient (deferred takeover)
self.addEventListener('message', (event) => {
  const msg = event && event.data;
  if (msg && (msg === 'SKIP_WAITING' || (msg.type && msg.type === 'SKIP_WAITING'))) {
    try { self.skipWaiting(); } catch(e) {}
  }
});

function isSameOrigin(url) {
  try { const u = new URL(url); return u.origin === self.location.origin; } catch(e){ return false; }
}

function isStaticAsset(url){
  return isSameOrigin(url) && (
    url.endsWith('.css') || url.endsWith('.js') || url.endsWith('.ico') ||
    url.endsWith('.png') || url.endsWith('.jpg') || url.endsWith('.svg') ||
    url.endsWith('index.html') || url.endsWith('.html') ||
    url.endsWith('data/partylabels.json') || url.endsWith('data/votes_kiesraad.json')
  );
}

function isFinalizedData(url){
  return isSameOrigin(url) && /\/data\/\d{4}\/[^?]+\.json$/.test(url);
}

function isFunctionAPI(url){
  // Match our serverless getdata endpoint (domain-agnostic). Adjust if your path changes.
  return /\/default\/getdata(\?|$)/.test(url);
}

self.addEventListener('fetch', event => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = req.url;

  // Static assets: Cache First
  if (isStaticAsset(url)) {
    event.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const res = await fetch(new Request(req, { cache: 'reload' }));
        const cache = await caches.open(STATIC_CACHE);
        cache.put(req, res.clone());
        return res;
      } catch(e) {
        return cached || Response.error();
      }
    })());
    return;
  }

  // Finalized data: Cache First (effectively immutable)
  if (isFinalizedData(url)) {
    event.respondWith((async () => {
      const cached = await caches.match(req);
      if (cached) return cached;
      try {
        const res = await fetch(new Request(req, { cache: 'reload' }));
        const cache = await caches.open(DATA_CACHE);
        cache.put(req, res.clone());
        return res;
      } catch(e) {
        return cached || Response.error();
      }
    })());
    return;
  }

  // Function API (live data): Stale-While-Revalidate with graceful network failure handling
  if (isFunctionAPI(url)) {
    event.respondWith((async () => {
      const cache = await caches.open(API_CACHE);
      const cached = await cache.match(req);
      try {
        const res = await fetch(req);
        try { cache.put(req, res.clone()); } catch(e) {}
        return cached || res; // serve cached immediately if present
      } catch (e) {
        // Network/CORS failed — serve cached if available, otherwise synthesize a JSON error to avoid uncaught rejections
        if (cached) return cached;
        return new Response(JSON.stringify({ error: 'network', message: 'Failed to fetch live data' }), { status: 502, headers: { 'Content-Type': 'application/json' } });
      }
    })());
    return;
  }
});
