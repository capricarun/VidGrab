#!/usr/bin/env python3
"""
VidGrab - a local video downloader for X, Instagram, YouTube, TikTok, Reddit,
Facebook, Vimeo and ~1800 other sites (anything yt-dlp supports).

Run:  python3 server.py
Then open http://127.0.0.1:8420

Only download content you own or have the right to save.
"""

import os
import re
import sys
import json
import time
import shutil
import threading
import subprocess
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

try:
    import yt_dlp
except ImportError:
    sys.exit("Missing yt-dlp.  Install with:  pip3 install -U yt-dlp fastapi 'uvicorn[standard]'")

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

# ---------------------------------------------------------------- config

HERE = Path(__file__).resolve().parent
DOWNLOAD_DIR = Path(os.environ.get("VIDGRAB_DIR", HERE / "Downloads")).expanduser()
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("VIDGRAB_PORT", 8420))
HAS_FFMPEG = shutil.which("ffmpeg") is not None
STATE_FILE = DOWNLOAD_DIR / ".vidgrab-history.json"
# When set, every request must carry ?k=<token> or the cookie it plants.
# The launcher sets this automatically so the public tunnel isn't wide open.
TOKEN = os.environ.get("VIDGRAB_TOKEN", "").strip()

app = FastAPI(title="VidGrab")


@app.middleware("http")
async def gate(request, call_next):
    if not TOKEN:
        return await call_next(request)
    if request.cookies.get("vg") == TOKEN:
        return await call_next(request)
    if request.query_params.get("k") == TOKEN:
        resp = await call_next(request)
        resp.set_cookie("vg", TOKEN, max_age=60 * 60 * 24 * 365,
                        httponly=True, samesite="lax")
        return resp
    return HTMLResponse(
        "<body style='background:#0c0d10;color:#8b929c;font:15px/1.6 system-ui;"
        "display:grid;place-items:center;height:100vh;margin:0;text-align:center'>"
        "<div><div style='font-size:34px;margin-bottom:10px'>&#128274;</div>"
        "VidGrab is private.<br>Open it with your personal link.</div></body>",
        status_code=401)
POOL = ThreadPoolExecutor(max_workers=3)
JOBS = {}
LOCK = threading.Lock()

PLATFORMS = [
    (r"(youtube\.com|youtu\.be)", "YouTube"),
    (r"(twitter\.com|x\.com|t\.co)", "X"),
    (r"instagram\.com", "Instagram"),
    (r"tiktok\.com", "TikTok"),
    (r"(reddit\.com|redd\.it)", "Reddit"),
    (r"(facebook\.com|fb\.watch)", "Facebook"),
    (r"vimeo\.com", "Vimeo"),
    (r"twitch\.tv", "Twitch"),
    (r"dailymotion\.com", "Dailymotion"),
    (r"linkedin\.com", "LinkedIn"),
    (r"pinterest\.", "Pinterest"),
    (r"(threads\.net|threads\.com)", "Threads"),
    (r"snapchat\.com", "Snapchat"),
    (r"bsky\.app", "Bluesky"),
]


def platform_of(url: str) -> str:
    for pat, name in PLATFORMS:
        if re.search(pat, url, re.I):
            return name
    return "Web"


def save_history():
    try:
        with LOCK:
            done = [j for j in JOBS.values() if j["status"] in ("done", "error")][-100:]
        STATE_FILE.write_text(json.dumps(done, indent=1))
    except Exception:
        pass


def load_history():
    try:
        if STATE_FILE.exists():
            for j in json.loads(STATE_FILE.read_text()):
                JOBS[j["id"]] = j
    except Exception:
        pass


# ---------------------------------------------------------------- yt-dlp glue

def base_opts(cookies_browser: str | None = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": False,
        "retries": 5,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 30,
    }
    if cookies_browser and cookies_browser != "none":
        opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


def fmt_selector(quality: str) -> str:
    if quality == "audio":
        return "bestaudio/best"
    if quality == "best":
        return "bv*+ba/b" if HAS_FFMPEG else "b"
    h = quality.rstrip("p")
    if HAS_FFMPEG:
        return f"bv*[height<={h}]+ba/b[height<={h}]/b"
    return f"b[height<={h}]/b"


class ProbeReq(BaseModel):
    url: str
    cookies: str | None = "none"


class DownloadReq(BaseModel):
    url: str
    quality: str = "best"
    cookies: str | None = "none"
    subtitles: bool = False


@app.post("/api/probe")
def probe(req: ProbeReq):
    url = req.url.strip()
    if not url.startswith("http"):
        raise HTTPException(400, "That doesn't look like a URL.")
    opts = base_opts(req.cookies)
    opts["extract_flat"] = "in_playlist"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(400, clean_err(str(e)))

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        return {
            "kind": "playlist",
            "platform": platform_of(url),
            "title": info.get("title") or "Playlist",
            "count": len(entries),
            "thumbnail": (entries[0].get("thumbnails") or [{}])[-1].get("url") if entries else None,
            "items": [{"title": e.get("title"), "url": e.get("url") or e.get("webpage_url")}
                      for e in entries[:50]],
        }

    heights = sorted({f.get("height") for f in (info.get("formats") or [])
                      if f.get("height")}, reverse=True)
    return {
        "kind": "video",
        "platform": platform_of(url),
        "title": info.get("title") or "Untitled",
        "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "heights": heights[:8],
        "is_live": bool(info.get("is_live")),
    }


