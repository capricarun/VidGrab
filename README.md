# VidGrab

A personal video downloader with a browser UI, reachable from anywhere by one
permanent link — but running on your own Mac, not in the cloud.

Paste a link from YouTube, X, Instagram, TikTok, Reddit, Facebook, Vimeo,
Twitch, LinkedIn, Bluesky or ~1800 other sites, pick a quality, get the file.

## Why it runs on your Mac

The obvious thing to do would be to host this on Render or Fly and be done with
it. That doesn't work in practice: YouTube and Instagram aggressively block
datacenter IP ranges, so a cloud-hosted copy gets "sign in to confirm you're not
a bot" on most requests and refuses almost everything on Instagram.

Running on your own machine means your residential IP and, optionally, your own
browser session — which is what actually makes the two hardest sites work. The
Cloudflare tunnel is what makes it reachable from your phone anyway.

```
  bookmark  ─→  GitHub Pages launcher  ─→  Cloudflare tunnel  ─→  your Mac
 (permanent)     (finds current address)      (public HTTPS)      (does the work)
```

## Setup — once

```bash
cd ~/Design/VidGrab
./install.sh
```

That creates a private Python environment, downloads the Cloudflare tunnel
client, asks you to choose a passphrase, and installs a LaunchAgent so VidGrab
starts itself at every login.

After it finishes, bookmark **<https://capricarun.github.io/vidgrab/>** and never
open Terminal again. The launcher page checks where the tunnel currently is and
forwards you there; your passphrase is asked once per device and remembered in
that browser.

## Using it

Paste → **Fetch** → choose a quality → **Download**. Files land in
`~/Design/VidGrab/Downloads/<Site>/<Creator>/`, and each finished row offers
**Show** (reveal in Finder) and **Save** (download to whatever device you're on).

For signed-in content — most of Instagram, age-restricted YouTube, private posts
— open **Advanced → Use cookies from** and pick the browser you're logged into.
macOS won't let anything read Chrome's cookie store while Chrome is running, so
quit it first or use Safari.

## Things that will bite you eventually

**ffmpeg.** YouTube serves anything above 720p as separate video and audio
streams that have to be merged. Without ffmpeg you're capped at 720p and can't
export mp3. `brew install ffmpeg` once.

**Your Mac has to be awake.** Closed lid or asleep means the launcher page shows
"offline". *System Settings → Lock Screen → Turn display off on power adapter →
Never* helps if you want it always reachable.

**Sites break.** Platforms change their players constantly; yt-dlp ships fixes
within days and the launcher auto-updates it on every start. If one site stops
working, that's the usual fix — restart, or `launchctl kickstart -k
gui/$UID/com.vidgrab.app`.

**Rate limits are real.** Three downloads run in parallel by default. Pushing
much harder than that gets your IP throttled.

## Configuration

`.vidgrab.env` (created by the installer, never committed):

| Variable | Default | Purpose |
|---|---|---|
| `VIDGRAB_TOKEN` | *(your passphrase)* | Required by every request. Empty disables the gate — only safe with no tunnel. |
| `VIDGRAB_PORT` | `8420` | Local port |
| `VIDGRAB_DIR` | `./Downloads` | Where files land |

## Running it locally only

If you don't want the tunnel at all, skip `install.sh` and use `./run.sh` (or
double-click `VidGrab.command`). That binds to `127.0.0.1` with no passphrase and
nothing leaves your machine.

To remove the auto-start later:

```bash
launchctl unload ~/Library/LaunchAgents/com.vidgrab.app.plist
rm ~/Library/LaunchAgents/com.vidgrab.app.plist
```

## Layout

```
server.py      FastAPI app wrapping yt-dlp — probe, queue, progress, file serving
index.html     the UI, single self-contained file
launch.sh      supervisor: app + tunnel + publishes the current address
install.sh     one-time setup and LaunchAgent installer
run.sh         local-only launcher, no tunnel
docs/          GitHub Pages launcher page and status.json
```

## Security

The tunnel URL is public, so `server.py` refuses every request without your
passphrase. The passphrase lives in `.vidgrab.env` (gitignored, `chmod 600`) and
in your browser's localStorage — never in this repo. `status.json` is public but
contains only the current tunnel address, which is useless without the
passphrase.

This is capability-style security appropriate for a personal tool, not a
hardened multi-user service. Don't hand the link and passphrase to people you
wouldn't hand your laptop to — downloads run as you, from your IP.

## Licence & scope

MIT. This is a tool; it has no idea what you're entitled to save. Your own posts,
public-domain and Creative Commons material, and content you have permission to
archive are fine. Redistributing other people's copyrighted video generally isn't,
and bulk downloading breaches most platforms' terms of service. That judgment is
yours.
