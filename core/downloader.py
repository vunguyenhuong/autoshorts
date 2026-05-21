import os
import json
from pathlib import Path
import subprocess
import sys
import threading
import requests
import shutil


class DownloadHistory:
    """Manages download history to prevent duplicate downloads"""
    
    def __init__(self, history_file="download_history.json"):
        import threading
        self._lock = threading.Lock()
        # Determine paths
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
            self.settings_dir = os.path.join(base_dir, "settings")
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.settings_dir = os.path.join(base_dir, "settings")
            
        if not os.path.exists(self.settings_dir):
            os.makedirs(self.settings_dir)
            
        self.history_file = Path(os.path.join(self.settings_dir, history_file))
        self.history = self.load_history()
    
    def load_history(self):
        """Load download history from JSON file"""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    new_data = {}
                    # Migrate old format to new format and ensure case-insensitivity
                    for channel_key in data:
                        lower_channel = channel_key.lower()
                        if lower_channel not in new_data:
                            new_data[lower_channel] = {
                                'videos': [],
                                'view_counts': {}
                            }
                            
                        if isinstance(data[channel_key], list):
                            # Old format: just a list of URLs
                            for v in data[channel_key]:
                                v_lower = v.lower()
                                if v_lower not in new_data[lower_channel]['videos']:
                                    new_data[lower_channel]['videos'].append(v_lower)
                        else:
                            # New format
                            for v in data[channel_key].get('videos', []):
                                v_lower = v.lower()
                                if v_lower not in new_data[lower_channel]['videos']:
                                    new_data[lower_channel]['videos'].append(v_lower)
                                    
                            for k, v in data[channel_key].get('view_counts', {}).items():
                                new_data[lower_channel]['view_counts'][k.lower()] = v
                    return new_data
            except Exception as e:
                print(f"Error loading history: {e}")
                return {}
        return {}
    
    def save_history(self):
        """Save download history to JSON file"""
        with self._lock:
            try:
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    json.dump(self.history, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Error saving history to {self.history_file}: {e}")
    
    def is_downloaded(self, channel_url, video_url):
        """Check if video was already downloaded from this channel"""
        channel_key = self._normalize_url(channel_url)
        video_key = self._normalize_url(video_url)
        channel_data = self.history.get(channel_key, {})
        if isinstance(channel_data, dict):
            return video_key in channel_data.get('videos', [])
        return video_key in channel_data  # Old format compatibility
    
    def add_to_history(self, channel_url, video_url, view_count=None):
        """Add video to download history with optional view count"""
        channel_key = self._normalize_url(channel_url)
        video_key = self._normalize_url(video_url)
        
        with self._lock:
            if channel_key not in self.history:
                self.history[channel_key] = {
                    'videos': [],
                    'view_counts': {}
                }
            
            # Ensure new format
            if isinstance(self.history[channel_key], list):
                self.history[channel_key] = {
                    'videos': self.history[channel_key],
                    'view_counts': {}
                }
            
            if video_key not in self.history[channel_key]['videos']:
                self.history[channel_key]['videos'].append(video_key)
                if view_count is not None:
                    self.history[channel_key]['view_counts'][video_key] = view_count
                
        # Save outside the manual lock block because save_history has its own lock
        self.save_history()
    
    def clear_history(self):
        """Clear all download history"""
        self.history = {}
        self.save_history()
    
    def get_channel_stats(self, channel_url):
        """Get download statistics for a channel"""
        channel_key = self._normalize_url(channel_url)
        channel_data = self.history.get(channel_key, {})
        if isinstance(channel_data, dict):
            return len(channel_data.get('videos', []))
        return len(channel_data)  # Old format compatibility
    
    def get_view_count(self, channel_url, video_url):
        """Get view count for a specific video"""
        channel_key = self._normalize_url(channel_url)
        video_key = self._normalize_url(video_url)
        channel_data = self.history.get(channel_key, {})
        if isinstance(channel_data, dict):
            return channel_data.get('view_counts', {}).get(video_key)
        return None
    
    def _normalize_url(self, url):
        """Normalize URL for consistent comparison"""
        if not url:
            return "__direct__"
        # Remove trailing slashes and whitespace, then lowercase for case-insensitive comparison
        normalized = url.strip().rstrip('/').lower()
        
        # Standardize http to https
        if normalized.startswith("http://"):
            normalized = "https://" + normalized[7:]
            
        # Standardize youtube.com to www.youtube.com
        if normalized.startswith("https://youtube.com/"):
            normalized = normalized.replace("https://youtube.com/", "https://www.youtube.com/", 1)
            
        # Remove /shorts or /videos suffix to treat @channel, @channel/shorts, @channel/videos as same
        if normalized.endswith('/shorts'):
            normalized = normalized[:-7]  # Remove '/shorts'
        elif normalized.endswith('/videos'):
            normalized = normalized[:-7]  # Remove '/videos'
        return normalized

class YtdlpUpdater:
    """Handles automatic updates for yt-dlp.exe"""
    
    def __init__(self, settings_dir):
        self.settings_dir = settings_dir
        self.ytdlp_path = os.path.join(self.settings_dir, "yt-dlp.exe")
        
    def run_update(self, callback=None):
        """Run update process in a background thread"""
        thread = threading.Thread(target=self._update_logic, args=(callback,))
        thread.daemon = True
        thread.start()
        
    def _update_logic(self, callback=None):
        prefix = "[yt-dlp]"
        if callback: callback(f"{prefix} Checking installed version...")
        
        try:
            if not os.path.exists(self.ytdlp_path):
                if callback: callback(f"{prefix} yt-dlp.exe not found in settings. Downloading latest release...")
                success = self._download_latest()
                if success:
                    version = self._get_version()
                    if callback: callback(f"{prefix} Successfully installed version: {version}")
                else:
                    if callback: callback(f"{prefix} Failed to download yt-dlp.exe.")
            else:
                # Get current version
                current_version = self._get_version()
                if callback: callback(f"{prefix} Found version: {current_version}")
                
                # Try to update
                if callback: callback(f"{prefix} Checking for updates...")
                cmd = [self.ytdlp_path, "--update"]
                kwargs = {'capture_output': True, 'text': True}
                if os.name == 'nt':
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                process = subprocess.run(cmd, **kwargs)
                
                if "is up to date" in process.stdout or "is up to date" in process.stderr:
                    if callback: callback(f"{prefix} Already up to date.")
                elif "Updating to version" in process.stdout or "Updating to version" in process.stderr:
                    new_version = self._get_version()
                    if callback: callback(f"{prefix} Updated to latest version: {new_version}")
                else:
                    # Fallback to manual download if -U fails
                    self._download_latest()
                    new_version = self._get_version()
                    if callback: callback(f"{prefix} Manually updated to: {new_version}")
                    
        except Exception as e:
            if callback: callback(f"{prefix} Error during update: {str(e)}")

    def _get_version(self):
        """Get current version of yt-dlp.exe"""
        try:
            if os.path.exists(self.ytdlp_path):
                kwargs = {'capture_output': True, 'text': True}
                if os.name == 'nt':
                    kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
                result = subprocess.run([self.ytdlp_path, "--version"], **kwargs)
                return result.stdout.strip()
        except:
            pass
        return "Unknown"

    def _download_latest(self):
        """Download the latest yt-dlp.exe from GitHub releases"""
        try:
            api_url = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
            response = requests.get(api_url, timeout=10)
            data = response.json()
            
            download_url = None
            for asset in data.get('assets', []):
                if asset['name'] == 'yt-dlp.exe':
                    download_url = asset['browser_download_url']
                    break
            
            if download_url:
                if not os.path.exists(self.settings_dir):
                    os.makedirs(self.settings_dir)
                
                # Download to a temporary file first
                temp_path = self.ytdlp_path + ".tmp"
                with requests.get(download_url, stream=True) as r:
                    r.raise_for_status()
                    with open(temp_path, 'wb') as f:
                        shutil.copyfileobj(r.raw, f)
                
                # Replace the old one
                if os.path.exists(self.ytdlp_path):
                    os.remove(self.ytdlp_path)
                os.rename(temp_path, self.ytdlp_path)
                return True
        except Exception as e:
            print(f"Error downloading yt-dlp: {e}")
        return False

class ShortsDownloader:
    def __init__(self):
        self.history = DownloadHistory()

    def get_ytdlp_exe(self):
        """Locate yt-dlp.exe in settings folder"""
        if getattr(sys, 'frozen', False):
            base_cwd = os.path.dirname(sys.executable)
            # Prioritize settings folder
            candidates = [
                os.path.join(base_cwd, 'settings', 'yt-dlp.exe'),
                os.path.join(base_cwd, 'yt-dlp.exe'),
            ]
            for c in candidates:
                if os.path.exists(c):
                    return c
            return "yt-dlp"
        else:
            # Check current dir or settings dir
            if os.path.exists("settings/yt-dlp.exe"):
                 return os.path.abspath("settings/yt-dlp.exe")
            if os.path.exists("yt-dlp.exe"):
                return os.path.abspath("yt-dlp.exe")
            return "yt-dlp"

    def _find_ffmpeg(self):
        """Return the ffmpeg directory path, or None if not found."""
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        candidates = [
            os.path.join(base_path, 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(base_path, 'ffmpeg', 'ffmpeg.exe'),
            os.path.join(base_path, 'ffmpeg.exe'),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return os.path.dirname(candidate)

        # Fallback: system PATH
        import shutil
        ffmpeg_exe = shutil.which('ffmpeg')
        if ffmpeg_exe:
            return os.path.dirname(ffmpeg_exe)
        return None



    def get_available_languages(self, video_url):
        """
        Detect available audio languages for a video by parsing yt-dlp JSON output.
        Returns a list of language tags found in the format list (e.g. ['de-DE', 'es-ES']).
        """
        import json
        ytdlp_exe = self.get_ytdlp_exe()
        
        # Use -j to get JSON metadata
        cmd = [ytdlp_exe, '--no-playlist', '--quiet', '--no-warnings', '-j', video_url]
        
        # Also try to use deno if available
        MD_DENO = r'C:/Users/Vu Nguyen Huong/AppData/Roaming/media-downloader/bin/deno.exe'
        if os.path.exists(MD_DENO):
            cmd.insert(1, '--js-runtimes')
            cmd.insert(2, f'deno:{MD_DENO}')
            
        try:
            kwargs = {'capture_output': True, 'text': True, 'timeout': 60, 'encoding': 'utf-8'}
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(cmd, **kwargs)
            if result.returncode != 0:
                return []
                
            data = json.loads(result.stdout)
            langs = set()
            
            formats = data.get('formats', [])
            for f in formats:
                lang = f.get('language')
                # Ignore 'und' (undetermined) and other generic tags
                if lang and lang != 'und' and lang != 'original':
                    langs.add(lang)
            
            return sorted(list(langs))
        except Exception as e:
            print(f"Error detecting languages: {e}")
            return []

    def check_channel(self, channel_url, limit=None):
        """
        Fetches the list of Shorts from the channel using yt_dlp library.
        """
        import yt_dlp
        
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0'
            },
        }

        if limit and limit > 0:
            ydl_opts['playlistend'] = limit
            
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                data = ydl.extract_info(channel_url, download=False)
                
            results = []
            if data and 'entries' in data:
                for entry in data['entries']:
                    if entry:
                        results.append({
                            'id': entry.get('id'),
                            'title': entry.get('title'),
                            'url': entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}",
                            'duration': entry.get('duration'),
                            'view_count': entry.get('view_count', 0),
                            'upload_date': entry.get('upload_date'),  # format: YYYYMMDD or None
                            'timestamp': entry.get('timestamp'),      # unix timestamp or None
                        })
            return results
            
        except Exception as e:
            print(f"Error fetching channel: {e}")
            return []

    def get_video_info(self, video_url):
        """
        Fetches metadata for a single video using yt_dlp.
        Returns a dict with video details, including channel_url and view_count.
        """
        import yt_dlp
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0'
            },
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                if info:
                    return {
                        'id': info.get('id'),
                        'title': info.get('title'),
                        'url': info.get('url') or video_url,
                        'duration': info.get('duration'),
                        'view_count': info.get('view_count', 0),
                        'upload_date': info.get('upload_date'),
                        'timestamp': info.get('timestamp'),
                        'channel_url': info.get('uploader_url') or info.get('channel_url') or info.get('uploader_id'),
                        'channel': info.get('channel') or info.get('uploader')
                    }
        except Exception as e:
            print(f"Error fetching video info: {e}")
        return None

    def download_videos(self, video_urls, download_path, channel_url=None, skip_downloaded=True, progress_hook=None, logger=None):
        """
        Download videos using yt_dlp Python library.
        Strategy: Download best 1080p quality (any codec), then auto-convert to H.264 via FFmpeg.

        After all downloads finish:
        - Runs a final full cleanup of all non-.mp4 files in the output folder.
        - Counts actual .mp4 files and compares against the requested count.
        - Logs a clear completion summary (success or warning if count is short).
        """
        if not os.path.exists(download_path):
            os.makedirs(download_path)

        urls_to_download = []
        skipped_count = 0

        for url in video_urls:
            if skip_downloaded and channel_url and self.history.is_downloaded(channel_url, url):
                skipped_count += 1
                if logger: logger.info(f"Skipping already downloaded: {url}")
            else:
                urls_to_download.append(url)

        if logger and skipped_count > 0:
            logger.info(f"Skipped {skipped_count} already downloaded videos")

        if not urls_to_download:
            return

        import yt_dlp

        # Find ffmpeg location
        ffmpeg_location = self._find_ffmpeg()
        requested_count = len(urls_to_download)

        for url in urls_to_download:
            if logger: logger.info(f"Downloading: {url}")

            ydl_opts = self._build_ydl_opts(download_path, ffmpeg_location)

            if "facebook.com" in url.lower():
                from core.fb_scraper import FB_COOKIES_TXT
                if os.path.exists(FB_COOKIES_TXT):
                    ydl_opts['cookiefile'] = FB_COOKIES_TXT

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    error_code = ydl.download([url])

                if error_code == 0:
                    if logger: logger.info(f"✅ Saved successfully: {url}")
                    if channel_url:
                        self.history.add_to_history(channel_url, url)
                else:
                    if logger: logger.error(f"❌ Download failed for: {url}")
            except Exception as e:
                if logger: logger.error(f"❌ Error downloading {url}: {e}")
            finally:
                # Clean up leftover fragment/partial files after each video
                self._cleanup_fragments(download_path, logger)

        # ── Final cleanup & verification ────────────────────────────────────────
        # One more full sweep to catch anything missed during the loop
        self._cleanup_fragments(download_path, logger)

        # Count valid .mp4 files actually present in the output folder
        mp4_files = [
            f for f in os.listdir(download_path)
            if f.lower().endswith('.mp4') and os.path.isfile(os.path.join(download_path, f))
        ]
        actual_count = len(mp4_files)

        if logger:
            logger.info(f"─" * 50)
            logger.info(f"📁 Thư mục lưu: {download_path}")
            logger.info(f"🎯 Yêu cầu tải:  {requested_count} video")
            logger.info(f"✅ Số file .mp4:  {actual_count} file")
            if actual_count >= requested_count:
                logger.info(f"🎉 Hoàn thành! Đã tải đủ {actual_count}/{requested_count} video .mp4.")
            else:
                missing = requested_count - actual_count
                logger.warning(
                    f"⚠️ Chưa đủ: chỉ có {actual_count}/{requested_count} file .mp4. "
                    f"Thiếu {missing} video (có thể bị lỗi hoặc bị xóa do không merge được)."
                )
            logger.info(f"─" * 50)

    def _build_ydl_opts(self, output_dir, ffmpeg_location=None, language=None):
        """
        Build yt-dlp options dict for downloading YouTube Shorts at 1080p H.264.

        Strategy:
        - Client: 'android_vr' — bypasses YouTube PO Token requirement,
          provides full 1080p H.264 streams without 403 errors.
        - Format: prioritize H.264/AVC codec explicitly via vcodec filter so that
          yt-dlp never selects VP9/AV1 free-format streams (which produce .f137 etc.).
        - prefer_free_formats=False: prevent yt-dlp from auto-upgrading to WebM/VP9.
        - merge_output_format + FFmpegVideoRemuxer: guarantee the merged file is .mp4.
        - postprocessor_args FFmpeg flags: ensure stream copy remux into mp4 container.

        Args:
            language: If provided (e.g. 'de-DE'), only download formats with that language tag.
        """
        if language and language != "Mặc định":
            # BỘ LỌC NGÔN NGỮ: ưu tiên H.264 + m4a, sau đó fallback
            fmt = (
                f'bestvideo[height>=1080][vcodec^=avc1][ext=mp4]+bestaudio[language={language}][ext=m4a]/'
                f'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[language={language}][ext=m4a]/'
                f'bestvideo[height>=1080][ext=mp4]+bestaudio[language={language}][ext=m4a]/'
                f'bestvideo[ext=mp4]+bestaudio[language={language}][ext=m4a]/'
                f'bestvideo[vcodec^=avc1]+bestaudio[language={language}]/'
                f'bestvideo[height>=1080][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[height>=1080][ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo[ext=mp4]+bestaudio[ext=m4a]/'
                f'bestvideo+bestaudio/'
                f'best[vcodec!=none]'
            )
        else:
            # Chế độ mặc định: ưu tiên H.264 (avc1), sau đó fallback dần
            fmt = (
                'bestvideo[height>=1080][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[height>=1080][ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[ext=mp4]+bestaudio[ext=m4a]/'
                'bestvideo[vcodec^=avc1]+bestaudio/'
                'bestvideo+bestaudio/'
                'best[vcodec!=none]'
            )

        opts = {
            'format': fmt,
            # Sort: resolution first, then prefer H.264 (avc), then prefer mp4 container
            'format_sort': ['res', 'vcodec:avc', 'ext:mp4:m4a'],
            # Block yt-dlp from auto-upgrading to VP9/AV1 "free" formats
            'prefer_free_formats': False,
            # Final merged container must be mp4
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(output_dir, '%(title)s [%(id)s].%(ext)s'),

            # Force remux into mp4 container after merge
            'postprocessors': [{
                'key': 'FFmpegVideoRemuxer',
                'preferedformat': 'mp4',
            }],
            # FFmpeg args: stream copy (no re-encode) for fast, lossless remux
            'postprocessor_args': {
                'ffmpeg': ['-c', 'copy'],
            },

            # android_vr client: provides 1080p H.264 without PO Token
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_vr']
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0'
            },

            # Reliability settings
            'retries': 10,
            'fragment_retries': 10,
            'ignoreerrors': True,
            'no_warnings': True,
            'quiet': True,
            'noprogress': True,

            # Delete intermediate/fragment files, keep only final .mp4
            'keepvideo': False,
        }

        if ffmpeg_location:
            opts['ffmpeg_location'] = ffmpeg_location

        return opts

    def _cleanup_fragments(self, download_path, logger=None):
        """Remove leftover fragment and partial files from failed/interrupted downloads.
        
        Removes:
        - .part, .ytdl, .temp files (yt-dlp temp files)
        - .f137, .f140, .f251, .fNNN files (raw stream fragment dumps)
        - Any file whose base name contains a fragment suffix (e.g. "title.f137.mp4")
        - Any non-.mp4 video file that was left behind (webm, mkv, ts, m4v, etc.)
          — these indicate a failed merge and should be deleted to avoid confusing
          the processor with broken partial video data.
        """
        import re
        # Match .f137, .f140, .f251, etc.
        fragment_re = re.compile(r'\.f\d+$', re.IGNORECASE)
        # Known yt-dlp temp extensions
        junk_exts = ('.part', '.ytdl', '.temp', '.vtt', '.srt')
        # Non-mp4 video containers that should NOT be kept (failed merge artifacts)
        stray_video_exts = ('.webm', '.mkv', '.ts', '.m4v', '.avi', '.mov', '.flv', '.3gp')

        try:
            for fname in os.listdir(download_path):
                fpath = os.path.join(download_path, fname)
                if not os.path.isfile(fpath):
                    continue

                name_lower = fname.lower()
                base, ext = os.path.splitext(fname)
                ext_lower = ext.lower()
                is_junk = False

                # 1. Known temp/partial suffixes
                if any(name_lower.endswith(e) for e in junk_exts):
                    is_junk = True

                # 2. Raw fragment extensions: .f137, .f140, etc.
                elif fragment_re.match(ext_lower):
                    is_junk = True

                # 3. Double-extension patterns: e.g. "video.f137.mp4" — base contains .fNNN
                elif fragment_re.search(base):
                    is_junk = True

                # 4. Stray non-mp4 video containers (failed merge left-overs)
                elif ext_lower in stray_video_exts:
                    is_junk = True

                if is_junk:
                    try:
                        os.remove(fpath)
                        if logger:
                            logger.info(f"🗑️ Đã xóa file rác: {fname}")
                    except Exception as e:
                        if logger:
                            logger.warning(f"⚠️ Không xóa được {fname}: {e}")
        except Exception:
            pass

