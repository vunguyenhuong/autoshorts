import yt_dlp

def get_formats(url):
    print("\n=== LẤY DANH SÁCH FORMAT ===\n")

    ydl_opts = {
        'quiet': True,
        'cookiesfrombrowser': ('chrome',),  # 👈 FIX BOT
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

        formats = info.get("formats", [])

        print(f"{'ID':<10} {'EXT':<6} {'RESOLUTION':<12} {'NOTE'}")
        print("-" * 60)

        for f in formats:
            fid = f.get("format_id")
            ext = f.get("ext")
            res = f.get("resolution") or f"{f.get('width')}x{f.get('height')}"
            note = f.get("format_note", "")

            print(f"{fid:<10} {ext:<6} {res:<12} {note}")


def download_video(url, fmt):
    print("\n=== BẮT ĐẦU DOWNLOAD ===\n")

    def progress_hook(d):
        if d['status'] == 'downloading':
            print(f"{d.get('_percent_str','')} | "
                  f"{d.get('_speed_str','')} | "
                  f"ETA {d.get('_eta_str','')}", end="\r")

        elif d['status'] == 'finished':
            print("\n✅ Download Completed!")

    ydl_opts = {
        'format': fmt,
        'outtmpl': '%(title).200s-%(id)s.%(ext)s',
        'noplaylist': True,
        'cookiesfrombrowser': ('chrome',),  # 👈 FIX BOT
        'http_headers': {
            'User-Agent': 'Mozilla/5.0'
        },
        'progress_hooks': [progress_hook],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


if __name__ == "__main__":
    url = input("Nhập URL: ").strip()

    # 1. Lấy format
    get_formats(url)

    # 2. Nhập format
    fmt = input("\nNhập format ID (ví dụ 96-17): ").strip()

    # 3. Download
    download_video(url, fmt)