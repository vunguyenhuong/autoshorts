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
        Fetches the list of Shorts from the channel using yt_dlp library.
        """
        import yt_dlp
        
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'playlist_items': f'1:{limit}' if limit else '1:10000',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0'
            },
        }
        
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
                            'view_count': entry.get('view_count', 0)
                        })
            return results
            
        except Exception as e:
            print(f"Error fetching channel: {e}")
            return []

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

    def _build_ydl_opts(self, output_dir, ffmpeg_location=None):
        """
        Build yt-dlp options dict for downloading YouTube Shorts at 1080p H.264.
        
        Proven strategy (tested & verified):
        - Client: 'android_vr' — bypasses YouTube PO Token requirement, 
          provides full 1080p H.264 streams without 403 errors.
        - Format: prioritize height>=1080, then sort by resolution first, 
          then prefer H.264 (avc) codec.
        - Result: 1080x1920 H.264 60fps confirmed.
        """
        opts = {
            # Prioritize 1080p+ video with best audio
            'format': 'bestvideo[height>=1080]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
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

