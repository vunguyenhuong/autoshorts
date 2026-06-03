"""
YouTube Channel Search — core/yt_search.py
==========================================
Tìm kiếm kênh YouTube theo 2 phương thức:
  A. yt-dlp (không cần API key) — dùng YouTube Search URL + ytsearch
  B. YouTube Data API v3 (cần API key) — search.list + channels.list
     Ưu điểm: chính xác hơn, filter quốc gia/sub trực tiếp, quota rõ ràng.

Chiến lược yt-dlp:
  1. Tìm theo từ khóa + quốc gia: dùng YouTube Search URL với tham số gl/hl
  2. Tìm kênh liên quan: extract tên kênh → tìm kiếm lại cùng gl/hl
"""

from __future__ import annotations

import re
import sys
import os
import urllib.parse
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class ChannelInfo:
    name: str = ""
    handle: str = ""              # @username hoặc channel_id
    description: str = ""
    subscribers: str = ""         # hiển thị dạng "1.2M subs"
    url: str = ""
    channel_id: str = ""
    thumbnail_url: str = ""
    country: str = ""             # gl code dùng khi tìm kiếm
    channel_country_code: str = "" # country code thực tế từ YouTube (DE, US...)
    subscriber_count_num: int = 0  # số sub thực tế (numeric)


# ── Country / Language presets ────────────────────────────────────────────────
# Format: code -> (gl, hl, display_label)
#   gl  = geographic location (YouTube region)
#   hl  = interface language (YouTube UI language)

# Mapping ISO code -> tên hiển thị tiếng Việt
COUNTRY_CODE_DISPLAY: dict[str, str] = {
    "US": "🇺🇸 Mỹ",   "GB": "🇬🇧 Anh",   "AU": "🇦🇺 Úc",
    "DE": "🇩🇪 Đức",   "AT": "🇦🇹 Áo",   "FR": "🇫🇷 Pháp",
    "ES": "🇪🇸 TBN",   "MX": "🇲🇽 Mexico", "BR": "🇧🇷 Brazil",
    "IT": "🇮🇹 Ý",    "RU": "🇷🇺 Nga",   "JP": "🇯🇵 Nhật",
    "KR": "🇰🇷 HQ",   "TW": "🇹🇼 Đài Loan","CN": "🇨🇳 TQ",
    "IN": "🇮🇳 Ấn Độ","VN": "🇻🇳 Việt Nam","TH": "🇹🇭 Thái",
    "ID": "🇮🇩 Indo", "PH": "🇵🇭 PH",   "TR": "🇹🇷 Thổ",
    "SA": "🇸🇦 Ả Rập","NL": "🇳🇱 HLan",  "PL": "🇵🇱 BLan",
    "SE": "🇸🇪 Thụy Điển","NO": "🇳🇴 Na Uy","CA": "🇨🇦 Canada",
    "CH": "🇨🇭 Thụy Sĩ","BE": "🇧🇪 Bỉ",  "PT": "🇵🇹 Bồ Đào Nha",
}

COUNTRY_PRESETS: dict[str, Tuple[str, str, str]] = {
    "all": ("",   "",      "🌍  Tất cả quốc gia"),
    "US":  ("US", "en",    "🇺🇸  Mỹ  (English)"),
    "GB":  ("GB", "en-GB", "🇬🇧  Anh  (English UK)"),
    "AU":  ("AU", "en-AU", "🇦🇺  Úc  (English AU)"),
    "DE":  ("DE", "de",    "🇩🇪  Đức  (Deutsch)"),
    "AT":  ("AT", "de",    "🇦🇹  Áo  (Deutsch AT)"),
    "FR":  ("FR", "fr",    "🇫🇷  Pháp  (Français)"),
    "ES":  ("ES", "es",    "🇪🇸  Tây Ban Nha  (Español)"),
    "MX":  ("MX", "es",    "🇲🇽  Mexico  (Español MX)"),
    "BR":  ("BR", "pt-BR", "🇧🇷  Brazil  (Português)"),
    "IT":  ("IT", "it",    "🇮🇹  Ý  (Italiano)"),
    "RU":  ("RU", "ru",    "🇷🇺  Nga  (Русский)"),
    "JP":  ("JP", "ja",    "🇯🇵  Nhật  (日本語)"),
    "KR":  ("KR", "ko",    "🇰🇷  Hàn Quốc  (한국어)"),
    "TW":  ("TW", "zh-TW", "🇹🇼  Đài Loan  (繁體中文)"),
    "CN":  ("CN", "zh-CN", "🇨🇳  Trung Quốc  (普通话)"),
    "IN":  ("IN", "hi",    "🇮🇳  Ấn Độ  (हिन्दी)"),
    "VN":  ("VN", "vi",    "🇻🇳  Việt Nam  (Tiếng Việt)"),
    "TH":  ("TH", "th",    "🇹🇭  Thái Lan  (ภาษาไทย)"),
    "ID":  ("ID", "id",    "🇮🇩  Indonesia  (Bahasa Indonesia)"),
    "PH":  ("PH", "en",    "🇵🇭  Philippines  (Filipino)"),
    "TR":  ("TR", "tr",    "🇹🇷  Thổ Nhĩ Kỳ  (Türkçe)"),
    "SA":  ("SA", "ar",    "🇸🇦  Ả Rập Saudi  (العربية)"),
    "NL":  ("NL", "nl",    "🇳🇱  Hà Lan  (Nederlands)"),
    "PL":  ("PL", "pl",    "🇵🇱  Ba Lan  (Polski)"),
    "SE":  ("SE", "sv",    "🇸🇪  Thụy Điển  (Svenska)"),
    "NO":  ("NO", "no",    "🇳🇴  Na Uy  (Norsk)"),
    "CA":  ("CA", "en",    "🇨🇦  Canada  (English CA)"),
}


