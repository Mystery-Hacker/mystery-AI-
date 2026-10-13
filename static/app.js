(() => {
  "use strict";
  const $ = selector => document.querySelector(selector);
  const form = $("#chatForm"), input = $("#prompt"), messagesEl = $("#messages");
  const chatScroll = $("#chatScroll"), welcome = $("#welcome"), sendButton = $("#sendButton");
  const charCount = $("#charCount"), conversationList = $("#conversationList"), toast = $("#toast");
  const STORAGE_KEY = "mystery-ai-conversations-v2";
  let conversations = loadConversations(), activeId = conversations[0]?.id || null;
  let busy = false, controller = null, toastTimer = null;

  function uid() {
    return (crypto.randomUUID && crypto.randomUUID()) ||
      `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  function loadConversations() {
    try {
      const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      if (!Array.isArray(data)) return [];
      return data.filter(c => c && typeof c.id === "string" && Array.isArray(c.messages))
        .map(c => ({
          id: c.id, title: typeof c.title === "string" ? c.title.slice(0, 90) : "New chat",
          updatedAt: Number(c.updatedAt) || Date.now(),
          messages: c.messages.filter(m => m && ["user", "assistant"].includes(m.role) &&
            typeof m.content === "string").slice(-40).map(m => ({
              role: m.role, content: m.content.slice(0, 12000), time: Number(m.time) || Date.now()
            }))
        })).slice(0, 100);
    } catch { return []; }
  }
  function saveConversations() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.slice(0, 100))); }
    catch { showToast("Could not save chat history in this browser."); }
  }
  function createConversation() {
    const c = {id: uid(), title: "New chat", updatedAt: Date.now(), messages: []};
    conversations.unshift(c); activeId = c.id; saveConversations(); return c;
  }
  function currentConversation() { return conversations.find(c => c.id === activeId) || null; }
  function escapeHTML(value) {
    return value.replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  }
  function renderMarkdown(raw) {
    const codeBlocks = [];
    let text = raw.replace(/```([\w+-]*)\n([\s\S]*?)```/g, (_, lang, code) => {
      const token = `MYSTERYCODETOKEN${codeBlocks.length}END`;
      codeBlocks.push({language: lang || "code", code: code.replace(/\n$/, "")});
      return `\n\n${token}\n\n`;
    });
    text = escapeHTML(text);
    const inlineCodes = [];
    text = text.replace(/`([^`\n]+)`/g, (_, code) => {
      const token = `MYSTERYINLINECODE${inlineCodes.length}END`; inlineCodes.push(code); return token;
    });
    text = text.replace(/^### (.+)$/gm, "<h3>$1</h3>")
      .replace(/^## (.+)$/gm, "<h2>$1</h2>").replace(/^# (.+)$/gm, "<h1>$1</h1>")
      .replace(/^&gt; (.+)$/gm, "<blockquote>$1</blockquote>")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/(^|\n)[-*] (.+)/g, "$1<li>$2</li>")
      .replace(/(?:<li>.*?<\/li>\n?)+/g, block => `<ul>${block}</ul>`);
    text = text.split(/\n{2,}/).map(part => {
      const trimmed = part.trim();
      if (!trimmed) return "";
      if (/^(<h[1-3]|<ul|<ol|<blockquote|<pre|<div|MYSTERYCODETOKEN)/.test(trimmed)) return trimmed;
      return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
    }).join("");
    inlineCodes.forEach((code, i) => { text = text.replace(`MYSTERYINLINECODE${i}END`, `<code>${code}</code>`); });
    codeBlocks.forEach((block, i) => {
      const html = `<div class="code-wrap"><div class="code-head"><span>${escapeHTML(block.language)}</span>
        <button class="copy-code" type="button">Copy code</button></div><pre><code>${escapeHTML(block.code)}</code></pre></div>`;
      text = text.replace(`MYSTERYCODETOKEN${i}END`, html);
    });
    return text;
  }
  function showToast(message) {
    toast.textContent = message; toast.classList.add("show"); clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
  }
  function scrollToBottom() { chatScroll.scrollTop = chatScroll.scrollHeight; }
  function makeMessage(message, index) {
    const row = document.createElement("article");
    row.className = `message-row ${message.role}-row`; row.dataset.messageIndex = String(index);
    if (message.role === "assistant") {
      const avatar = document.createElement("div"); avatar.className = "avatar";
      avatar.textContent = "✦"; avatar.setAttribute("aria-hidden", "true"); row.appendChild(avatar);
    }
    const content = document.createElement("div"); content.className = "message-content";
    if (message.role === "assistant") {
      const meta = document.createElement("div"); meta.className = "message-meta";
      meta.textContent = "MYSTERY AI"; content.appendChild(meta);
    }
    const body = document.createElement("div"); body.className = "message-text";
    if (message.role === "assistant") body.innerHTML = renderMarkdown(message.content);
    else body.textContent = message.content;
    content.appendChild(body);
    if (message.role === "assistant") {
      const actions = document.createElement("div"); actions.className = "message-actions";
      actions.innerHTML = '<button class="message-action" data-action="copy">Copy</button><button class="message-action" data-action="regenerate">Regenerate</button>';
      content.appendChild(actions);
    }
    row.appendChild(content); return row;
  }
  function renderConversationList() {
    conversationList.replaceChildren();
    [...conversations].sort((a,b) => b.updatedAt-a.updatedAt).forEach(c => {
      const row = document.createElement("div");
      row.className = "conversation-item" + (c.id === activeId ? " active" : "");
      const title = document.createElement("button"); title.className = "conversation-title";
      title.textContent = c.title || "New chat";
      title.addEventListener("click", () => {
        if (busy) return showToast("Wait for the current response to finish.");
        activeId = c.id; renderConversation(); closeSidebar();
      });
      const del = document.createElement("button"); del.className = "conv-delete"; del.textContent = "×";
      del.setAttribute("aria-label", "Delete conversation");
      del.addEventListener("click", () => {
        if (busy && c.id === activeId) return showToast("Wait for the response to finish.");
        conversations = conversations.filter(item => item.id !== c.id);
        if (activeId === c.id) {
          activeId = conversations[0]?.id || null;
          if (!activeId) createConversation();
        }
        saveConversations(); renderConversation();
      });
      row.append(title, del); conversationList.appendChild(row);
    });
  }
  function renderConversation() {
    messagesEl.replaceChildren();
    const c = currentConversation();
    welcome.hidden = Boolean(c && c.messages.length);
    if (c) c.messages.forEach((m,i) => messagesEl.appendChild(makeMessage(m,i)));
    renderConversationList(); scrollToBottom();
  }
  function addMessage(role, content) {
    const c = currentConversation(); if (!c) return null;
    const message = {role, content, time: Date.now()}; c.messages.push(message);
    c.updatedAt = Date.now();
    if (role === "user" && c.title === "New chat") c.title = content.trim().replace(/\s+/g," ").slice(0,42);
    saveConversations(); renderConversation(); return message;
  }
  function setBusy(value) { busy = value; sendButton.disabled = value; sendButton.textContent = value ? "…" : "↑"; input.disabled = value; }
  function addTypingIndicator() {
    const row = document.createElement("article"); row.id = "typingIndicator"; row.className = "message-row assistant-row";
    const content = document.createElement("div"); content.className = "message-content";
    const meta = document.createElement("div"); meta.className = "message-meta"; meta.textContent = "MYSTERY is thinking…";
    const dots = document.createElement("div"); dots.className = "typing-dots"; dots.textContent = "•••";
    content.append(meta,dots); row.appendChild(content); messagesEl.appendChild(row); scrollToBottom();
  }
  function resizeInput() { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight,180)}px`; }
  function updateCount() { charCount.textContent = `${input.value.length.toLocaleString()} / 12,000`; }
  async function requestReply(c) {
    controller = new AbortController();
    try {
      const response = await fetch("/api/chat", {
        method:"POST", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({messages:c.messages.map(m => ({role:m.role,content:m.content}))}),
        signal:controller.signal
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
      if (typeof data.reply !== "string" || !data.reply.trim()) throw new Error("The model returned an empty response.");
      return data.reply;
    } finally { controller = null; }
  }
  async function sendMessage(text) {
    if (busy || !text.trim()) return;
    const c = currentConversation() || createConversation(); const clean = text.trim();
    addMessage("user",clean); input.value = ""; resizeInput(); updateCount(); setBusy(true); addTypingIndicator();
    try {
      const reply = await requestReply(c); $("#typingIndicator")?.remove();
      if (currentConversation()?.id === c.id) addMessage("assistant",reply);
      else { c.messages.push({role:"assistant",content:reply,time:Date.now()}); saveConversations(); }
    } catch (error) {
      $("#typingIndicator")?.remove();
      if (error.name === "AbortError") showToast("Generation stopped.");
      else {
        showToast(error.message || "Could not reach Ollama.");
        const last = c.messages.at(-1);
        if (last?.role === "user" && last.content === clean) { c.messages.pop(); saveConversations(); renderConversation(); }
      }
    } finally { controller = null; setBusy(false); input.focus(); scrollToBottom(); }
  }
  async function regenerateAnswer(index) {
    if (busy) return;
    const c = currentConversation();
    if (!c || c.messages[index]?.role !== "assistant" || !c.messages.slice(0,index).some(m => m.role === "user")) return;
    c.messages = c.messages.slice(0,index); saveConversations(); renderConversation(); setBusy(true); addTypingIndicator();
    try { const reply = await requestReply(c); $("#typingIndicator")?.remove(); addMessage("assistant",reply); }
    catch (error) { $("#typingIndicator")?.remove(); showToast(error.message || "Could not regenerate response."); }
    finally { controller = null; setBusy(false); scrollToBottom(); }
  }
  function closeSidebar() { $("#sidebar").classList.remove("open"); $("#sidebarScrim").classList.remove("visible"); }
  function newChat() {
    if (busy) return showToast("Wait for the current response to finish.");
    createConversation(); renderConversation(); input.focus(); closeSidebar();
  }
  form.addEventListener("submit", e => { e.preventDefault(); if (!busy) sendMessage(input.value); });
  input.addEventListener("input", () => { resizeInput(); updateCount(); });
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  $("#newChat").addEventListener("click",newChat);
  $("#openSidebar").addEventListener("click",() => { $("#sidebar").classList.add("open"); $("#sidebarScrim").classList.add("visible"); });
  $("#closeSidebar").addEventListener("click",closeSidebar); $("#sidebarScrim").addEventListener("click",closeSidebar);
  document.querySelectorAll(".suggestion").forEach(button => button.addEventListener("click",() => {
    input.value = button.dataset.prompt || ""; resizeInput(); updateCount(); input.focus();
  }));
  messagesEl.addEventListener("click",async e => {
    const codeButton = e.target.closest(".copy-code");
    if (codeButton) {
      const code = codeButton.closest(".code-wrap")?.querySelector("pre code")?.textContent || "";
      try { await navigator.clipboard.writeText(code); showToast("Code copied."); }
      catch { showToast("Clipboard access is unavailable."); }
      return;
    }
    const action = e.target.closest("[data-action]"); if (!action) return;
    const row = action.closest(".message-row"), index = Number(row?.dataset.messageIndex);
    const message = currentConversation()?.messages[index]; if (!message) return;
    if (action.dataset.action === "copy") {
      try { await navigator.clipboard.writeText(message.content); showToast("Message copied."); }
      catch { showToast("Clipboard access is unavailable."); }
    } else if (action.dataset.action === "regenerate") regenerateAnswer(index);
  });
  $("#clearChat").addEventListener("click",() => {
    if (busy) return showToast("Wait for the current response to finish.");
    const c = currentConversation(); if (!c) return;
    c.messages = []; c.title = "New chat"; c.updatedAt = Date.now();
    saveConversations(); renderConversation(); showToast("Conversation cleared.");
  });
  $("#exportChat").addEventListener("click",() => {
    const c = currentConversation(); if (!c?.messages.length) return showToast("There are no messages to export.");
    const text = c.messages.map(m => `${m.role === "user" ? "You" : "MYSTERY AI"}\n${m.content}`).join("\n\n---\n\n");
    const blob = new Blob([text],{type:"text/plain;charset=utf-8"}), url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = "mystery-chat.txt"; a.click();
    setTimeout(() => URL.revokeObjectURL(url),1000);
  });
  async function checkHealth() {
    const dot=$("#statusDot"), title=$("#statusTitle"), sub=$("#statusSub");
    title.textContent="Checking Ollama…"; dot.className="status-dot";
    try {
      const response=await fetch("/api/health"), data=await response.json();
      if (!response.ok || !data.ok) throw new Error("Ollama unavailable");
      dot.className="status-dot online"; title.textContent="Ollama connected";
      sub.textContent=data.model_available ? `Model ready · ${data.model}` : `Model not found · ${data.model}`;
    } catch { dot.className="status-dot offline"; title.textContent="Ollama offline"; sub.textContent="Start Ollama to chat"; }
  }
  $("#refreshHealth").addEventListener("click",checkHealth);
  document.addEventListener("keydown",e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase()==="k") { e.preventDefault(); newChat(); }
    if (e.key==="Escape") closeSidebar();
  });
  if (!conversations.length) createConversation(); else activeId=conversations[0].id;
  renderConversation(); updateCount(); checkHealth();
})();
