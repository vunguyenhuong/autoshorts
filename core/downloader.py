import os
import json
from pathlib import Path
import subprocess
import sys


class DownloadHistory:
    """Manages download history to prevent duplicate downloads"""
    
    def __init__(self, history_file="download_history.json"):
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
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)
    
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
        # Remove trailing slashes and convert to lowercase
        normalized = url.rstrip('/').lower()
        # Remove /shorts suffix to treat @channel and @channel/shorts as same
        if normalized.endswith('/shorts'):
            normalized = normalized[:-7]  # Remove '/shorts'
        return normalized

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



    def check_channel(self, channel_url, limit=None):
        """
        Fetches the list of Shorts from the channel using external yt-dlp.exe.
        If limit is None, fetches ALL videos from the channel.
        """
        # Heuristic to force shorts tab
        if "/@" in channel_url:
            pass # yt-dlp usually handles it, but we can append /shorts if needed.
            # But let's trust yt-dlp default or user input.
            
        ytdlp_exe = self.get_ytdlp_exe()
        
        cmd = [
            ytdlp_exe, 
            '-J', # Dump JSON
            '--flat-playlist',
            '--no-warnings',
            '--ignore-errors',  # Continue on download errors
            channel_url
        ]
        
        if limit:
            cmd.extend(['--playlist-end', str(limit)])
        else:
            # Explicitly request all items (no limit) but with a massive ceiling to prevent infinite loops (like live streams)
            cmd.extend(['--playlist-items', '1:10000'])
            
        # Startup info to hide window
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                timeout=240  # 4 minutes max per channel to prevent indefinite hanging
            ) 
            
            if result.returncode != 0:
                print(f"yt-dlp error: {result.stderr}")
                return []
                
            data = json.loads(result.stdout)
            results = []
            
            if 'entries' in data:
                for entry in data['entries']:
                    if entry:
                        results.append({
                            'id': entry.get('id'),
                            'title': entry.get('title'),
                            'url': entry.get('url') or f"https://www.youtube.com/watch?v={entry.get('id')}",
                            'duration': entry.get('duration'),
                            'view_count': entry.get('view_count', 0)
                        })
            return results
            
        except subprocess.TimeoutExpired:
            print(f"Error fetching channel (Timeout): {channel_url}")
            return []
        except Exception as e:
            print(f"Error fetching channel: {e}")
            return []

    def download_videos(self, video_urls, download_path, channel_url=None, skip_downloaded=True, progress_hook=None, logger=None):
        """
        Download videos using external yt-dlp.exe
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

        # Get ffmpeg path - check multiple locations
        ffmpeg_location = None
        ffmpeg_exe = None
        
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            base_path = os.path.dirname(sys.executable)
            candidates = [
                os.path.join(base_path, 'ffmpeg', 'bin', 'ffmpeg.exe'),
                os.path.join(base_path, 'ffmpeg', 'ffmpeg.exe'),
                os.path.join(base_path, 'ffmpeg.exe'),
            ]
        else:
            # Running from Python source (this file is in 'core/')
            # We want the root project directory
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidates = [
                os.path.join(base_path, 'ffmpeg', 'bin', 'ffmpeg.exe'),
                os.path.join(base_path, 'ffmpeg', 'ffmpeg.exe'),
                os.path.join(base_path, 'ffmpeg.exe'),
            ]
        
        # Check local candidates first
        for candidate in candidates:
            if os.path.exists(candidate):
                ffmpeg_exe = candidate
                ffmpeg_location = os.path.dirname(candidate)
                if logger:
                    logger.info(f"Found ffmpeg at: {ffmpeg_exe}")
                break
        
        # If not found locally, try system PATH
        if not ffmpeg_exe:
            import shutil
            ffmpeg_exe = shutil.which('ffmpeg')
            if ffmpeg_exe:
                ffmpeg_location = os.path.dirname(ffmpeg_exe)
                if logger:
                    logger.info(f"Found ffmpeg in system PATH: {ffmpeg_exe}")
        
        if not ffmpeg_exe and logger:
            logger.warning("ffmpeg not found! Videos may not merge properly. Please ensure ffmpeg is installed.")
        
        ytdlp_exe = self.get_ytdlp_exe()
        
        # Download one by one to handle history update per video
        import re

        for url in urls_to_download:
            if logger: logger.info(f"Downloading: {url}")

            files_before = set(os.listdir(download_path)) if os.path.exists(download_path) else set()

            cmd = [
                ytdlp_exe,
                url,
                '-o', os.path.join(download_path, '%(title)s [%(id)s].%(ext)s'),
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
                '--merge-output-format', 'mp4',
                '--no-playlist',
                '--no-warnings',
                '--extractor-retries', '3',
                '--retries', '10',
                '--fragment-retries', '10',
                # Do NOT add android player_client — it caps quality to pre-merged ≤720p
            ]

            if "facebook.com" in url.lower():
                from core.fb_scraper import FB_COOKIES_TXT
                if os.path.exists(FB_COOKIES_TXT):
                    cmd.extend(['--cookies', FB_COOKIES_TXT])

            if ffmpeg_location:
                cmd.extend(['--ffmpeg-location', ffmpeg_location])

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            for line in proc.stdout:
                stripped = line.strip()
                if stripped and logger:
                    logger.info(stripped)
            proc.wait()

            # Verify file was downloaded
            files_after = set(os.listdir(download_path)) if os.path.exists(download_path) else set()
            new_files = files_after - files_before
            download_successful = any(
                os.path.isfile(os.path.join(download_path, f)) and os.path.getsize(os.path.join(download_path, f)) > 0
                for f in new_files
            )

            if download_successful:
                new_file = next(iter(new_files))
                size = os.path.getsize(os.path.join(download_path, new_file))
                if logger: logger.info(f"✅ Saved: {new_file} ({size:,} bytes)")
                if channel_url:
                    self.history.add_to_history(channel_url, url)
            else:
                if logger: logger.error(f"❌ Download failed for: {url} (returncode={proc.returncode})")

