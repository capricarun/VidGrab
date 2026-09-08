#!/bin/bash
# One-time setup. Run this once; after it, VidGrab starts itself at every login
# and you never touch Terminal again.
set -e
cd "$(dirname "$0")"
PROJ="$PWD"
PLIST="$HOME/Library/LaunchAgents/com.vidgrab.app.plist"

echo
echo "  VidGrab setup"
echo "  ─────────────"
echo

# ---- 1. python deps -----------------------------------------------------
if [ ! -d .venv ]; then
  echo "  · creating a private Python environment…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q yt-dlp fastapi "uvicorn[standard]"
else
  echo "  · Python environment already there"
fi

# ---- 2. ffmpeg ----------------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1; then
  echo "  · ffmpeg found"
else
  echo "  ⚠  ffmpeg missing — you'll be capped at 720p on YouTube and can't make mp3s."
  echo "     Install later with:  brew install ffmpeg"
fi

# ---- 3. cloudflared -----------------------------------------------------
mkdir -p bin logs docs
if [ ! -x bin/cloudflared ]; then
  ARCH=$([ "$(uname -m)" = "arm64" ] && echo arm64 || echo amd64)
  echo "  · downloading Cloudflare tunnel client ($ARCH)…"
  curl -fsSL -o /tmp/cloudflared.tgz \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-$ARCH.tgz"
  tar -xzf /tmp/cloudflared.tgz -C bin cloudflared
  chmod +x bin/cloudflared
  rm -f /tmp/cloudflared.tgz
  xattr -dr com.apple.quarantine bin/cloudflared 2>/dev/null || true
else
  echo "  · tunnel client already there"
fi

# ---- 4. passphrase ------------------------------------------------------
if [ ! -f .vidgrab.env ]; then
  echo
  echo "  Your link will be reachable from the public internet, so it needs a"
  echo "  passphrase. You'll type it once per device, then never again."
  echo
  while :; do
    read -r -s -p "  Choose a passphrase: " P1; echo
    read -r -s -p "  Type it again:      " P2; echo
    [ -n "$P1" ] && [ "$P1" = "$P2" ] && break
    echo "  ✗ empty or didn't match — try again"; echo
  done
  printf 'VIDGRAB_TOKEN=%q\nVIDGRAB_PORT=8420\n' "$P1" > .vidgrab.env
  chmod 600 .vidgrab.env
  echo "  · passphrase saved (never leaves this Mac, never committed)"
else
  echo "  · passphrase already set — delete .vidgrab.env to change it"
fi

chmod +x launch.sh run.sh VidGrab.command 2>/dev/null || true

# ---- 5. auto-start at login --------------------------------------------
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.vidgrab.app</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$PROJ/launch.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJ</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$PROJ/logs/agent.log</string>
  <key>StandardErrorPath</key><string>$PROJ/logs/agent.log</string>
</dict></plist>
PLISTEOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load  "$PLIST"
echo "  · auto-start installed — VidGrab now runs at every login"

# ---- 6. wait for the tunnel --------------------------------------------
echo
printf "  Opening your tunnel"
URL=""
for _ in $(seq 1 45); do
  printf "."
  URL=$(python3 -c "import json;print(json.load(open('docs/status.json')).get('url',''))" 2>/dev/null || true)
  [ -n "$URL" ] && break
  sleep 1
done
echo

if [ -n "$URL" ]; then
  echo
  echo "  ✓ VidGrab is live at:"
  echo "      $URL"
else
  echo
  echo "  ⚠  Tunnel didn't come up yet. Check logs/tunnel.log in a minute."
fi

echo
echo "  Bookmark your permanent link instead of the address above —"
echo "  it survives restarts and follows the tunnel wherever it moves:"
echo
echo "      https://capricarun.github.io/vidgrab/"
echo
echo "  Done. You never need Terminal again."
echo
