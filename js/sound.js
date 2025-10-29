(function(){
  const STORAGE_KEY = 'soundEnabled';
  let enabled = false;
  let ctx = null;
  let unlocked = false;

  function ensureContext(){
    if (!ctx) {
      try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch(e) { ctx = null; }
    }
    return ctx;
  }

  async function resumeContext(){
    const audio = ensureContext();
    if (!audio) return false;
    try {
      if (audio.state === 'suspended') { await audio.resume(); }
      return true;
    } catch(e){ return false; }
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
    if (enabled) {
      ensureContext();
      // Attempt to resume immediately on user gesture
      resumeContext().then(() => {
        // Provide a short confirmation beep
        try { playBeep({ freq: 880, duration: 0.06, volume: 0.15 }); } catch(e){}
      });
    }
  }

  function init(){
    const saved = window.localStorage.getItem(STORAGE_KEY);
    enabled = saved === '1';
    updateButton();
    const btn = document.getElementById('soundToggle');
    if (btn){
      btn.addEventListener('click', async ()=> {
        setEnabled(!enabled);
        await resumeContext();
      });
    }
    const promptBtn = document.getElementById('soundPrompt');
    if (promptBtn){
      promptBtn.style.display = enabled ? 'none' : 'inline-flex';
      promptBtn.addEventListener('click', async ()=> {
        setEnabled(true);
        await resumeContext();
        promptBtn.style.display = 'none';
      });
    }
    // iOS/Safari unlock: resume context on first pointer/keyboard interaction
    const unlock = async () => {
      if (unlocked) return; unlocked = true;
      await resumeContext();
      window.removeEventListener('pointerdown', unlock, true);
      window.removeEventListener('keydown', unlock, true);
    };
    window.addEventListener('pointerdown', unlock, true);
    window.addEventListener('keydown', unlock, true);
  }

  function isEnabled(){ return enabled; }

  function playBeep({ freq=440, duration=0.3, volume=0.22, type='sine' }={}){
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
    // 50% longer than previous (0.22s -> ~0.33s)
    playBeep({ freq: 660, duration: 0.33, volume: 0.22, type: 'sine' });
  }

  function playSeatChange(){
    // punchier two-beep sequence
    if (!enabled || document.hidden) return;
    const audio = ensureContext();
    if (!audio) return;
    const doBeep = (t, freq, dur=0.36, vol=0.28) => {
      const osc = audio.createOscillator();
      const gain = audio.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(freq, t);
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(vol, t + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      osc.connect(gain).connect(audio.destination);
      osc.start(t);
      osc.stop(t + dur + 0.02);
    };
    const now = audio.currentTime;
    doBeep(now, 550, 0.36, 0.28);
    // Start the second tone after the first finishes (gap ~20ms)
    doBeep(now + 0.38, 880, 0.39, 0.30);
  }

  window.Sound = { init, isEnabled, setEnabled, playNewVotes, playSeatChange };
})();
