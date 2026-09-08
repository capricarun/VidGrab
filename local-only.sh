#!/bin/bash
# Switch VidGrab back to local-only: stop the auto-start agent, close the public
# tunnel, and mark the launcher page offline. Your files and settings are kept.
cd "$(dirname "$0")" || exit 1
PLIST="$HOME/Library/LaunchAgents/com.vidgrab.app.plist"

echo
echo "  Switching VidGrab to local-only…"

if [ -f "$PLIST" ]; then
  launchctl unload "$PLIST" 2>/dev/null
  rm -f "$PLIST"
  echo "  · auto-start removed"
else
  echo "  · no auto-start agent found"
fi

pkill -f "cloudflared tunnel --url http://127.0.0.1" 2>/dev/null && echo "  · tunnel closed"
pkill -f "\.venv/bin/python server.py"                2>/dev/null && echo "  · server stopped"

# Tell the launcher page nothing is listening any more.
printf '{\n "url": "",\n "updated": %d\n}\n' "$(date +%s)" > docs/status.json
if git remote get-url origin >/dev/null 2>&1; then
  git add docs/status.json >/dev/null 2>&1
  git -c user.name="VidGrab" -c user.email="vidgrab@local" \
      commit -q -m "status: offline (local-only mode)" >/dev/null 2>&1
  git push -q origin HEAD >/dev/null 2>&1 \
    && echo "  · launcher page now shows offline" \
    || echo "  · couldn't push status (harmless — page will just show a stale address)"
fi

echo
echo "  Done. VidGrab is local-only now."
echo "  Start it by double-clicking VidGrab.command, or:  ./run.sh"
echo "  It opens at http://127.0.0.1:8420 with no passphrase, and nothing"
echo "  is reachable from outside this Mac."
echo
