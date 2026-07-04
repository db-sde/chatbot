(function () {
  const script = document.currentScript;
  const siteKey = script && script.dataset.siteKey;
  const apiBase = script && script.dataset.apiBase;
  if (!siteKey || !apiBase) {
    console.error("DegreeBaba widget: data-site-key and data-api-base are required.");
    return;
  }
  const pageSlug = (script && script.dataset.universitySlug) || location.pathname.split("/").filter(Boolean).pop() || null;
  const storageKey = "degreebaba_ai_session_id";
  const sessionId = localStorage.getItem(storageKey) || crypto.randomUUID();
  localStorage.setItem(storageKey, sessionId);

  // -------------------------------------------------------------------------
  // Default widget configuration.  These values are used until the public
  // /public/widget-settings endpoint returns site-specific overrides.
  // -------------------------------------------------------------------------
  const DEFAULT_SETTINGS = {
    show_estimated_wait_time: true,
    sound_notifications: true,
    desktop_notifications: true,
    mobile_message_preview: true,
    agent_typing_indicator: true,
    visitor_typing_indicator: true,
    browser_tab_notifications: true,
    hide_when_offline: false,
    hide_on_desktop: false,
    hide_on_mobile: false,
    offline_if_no_agents: false,
    emoji_picker_enabled: true,
    file_upload_enabled: true,
    chat_rating_enabled: true,
    email_transcript_enabled: true,
  };

  const settings = { ...DEFAULT_SETTINGS };

  // -------------------------------------------------------------------------
  // Device detection
  // -------------------------------------------------------------------------
  const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (isTouch && window.innerWidth <= 768);

  // -------------------------------------------------------------------------
  // Sound notification — single base64 "pop" for new messages
  // -------------------------------------------------------------------------
  const AUDIO_SRC = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAAAAAA==";
  const audioCtx = typeof AudioContext !== "undefined" ? new AudioContext() : null;

  async function playSound() {
    if (!settings.sound_notifications) return;
    try {
      if (audioCtx && audioCtx.state === "suspended") await audioCtx.resume();
      const audio = new Audio(AUDIO_SRC);
      audio.volume = 0.4;
      await audio.play();
    } catch (_) {
      // Browsers block audio until user interaction; ignore.
    }
  }

  // -------------------------------------------------------------------------
  // Desktop / browser-tab notifications
  // -------------------------------------------------------------------------
  async function requestDesktopPermission() {
    if (!settings.desktop_notifications || !("Notification" in window)) return false;
    if (Notification.permission === "granted") return true;
    if (Notification.permission === "default") {
      const permission = await Notification.requestPermission();
      return permission === "granted";
    }
    return false;
  }

  function showDesktopNotification(title, body) {
    if (!settings.desktop_notifications || !("Notification" in window)) return;
    if (document.hidden && Notification.permission === "granted") {
      try {
        new Notification(title, { body, icon: "", tag: "degreebaba-msg" });
      } catch (_) {}
    }
  }

  // -------------------------------------------------------------------------
  // Browser tab title notifications
  // -------------------------------------------------------------------------
  let originalTitle = document.title;
  let unreadCount = 0;
  let titleFlashInterval = null;

  function startTitleFlash() {
    if (!settings.browser_tab_notifications || titleFlashInterval) return;
    titleFlashInterval = setInterval(() => {
      document.title = document.title === originalTitle ? `(${unreadCount}) New message — ${originalTitle}` : originalTitle;
    }, 1200);
  }

  function stopTitleFlash() {
    if (titleFlashInterval) {
      clearInterval(titleFlashInterval);
      titleFlashInterval = null;
    }
    document.title = originalTitle;
    unreadCount = 0;
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) stopTitleFlash();
  });

  // -------------------------------------------------------------------------
  // Typing indicators
  // -------------------------------------------------------------------------
  let typingTimeout = null;
  let lastTypingSent = 0;

  function sendTypingEvent() {
    if (!settings.visitor_typing_indicator) return;
    const now = Date.now();
    if (now - lastTypingSent < 1200) return;
    lastTypingSent = now;
    // Future endpoint: notify admin dashboard that visitor is typing.
    // fetch(`${apiBase}/public/typing`, { method: "POST", ... })
  }

  function clearVisitorTyping() {
    if (typingTimeout) clearTimeout(typingTimeout);
  }

  // -------------------------------------------------------------------------
  // DOM
  // -------------------------------------------------------------------------
  const host = document.createElement("div");
  host.id = "degreebaba-ai-widget";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
    <style>
      :host { all: initial; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      .bubble { position: fixed; right: 20px; bottom: 20px; width: 58px; height: 58px; border-radius: 50%; border: 0; background: #135d66; color: white; box-shadow: 0 12px 30px rgba(0,0,0,.22); cursor: pointer; font-size: 24px; z-index: 2147483647; display: flex; align-items: center; justify-content: center; }
      .bubble.hidden { display: none !important; }
      .panel { position: fixed; right: 20px; bottom: 90px; width: min(380px, calc(100vw - 32px)); height: min(620px, calc(100vh - 120px)); background: #ffffff; color: #172326; border: 1px solid #d7e1df; box-shadow: 0 18px 60px rgba(0,0,0,.22); display: none; flex-direction: column; z-index: 2147483647; border-radius: 8px; overflow: hidden; }
      .panel.open { display: flex; }
      .head { padding: 14px 16px; background: #135d66; color: white; display: flex; justify-content: space-between; align-items: center; font-weight: 700; }
      .head .status { font-size: 11px; font-weight: 500; opacity: 0.9; margin-top: 2px; }
      .close { border: 0; background: transparent; color: white; font-size: 22px; cursor: pointer; }
      .msgs { flex: 1; overflow: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; background: #f7faf9; }
      .msg { max-width: 84%; padding: 10px 12px; border-radius: 8px; line-height: 1.38; font-size: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
      .user { align-self: flex-end; background: #135d66; color: white; }
      .bot { align-self: flex-start; background: white; border: 1px solid #d7e1df; color: #172326; }
      .history-divider { align-self: stretch; text-align: center; font-size: 11px; color: #9ca3af; padding: 4px 0 8px; display: flex; align-items: center; gap: 8px; }
      .history-divider::before, .history-divider::after { content: ""; flex: 1; height: 1px; background: #d7e1df; }
      .load-more { align-self: center; background: none; border: 1px solid #b9cbc8; color: #135d66; padding: 5px 14px; border-radius: 999px; cursor: pointer; font-size: 12px; margin-bottom: 4px; }
      .load-more:hover { background: #eef4f3; }
      .chips { display: flex; gap: 8px; flex-wrap: wrap; padding: 10px 14px; border-top: 1px solid #e7eeee; background: white; }
      .chip { border: 1px solid #b9cbc8; background: white; color: #135d66; padding: 7px 10px; border-radius: 999px; cursor: pointer; font-size: 13px; }
      .composer { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e7eeee; background: white; align-items: center; }
      .composer-actions { display: flex; gap: 4px; }
      .composer-btn { border: 0; background: transparent; color: #6b7d7a; cursor: pointer; font-size: 18px; padding: 6px; border-radius: 6px; }
      .composer-btn:hover { background: #eef4f3; }
      .composer-btn.hidden { display: none; }
      input { flex: 1; border: 1px solid #b9cbc8; border-radius: 6px; padding: 10px; font: inherit; min-width: 0; }
      .send, .lead button { border: 0; border-radius: 6px; background: #135d66; color: white; padding: 10px 12px; cursor: pointer; font: inherit; }
      .lead { display: grid; gap: 8px; padding: 10px; border: 1px solid #d7e1df; background: white; border-radius: 8px; }
      .lead .skip { background: #eef4f3; color: #135d66; }
      .typing { align-self: flex-start; display: flex; gap: 5px; align-items: center; padding: 10px 14px; background: white; border: 1px solid #d7e1df; border-radius: 8px; }
      .typing span { width: 7px; height: 7px; border-radius: 50%; background: #135d66; opacity: .4; animation: blink 1.2s infinite; }
      .typing span:nth-child(2) { animation-delay: .2s; }
      .typing span:nth-child(3) { animation-delay: .4s; }
      @keyframes blink { 0%,80%,100% { opacity:.4; transform:scale(1); } 40% { opacity:1; transform:scale(1.25); } }
      .offline-badge { align-self: center; font-size: 11px; color: #9ca3af; padding: 4px 0; }
      .rating { align-self: flex-start; display: flex; gap: 8px; padding: 8px 0; }
      .rating button { border: 1px solid #b9cbc8; background: white; border-radius: 999px; padding: 6px 12px; cursor: pointer; font-size: 12px; }
      .rating button:hover { background: #eef4f3; }
      @media (max-width: 768px) {
        .panel { right: 10px; bottom: 80px; width: calc(100vw - 20px); height: calc(100vh - 100px); }
        .bubble { right: 10px; bottom: 10px; }
      }
    </style>
    <button class="bubble" aria-label="Open DegreeBaba chat">💬</button>
    <section class="panel" aria-label="DegreeBaba AI Chat">
      <div class="head">
        <div>
          <span>DegreeBaba AI</span>
          <div class="status" id="db-status">Online</div>
        </div>
        <button class="close" aria-label="Close">×</button>
      </div>
      <div class="msgs"></div>
      <div class="chips">
        <button class="chip">Check fees</button>
        <button class="chip">Eligibility</button>
        <button class="chip">Talk to counsellor</button>
      </div>
      <form class="composer">
        <div class="composer-actions">
          <button type="button" class="composer-btn emoji-btn" title="Emoji">😊</button>
          <button type="button" class="composer-btn upload-btn" title="Upload">📎</button>
        </div>
        <input placeholder="Ask about fees, eligibility, admissions..." maxlength="4000" />
        <button class="send">Send</button>
      </form>
    </section>
  `;

  const panel = root.querySelector(".panel");
  const bubble = root.querySelector(".bubble");
  const close = root.querySelector(".close");
  const msgs = root.querySelector(".msgs");
  const form = root.querySelector(".composer");
  const input = root.querySelector("input");
  const chips = root.querySelector(".chips");
  const emojiBtn = root.querySelector(".emoji-btn");
  const uploadBtn = root.querySelector(".upload-btn");
  const statusEl = root.querySelector("#db-status");

  // Pagination state for history restoration
  let oldestLoadedId = null;
  let historyFullyLoaded = false;
  let isOpen = false;
  let conversationEnded = false;

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function shouldHideWidget() {
    if (settings.hide_on_desktop && !isMobile) return true;
    if (settings.hide_on_mobile && isMobile) return true;
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

  function applyComposerFeatures() {
    if (!settings.emoji_picker_enabled) emojiBtn.classList.add("hidden");
    else emojiBtn.classList.remove("hidden");

    if (!settings.file_upload_enabled) uploadBtn.classList.add("hidden");
    else uploadBtn.classList.remove("hidden");

    if (settings.offline_if_no_agents) {
      setStatus("Offline");
    } else {
      setStatus(settings.show_estimated_wait_time ? "Typically replies instantly" : "AI Advisor online");
    }
  }

  function addMessage(text, role) {
    const node = document.createElement("div");
    node.className = `msg ${role}`;
    node.textContent = text;
    msgs.appendChild(node);
    msgs.scrollTop = msgs.scrollHeight;
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
      node.textContent = msg.content;
      fragment.appendChild(node);
    });
    msgs.insertBefore(fragment, msgs.firstChild);
  }

  async function loadHistory() {
    try {
      const url =
        `${apiBase}/api/session/history` +
        `?session_id=${encodeURIComponent(sessionId)}` +
        `&site_key=${encodeURIComponent(siteKey)}` +
        `&limit=20`;
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const messages = data.messages || [];
      if (messages.length === 0) return;

      oldestLoadedId = data.oldest_id;
      historyFullyLoaded = !data.has_more;

      const divider = document.createElement("div");
      divider.className = "history-divider";
      divider.textContent = "Earlier conversation";
      msgs.appendChild(divider);

      prependHistoryMessages(messages, data.has_more);
    } catch (_) {}
  }

  async function loadMoreHistory() {
    if (!oldestLoadedId || historyFullyLoaded) return;
    const existingBtn = msgs.querySelector(".load-more");
    if (existingBtn) existingBtn.remove();
    try {
      const url =
        `${apiBase}/api/session/history` +
        `?session_id=${encodeURIComponent(sessionId)}` +
        `&site_key=${encodeURIComponent(siteKey)}` +
        `&limit=20` +
        `&before_id=${oldestLoadedId}`;
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
    const box = document.createElement("form");
    box.className = "lead";
    box.innerHTML = `
      <input name="name" placeholder="Name" required />
      <input name="phone" placeholder="Phone" required />
      <input name="email" placeholder="Email (optional)" />
      <button>Request callback</button>
      <button class="skip" type="button">No thanks, just browsing</button>
    `;
    box.querySelector(".skip").addEventListener("click", () => box.remove());
    box.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(box).entries());
      await fetch(`${apiBase}/webhook/lead`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, site_key: siteKey, course_interest: courseInterest || "", ...data })
      });
      box.innerHTML = "Thanks. A counsellor can follow up with you.";
      await playSound();
    });
    msgs.appendChild(box);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function renderRating() {
    if (!settings.chat_rating_enabled || conversationEnded) return;
    conversationEnded = true;
    const node = document.createElement("div");
    node.className = "rating";
    node.innerHTML = `
      <button type="button" data-value="up">👍 Helpful</button>
      <button type="button" data-value="down">👎 Not Helpful</button>
    `;
    node.addEventListener("click", (e) => {
      const btn = e.target.closest("button");
      if (!btn) return;
      node.innerHTML = `<span style="font-size:12px;color:#6b7d7a;">Thanks for your feedback!</span>`;
    });
    msgs.appendChild(node);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function showAgentTyping() {
    if (!settings.agent_typing_indicator) return null;
    const node = document.createElement("div");
    node.className = "typing";
    node.innerHTML = "<span></span><span></span><span></span>";
    msgs.appendChild(node);
    msgs.scrollTop = msgs.scrollHeight;
    return node;
  }

  async function send(text) {
    const message = text.trim();
    if (!message) return;
    addMessage(message, "user");
    input.value = "";
    clearVisitorTyping();

    const typingNode = showAgentTyping();
    const bot = addMessage("", "bot");
    bot.style.display = "none";

    try {
      const response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, site_key: siteKey, message, page_university_slug: pageSlug })
      });
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
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
          if (eventLine && eventLine.includes("final")) {
            if (data.quick_replies && data.quick_replies.length) {
              chips.innerHTML = "";
              data.quick_replies.forEach((r) => {
                const chip = document.createElement("button");
                chip.className = "chip";
                chip.textContent = r;
                chips.appendChild(chip);
              });
            }
            if (data.lead_ask) renderLeadForm(message);
            if (settings.chat_rating_enabled) renderRating();
          } else {
            if (firstToken) {
              if (typingNode) typingNode.remove();
              bot.style.display = "";
              firstToken = false;
            }
            bot.textContent += data.text || "";
            msgs.scrollTop = msgs.scrollHeight;
          }
        }
      }
      if (firstToken && typingNode) typingNode.remove();

      if (!isOpen && settings.desktop_notifications) {
        showDesktopNotification("DegreeBaba AI", "New message received");
      }
      if (!isOpen && settings.browser_tab_notifications) {
        unreadCount += 1;
        startTitleFlash();
      }
      await playSound();
    } catch (err) {
      if (typingNode) typingNode.remove();
      bot.style.display = "";
      bot.textContent = "I'm temporarily unavailable. Please try again.";
    }
  }

  // -------------------------------------------------------------------------
  // Event listeners
  // -------------------------------------------------------------------------
  bubble.addEventListener("click", () => {
    panel.classList.add("open");
    isOpen = true;
    stopTitleFlash();
    requestDesktopPermission();
  });
  close.addEventListener("click", () => {
    panel.classList.remove("open");
    isOpen = false;
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(input.value);
  });
  input.addEventListener("input", () => {
    sendTypingEvent();
    clearVisitorTyping();
    typingTimeout = setTimeout(clearVisitorTyping, 1500);
  });
  chips.addEventListener("click", (event) => {
    if (event.target.matches(".chip")) send(event.target.textContent);
  });
  emojiBtn.addEventListener("click", () => {
    if (!settings.emoji_picker_enabled) return;
    input.value += "😊";
    input.focus();
  });
  uploadBtn.addEventListener("click", () => {
    if (!settings.file_upload_enabled) return;
    alert("File upload will be enabled in a future release.");
  });

  // -------------------------------------------------------------------------
  // Load runtime settings then bootstrap widget
  // -------------------------------------------------------------------------
  async function loadSettings() {
    try {
      const res = await fetch(`${apiBase}/public/widget-settings?site_key=${encodeURIComponent(siteKey)}`);
      if (res.ok) {
        const data = await res.json();
        Object.keys(DEFAULT_SETTINGS).forEach((key) => {
          if (typeof data[key] === "boolean") settings[key] = data[key];
        });
      }
    } catch (_) {
      // Network failures fall back to defaults.
    }
  }

  loadSettings().then(() => {
    applyVisibility();
    applyComposerFeatures();
    if (settings.hide_when_offline && settings.offline_if_no_agents) {
      bubble.classList.add("hidden");
    }
    loadHistory();
  });
})();
