// ══════════════════════════════════════════════════════════════════════════
// WEBSOCKET CLIENT & REAL-TIME HUD TELEMETRY ENGINE
// Manages WebSocket connection, exponential backoff, ping/pong RTT,
// live event dispatching, and luxury toast notifications
// ══════════════════════════════════════════════════════════════════════════

var _wsReconnectDelay = 3000; // starts at 3s, doubles up to 30s max
var _wsReconnectTimer = null;
var ws = null;
window.ws = ws;

// Pending new stories tracking
var pendingNewEntries = [];
window.pendingNewEntries = pendingNewEntries;

var rocketStreamActive = false;
window.rocketStreamActive = rocketStreamActive;

function initWebSocket() {
  // Prevent duplicate reconnect timers
  if (_wsReconnectTimer) { clearTimeout(_wsReconnectTimer); _wsReconnectTimer = null; }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws`;
  
  ws = new WebSocket(wsUrl);
  window.ws = ws;

  ws.onopen = () => {
    console.log("WebSocket connected to Global AI Intelligence Radar");
    _wsReconnectDelay = 3000; // reset backoff on successful connect
    const statusEl = document.getElementById('connection-status');
    if (statusEl) statusEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span> WS:<span id="ping-time" class="text-emerald-400 ml-0.5">0ms</span>`;
    
    // Measure real network RTT latency every 4s
    if (window._pingInterval) clearInterval(window._pingInterval);
    window._pingInterval = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping', timestamp: performance.now() }));
      }
    }, 4000);
    // Initial ping immediately
    setTimeout(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping', timestamp: performance.now() }));
      }
    }, 500);
  };

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleWebSocketMessage(msg);
    } catch (e) {
      console.error("WS parse error: ", e);
    }
  };

  ws.onclose = () => {
    if (window._pingInterval) clearInterval(window._pingInterval);
    const statusEl = document.getElementById('connection-status');
    if (statusEl) statusEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-rose-400 animate-pulse"></span> WS:<span class="text-rose-400 ml-0.5">RECONNECTING</span>`;
    // Exponential backoff: 3s → 6s → 12s → 30s max
    _wsReconnectTimer = setTimeout(() => {
      _wsReconnectDelay = Math.min(_wsReconnectDelay * 2, 30000);
      initWebSocket();
    }, _wsReconnectDelay);
  };

  ws.onerror = (err) => {
    console.error("WebSocket error: ", err);
  };
}

// Live KPI Counter Animated Ticker
function incrementKPICounter(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const text = el.innerText.trim();
  if (text === '—') {
    el.innerText = '1';
    return;
  }
  const current = parseInt(text.replace(/,/g, ''), 10);
  if (!isNaN(current)) {
    el.innerText = (current + 1).toLocaleString();
    el.classList.add('text-cyan-300');
    setTimeout(() => el.classList.remove('text-cyan-300'), 500);
  }
}

function updatePendingBanner() {
  const banner = document.getElementById('new-stories-banner');
  const countEl = document.getElementById('new-stories-count');
  const pill = document.getElementById('new-stories-floating-pill');
  const pillCount = document.getElementById('new-stories-floating-count');

  const count = (window.pendingNewEntries || pendingNewEntries).length;
  if (count > 0) {
    if (banner) {
      banner.classList.remove('hidden');
      if (countEl) countEl.innerText = count;
    }
    if (pill) {
      pill.classList.remove('hidden');
      if (pillCount) pillCount.innerText = count;
    }
  } else {
    if (banner) banner.classList.add('hidden');
    if (pill) pill.classList.add('hidden');
  }
  if (typeof lucide !== 'undefined' && lucide.createIcons) {
    lucide.createIcons();
  }
}