def get_country_labels() -> List[str]:
    """Trả về danh sách label hiển thị cho ComboBox."""
    return [v[2] for v in COUNTRY_PRESETS.values()]


def get_country_code_by_label(label: str) -> str:
    """Tra cứu country preset code từ label hiển thị."""
    for code, (gl, hl, lbl) in COUNTRY_PRESETS.items():
        if lbl == label:
            return code
    return "all"


def get_gl_hl(preset_code: str) -> Tuple[str, str]:
    """Trả về (gl, hl) từ preset code."""
    if preset_code in COUNTRY_PRESETS:
        gl, hl, _ = COUNTRY_PRESETS[preset_code]
        return gl, hl
    return "", ""


# ── yt-dlp helpers ────────────────────────────────────────────────────────────

def _ydl_opts_base(gl: str = "", hl: str = "") -> dict:
    """Base yt-dlp options, optionally with country/language."""
    opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept-Language': f'{hl},en;q=0.5' if hl else 'en-US,en;q=0.9',
        },
    }
    # yt-dlp extractor args for YouTube region/language
    if gl or hl:
        extractor_args: dict = {}
        if gl:
            extractor_args['gl'] = [gl]
        if hl:
            extractor_args['hl'] = [hl]
            extractor_args['lang'] = [hl]
        opts['extractor_args'] = {'youtube': extractor_args}

    return opts


