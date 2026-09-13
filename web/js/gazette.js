// ══════════════════════════════════════════════════════════════════════════
// THE GLOBAL AI GAZETTE: AUTONOMOUS BROADSHEET & DISPATCH ENGINE
// Manages modal views, re-compilation, Markdown copy, and Email/Telegram PDF
// ══════════════════════════════════════════════════════════════════════════

let _latestNewspaperMarkdown = '';

async function openNewspaperModal() {
  const modal = document.getElementById('newspaper-modal');
  if (!modal) return;
  modal.classList.remove('hidden');
  if (typeof playBeep === 'function') playBeep('click');
  if (typeof lucide !== 'undefined') lucide.createIcons();

  try {
    const res = await fetch('/api/newspaper/latest');
    if (res.ok) {
      const data = await res.json();
      _latestNewspaperMarkdown = data.markdown || '';
      window._currentNewspaperMarkdown = _latestNewspaperMarkdown;
      
      const titleEl = document.getElementById('newspaper-modal-title');
      const badgeEl = document.getElementById('newspaper-edition-badge');
      const dateEl = document.getElementById('newspaper-modal-date');
      const mdView = document.getElementById('newspaper-markdown-view');

      if (titleEl) titleEl.textContent = `The Global AI Gazette — Autonomous Broadsheet`;
      if (badgeEl) badgeEl.textContent = `EDITION #${data.edition_number || '100'}`;
      if (dateEl) {
        const dt = data.generated_at ? new Date(data.generated_at).toLocaleString() : 'Recent';
        dateEl.textContent = `5-Hour Intelligence Cycle • Compiled: ${dt} • ${data.total_threats || 0} Stories & Models Analyzed`;
      }
      if (mdView) mdView.textContent = _latestNewspaperMarkdown;
    }

    // Refresh iframe src with cache buster
    const iframe = document.getElementById('newspaper-iframe');
    if (iframe) iframe.src = '/api/newspaper/latest/html?t=' + Date.now();
  } catch (e) {
    console.warn("Failed to load latest newspaper details:", e);
  }
}

function closeNewspaperModal() {
  const modal = document.getElementById('newspaper-modal');
  if (modal) modal.classList.add('hidden');
}

