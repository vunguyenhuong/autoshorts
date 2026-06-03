"""
core/tiktok_douyin.py
---------------------
Downloads TikTok and Douyin videos WITHOUT watermark via tikwm.com API.

Rate-limit fix:
  - Global threading.Lock serializes all tikwm API calls (no parallel API hits).
  - Each call has a configurable delay + retry-with-backoff.
  - Only the actual file streaming (bytes download) runs in parallel threads.

403 channel fix:
  - Channel scan only returns video IDs/URLs (no pre-fetched play links).
  - At download time, we ALWAYS call tikwm freshly to get a live download URL.
"""

import os
import re
import sys
import time
import random
import shutil
import threading
import subprocess

import requests

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

TIKWM_API          = "https://www.tikwm.com/api/"
TIKWM_USER_API     = "https://www.tikwm.com/api/user/posts"
TIKWM_CALL_DELAY   = 1.5   # seconds between successive tikwm API calls
TIKWM_MAX_RETRIES  = 4
TIKWM_RETRY_DELAY  = 3.0   # base delay on retry (doubles each attempt)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.tiktok.com",
    "Referer": "https://www.tiktok.com/",
}

DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.tiktok.com/",
}

# Global lock: serialises all tikwm API calls across threads
_tikwm_api_lock = threading.Lock()
_tikwm_last_call = [0.0]   # mutable so threads share it


# ─────────────────────────────────────────────────────────────────────────────
# Core downloader class
# ─────────────────────────────────────────────────────────────────────────────

