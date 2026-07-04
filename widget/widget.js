(function () {
  const script = document.currentScript;
  const siteKey = script && script.dataset.siteKey ? script.dataset.siteKey : "degreebaba_dev";
  const apiBase = script && script.dataset.apiBase ? script.dataset.apiBase : "http://localhost:2323";
  const pageSlug = (script && script.dataset.universitySlug) || location.pathname.split("/").filter(Boolean).pop() || null;
  const storageKey = "degreebaba_ai_session_id";
  const sessionId = localStorage.getItem(storageKey) || crypto.randomUUID();
  localStorage.setItem(storageKey, sessionId);

  const host = document.createElement("div");
  host.id = "degreebaba-ai-widget";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
    <style>
      :host { all: initial; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      .bubble { position: fixed; right: 20px; bottom: 20px; width: 58px; height: 58px; border-radius: 50%; border: 0; background: #135d66; color: white; box-shadow: 0 12px 30px rgba(0,0,0,.22); cursor: pointer; font-size: 24px; z-index: 2147483647; }
      .panel { position: fixed; right: 20px; bottom: 90px; width: min(380px, calc(100vw - 32px)); height: min(620px, calc(100vh - 120px)); background: #ffffff; color: #172326; border: 1px solid #d7e1df; box-shadow: 0 18px 60px rgba(0,0,0,.22); display: none; flex-direction: column; z-index: 2147483647; border-radius: 8px; overflow: hidden; }
      .panel.open { display: flex; }
      .head { padding: 14px 16px; background: #135d66; color: white; display: flex; justify-content: space-between; align-items: center; font-weight: 700; }
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
      .composer { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #e7eeee; background: white; }
      input { flex: 1; border: 1px solid #b9cbc8; border-radius: 6px; padding: 10px; font: inherit; min-width: 0; }
      .send, .lead button { border: 0; border-radius: 6px; background: #135d66; color: white; padding: 10px 12px; cursor: pointer; font: inherit; }
      .lead { display: grid; gap: 8px; padding: 10px; border: 1px solid #d7e1df; background: white; border-radius: 8px; }
      .lead .skip { background: #eef4f3; color: #135d66; }
      .typing { align-self: flex-start; display: flex; gap: 5px; align-items: center; padding: 10px 14px; background: white; border: 1px solid #d7e1df; border-radius: 8px; }
      .typing span { width: 7px; height: 7px; border-radius: 50%; background: #135d66; opacity: .4; animation: blink 1.2s infinite; }
      .typing span:nth-child(2) { animation-delay: .2s; }
      .typing span:nth-child(3) { animation-delay: .4s; }
      @keyframes blink { 0%,80%,100% { opacity:.4; transform:scale(1); } 40% { opacity:1; transform:scale(1.25); } }
    </style>
    <button class="bubble" aria-label="Open DegreeBaba chat">💬</button>
    <section class="panel" aria-label="DegreeBaba AI Chat">
      <div class="head"><span>DegreeBaba AI</span><button class="close" aria-label="Close">×</button></div>
      <div class="msgs"></div>
      <div class="chips">
        <button class="chip">Check fees</button>
        <button class="chip">Eligibility</button>
        <button class="chip">Talk to counsellor</button>
      </div>
      <form class="composer"><input placeholder="Ask about fees, eligibility, admissions..." maxlength="4000" /><button class="send">Send</button></form>
    </section>
  `;

  const panel = root.querySelector(".panel");
  const bubble = root.querySelector(".bubble");
  const close = root.querySelector(".close");
  const msgs = root.querySelector(".msgs");
  const form = root.querySelector(".composer");
  const input = root.querySelector("input");
  const chips = root.querySelector(".chips");

  // Pagination state for history restoration
  let oldestLoadedId = null;
  let historyFullyLoaded = false;

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

  // Prepend historical messages above existing DOM content.
  // hasMore=true adds a "Load earlier messages" button at the very top.
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
      if (!res.ok) return; // silently skip — don't block fresh sessions
      const data = await res.json();
      const messages = data.messages || [];
      if (messages.length === 0) return;

      oldestLoadedId = data.oldest_id;
      historyFullyLoaded = !data.has_more;

      // Insert the "Earlier conversation" divider first (at current bottom of msgs)
      const divider = document.createElement("div");
      divider.className = "history-divider";
      divider.textContent = "Earlier conversation";
      msgs.appendChild(divider);

      // Then prepend the actual history above the divider
      prependHistoryMessages(messages, data.has_more);
    } catch (_) {
      // Network errors must never crash the widget
    }
  }

  async function loadMoreHistory() {
    if (!oldestLoadedId || historyFullyLoaded) return;
    // Remove the existing "Load earlier messages" button before fetching
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
    });
    msgs.appendChild(box);
    msgs.scrollTop = msgs.scrollHeight;
  }

  async function send(text) {
    const message = text.trim();
    if (!message) return;
    addMessage(message, "user");
    input.value = "";

    const typingNode = document.createElement("div");
    typingNode.className = "typing";
    typingNode.innerHTML = "<span></span><span></span><span></span>";
    msgs.appendChild(typingNode);
    msgs.scrollTop = msgs.scrollHeight;

    const bot = addMessage("", "bot");
    bot.style.display = "none";

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
        } else {
          if (firstToken) {
            typingNode.remove();
            bot.style.display = "";
            firstToken = false;
          }
          bot.textContent += data.text || "";
          msgs.scrollTop = msgs.scrollHeight;
        }
      }
    }
    if (firstToken) typingNode.remove();
  }

  bubble.addEventListener("click", () => panel.classList.add("open"));
  close.addEventListener("click", () => panel.classList.remove("open"));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(input.value);
  });
  chips.addEventListener("click", (event) => {
    if (event.target.matches(".chip")) send(event.target.textContent);
  });

  // Load history after the widget mounts — non-blocking, silently fails on errors
  loadHistory();
})();