// Handle incoming WebSocket messages (🚀 Rocket-Speed Live Stream: auto-inject on arrival)
function handleWebSocketMessage(msg) {
  if (msg.type === 'pong') {
    const pingTimeEl = document.getElementById('ping-time');
    if (pingTimeEl && msg.timestamp) {
      const rtt = Math.max(1, Math.round(performance.now() - msg.timestamp));
      pingTimeEl.innerText = rtt + 'ms';
    }
  } else if (msg.type === 'connected') {
    if (msg.stats && typeof renderStats === 'function') renderStats(msg.stats);
  } else if (msg.type === 'emergency_threat_alert' || msg.type === 'new_entry' || msg.type === 'landmark_ai_breakthrough') {
    const entry = msg.data || msg.entry;
    if (!entry) return;

    // 🚀 ROCKET MODE: Instantly inject new entry into live feed
    const entryId = entry.id || ('new-' + (entry.url || Date.now()));
    entry.id = entryId;
    entry.is_new_since_refresh = true;

    const allItems = window.allFeedItems || [];
    // Deduplicate: skip if card already in DOM or allFeedItems
    if (!document.getElementById('ai-card-' + entryId) && !document.getElementById('threat-card-' + entryId) && !allItems.some(e => e.id === entryId)) {
      allItems.unshift(entry);
      if (allItems.length > 250) allItems.length = 250;
      if (typeof prependFeedItem === 'function') prependFeedItem(entry);
      
      const lb = document.getElementById('feed-loading-bar');
      if (lb) { lb.classList.add('opacity-100'); setTimeout(() => lb.classList.remove('opacity-100'), 600); }
    }

    if (msg.type === 'landmark_ai_breakthrough') {
      showHUDToast({
        title: 'Landmark AI Breakthrough',
        message: entry.title,
        badge: entry.archetype || 'BREAKTHROUGH',
        icon: 'sparkles',
        color: 'text-violet-400',
        borderClass: 'border-violet-500/40',
        onClick: () => {
          if (typeof openInspectModal === 'function') openInspectModal(entry);
        }
      });
      if (typeof playBeep === 'function') playBeep('alert');
    }

    // Soft Real-Time Telemetry Counter Increment (Deduplicated to prevent dual-event counter surges)
    window._seenCounterEntryIds = window._seenCounterEntryIds || new Set();
    if (!window._seenCounterEntryIds.has(entryId)) {
      window._seenCounterEntryIds.add(entryId);
      if (window._seenCounterEntryIds.size > 2000) {
        const arr = Array.from(window._seenCounterEntryIds);
        window._seenCounterEntryIds = new Set(arr.slice(arr.length - 1000));
      }
      incrementKPICounter('total-entries');
      const cat = entry.category || '';
      if (cat === 'github_trending' || cat === 'trending_repos') incrementKPICounter('trending-repos-count');
      else if (cat === 'ai_models' || cat === 'frontier_models') incrementKPICounter('frontier-models-count');
      else if (cat === 'ai_research' || cat === 'research_papers') incrementKPICounter('ai-count');
      else if (cat === 'cyber_tools' || cat === 'dev_tools') incrementKPICounter('developer-tools-count');
      else if (cat === 'ai_tech') incrementKPICounter('global-tech-count');
    }

    // Mark stats dirty so engine proactively refreshes on next tick
    if (window.DataSyncEngine) window.DataSyncEngine.invalidate('stats');

  } else if (msg.type === 'scan_status') {
    const banner = document.getElementById('scan-progress-banner');
    const icon = document.getElementById('scan-icon');
    if (msg.status === 'started') {
      if (banner) banner.classList.remove('hidden');
      const bannerText = document.getElementById('scan-banner-text');
      if (bannerText) bannerText.innerText = msg.message || "Active intelligence sweep in progress...";
      if (icon) icon.classList.add('animate-spin');
    } else {
      if (banner) banner.classList.add('hidden');
      if (icon) icon.classList.remove('animate-spin');
      if (msg.results) {
        if (window.DataSyncEngine) {
          window.DataSyncEngine.invalidate('stats');
          window.DataSyncEngine.invalidate('sweep');
          window.DataSyncEngine.invalidate('feed');
        } else if (typeof refreshStats === 'function') {
          refreshStats();
        }
      }
    }
  } else if (msg.type === 'triage_queue_updated') {
    if (typeof updateTriageStatus === 'function') updateTriageStatus(msg.data);
  } else if (msg.type === 'triage_completed') {
    if (typeof handleTriageCompleted === 'function') handleTriageCompleted(msg.data);
  }
}

