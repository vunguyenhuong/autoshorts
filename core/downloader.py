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
                    # Migrate old format to new format if needed
                    for channel_key in data:
                        if isinstance(data[channel_key], list):
                            # Old format: just a list of URLs
                            data[channel_key] = {
                                'videos': data[channel_key],
                                'view_counts': {}
                            }
                    return data
            except:
                return {}
        return {}
    
    def save_history(self):
        """Save download history to JSON file"""
        with self._lock:
            try:
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    json.dump(self.history, f, indent=2, ensure_ascii=False)
                # Print to console for debugging
                print(f"DEBUG: History saved to {os.path.abspath(self.history_file)}")
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
        # Remove trailing slashes and whitespace
        normalized = url.strip().rstrip('/')
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
                process = subprocess.run(cmd, capture_output=True, text=True)
                
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
                result = subprocess.run([self.ytdlp_path, "--version"], capture_output=True, text=True)
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
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding='utf-8')
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

    def _build_ydl_opts(self, output_dir, ffmpeg_location=None, language=None):
        """
        Build yt-dlp options dict for downloading YouTube Shorts at 1080p H.264.
        
        Proven strategy (tested & verified):
        - Client: 'android_vr' — bypasses YouTube PO Token requirement, 
          provides full 1080p H.264 streams without 403 errors.
        - Format: prioritize height>=1080, then sort by resolution first, 
          then prefer H.264 (avc) codec.
        - Result: 1080x1920 H.264 60fps confirmed.
        
        Args:
            language: If provided (e.g. 'de-DE'), only download formats with that language tag.
                      Videos without this audio track will be skipped if combined formats are used.
        """
        if language and language != "Mặc định":
            # BỘ LỌC NGÔN NGỮ: Chỉ tải các bản lồng tiếng phù hợp
            lang_tag = f"[{language}]"
            fmt = (
                f'best[height>=1080][language={language}]/'
                f'best[language={language}]/'
                f'bestvideo[height>=1080]+bestaudio[language={language}]/'
                f'bestvideo+bestaudio[language={language}]/'
                'bestvideo[height>=1080]+bestaudio/best' # Fallback
            )
        else:
            # Chế độ mặc định: tải chất lượng cao nhất, không lọc ngôn ngữ
            fmt = 'bestvideo[height>=1080]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'

        opts = {
            'format': fmt,
            'format_sort': ['res', 'vcodec:avc'],
            'merge_output_format': 'mp4',
            'outtmpl': os.path.join(output_dir, '%(title)s [%(id)s].%(ext)s'),
            
            # android_vr client: the ONLY client that provides 1080p H.264 without PO Token
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
            'ignoreerrors': True,
            'no_warnings': True,
            'quiet': True,
        }

        if ffmpeg_location:
            opts['ffmpeg_location'] = ffmpeg_location
            
        return opts

