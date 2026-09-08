#!/bin/bash
# VidGrab supervisor — started automatically at login by the LaunchAgent.
# Boots the app, opens a Cloudflare tunnel, and publishes the tunnel's current
# address to the GitHub Pages launcher so your bookmark always finds it.

cd "$(dirname "$0")" || exit 1
mkdir -p logs docs bin
[ -f .vidgrab.env ] && . ./.vidgrab.env
PORT="${VIDGRAB_PORT:-8420}"
export VIDGRAB_TOKEN VIDGRAB_PORT VIDGRAB_DIR

log(){ echo "$(date '+%F %T')  $*" >> logs/launch.log; }

publish(){                       # $1 = url ("" means offline)
  python3 - "$1" <<'PY' 2>/dev/null
import json, sys, time, pathlib
pathlib.Path("docs").mkdir(exist_ok=True)
pathlib.Path("docs/status.json").write_text(json.dumps(
    {"url": sys.argv[1], "updated": int(time.time())}, indent=1) + "\n")
PY
  if git rev-parse --git-dir >/dev/null 2>&1 && git remote get-url origin >/dev/null 2>&1; then
    git add docs/status.json >/dev/null 2>&1
    git -c user.name="VidGrab" -c user.email="vidgrab@local" \
        commit -q -m "status: ${1:-offline}" >/dev/null 2>&1
    git push -q origin HEAD >/dev/null 2>&1 \
      && log "published ${1:-offline}" || log "push failed (app still reachable at ${1:-—})"
  fi
}

# ---- dependencies -------------------------------------------------------
if [ ! -d .venv ]; then
  log "creating venv"
  python3 -m venv .venv || { log "python3 missing"; exit 1; }
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q yt-dlp fastapi "uvicorn[standard]" || { log "pip failed"; exit 1; }
fi
# extractors go stale fast; refresh in the background, never block startup
( ./.venv/bin/pip install -q --upgrade yt-dlp >/dev/null 2>&1 ; log "yt-dlp refreshed" ) &

# ---- app ----------------------------------------------------------------
./.venv/bin/python server.py >> logs/server.log 2>&1 &
SRV=$!
for _ in $(seq 1 40); do
  curl -sf -o /dev/null "http://127.0.0.1:$PORT/api/jobs?k=$VIDGRAB_TOKEN" && break
  sleep 0.5
done
log "server up (pid $SRV)"

# ---- tunnel -------------------------------------------------------------
: > logs/tunnel.log
./bin/cloudflared tunnel --url "http://127.0.0.1:$PORT" --no-autoupdate \
  >> logs/tunnel.log 2>&1 &
TUN=$!

URL=""
for _ in $(seq 1 60); do
  URL=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' logs/tunnel.log | head -1)
  [ -n "$URL" ] && break
  sleep 1
done
[ -n "$URL" ] && log "tunnel $URL" || log "tunnel failed to start"
publish "$URL"

cleanup(){ publish ""; kill "$SRV" "$TUN" 2>/dev/null; }
trap cleanup EXIT INT TERM

# Re-publish if cloudflared reconnects under a new address.
while kill -0 "$SRV" 2>/dev/null && kill -0 "$TUN" 2>/dev/null; do
  sleep 30
  NEW=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' logs/tunnel.log | tail -1)
  if [ -n "$NEW" ] && [ "$NEW" != "$URL" ]; then
    URL="$NEW"; log "tunnel moved to $URL"; publish "$URL"
  fi
done
