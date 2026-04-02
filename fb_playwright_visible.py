import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()
        print("Navigating to Facebook reels page...")
        url = "https://www.facebook.com/61570393616197/reels"
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=20000)
        except Exception as e:
            print(f"Goto error: {e}")
            
        print("Waiting a bit for content to render...")
        await page.wait_for_timeout(3000)
        
        html = await page.content()
        print(f"Total HTML length: {len(html)}")
        print("Title:", await page.title())
        
        # Search for reel links
        links = await page.query_selector_all("a")
        reel_urls = set()
        
        for link in links:
            href = await link.get_attribute("href")
            if href and "/reel/" in href:
                if href.startswith("http"):
                    reel_urls.add(href.split('?')[0])
                else:
                    reel_urls.add("https://www.facebook.com" + href.split('?')[0])
                    
        print(f"Extracted {len(reel_urls)} unique reels.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
