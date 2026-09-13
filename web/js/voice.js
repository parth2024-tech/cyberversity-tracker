// ══════════════════════════════════════════════════════════════════════════
// VOICE RADAR: UNIVERSAL NEURAL AI BROADCAST ENGINE (ZERO OS DEPENDENCY)
// Client-side neural TTS streaming, Web Speech API fallback, and Audio HUD
// ══════════════════════════════════════════════════════════════════════════

var VoiceRadar = {
  speaking: false,
  paused: false,
  rate: 1.0,
  selectedVoice: 'en-US-GuyNeural',
  playlist: [],
  currentIndex: 0,
  _audio: null,
  _activeCardId: null,
  _currentOnEnd: null,
  _voices: [],

  init() {
    if (!this._audio && typeof Audio !== 'undefined') {
      this._audio = new Audio();
      this._audio.addEventListener('ended', () => {
        this._setVisualizer(false);
        if (this._currentOnEnd) {
          const cb = this._currentOnEnd;
          this._currentOnEnd = null;
          cb();
        }
      });
      this._audio.addEventListener('error', (e) => {
        console.warn("Neural audio streaming error, attempting fallback...", e);
        this._setVisualizer(false);
        if (this._currentOnEnd) {
          const cb = this._currentOnEnd;
          this._currentOnEnd = null;
          cb();
        }
      });
      this._audio.addEventListener('play', () => {
        this._setVisualizer(true);
      });
      this._audio.addEventListener('pause', () => {
        this._setVisualizer(false);
      });
    }

    this.loadVoices();
  },

  async loadVoices() {
    const voiceSelect = document.getElementById('hud-voice-select');
    const fallbackVoices = [
      { id: 'en-US-GuyNeural', name: 'Guy (US Anchor)' },
      { id: 'en-US-ChristopherNeural', name: 'Christopher (US Executive)' },
      { id: 'en-US-AriaNeural', name: 'Aria (US Intel)' },
      { id: 'en-US-JennyNeural', name: 'Jenny (US Natural)' },
      { id: 'en-GB-SoniaNeural', name: 'Sonia (UK News)' },
      { id: 'en-IN-PrabhatNeural', name: 'Prabhat (IN Clear)' }
    ];

    try {
      const res = await fetch('/api/audio/voices');
      if (res.ok) {
        const data = await res.json();
        this._voices = data.voices || fallbackVoices;
      } else {
        this._voices = fallbackVoices;
      }
    } catch (e) {
      this._voices = fallbackVoices;
    }

    if (voiceSelect) {
      voiceSelect.innerHTML = '';
      this._voices.forEach(v => {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = v.name;
        if (v.id === this.selectedVoice) opt.selected = true;
        voiceSelect.appendChild(opt);
      });
    }
  },

  setVoice(voiceId) {
    this.selectedVoice = voiceId || 'en-US-GuyNeural';
    if (typeof playBeep === 'function') playBeep('click');
  },

  cycleSpeed() {
    const rates = [1.0, 1.25, 1.5];
    const curIdx = rates.indexOf(this.rate);
    this.rate = rates[(curIdx + 1) % rates.length];
    const btn = document.getElementById('hud-speed-btn');
    if (btn) btn.textContent = this.rate.toFixed(1) + 'x';
    if (this._audio) this._audio.playbackRate = this.rate;
    if (typeof playBeep === 'function') playBeep('click');
  },

  playTacticalChirp() {
    if (typeof audioEnabled !== 'undefined' && !audioEnabled) return;
    if (typeof audioCtx === 'undefined' || !audioCtx) return;
    try {
      if (audioCtx.state === 'suspended') audioCtx.resume();
      const osc = audioCtx.createOscillator();
      const gain = audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(1200, audioCtx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(800, audioCtx.currentTime + 0.08);
      gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.08);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.08);
    } catch (e) {}
  },

  normalizeSecurityText(raw) {
    if (!raw) return '';
    return raw
      .replace(/https?:\/\/[^\s]+/g, '')
      .replace(/CVE-(\d{4})-(\d+)/gi, (m, y, id) => `CVE ${y} ${id}`)
      .replace(/\bPoC\b/g, 'Proof of Concept')
      .replace(/\bRAG\b/g, 'RAG')
      .replace(/\bLLMs\b/g, 'LLMs')
      .replace(/\bLLM\b/g, 'LLM')
      .replace(/\barXiv\b/gi, 'Archive')
      .replace(/\b0-day\b/gi, 'zero day')
      .replace(/\bzero-day\b/gi, 'zero day')
      .replace(/\bCNNVD\b/gi, 'C-N-N-V-D')
      .replace(/\bCNCERT\b/gi, 'C-N-CERT')
      .replace(/\bDeepSeek\b/gi, 'Deep-Seek')
      .replace(/\bQwen\b/gi, 'Q-wen')
      .replace(/\bZhipu\b/gi, 'Zhi-pu')
      .replace(/[*#`_~[\]]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  },

  _rateStringToPercent(rate) {
    if (rate === 1.25) return '+25%';
    if (rate === 1.5) return '+50%';
    return '+0%';
  },

  async _playSpeech(text, onComplete) {
    if (!text) {
      if (onComplete) onComplete();
      return;
    }

    this.init();
    this._currentOnEnd = onComplete;
    const rateStr = this._rateStringToPercent(this.rate);
    const voiceId = this.selectedVoice || 'en-US-GuyNeural';

    // 1. Primary Engine: Server-side Neural TTS Stream (100% OS Independent)
    if (this._audio) {
      try {
        const url = `/api/audio/tts?text=${encodeURIComponent(text.slice(0, 4000))}&voice=${encodeURIComponent(voiceId)}&rate=${encodeURIComponent(rateStr)}`;
        this._audio.src = url;
        this._audio.playbackRate = this.rate;
        await this._audio.play();
        this._setVisualizer(true);
        return;
      } catch (err) {
        console.warn("HTML5 audio playback error, trying client fallback...", err);
      }
    }

    // 2. Client Fallback: SpeechSynthesis (if browser supports and has voices)
    if ('speechSynthesis' in window && window.speechSynthesis.getVoices().length > 0) {
      try {
        window.speechSynthesis.cancel();
        const utt = new SpeechSynthesisUtterance(text);
        utt.rate = this.rate;
        utt.onstart = () => this._setVisualizer(true);
        utt.onend = () => {
          this._setVisualizer(false);
          if (onComplete) onComplete();
        };
        utt.onerror = () => {
          this._setVisualizer(false);
          if (onComplete) onComplete();
        };
        window.speechSynthesis.speak(utt);
        return;
      } catch (e) {}
    }

    // 3. Graceful completion if audio blocked by browser policy
    this._setVisualizer(false);
    if (onComplete) onComplete();
  },

  _setVisualizer(active) {
    const viz = document.getElementById('audio-visualizer');
    if (viz) {
      if (active) viz.classList.add('audio-playing');
      else viz.classList.remove('audio-playing');
    }
  },

  _highlightCard(cardId) {
    if (this._activeCardId) {
      const prev = document.getElementById('threat-card-' + this._activeCardId);
      if (prev) prev.classList.remove('card-speaking');
    }
    this._activeCardId = cardId;
    if (cardId) {
      const el = document.getElementById('threat-card-' + cardId);
      if (el) {
        el.classList.add('card-speaking');
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  },

  speak(rawText, options = {}) {
    if (!rawText) return;
    this.stop();
    this.speaking = true;
    this.paused = false;

    const hud = document.getElementById('audio-hud');
    if (hud) hud.classList.remove('hidden');
    const headline = document.getElementById('hud-headline');
    const status = document.getElementById('hud-status-text');
    const counter = document.getElementById('hud-item-counter');
    const playBtnIcon = document.getElementById('hud-play-icon');

    if (counter) counter.textContent = 'RADIO';
    if (headline) headline.textContent = options.title || "Chronicle Radio Broadcast";
    if (status) status.textContent = "EDITORIAL BROADCAST // ACTIVE";
    if (playBtnIcon) playBtnIcon.setAttribute('data-lucide', 'pause');
    if (typeof lucide !== 'undefined') lucide.createIcons();

    const normalized = this.normalizeSecurityText(rawText);
    this.playTacticalChirp();
    this._playSpeech(normalized, () => {
      this.stop();
    });
  },

  startBriefing(customItems = null) {
    let items = customItems;
    const feed = typeof allFeedItems !== 'undefined' ? allFeedItems : [];
    if (!items || items.length === 0) {
      items = [...feed].sort((a, b) => {
        const aPre = a.is_pre_cve_warning || (a.analysis && a.analysis.is_pre_cve_warning) ? 1 : 0;
        const bPre = b.is_pre_cve_warning || (b.analysis && b.analysis.is_pre_cve_warning) ? 1 : 0;
        if (bPre !== aPre) return bPre - aPre;
        const aVel = (a.analysis ? a.analysis.threat_velocity : a.threat_velocity) || 0;
        const bVel = (b.analysis ? b.analysis.threat_velocity : b.threat_velocity) || 0;
        return bVel - aVel;
      }).slice(0, 5);
    }

    if (items.length === 0) {
      if (typeof showToast === 'function') showToast("No active intelligence advisories to brief.", "alert");
      return;
    }

    this.playlist = items;
    this.currentIndex = 0;
    this.speaking = true;
    this.paused = false;

    const hud = document.getElementById('audio-hud');
    if (hud) hud.classList.remove('hidden');

    const playBtnIcon = document.getElementById('hud-play-icon');
    if (playBtnIcon) playBtnIcon.setAttribute('data-lucide', 'pause');
    if (typeof lucide !== 'undefined') lucide.createIcons();

    this.playTacticalChirp();
    this._playPlaylistItem(0, true);
  },

  _playPlaylistItem(idx, includeIntro = false) {
    if (idx < 0 || idx >= this.playlist.length) {
      this.stop();
      return;
    }

    this.currentIndex = idx;
    const item = this.playlist[idx];
    const src = item.source_name || (item.source ? item.source.name : 'Radar Intelligence');

    const counter = document.getElementById('hud-item-counter');
    const headline = document.getElementById('hud-headline');
    const status = document.getElementById('hud-status-text');

    if (counter) counter.textContent = `${idx + 1} / ${this.playlist.length}`;
    if (headline) headline.textContent = item.title;
    if (status) status.textContent = `BRIEFING // ITEM ${idx + 1}`;

    this._highlightCard(item.id);

    let script = '';
    if (includeIntro) {
      script += `AetherGuard Global AI Briefing. Analyzing top ${this.playlist.length} intelligence developments. `;
    }

    script += `Item ${idx + 1}. ${this.normalizeSecurityText(item.title)}. `;
    script += `Source, ${src}. `;

    if (item.summary) {
      script += `${this.normalizeSecurityText(item.summary.slice(0, 220))}. `;
    }

    if (idx === this.playlist.length - 1) {
      script += `End of intelligence briefing.`;
    }

    this._playSpeech(script, () => {
      if (idx + 1 < this.playlist.length) {
        setTimeout(() => {
          this.playTacticalChirp();
          this._playPlaylistItem(idx + 1, false);
        }, 500);
      } else {
        setTimeout(() => {
          this.stop();
        }, 800);
      }
    });
  },

  speakSingleEntry(entryId) {
    const feed = typeof allFeedItems !== 'undefined' ? allFeedItems : [];
    const item = feed.find(x => String(x.id) === String(entryId));
    if (!item) return;

    this.playlist = [item];
    this.currentIndex = 0;
    this.speaking = true;
    this.paused = false;

    const hud = document.getElementById('audio-hud');
    if (hud) hud.classList.remove('hidden');

    const counter = document.getElementById('hud-item-counter');
    const headline = document.getElementById('hud-headline');
    const status = document.getElementById('hud-status-text');
    const playBtnIcon = document.getElementById('hud-play-icon');

    if (counter) counter.textContent = '1 / 1';
    if (headline) headline.textContent = item.title;
    if (status) status.textContent = 'INTELLIGENCE READOUT';
    if (playBtnIcon) playBtnIcon.setAttribute('data-lucide', 'pause');
    if (typeof lucide !== 'undefined') lucide.createIcons();

    this._highlightCard(item.id);
    this.playTacticalChirp();

    const src = item.source_name || (item.source ? item.source.name : 'Radar Intelligence');

    let script = `${this.normalizeSecurityText(item.title)}. `;
    script += `Source: ${src}. `;

    if (item.summary) {
      script += `${this.normalizeSecurityText(item.summary.slice(0, 280))}. `;
    }

    this._playSpeech(script, () => {
      setTimeout(() => this.stop(), 800);
    });
  },

  togglePlayPause() {
    if (!this.speaking) {
      this.startBriefing();
      return;
    }

    const icon = document.getElementById('hud-play-icon');
    if (this._audio && this._audio.src) {
      if (this.paused) {
        this._audio.play();
        this.paused = false;
        this._setVisualizer(true);
        if (icon) icon.setAttribute('data-lucide', 'pause');
      } else {
        this._audio.pause();
        this.paused = true;
        this._setVisualizer(false);
        if (icon) icon.setAttribute('data-lucide', 'play');
      }
    } else if ('speechSynthesis' in window) {
      if (this.paused) {
        window.speechSynthesis.resume();
        this.paused = false;
        this._setVisualizer(true);
        if (icon) icon.setAttribute('data-lucide', 'pause');
      } else {
        window.speechSynthesis.pause();
        this.paused = true;
        this._setVisualizer(false);
        if (icon) icon.setAttribute('data-lucide', 'play');
      }
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
    if (typeof playBeep === 'function') playBeep('click');
  },

  next() {
    if (this.currentIndex + 1 < this.playlist.length) {
      if (typeof playBeep === 'function') playBeep('click');
      this.playTacticalChirp();
      this._playPlaylistItem(this.currentIndex + 1, false);
    } else {
      this.stop();
    }
  },

  prev() {
    if (this.currentIndex > 0) {
      if (typeof playBeep === 'function') playBeep('click');
      this.playTacticalChirp();
      this._playPlaylistItem(this.currentIndex - 1, false);
    }
  },

  stop() {
    this.speaking = false;
    this.paused = false;
    if (this._audio) {
      this._audio.pause();
      this._audio.currentTime = 0;
    }
    if ('speechSynthesis' in window) {
      try { window.speechSynthesis.cancel(); } catch (e) {}
    }
    this._setVisualizer(false);
    this._highlightCard(null);

    const hud = document.getElementById('audio-hud');
    if (hud) hud.classList.add('hidden');
    if (typeof playBeep === 'function') playBeep('click');
  }
};

window.VoiceRadar = VoiceRadar;
