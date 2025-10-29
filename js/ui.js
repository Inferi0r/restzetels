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

  window.UI = { createFractionHTML };
})();
