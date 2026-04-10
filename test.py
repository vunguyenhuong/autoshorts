import yt_dlp
import os

url = "https://www.youtube.com/watch?v=tKNAQLyrCAY"

ydl_opts = {
    'format': 'bv*+ba/b',
    'merge_output_format': 'mp4',
    'outtmpl': '%(title)s.%(ext)s',

    'ffmpeg_location': os.path.join(os.path.dirname(__file__), 'ffmpeg'),

    # ✅ FIX ở đây
    'js_runtimes': {
        'node': {}
    },

    'http_headers': {
        'User-Agent': 'Mozilla/5.0'
    },

    'extractor_args': {
        'youtube': {
            'player_client': ['android']
        }
    },

    'retries': 10,
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    ydl.download([url])