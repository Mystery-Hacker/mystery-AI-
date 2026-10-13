from pathlib import Path
import zipfile, textwrap

base = Path(__file__).resolve().parent
(base / "templates").mkdir(parents=True, exist_ok=True)
(base / "static").mkdir(parents=True, exist_ok=True)

files = {
"app.py": r'''
import logging
import os
import time
from collections import defaultdict, deque
from threading import Lock

import requests
from flask import Flask, jsonify, render_template, request
from requests.exceptions import RequestException

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("mystery-ai")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = max(1, int(os.getenv("OLLAMA_TIMEOUT", "180")))
SYSTEM_PROMPT = os.getenv(
    "MYSTERY_SYSTEM_PROMPT",
    "You are MYSTERY AI, a helpful, accurate assistant. "
    "Be clear and honest about uncertainty.",
)

MAX_MESSAGES = 40
MAX_MESSAGE_CHARS = 12000
MAX_TOTAL_CHARS = 60000
RATE_LIMIT = max(1, int(os.getenv("RATE_LIMIT_PER_MINUTE", "20")))
rate_lock = Lock()
request_times = defaultdict(deque)


def rate_limited(client_ip):
    now = time.monotonic()
    cutoff = now - 60
    with rate_lock:
        bucket = request_times[client_ip]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT:
            return True
        bucket.append(now)
        return False


def normalize_messages(raw_messages):
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ValueError("Please enter a message.")

    cleaned = []
    total_chars = 0
    for item in raw_messages[-MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        if len(content) > MAX_MESSAGE_CHARS:
            raise ValueError(
                f"Each message must be at most {MAX_MESSAGE_CHARS:,} characters."
            )
        total_chars += len(content)
        if total_chars > MAX_TOTAL_CHARS:
            raise ValueError("Conversation is too long. Start a new chat.")
        cleaned.append({"role": role, "content": content})

    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    if not cleaned or cleaned[-1]["role"] != "user":
        raise ValueError("Please send a user message.")
    return cleaned


@app.get("/")
def home():
    return render_template("index.html", model=OLLAMA_MODEL)


@app.get("/api/health")
def health():
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        response.raise_for_status()
        models = response.json().get("models", [])
        available_names = {
            name
            for model in models
            if isinstance(model, dict)
            for name in (model.get("name"), model.get("model"))
            if isinstance(name, str)
        }
        return jsonify(
            ok=True,
            ollama="connected",
            model=OLLAMA_MODEL,
            model_available=OLLAMA_MODEL in available_names,
        )
    except (RequestException, ValueError, AttributeError):
        return jsonify(
            ok=False, ollama="unavailable", model=OLLAMA_MODEL
        ), 503


@app.post("/api/chat")
def chat():
    if rate_limited(request.remote_addr or "unknown"):
        return jsonify(error="Too many requests. Please wait a minute."), 429

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Expected a JSON request body."), 400

    try:
        messages = normalize_messages(data.get("messages"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, *messages],
        "stream": False,
        "options": {"temperature": 0.7},
    }

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=(5, OLLAMA_TIMEOUT),
        )
        response.raise_for_status()
        body = response.json()
        message = body.get("message", {})
        reply = message.get("content") if isinstance(message, dict) else None
        if not isinstance(reply, str) or not reply.strip():
            logger.warning("Ollama returned an empty response")
            return jsonify(error="The model returned an empty response."), 502
        return jsonify(reply=reply, model=OLLAMA_MODEL)
    except requests.Timeout:
        return jsonify(error="The model timed out. Try again."), 504
    except RequestException:
        logger.exception("Ollama request failed")
        return jsonify(
            error="Ollama is unavailable. Check that it is running "
                  "and the requested model is installed."
        ), 503
    except (ValueError, TypeError, AttributeError):
        logger.exception("Invalid Ollama response")
        return jsonify(error="The AI returned an invalid response."), 502


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify(error="Request too large. Start a new conversation."), 413


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    print(f"MYSTERY AI: http://{host}:{port}")
    print(f"Ollama: {OLLAMA_URL}")
    print(f"Model: {OLLAMA_MODEL}")
    app.run(host=host, port=port, debug=False)
''',
"templates/index.html": r'''
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#111114">
  <title>MYSTERY AI</title>
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<div class="app-shell">
  <aside class="sidebar" id="sidebar">
    <div class="brand"><div class="brand-mark">✦</div><div><strong>MYSTERY</strong><small>LOCAL INTELLIGENCE</small></div>
      <button id="closeSidebar" class="icon mobile-close" aria-label="Close sidebar">×</button>
    </div>
    <button id="newChat" class="new-chat">＋ New chat</button>
    <p class="sidebar-label">YOUR WORKSPACE</p>
    <div id="conversationList" class="conversation-list"></div>
    <div class="sidebar-spacer"></div>
    <div class="status"><span id="statusDot" class="status-dot"></span><div>
      <strong id="statusTitle">Checking Ollama…</strong><small id="statusSub">Local model connection</small>
    </div><button id="refreshHealth" class="icon" aria-label="Refresh connection">↻</button></div>
    <small class="footnote">PRIVATE BY DESIGN · RUNS LOCALLY</small>
  </aside>
  <div id="sidebarScrim" class="sidebar-scrim"></div>
  <main class="main">
    <header class="topbar">
      <div class="topbar-left"><button id="openSidebar" class="icon menu" aria-label="Open sidebar">☰</button>
        <span class="mobile-brand">MYSTERY <b>AI</b></span>
        <div class="model-pill"><span class="pulse"></span><span id="modelName">{{ model }}</span></div>
      </div>
      <div class="topbar-actions"><button id="exportChat" class="subtle">Export</button>
        <button id="clearChat" class="icon" aria-label="Clear conversation">⌫</button></div>
    </header>
    <section id="chatScroll" class="chat-scroll">
      <div id="welcome" class="welcome">
        <div class="welcome-orb">✦</div><p class="eyebrow">YOUR PRIVATE AI WORKSPACE</p>
        <h1>Ideas begin<br><span>with a question.</span></h1>
        <p class="intro">Explore an idea, solve a problem, or build something useful. MYSTERY is ready when you are.</p>
        <div class="suggestions">
          <button class="suggestion" data-prompt="Explain a complex topic simply, with an example."><strong>◇ Explain a concept</strong><small>Make the complicated clear</small></button>
          <button class="suggestion" data-prompt="Help me brainstorm creative project ideas."><strong>✳ Brainstorm ideas</strong><small>Explore new possibilities</small></button>
          <button class="suggestion" data-prompt="Help me write clean, well-documented code."><strong>{ } Write some code</strong><small>Turn a plan into a solution</small></button>
          <button class="suggestion" data-prompt="Help me create a step-by-step plan for a goal."><strong>↗ Make a plan</strong><small>Break a goal into steps</small></button>
        </div>
      </div>
      <div id="messages" class="messages"></div>
    </section>
    <footer class="composer-area">
      <form id="chatForm" class="composer">
        <textarea id="prompt" rows="1" maxlength="12000" placeholder="Message MYSTERY…" aria-label="Message MYSTERY AI" required></textarea>
        <div class="composer-toolbar"><small>Enter to send · Shift+Enter for a new line</small>
          <div class="composer-controls"><span id="charCount">0 / 12,000</span><button id="sendButton" type="submit" aria-label="Send message">↑</button></div>
        </div>
      </form>
      <p class="disclaimer">Runs locally with Ollama. AI can make mistakes; verify important information.</p>
    </footer>
  </main>
</div>
<div id="toast" class="toast" role="status" aria-live="polite"></div>
<script>window.MYSTERY_CONFIG = {model: {{ model|tojson }}};</script>
<script src="{{ url_for('static', filename='app.js') }}" defer></script>
</body>
</html>
''',
"static/style.css": r'''
:root{color-scheme:dark;--bg:#111114;--sidebar:#17171b;--panel:#1d1c22;--line:rgba(255,255,255,.08);--text:#f0eff5;--muted:#8c8b98;--accent:#c7a8ff}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;font-size:14px}
button,textarea{font:inherit}button{color:inherit;cursor:pointer}button:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.app-shell{display:flex;height:100dvh;overflow:hidden}.sidebar{width:264px;flex:0 0 264px;padding:22px 15px 15px;background:var(--sidebar);border-right:1px solid var(--line);display:flex;flex-direction:column;z-index:5}
.brand{display:flex;align-items:center;gap:11px;margin-bottom:28px;padding:0 8px}.brand-mark,.welcome-orb{display:grid;place-items:center;background:linear-gradient(140deg,#d8c4ff,#8d6ed4);color:#21162f;border-radius:11px}.brand-mark{width:35px;height:35px;font-size:21px}.brand strong{display:block;font-size:13px;letter-spacing:.17em}.brand small{display:block;margin-top:4px;color:#777482;font-size:8px;letter-spacing:.13em}
.new-chat{text-align:left;padding:12px;border:1px solid #3a3943;border-radius:10px;background:#222127}.new-chat:hover{background:#2b2932}.sidebar-label{margin:29px 10px 10px;color:#777582;font-size:9px;letter-spacing:.16em}.conversation-list{display:flex;flex-direction:column;gap:4px;overflow:auto}
.conversation-item{display:flex;align-items:center;gap:8px;padding:9px;border-radius:8px}.conversation-item.active,.conversation-item:hover{background:#25242b}.conversation-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left;border:0;background:none}.conv-delete{border:0;background:transparent;color:#aaa}
.sidebar-spacer{flex:1;min-height:20px}.status{display:flex;align-items:center;gap:9px;padding:12px 5px;border-top:1px solid var(--line)}.status>div{flex:1;min-width:0}.status strong,.status small{display:block}.status strong{font-size:11px}.status small{margin-top:4px;font-size:10px;color:var(--muted);overflow-wrap:anywhere}.status-dot{width:7px;height:7px;border-radius:50%;background:#d3a75f}.status-dot.online{background:#76d7a0}.status-dot.offline{background:#ed777e}.footnote{color:#5e5b68;font-size:8px;letter-spacing:.12em;text-align:center;padding-top:8px}
.main{display:flex;flex-direction:column;flex:1;min-width:0}.topbar{height:65px;flex:0 0 65px;display:flex;align-items:center;justify-content:space-between;padding:0 25px;border-bottom:1px solid var(--line)}.topbar-left,.topbar-actions{display:flex;align-items:center;gap:12px}.model-pill{display:flex;align-items:center;gap:8px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;color:#c9c7d2;font-size:11px}.pulse{width:6px;height:6px;border-radius:50%;background:var(--accent)}
.icon{border:0;background:transparent;color:#aaa;border-radius:8px;padding:8px}.icon:hover,.subtle:hover{background:#25242b}.subtle{border:1px solid var(--line);background:transparent;border-radius:8px;padding:8px 11px;color:#aaa}.menu,.mobile-brand,.mobile-close{display:none}
.chat-scroll{flex:1;overflow-y:auto;padding:0 20px}.welcome{max-width:720px;margin:clamp(35px,8vh,86px) auto 35px;text-align:center}.welcome-orb{width:52px;height:52px;margin:0 auto 22px;border-radius:17px;font-size:25px}.eyebrow{color:#a18ac8;font-size:9px;font-weight:700;letter-spacing:.2em}.welcome h1{margin:0;font-size:clamp(34px,4vw,49px);line-height:1.13;letter-spacing:-.055em}.welcome h1 span{color:#a59ab9}.intro{color:#8e8b99;line-height:1.8;margin:17px 0 29px}
.suggestions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;max-width:570px;margin:auto;text-align:left}.suggestion{display:flex;flex-direction:column;gap:7px;padding:15px;border:1px solid #2c2a33;border-radius:12px;background:#19191e;text-align:left}.suggestion:hover{border-color:#5d4b76;background:#211e28}.suggestion strong{font-size:11px}.suggestion small{color:#777482;font-size:10px}
.messages{max-width:790px;margin:auto;padding:5px 0 28px}.message-row{display:flex;gap:12px;margin:24px 0}.user-row{justify-content:flex-end}.avatar{display:grid;place-items:center;flex:0 0 30px;height:30px;border-radius:10px;background:#c7a8ff;color:#21162f}.message-content{min-width:0;max-width:calc(100% - 42px)}.message-meta{margin:2px 0 8px;color:#bcb9c7;font-size:11px}.message-text{color:#d8d6df;font-size:13px;line-height:1.8;overflow-wrap:anywhere;white-space:pre-wrap}.user-row .message-content{padding:12px 15px;border:1px solid #393442;border-radius:16px 16px 4px 16px;background:#27252f}.user-row .message-meta{display:none}.message-actions{display:flex;gap:6px;margin-top:10px}.message-action,.copy-code{border:0;background:transparent;color:#999;padding:5px;font-size:10px}.message-text p{margin:0 0 11px}.message-text h1,.message-text h2,.message-text h3{line-height:1.35}.message-text a{color:#c6a7ff}.message-text code{padding:2px 5px;border-radius:5px;background:#1a191f;color:#e0cfff;font-family:monospace}.code-wrap{margin:13px 0;overflow:hidden;border:1px solid #34313c;border-radius:10px;background:#151519}.code-head{display:flex;justify-content:space-between;padding:8px 11px;border-bottom:1px solid #2a2831;color:#aaa;font-size:10px}.message-text pre{margin:0;padding:13px;overflow-x:auto;white-space:pre}.message-text pre code{padding:0;background:transparent;color:#ddd8e9}.typing-dots{padding:8px 0;color:var(--accent)}
.composer-area{width:min(850px,100%);margin:0 auto;padding:10px 25px 13px}.composer{padding:13px 14px 10px;border:1px solid #3b3744;border-radius:17px;background:var(--panel)}.composer:focus-within{border-color:#6d588c}textarea{display:block;width:100%;min-height:30px;max-height:180px;padding:4px 2px 8px;resize:none;border:0;outline:0;background:transparent;color:#f0edf7;line-height:1.55}textarea::placeholder{color:#777482}.composer-toolbar{display:flex;align-items:center;justify-content:space-between;gap:10px}.composer-toolbar small,#charCount{color:#777482;font-size:9px}.composer-controls{display:flex;align-items:center;gap:12px}#sendButton{width:34px;height:34px;border:0;border-radius:10px;background:var(--accent);color:#21162f;font-size:21px}#sendButton:disabled{opacity:.5;cursor:not-allowed}.disclaimer{margin-top:10px;text-align:center;color:#686573;font-size:9px;line-height:1.5}
.toast{position:fixed;z-index:20;left:50%;bottom:35px;transform:translateX(-50%);padding:11px 15px;border:1px solid #46404f;border-radius:9px;background:#26232c;color:#eeeaf5;opacity:0;pointer-events:none;transition:opacity .2s}.toast.show{opacity:1}.sidebar-scrim{display:none}
@media(max-width:800px){.sidebar{position:fixed;inset:0 auto 0 0;width:280px;transform:translateX(-105%);transition:transform .22s;box-shadow:15px 0 45px #0004}.sidebar.open{transform:translateX(0)}.sidebar-scrim.visible{display:block;position:fixed;inset:0;z-index:4;background:#0009}.menu,.mobile-brand{display:inline-flex}.mobile-brand{gap:5px;font-size:12px;letter-spacing:.1em}.mobile-brand b{color:var(--accent)}.mobile-close{display:block;margin-left:auto}.topbar{padding:0 13px}.chat-scroll{padding:0 13px}.composer-area{padding:9px 13px 11px}}
@media(max-width:520px){.topbar{height:58px;flex-basis:58px}.model-pill{max-width:125px;overflow:hidden}#modelName{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.suggestions{grid-template-columns:1fr}.welcome h1{font-size:36px}.composer-toolbar>small{display:none}.message-row{gap:8px;margin:20px 0}.message-content{max-width:calc(100% - 35px)}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important;scroll-behavior:auto!important}}
''',
"static/app.js": r'''
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
''',
"requirements.txt": "Flask>=3.0,<4.0\nrequests>=2.31,<3.0\n",
"README.md": r'''
# MYSTERY AI

A local AI chat interface powered by Flask and Ollama.

## Requirements

- Python 3.10 or later
- Ollama installed
- A compatible model downloaded into Ollama

## Installation

Download the model:

    ollama pull qwen2.5:3b

Create and activate a virtual environment:

    python -m venv .venv
    source .venv/bin/activate        # Linux/macOS
    # .venv\Scripts\Activate.ps1     # Windows PowerShell

Install dependencies and run:

    python -m pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000 in your browser.

## Configuration

- `OLLAMA_URL`: Ollama API URL; defaults to `http://127.0.0.1:11434`
- `OLLAMA_MODEL`: Model name; defaults to `qwen2.5:3b`
- `OLLAMA_TIMEOUT`: Response timeout in seconds; defaults to `180`
- `RATE_LIMIT_PER_MINUTE`: Per-IP request limit; defaults to `20`
- `HOST`: Flask bind address; defaults to `127.0.0.1`
- `PORT`: Flask port; defaults to `5000`
- `LOG_LEVEL`: Logging level; defaults to `INFO`

Conversation history is stored in browser local storage. The Flask development server is intended for local use; use a production WSGI server and appropriate security controls for production deployment.
'''
}

for relative, content in files.items():
    path = base / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")

zip_path = base.parent / "mystery-ai.zip"
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for relative in files:
        archive.write(base / relative, arcname=f"mystery-ai/{relative}")

# Validate Python syntax without running the Flask app.
compile((base / "app.py").read_text(encoding="utf-8"), str(base / "app.py"), "exec")

print("Fixed project created and app.py syntax-checked.")
print(f"ZIP archive: {zip_path}")
print(f"Project directory: {base}")