// Generic Luxury HUD Toast System
function showToast(message, type = 'info') {
  showHUDToast({
    title: type === 'alert' ? 'System Notice' : 'Intelligence Radar',
    message: message,
    badge: type.toUpperCase(),
    icon: type === 'alert' ? 'alert-triangle' : 'shield',
    color: type === 'alert' ? 'text-amber-400' : 'text-cyan-400',
    borderClass: type === 'alert' ? 'border-amber-500/40' : 'border-cyan-500/40'
  });
}

function showHUDToast({ title, message, badge = "SYSTEM", icon = "info", color = "text-sky-400", borderClass = "border-white/[0.08]", onClick = null }) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  // Keep maximum 3 toast notifications on screen to prevent browser UI spam
  while (container.children.length >= 3) {
    container.lastElementChild.remove();
  }

  const toastId = 'toast-' + Math.random().toString(36).substring(2, 9);
  const toast = document.createElement('div');
  toast.id = toastId;
  toast.className = `glass-panel pointer-events-auto rounded-xl p-4 shadow-2xl transition-all duration-300 toast-animate-in flex gap-3 border ${borderClass} bg-black/90`;
  toast.innerHTML = `
    <div class="mt-0.5">
      <div class="w-8 h-8 rounded-lg bg-white/[0.04] ${color} flex items-center justify-center border border-white/[0.08]">
        <i data-lucide="${icon}" class="w-4 h-4"></i>
      </div>
    </div>
    <div class="flex-1 min-w-0 ${onClick ? 'cursor-pointer' : ''}">
      <div class="flex items-center justify-between gap-2">
        <span class="text-[10px] font-mono uppercase font-semibold px-1.5 py-0.5 rounded bg-white/[0.06] ${color}">${badge}</span>
        <span class="text-[10px] font-mono text-slate-500">SYSTEM</span>
      </div>
      <h4 class="text-xs font-semibold text-white mt-1 line-clamp-1">${title}</h4>
      <p class="text-[11px] text-slate-400 mt-0.5 font-sans line-clamp-2">${message}</p>
    </div>
    <button onclick="dismissToast('${toastId}')" class="text-slate-400 hover:text-white self-start">
      <i data-lucide="x" class="w-3.5 h-3.5"></i>
    </button>
  `;
  if (onClick) {
    toast.querySelector('.flex-1').addEventListener('click', onClick);
  }
  container.prepend(toast);
  if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons({ root: toast });
  setTimeout(() => dismissToast(toastId), 4500);
}

// Toast Pop-up Notification Engine for Ingested Entries
const _toastEntryRegistry = {}; // Safe map: toastId → entry object

