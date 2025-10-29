(function(){
  // Single source of truth for serverless endpoint
  // If you need to override at runtime, set window.RESTZETELS_DO_BASE before this file loads.
  var DEFAULT = 'https://faas-ams3-2a2df116.doserverless.co/api/v1/web/fn-99532869-f9f1-44c3-ba3b-9af9d74b05e5/default/getdata';
  var DO_BASE = (window.RESTZETELS_DO_BASE || DEFAULT);
  window.CONFIG = window.CONFIG || {};
  window.CONFIG.DO_BASE = DO_BASE;
  // Register Service Worker (scoped to current directory)
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function(){
      try { navigator.serviceWorker.register('sw.js', { scope: './' }); } catch(e) {}
    });
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
