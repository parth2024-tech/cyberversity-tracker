// ══════════════════════════════════════════════════════════════════════════
// FEATURE 1: SPOTLIGHT COMMAND PALETTE (Cmd+K / Ctrl+K) & GLOBAL SHORTCUTS
// Fast navigation, fuzzy search, and tactical hotkeys
// ══════════════════════════════════════════════════════════════════════════

var paletteSelectedIndex = 0;
var paletteItems = [];

const DEFAULT_PALETTE_ACTIONS = [
  { id: 'action-translate-all', title: 'Translate All Foreign Intelligence to English', subtitle: 'Auto-detect & translate Chinese, Russian, Japanese & EU feeds', icon: 'languages', badge: 'TRANSLATE', type: 'action', run: () => typeof backfillAllTranslations === 'function' ? backfillAllTranslations() : null },
  { id: 'action-theatre-china', title: 'Switch Theatre to China Intel & AI', subtitle: 'Filter DeepSeek, Qwen, CNNVD & sovereign China threat feeds', icon: 'globe', badge: '🇨🇳 CHINA', type: 'action', run: () => typeof setRegionFilter === 'function' ? setRegionFilter('china') : null },
  { id: 'action-theatre-india', title: 'Switch Theatre to India & South Asia', subtitle: 'Filter Indian AI startups, CERT-In & IIT deep tech research', icon: 'globe', badge: '🇮🇳 INDIA', type: 'action', run: () => typeof setRegionFilter === 'function' ? setRegionFilter('south_asia') : null },
  { id: 'action-theatre-middle-east', title: 'Switch Theatre to Middle East (Israel & UAE)', subtitle: 'Filter Check Point, TII Falcon, CTech & regional feeds', icon: 'globe', badge: '🇮🇱 🇦🇪 MIDEAST', type: 'action', run: () => typeof setRegionFilter === 'function' ? setRegionFilter('middle_east') : null },
  { id: 'action-theatre-apac', title: 'Switch Theatre to Asia-Pacific (Japan, Korea, Taiwan)', subtitle: 'Filter TSMC, Samsung AI, JPCERT & robotics', icon: 'globe', badge: '🇯🇵 🇰🇷 APAC', type: 'action', run: () => typeof setRegionFilter === 'function' ? setRegionFilter('apac') : null },
  { id: 'action-export-pdf', title: 'Export Threat Intelligence PDF Dossier', subtitle: 'Download executive multi-page PDF briefing report', icon: 'file-down', badge: 'PDF', type: 'action', run: () => typeof exportPdfReport === 'function' ? exportPdfReport() : null },
  { id: 'action-auto-triage', title: 'Run Autonomous Local LLM Triage', subtitle: 'Queue top threats for local Ollama (llama3.1:8b) deep analysis', icon: 'sparkles', badge: 'AI TRIAGE', type: 'action', run: () => typeof triggerTriageBackfill === 'function' ? triggerTriageBackfill() : null },
  { id: 'action-scan', title: 'Trigger Real-Time Intelligence Sweep', subtitle: 'Ingest latest CVEs, arXiv papers & GitHub advisories', icon: 'refresh-cw', badge: 'RADAR', type: 'action', run: () => typeof triggerScan === 'function' ? triggerScan() : null },
  { id: 'action-3d', title: 'Toggle 3D Holographic Globe Radar', subtitle: 'View or hide Three.js spatial threat matrix', icon: 'globe', badge: '3D WEBGL', type: 'action', run: () => typeof toggle3DGlobe === 'function' ? toggle3DGlobe() : null },
  { id: 'action-h24', title: 'Filter: Last 24 Hours Only', subtitle: 'Show emerging threats discovered in past 24h', icon: 'clock', badge: '24H', type: 'action', run: () => typeof setTimeHorizon === 'function' ? setTimeHorizon(24) : null },
  { id: 'action-pinned', title: 'Open Active Investigation Pinboard', subtitle: 'View all bookmarked & pinned incident files', icon: 'star', badge: 'PINBOARD', type: 'action', run: () => typeof setCategory === 'function' ? setCategory('pinned') : null },
  { id: 'action-export-md', title: 'Export Threat Intelligence Markdown Brief', subtitle: 'Download formatted report for Notion/Obsidian/GitHub', icon: 'file-text', badge: 'REPORT', type: 'action', run: () => typeof exportMarkdownReport === 'function' ? exportMarkdownReport() : null },
  { id: 'action-export-stix', title: 'Export Threat Intel STIX 2.1 Bundle', subtitle: 'Download JSON indicators for SIEM / MISP ingestion', icon: 'shield', badge: 'STIX 2.1', type: 'action', run: () => typeof exportStixJson === 'function' ? exportStixJson() : null },
  { id: 'action-watchlist', title: 'Manage Threat Hunting Watchlists', subtitle: 'Configure keyword rules and alerts', icon: 'target', badge: 'RULES', type: 'action', run: () => typeof openWatchlistModal === 'function' ? openWatchlistModal() : null },
  { id: 'action-audio', title: 'Toggle Cybernetic Audio Soundscape', subtitle: 'Switch audio synthesis alerts ON/OFF', icon: 'volume-2', badge: 'AUDIO', type: 'action', run: () => typeof toggleAudio === 'function' ? toggleAudio() : null }
];

