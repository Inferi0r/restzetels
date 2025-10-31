(function(){
  function createFractionHTML(numerator, denominator){
    if (!numerator || !denominator) return '';
    return (
      '<div style="display:inline-block;text-align:center;font-size:smaller;">' +
      `<span style="display:block;border-bottom:1px solid;padding-bottom:2px;">${numerator}</span>` +
      `<span style="display:block;padding-top:2px;">${denominator}</span>` +
      '</div>'
    );
  }

  // Fit a wide table inside its container by scaling down (no horizontal scroll).
  // - Scales only when table is wider than container.
  // - Preserves layout; users can zoom if they want to read details.
  function fitTableScaleToWidth(containerId){
    const container = document.getElementById(containerId);
    if (!container) return;
    const table = container.querySelector('table');
    if (!table) { container.style.height=''; return; }
    // Reset
    table.style.transform = '';
    table.style.transformOrigin = '';
    container.style.height = '';
    container.style.overflow = '';
    container.style.textAlign = '';
    // Measure
    const contW = container.clientWidth || 0;
    const tableW = table.scrollWidth || 0;
    if (!contW || !tableW) return;
    if (tableW <= contW) return; // no scaling needed
    const scale = contW / tableW;
    const unscaledH = table.offsetHeight || 0;
    // Center the scaled table
    container.style.textAlign = 'center';
    table.style.display = 'inline-block';
    table.style.transformOrigin = 'top center';
    table.style.transform = `scale(${scale})`;
    if (unscaledH) container.style.height = `${Math.ceil(unscaledH * scale)}px`;
    container.style.overflow = 'hidden';
  }

  // Debounced global resizer for registered containers
  const _scaleTargets = new Set();
  let _resizeTimer = 0;
  function _recalcAll(){
    _scaleTargets.forEach(id => fitTableScaleToWidth(id));
  }
  function _queueRecalc(){
    if (_resizeTimer) cancelAnimationFrame(_resizeTimer);
    _resizeTimer = requestAnimationFrame(_recalcAll);
  }
  if (typeof window !== 'undefined') {
    window.addEventListener('resize', _queueRecalc, { passive: true });
    window.addEventListener('orientationchange', _queueRecalc, { passive: true });
  }
  function registerScaleTarget(containerId){
    _scaleTargets.add(containerId);
    // Recalc soon after DOM update
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(()=>fitTableScaleToWidth(containerId));
    else setTimeout(()=>fitTableScaleToWidth(containerId), 0);
  }

  // Keep a block's width in sync with a table inside a container using observers
  function initBlockWidthSync(blockId, tableContainerId){
    const block = document.getElementById(blockId);
    const cont = document.getElementById(tableContainerId);
    if (!block || !cont) return;
    let table = null;
    let resizeObs = null;
    let rafId = 0;
    const sync = () => {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        try {
          const t = cont.querySelector('table');
          if (!t) { return; }
          const w = t.getBoundingClientRect().width;
          if (w && isFinite(w)) {
            block.style.width = Math.round(w) + 'px';
          }
        } catch(e){}
      });
    };
    const attachResize = () => {
      const t = cont.querySelector('table');
      if (!t) return;
      if (table === t) return; // already observing
      table = t;
      if (resizeObs) { try { resizeObs.disconnect(); } catch(e){} resizeObs = null; }
      try {
        resizeObs = new ResizeObserver(sync);
        resizeObs.observe(table);
      } catch(e){}
      sync();
    };
    // Observe whenever the table is inserted/updated
    try {
      const mo = new MutationObserver(attachResize);
      mo.observe(cont, { childList: true, subtree: true });
    } catch(e){}
    // Also react to window resizes
    window.addEventListener('resize', sync, { passive: true });
    // Try now
    attachResize();
  }

  window.UI = { createFractionHTML, fitTableScaleToWidth, registerScaleTarget, initBlockWidthSync };
})();
