"""
core/tiktok_checker.py
----------------------
Lấy thông tin kênh TikTok: followers, likes, số video, ...

Chiến lược tốc độ:
  - tikwm giới hạn 1 request/giây (Free tier)
  - Dùng TokenBucket để dispatch request mỗi 1.1s
  - Các requests chạy song song (pipeline): request N+1 được gửi đi
    trong khi request N vẫn đang chờ phản hồi từ server (~8-10s)
  - Kết quả: N kênh ≈ N×1.1s + 10s (thay vì N×10s sequential)
  - Ví dụ 10 kênh: ~21s thay vì ~100s
"""

import re
import time
import threading
import random
import requests

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

TIKWM_USER_INFO_API = "https://www.tikwm.com/api/user/info"

# tikwm free tier: 1 req/s strict. Dùng 1.15s để có buffer nhỏ.
RATE_INTERVAL   = 1.15  # giây tối thiểu giữa 2 lần gửi request
REQUEST_TIMEOUT = 15    # giây timeout mỗi request
MAX_RETRIES     = 2     # số lần retry khi lỗi tạm thời

# Session dùng chung (HTTP connection pool, tái sử dụng TCP)
_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.tiktok.com",
    "Referer": "https://www.tiktok.com/",
})


# ─────────────────────────────────────────────────────────────────────────────
# Token Bucket Rate Limiter
# Đảm bảo tối đa 1 request gửi đi mỗi RATE_INTERVAL giây,
# nhưng không block thời gian chờ phản hồi (chỉ block lúc dispatch).
# ─────────────────────────────────────────────────────────────────────────────

class _RateLimiter:
    def __init__(self, interval: float):
        self._interval  = interval
        self._last_sent = 0.0
        self._lock      = threading.Lock()

    def acquire(self):
        """Block cho đến khi được phép gửi request tiếp theo."""
        with self._lock:
            now     = time.monotonic()
            wait    = self._interval - (now - self._last_sent)
            if wait > 0:
                time.sleep(wait)
            self._last_sent = time.monotonic()