function openCommandPalette() {
  const modal = document.getElementById('command-palette-modal');
  const input = document.getElementById('palette-search');
  if (!modal || !input) return;
  modal.classList.remove('hidden');
  input.value = '';
  input.focus();
  paletteSelectedIndex = 0;
  paletteItems = [...DEFAULT_PALETTE_ACTIONS];
  renderPaletteItems();
  if (typeof playBeep === 'function') playBeep('click');
}

function closeCommandPalette() {
  const modal = document.getElementById('command-palette-modal');
  if (modal) modal.classList.add('hidden');
}

function handlePaletteBackdrop(e) {
  if (e.target && e.target.id === 'command-palette-modal') {
    closeCommandPalette();
  }
}

var paletteDebounceTimer = null;
function handlePaletteSearch() {
  clearTimeout(paletteDebounceTimer);
  paletteDebounceTimer = setTimeout(async () => {
    const input = document.getElementById('palette-search');
    const query = input ? input.value.trim().toLowerCase() : '';
    if (!query) {
      paletteItems = [...DEFAULT_PALETTE_ACTIONS];
      paletteSelectedIndex = 0;
      renderPaletteItems();
      return;
    }

    // Filter default actions
    const matchedActions = DEFAULT_PALETTE_ACTIONS.filter(a =>
      a.title.toLowerCase().includes(query) || a.subtitle.toLowerCase().includes(query) || a.badge.toLowerCase().includes(query)
    );

    // Fetch live threats matching search query
    try {
      const res = await fetch(`/api/entries?search=${encodeURIComponent(query)}&limit=8`);
      const data = await res.json();
      const threatMatches = (data.entries || []).map(entry => ({
        id: `threat-${entry.id}`,
        title: entry.title,
        subtitle: `${entry.source_name} • ${entry.category} • Velocity: ${entry.threat_velocity || 25}/100`,
        icon: 'alert-triangle',
        badge: (entry.category || 'INTEL').toUpperCase(),
        type: 'threat',
        entry: entry,
        run: () => {
          closeCommandPalette();
          if (typeof openInspectModal === 'function') openInspectModal(entry);
        }
      }));

      paletteItems = [...matchedActions, ...threatMatches];
      paletteSelectedIndex = 0;
      renderPaletteItems();
    } catch (e) {
      paletteItems = matchedActions;
      paletteSelectedIndex = 0;
      renderPaletteItems();
    }
  }, 150);
}

