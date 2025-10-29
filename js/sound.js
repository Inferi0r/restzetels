(function(){
  const STORAGE_KEY = 'soundEnabled';
  let enabled = false;

  function updateButton(){
    const btn = document.getElementById('soundToggle');
    if (!btn) return;
    btn.textContent = enabled ? '🔊' : '🔇';
  }

  function setEnabled(val){
    enabled = !!val;
    window.localStorage.setItem(STORAGE_KEY, enabled ? '1' : '0');
    updateButton();
    // Reflect prompt visibility whenever sound state changes
    const promptBtn = document.getElementById('soundPrompt');
    if (promptBtn){
      promptBtn.style.display = enabled ? 'none' : 'inline-flex';
    }
  }

  function init(){
    const saved = window.localStorage.getItem(STORAGE_KEY);
    enabled = saved === '1';
    updateButton();
    const btn = document.getElementById('soundToggle');
    if (btn){
      btn.addEventListener('click', ()=> setEnabled(!enabled));
    }
    const promptBtn = document.getElementById('soundPrompt');
    if (promptBtn){
      promptBtn.style.display = enabled ? 'none' : 'inline-flex';
      promptBtn.addEventListener('click', ()=> {
        setEnabled(true);
        promptBtn.style.display = 'none';
      });
    }
  }

  function isEnabled(){ return enabled; }

  window.Sound = { init, isEnabled, setEnabled };
})();
