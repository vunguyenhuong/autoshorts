"""
Debug: thử các client khác để tìm client nào trả về m3u8 streams có language tags
"""
import yt_dlp

url = "https://www.youtube.com/shorts/gDGKSYeppkw"

clients_to_test = ['ios', 'android', 'web_embedded', 'mweb', 'tv_embedded']

for client in clients_to_test:
    print(f"\n{'='*60}")
    print(f"  CLIENT: {client}")
    print(f"{'='*60}")
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'extractor_args': {
            'youtube': {
                'player_client': [client]
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0'
        },
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            print("  -> No info returned")
            continue
        formats = info.get('formats') or []
        print(f"  Total formats: {len(formats)}")

        # m3u8 formats
        m3u8_fmts = [f for f in formats if f.get('protocol') in ('m3u8', 'm3u8_native')]
        print(f"  m3u8 formats: {len(m3u8_fmts)}")

        # German language
        de_fmts = [f for f in formats if f.get('language') in ('de', 'de-DE')]
        print(f"  German (de/de-DE) formats: {len(de_fmts)}")
        for f in de_fmts:
            print(f"    ID={f.get('format_id'):<8} lang={f.get('language'):<8} "
                  f"h={str(f.get('height')):<5} ext={f.get('ext'):<5} "
                  f"proto={f.get('protocol')} "
                  f"vc={str(f.get('vcodec','none'))[:10]} ac={str(f.get('acodec','none'))[:10]}")
    except Exception as e:
        print(f"  -> ERROR: {e}")