function switchNewspaperView(mode) {
  const iframe = document.getElementById('newspaper-iframe');
  const mdView = document.getElementById('newspaper-markdown-view');
  const visualTab = document.getElementById('tab-newspaper-visual');
  const mdTab = document.getElementById('tab-newspaper-markdown');

  if (mode === 'visual') {
    if (iframe) iframe.classList.remove('hidden');
    if (mdView) mdView.classList.add('hidden');
    if (visualTab) {
      visualTab.className = 'px-3 py-1 rounded-md bg-white/[0.12] text-white border border-white/[0.2] font-semibold flex items-center gap-1.5';
    }
    if (mdTab) {
      mdTab.className = 'px-3 py-1 rounded-md bg-transparent text-slate-400 hover:text-slate-200 border border-transparent font-medium flex items-center gap-1.5';
    }
  } else {
    if (iframe) iframe.classList.add('hidden');
    if (mdView) mdView.classList.remove('hidden');
    if (mdTab) {
      mdTab.className = 'px-3 py-1 rounded-md bg-white/[0.12] text-white border border-white/[0.2] font-semibold flex items-center gap-1.5';
    }
    if (visualTab) {
      visualTab.className = 'px-3 py-1 rounded-md bg-transparent text-slate-400 hover:text-slate-200 border border-transparent font-medium flex items-center gap-1.5';
    }
  }
  if (typeof playBeep === 'function') playBeep('click');
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function triggerNewspaperCompile() {
  const btn = document.getElementById('newspaper-recompile-btn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> Compiling...`;
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
  if (typeof playBeep === 'function') playBeep('alert');

  try {
    const res = await fetch('/api/newspaper/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ window_hours: 5 })
    });
    const data = await res.json();
    if (typeof showToast === 'function') showToast(data.message || "Fresh 5-Hour Newspaper Edition Published!", "info");
    await openNewspaperModal();
  } catch (e) {
    if (typeof showToast === 'function') showToast("Compilation failed: " + e.message, "alert");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="refresh-cw" class="w-3.5 h-3.5"></i> <span class="hidden sm:inline">Compile Now</span>`;
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }
  }
}

function copyNewspaperMarkdown() {
  if (!_latestNewspaperMarkdown) return;
  navigator.clipboard.writeText(_latestNewspaperMarkdown).then(() => {
    const txt = document.getElementById('newspaper-copy-text');
    if (txt) {
      txt.textContent = 'Copied!';
      setTimeout(() => { txt.textContent = 'Copy Markdown'; }, 2000);
    }
    if (typeof playBeep === 'function') playBeep('click');
  }).catch(err => {
    console.warn("Clipboard failed:", err);
  });
}

async function dispatchNewspaperToTelegram(force = false) {
  const btn = document.getElementById('chronicle-telegram-btn');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin text-sky-400"></i><span>Sending...</span>`;
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
  if (typeof playBeep === 'function') playBeep('alert');

  try {
    const res = await fetch('/api/newspaper/telegram', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force })
    });
    const data = await res.json();
    if (data.status === 'skipped') {
      if (typeof showToast === 'function') showToast(data.message, "alert");
      if (!force && confirm(`${data.message}\n\nDo you want to FORCE send it to Telegram anyway?`)) {
        return dispatchNewspaperToTelegram(true);
      }
    } else if (res.ok) {
      if (typeof showToast === 'function') showToast(data.message || "The Global AI Gazette PDF sent to Telegram!", "info");
    } else {
      if (typeof showToast === 'function') showToast("Failed to send to Telegram: " + (data.detail || "Error"), "alert");
    }
  } catch (e) {
    if (typeof showToast === 'function') showToast("Telegram send error: " + e.message, "alert");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i data-lucide="send" class="w-3.5 h-3.5 text-sky-400"></i><span>Telegram PDF</span>`;
      if (typeof lucide !== 'undefined') lucide.createIcons();
    }
  }
}

function narrateChronicle() {
  if (!window.VoiceRadar) {
    if (typeof showToast === 'function') showToast("Voice Radar engine not initialized", "alert");
    return;
  }
  const rawMd = window._currentNewspaperMarkdown || "";
  let narrative = "Good day. This is your Global AI Gazette audio edition. Worldwide AI telemetry active across fifty verified research hubs and developer codebases. ";

  if (rawMd) {
    const leadMatch = rawMd.match(/##? (?:🚀 LEAD STORY:|LEAD STORY:)\s*(.+)/i) || rawMd.match(/#+ (?:FRONT PAGE|BREAKING):\s*(.+)/i);
    if (leadMatch) {
      narrative += "Lead story: " + leadMatch[1].replace(/[*_~`#]/g, '') + ". ";
    }
    const execMatch = rawMd.match(/## (?:🌐 EXECUTIVE AI STRATEGIC BRIEFING|👔 CISO EXECUTIVE INTELLIGENCE BRIEF)\n+([^#\n]+)/i);
    if (execMatch) {
      narrative += "Executive briefing: " + execMatch[1].replace(/[*_~`#]/g, '') + ". ";
    }
    narrative += "Strategic vectors: Optimize test-time compute, benchmark KV-cache quantization, and evaluate open-weights foundation architectures. End of broadcast.";
  } else {
    narrative += "Global AI telemetry active across developer hubs, frontier model releases, and arXiv research preprints. All feeds operational.";
  }

  window.VoiceRadar.speak(narrative, { priority: true });
  if (typeof showToast === 'function') showToast("🎙️ Voice AI reading Global AI Gazette broadcast...", "info");
}

function openEmailPdfModal() {
  const modal = document.getElementById('email-pdf-modal');
  const statusBox = document.getElementById('email-pdf-status');
  if (statusBox) statusBox.classList.add('hidden');
  if (modal) modal.classList.remove('hidden');
  if (typeof playBeep === 'function') playBeep('click');
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function closeEmailPdfModal() {
  const modal = document.getElementById('email-pdf-modal');
  if (modal) modal.classList.add('hidden');
}

async function sendNewspaperPdfEmail(force = false) {
  const targetInput = document.getElementById('email-pdf-target');
  const statusBox = document.getElementById('email-pdf-status');
  const btn = document.getElementById('send-pdf-email-btn');
  
  const toEmail = targetInput ? targetInput.value.trim() : '';
  if (!toEmail || !toEmail.includes('@')) {
    alert("Please enter a valid recipient email address.");
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader" class="w-4 h-4 animate-spin"></i> Dispatching PDF...`;
  if (typeof lucide !== 'undefined') lucide.createIcons();
  if (typeof playBeep === 'function') playBeep('alert');

  try {
    const res = await fetch('/api/newspaper/email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to_email: toEmail, force })
    });
    const data = await res.json();
    
    if (data.status === 'skipped') {
      statusBox.classList.remove('hidden', 'bg-rose-500/20', 'text-rose-300', 'bg-emerald-500/15', 'text-emerald-300');
      statusBox.classList.add('bg-amber-500/20', 'text-amber-300', 'border', 'border-amber-500/30');
      statusBox.textContent = data.message;
      if (typeof showToast === 'function') showToast(data.message, "alert");
      if (!force && confirm(`${data.message}\n\nDo you want to FORCE send the email anyway?`)) {
        return sendNewspaperPdfEmail(true);
      }
    } else if (res.ok) {
      statusBox.classList.remove('hidden', 'bg-rose-500/20', 'text-rose-300', 'bg-amber-500/20', 'text-amber-300');
      statusBox.classList.add('bg-emerald-500/15', 'text-emerald-300', 'border', 'border-emerald-500/30');
      statusBox.textContent = data.message || `PDF Edition emailed successfully to ${toEmail}!`;
      if (typeof showToast === 'function') showToast(`The Global AI Gazette sent to ${toEmail}!`, "info");
    } else {
      statusBox.classList.remove('hidden', 'bg-emerald-500/15', 'text-emerald-300', 'bg-amber-500/20', 'text-amber-300');
      statusBox.classList.add('bg-rose-500/20', 'text-rose-300', 'border', 'border-rose-500/30');
      statusBox.textContent = data.detail || "Email delivery failed. Please check SMTP configuration.";
      if (typeof showToast === 'function') showToast("Failed to email PDF: " + (data.detail || "SMTP error"), "alert");
    }
  } catch (e) {
    statusBox.classList.remove('hidden', 'bg-emerald-500/15', 'text-emerald-300', 'bg-amber-500/20', 'text-amber-300');
    statusBox.classList.add('bg-rose-500/20', 'text-rose-300', 'border', 'border-rose-500/30');
    statusBox.textContent = "Error sending email: " + e.message;
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="send" class="w-4 h-4"></i> Dispatch PDF to Email`;
    if (typeof lucide !== 'undefined') lucide.createIcons();
  }
}
