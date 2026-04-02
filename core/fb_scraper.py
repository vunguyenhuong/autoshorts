import os
import sys
import json
import asyncio
from pathlib import Path

def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_settings_dir():
    settings_dir = os.path.join(get_base_dir(), "settings")
    if not os.path.exists(settings_dir):
        os.makedirs(settings_dir, exist_ok=True)
    return settings_dir

FB_STATE_FILE = os.path.join(get_settings_dir(), "fb_session.json")
FB_COOKIES_TXT = os.path.join(get_settings_dir(), "fb_cookies.txt")

def export_to_netscape_format(playwright_cookies, output_path):
    """Converts Playwright JSON cookies to Netscape format for yt-dlp"""
    lines = ["# Netscape HTTP Cookie File", "# This is a generated file! Do not edit.", ""]
    for cookie in playwright_cookies:
        domain = cookie.get('domain', '')
        # If domain does not start with a dot, we need to check if it's a domain boundary
        # For Facebook, usually cookies are .facebook.com
        include_sub_domains = "TRUE" if domain.startswith('.') else "FALSE"
        path = cookie.get('path', '/')
        secure = "TRUE" if cookie.get('secure', False) else "FALSE"
        # yt-dlp expects expiration in seconds, and 0 for session cookies
        expires = str(max(int(cookie.get('expires', 0)), 0))
        name = cookie.get('name', '')
        value = cookie.get('value', '')
        
        lines.append(f"{domain}\t{include_sub_domains}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
        
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

class FacebookScraper:
    def __init__(self):
        self.state_file = FB_STATE_FILE
        self.cookies_txt = FB_COOKIES_TXT

    def has_session(self):
        return os.path.exists(self.state_file)

    async def _launch_browser(self, p, headless=True):
        """Khởi chạy trình duyệt, sử dụng Edge hoặc Chrome của người dùng nếu có thể."""
        channels = ["msedge", "chrome", None]
        for channel in channels:
            try:
                if channel:
                    return await p.chromium.launch(headless=headless, channel=channel)
                else:
                    return await p.chromium.launch(headless=headless)
            except Exception:
                continue
        raise Exception("Không thể khởi động Playwright. Vui lòng cài đặt Edge/Chrome hoặc chạy 'playwright install chromium'.")

    async def _run_login(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await self._launch_browser(p, headless=False)
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            await page.goto("https://www.facebook.com/login", wait_until="networkidle")
            
            # Wait for user to login and close the browser or navigate away
            print("Đang chờ người dùng đăng nhập Facebook...")
            
            # Check periodically if the browser is closed
            try:
                while len(context.pages) > 0:
                    # Save state continuously in case they close it abruptly
                    await context.storage_state(path=self.state_file)
                    
                    # Also export cookies for yt-dlp
                    cookies = await context.cookies()
                    export_to_netscape_format(cookies, self.cookies_txt)
                    
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"Browser closed: {e}")
                
            # Final save
            try:
                if browser.is_connected():
                    await context.storage_state(path=self.state_file)
                    cookies = await context.cookies()
                    export_to_netscape_format(cookies, self.cookies_txt)
                    await browser.close()
            except:
                pass

    def start_login_sync(self):
        """Called from UI to block until login is finished or browser closed"""
        asyncio.run(self._run_login())
        return os.path.exists(self.state_file)

    async def _scan_reels(self, url, limit, progress_callback=None):
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await self._launch_browser(p, headless=True)
            
            context_args = {
                'viewport': {'width': 1280, 'height': 800},
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            if self.has_session():
                context_args['storage_state'] = self.state_file
                
            context = await browser.new_context(**context_args)
            page = await context.new_page()
            
            # Block media to save bandwidth
            await page.route("**/*.{png,jpg,jpeg,webp,gif,svg,css,woff2}", lambda route: route.abort())
            await page.route("**/*.{mp4,webm,ogg}", lambda route: route.abort())
            
            if progress_callback:
                progress_callback(f"Đang mở trang Facebook: {url} ...")
                
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"Lỗi tải trang: {e}")
                raise Exception(f"Không thể mở trang {url}")
                
            # Try to close any login popups
            try:
                await page.evaluate('''() => {
                    let closeBtns = document.querySelectorAll('div[aria-label="Close"], div[aria-label="Đóng"]');
                    closeBtns.forEach(btn => btn.click());
                }''')
            except:
                pass

                
            if progress_callback:
                progress_callback("Đang tìm video Reels (cuộn trang)...")

            reel_urls = set()
            scroll_attempts = 0
            max_scrolls = int(limit / 5) + 10  # approximate scrolls
            
            previous_count = 0
            stall_count = 0
            
            while len(reel_urls) < limit and scroll_attempts < max_scrolls:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(2.0)  # Wait for FB to load dynamic content
                scroll_attempts += 1
                
                # Extract links
                links = await page.evaluate(r'''() => {
                    const anchors = Array.from(document.querySelectorAll('a'));
                    return anchors.map(a => a.href).filter(href => 
                        href.includes('/reel/') || 
                        href.includes('/video/') || 
                        href.includes('/videos/') || 
                        href.includes('/watch')
                    );
                }''')
                
                for href in links:
                    if href:
                        if "/watch" in href or "watch?v=" in href:
                            # Keep query params for /watch links
                            reel_urls.add(href)
                        else:
                            clean_url = href.split('?')[0].rstrip('/')
                            if "/reel/" in clean_url or "/video/" in clean_url or "/videos/" in clean_url:
                                reel_urls.add(clean_url)
                            
                current_count = len(reel_urls)
                if progress_callback:
                    progress_callback(f"Đang tìm Reels: {current_count}/{limit} video...")
                    
                if current_count == previous_count:
                    stall_count += 1
                    if stall_count >= 4:
                        break # No more new videos loading
                else:
                    stall_count = 0
                    previous_count = current_count

            await browser.close()
            
            # Format results
            results = []
            for i, r_url in enumerate(list(reel_urls)[:limit]):
                # Dummy ID from URL
                vid_id = r_url.split('/')[-1] if not r_url.endswith('/') else r_url.split('/')[-2]
                results.append({
                    'id': vid_id,
                    'title': f"FB_Reel_{vid_id}",
                    'url': r_url,
                    'duration': 0,
                    'view_count': 0
                })
            
            return results

    def scan_reels_sync(self, url, limit=50, progress_callback=None):
        """Synchronous wrapper for scanning"""
        # Ensure we don't have nested event loops
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            
        return asyncio.run(self._scan_reels(url, limit, progress_callback))
