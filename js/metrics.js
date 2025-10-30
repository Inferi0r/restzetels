(function(){
  try {
    var host = String(location.hostname || '').toLowerCase();
    var isHTTPS = location.protocol === 'https:';
    var PROD_HOSTS = ['wiekrijgtderestzetel.nl', 'www.wiekrijgtderestzetel.nl'];
    var allow = isHTTPS && PROD_HOSTS.indexOf(host) !== -1;
    if (!allow) return; // do not load 3rd-party scripts on local/dev

    // Google Analytics (gtag)
    window.dataLayer = window.dataLayer || [];
    function gtag(){ dataLayer.push(arguments); }
    window.gtag = gtag;
    gtag('js', new Date());
    gtag('config', 'G-RTCSP63MWM');
    var ga = document.createElement('script');
    ga.async = true; ga.src = 'https://www.googletagmanager.com/gtag/js?id=G-RTCSP63MWM';
    document.head.appendChild(ga);

    // Google AdSense
    var ads = document.createElement('script');
    ads.async = true;
    ads.src = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-9473143074028298';
    ads.crossOrigin = 'anonymous';
    document.head.appendChild(ads);
  } catch(e) {
    // fail silent in dev
  }
})();

