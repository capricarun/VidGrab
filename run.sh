#!/bin/bash
# VidGrab launcher — sets up a private virtualenv on first run, then starts the app.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "First run: setting up (takes ~30s)…"
  python3 -m venv .venv || { echo "Need Python 3. Install from python.org"; exit 1; }
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q yt-dlp fastapi "uvicorn[standard]" || exit 1
fi

# keep the extractors fresh — sites change constantly
./.venv/bin/pip install -q --upgrade yt-dlp 2>/dev/null &

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "⚠  ffmpeg not found — best-quality merging and mp3 export will be limited."
  echo "   Install it with:  brew install ffmpeg"
  echo
fi

( sleep 2; open "http://127.0.0.1:8420" ) &
exec ./.venv/bin/python server.py