def clean_err(msg: str) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)
    msg = msg.replace("ERROR: ", "").strip()
    low = msg.lower()
    if "login" in low or "rate-limit" in low or "private" in low or "cookies" in low:
        return (msg.split("\n")[0] +
                "  →  Try setting 'Use cookies from' to the browser you're logged into.")
    if "unsupported url" in low:
        return "That site isn't supported (or the URL isn't a direct link to a post)."
    return msg.split("\n")[0][:400]


def run_job(job_id: str, url: str, quality: str, cookies: str, subs: bool):
    job = JOBS[job_id]

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            job["status"] = "downloading"
            job["percent"] = round(got / total * 100, 1) if total else 0
            job["speed"] = d.get("speed") or 0
            job["eta"] = d.get("eta")
            job["size"] = total
        elif d["status"] == "finished":
            job["status"] = "processing"
            job["percent"] = 100

    outtmpl = str(DOWNLOAD_DIR / "%(extractor_key)s" /
                  "%(uploader,channel,extractor_key)s" /
                  "%(title).120B [%(id)s].%(ext)s")

    opts = base_opts(cookies)
    opts.update({
        "outtmpl": outtmpl,
        "format": fmt_selector(quality),
        "progress_hooks": [hook],
        "postprocessor_hooks": [lambda d: hook({"status": "processing"})
                                if d.get("status") == "started" else None],
        "windowsfilenames": True,
        "restrictfilenames": False,
        "writethumbnail": False,
        "noplaylist": False,
    })
    if quality == "audio":
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                   "preferredcodec": "mp3",
                                   "preferredquality": "192"}] if HAS_FFMPEG else []
    elif HAS_FFMPEG:
        opts["merge_output_format"] = "mp4"
    if subs:
        opts.update({"writesubtitles": True, "writeautomaticsub": True,
                     "subtitleslangs": ["en.*"], "subtitlesformat": "srt/best"})

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist":
            entries = [e for e in (info.get("entries") or []) if e]
            job["title"] = info.get("title") or job["title"]
            job["count"] = len(entries)
            path = None
            if entries:
                path = entries[0].get("requested_downloads", [{}])[0].get("filepath")
                path = str(Path(path).parent) if path else None
        else:
            job["title"] = info.get("title") or job["title"]
            job["thumbnail"] = info.get("thumbnail") or job.get("thumbnail")
            rd = (info.get("requested_downloads") or [{}])[0]
            path = rd.get("filepath")
        job["path"] = path
        job["filename"] = Path(path).name if path else None
        if path and Path(path).is_file():
            job["size"] = Path(path).stat().st_size
        job["status"] = "done"
        job["percent"] = 100
    except Exception as e:
        job["status"] = "error"
        job["error"] = clean_err(str(e))
    job["finished_at"] = time.time()
    save_history()


@app.post("/api/download")
def download(req: DownloadReq):
    url = req.url.strip()
    if not url.startswith("http"):
        raise HTTPException(400, "That doesn't look like a URL.")
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {
        "id": job_id, "url": url, "platform": platform_of(url),
        "title": url, "quality": req.quality, "status": "queued",
        "percent": 0, "speed": 0, "eta": None, "size": 0,
        "path": None, "filename": None, "error": None,
        "created_at": time.time(),
    }
    POOL.submit(run_job, job_id, url, req.quality, req.cookies or "none", req.subtitles)
    return {"id": job_id}


@app.get("/api/jobs")
def jobs():
    js = sorted(JOBS.values(), key=lambda j: j["created_at"], reverse=True)
    return {"jobs": js[:60], "dir": str(DOWNLOAD_DIR), "ffmpeg": HAS_FFMPEG}


@app.post("/api/clear")
def clear():
    with LOCK:
        for k in [k for k, v in JOBS.items() if v["status"] in ("done", "error")]:
            JOBS.pop(k, None)
    save_history()
    return {"ok": True}


@app.get("/api/file/{job_id}")
def get_file(job_id: str):
    job = JOBS.get(job_id)
    if not job or not job.get("path") or not Path(job["path"]).is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(job["path"], filename=Path(job["path"]).name)


@app.post("/api/reveal/{job_id}")
def reveal(job_id: str):
    job = JOBS.get(job_id)
    target = job.get("path") if job else None
    target = target or str(DOWNLOAD_DIR)
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", target] if Path(target).is_file()
                           else ["open", target], check=False)
        elif sys.platform.startswith("win"):
            os.startfile(str(Path(target).parent))  # noqa
        else:
            subprocess.run(["xdg-open", str(Path(target).parent)], check=False)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return (HERE / "index.html").read_text()


if __name__ == "__main__":
    load_history()
    print(f"\n  VidGrab  →  http://127.0.0.1:{PORT}")
    print(f"  Saving to: {DOWNLOAD_DIR}")
    if not HAS_FFMPEG:
        print("  ⚠  ffmpeg not found — quality capped to single-file formats.")
        print("     Fix with:  brew install ffmpeg\n")
    else:
        print()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