def _fmt_subscribers(n) -> str:
    """Format subscriber count to human-readable string."""
    if n is None:
        return ""
    try:
        n = int(n)
    except (ValueError, TypeError):
        return str(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M subs"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K subs"
    return f"{n} subs"


def _build_channel_info(entry: dict) -> Optional[ChannelInfo]:
    """Build ChannelInfo from a flat yt-dlp entry."""
    if not entry:
        return None

    channel_id = entry.get('channel_id') or ""
    name = entry.get('channel') or entry.get('uploader') or ""
    if not name or not channel_id:
        return None

    ch = ChannelInfo()
    ch.channel_id = channel_id
    ch.name = name
    ch.url = entry.get('channel_url') or entry.get('uploader_url') or ""
    if not ch.url and channel_id:
        ch.url = f"https://www.youtube.com/channel/{channel_id}"

    # Normalize URL to @handle
    uploader_id = entry.get('uploader_id') or ""
    if uploader_id.startswith("@"):
        ch.handle = uploader_id
        ch.url = f"https://www.youtube.com/{uploader_id}"
    elif ch.url:
        m = re.search(r"(@[\w.\-]+)", ch.url)
        if m:
            ch.handle = m.group(1)

    # Description (from video)
    desc = entry.get('description') or ""
    ch.description = desc[:200] if desc else ""

    # Thumbnail
    thumbs = entry.get('thumbnails') or []
    if thumbs and isinstance(thumbs[-1], dict):
        ch.thumbnail_url = thumbs[-1].get('url', '')

    return ch


# ── Public API ─────────────────────────────────────────────────────────────────

def search_channels(
    keyword: str,
    max_results: int = 20,
    gl: str = "",
    hl: str = "",
    candidates_multiplier: int = 1,
) -> List[ChannelInfo]:
    """
    Tìm kiếm kênh YouTube theo từ khóa, có hỗ trợ lọc theo quốc gia.

    Khi có gl/hl: dùng YouTube Search URL với sp=EgIQAg (filter channel) + gl/hl.
    Fallback sang ytsearchN nếu URL search trả ít kết quả.

    Args:
        keyword:              Từ khóa tìm kiếm
        max_results:          Số kênh tối đa muốn trả về
        gl:                   YouTube geographic location code (ví dụ: 'DE', 'US')
        hl:                   YouTube interface language code (ví dụ: 'de', 'en')
        candidates_multiplier: Nhân số lượng ứng viên cần tìm (dùng khi có sub filter để bù lại sau lọc)

    Returns:
        Danh sách ChannelInfo unique theo channel_id
    """
    if not keyword.strip():
        return []

    import yt_dlp

    # Khi có sub filter, tìm nhiều ứng viên hơn để bù lại việc bị lọc
    fetch_limit = max_results * candidates_multiplier
    search_count = fetch_limit * 4
    ydl_opts = _ydl_opts_base(gl=gl, hl=hl)
    channels_map: dict[str, ChannelInfo] = {}

    def _extract_channels_from_data(data) -> int:
        """Parse entries và thêm vào channels_map. Trả về số kênh đã thêm."""
        added = 0
        for entry in (data.get('entries') or []):
            if not entry:
                continue
            # Nếu entry là playlist/channel page, đi vào entries con
            if entry.get('_type') == 'playlist' and 'entries' in entry:
                for sub in (entry.get('entries') or []):
                    ch = _build_channel_info(sub)
                    if ch and ch.channel_id not in channels_map:
                        if gl:
                            ch.country = gl
                        channels_map[ch.channel_id] = ch
                        added += 1
                        if len(channels_map) >= fetch_limit:
                            return added
                continue
            ch = _build_channel_info(entry)
            if not ch or ch.channel_id in channels_map:
                continue
            if gl:
                ch.country = gl
            channels_map[ch.channel_id] = ch
            added += 1
            if len(channels_map) >= fetch_limit:
                return added
        return added

    # Strategy 1: URL search với sp=EgIQAg (channel-only filter)
    if gl or hl:
        encoded_kw = urllib.parse.quote_plus(keyword.strip())
        params = f"search_query={encoded_kw}&sp=EgIQAg"  # EgIQAg = channel filter
        if gl:
            params += f"&gl={gl}"
        if hl:
            params += f"&hl={hl}"
        search_url = f"https://www.youtube.com/results?{params}"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data = ydl.extract_info(search_url, download=False)
            if data:
                _extract_channels_from_data(data)
        except Exception:
            pass

    # Strategy 2: ytsearchN (luôn chạy nếu chưa đủ kênh)
    if len(channels_map) < fetch_limit:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data2 = ydl.extract_info(f"ytsearch{search_count}:{keyword}", download=False)
            if data2:
                _extract_channels_from_data(data2)
        except Exception:
            pass

    # Strategy 3: URL search không có sp filter (bắt thêm kênh)
    if len(channels_map) < fetch_limit and (gl or hl):
        encoded_kw = urllib.parse.quote_plus(keyword.strip())
        params = f"search_query={encoded_kw}"
        if gl:
            params += f"&gl={gl}"
        if hl:
            params += f"&hl={hl}"
        search_url2 = f"https://www.youtube.com/results?{params}"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data3 = ydl.extract_info(search_url2, download=False)
            if data3:
                _extract_channels_from_data(data3)
        except Exception:
            pass

    # Strategy 4: Nếu có gl, thêm tên quốc gia/ngôn ngữ vào keyword để tìm rộng hơn
    if len(channels_map) < fetch_limit and gl:
        _GL_SEARCH_SUFFIX: dict[str, str] = {
            "US": "english", "GB": "english uk", "AU": "australia",
            "DE": "deutsch", "FR": "francais", "ES": "español",
            "JP": "japanese", "KR": "korean", "CN": "chinese",
            "BR": "brazil", "IN": "india", "VN": "vietnam",
            "CA": "canada", "MX": "mexico",
        }
        suffix = _GL_SEARCH_SUFFIX.get(gl.upper(), "")
        if suffix:
            kw2 = f"{keyword.strip()} {suffix}"
            encoded_kw2 = urllib.parse.quote_plus(kw2)
            params2 = f"search_query={encoded_kw2}&sp=EgIQAg"
            params2 += f"&gl={gl}"
            if hl:
                params2 += f"&hl={hl}"
            search_url3 = f"https://www.youtube.com/results?{params2}"
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    data4 = ydl.extract_info(search_url3, download=False)
                if data4:
                    _extract_channels_from_data(data4)
            except Exception:
                pass

    return list(channels_map.values())[:fetch_limit]


def get_channel_details(channel_url: str, gl: str = "", hl: str = "") -> Optional[ChannelInfo]:
    """
    Lấy thông tin chi tiết của một kênh (tên, subscribers, description).

    Args:
        channel_url: URL kênh YouTube
        gl, hl:      Country/language context (truyền vào nếu có)

    Returns:
        ChannelInfo hoặc None nếu không lấy được
    """
    import yt_dlp

    url = channel_url.strip().rstrip("/")
    url = re.sub(r"/(shorts|videos|playlists|community|about|channels)$", "", url)

    ydl_opts = _ydl_opts_base(gl=gl, hl=hl)
    ydl_opts['playlistend'] = 3

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url + "/videos", download=False)

        if not data:
            return None

        ch = ChannelInfo()
        ch.name = data.get('channel') or data.get('uploader') or data.get('title') or ""
        ch.channel_id = data.get('channel_id') or data.get('uploader_id') or ""
        ch.url = data.get('channel_url') or data.get('uploader_url') or channel_url
        ch.description = (data.get('description') or "")[:200]

        sub = data.get('channel_follower_count') or data.get('subscriber_count')
        ch.subscribers = _fmt_subscribers(sub)

        uploader_id = data.get('uploader_id') or ""
        if uploader_id.startswith("@"):
            ch.handle = uploader_id
        else:
            m = re.search(r"(@[\w.\-]+)", ch.url)
            if m:
                ch.handle = m.group(1)

        return ch if ch.name else None

    except Exception:
        return None


