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

  // Continued fraction approximation with bounded denominator
  function decimalToFraction(x, maxDenominator = 1000){
    if (!isFinite(x)) return '0/1';
    const sign = x < 0 ? -1 : 1;
    x = Math.abs(x);
    if (Math.floor(x) === x) return `${sign * Math.floor(x)}/1`;

    let h1 = 1, h0 = 0, k1 = 0, k0 = 1;
    let b = x;
    let a = Math.floor(b);
    let n = a, d = 1;

    for (let i = 0; i < 32; i++) {
      const h2 = a * h1 + h0;
      const k2 = a * k1 + k0;
      if (k2 > maxDenominator) break;
      h0 = h1; k0 = k1; h1 = h2; k1 = k2;
      n = h1; d = k1;
      const frac = h1 / k1;
      if (Math.abs(frac - x) < 1e-10) break;
      const diff = b - a;
      if (diff === 0) break;
      b = 1 / diff;
      if (!isFinite(b)) break;
      a = Math.floor(b);
    }
    n = Math.round(n * sign);
    d = Math.round(d);
    return `${n}/${d}`;
  }

  function formatNL(value){
    if (value == null) return '';
    if (typeof value === 'string') return value;
    const n = Number(value);
    if (!isFinite(n)) return '';
    return n.toLocaleString('nl-NL');
  }

  window.UI = { createFractionHTML, decimalToFraction, formatNL };
})();

