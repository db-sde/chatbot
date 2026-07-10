(function () {
  const script = document.currentScript;
  const scriptSrc = script ? script.src : "";
  const apiBase = (script && script.dataset.apiBase) || (scriptSrc && scriptSrc.startsWith("http") ? new URL(scriptSrc).origin : window.location.origin);
  const pageSlug = (script && script.dataset.universitySlug) || location.pathname.split("/").filter(Boolean).pop() || null;
  const siteKey = (script && script.dataset.siteKey) || "default";
  const storageKey = "degreebaba_ai_session_id";
  const sessionId = localStorage.getItem(storageKey) || crypto.randomUUID();
  localStorage.setItem(storageKey, sessionId);

  // -------------------------------------------------------------------------
  // Default widget configuration.
  // -------------------------------------------------------------------------
  const settings = {
    primary_color: "#135d66",
    widget_title: "DegreeBaba Assistant",
    bot_name: "DegreeBaba Assistant",
    welcome_message: "Hello! Ask me about colleges, courses, admissions and fees.",
    logo_url: "",
    show_on_mobile: true,
    show_on_desktop: true,
    lead_capture_enabled: true,
    capture_name: true,
    capture_email: true,
    capture_phone: true,
    lead_trigger: "during_chat",
    lead_form_title: "Request callback",
    lead_form_description: "A counsellor can follow up with you."
  };

  // -------------------------------------------------------------------------
  // Device detection & Audio
  // -------------------------------------------------------------------------
  const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (isTouch && window.innerWidth <= 768);

  const AUDIO_SRC = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAAAAAA==";
  const audioCtx = typeof AudioContext !== "undefined" ? new AudioContext() : null;

  async function playSound() {
    try {
      if (audioCtx && audioCtx.state === "suspended") await audioCtx.resume();
      const audio = new Audio(AUDIO_SRC);
      audio.volume = 0.3;
      await audio.play();
    } catch (_) {}
  }

  // -------------------------------------------------------------------------
  // DOM setup & Shadow Root
  // -------------------------------------------------------------------------
  const host = document.createElement("div");
  host.id = "degreebaba-ai-widget";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  // Icons (Inline SVGs)
  const ICON_CHAT = `<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>`;
  const ICON_CLOSE = `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
  const ICON_SEND = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>`;

  root.innerHTML = `
    <style>
      :host {
        --primary-color: #135d66;
        --primary-hover: #0f4a52;
        --bg-color: #ffffff;
        --bg-secondary: #f7faf9;
        --text-main: #172326;
        --text-muted: #6b7d7a;
        --border-color: #e7eeee;
        all: initial;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      }
      
      * { box-sizing: border-box; }

      .bubble {
        position: fixed; right: 24px; bottom: 24px; width: 60px; height: 60px;
        border-radius: 50%; border: 0; background: var(--primary-color); color: white;
        box-shadow: 0 8px 24px rgba(19, 93, 102, 0.35);
        cursor: pointer; z-index: 2147483647; display: flex; align-items: center; justify-content: center;
        transition: transform 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275), box-shadow 0.3s ease;
      }
      .bubble:hover { transform: scale(1.08); box-shadow: 0 12px 28px rgba(19, 93, 102, 0.45); }
      .bubble:active { transform: scale(0.95); }
      .bubble.hidden { display: none !important; }
      .bubble::before {
        content: ''; position: absolute; width: 100%; height: 100%; border-radius: 50%;
        border: 2px solid var(--primary-color); animation: pulse 2.5s infinite;
      }
      .bubble.interacted::before { display: none; }
      @keyframes pulse {
        0% { transform: scale(1); opacity: 0.8; }
        100% { transform: scale(1.5); opacity: 0; }
      }

      .panel {
        position: fixed; right: 24px; bottom: 100px; width: 380px; max-width: calc(100vw - 32px);
        height: 620px; max-height: calc(100vh - 120px); background: var(--bg-color);
        color: var(--text-main); border-radius: 16px; box-shadow: 0 24px 48px rgba(0,0,0,0.15);
        display: flex; flex-direction: column; z-index: 2147483647; overflow: hidden;
        opacity: 0; transform: translateY(20px) scale(0.98); pointer-events: none;
        transition: opacity 0.3s ease, transform 0.35s cubic-bezier(0.175, 0.885, 0.32, 1.275);
      }
      .panel.open { opacity: 1; transform: translateY(0) scale(1); pointer-events: auto; }

      .head {
        padding: 16px 20px; background: var(--primary-color); color: white;
        display: flex; justify-content: space-between; align-items: center; flex-shrink: 0;
      }
      .head .title-area { display: flex; align-items: center; gap: 12px; }
      .head .logo { width: 32px; height: 32px; border-radius: 50%; object-fit: cover; background: white; }
      .head .logo-fallback {
        width: 32px; height: 32px; border-radius: 50%; background: rgba(255,255,255,0.2);
        display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 13px;
      }
      .head .info { display: flex; flex-direction: column; }
      .head .title { font-size: 15px; font-weight: 600; line-height: 1.2; }
      .head .status { font-size: 12px; opacity: 0.85; margin-top: 2px; display: flex; align-items: center; gap: 5px; }
      .head .status::before { content: ''; width: 6px; height: 6px; background: #4ade80; border-radius: 50%; display: inline-block; }
      .close-btn {
        background: rgba(255,255,255,0.1); border: 0; color: white; cursor: pointer;
        width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
        transition: background 0.2s; padding: 0;
      }
      .close-btn:hover { background: rgba(255,255,255,0.2); }

      .msgs {
        flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px;
        background: var(--bg-secondary); scrollbar-width: thin; scrollbar-color: #cfd8d6 transparent;
      }
      .msgs::-webkit-scrollbar { width: 6px; }
      .msgs::-webkit-scrollbar-thumb { background: #cfd8d6; border-radius: 3px; }

      .msg {
        max-width: 80%; padding: 10px 14px; border-radius: 12px; line-height: 1.5;
        font-size: 14px; white-space: pre-wrap; overflow-wrap: anywhere; position: relative;
        animation: msgIn 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
      }
      @keyframes msgIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
      
      .user { align-self: flex-end; background: var(--primary-color); color: white; border-bottom-right-radius: 4px; box-shadow: 0 2px 5px rgba(19,93,102,0.2); }
      .bot { align-self: flex-start; background: white; border: 1px solid var(--border-color); color: var(--text-main); border-bottom-left-radius: 4px; }
      .bot strong, .bot b { color: var(--primary-color); font-weight: 700; }
      .bot ul { margin: 6px 0; padding-left: 20px; display: grid; gap: 5px; }
      .bot li { padding-left: 2px; }
      .bot .section-label { color: var(--primary-color); font-weight: 700; }
      .bot code { background: #eef4f3; padding: 2px 4px; border-radius: 4px; font-family: monospace; font-size: 13px; }
      .stream-cursor { display: inline-block; width: 2px; height: 14px; background: var(--primary-color); margin-left: 2px; animation: blink 1s infinite; vertical-align: middle; }
      @keyframes blink { 0%, 50% { opacity: 1; } 51%, 100% { opacity: 0; } }

      .history-divider { align-self: center; font-size: 11px; color: var(--text-muted); background: #e7eeee; padding: 4px 12px; border-radius: 12px; margin: 4px 0; }
      .load-more { align-self: center; background: white; border: 1px solid var(--border-color); color: var(--primary-color); padding: 6px 16px; border-radius: 999px; cursor: pointer; font-size: 12px; font-weight: 500; transition: all 0.2s; }
      .load-more:hover { background: var(--bg-secondary); border-color: var(--primary-color); }

      /* Upgraded Thinking Animation */
      .thinking-bubble {
        align-self: flex-start; background: white; border: 1px solid var(--border-color);
        padding: 12px 16px; border-radius: 12px; border-bottom-left-radius: 4px;
        display: flex; flex-direction: column; gap: 6px; animation: msgIn 0.3s ease;
      }
      .dots-container { display: flex; gap: 5px; }
      .dots-container span {
        width: 7px; height: 7px; border-radius: 50%; background: var(--primary-color);
        animation: bounce 1.4s infinite ease-in-out both;
      }
      .dots-container span:nth-child(1) { animation-delay: -0.32s; }
      .dots-container span:nth-child(2) { animation-delay: -0.16s; }
      @keyframes bounce { 0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; } 40% { transform: scale(1); opacity: 1; } }
      
      .thinking-text {
        font-size: 11px; color: var(--text-muted); font-style: italic;
        transition: opacity 0.4s ease-in-out; white-space: nowrap;
      }

      .chips { display: flex; gap: 8px; flex-wrap: wrap; padding: 12px 20px; border-top: 1px solid var(--border-color); background: white; flex-shrink: 0; }
      .chip { border: 1px solid var(--border-color); background: white; color: var(--primary-color); padding: 8px 14px; border-radius: 999px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all 0.2s; }
      .chip:hover { background: var(--primary-color); color: white; border-color: var(--primary-color); }
      .chip:disabled { opacity: 0.55; cursor: not-allowed; }

      .composer { display: flex; gap: 8px; padding: 16px; border-top: 1px solid var(--border-color); background: white; flex-shrink: 0; align-items: center; }
      .input-wrap { flex: 1; position: relative; }
      input {
        width: 100%; border: 1px solid var(--border-color); border-radius: 24px;
        padding: 12px 16px; font: inherit; font-size: 14px; outline: none; transition: border-color 0.2s, box-shadow 0.2s; background: var(--bg-secondary);
      }
      input:focus { border-color: var(--primary-color); box-shadow: 0 0 0 3px rgba(19, 93, 102, 0.1); background: white; }
      .send-btn {
        width: 42px; height: 42px; border-radius: 50%; border: 0; background: var(--primary-color); color: white;
        cursor: pointer; display: flex; align-items: center; justify-content: center; transition: background 0.2s, transform 0.2s; flex-shrink: 0;
      }
      .send-btn:hover { background: var(--primary-hover); transform: scale(1.05); }
      .send-btn:active { transform: scale(0.95); }
      .send-btn:disabled { background: #b9cbc8; cursor: not-allowed; }

      .lead-card {
        background: white; border: 1px solid var(--border-color); border-radius: 12px; padding: 16px;
        margin-top: 8px; display: flex; flex-direction: column; gap: 10px; animation: msgIn 0.3s ease;
        align-self: center; width: 90%; box-shadow: 0 4px 12px rgba(0,0,0,0.05);
      }
      .lead-card h4 { margin: 0; font-size: 15px; color: var(--text-main); }
      .lead-card p { margin: 0; font-size: 12px; color: var(--text-muted); }
      .lead-card input { background: white; }
      .lead-card .lead-submit { background: var(--primary-color); color: white; border: 0; border-radius: 8px; padding: 10px; font-weight: 500; cursor: pointer; transition: background 0.2s; font-size: 14px; }
      .lead-card .lead-submit:hover { background: var(--primary-hover); }
      .lead-card .lead-submit:disabled { opacity: 0.65; cursor: wait; }
      .lead-card .skip-btn { background: transparent; border: 0; color: var(--text-muted); font-size: 12px; cursor: pointer; text-decoration: underline; padding: 4px; }

      .journey-card {
        align-self: stretch; background: #f4f8f7; background: color-mix(in srgb, var(--primary-color) 7%, white);
        border: 1px solid #dce8e6;
        border: 1px solid color-mix(in srgb, var(--primary-color) 16%, white);
        border-radius: 16px; padding: 16px; display: flex; flex-direction: column;
        gap: 12px; box-shadow: 0 4px 14px rgba(0,0,0,0.04); animation: msgIn 0.3s ease;
      }
      .journey-eyebrow { color: var(--primary-color); font-size: 11px; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }
      .journey-title { margin: 0; color: var(--text-main); font-size: 16px; line-height: 1.35; }
      .journey-actions { display: flex; flex-wrap: wrap; gap: 8px; }
      .journey-action {
        border: 1px solid color-mix(in srgb, var(--primary-color) 28%, white);
        background: white; color: var(--primary-color); border-radius: 999px;
        padding: 9px 13px; font-size: 13px; font-weight: 600; cursor: pointer;
      }
      .journey-action:hover { background: var(--primary-color); color: white; }
      .journey-action:disabled, .journey-confirm:disabled { opacity: 0.6; cursor: wait; }
      .journey-range-value { color: var(--primary-color); font-size: 14px; font-weight: 700; }
      .journey-range { width: 100%; accent-color: var(--primary-color); }
      .journey-range-labels { display: flex; justify-content: space-between; color: var(--text-muted); font-size: 11px; }
      .journey-confirm {
        width: 100%; border: 0; border-radius: 10px; padding: 12px;
        color: white; background: var(--primary-color); font-weight: 700; cursor: pointer;
      }

      @media (max-width: 768px) {
        .panel { right: 0; bottom: 0; width: 100vw; height: 100vh; max-height: 100vh; border-radius: 0; }
        .bubble { right: 20px; bottom: 20px; }
      }
    </style>
    <button class="bubble" aria-label="Open chat">${ICON_CHAT}</button>
    <section class="panel" aria-label="AI Chat">
      <div class="head">
        <div class="title-area">
          <div class="logo-fallback" style="display:none;">DB</div>
          <img class="logo" style="display:none;" alt="Logo" />
          <div class="info">
            <span class="title">DegreeBaba Assistant</span>
            <span class="status">AI Advisor online</span>
          </div>
        </div>
        <button class="close-btn" aria-label="Close chat">${ICON_CLOSE}</button>
      </div>
      <div class="msgs"></div>
      <div class="chips">
        <button class="chip">Check fees</button>
        <button class="chip">Eligibility</button>
        <button class="chip">Accreditations</button>
        <button class="chip">Ratings &amp; reviews</button>
        <button class="chip">Specializations</button>
        <button class="chip">Talk to counsellor</button>
      </div>
      <form class="composer">
        <div class="input-wrap">
          <input type="text" placeholder="Ask about fees, eligibility..." maxlength="4000" autocomplete="off" />
        </div>
        <button type="submit" class="send-btn" aria-label="Send message">${ICON_SEND}</button>
      </form>
    </section>
  `;

  // -------------------------------------------------------------------------
  // Element References
  // -------------------------------------------------------------------------
  const panel = root.querySelector(".panel");
  const bubble = root.querySelector(".bubble");
  const closeBtn = root.querySelector(".close-btn");
  const msgs = root.querySelector(".msgs");
  const form = root.querySelector(".composer");
  const input = root.querySelector("input");
  const sendBtn = root.querySelector(".send-btn");
  const chips = root.querySelector(".chips");
  const titleEl = root.querySelector(".title");
  const logoEl = root.querySelector(".logo");
  const logoFallback = root.querySelector(".logo-fallback");

  let oldestLoadedId = null;
  let historyFullyLoaded = false;
  let leadFormTriggered = false;
  let historyLoaded = false; // Prevents multiple fetches for history
  let isThinking = false;
  let thinkingInterval = null;
  let streamInFlight = false;
  let lastSubmittedText = "";
  let lastSubmittedAt = 0;
  const progressiveFormsShown = new Set();

  // -------------------------------------------------------------------------
  // Utility Functions
  // -------------------------------------------------------------------------
  function formatMarkdown(text) {
    const escaped = String(text || "")
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    const inline = (value) => value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    const output = [];
    let listOpen = false;
    escaped.split(/\r?\n/).forEach((line) => {
      const bullet = line.match(/^\s*(?:[-•])\s+(.+)$/);
      if (bullet) {
        if (!listOpen) { output.push('<ul>'); listOpen = true; }
        output.push(`<li>${inline(bullet[1])}</li>`);
        return;
      }
      if (listOpen) { output.push('</ul>'); listOpen = false; }
      const section = line.match(/^([A-Za-z][A-Za-z &/\-]{1,38}:)\s*(.*)$/);
      if (section) {
        output.push(`<span class="section-label">${section[1]}</span>${section[2] ? ` ${inline(section[2])}` : ''}`);
      } else {
        output.push(inline(line));
      }
    });
    if (listOpen) output.push('</ul>');
    return output.join('<br>').replace(/<br><ul>/g, '<ul>').replace(/<\/ul><br>/g, '</ul>');
  }

  function setComposerBusy(busy) {
    streamInFlight = busy;
    input.disabled = busy;
    sendBtn.disabled = busy;
    chips.querySelectorAll('.chip').forEach((chip) => { chip.disabled = busy; });
    msgs.querySelectorAll('.journey-action, .journey-confirm').forEach((button) => { button.disabled = busy; });
  }

  function isAtBottom() {
    return msgs.scrollHeight - msgs.scrollTop - msgs.clientHeight < 60;
  }

  function scrollToBottom(force = false) {
    if (force || isAtBottom()) {
      requestAnimationFrame(() => { msgs.scrollTop = msgs.scrollHeight; });
    }
  }

  function shouldHideWidget() {
    if (settings.show_on_desktop === false && !isMobile) return true;
    if (settings.show_on_mobile === false && isMobile) return true;
    return false;
  }

  function applyVisibility() {
    if (shouldHideWidget()) {
      bubble.classList.add("hidden");
      panel.classList.remove("open");
    } else {
      bubble.classList.remove("hidden");
    }
  }

  function applyConfig() {
    host.style.setProperty("--primary-color", settings.primary_color);
    titleEl.textContent = settings.widget_title;
    
    if (settings.logo_url) {
      logoEl.src = settings.logo_url;
      logoEl.style.display = "block";
    } else {
      const initials = settings.widget_title.split(' ').map(w => w[0]).slice(0, 2).join('');
      logoFallback.textContent = initials;
      logoFallback.style.display = "flex";
    }
  }

  function addMessage(text, role, isHtml = false) {
    const node = document.createElement("div");
    node.className = `msg ${role}`;
    node.innerHTML = isHtml ? formatMarkdown(text) : text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
    msgs.appendChild(node);
    scrollToBottom(true);
    return node;
  }

  function makeLoadMoreBtn() {
    const btn = document.createElement("button");
    btn.className = "load-more";
    btn.textContent = "Load earlier messages";
    btn.addEventListener("click", loadMoreHistory);
    return btn;
  }

  function prependHistoryMessages(messages, hasMore) {
    const fragment = document.createDocumentFragment();
    if (hasMore) fragment.appendChild(makeLoadMoreBtn());
    messages.forEach((msg) => {
      const node = document.createElement("div");
      node.className = `msg ${msg.role === "user" ? "user" : "bot"}`;
      node.innerHTML = formatMarkdown(msg.content);
      fragment.appendChild(node);
    });
    const divider = msgs.querySelector(".history-divider");
    if (divider) {
      msgs.insertBefore(fragment, divider);
    } else {
      msgs.insertBefore(fragment, msgs.firstChild);
    }
  }

  // -------------------------------------------------------------------------
  // Thinking Animation Logic
  // -------------------------------------------------------------------------
  function showThinkingBubble() {
    if (isThinking) return;
    isThinking = true;

    const bubble = document.createElement("div");
    bubble.className = "thinking-bubble";
    bubble.innerHTML = `
      <div class="dots-container"><span></span><span></span><span></span></div>
      <div class="thinking-text">Thinking...</div>
    `;
    msgs.appendChild(bubble);
    scrollToBottom(true);

    // Cycle through contextual messages
    const texts = ["Thinking...", "Finding the best result for you...", "Just a moment..."];
    let i = 0;
    
    thinkingInterval = setInterval(() => {
      i = (i + 1) % texts.length;
      const textEl = bubble.querySelector(".thinking-text");
      if (textEl) {
        textEl.style.opacity = 0;
        setTimeout(() => {
          textEl.textContent = texts[i];
          textEl.style.opacity = 1;
        }, 300);
      }
    }, 2200); // Change text every 2.2 seconds
  }

  function hideThinkingBubble() {
    if (!isThinking) return;
    isThinking = false;
    clearInterval(thinkingInterval);
    const bubble = msgs.querySelector(".thinking-bubble");
    if (bubble) bubble.remove();
  }

  // -------------------------------------------------------------------------
  // Data Loading & Chat Logic
  // -------------------------------------------------------------------------
  async function loadHistory() {
    if (historyLoaded) return;
    historyLoaded = true;

    try {
      const url = `${apiBase}/api/session/history?session_id=${encodeURIComponent(sessionId)}&site_key=${encodeURIComponent(siteKey)}&limit=20`;
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const messages = data.messages || [];
      
      if (messages.length === 0) {
        addMessage(settings.welcome_message, "bot", true);
        if (settings.lead_capture_enabled && settings.lead_trigger === "before_chat") {
          renderLeadForm();
        }
        return;
      }

      oldestLoadedId = data.oldest_id;
      historyFullyLoaded = !data.has_more;

      const divider = document.createElement("div");
      divider.className = "history-divider";
      divider.textContent = "Earlier conversation";
      msgs.appendChild(divider);

      prependHistoryMessages(messages, data.has_more);
      scrollToBottom(true);
    } catch (_) {}
  }

  async function loadMoreHistory() {
    if (!oldestLoadedId || historyFullyLoaded) return;
    const existingBtn = msgs.querySelector(".load-more");
    if (existingBtn) existingBtn.remove();
    try {
      const url = `${apiBase}/api/session/history?session_id=${encodeURIComponent(sessionId)}&site_key=${encodeURIComponent(siteKey)}&limit=20&before_id=${oldestLoadedId}`;
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const messages = data.messages || [];
      if (messages.length === 0) { historyFullyLoaded = true; return; }
      oldestLoadedId = data.oldest_id;
      historyFullyLoaded = !data.has_more;
      prependHistoryMessages(messages, data.has_more);
    } catch (_) {}
  }

  function renderLeadForm(courseInterest) {
    if (!settings.lead_capture_enabled || leadFormTriggered) return;
    leadFormTriggered = true;
    
    const box = document.createElement("form");
    box.className = "lead-card";
    
    let inputsHtml = "";
    if (settings.capture_name) inputsHtml += `<input name="name" placeholder="Full Name" required style="margin-bottom: 8px;" />`;
    if (settings.capture_phone) inputsHtml += `<input name="phone" placeholder="Phone Number" required style="margin-bottom: 8px;" />`;
    if (settings.capture_email) inputsHtml += `<input name="email" type="email" placeholder="Email Address" style="margin-bottom: 8px;" />`;

    box.innerHTML = `
      <h4>${settings.lead_form_title}</h4>
      <p>${settings.lead_form_description}</p>
      ${inputsHtml}
      <button type="submit" class="lead-submit">Request Callback</button>
      <button type="button" class="skip-btn">No thanks, maybe later</button>
    `;

    box.querySelector(".skip-btn").addEventListener("click", () => box.remove());
    box.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(box).entries());
      box.innerHTML = `<p style="text-align: center; color: var(--primary-color); font-weight: 500; padding: 10px 0;">✓ Thanks! A counsellor will reach out to you shortly.</p>`;
      await playSound();
      
      await fetch(`${apiBase}/webhook/lead`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId, site_key: siteKey, course_interest: courseInterest || "",
          name: data.name || "Anonymous", phone: data.phone || "0000000000", email: data.email || null
        })
      });
      
      setTimeout(() => box.remove(), 3000);
    });
    
    msgs.appendChild(box);
    scrollToBottom(true);
  }

  function renderProgressiveLeadField(field, force = false) {
    if (force) progressiveFormsShown.delete(field);
    if (!settings.lead_capture_enabled || progressiveFormsShown.has(field)) return;
    progressiveFormsShown.add(field);
    const copy = {
      name: { title: "Optional: what should we call you?", placeholder: "Your name", type: "text" },
      phone: { title: "Optional: share a callback number", placeholder: "Phone number", type: "tel" },
      email: { title: "Optional: save these options by email", placeholder: "Email address", type: "email" }
    }[field];
    if (!copy) return;

    const box = document.createElement("form");
    box.className = "lead-card progressive-lead-card";
    box.innerHTML = `
      <h4>${copy.title}</h4>
      <p>You can skip this and continue chatting.</p>
      <input name="value" type="${copy.type}" placeholder="${copy.placeholder}" required />
      <button type="submit" class="lead-submit">Save</button>
      <button type="button" class="skip-btn">Skip for now</button>
    `;
    let isSaving = false;
    box.querySelector(".skip-btn").addEventListener("click", () => box.remove());
    box.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (isSaving) return;
      const value = String(new FormData(box).get("value") || "").trim();
      if (!value) return;
      const submitButton = box.querySelector(".lead-submit");
      isSaving = true;
      submitButton.disabled = true;
      submitButton.textContent = "Saving...";
      try {
        const response = await fetch(`${apiBase}/webhook/lead/progressive`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, site_key: siteKey, field, value })
        });
        if (!response.ok) throw new Error("lead field was not saved");
        const result = await response.json();
        box.dataset.nextField = result.next_field || "";
      } catch (_) {
        const hint = box.querySelector("p");
        if (hint) hint.textContent = "That value doesn't look valid yet. Please check it or skip for now.";
        isSaving = false;
        submitButton.disabled = false;
        submitButton.textContent = "Save";
        return;
      }
      box.innerHTML = `<p style="text-align:center;color:var(--primary-color);font-weight:500;">✓ Saved — you can keep chatting.</p>`;
      const nextField = box.dataset.nextField;
      setTimeout(() => {
        box.remove();
        if (nextField) renderProgressiveLeadField(nextField);
      }, 900);
    });
    msgs.appendChild(box);
    scrollToBottom(true);
  }

  function formatCurrency(value, unit = "₹") {
    return `${unit}${Number(value || 0).toLocaleString("en-IN")}`;
  }

  function renderUICards(cards) {
    (cards || []).forEach((card) => {
      if (!card || !card.type) return;
      const node = document.createElement("section");
      node.className = "journey-card";

      if (card.eyebrow) {
        const eyebrow = document.createElement("div");
        eyebrow.className = "journey-eyebrow";
        eyebrow.textContent = card.eyebrow;
        node.appendChild(eyebrow);
      }
      const title = document.createElement("h4");
      title.className = "journey-title";
      title.textContent = card.title || "Continue";
      node.appendChild(title);

      if (card.type === "range") {
        const value = document.createElement("div");
        value.className = "journey-range-value";
        const range = document.createElement("input");
        range.className = "journey-range";
        range.type = "range";
        range.min = String(card.min || 0);
        range.max = String(card.max || 500000);
        range.step = String(card.step || 25000);
        range.value = String(card.value || card.min || 0);
        value.textContent = formatCurrency(range.value, card.unit);
        range.addEventListener("input", () => { value.textContent = formatCurrency(range.value, card.unit); });

        const labels = document.createElement("div");
        labels.className = "journey-range-labels";
        const minLabel = document.createElement("span");
        minLabel.textContent = formatCurrency(range.min, card.unit);
        const maxLabel = document.createElement("span");
        maxLabel.textContent = formatCurrency(range.max, card.unit);
        labels.append(minLabel, maxLabel);

        const confirm = document.createElement("button");
        confirm.className = "journey-confirm";
        confirm.type = "button";
        confirm.textContent = card.submit_label || "Confirm selection";
        confirm.addEventListener("click", () => {
          confirm.disabled = true;
          send(`${card.unit || "₹"}${range.value}`);
        });
        node.append(value, range, labels, confirm);
      } else {
        const actions = document.createElement("div");
        actions.className = "journey-actions";
        (card.actions || []).forEach((action) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "journey-action";
          button.textContent = action.label;
          button.addEventListener("click", () => send(action.message || action.label));
          actions.appendChild(button);
        });
        node.appendChild(actions);
      }
      msgs.appendChild(node);
    });
    scrollToBottom(true);
  }

  async function send(text) {
    const message = text.trim();
    const now = Date.now();
    if (!message || streamInFlight) return;
    if (message === lastSubmittedText && now - lastSubmittedAt < 1500) return;
    lastSubmittedText = message;
    lastSubmittedAt = now;
    setComposerBusy(true);
    addMessage(message, "user");
    input.value = "";

    const bot = document.createElement("div");
    bot.className = "msg bot";
    bot.style.display = "none";
    msgs.appendChild(bot);

    showThinkingBubble();

    try {
      const response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, site_key: siteKey, message, page_university_slug: pageSlug })
      });

      if (!response.ok) {
        hideThinkingBubble();
        bot.style.display = "";
        if (response.status === 403) bot.textContent = "Your access has been restricted due to suspicious activity.";
        else if (response.status === 429) bot.textContent = "Too many requests. Please slow down and try again.";
        else bot.textContent = "I'm temporarily unavailable. Please try again.";
        scrollToBottom();
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let rawText = "";
      let firstToken = true;

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop();
        
        for (const event of events) {
          const dataLine = event.split("\n").find((line) => line.startsWith("data: "));
          const eventLine = event.split("\n").find((line) => line.startsWith("event: "));
          if (!dataLine) continue;
          const data = JSON.parse(dataLine.slice(6));
          const eventType = eventLine ? eventLine.slice(7).trim() : "token";
          
          if (eventType === "final") {
            if (data.quick_replies && data.quick_replies.length) {
              chips.innerHTML = "";
              data.quick_replies.forEach((r) => {
                const chip = document.createElement("button");
                chip.className = "chip";
                chip.textContent = r;
                chips.appendChild(chip);
              });
            }
            if (data.ui_cards && data.ui_cards.length) renderUICards(data.ui_cards);
            if (data.progressive_lead_field) renderProgressiveLeadField(data.progressive_lead_field, data.route === "contact");
            if (data.lead_ask && settings.lead_trigger !== "before_chat") renderLeadForm(message);
            bot.innerHTML = formatMarkdown(rawText);
          } else if (eventType === "replace") {
            if (firstToken) {
              hideThinkingBubble();
              bot.style.display = "";
              firstToken = false;
            }
            rawText = data.text || "";
            bot.innerHTML = formatMarkdown(rawText);
            scrollToBottom();
          } else {
            if (firstToken) {
              hideThinkingBubble();
              bot.style.display = "";
              firstToken = false;
            }
            rawText += data.text || "";
            bot.innerHTML = formatMarkdown(rawText) + '<span class="stream-cursor"></span>';
            scrollToBottom();
          }
        }
      }
    } catch (err) {
      hideThinkingBubble();
      bot.style.display = "";
      bot.textContent = "I'm temporarily unavailable. Please try again.";
      scrollToBottom();
    } finally {
      setComposerBusy(false);
      input.focus();
    }
  }

  // -------------------------------------------------------------------------
  // Event Listeners
  // -------------------------------------------------------------------------
  bubble.addEventListener("click", () => {
    panel.classList.add("open");
    bubble.classList.add("interacted"); // Stop pulse animation
    if (!historyLoaded) loadHistory();  // LAZY LOAD: Only load chat when opened
    setTimeout(() => input.focus(), 300);
  });

  closeBtn.addEventListener("click", () => {
    panel.classList.remove("open");
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(input.value);
  });

  chips.addEventListener("click", (event) => {
    if (!streamInFlight && event.target.matches(".chip")) send(event.target.textContent);
  });

  // -------------------------------------------------------------------------
  // Initialization
  // -------------------------------------------------------------------------
  async function loadConfig() {
    try {
      const res = await fetch(`${apiBase}/widget/config`);
      if (res.ok) {
        const data = await res.json();
        if (data.branding) Object.assign(settings, data.branding);
        if (data.behavior) Object.assign(settings, data.behavior);
        if (data.lead_capture) Object.assign(settings, data.lead_capture);
      }
    } catch (_) {}
  }

  loadConfig().then(() => {
    applyConfig();
    applyVisibility();
    // Removed loadHistory() from here to speed up initial page load!
  });
})();