function showToastNotification(entry) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  while (container.children.length >= 3) {
    container.lastElementChild.remove();
  }
  
  const cat = entry.category || '';
  const isTrending = cat === 'trending_repos' || cat === 'github' || cat === 'github_trending';
  const isPaper = cat === 'research_papers' || cat === 'arxiv' || cat === 'ai_research';
  const isModel = cat === 'frontier_models' || cat === 'models' || cat === 'ai_models';
  const isTools = cat === 'dev_tools' || cat === 'infrastructure' || cat === 'cyber_tools';
  const isTech = cat === 'ai_tech';

  const toastId = 'toast-' + Math.random().toString(36).substring(2, 9);
  const toast = document.createElement('div');
  toast.id = toastId;
  _toastEntryRegistry[toastId] = entry;
  
  let borderClass = 'border-white/[0.08] bg-black/90';
  let icon = 'bot';
  let color = 'text-sky-400';
  let label = (entry.category || 'AI INTELLIGENCE').replace(/_/g, ' ').toUpperCase();

  if (isTrending) {
    borderClass = 'border-emerald-500/40 bg-black/90 shadow-emerald-500/15';
    icon = 'git-branch';
    color = 'text-emerald-400';
    label = 'TRENDING REPO';
  } else if (isPaper) {
    borderClass = 'border-purple-500/40 bg-black/90 shadow-purple-500/15';
    icon = 'book-open';
    color = 'text-purple-400';
    label = 'AI BREAKTHROUGH';
  } else if (isModel) {
    borderClass = 'border-cyan-500/40 bg-black/90 shadow-cyan-500/15';
    icon = 'cpu';
    color = 'text-cyan-400';
    label = 'FRONTIER MODEL';
  } else if (isTools) {
    borderClass = 'border-amber-500/40 bg-black/90 shadow-amber-500/15';
    icon = 'wrench';
    color = 'text-amber-400';
    label = 'DEV TOOLS / INFRA';
  } else if (isTech) {
    borderClass = 'border-sky-500/40 bg-black/90 shadow-sky-500/15';
    icon = 'globe';
    color = 'text-sky-400';
    label = 'GLOBAL AI TECH';
  }

  toast.className = `glass-panel pointer-events-auto rounded-xl p-4 shadow-2xl transition-all duration-300 toast-animate-in flex gap-3 border ${borderClass}`;

  const safeTitle = (entry.title || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const safeSummary = ((entry.analysis && entry.analysis.summary) || entry.summary || 'New intelligence advisory detected.').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  toast.innerHTML = `
    <div class="mt-0.5">
      <div class="w-8 h-8 rounded-lg bg-white/[0.04] ${color} flex items-center justify-center border border-white/[0.08]">
        <i data-lucide="${icon}" class="w-4 h-4"></i>
      </div>
    </div>
    <div class="flex-1 min-w-0">
      <div class="flex items-center justify-between gap-2">
        <span class="text-[10px] font-mono uppercase font-semibold px-1.5 py-0.5 rounded bg-white/[0.06] ${color}">
          ${label}
        </span>
        <span class="text-[10px] font-mono text-slate-500">JUST NOW</span>
      </div>
      <h4 class="text-xs font-semibold text-white mt-1 line-clamp-1 hover:text-sky-300 cursor-pointer toast-inspect-btn" data-toast-id="${toastId}">
        ${safeTitle}
      </h4>
      <p class="text-[11px] text-slate-400 line-clamp-2 mt-0.5 font-sans">
        ${safeSummary}
      </p>
      <div class="mt-2 flex items-center justify-between">
        <span class="text-[10px] font-mono text-slate-400">${(entry.source_name || 'Feed').replace(/</g,'&lt;')}</span>
        <button class="text-[11px] text-sky-400 hover:underline flex items-center gap-1 font-mono toast-inspect-btn" data-toast-id="${toastId}">
          Deep Inspect <i data-lucide="arrow-right" class="w-3 h-3"></i>
        </button>
      </div>
    </div>
    <button onclick="dismissToast('${toastId}')" class="text-slate-400 hover:text-white self-start">
      <i data-lucide="x" class="w-3.5 h-3.5"></i>
    </button>
  `;

  toast.querySelectorAll('.toast-inspect-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const e = _toastEntryRegistry[btn.getAttribute('data-toast-id')];
      if (e && typeof openInspectModal === 'function') openInspectModal(e);
    });
  });

  container.prepend(toast);
  if (typeof lucide !== 'undefined' && lucide.createIcons) lucide.createIcons({ root: toast });

  setTimeout(() => dismissToast(toastId), 4500);
}

function dismissToast(id) {
  const el = document.getElementById(id);
  if (el) {
    el.style.opacity = '0';
    el.style.transform = 'translateX(100%)';
    setTimeout(() => {
      if (el && el.remove) el.remove(); else if (el && el.parentNode) el.parentNode.removeChild(el);
      delete _toastEntryRegistry[id];
    }, 300);
  }
}

// Global exposure
window.initWebSocket = initWebSocket;
window.handleWebSocketMessage = handleWebSocketMessage;
window.incrementKPICounter = incrementKPICounter;
window.updatePendingBanner = updatePendingBanner;
window.showToast = showToast;
window.showHUDToast = showHUDToast;
window.showToastNotification = showToastNotification;
window.dismissToast = dismissToast;
