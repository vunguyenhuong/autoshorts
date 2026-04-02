import requests
import re
import json

url = "https://www.facebook.com/61570393616197/reels"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1"
}

try:
    print(f"Fetching {url}...")
    resp = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {resp.status_code}")
    
    html = resp.text
    # Search for reel URLs in the text
    # Facebook might use format: "url":"https:\/\/www.facebook.com\/reel\/12345" or similar
    # Or just /reel/12345
    
    reel_ids = set()
    # Pattern for /reel/ID or /watch/?v=ID
    matches = re.findall(r'(\/reel\/[0-9]+)', html)
    for m in matches:
        reel_ids.add(m)
        
    url_matches = re.findall(r'(https:\\[/a-zA-Z0-9\.]*reel\\[/0-9]+)', html)
    for m in url_matches:
        reel_ids.add(m.replace('\\/', '/'))
        
    print(f"Found {len(reel_ids)} unique reel IDs from HTML parsing:")
    for rid in list(reel_ids)[:10]:
        print(rid)
        
    if not reel_ids:
        # Save a snippet of the HTML to see what we got (e.g., login redirect?)
        print("HTML snippet:")
        print(html[:1000])
        if "login" in html.lower():
            print("Redirected to login page.")
            
except Exception as e:
    print(f"Error: {e}")