_rate_limiter = _RateLimiter(RATE_INTERVAL)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_number(n) -> str:
    """Format số lớn thành dạng 1.2M / 345.6K / 1,234"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n) if n is not None else "—"
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return f"{n:,}"


def _extract_username(text: str) -> str:
    """Trích username từ URL hoặc @username hoặc username thuần."""
    text = text.strip().rstrip("/")
    m = re.search(r"tiktok\.com/@([\w.]+)", text)
    if m:
        return m.group(1)
    if text.startswith("@"):
        return text[1:]
    if re.match(r"^[\w.]+$", text):
        return text
    return ""


def _parse_tikwm_response(body: dict, username: str, username_or_url: str) -> dict | None:
    """Parse tikwm response body → dict kết quả. None nếu code != 0."""
    if body.get("code") != 0:
        return None

    data  = body.get("data", {})
    user  = data.get("user", {}) or data
    stats = data.get("stats", {}) or {}

    followers   = (stats.get("followerCount")  or user.get("follower_count") or user.get("fans_count")      or 0)
    following   = (stats.get("followingCount") or user.get("following_count")                               or 0)
    likes       = (stats.get("heartCount")     or stats.get("heart")         or user.get("total_favorited") or user.get("heart_count") or 0)
    video_count = (stats.get("videoCount")     or user.get("video_count")    or user.get("aweme_count")     or 0)
    nickname    = user.get("nickname") or user.get("name") or username
    bio         = user.get("signature") or user.get("bio", "")
    avatar_url  = (
        user.get("avatarLarger") or user.get("avatarMedium") or user.get("avatarThumb")
        or user.get("avatar_larger") or user.get("avatar_medium") or ""
    )
    verified = bool(user.get("verified") or user.get("custom_verify"))

    return {
        "input":           username_or_url,
        "username":        username,
        "nickname":        nickname,
        "followers":       followers,
        "following":       following,
        "likes":           likes,
        "video_count":     video_count,
        "bio":             bio,
        "avatar_url":      avatar_url,
        "verified":        verified,
        "status":          "ok",
        "followers_fmt":   _fmt_number(followers),
        "following_fmt":   _fmt_number(following),
        "likes_fmt":       _fmt_number(likes),
        "video_count_fmt": _fmt_number(video_count),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main checker  — thread-safe, rate-limited pipeline
# ─────────────────────────────────────────────────────────────────────────────

def fetch_channel_info(username_or_url: str,
                       progress_callback=None) -> dict:
    """
    Lấy thông tin kênh TikTok.

    Sử dụng rate limiter 1 req/s để không bị tikwm block.
    Các requests gửi tuần tự (1 req mỗi 1.1s) nhưng khi chạy
    nhiều kênh song song qua ThreadPoolExecutor, thời gian chờ phản
    hồi (~8-10s) overlap với thời gian dispatch → pipeline hiệu quả.

    Ví dụ 10 kênh:
      - Sequential: 10 × 10s = 100s
      - Pipeline:   10 × 1.1s + 10s ≈ 21s
    """
    username = _extract_username(username_or_url)
    if not username:
        return {
            "input":    username_or_url,
            "username": username_or_url,
            "status":   "error",
            "error":    "Không nhận dạng được username",
        }

    if progress_callback:
        progress_callback(f"🔍 Checking @{username}...")

    last_error = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            # Chờ token — đảm bảo ≤1 req/s gửi đến tikwm
            _rate_limiter.acquire()

            resp = _session.post(
                TIKWM_USER_INFO_API,
                data={"unique_id": username},
                timeout=REQUEST_TIMEOUT,
            )

            # HTTP 429 → wait & retry
            if resp.status_code == 429:
                wait = 3.0 * (attempt + 1) + random.uniform(0, 1)
                if progress_callback:
                    progress_callback(f"⚠️ Rate limit @{username}, thử lại sau {wait:.0f}s...")
                time.sleep(wait)
                last_error = "Rate limit (429)"
                continue

            # HTTP 5xx → retry
            if resp.status_code >= 500:
                wait = 2.0 * (attempt + 1)
                if progress_callback:
                    progress_callback(f"⚠️ Server error {resp.status_code}, thử lại...")
                time.sleep(wait)
                last_error = f"Server error ({resp.status_code})"
                continue

            resp.raise_for_status()
            body = resp.json()

            result = _parse_tikwm_response(body, username, username_or_url)
            if result:
                if progress_callback:
                    progress_callback(
                        f"✅ @{username}: {result['followers_fmt']} followers · "
                        f"{result['video_count_fmt']} videos"
                    )
                return result

            # tikwm trả code != 0
            last_error = body.get("msg", "tikwm error")
            err_lower  = last_error.lower()

            # Lỗi logic thật (không tồn tại) → dừng ngay
            if any(k in err_lower for k in ("not found", "does not exist", "user not found", "invalid")):
                if progress_callback:
                    progress_callback(f"❌ @{username}: {last_error}")
                break

            # Lỗi tạm thời (rate-limit message trong body) → retry
            wait = 2.5 * (attempt + 1) + random.uniform(0, 1)
            if progress_callback:
                progress_callback(f"⚠️ @{username}: {last_error} → thử lại sau {wait:.0f}s (lần {attempt+1})")
            time.sleep(wait)
            continue

        except requests.Timeout:
            last_error = "Timeout"
            if progress_callback:
                progress_callback(f"⚠️ @{username}: timeout (lần {attempt+1})")
            if attempt < MAX_RETRIES:
                time.sleep(2.0)
            continue

        except Exception as e:
            last_error = str(e)
            if progress_callback:
                progress_callback(f"⚠️ @{username}: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(1.5)
            continue

    return {
        "input":    username_or_url,
        "username": username,
        "status":   "error",
        "error":    last_error or "Không lấy được thông tin",
    }