function renderPaletteItems() {
  const container = document.getElementById('palette-content');
  if (!container) return;
  if (!paletteItems.length) {
    container.innerHTML = `
      <div class="p-8 text-center text-gray-500 font-mono text-xs">
        <i data-lucide="compass" class="w-6 h-6 mx-auto mb-2 text-gray-600"></i>
        No matching commands or threat advisories found.
      </div>
    `;
    if (typeof lucide !== 'undefined') lucide.createIcons();
    return;
  }

  container.innerHTML = paletteItems.map((item, idx) => `
    <div onclick="executePaletteItem(${idx})" class="p-3 rounded-xl flex items-center justify-between gap-3 cursor-pointer transition border ${idx === paletteSelectedIndex ? 'bg-white/[0.08] border-white/25 text-white shadow-md' : 'bg-black/40 border-white/[0.05] hover:bg-white/[0.04] text-slate-300'}">
      <div class="flex items-center gap-3 overflow-hidden">
        <div class="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${idx === paletteSelectedIndex ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30' : 'bg-white/[0.04] border border-white/[0.08] text-slate-400'}">
          <i data-lucide="${item.icon}" class="w-4 h-4"></i>
        </div>
        <div class="overflow-hidden">
          <div class="font-medium text-xs truncate ${idx === paletteSelectedIndex ? 'text-white' : 'text-slate-200'}">${item.title}</div>
          <div class="text-[10px] text-slate-400 truncate">${item.subtitle}</div>
        </div>
      </div>
      <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.04] border border-white/[0.08] text-slate-400 flex-shrink-0">${item.badge}</span>
    </div>
  `).join('');
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function executePaletteItem(index) {
  if (paletteItems[index] && typeof paletteItems[index].run === 'function') {
    if (typeof playBeep === 'function') playBeep('click');
    const action = paletteItems[index];
    closeCommandPalette();
    action.run();
  }
}

// Global Keyboard Navigation & Hotkeys
document.addEventListener('keydown', (e) => {
  // Cmd+K or Ctrl+K for Command Palette
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    const palModal = document.getElementById('command-palette-modal');
    if (palModal && palModal.classList.contains('hidden')) {
      openCommandPalette();
    } else if (palModal) {
      closeCommandPalette();
    }
    return;
  }

  // If Command Palette is open, trap its navigation
  const palModal = document.getElementById('command-palette-modal');
  if (palModal && !palModal.classList.contains('hidden')) {
    if (e.key === 'Escape') {
      closeCommandPalette();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      paletteSelectedIndex = (paletteSelectedIndex + 1) % Math.max(1, paletteItems.length);
      renderPaletteItems();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      paletteSelectedIndex = (paletteSelectedIndex - 1 + paletteItems.length) % Math.max(1, paletteItems.length);
      renderPaletteItems();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      executePaletteItem(paletteSelectedIndex);
    }
    return;
  }

  // If user is actively typing in an input or textarea, only process Escape
  const activeTag = document.activeElement ? document.activeElement.tagName : '';
  const isTyping = activeTag === 'INPUT' || activeTag === 'TEXTAREA' || (document.activeElement && document.activeElement.isContentEditable);
  if (isTyping) {
    if (e.key === 'Escape') {
      document.activeElement.blur();
    }
    return;
  }

  // Global Hotkeys
  if (e.key === 'Escape') {
    if (typeof closeInspectModal === 'function') closeInspectModal();
    if (typeof closeTriageModal === 'function') closeTriageModal();
    if (typeof closeWatchlistModal === 'function') closeWatchlistModal();
    if (typeof closeNewspaperModal === 'function') closeNewspaperModal();
    if (typeof closeEmailPdfModal === 'function') closeEmailPdfModal();
    if (typeof closeSourcesModal === 'function') closeSourcesModal();
    if (typeof closeTelegramModal === 'function') closeTelegramModal();
    if (typeof closeKeyboardModal === 'function') closeKeyboardModal();
    closeCommandPalette();
    const cards = document.querySelectorAll('#feed-container .feed-card');
    cards.forEach(c => c.classList.remove('card-focused'));
    if (typeof focusedCardIndex !== 'undefined') window.focusedCardIndex = -1;
    return;
  }

  if (e.key === '/') {
    e.preventDefault();
    const searchInput = document.getElementById('search-input');
    if (searchInput) {
      searchInput.focus();
      searchInput.select();
    }
    return;
  }

  if (e.key === '?') {
    e.preventDefault();
    if (typeof toggleKeyboardModal === 'function') toggleKeyboardModal();
    return;
  }

  if (e.key === 'g' || e.key === 'G') {
    e.preventDefault();
    if (typeof toggleViewMode === 'function') toggleViewMode();
    return;
  }

  if (e.key === 'b' || e.key === 'B') {
    e.preventDefault();
    if (typeof toggle3DGlobe === 'function') toggle3DGlobe();
    return;
  }

  if (e.key === 'j' || e.key === 'ArrowDown') {
    e.preventDefault();
    const idx = typeof focusedCardIndex !== 'undefined' ? focusedCardIndex : -1;
    if (typeof focusFeedCard === 'function') focusFeedCard(idx + 1);
    return;
  }

  if (e.key === 'k' || e.key === 'ArrowUp') {
    e.preventDefault();
    const idx = typeof focusedCardIndex !== 'undefined' ? focusedCardIndex : -1;
    if (typeof focusFeedCard === 'function') focusFeedCard(idx - 1);
    return;
  }

  if (e.key === 'Enter') {
    if (typeof getFocusedCardEntry === 'function' && typeof openInspectModal === 'function') {
      const entry = getFocusedCardEntry();
      if (entry) {
        e.preventDefault();
        openInspectModal(entry);
      }
    }
    return;
  }

  if (e.key === ' ') {
    if (typeof getFocusedCardEntry === 'function') {
      const entry = getFocusedCardEntry();
      if (entry && window.VoiceRadar && typeof window.VoiceRadar.speakSingleEntry === 'function') {
        e.preventDefault();
        window.VoiceRadar.speakSingleEntry(entry.id);
      }
    }
    return;
  }

  if (e.key.toLowerCase() === 'p') {
    if (typeof getFocusedCardEntry === 'function' && typeof togglePinThreat === 'function') {
      const entry = getFocusedCardEntry();
      if (entry) {
        e.preventDefault();
        togglePinThreat(entry.id);
      }
    }
    return;
  }

  if (e.key.toLowerCase() === 's') {
    if (typeof getFocusedCardEntry === 'function' && typeof shareCardLink === 'function') {
      const entry = getFocusedCardEntry();
      if (entry) {
        e.preventDefault();
        shareCardLink(entry.id);
      }
    }
    return;
  }

  if (e.key.toLowerCase() === 'o') {
    if (typeof getFocusedCardEntry === 'function') {
      const entry = getFocusedCardEntry();
      if (entry && entry.url) {
        e.preventDefault();
        window.open(entry.url, '_blank');
      }
    }
    return;
  }
});

// Expose globally for HTML onclick handlers
window.openCommandPalette = openCommandPalette;
window.closeCommandPalette = closeCommandPalette;
window.handlePaletteBackdrop = handlePaletteBackdrop;
window.handlePaletteSearch = handlePaletteSearch;
window.renderPaletteItems = renderPaletteItems;
window.executePaletteItem = executePaletteItem;
