(function(){
  // Single source of truth for serverless endpoint
  // If you need to override at runtime, set window.RESTZETELS_DO_BASE before this file loads.
  var DEFAULT = 'https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata';
  var DO_BASE = (window.RESTZETELS_DO_BASE || DEFAULT);
  window.CONFIG = window.CONFIG || {};
  window.CONFIG.DO_BASE = DO_BASE;

  // Optional data source mode: 'auto' (default), 'remote', or 'local'.
  // Can be set via query param ?data=remote|local|auto or by setting window.CONFIG.DATA_MODE before this file loads.
  try {
    if (!window.CONFIG.DATA_MODE) {
      var qs = new URLSearchParams(location.search || '');
      var dm = (qs.get('data') || qs.get('mode') || '').toLowerCase();
      if (dm === 'remote' || dm === 'local' || dm === 'auto') {
        window.CONFIG.DATA_MODE = dm;
      } else {
        window.CONFIG.DATA_MODE = 'auto';
      }
    }
  } catch(e) { window.CONFIG.DATA_MODE = window.CONFIG.DATA_MODE || 'auto'; }

  var isLocalHost = /^(127\.0\.0\.1|localhost)$/.test(location.hostname);
  // Register Service Worker (scoped to current directory) only outside local dev
  if ('serviceWorker' in navigator && !isLocalHost) {
    // Register and defer activation so the first page load doesn't reset immediately
    (async () => {
      try {
        const reg = await navigator.serviceWorker.register('sw.js', { scope: './' });
        const DEFER_MS = 12000; // align roughly with first auto-refresh tick (10s) + slack

        const scheduleActivate = (registration) => {
          try {
            const doSkip = () => {
              if (registration && registration.waiting) {
                try { registration.waiting.postMessage({ type: 'SKIP_WAITING' }); } catch(e) {}
              }
            };
            setTimeout(doSkip, DEFER_MS);
          } catch(e) {}
        };

        // If there's already a waiting worker (first load or update found before page ready), schedule activation
        if (reg.waiting) scheduleActivate(reg);
        // For future updates
        reg.addEventListener('updatefound', () => {
          const sw = reg.installing;
          if (!sw) return;
          sw.addEventListener('statechange', () => {
            if (sw.state === 'installed' && reg.waiting) scheduleActivate(reg);
          });
        });
      } catch(e) {}
    })();

    // Auto-reload once when the new SW finally takes control (deferred)
    let reloaded = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (reloaded) return; reloaded = true;
      setTimeout(() => { try { window.location.reload(); } catch(e) {} }, 50);
    });
  } else if ('serviceWorker' in navigator && isLocalHost) {
    // In local dev, ensure any previously registered SW is removed to avoid stale caches
    try {
      navigator.serviceWorker.getRegistrations().then(function(regs){ regs.forEach(function(r){ try{ r.unregister(); }catch(e){} }); });
      if (window.caches && typeof caches.keys === 'function') {
        caches.keys().then(function(keys){ keys.forEach(function(k){ if (/^(static-|data-|api-)/.test(k)) { try{ caches.delete(k); }catch(e){} } }); });
      }
    } catch(e) {}
  }
  // Inject preconnect for performance based on the origin
  try {
    var origin = new URL(DO_BASE).origin;
    var head = document.head || document.getElementsByTagName('head')[0];
    if (head) {
      var exists = Array.prototype.some.call(
        head.querySelectorAll('link[rel="preconnect"]'),
        function(l){ return l && l.href && (l.href === origin || l.href === origin + '/'); }
      );
      if (!exists) {
        var link = document.createElement('link');
        link.rel = 'preconnect';
        link.href = origin;
        head.appendChild(link);
      }
    }
  } catch(e) {}
})();
