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
