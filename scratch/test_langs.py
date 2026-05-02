import json
import subprocess
import os

ytdlp_exe = r"C:/Users/Vu Nguyen Huong/AppData/Roaming/media-downloader/bin/yt-dlp.exe"
url = "https://www.youtube.com/shorts/Os1l6ZHRXRk"

cmd = [ytdlp_exe, "-j", url]
result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
data = json.loads(result.stdout)

languages = set()
for f in data.get('formats', []):
    lang = f.get('language')
    if lang and lang != 'und':
        languages.add(lang)

print(f"Detected languages: {sorted(list(languages))}")
