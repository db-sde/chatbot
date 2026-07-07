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
  // Default widget configuration. Loaded dynamically from /widget/config
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
  // Device detection
  // -------------------------------------------------------------------------
  const isTouch = "ontouchstart" in window || navigator.maxTouchPoints > 0;
  const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent) || (isTouch && window.innerWidth <= 768);

  // -------------------------------------------------------------------------
  // Sound notification
  // -------------------------------------------------------------------------
  const AUDIO_SRC = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAAAAAA==";
  const audioCtx = typeof AudioContext !== "undefined" ? new AudioContext() : null;

  async function playSound() {
    try {
      if (audioCtx && audioCtx.state === "suspended") await audioCtx.resume();
      const audio = new Audio(AUDIO_SRC);
      audio.volume = 0.4;
      await audio.play();
    } catch (_) {}
  }

  // -------------------------------------------------------------------------
  // DOM setup
  // -------------------------------------------------------------------------
  const host = document.createElement("div");
  host.id = "degreebaba-ai-widget";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
    <style>
      :host {
        --primary-color: #135d66;
        all: initial;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .bubble { position: fixed; right: 20px; bottom: 20px; width: 58px; height: 58px; border-radius: 50%; border: 0; background: var(--primary-color); color: white; box-shadow: 0 12px 30px rgba(0,0,0,.22); cursor: pointer; font-size: 24px; z-index: 2147483647; display: flex; align-items: center; justify-content: center; transition: transform 0.2s ease; }
      .bubble:hover { transform: scale(1.05); }
      .bubble.hidden { display: none !important; }
      .panel { position: fixed; right: 20px; bottom: 90px; width: min(380px, calc(100vw - 32px)); height: min(620px, calc(100vh - 120px)); background: #ffffff; color: #172326; border: 1px solid #d7e1df; box-shadow: 0 18px 60px rgba(0,0,0,.22); display: none; flex-direction: column; z-index: 2147483647; border-radius: 12px; overflow: hidden; }
      .panel.open { display: flex; }
      .head { padding: 14px 16px; background: var(--primary-color); color: white; display: flex; justify-content: space-between; align-items: center; font-weight: 700; }
      .head .title-area { display: flex; align-items: center; gap: 8px; }
      .head .logo { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; background: white; }
      .head .status { font-size: 11px; font-weight: 500; opacity: 0.9; margin-top: 2px; }
      .close { border: 0; background: transparent; color: white; font-size: 22px; cursor: pointer; }
      .msgs { flex: 1; overflow: auto; padding: 14px; display: flex; flex-direction: column; gap: 10px; background: #f7faf9; }
      .msg { max-width: 84%; padding: 10px 12px; border-radius: 8px; line-height: 1.38; font-size: 14px; white-space: pre-wrap; overflow-wrap: anywhere; }
      .user { align-self: flex-end; background: var(--primary-color); color: white; }
      .bot { align-self: flex-start; background: white; border: 1px solid #d7e1df; color: #172326; }
      .history-divider { align-self: stretch; text-align: center; font-size: 11px; color: #9ca3af; padding: 4px 0 8px; display: flex; align-items: center; gap: 8px; }
      .history-divider::before, .history-divider::after { content: ""; flex: 1; height: 1px; background: #d7e1df; }
      .load-more { align-self: center; background: none; border: 1px solid #b9cbc8; color: var(--primary-color); padding: 5px 14px; border-radius: 999px; cursor: pointer; font-size: 12px; margin-bottom: 4px; }
      .load-more:hover { background: #eef4f3; }
      .chips { display: flex; gap: 8px; flex-wrap: wrap; padding: 10px 14px; border-top: 1px solid #e7eeee; background: white; }
      .chip { border: 1px solid #b9cbc8; background: white; color: var(--primary-color); padding: 7px 10px; border-radius: 999px; cursor: pointer; font-size: 13px; }
      .composer { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e7eeee; background: white; align-items: center; }
      input { flex: 1; border: 1px solid #b9cbc8; border-radius: 6px; padding: 10px; font: inherit; min-width: 0; }
      .send, .lead button { border: 0; border-radius: 6px; background: var(--primary-color); color: white; padding: 10px 12px; cursor: pointer; font: inherit; }
      .lead { display: grid; gap: 8px; padding: 12px; border: 1px solid #d7e1df; background: white; border-radius: 8px; }
      .lead input { width: 100%; box-sizing: border-box; }
      .lead .skip { background: #eef4f3; color: var(--primary-color); border: 0; border-radius: 6px; padding: 8px; cursor: pointer; font-size: 12px; }
      .typing { align-self: flex-start; display: flex; gap: 5px; align-items: center; padding: 10px 14px; background: white; border: 1px solid #d7e1df; border-radius: 8px; }
      .typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--primary-color); opacity: .4; animation: blink 1.2s infinite; }
      .typing span:nth-child(2) { animation-delay: .2s; }
      .typing span:nth-child(3) { animation-delay: .4s; }
      @keyframes blink { 0%,80%,100% { opacity:.4; transform:scale(1); } 40% { opacity:1; transform:scale(1.25); } }
      @media (max-width: 768px) {
        .panel { right: 10px; bottom: 80px; width: calc(100vw - 20px); height: calc(100vh - 100px); }
        .bubble { right: 10px; bottom: 10px; }
      }
    </style>
    <button class="bubble" aria-label="Open chat">💬</button>
    <section class="panel" aria-label="AI Chat">
      <div class="head">
        <div class="title-area">
          <img class="logo" style="display:none;" />
          <div>
            <span id="db-title">DegreeBaba Assistant</span>
            <div class="status">AI Advisor online</div>
          </div>
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
  const titleEl = root.querySelector("#db-title");
  const logoEl = root.querySelector(".logo");

  let oldestLoadedId = null;
  let historyFullyLoaded = false;
  let isOpen = false;
  let conversationEnded = false;
  let leadFormTriggered = false;

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
    // Apply styling properties
    host.style.setProperty("--primary-color", settings.primary_color);
    
    // Apply texts
    titleEl.textContent = settings.widget_title;
    if (settings.logo_url) {
      logoEl.src = settings.logo_url;
      logoEl.style.display = "block";
    } else {
      logoEl.style.display = "none";
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
      if (messages.length === 0) {
        // Welcome message on new session
        addMessage(settings.welcome_message, "bot");
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
    if (!settings.lead_capture_enabled || leadFormTriggered) return;
    leadFormTriggered = true;
    
    const box = document.createElement("form");
    box.className = "lead";
    
    let inputsHtml = "";
    if (settings.capture_name) {
      inputsHtml += `<input name="name" placeholder="Name" required style="padding: 8px; border: 1px solid #b9cbc8; border-radius: 4px;" />`;
    }
    if (settings.capture_phone) {
      inputsHtml += `<input name="phone" placeholder="Phone" required style="padding: 8px; border: 1px solid #b9cbc8; border-radius: 4px;" />`;
    }
    if (settings.capture_email) {
      inputsHtml += `<input name="email" type="email" placeholder="Email" style="padding: 8px; border: 1px solid #b9cbc8; border-radius: 4px;" />`;
    }

    box.innerHTML = `
      <div style="font-size: 13px; font-weight: bold; color: #172326;">${settings.lead_form_title}</div>
      <div style="font-size: 11px; color: #6b7d7a; margin-bottom: 4px;">${settings.lead_form_description}</div>
      ${inputsHtml}
      <button class="send" style="padding: 8px 12px; margin-top: 4px;">Submit</button>
      <button class="skip" type="button">No thanks</button>
    `;

    box.querySelector(".skip").addEventListener("click", () => box.remove());
    box.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(box).entries());
      await fetch(`${apiBase}/webhook/lead`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          site_key: siteKey,
          course_interest: courseInterest || "",
          name: data.name || "Anonymous",
          phone: data.phone || "0000000000",
          email: data.email || null
        })
      });
      box.innerHTML = `<span style="font-size: 12px; color: #6b7d7a;">Thanks. A counsellor can follow up with you.</span>`;
      await playSound();
    });
    msgs.appendChild(box);
    msgs.scrollTop = msgs.scrollHeight;
  }



  async function send(text) {
    const message = text.trim();
    if (!message) return;
    addMessage(message, "user");
    input.value = "";

    const bot = addMessage("", "bot");
    bot.style.display = "none";

    const typing = document.createElement("div");
    typing.className = "typing";
    typing.innerHTML = "<span></span><span></span><span></span>";
    msgs.appendChild(typing);
    msgs.scrollTop = msgs.scrollHeight;

    try {
      const response = await fetch(`${apiBase}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, site_key: siteKey, message, page_university_slug: pageSlug })
      });
      if (!response.ok) {
        typing.remove();
        bot.style.display = "";
        if (response.status === 403) {
          bot.textContent = "Your access has been restricted due to suspicious activity.";
        } else if (response.status === 429) {
          bot.textContent = "Too many requests. Please slow down and try again in a moment.";
        } else {
          bot.textContent = "I'm temporarily unavailable. Please try again.";
        }
        msgs.scrollTop = msgs.scrollHeight;
        return;
      }
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
            if (data.lead_ask && settings.lead_trigger !== "before_chat") renderLeadForm(message);
          } else {
            if (firstToken) {
              typing.remove();
              bot.style.display = "";
              firstToken = false;
            }
            bot.textContent += data.text || "";
            msgs.scrollTop = msgs.scrollHeight;
          }
        }
      }

    } catch (err) {
      typing.remove();
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
  });
  close.addEventListener("click", () => {
    panel.classList.remove("open");
    isOpen = false;
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(input.value);
  });
  chips.addEventListener("click", (event) => {
    if (event.target.matches(".chip")) send(event.target.textContent);
  });


  // -------------------------------------------------------------------------
  // Fetch config and start
  // -------------------------------------------------------------------------
  async function loadConfig() {
    try {
      const res = await fetch(`${apiBase}/widget/config`);
      if (res.ok) {
        const data = await res.json();
        
        // Merge branding
        if (data.branding) {
          Object.assign(settings, data.branding);
        }
        // Merge behavior
        if (data.behavior) {
          Object.assign(settings, data.behavior);
        }
        // Merge lead capture
        if (data.lead_capture) {
          Object.assign(settings, data.lead_capture);
        }
      }
    } catch (_) {}
  }

  loadConfig().then(() => {
    applyConfig();
    applyVisibility();
    loadHistory();
  });
})();
