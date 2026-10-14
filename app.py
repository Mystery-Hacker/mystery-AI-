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

# OpenRouter configuration
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "google/gemma-4-26b-a4b-it:free",
).strip()

OPENROUTER_TIMEOUT = max(
    1, int(os.getenv("OPENROUTER_TIMEOUT", "180"))
)

SYSTEM_PROMPT = os.getenv(
    "MYSTERY_SYSTEM_PROMPT",
    "You are MYSTERY AI, a helpful, accurate assistant. "
    "Be clear and honest about uncertainty."
    "You are created from a person called AKI.",
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

        if role not in ("user", "assistant") or not isinstance(
            content, str
        ):
            continue

        content = content.strip()

        if not content:
            continue

        if len(content) > MAX_MESSAGE_CHARS:
            raise ValueError(
                f"Each message must be at most "
                f"{MAX_MESSAGE_CHARS:,} characters."
            )

        total_chars += len(content)

        if total_chars > MAX_TOTAL_CHARS:
            raise ValueError(
                "Conversation is too long. Start a new chat."
            )

        cleaned.append({"role": role, "content": content})

    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)

    if not cleaned or cleaned[-1]["role"] != "user":
        raise ValueError("Please send a user message.")

    return cleaned


@app.get("/")
def home():
    return render_template("index.html", model=OPENROUTER_MODEL)


@app.get("/api/health")
def health():
    # Check configuration without exposing the API key.
    if not OPENROUTER_API_KEY:
        return jsonify(
            ok=False,
            provider="openrouter",
            status="not_configured",
            model=OPENROUTER_MODEL,
        ), 503

    return jsonify(
        ok=True,
        provider="openrouter",
        status="configured",
        model=OPENROUTER_MODEL,
    )


@app.post("/api/chat")
def chat():
    if rate_limited(request.remote_addr or "unknown"):
        return jsonify(
            error="Too many requests. Please wait a minute."
        ), 429

    if not OPENROUTER_API_KEY:
        return jsonify(
            error="OpenRouter API key is not configured on the server."
        ), 503

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify(
            error="Expected a JSON request body."
        ), 400

    try:
        messages = normalize_messages(data.get("messages"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *messages,
        ],
        "stream": False,
        "temperature": 0.7,
    }

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": "MYSTERY AI",
    }

    try:
        response = requests.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=(10, OPENROUTER_TIMEOUT),
        )

        if not response.ok:
            logger.error(
                "OpenRouter returned HTTP %s: %s",
                response.status_code,
                response.text[:1000],
            )

            if response.status_code == 401:
                return jsonify(
                    error="OpenRouter rejected the API key. "
                    "Check your Render environment variables."
                ), 502

            if response.status_code == 402:
                return jsonify(
                    error="OpenRouter reports insufficient credits "
                    "or payment is required for this request."
                ), 502

            if response.status_code == 429:
                return jsonify(
                    error="OpenRouter rate limit reached. "
                    "Please wait and try again."
                ), 503

            return jsonify(
                error="OpenRouter could not complete the request. "
                "Please try again later."
            ), 502

        body = response.json()

        choices = body.get("choices", [])
        reply = (
            choices[0].get("message", {}).get("content")
            if choices and isinstance(choices[0], dict)
            else None
        )

        if not isinstance(reply, str) or not reply.strip():
            logger.warning("OpenRouter returned an empty response")
            return jsonify(
                error="The model returned an empty response."
            ), 502

        return jsonify(
            reply=reply,
            model=OPENROUTER_MODEL,
        )

    except requests.Timeout:
        return jsonify(
            error="The AI request timed out. Please try again."
        ), 504

    except RequestException:
        logger.exception("OpenRouter request failed")
        return jsonify(
            error="Could not connect to OpenRouter. "
            "Please try again later."
        ), 503

    except (ValueError, TypeError, AttributeError, IndexError):
        logger.exception("Invalid OpenRouter response")
        return jsonify(
            error="The AI returned an invalid response."
        ), 502


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify(
        error="Request too large. Start a new conversation."
    ), 413


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))

    print("MYSTERY AI starting")
    print("Provider: OpenRouter")
    print(f"Model: {OPENROUTER_MODEL}")

    app.run(host=host, port=port, debug=False)