def search_channels_multi(
    keywords: List[str],
    max_results: int = 20,
    gl: str = "",
    hl: str = "",
    progress_cb=None,          # callable(keyword_done: int, keyword_total: int)
    candidates_multiplier: int = 1,
) -> List[ChannelInfo]:
    """
    Tìm kênh theo NHIỀU từ khóa (phân cách bằng dấu phẩy).

    - Mỗi từ khóa được search song song (ThreadPoolExecutor).
    - Kết quả được merge và deduplicate theo channel_id.
    - Thứ tự ưu tiên: keyword đầu tiên tìm được kênh nào thì kênh đó
      lên trước, đảm bảo đa dạng (round-robin interleave).

    Args:
        keywords:             Danh sách từ khóa (đã strip)
        max_results:          Tổng số kênh tối đa trả về
        gl, hl:               Quốc gia/ngôn ngữ
        progress_cb:          callable(done, total) để báo tiến trình
        candidates_multiplier: Nhân số ứng viên (dùng khi có sub filter)

    Returns:
        Danh sách ChannelInfo unique, tối đa max_results
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    kws = [k.strip() for k in keywords if k.strip()]
    if not kws:
        return []

    # Mỗi keyword lấy thêm để sau khi merge vẫn đủ max_results
    per_kw = max(max_results, max_results * 2 // len(kws) + 5)

    done_count = [0]
    total_kws = len(kws)
    results_by_kw: dict[str, List[ChannelInfo]] = {}

    def _search_one(kw: str) -> tuple[str, List[ChannelInfo]]:
        try:
            return kw, search_channels(kw, per_kw, gl=gl, hl=hl,
                                       candidates_multiplier=candidates_multiplier)
        except Exception:
            return kw, []
        finally:
            done_count[0] += 1
            if progress_cb:
                try:
                    progress_cb(done_count[0], total_kws)
                except Exception:
                    pass

    with ThreadPoolExecutor(max_workers=min(len(kws), 4)) as ex:
        futures = {ex.submit(_search_one, kw): kw for kw in kws}
        for f in as_completed(futures):
            try:
                kw, chs = f.result()
                results_by_kw[kw] = chs
            except Exception:
                pass

    # Round-robin interleave: lấy 1 kênh từ mỗi keyword theo thứ tự vòng
    seen_ids: dict[str, ChannelInfo] = {}
    lists = [results_by_kw.get(kw, []) for kw in kws]
    max_len = max((len(l) for l in lists), default=0)

    fetch_limit = max_results * candidates_multiplier
    for i in range(max_len):
        for lst in lists:
            if i < len(lst):
                ch = lst[i]
                if ch.channel_id and ch.channel_id not in seen_ids:
                    seen_ids[ch.channel_id] = ch
                    if len(seen_ids) >= fetch_limit:
                        return list(seen_ids.values())

    return list(seen_ids.values())[:fetch_limit]


def get_related_channels(
    channel_url: str,
    max_results: int = 20,
    gl: str = "",
    hl: str = "",
) -> List[ChannelInfo]:
    """
    Tìm các kênh liên quan dựa trên một kênh cho trước.

    Chiến lược:
    1. Lấy tên kênh gốc từ channel_url
    2. Tìm kiếm bằng tên kênh với cùng gl/hl để tìm kênh cùng niche và vùng
    3. Loại bỏ kênh gốc khỏi kết quả

    Args:
        channel_url: URL kênh YouTube
        max_results: Số kênh tối đa
        gl, hl:      Country/language filter

    Returns:
        Danh sách ChannelInfo (không gồm kênh gốc)
    """
    url = channel_url.strip().rstrip("/")
    url = re.sub(r"/(shorts|videos|playlists|community|about|channels)$", "", url)

    # Bước 1: Lấy tên và ID kênh gốc
    source_ch = get_channel_details(url, gl=gl, hl=hl)
    source_id = source_ch.channel_id if source_ch else ""
    source_name = source_ch.name if source_ch else ""

    # Fallback: extract từ URL
    if not source_name:
        m = re.search(r"(@[\w.\-]+)", url)
        if m:
            source_name = m.group(1).lstrip("@").replace("-", " ").replace("_", " ").title()
        else:
            segs = url.rstrip("/").split("/")
            source_name = segs[-1] if segs else "channel"

    # Bước 2: Tìm kiếm cùng gl/hl
    results = search_channels(source_name, max_results=max_results + 5, gl=gl, hl=hl)

    # Bước 3: Loại bỏ kênh gốc và deduplicate
    filtered = []
    seen_ids: set[str] = set()
    for ch in results:
        if ch.channel_id == source_id:
            continue
        norm_url = ch.url.rstrip("/").lower()
        if norm_url in seen_ids:
            continue
        seen_ids.add(norm_url)
        filtered.append(ch)
        if len(filtered) >= max_results:
            break

    return filtered


# ── Browser opener ─────────────────────────────────────────────────────────────

def open_url_in_browser(url: str) -> None:
    """
    Mở URL trong Chrome (nếu có) hoặc trình duyệt mặc định.
    """
    import subprocess
    import shutil
    import webbrowser

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Users\{}\AppData\Local\Google\Chrome\Application\chrome.exe".format(
            os.environ.get("USERNAME", "")
        ),
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]

    for path in chrome_paths:
        if path and os.path.exists(path):
            try:
                subprocess.Popen(
                    [path, url],
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                return
            except Exception:
                continue

    # Fallback: hệ thống mặc định
    webbrowser.open(url)


# ── Metadata batch fetcher ─────────────────────────────────────────────────────

def fetch_channel_metadata(channel_url: str, gl: str = "") -> tuple[str, int]:
    """
    Lấy country_code thực tế và subscriber_count của một kênh.
    Returns: (country_code, subscriber_count_num)
    """
    import yt_dlp

    url = channel_url.strip().rstrip("/")
    url = re.sub(r"/(shorts|videos|playlists|community|about|channels)$", "", url)

    sub_count = 0
    country_code = ""

    # extract_flat='in_playlist': entries lấy flat (nhanh), channel dict lấy full
    # playlistend=1: chỉ xử lý 1 video entry (tránh mất thời gian)
    opts = {
        'extract_flat': 'in_playlist',
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'playlistend': 1,
        'skip_download': True,
    }
    if gl:
        opts['extractor_args'] = {'youtube': {'gl': [gl]}}

    # Thử từng URL variant — /about thường nhanh nhất
    for suffix in ["/about", "", "/videos"]:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                d = ydl.extract_info(url + suffix, download=False)
            if not d:
                continue

            # channel_follower_count có ở top-level dict (không phải trong entries)
            sub_count = int(
                d.get('channel_follower_count') or
                d.get('subscriber_count') or 0
            )

            # Nếu d là playlist, thử entries[0] để lấy channel info
            if sub_count == 0 and d.get('entries'):
                first = d['entries'][0] if d['entries'] else None
                if first:
                    sub_count = int(
                        first.get('channel_follower_count') or
                        first.get('subscriber_count') or 0
                    )

            # Lấy country từ YouTube field thực (channel_location, uploader_country, ...)
            raw_country = (
                d.get('channel_location') or
                d.get('uploader_country') or
                d.get('location') or
                d.get('country') or
                ""
            )
            if raw_country:
                rc = raw_country.strip()
                if len(rc) == 2:
                    country_code = rc.upper()
                else:
                    country_code = _COUNTRY_NAME_TO_CODE.get(rc.lower(), "")

            # Fallback: heuristic từ tags + description
            if not country_code:
                tags = [t.lower() for t in (d.get('tags') or [])]
                desc = (d.get('description') or "").lower()
                country_code = _detect_country_from_content(tags, desc)

            if sub_count > 0:
                break
        except Exception:
            continue

    return country_code, sub_count


def _detect_country_from_content(tags: list[str], desc: str) -> str:
    """
    Detect country code từ tags và description của kênh.
    Dựa trên các từ khóa ngôn ngữ/quốc gia phổ biến.
    """
    combined = " ".join(tags) + " " + desc[:500]

    # Language-specific character sets
    if re.search(r'[\u4e00-\u9fff]', combined):  # CJK
        if re.search(r'[\u3040-\u309f\u30a0-\u30ff]', combined):
            return "JP"
        if re.search(r'[\uac00-\ud7af]', combined):
            return "KR"
        return "CN"
    if re.search(r'[\u0e00-\u0e7f]', combined):  # Thai
        return "TH"
    if re.search(r'[\u0600-\u06ff]', combined):  # Arabic
        return "SA"
    if re.search(r'[\u0400-\u04ff]', combined):  # Cyrillic
        return "RU"
    if re.search(r'[\u0900-\u097f]', combined):  # Devanagari
        return "IN"

    # Keyword-based detection
    _KW_MAP = {
        "DE": ["deutsch", "german", "deutschland", "österreich", "schweiz",
               "rezept", "kochen", "kanal", "folge"],
        "FR": ["français", "france", "french", "recette", "cuisine française"],
        "ES": ["español", "spain", "españa", "receta", "cocina"],
        "IT": ["italiano", "italy", "italia", "ricetta", "cucina"],
        "PT": ["português", "portugal", "brazil", "brasil"],
        "NL": ["nederland", "dutch", "netherlands", "vlaams"],
        "PL": ["polski", "poland", "polska"],
        "TR": ["türkçe", "turkey", "türkiye"],
        "KR": ["korean", "korea", "한국"],
        "JP": ["japanese", "japan", "日本"],
        "VN": ["việt", "vietnam", "tiếng việt"],
        "TH": ["thai", "thailand", "ไทย"],
        "ID": ["indonesia", "bahasa"],
        "US": ["american", "usa", "united states", "english"],
        "GB": ["british", "uk", "united kingdom", "england"],
        "AU": ["australia", "aussie"],
        "IN": ["hindi", "india", "indian"],
    }
    for code, keywords in _KW_MAP.items():
        for kw in keywords:
            if kw in combined:
                return code

    return ""



# English country name → ISO 2-letter code
_COUNTRY_NAME_TO_CODE: dict[str, str] = {
    "afghanistan": "AF", "albania": "AL", "algeria": "DZ", "argentina": "AR",
    "australia": "AU", "austria": "AT", "bangladesh": "BD", "belgium": "BE",
    "brazil": "BR", "bulgaria": "BG", "canada": "CA", "chile": "CL",
    "china": "CN", "colombia": "CO", "croatia": "HR", "czech republic": "CZ",
    "denmark": "DK", "egypt": "EG", "finland": "FI", "france": "FR",
    "germany": "DE", "ghana": "GH", "greece": "GR", "hungary": "HU",
    "india": "IN", "indonesia": "ID", "iran": "IR", "iraq": "IQ",
    "ireland": "IE", "israel": "IL", "italy": "IT", "japan": "JP",
    "jordan": "JO", "kenya": "KE", "south korea": "KR", "kuwait": "KW",
    "lebanon": "LB", "malaysia": "MY", "mexico": "MX", "morocco": "MA",
    "netherlands": "NL", "new zealand": "NZ", "nigeria": "NG", "norway": "NO",
    "pakistan": "PK", "peru": "PE", "philippines": "PH", "poland": "PL",
    "portugal": "PT", "romania": "RO", "russia": "RU", "saudi arabia": "SA",
    "serbia": "RS", "singapore": "SG", "south africa": "ZA", "spain": "ES",
    "sweden": "SE", "switzerland": "CH", "taiwan": "TW", "thailand": "TH",
    "turkey": "TR", "ukraine": "UA", "united arab emirates": "AE",
    "united kingdom": "GB", "united states": "US", "venezuela": "VE",
    "vietnam": "VN", "vietnam": "VN",
}




def fetch_channel_metadata_batch(
    channels: List[ChannelInfo],
    max_workers: int = 5,
    progress_cb=None,          # callable(current: int, total: int)
) -> List[ChannelInfo]:
    """
    Fetch country + subscriber_count cho từng kênh trong danh sách (song song).
    Cập nhật trực tiếp channel_country_code và subscriber_count_num.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    total = len(channels)
    done_count = [0]

    def _fetch(ch: ChannelInfo):
        try:
            country, sub_num = fetch_channel_metadata(ch.url)
            ch.channel_country_code = country
            ch.subscriber_count_num = sub_num
            # Luôn cập nhật subscribers nếu fetch được (không check ch.subscribers cũ)
            if sub_num > 0:
                ch.subscribers = _fmt_subscribers(sub_num)
        except Exception:
            pass
        finally:
            done_count[0] += 1
            if progress_cb:
                try:
                    progress_cb(done_count[0], total)
                except Exception:
                    pass
        return ch

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch, ch): ch for ch in channels}
        for f in as_completed(futures):
            try:
                f.result()
            except Exception:
                pass

    return channels


