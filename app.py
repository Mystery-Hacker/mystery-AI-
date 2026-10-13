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
app.run(host="0.0.0.0", port=5000, debug=False) 