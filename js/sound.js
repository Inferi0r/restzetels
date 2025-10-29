(function(){
  const STORAGE_KEY = 'soundEnabled';
  let enabled = false;
  let ctx = null;

  function ensureContext(){
    if (!ctx) {
      try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch(e) { ctx = null; }
    }
    return ctx;
  }

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
    if (enabled) ensureContext();
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

  function playBeep({ freq=440, duration=0.12, volume=0.2, type='sine' }={}){
    if (!enabled || document.hidden) return;
    const audio = ensureContext();
    if (!audio) return;
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, audio.currentTime);
    gain.gain.setValueAtTime(0, audio.currentTime);
    gain.gain.linearRampToValueAtTime(volume, audio.currentTime + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + duration);
    osc.connect(gain).connect(audio.destination);
    osc.start();
    osc.stop(audio.currentTime + duration + 0.02);
  }

  function playNewVotes(){
    // short, softer beep
    playBeep({ freq: 660, duration: 0.10, volume: 0.15, type: 'sine' });
  }

  function playSeatChange(){
    // punchier two-beep sequence
    if (!enabled || document.hidden) return;
    const audio = ensureContext();
    if (!audio) return;
    const doBeep = (t, freq) => {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq, t);
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.25, t + 0.01);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.14);
      osc.connect(gain).connect(audio.destination);
      osc.start(t);
      osc.stop(t + 0.16);
    };
    const now = audio.currentTime;
    doBeep(now, 550);
    doBeep(now + 0.18, 880);
  }

  window.Sound = { init, isEnabled, setEnabled, playNewVotes, playSeatChange };
})();