# ══════════════════════════════════════════════════════════════════════════════
# ██  YOUTUBE DATA API v3  ██
# ══════════════════════════════════════════════════════════════════════════════
#
# Tìm kênh qua YouTube Data API v3 (search.list + channels.list).
# Ưu điểm so với yt-dlp:
#   - Chính xác: chỉ trả kênh, không lẫn video
#   - Region filter qua regionCode parameter
#   - Sub count + country chính xác ngay từ API
#   - Quota: 100 units/search.list call, 1 unit/channels.list (batch 50)
#
# Lưu ý quota: mỗi project được 10,000 units/ngày (free)
#   → tối đa 100 search calls/ngày → đủ dùng thực tế
# ═══════════════════════════════════════════════════════════════════════════════

import json as _json

_API_KEY_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "settings", "yt_api_config.json"
)

_YT_API_BASE = "https://www.googleapis.com/youtube/v3"


def load_api_key() -> str:
    """Đọc YouTube API key từ settings/yt_api_config.json."""
    try:
        with open(_API_KEY_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = _json.load(f)
        return data.get("api_key", "").strip()
    except Exception:
        return ""


def save_api_key(key: str) -> None:
    """Lưu YouTube API key vào settings/yt_api_config.json."""
    try:
        data = {}
        if os.path.exists(_API_KEY_SETTINGS_PATH):
            try:
                with open(_API_KEY_SETTINGS_PATH, "r", encoding="utf-8") as f:
                    data = _json.load(f)
            except Exception:
                pass
        data["api_key"] = key.strip()
        with open(_API_KEY_SETTINGS_PATH, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _api_get(endpoint: str, params: dict, api_key: str) -> dict:
    """
    Gọi YouTube Data API v3 endpoint.
    Trả về dict JSON hoặc raise Exception nếu lỗi.
    """
    import urllib.request
    import urllib.error

    params = dict(params)
    params["key"] = api_key
    query = urllib.parse.urlencode(params)
    url = f"{_YT_API_BASE}/{endpoint}?{query}"

    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        return _json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        try:
            err = _json.loads(body)
            msg = err.get("error", {}).get("message", body)
        except Exception:
            msg = body[:300]
        raise RuntimeError(f"YouTube API lỗi {e.code}: {msg}")


def _parse_sub_count(txt: str) -> int:
    """Parse subscriber count string từ API (có thể dạng '1234567')."""
    try:
        return int(txt)
    except Exception:
        return 0


def search_channels_api(
    keyword: str,
    max_results: int = 20,
    api_key: str = "",
    region_code: str = "",        # regionCode cho search.list (gợi ý vùng)
    relevance_language: str = "",  # relevanceLanguage cho search.list
    country_filter: str = "",      # Lọc theo snippet.country của kênh (VD: 'US')
    sub_min: int = 0,
    sub_max: int = 0,
    progress_cb=None,              # callable(status_str)
) -> List[ChannelInfo]:
    """
    Tìm kênh YouTube có NỘI DUNG liên quan đến keyword qua YouTube Data API v3.

    Chiến lược: search video (type=video) thay vì tên kênh (type=channel)
    → Tìm video nói về keyword → lấy channelId từ video → deduplicate kênh
    → Gọi channels.list để lấy sub count, country, mô tả

    Lợi ích:
    - Tìm được kênh làm NỘI DUNG về keyword (không cần tên kênh chứa keyword)
    - Ví dụ: tìm "geometry dash" → ra kênh gaming Đức làm video về game này
    - regionCode + relevanceLanguage giúp ưu tiên kênh theo vùng/ngôn ngữ

    Args:
        keyword:            Từ khóa tìm kiếm (nội dung video)
        max_results:        Số kênh tối đa muốn trả về
        api_key:            YouTube Data API v3 key
        region_code:        regionCode cho search.list (gợi ý vùng địa lý)
        relevance_language: Ngôn ngữ ưu tiên cho search.list
        country_filter:     Lọc kênh có snippet.country == country_filter (VD: 'US')
                            Lưu ý: nhiều kênh không set country → sẽ không xuất hiện
        sub_min, sub_max:   Filter subscriber (0 = không filter)
        progress_cb:        callable(status_str) để báo tiến trình

    Returns:
        Danh sách ChannelInfo unique, đã có sub count + country
    """
    if not api_key:
        raise ValueError("Cần nhập YouTube API key để dùng chế độ này.")
    if not keyword.strip():
        return []

    # Khi có filter, cần fetch nhiều video hơn để bù lại sau lọc
    has_filter = (sub_min > 0) or (sub_max > 0) or bool(country_filter)
    if country_filter and not (sub_min or sub_max):
        multiplier = 10   # country filter cần nhiều nhất vì nhiều kênh ko set country
    elif has_filter:
        multiplier = 6
    else:
        multiplier = 2    # luôn lấy dư để có đủ kênh unique sau dedup
    # Số video cần fetch để đủ kênh unique (1 kênh có thể có nhiều video)
    videos_to_fetch = min(max_results * multiplier, 400)

    if progress_cb:
        cf_info = f" · lọc: {country_filter}" if country_filter else ""
        progress_cb(f"🔍 [API] Tìm video về: \"{keyword}\"{cf_info}...")

    # ── Step 1: search.list type=video ───────────────────────────────────────
    # Dùng type=video để tìm VIDEO có nội dung về keyword
    # channelId được extract từ video → tìm ra kênh làm nội dung về topic này
    channel_id_ordered: List[str] = []   # giữ thứ tự xuất hiện
    seen_ch_ids: set = set()
    page_token: str = ""
    max_pages = 8
    page_count = 0

    while len(channel_id_ordered) < videos_to_fetch and page_count < max_pages:
        params: dict = {
            "part": "snippet",
            "q": keyword.strip(),
            "type": "video",           # TÌM VIDEO, không phải tên kênh
            "maxResults": 50,
            "order": "relevance",      # sắp xếp theo độ liên quan
        }
        if region_code:
            params["regionCode"] = region_code.upper()
        if relevance_language:
            params["relevanceLanguage"] = relevance_language
        if page_token:
            params["pageToken"] = page_token

        try:
            data = _api_get("search", params, api_key)
        except Exception as e:
            raise RuntimeError(str(e))

        items = data.get("items") or []
        if not items:
            break

        for item in items:
            # Lấy channelId từ snippet của video
            snippet = item.get("snippet") or {}
            cid = snippet.get("channelId") or ""
            if cid and cid not in seen_ch_ids:
                seen_ch_ids.add(cid)
                channel_id_ordered.append(cid)

        page_token = data.get("nextPageToken") or ""
        page_count += 1
        if not page_token:
            break

    if not channel_id_ordered:
        return []

    if progress_cb:
        progress_cb(f"📊 [API] Lấy thông tin {len(channel_id_ordered)} kênh...")

    # ── Step 2: channels.list (batch 50) ────────────────────────────────────
    # Lấy sub count, country, description, handle cho từng kênh
    channel_map: dict[str, ChannelInfo] = {}
    BATCH = 50
    for i in range(0, len(channel_id_ordered), BATCH):
        batch = channel_id_ordered[i:i + BATCH]
        params2: dict = {
            "part": "snippet,statistics",
            "id": ",".join(batch),
            "maxResults": len(batch),
        }
        try:
            data2 = _api_get("channels", params2, api_key)
        except Exception:
            continue

        for item in (data2.get("items") or []):
            ch = ChannelInfo()
            ch.channel_id = item.get("id") or ""
            snippet = item.get("snippet") or {}
            stats   = item.get("statistics") or {}

            ch.name = snippet.get("title") or ""
            ch.description = (snippet.get("description") or "")[:200]
            custom_url = snippet.get("customUrl") or ""
            if custom_url:
                handle = custom_url if custom_url.startswith("@") else f"@{custom_url}"
                ch.handle = handle
                ch.url = f"https://www.youtube.com/{handle}"
            else:
                ch.url = f"https://www.youtube.com/channel/{ch.channel_id}"

            # Thumbnail
            thumbs = snippet.get("thumbnails") or {}
            for size in ("high", "medium", "default"):
                t = thumbs.get(size) or {}
                if t.get("url"):
                    ch.thumbnail_url = t["url"]
                    break

            # Country — chính xác từ API snippet
            ch.channel_country_code = (snippet.get("country") or "").upper()

            # Subscribers
            sub_count = _parse_sub_count(stats.get("subscriberCount") or "0")
            ch.subscriber_count_num = sub_count
            ch.subscribers = _fmt_subscribers(sub_count)

            if ch.name and ch.channel_id:
                channel_map[ch.channel_id] = ch

    if progress_cb:
        progress_cb(f"🔎 [API] Đã fetch {len(channel_map)} kênh, đang lọc...")

    # ── Step 3: Apply filters (giữ thứ tự từ search) ─────────────────────────
    filtered: List[ChannelInfo] = []
    for cid in channel_id_ordered:
        ch = channel_map.get(cid)
        if not ch:
            continue
        # Country filter — lọc theo snippet.country
        if country_filter:
            if ch.channel_country_code.upper() != country_filter.upper():
                continue
        # Subscriber range
        if sub_min > 0 and ch.subscriber_count_num < sub_min:
            continue
        if sub_max > 0 and ch.subscriber_count_num > sub_max:
            continue
        filtered.append(ch)
        if len(filtered) >= max_results:
            break

    return filtered



def search_channels_multi_api(
    keywords: List[str],
    max_results: int = 20,
    api_key: str = "",
    region_code: str = "",
    relevance_language: str = "",
    country_filter: str = "",
    sub_min: int = 0,
    sub_max: int = 0,
    progress_cb=None,    # callable(keyword_done: int, keyword_total: int)
) -> List[ChannelInfo]:
    """
    Tìm kênh theo NHIỀU từ khóa qua YouTube Data API v3.
    Kết quả được merge và deduplicate theo channel_id.
    """
    kws = [k.strip() for k in keywords if k.strip()]
    if not kws:
        return []

    per_kw = max(max_results, max_results * 2 // len(kws) + 5)
    seen_ids: dict[str, ChannelInfo] = {}

    for idx, kw in enumerate(kws):
        def _prog(msg, _kw=kw, _idx=idx):
            if progress_cb:
                try:
                    progress_cb(_idx + 1, len(kws))
                except Exception:
                    pass

        try:
            results = search_channels_api(
                kw, per_kw,
                api_key=api_key,
                region_code=region_code,
                relevance_language=relevance_language,
                country_filter=country_filter,
                sub_min=sub_min,
                sub_max=sub_max,
                progress_cb=_prog,
            )
            for ch in results:
                if ch.channel_id and ch.channel_id not in seen_ids:
                    seen_ids[ch.channel_id] = ch
        except Exception:
            pass

        if progress_cb:
            try:
                progress_cb(idx + 1, len(kws))
            except Exception:
                pass

        if len(seen_ids) >= max_results:
            break

    return list(seen_ids.values())[:max_results]


def get_related_channels_api(
    channel_url: str,
    max_results: int = 20,
    api_key: str = "",
    region_code: str = "",
    relevance_language: str = "",
) -> List[ChannelInfo]:
    """
    Tìm kênh liên quan bằng YouTube Data API v3.
    Lấy tên kênh từ URL rồi tìm kiếm theo tên với cùng region.
    """
    url = channel_url.strip().rstrip("/")
    url = re.sub(r"/(shorts|videos|playlists|community|about|channels)$", "", url)

    # Lấy tên kênh
    source_ch = get_channel_details(url)
    source_id  = source_ch.channel_id if source_ch else ""
    source_name = source_ch.name if source_ch else ""

    if not source_name:
        m = re.search(r"(@[\w.\-]+)", url)
        if m:
            source_name = m.group(1).lstrip("@").replace("-", " ").replace("_", " ").title()
        else:
            segs = url.rstrip("/").split("/")
            source_name = segs[-1] if segs else "channel"

    results = search_channels_api(
        source_name,
        max_results=max_results + 5,
        api_key=api_key,
        region_code=region_code,
        relevance_language=relevance_language,
    )

    filtered = [ch for ch in results if ch.channel_id != source_id]
    return filtered[:max_results]


def validate_api_key(api_key: str) -> tuple[bool, str]:
    """
    Kiểm tra API key có hợp lệ không bằng cách thực hiện 1 search đơn giản.
    Returns: (is_valid: bool, message: str)
    """
    if not api_key or len(api_key) < 10:
        return False, "API key quá ngắn hoặc trống."
    try:
        data = _api_get("search", {
            "part": "snippet",
            "q": "test",
            "type": "channel",
            "maxResults": 1,
        }, api_key)
        if "items" in data:
            return True, "✅ API key hợp lệ!"
        return False, "Phản hồi không hợp lệ từ API."
    except RuntimeError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Lỗi kết nối: {e}"

