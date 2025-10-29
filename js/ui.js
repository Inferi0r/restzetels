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

  window.UI = { createFractionHTML, fitTableScaleToWidth, registerScaleTarget };
})();