class TiktokDouyinDownloader:

    # ── Misc helpers ──────────────────────────────────────────────────────────

    def get_ytdlp_exe(self):
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
            for c in [os.path.join(base, "settings", "yt-dlp.exe"),
                      os.path.join(base, "yt-dlp.exe")]:
                if os.path.exists(c):
                    return c
            return "yt-dlp"
        if os.path.exists("settings/yt-dlp.exe"):
            return os.path.abspath("settings/yt-dlp.exe")
        if os.path.exists("yt-dlp.exe"):
            return os.path.abspath("yt-dlp.exe")
        return "yt-dlp"

    def _find_ffmpeg(self):
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for c in [os.path.join(base, "ffmpeg", "bin", "ffmpeg.exe"),
                  os.path.join(base, "ffmpeg", "ffmpeg.exe"),
                  os.path.join(base, "ffmpeg.exe")]:
            if os.path.exists(c):
                return os.path.dirname(c)
        exe = shutil.which("ffmpeg")
        return os.path.dirname(exe) if exe else None

    # ── URL classification ────────────────────────────────────────────────────

    def is_channel_url(self, url: str) -> bool:
        url = url.strip().rstrip("/")
        # Short redirect → single video
        if re.search(r"(vm|vt|m)\.tiktok\.com/", url):
            return False
        if re.search(r"v\.douyin\.com/", url):
            return False
        # Explicit single-video paths
        if re.search(r"tiktok\.com/.+/video/\d+", url):
            return False
        if re.search(r"douyin\.com/video/\d+", url):
            return False
        # Channel patterns
        if re.search(r"tiktok\.com/@[\w.]+$", url):
            return True
        if re.search(r"douyin\.com/(user/|@)", url):
            return True
        return False

    # ── Serialised tikwm API call ─────────────────────────────────────────────

    def _tikwm_call(self, endpoint: str, payload: dict,
                    progress_callback=None) -> dict | None:
        """
        Thread-safe, rate-limited POST to tikwm.
        - Acquires global lock so only one thread calls tikwm at a time.
        - Waits TIKWM_CALL_DELAY since the last call before firing.
        - Retries with exponential back-off on failure.
        """
        for attempt in range(TIKWM_MAX_RETRIES):
            with _tikwm_api_lock:
                # Throttle: wait since last call
                elapsed = time.time() - _tikwm_last_call[0]
                if elapsed < TIKWM_CALL_DELAY:
                    time.sleep(TIKWM_CALL_DELAY - elapsed)

                try:
                    resp = requests.post(
                        endpoint, data=payload,
                        headers=BROWSER_HEADERS, timeout=20
                    )
                    _tikwm_last_call[0] = time.time()

                    if resp.status_code == 429 or resp.status_code == 403:
                        raise requests.HTTPError(
                            f"HTTP {resp.status_code}", response=resp
                        )

                    resp.raise_for_status()
                    body = resp.json()
                    if body.get("code") == 0:
                        return body.get("data")

                    # tikwm returned an error code
                    msg = body.get("msg", "unknown error")
                    if progress_callback:
                        progress_callback(f"⚠️ tikwm: {msg} (attempt {attempt+1})")

                except Exception as e:
                    if progress_callback:
                        progress_callback(
                            f"⚠️ tikwm API error (attempt {attempt+1}): {e}"
                        )

            # Back-off outside the lock
            if attempt < TIKWM_MAX_RETRIES - 1:
                wait = TIKWM_RETRY_DELAY * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)

        return None

    # ── Single-video info ─────────────────────────────────────────────────────

    def get_video_info(self, url: str,
                       progress_callback=None) -> dict | None:
        """Fetch metadata for a single TikTok/Douyin URL via tikwm."""
        return self._tikwm_call(
            TIKWM_API, {"url": url, "hd": "1"},
            progress_callback=progress_callback
        )

    # ── Channel scan ──────────────────────────────────────────────────────────

    def fetch_channel_videos(self, channel_url: str,
                             limit: int = 0,
                             progress_callback=None) -> list[dict]:
        """
        Enumerate a TikTok channel via tikwm user/posts API.
        Returns list of {'id', 'url', 'title'} — NO pre-fetched play URLs
        (they expire; we re-fetch at download time).
        """
        m = re.search(r"@([\w.]+)", channel_url)
        username = m.group(1) if m else ""

        if not username:
            if progress_callback:
                progress_callback(f"❌ Không lấy được username từ: {channel_url}")
            return []

        collected = []
        cursor = 0
        page_size = 35

        while True:
            if limit and len(collected) >= limit:
                break

            payload = {
                "unique_id": username,
                "count": page_size,
                "cursor": cursor,
                "hd": "1",
            }
            data = self._tikwm_call(
                TIKWM_USER_API, payload,
                progress_callback=progress_callback
            )

            if not data:
                break

            videos   = data.get("videos", [])
            has_more = data.get("hasMore", False)
            cursor   = data.get("cursor", 0)

            if not videos:
                break

            for v in videos:
                vid_id = str(v.get("video_id") or v.get("id") or "")
                if not vid_id:
                    continue
                collected.append({
                    "id":    vid_id,
                    "url":   f"https://www.tiktok.com/@{username}/video/{vid_id}",
                    "title": v.get("title", ""),
                })
                if limit and len(collected) >= limit:
                    break

            if progress_callback:
                progress_callback(f"  📋 Đã quét: {len(collected)} video...")

            if not has_more:
                break

        if progress_callback:
            progress_callback(
                f"✅ Kênh @{username}: tìm thấy {len(collected)} video"
            )
        return collected[:limit] if limit else collected

    def fetch_channel_ytdlp(self, channel_url: str,
                             limit: int = 0,
                             progress_callback=None) -> list[dict]:
        """Fallback: enumerate Douyin channel with yt-dlp flat-extract."""
        import yt_dlp

        opts = {
            "extract_flat": True,
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "http_headers": BROWSER_HEADERS,
        }
        if limit and limit > 0:
            opts["playlistend"] = limit

        if progress_callback:
            progress_callback(f"🔍 yt-dlp: đang quét {channel_url}...")

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info(channel_url, download=False)

            results = []
            if data and "entries" in data:
                for entry in data["entries"]:
                    if not entry:
                        continue
                    vid_url = (
                        entry.get("url")
                        or entry.get("webpage_url")
                        or ""
                    )
                    if vid_url:
                        results.append({
                            "id":    entry.get("id", ""),
                            "url":   vid_url,
                            "title": entry.get("title", ""),
                        })
            if progress_callback:
                progress_callback(f"✅ yt-dlp: {len(results)} video")
            return results[:limit] if limit else results

        except Exception as e:
            if progress_callback:
                progress_callback(f"❌ yt-dlp scan: {e}")
            return []

    # ── Download a single video ───────────────────────────────────────────────

    def download_video(self, url: str, output_dir: str,
                       progress_callback=None) -> tuple[bool, str]:
        """
        Download one TikTok/Douyin video.
        Always fetches a fresh tikwm info → no expired URL issues.
        Falls back to yt-dlp if tikwm fails entirely.
        """
        os.makedirs(output_dir, exist_ok=True)

        # Fresh info fetch (serialised via lock, so no parallel API spam)
        info = self.get_video_info(url, progress_callback=progress_callback)

        if not info:
            if progress_callback:
                progress_callback("⚠️ tikwm thất bại, thử yt-dlp...")
            return self._download_via_ytdlp(url, output_dir, progress_callback)

        # Best URL: hdplay > play > wmplay
        video_url = (
            info.get("hdplay")
            or info.get("play")
            or info.get("wmplay", "")
        )
        if not video_url:
            if progress_callback:
                progress_callback("❌ tikwm: không có link video")
            return self._download_via_ytdlp(url, output_dir, progress_callback)

        vid_id = str(info.get("id", ""))
        title  = info.get("title", "") or vid_id
        safe   = re.sub(r'[<>:"/\\|?*\n\r]', '', title)
        safe   = re.sub(r'\s+', ' ', safe).strip()[:80] or vid_id

        filename = f"{safe}.mp4"
        filepath  = os.path.join(output_dir, filename)
        counter   = 1
        while os.path.exists(filepath):
            filename = f"{safe} ({counter}).mp4"
            filepath  = os.path.join(output_dir, filename)
            counter  += 1

        # Stream the file (this part CAN be parallel — it's just HTTP streaming)
        for attempt in range(3):
            try:
                with requests.get(
                    video_url,
                    headers=DOWNLOAD_HEADERS,
                    stream=True,
                    timeout=120,
                ) as r:
                    r.raise_for_status()
                    with open(filepath, "wb") as f:
                        for chunk in r.iter_content(chunk_size=512 * 1024):
                            if chunk:
                                f.write(chunk)

                size = os.path.getsize(filepath)
                if size < 10_000:
                    os.remove(filepath)
                    raise ValueError(f"File quá nhỏ: {size} bytes")

                return True, filename

            except Exception as e:
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                if attempt < 2:
                    if progress_callback:
                        progress_callback(
                            f"⚠️ Stream lỗi (lần {attempt+1}): {e} — thử lại..."
                        )
                    time.sleep(2)
                else:
                    if progress_callback:
                        progress_callback(
                            f"⚠️ Stream thất bại sau 3 lần, thử yt-dlp: {e}"
                        )
                    return self._download_via_ytdlp(
                        url, output_dir, progress_callback
                    )

        return False, ""

    # ── yt-dlp fallback ───────────────────────────────────────────────────────

    def _download_via_ytdlp(self, url: str, output_dir: str,
                             progress_callback=None) -> tuple[bool, str]:
        ytdlp  = self.get_ytdlp_exe()
        ffmpeg = self._find_ffmpeg()

        cmd = [
            ytdlp, "--no-playlist",
            "-f", (
                "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height<=1080]+bestaudio/"
                "best[height<=1080]/best"
            ),
            "--merge-output-format", "mp4",
            "-o", os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s"),
            "--retries", "5",
            "--quiet", "--no-warnings",
        ]
        if ffmpeg:
            cmd += ["--ffmpeg-location", ffmpeg]
        cmd.append(url)

        try:
            kwargs = {"capture_output": True, "text": True, "timeout": 300}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            subprocess.run(cmd, **kwargs)

            now  = time.time()
            best = None
            bt   = 0
            for f in os.listdir(output_dir):
                if f.endswith(".mp4"):
                    fp = os.path.join(output_dir, f)
                    mt = os.path.getmtime(fp)
                    if now - mt < 300 and mt > bt:
                        bt   = mt
                        best = f
            if best:
                return True, best

            if progress_callback:
                progress_callback("❌ yt-dlp: không tìm thấy file sau khi tải")
            return False, ""

        except Exception as e:
            if progress_callback:
                progress_callback(f"❌ yt-dlp exception: {e}")
            return False, ""
