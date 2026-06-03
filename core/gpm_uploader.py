"""
core/gpm_uploader.py
---------------------
GPM Login API client + TikTok auto-upload worker (via Selenium → Chrome remote debug).

Flow per profile:
  1. Call GPM API  POST /api/v3/profiles/start/{id}  → get remote_debug_port
  2. Connect Selenium to chrome://  localhost:<port>
  3. Navigate to https://www.tiktok.com/upload
  4. Wait for upload iframe → send video file path → fill caption → submit
  5. Wait for "posted" confirmation
  6. Call GPM API  POST /api/v3/profiles/close/{id}  (optional)

Caption logic (caption_mode):
  "filename"  → video stem (no extension)
  "txt_file"  → read <same_dir>/<stem>.txt  (fallback: filename)
  "fixed"     → use fixed_caption string
"""

import os
import time
import json
import threading
import requests as _requests

from PyQt6.QtCore import QThread, pyqtSignal


# ─────────────────────────────────────────────────────────────────────────────
# GPM REST API helper
# ─────────────────────────────────────────────────────────────────────────────

class GpmApi:
    """Thin wrapper around GPM Login local API."""

    def __init__(self, host: str = "http://127.0.0.1", port: int = 19995):
        self.base = f"{host.rstrip('/')}:{port}"

    # ------------------------------------------------------------------
    def get_profiles(self) -> list[dict]:
        """Return list of profile dicts from GPM.
        Each dict has at least: id, name, group_name (may vary by GPM version).
        Tries v3 first, falls back to v2.
        """
        for path in ("/api/v3/profiles", "/api/v2/profiles"):
            try:
                r = _requests.get(
                    f"{self.base}{path}",
                    params={"page": 1, "per_page": 1000},
                    timeout=8,
                )
                if r.status_code == 200:
                    data = r.json()
                    # v3 returns {"data": [...]}; v2 may return list directly
                    if isinstance(data, dict) and "data" in data:
                        return data["data"]
                    if isinstance(data, list):
                        return data
            except Exception:
                continue
        raise ConnectionError(
            "Không thể kết nối GPM Login. Hãy đảm bảo GPM đang chạy "
            f"và API endpoint tại {self.base} hoạt động bình thường."
        )

    # ------------------------------------------------------------------
    def start_profile(self, profile_id: str) -> dict:
        """Start a GPM profile and return the response dict.
        Expected response: {"success": true, "data": {"remote_debugging_port": 9222, ...}}
        """
        for path in (
            f"/api/v3/profiles/start/{profile_id}",
            f"/api/v2/profiles/start/{profile_id}",
        ):
            try:
                r = _requests.get(f"{self.base}{path}", timeout=30)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                continue
        raise RuntimeError(f"Không thể start profile {profile_id}")

    # ------------------------------------------------------------------
    def close_profile(self, profile_id: str) -> None:
        """Close a GPM profile (best-effort)."""
        for path in (
            f"/api/v3/profiles/close/{profile_id}",
            f"/api/v2/profiles/close/{profile_id}",
        ):
            try:
                _requests.get(f"{self.base}{path}", timeout=10)
                return
            except Exception:
                continue


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

VALID_VIDEO_EXTS = ('.mp4', '.mov', '.avi', '.mkv', '.webm')


def _collect_videos(folder: str, limit: int) -> list[str]:
    """Return up to `limit` video paths from `folder` (sorted, flat)."""
    if not os.path.isdir(folder):
        return []
    files = sorted(
        os.path.join(folder, f) for f in os.listdir(folder)
        if os.path.isfile(os.path.join(folder, f))
        and f.lower().endswith(VALID_VIDEO_EXTS)
    )
    return files[:limit] if limit > 0 else files


def _get_caption(video_path: str, mode: str, fixed: str) -> str:
    stem = os.path.splitext(os.path.basename(video_path))[0]
    if mode == "fixed":
        return fixed or stem
    if mode == "txt_file":
        txt = os.path.join(os.path.dirname(video_path), stem + ".txt")
        if os.path.isfile(txt):
            try:
                return open(txt, encoding="utf-8").read().strip() or stem
            except Exception:
                pass
    return stem  # fallback / "filename" mode


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Clear modal overlays / Popups via JS
# ─────────────────────────────────────────────────────────────────────────────

def _clear_overlays(driver, log_fn):
    """Dismiss any TikTok studio modals, cookie banners or tutorials using JavaScript to avoid click interception."""
    dismiss_js = """
    const keywords = [
        'verstanden', 'got it', 'understood', 'đã hiểu', 'đã rõ', 
        'einschalten', 'turn on', 'bật', 'allow', 'đồng ý',
        'dismiss', 'close', 'verstanden.'
    ];
    let clickedAny = false;
    
    const buttons = document.querySelectorAll('button, div[role="button"], span[role="button"]');
    
    // 1. Khôi phục khẩn cấp: Nếu có nút "Nein" / "No" / "Không" (hỏi xem có muốn Hủy upload không), click nó ngay để quay lại
    for (const btn of buttons) {
        const text = btn.innerText ? btn.innerText.toLowerCase().trim() : '';
        if (text === 'nein' || text === 'no' || text === 'không') {
            try {
                btn.click();
                clickedAny = true;
            } catch(e) {}
        }
    }
    
    // 2. Click các nút đồng ý/bật tích cực trong danh sách keywords
    for (const btn of buttons) {
        const text = btn.innerText ? btn.innerText.toLowerCase().trim() : '';
        if (keywords.includes(text) || keywords.some(kw => text.includes(kw))) {
            try {
                btn.click();
                clickedAny = true;
            } catch(e) {}
        }
    }
    
    // 3. Click nút X ở các góc popup
    const modalCloses = document.querySelectorAll('div[class*="close"], button[class*="close"], span[class*="close"], [class*="modal"] svg');
    for (const close of modalCloses) {
        try {
            const rect = close.getBoundingClientRect();
            if (rect.width > 0 && rect.width < 55 && rect.height > 0 && rect.height < 55) {
                close.click();
                clickedAny = true;
            }
        } catch(e) {}
    }
    return clickedAny;
    """
    try:
        res = driver.execute_script(dismiss_js)
        if res:
            log_fn("   🧹 Tự động đóng các thông báo/modal che khuất màn hình thành công!")
            time.sleep(1)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Selenium upload helper (runs in worker thread)
# ─────────────────────────────────────────────────────────────────────────────

def _selenium_upload_tiktok(
    debug_port: int,
    video_path: str,
    caption: str,
    log_fn,
    stop_check,
    delay_after: float = 3.0,
    driver_path: str = None,
    human_typing: bool = True,
) -> bool:
    """
    Connect to a running Chrome (via remote debug port), open TikTok upload page,
    upload `video_path` with `caption`.

    Returns True on success, False on any failure.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.keys import Keys
    except ImportError:
        log_fn("❌ Chưa cài selenium. Chạy: pip install selenium")
        return False

    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")

    try:
        if driver_path and os.path.exists(driver_path):
            log_fn(f"   ⚙️  Sử dụng ChromeDriver đi kèm GPM: {os.path.basename(driver_path)}")
            try:
                from selenium.webdriver.chrome.service import Service
                service = Service(executable_path=driver_path)
                driver = webdriver.Chrome(service=service, options=opts)
            except Exception:
                try:
                    driver = webdriver.Chrome(executable_path=driver_path, options=opts)
                except Exception:
                    driver = webdriver.Chrome(options=opts)
        else:
            driver = webdriver.Chrome(options=opts)
    except Exception as e:
        log_fn(f"❌ Không thể kết nối Chrome (port {debug_port}): {e}")
        return False

    try:
        wait = WebDriverWait(driver, 60)

        # ── Navigate / Find existing TikTok tab ──────────────────────────
        tiktok_tab = None
        for handle in driver.window_handles:
            try:
                driver.switch_to.window(handle)
                curr_url = driver.current_url.lower()
                if "tiktok.com" in curr_url:
                    tiktok_tab = handle
                    log_fn(f"   🌐 Phát hiện tab TikTok đang mở: {driver.current_url}")
                    # If already on upload page, do not reload
                    if "upload" in curr_url:
                        log_fn("   ✅ Tab đã ở trang upload, giữ nguyên không tải lại.")
                    else:
                        log_fn("   🔄 Tab chưa ở trang upload, đang chuyển hướng...")
                        driver.get("https://tiktok.com/tiktokstudio/upload?from=creator_center&tab=video")
                    break
            except Exception:
                continue

        if not tiktok_tab:
            log_fn("   🌐 Không tìm thấy tab TikTok nào đang mở. Tiến hành mở trang upload mới...")
            driver.get("https://tiktok.com/tiktokstudio/upload?from=creator_center&tab=video")

        import random
        # Chờ ngẫu nhiên để trang tải hoàn tất và ổn định (mô phỏng người xem)
        time.sleep(random.uniform(2.0, 4.0))

        if stop_check():
            return False

        # ── Find file input and send video path ───────────────────────
        file_input = None
        
        # 1. Thử tìm trực tiếp ở trang chính (Các phiên bản TikTok Studio/Creator Center mới đều dạng Direct React)
        try:
            file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            log_fn("   ✅ Tìm thấy ô chọn file trực tiếp ở trang chính")
        except Exception:
            pass

        # 2. Nếu không tìm thấy, quét đệ quy qua các iframe hợp lệ trên trang
        if not file_input:
            try:
                iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
                if iframes:
                    log_fn(f"   ℹ️  Không tìm thấy trực tiếp, quét thử qua {len(iframes)} iframe...")
                    for idx, iframe in enumerate(iframes):
                        try:
                            driver.switch_to.frame(iframe)
                            file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                            if file_input:
                                log_fn(f"   🖼️  Đã tìm thấy ô chọn file trong iframe #{idx+1}")
                                break
                        except Exception:
                            # Quay lại trang chính nếu iframe này không có
                            driver.switch_to.default_content()
            except Exception:
                driver.switch_to.default_content()

        # 3. Chờ đợi lần cuối ở trang chính nếu vẫn chưa tìm thấy (trong trường hợp mạng chậm)
        if not file_input:
            try:
                driver.switch_to.default_content()
                log_fn("   ⏳ Đang đợi ô chọn file tải lên xuất hiện...")
                file_input = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
                )
                log_fn("   ✅ Đã tìm thấy ô chọn file sau thời gian đợi")
            except Exception as e:
                log_fn(f"   ❌ Không tìm thấy ô chọn file!")
                try:
                    log_fn(f"   ℹ️  URL Hiện Tại: {driver.current_url}")
                    log_fn(f"   ℹ️  Tiêu Đề Trang: {driver.title}")
                except Exception:
                    pass
                log_fn(f"   ❌ Lỗi chi tiết: {e}")
                return False

        # Gửi file video
        try:
            file_input.send_keys(os.path.abspath(video_path))
            log_fn(f"   📂 Đã tải file: {os.path.basename(video_path)}")
        except Exception as e:
            log_fn(f"   ❌ Lỗi khi gửi file vào ô tải lên: {e}")
            return False

        if stop_check():
            return False

        # ── Wait for video upload to complete (Real-time Progress Tracker) ───────
        log_fn("   ⏳ Đang tiến hành tải video lên TikTok (Chờ đạt 100%)...")
        upload_complete = False
        start_time = time.time()
        max_wait_time = 600  # Chờ tối đa 10 phút cho video lớn
        last_logged_percent = -1
        
        while time.time() - start_time < max_wait_time:
            if stop_check():
                return False
                
            # Đo phần trăm tải lên ngầm bằng JS
            progress_js = """
            // 1. Tìm các thẻ lá chứa ký tự %
            const leafNodes = Array.from(document.querySelectorAll('div, span, p')).filter(el => el.children.length === 0);
            for (const el of leafNodes) {
                const text = el.innerText || '';
                const m = text.match(/(\\d+)\\s*%/);
                if (m) {
                    return { percent: parseInt(m[1]), text: text };
                }
            }
            // 2. Tìm text báo hoàn thành
            for (const el of leafNodes) {
                const text = el.innerText.toLowerCase();
                if (text.includes('upload complete') || text.includes('hoàn tất') || text.includes('hochgeladen') || text.includes('uploaded')) {
                    return { percent: 100, text: text };
                }
            }
            return null;
            """
            
            try:
                progress_info = driver.execute_script(progress_js)
                if progress_info:
                    percent = progress_info.get("percent")
                    text_found = progress_info.get("text")
                    if percent is not None:
                        if percent != last_logged_percent:
                            log_fn(f"   ⏳ Tiến trình tải lên: {percent}% ({text_found})")
                            last_logged_percent = percent
                        if percent >= 100:
                            upload_complete = True
                            log_fn("   ✅ Tải video lên TikTok hoàn tất 100%!")
                            break
                else:
                    # Kiểm tra xem nút Đăng đã kích hoạt chưa (nút đăng bị disabled trong khi đang tải)
                    post_btn_disabled_js = """
                    let btn = null;
                    try {
                        const xpathResult = document.evaluate("/html/body/div[1]/div/div/div[2]/div[2]/div/div/div/div[6]/div/button[1]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                        btn = xpathResult.singleNodeValue;
                    } catch(e) {}
                    if (!btn) {
                        btn = document.querySelector("button[class*='submit'], button[class*='post'], button[class*='primary'], button[data-e2e='post_video_button']");
                    }
                    if (!btn) {
                        const buttons = document.querySelectorAll('button');
                        const keywords = ['post', 'đăng', 'teilen', 'publish', 'submit', 'posten'];
                        for (const b of buttons) {
                            const text = b.innerText ? b.innerText.toLowerCase().trim() : '';
                            if (keywords.includes(text) || keywords.some(kw => text.includes(kw))) {
                                btn = b;
                                break;
                            }
                        }
                    }
                    if (btn) {
                        return btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true' || btn.className.includes('disabled');
                    }
                    return true;
                    """
                    is_disabled = driver.execute_script(post_btn_disabled_js)
                    if not is_disabled:
                        log_fn("   ✅ Phát hiện nút Đăng đã sẵn sàng (Enabled). Tải lên hoàn tất!")
                        upload_complete = True
                        break
            except Exception:
                pass
                
            time.sleep(3)
            
        if not upload_complete:
            log_fn("   ⚠️  Hết thời gian chờ 10 phút, tự động chuyển sang điền caption...")
            time.sleep(5)

        if stop_check():
            return False

        # Dọn dẹp modal/thông báo che khuất trước khi điền caption
        _clear_overlays(driver, log_fn)

        # ── Fill caption ───────────────────────────────────────────────
        try:
            # Try contenteditable first (TikTok's rich text caption box)
            caption_box = driver.find_element(
                By.CSS_SELECTOR,
                "div[contenteditable='true'], .public-DraftEditor-content"
            )
            
            # Click bằng JS để tránh lỗi Click Intercepted
            try:
                import random
                time.sleep(random.uniform(0.8, 1.5))
                caption_box.click()
            except Exception:
                driver.execute_script("arguments[0].click();", caption_box)
                
            import random
            time.sleep(random.uniform(1.0, 2.0))
            # Select all and delete
            caption_box.send_keys(Keys.CONTROL + "a")
            time.sleep(random.uniform(0.3, 0.6))
            caption_box.send_keys(Keys.BACKSPACE)
            time.sleep(random.uniform(0.5, 1.0))
            
            if human_typing:
                log_fn(f"   ✏️  Đang mô phỏng gõ caption từng ký tự (chống bot)...")
                for char in caption:
                    caption_box.send_keys(char)
                    time.sleep(random.uniform(0.05, 0.18))
            else:
                caption_box.send_keys(caption)
                
            log_fn(f"   ✏️  Caption: {caption[:60]}{'...' if len(caption) > 60 else ''}")
            time.sleep(random.uniform(0.8, 1.5))
        except Exception as e:
            log_fn(f"   ⚠️  Không điền được caption: {e}")

        if stop_check():
            return False

        time.sleep(1)

        # Dọn dẹp modal/thông báo che khuất lần cuối trước khi bấm đăng
        _clear_overlays(driver, log_fn)

        # ── Click Post button ──────────────────────────────────────────
        try:
            log_fn("   ⏳ Đang tìm nút Đăng video...")
            post_btn = None
            
            # 1. Ưu tiên số 1: Sử dụng chính xác XPath do bạn cung cấp
            try:
                user_xpath = "/html/body/div[1]/div/div/div[2]/div[2]/div/div/div/div[6]/div/button[1]"
                post_btn = driver.find_element(By.XPATH, user_xpath)
                if post_btn:
                    log_fn("   🎯 Tìm thấy nút Đăng bằng XPath chính xác!")
            except Exception:
                pass
            
            # 2. Ưu tiên số 2: Sử dụng Selector CSS gộp
            if not post_btn:
                try:
                    combined_sel = "button[class*='submit'], button[class*='post'], button[class*='primary'], button[data-e2e='post_video_button'], div[class*='btn-post']"
                    wait10 = WebDriverWait(driver, 10)
                    post_btn = wait10.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, combined_sel))
                    )
                except Exception:
                    pass

            # 3. Ưu tiên số 3: Quét từ khóa văn bản trên toàn bộ các nút
            if not post_btn:
                buttons = driver.find_elements(By.CSS_SELECTOR, "button")
                post_keywords = ["post", "đăng", "teilen", "publish", "submit", "posten"]
                for btn in buttons:
                    try:
                        text = btn.text.lower().strip()
                        if any(kw in text for kw in post_keywords):
                            post_btn = btn
                            break
                    except Exception:
                        continue

            if post_btn:
                import random
                post_delay = random.uniform(2.0, 4.0)
                log_fn(f"   ⏳ Dừng {post_delay:.2f} giây trước khi bấm Đăng (mô phỏng hành vi thật)...")
                time.sleep(post_delay)
                # Thử click thông thường, nếu bị đè bởi modal thì dùng JS Force Click
                try:
                    post_btn.click()
                    log_fn("   🚀 Đã bấm đăng video!")
                except Exception:
                    driver.execute_script("arguments[0].click();", post_btn)
                    log_fn("   🚀 Đã bấm đăng video (qua JS Force Click)!")
                
                # ── Hộp thoại xác nhận bản quyền (Nếu xuất hiện sau khi bấm đăng) ──
                # ── Hộp thoại xác nhận bản quyền (Nếu xuất hiện sau khi bấm đăng) ──
                log_fn("   ⏳ Đang chờ kiểm tra xem có xuất hiện hộp thoại cảnh báo bản quyền/kiểm duyệt...")
                confirmed = False
                for _ in range(12):
                    time.sleep(random.uniform(2.0, 3.5))
                    try:
                        # Thực hiện click lập tức khi phát hiện nút
                        click_btn_js = """
                        const xpaths = [
                            "/html/body/div[6]/div/div/div[3]/button[2]/div/div",
                            "/html/body/div[5]/div/div/div[3]/button[2]/div/div",
                            "/html/body/div[7]/div/div/div[3]/button[2]/div/div",
                            "//button[contains(., 'Post now')]//div/div",
                            "//button[contains(., 'Post now')]//div",
                            "//button[contains(., 'Post now')]",
                            "//button[contains(., 'Đăng ngay')]//div/div",
                            "//button[contains(., 'Đăng ngay')]//div",
                            "//button[contains(., 'Đăng ngay')]",
                            "//button[contains(., 'Vẫn đăng')]//div/div",
                            "//button[contains(., 'Vẫn đăng')]//div",
                            "//button[contains(., 'Vẫn đăng')]"
                        ];
                        for (const xp of xpaths) {
                            try {
                                const xr = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                                const el = xr.singleNodeValue;
                                if (el) {
                                    const rect = el.getBoundingClientRect();
                                    if (rect.width > 0 && rect.height > 0) {
                                        el.click();
                                        return true;
                                    }
                                }
                            } catch(e) {}
                        }
                        
                        const keywords = [
                            'publish anyway', 'post anyway', 'post now', 'publish now', 
                            'đăng ngay', 'vẫn đăng', 'vẫn muốn đăng', 'đăng ngay bây giờ',
                            'veröffentlichen', 'trotzdem veröffentlichen', 'jetzt veröffentlichen',
                            'confirm', 'xác nhận'
                        ];
                        const elements = document.querySelectorAll('button, div[role="button"], span[role="button"], div, span');
                        for (const el of elements) {
                            const text = el.innerText ? el.innerText.toLowerCase().trim() : '';
                            let matched = keywords.some(kw => text === kw || (kw.includes(' ') && text.includes(kw)));
                            
                            if (matched) {
                                const negatives = ['không', 'hủy', 'cancel', 'no', 'nein', 'close', 'zurück', 'quay lại'];
                                if (negatives.some(neg => text.includes(neg))) {
                                    matched = false;
                                }
                            }
                            
                            if (matched) {
                                const rect = el.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0) {
                                    // Thử tìm phần tử div/span con sâu nhất chứa chữ để click trực tiếp (React event bound)
                                    const children = el.querySelectorAll('div, span');
                                    for (const child of children) {
                                        const childText = child.innerText ? child.innerText.toLowerCase().trim() : '';
                                        if (keywords.some(kw => childText === kw)) {
                                            const crect = child.getBoundingClientRect();
                                            if (crect.width > 0 && crect.height > 0) {
                                                child.click();
                                                return true;
                                            }
                                        }
                                    }
                                    el.click();
                                    return true;
                                }
                            }
                        }
                        return false;
                        """
                        if driver.execute_script(click_btn_js):
                            log_fn("   🚀 Đã tự động click vượt qua cảnh báo bản quyền/kiểm duyệt!")
                            confirmed = True
                            break
                    except Exception:
                        pass
                if not confirmed:
                    log_fn("   ℹ️  Không phát hiện hộp thoại cảnh báo bản quyền/kiểm duyệt (hoặc đã tự động qua).")
            else:
                log_fn("   ⚠️  Không tìm thấy nút đăng bài. Hãy tự bấm trong trình duyệt.")
                return False

        except Exception as e:
            log_fn(f"   ❌ Lỗi khi bấm đăng: {e}")
            return False

        # ── Wait for upload to complete ────────────────────────────────
        log_fn("   ⏳ Chờ upload hoàn tất...")
        time.sleep(delay_after + 5)  # wait for upload + server processing

        # Try detecting success page
        try:
            wait30 = WebDriverWait(driver, 30)
            # TikTok may redirect or show success toast
            wait30.until(
                lambda d: "tiktok.com" in d.current_url
                and "upload" not in d.current_url.lower()
                or len(d.find_elements(By.CSS_SELECTOR, "[class*='success'], [class*='complete']")) > 0
            )
            log_fn("   ✅ Upload thành công!")
        except Exception:
            log_fn("   ℹ️  Không xác nhận được kết quả, có thể vẫn thành công.")

        import random
        post_close_delay = random.uniform(4.0, 7.0)
        log_fn(f"   ⏳ Dừng {post_close_delay:.2f} giây trước khi hoàn tất...")
        time.sleep(post_close_delay)
        return True

    except Exception as e:
        log_fn(f"   ❌ Lỗi upload: {e}")
        return False
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        # Do NOT quit() — GPM is managing the browser window


# ─────────────────────────────────────────────────────────────────────────────
# Robust Port Extractor Helper
# ─────────────────────────────────────────────────────────────────────────────

def _extract_port_robustly(result) -> int:
    """Recursively search for a port or address string in the response dict/list."""
    if not result:
        return None

    if isinstance(result, bool):
        return None

    # If it is a string, check if it contains 127.0.0.1:XXXX or localhost:XXXX
    if isinstance(result, str):
        import re
        match = re.search(r'(?:127\.0\.0\.1|localhost):(\d+)', result)
        if match:
            p = int(match.group(1))
            if p > 1000:
                return p
        # fallback if it's just a raw number in string form
        if result.strip().isdigit():
            p = int(result.strip())
            if p > 1000:
                return p

    if isinstance(result, (int, float)):
        p = int(result)
        if p > 1000:
            return p

    if isinstance(result, dict):
        # Direct key search priority
        keys_to_try = [
            "selenium_remote_debug_address",
            "selenium_address",
            "remote_debugging_port",
            "remote_debug_port",
            "address",
            "port",
            "debugPort",
            "debug_port"
        ]
        for k in keys_to_try:
            val = result.get(k)
            if val is not None:
                port = _extract_port_robustly(val)
                if port:
                    return port

        # Recursive fallback search
        for val in result.values():
            port = _extract_port_robustly(val)
            if port:
                return port

    if isinstance(result, list):
        for val in result:
            port = _extract_port_robustly(val)
            if port:
                return port

    return None


def _extract_driver_path(result) -> str:
    """Recursively search for a driver path string in GPM start response."""
    if not result:
        return None
    if isinstance(result, str):
        cleaned = result.strip().replace('"', '').replace("'", "")
        if "chromedriver" in cleaned.lower() and os.path.exists(cleaned):
            return cleaned
        return None
    if isinstance(result, dict):
        keys = ["driver_path", "driver", "canvas_driver", "chromedriver_path", "executable_path"]
        for k in keys:
            val = result.get(k)
            if val and isinstance(val, str):
                cleaned = val.strip().replace('"', '').replace("'", "")
                if os.path.exists(cleaned):
                    return cleaned
        # fallback recursive
        for val in result.values():
            d = _extract_driver_path(val)
            if d:
                return d
    if isinstance(result, list):
        for val in result:
            d = _extract_driver_path(val)
            if d:
                return d
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Worker Thread
# ─────────────────────────────────────────────────────────────────────────────

class GpmUploadThread(QThread):
    """
    Background worker: support parallel profile execution using ThreadPoolExecutor,
    and multi-tab parallel video uploads within each GPM profile window.
    """
    progress    = pyqtSignal(str)       # short status (shown in info label)
    log_message = pyqtSignal(str)       # detailed log (shown in terminal)
    percent     = pyqtSignal(int)       # 0-100
    finished    = pyqtSignal(int, int)  # (success_count, failed_count)

    def __init__(
        self,
        profiles: list[dict],
        gpm_host: str,
        gpm_port: int,
        caption_mode: str,
        fixed_caption: str,
        videos_per_profile: int,
        delay_seconds: float,
        close_after: bool = False,
        move_done: bool = False,
        max_concurrent_profiles: int = 3,
        parallel_tabs: int = 3,
        human_typing: bool = True,
    ):
        super().__init__()
        self.profiles                = profiles
        self.gpm_host                = gpm_host
        self.gpm_port                = gpm_port
        self.caption_mode            = caption_mode
        self.fixed_caption           = fixed_caption
        self.videos_per_profile      = videos_per_profile
        self.delay_seconds           = delay_seconds
        self.close_after             = close_after
        self.move_done               = move_done
        self.max_concurrent_profiles = max_concurrent_profiles
        self.parallel_tabs           = parallel_tabs
        self.human_typing            = human_typing
        self.is_running              = True
        self._lock                   = threading.Lock()

    def stop(self):
        self.is_running = False

    # ── Main ─────────────────────────────────────────────────────────────────
    def run(self):
        import concurrent.futures
        
        api = GpmApi(host=self.gpm_host, port=self.gpm_port)

        total_profiles = len(self.profiles)
        success_total  = 0
        failed_total   = 0
        done_profiles  = 0

        # ── Pre-allocate unique videos per profile ────────────────────────────
        self.log_message.emit("🔍 Đang quét và phân bổ video không trùng lặp cho các profile...")
        used_videos = set()
        for p in self.profiles:
            folder = p.get("folder", "")
            raw_videos = []
            if folder and os.path.isdir(folder):
                raw_videos = sorted(
                    os.path.join(folder, f) for f in os.listdir(folder)
                    if os.path.isfile(os.path.join(folder, f))
                    and f.lower().endswith(VALID_VIDEO_EXTS)
                )
            
            # Filter out already used ones to guarantee absolutely zero duplicate video uploads
            available = [v for v in raw_videos if v not in used_videos]
            
            limit = self.videos_per_profile
            selected = available[:limit] if limit > 0 else available
            
            for v in selected:
                used_videos.add(v)
                
            p["videos"] = selected

        self.log_message.emit(
            f"🚀 Bắt đầu chạy song song lên tới {self.max_concurrent_profiles} GPM profile..."
        )
        self.percent.emit(0)

        # ─────────────────────────────────────────────────────────────────────
        # Hàm xử lý toàn bộ tiến trình cho MỘT GPM Profile
        # ─────────────────────────────────────────────────────────────────────
        def process_one_profile(p):
            nonlocal success_total, failed_total, done_profiles
            # Wrap toàn bộ để đảm bảo mọi exception đều được bắt,
            # tránh ThreadPoolExecutor treo hoặc crash toàn bộ app
            try:
                _process_one_profile_inner(p)
            except Exception as _top_err:
                pname = p.get("name", p.get("id", "?"))
                try:
                    self.log_message.emit(f"   ❌ [{pname}] Lỗi không xác định trong tiến trình: {_top_err}")
                except Exception:
                    pass
                with self._lock:
                    done_profiles += 1
                    self.percent.emit(int(done_profiles * 100 / total_profiles))

        def _process_one_profile_inner(p):
            nonlocal success_total, failed_total, done_profiles
            
            if not self.is_running:
                return

            pid    = p["id"]
            pname  = p.get("name", pid)
            folder = p.get("folder", "")

            # ── 1. Lấy danh sách video đã phân bổ không trùng ─────────────────
            videos = p.get("videos", [])
            if not videos:
                self.log_message.emit(
                    f"⚠️  [{pname}] Không có video khả dụng (hoặc đã bị trùng lặp) trong thư mục: {folder}"
                )
                with self._lock:
                    done_profiles += 1
                    self.percent.emit(int(done_profiles * 100 / total_profiles))
                return

            self.log_message.emit(
                f"─── Profile: {pname} (ID: {pid}) ───\n"
                f"   📂 Folder: {folder}  |  Có {len(videos)} video chuẩn bị upload..."
            )

            # ── 2. Khởi động GPM Profile qua API ──────────────────────────────
            debug_port = None
            driver_path = None
            try:
                self.log_message.emit(f"   🔗 [{pname}] Đang kết nối và khởi động GPM...")
                result = api.start_profile(pid)
                
                debug_port = _extract_port_robustly(result)
                driver_path = _extract_driver_path(result)
                
                if not debug_port:
                    raise RuntimeError(
                        f"GPM không trả về cổng debug port. Response: {json.dumps(result)}"
                    )

                self.log_message.emit(
                    f"   ✅ [{pname}] Profile khởi động thành công! Chrome Debug Port: {debug_port}"
                )
                time.sleep(3)
            except Exception as e:
                self.log_message.emit(f"   ❌ [{pname}] Lỗi không thể khởi động profile GPM: {e}")
                with self._lock:
                    failed_total += len(videos)
                    done_profiles += 1
                    self.percent.emit(int(done_profiles * 100 / total_profiles))
                return

            # ── 3. Kết nối Selenium ───────────────────────────────────────────
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.keys import Keys

            opts = Options()
            opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{debug_port}")

            try:
                if driver_path and os.path.exists(driver_path):
                    self.log_message.emit(f"   ⚙️  [{pname}] Sử dụng ChromeDriver đi kèm GPM: {os.path.basename(driver_path)}")
                    from selenium.webdriver.chrome.service import Service
                    service = Service(executable_path=driver_path)
                    driver = webdriver.Chrome(service=service, options=opts)
                else:
                    driver = webdriver.Chrome(options=opts)
            except Exception as e:
                self.log_message.emit(f"   ❌ [{pname}] Thất bại khi thiết lập kết nối Selenium ChromeDriver: {e}")
                with self._lock:
                    failed_total += len(videos)
                    done_profiles += 1
                    self.percent.emit(int(done_profiles * 100 / total_profiles))
                return

            # ── 4. Quản lý Tab Upload Song Song (Tab Worker Pool) ─────────────
            wait = WebDriverWait(driver, 60)
            active_jobs = []  # List dicts: {"handle": ..., "video_path": ..., "caption": ..., "status": "uploading"/"ready", "last_percent": -1}
            video_idx = 0
            profile_success = 0
            profile_failed  = 0
            
            main_handle = driver.current_window_handle

            try:
                while video_idx < len(videos) or active_jobs:
                    if not self.is_running:
                        break

                    # A. Bơm đầy các tab song song lên tới giới hạn parallel_tabs
                    while len(active_jobs) < self.parallel_tabs and video_idx < len(videos):
                        vpath = videos[video_idx]
                        vname = os.path.basename(vpath)
                        caption = _get_caption(vpath, self.caption_mode, self.fixed_caption)
                        
                        # Thêm delay giữa các lần upload video
                        if video_idx > 0 and self.delay_seconds > 0:
                            self.log_message.emit(f"   ⏳ [{pname}] Chờ {self.delay_seconds} giây delay trước khi bắt đầu video tiếp theo ({vname})...")
                            # Chia nhỏ sleep để có thể dừng ngay lập tức nếu người dùng bấm Dừng
                            for _ in range(int(self.delay_seconds * 2)):
                                if not self.is_running:
                                    break
                                time.sleep(0.5)
                            if not self.is_running:
                                break
                                
                        video_idx += 1

                        try:
                            # Đảm bảo driver đang tập trung vào một window hợp lệ trước khi thao tác
                            try:
                                _ = driver.current_window_handle
                            except Exception:
                                if driver.window_handles:
                                    driver.switch_to.window(driver.window_handles[0])

                            # Mở tab mới hoặc tận dụng tab chính ban đầu
                            if len(active_jobs) == 0 and len(driver.window_handles) == 1:
                                handle = main_handle
                            else:
                                driver.execute_script("window.open('about:blank', '_blank');")
                                time.sleep(0.5)
                                handle = driver.window_handles[-1]

                            driver.switch_to.window(handle)
                            driver.get("https://tiktok.com/tiktokstudio/upload?from=creator_center&tab=video")
                            self.log_message.emit(f"   🌐 [{pname}] [Tab {len(active_jobs)+1}] Đang mở trang upload cho video: {vname}")
                            
                            # Chờ trang load ổn định
                            import random
                            time.sleep(random.uniform(2.0, 4.0))

                            # Nạp file video vào
                            file_input = _find_file_input_robustly(driver, self.log_message.emit, wait)
                            if file_input:
                                try:
                                    file_input.send_keys(os.path.abspath(vpath))
                                    self.log_message.emit(f"   📂 [{pname}] [Tab {len(active_jobs)+1}] Đã nạp file thành công: {vname}")
                                    active_jobs.append({
                                        "handle": handle,
                                        "video_path": vpath,
                                        "caption": caption,
                                        "status": "uploading",
                                        "last_percent": -1
                                    })
                                except Exception as fe:
                                    self.log_message.emit(f"   ❌ [{pname}] [Tab {len(active_jobs)+1}] Lỗi nạp video {vname}: {fe}")
                                    profile_failed += 1
                            else:
                                self.log_message.emit(f"   ❌ [{pname}] [Tab {len(active_jobs)+1}] Không tìm thấy ô nạp file cho {vname}")
                                profile_failed += 1
                        except Exception as tab_open_err:
                            self.log_message.emit(f"   ❌ [{pname}] Lỗi khi khởi tạo Tab upload mới cho {vname}: {tab_open_err}")
                            profile_failed += 1

                    # B. Quét kiểm tra tiến trình của các tab đang upload
                    time.sleep(3)
                    for job in list(active_jobs):
                        if not self.is_running:
                            break

                        handle = job["handle"]
                        vname = os.path.basename(job["video_path"])

                        try:
                            driver.switch_to.window(handle)

                            # Trích xuất % tiến trình
                            progress_info = _check_progress_js(driver)
                            if progress_info:
                                percent = progress_info.get("percent")
                                text_found = progress_info.get("text")
                                if percent is not None:
                                    if percent != job["last_percent"]:
                                        self.log_message.emit(f"   ⏳ [{pname}] [{vname}] Tiến trình: {percent}% ({text_found})")
                                        job["last_percent"] = percent
                                    if percent >= 100:
                                        # Kiểm tra xem nút Đăng đã được kích hoạt chưa (TikTok xử lý video xong)
                                        is_disabled = _check_post_disabled_js(driver)
                                        if not is_disabled:
                                            job["status"] = "ready"
                                        else:
                                            if job["last_percent"] != 100.5:
                                                self.log_message.emit(f"   ⏳ [{pname}] [{vname}] Tải video lên đạt 100%, đang chờ TikTok xử lý để kích hoạt nút Đăng...")
                                                job["last_percent"] = 100.5
                            else:
                                # Kiểm tra xem nút đăng đã được kích hoạt (enabled) chưa
                                is_disabled = _check_post_disabled_js(driver)
                                if not is_disabled:
                                    job["status"] = "ready"

                            # C. Điền caption và Bấm Đăng nếu video đã tải xong 100%
                            if job["status"] == "ready":
                                self.log_message.emit(f"   ✏️  [{pname}] [{vname}] Upload xong! Bắt đầu điền Caption & Đăng...")
                                
                                # Xử lý popup/modal trước khi viết
                                import random
                                time.sleep(random.uniform(1.5, 2.5))
                                _clear_overlays(driver, self.log_message.emit)
                                time.sleep(random.uniform(1.0, 2.0))
                                _fill_caption_robustly(driver, job["caption"], self.log_message.emit, Keys, self.human_typing)
                                time.sleep(random.uniform(1.5, 2.5))
                                _clear_overlays(driver, self.log_message.emit)
                                time.sleep(random.uniform(1.0, 2.0))

                                # Click Đăng
                                ok = _click_post_button_robustly(driver, self.log_message.emit, wait, By, EC)
                                if ok:
                                    profile_success += 1
                                    self.log_message.emit(f"   ✅ [{pname}] [{vname}] Upload & Đăng thành công!")
                                    
                                    # Di chuyển file đã up vào thư mục done
                                    if self.move_done:
                                        done_dir = os.path.join(os.path.dirname(job["video_path"]), "done")
                                        os.makedirs(done_dir, exist_ok=True)
                                        try:
                                            import shutil
                                            shutil.move(job["video_path"], os.path.join(done_dir, vname))
                                        except Exception:
                                            pass
                                else:
                                    profile_failed += 1
                                    self.log_message.emit(f"   ❌ [{pname}] [{vname}] Đăng thất bại!")

                                # Nghỉ vài giây trước khi đóng tab để mô phỏng hành vi thật (chờ trình duyệt hoàn tất gửi gói tin)
                                import random
                                post_close_delay = random.uniform(4.0, 7.0)
                                self.log_message.emit(f"   ⏳ [{pname}] Dừng {post_close_delay:.2f} giây trước khi đóng tab...")
                                time.sleep(post_close_delay)

                                # Đóng Tab này để dọn dẹp dung lượng RAM
                                if len(driver.window_handles) > 1:
                                    try:
                                        driver.close()
                                    except Exception:
                                        pass
                                    
                                    # CHÚ Ý: Sau khi close(), phải switch_to sang một window khác đang mở,
                                    # tránh lỗi "no such window" cho các thao tác tiếp theo.
                                    try:
                                        if driver.window_handles:
                                            driver.switch_to.window(driver.window_handles[0])
                                    except Exception:
                                        pass
                                active_jobs.remove(job)

                        except Exception as tab_err:
                            self.log_message.emit(f"   ⚠️  [{pname}] [{vname}] Lỗi điều khiển Tab: {tab_err}")
                            try:
                                active_jobs.remove(job)
                            except Exception:
                                pass
                            profile_failed += 1

            except Exception as loop_err:
                self.log_message.emit(f"   ❌ [{pname}] Lỗi trong vòng lặp upload: {loop_err}")
            finally:
                # Đóng GPM nếu có cài đặt đóng profile
                if self.close_after:
                    try:
                        # Thêm trễ vài giây trước khi tắt hẳn profile để đảm bảo đồng bộ hóa dữ liệu profile GPM
                        import random
                        profile_close_delay = random.uniform(5.0, 8.0)
                        self.log_message.emit(f"   ⏳ [{pname}] Chờ {profile_close_delay:.2f} giây trước khi tắt Profile GPM...")
                        time.sleep(profile_close_delay)
                        api.close_profile(pid)
                        self.log_message.emit(f"   🔒 [{pname}] Đã tự động đóng Profile GPM.")
                    except Exception:
                        pass
                
                # Cập nhật kết quả chung
                with self._lock:
                    success_total += profile_success
                    failed_total += profile_failed
                    done_profiles += 1
                    self.percent.emit(int(done_profiles * 100 / total_profiles))
                    self.progress.emit(f"Profile {pname} hoàn thành.")

        # ─────────────────────────────────────────────────────────────────────
        # Khởi chạy song song đa luồng giữa các GPM Profile
        # ─────────────────────────────────────────────────────────────────────
        max_workers = min(self.max_concurrent_profiles, total_profiles)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_one_profile, p) for p in self.profiles]
            # Chờ từng future một, log exception nếu có để tránh treo app
            for fut in concurrent.futures.as_completed(futures):
                try:
                    fut.result()
                except Exception as fut_err:
                    self.log_message.emit(f"   ⚠️  Một tiến trình profile gặp lỗi ngoại lệ: {fut_err}")

        # ── Kết thúc toàn bộ tiến trình ─────────────────────────────────────
        if self.is_running:
            self.log_message.emit(
                f"🎉 Hoàn tất toàn bộ tác vụ! ✅ Tổng thành công: {success_total} | ❌ Tổng thất bại: {failed_total}"
            )
        else:
            self.log_message.emit(
                f"⏹️ Đã dừng luồng xử lý theo yêu cầu. ✅ Đăng được: {success_total} video."
            )

        self.percent.emit(100)
        self.progress.emit("Hoàn tất!")
        self.finished.emit(success_total, failed_total)


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions for Tab Worker Pool
# ─────────────────────────────────────────────────────────────────────────────

def _find_file_input_robustly(driver, log_fn, wait):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    
    # 1. Tìm trực tiếp
    try:
        return driver.find_element(By.CSS_SELECTOR, "input[type='file']")
    except Exception:
        pass
        
    # 2. Tìm đệ quy trong iframe
    try:
        iframes = driver.find_elements(By.CSS_SELECTOR, "iframe")
        for iframe in iframes:
            try:
                driver.switch_to.frame(iframe)
                file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                if file_input:
                    return file_input
            except Exception:
                driver.switch_to.default_content()
    except Exception:
        driver.switch_to.default_content()
        
    # 3. Đợi fallback
    try:
        driver.switch_to.default_content()
        return wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
    except Exception:
        return None


def _check_progress_js(driver) -> dict:
    progress_js = """
    const leafNodes = Array.from(document.querySelectorAll('div, span, p')).filter(el => el.children.length === 0);
    for (const el of leafNodes) {
        const text = el.innerText || '';
        const m = text.match(/(\\d+)\\s*%/);
        if (m) {
            return { percent: parseInt(m[1]), text: text };
        }
    }
    for (const el of leafNodes) {
        const text = el.innerText.toLowerCase();
        if (text.includes('upload complete') || text.includes('hoàn tất') || text.includes('hochgeladen') || text.includes('uploaded')) {
            return { percent: 100, text: text };
        }
    }
    return null;
    """
    try:
        return driver.execute_script(progress_js)
    except Exception:
        return None


def _check_post_disabled_js(driver) -> bool:
    post_btn_disabled_js = """
    let btn = null;
    try {
        const xpathResult = document.evaluate("/html/body/div[1]/div/div/div[2]/div[2]/div/div/div/div[6]/div/button[1]", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
        btn = xpathResult.singleNodeValue;
    } catch(e) {}
    if (!btn) {
        btn = document.querySelector("button[class*='submit'], button[class*='post'], button[class*='primary'], button[data-e2e='post_video_button']");
    }
    if (!btn) {
        const buttons = document.querySelectorAll('button');
        const keywords = ['post', 'đăng', 'teilen', 'publish', 'submit', 'posten'];
        for (const b of buttons) {
            const text = b.innerText ? b.innerText.toLowerCase().trim() : '';
            if (keywords.includes(text) || keywords.some(kw => text.includes(kw))) {
                btn = b;
                break;
            }
        }
    }
    if (btn) {
        return btn.hasAttribute('disabled') || btn.getAttribute('aria-disabled') === 'true' || btn.className.includes('disabled');
    }
    return true;
    """
    try:
        return driver.execute_script(post_btn_disabled_js)
    except Exception:
        return True


def _fill_caption_robustly(driver, caption, log_fn, Keys, human_typing: bool = True):
    from selenium.webdriver.common.by import By
    import random
    try:
        caption_box = driver.find_element(By.CSS_SELECTOR, "div[contenteditable='true'], .public-DraftEditor-content")
        # Click bằng JS hoặc thông thường
        try:
            time.sleep(random.uniform(0.8, 1.5))
            caption_box.click()
        except Exception:
            driver.execute_script("arguments[0].click();", caption_box)
        
        # Dừng ngẫu nhiên mô phỏng người click vào ô nhập
        time.sleep(random.uniform(1.0, 2.0))
        
        # Chọn tất cả và xóa đi để đảm bảo ô trống
        caption_box.send_keys(Keys.CONTROL + "a")
        time.sleep(random.uniform(0.3, 0.6))
        caption_box.send_keys(Keys.BACKSPACE)
        time.sleep(random.uniform(0.5, 1.0))
        
        if human_typing:
            # Mô phỏng gõ từng ký tự với độ trễ ngẫu nhiên siêu mượt
            log_fn(f"   ✏️  Đang mô phỏng gõ caption từng ký tự (chống bot)...")
            for char in caption:
                caption_box.send_keys(char)
                # Dừng ngẫu nhiên từ 0.05 đến 0.18 giây giữa các phím
                time.sleep(random.uniform(0.05, 0.18))
        else:
            caption_box.send_keys(caption)
            log_fn(f"   ✏️  Caption: {caption[:60]}{'...' if len(caption) > 60 else ''}")
            
        time.sleep(random.uniform(0.8, 1.5))
    except Exception as e:
        log_fn(f"   ⚠️  Không điền được caption: {e}")


def _click_post_button_robustly(driver, log_fn, wait, By, EC) -> bool:
    try:
        from selenium.webdriver.support.ui import WebDriverWait  # ensure import
        post_btn = None
        user_xpath = "/html/body/div[1]/div/div/div[2]/div[2]/div/div/div/div[6]/div/button[1]"
        try:
            post_btn = driver.find_element(By.XPATH, user_xpath)
        except Exception:
            pass
            
        if not post_btn:
            try:
                combined_sel = "button[class*='submit'], button[class*='post'], button[class*='primary'], button[data-e2e='post_video_button'], div[class*='btn-post']"
                wait10 = WebDriverWait(driver, 10)
                post_btn = wait10.until(EC.element_to_be_clickable((By.CSS_SELECTOR, combined_sel)))
            except Exception:
                pass

        if not post_btn:
            buttons = driver.find_elements(By.CSS_SELECTOR, "button")
            post_keywords = ["post", "đăng", "teilen", "publish", "submit", "posten"]
            for btn in buttons:
                try:
                    text = btn.text.lower().strip()
                    if any(kw in text for kw in post_keywords):
                        post_btn = btn
                        break
                except Exception:
                    continue

        if post_btn:
            import random
            post_delay = random.uniform(2.0, 4.0)
            log_fn(f"   ⏳ Dừng {post_delay:.2f} giây trước khi bấm Đăng (mô phỏng hành vi thật)...")
            time.sleep(post_delay)
            try:
                post_btn.click()
                log_fn("   🚀 Đã bấm đăng video!")
            except Exception:
                driver.execute_script("arguments[0].click();", post_btn)
                log_fn("   🚀 Đã bấm đăng video (JS Force Click)!")
            
            # Hộp thoại xác nhận bản quyền dự phòng
            log_fn("   ⏳ Đang chờ kiểm tra xem có xuất hiện hộp thoại cảnh báo bản quyền/kiểm duyệt...")
            confirmed = False
            for _ in range(12):
                time.sleep(random.uniform(2.0, 3.5))
                try:
                    # Thực hiện click lập tức khi phát hiện nút
                    click_btn_js = """
                    const xpaths = [
                        "/html/body/div[6]/div/div/div[3]/button[2]/div/div",
                        "/html/body/div[5]/div/div/div[3]/button[2]/div/div",
                        "/html/body/div[7]/div/div/div[3]/button[2]/div/div",
                        "//button[contains(., 'Post now')]//div/div",
                        "//button[contains(., 'Post now')]//div",
                        "//button[contains(., 'Post now')]",
                        "//button[contains(., 'Đăng ngay')]//div/div",
                        "//button[contains(., 'Đăng ngay')]//div",
                        "//button[contains(., 'Đăng ngay')]",
                        "//button[contains(., 'Vẫn đăng')]//div/div",
                        "//button[contains(., 'Vẫn đăng')]//div",
                        "//button[contains(., 'Vẫn đăng')]"
                    ];
                    for (const xp of xpaths) {
                        try {
                            const xr = document.evaluate(xp, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                            const el = xr.singleNodeValue;
                            if (el) {
                                const rect = el.getBoundingClientRect();
                                if (rect.width > 0 && rect.height > 0) {
                                    el.click();
                                    return true;
                                }
                            }
                        } catch(e) {}
                    }
                    
                    const keywords = [
                        'publish anyway', 'post anyway', 'post now', 'publish now', 
                        'đăng ngay', 'vẫn đăng', 'vẫn muốn đăng', 'đăng ngay bây giờ',
                        'veröffentlichen', 'trotzdem veröffentlichen', 'jetzt veröffentlichen',
                        'confirm', 'xác nhận'
                    ];
                    const elements = document.querySelectorAll('button, div[role="button"], span[role="button"], div, span');
                    for (const el of elements) {
                        const text = el.innerText ? el.innerText.toLowerCase().trim() : '';
                        let matched = keywords.some(kw => text === kw || (kw.includes(' ') && text.includes(kw)));
                        
                        if (matched) {
                            const negatives = ['không', 'hủy', 'cancel', 'no', 'nein', 'close', 'zurück', 'quay lại'];
                            if (negatives.some(neg => text.includes(neg))) {
                                matched = false;
                            }
                        }
                        
                        if (matched) {
                            const rect = el.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                // Thử tìm phần tử div/span con sâu nhất chứa chữ để click trực tiếp (React event bound)
                                const children = el.querySelectorAll('div, span');
                                for (const child of children) {
                                    const childText = child.innerText ? child.innerText.toLowerCase().trim() : '';
                                    if (keywords.some(kw => childText === kw)) {
                                        const crect = child.getBoundingClientRect();
                                        if (crect.width > 0 && crect.height > 0) {
                                            child.click();
                                            return true;
                                        }
                                    }
                                }
                                el.click();
                                return true;
                            }
                        }
                    }
                    return false;
                    """
                    if driver.execute_script(click_btn_js):
                        log_fn("   🚀 Đã tự động click vượt qua cảnh báo bản quyền/kiểm duyệt!")
                        confirmed = True
                        break
                except Exception:
                    pass
            if not confirmed:
                log_fn("   ℹ️  Không phát hiện hộp thoại cảnh báo bản quyền/kiểm duyệt (hoặc đã tự động qua).")

            # ── Đợi điều hướng hoặc báo thành công thực tế để tránh đóng tab quá nhanh ──
            log_fn("   ⏳ Đang chờ TikTok xác nhận đăng bài thành công...")
            success = False
            start_wait = time.time()
            while time.time() - start_wait < 30:
                try:
                    curr_url = driver.current_url.lower()
                    # 1. Nếu URL đã chuyển hướng khỏi trang upload
                    if "upload" not in curr_url and "tiktok.com" in curr_url:
                        success = True
                        break
                    # 2. Hoặc xuất hiện phần tử báo thành công / quản lý bài viết
                    success_elements = driver.find_elements(By.CSS_SELECTOR, "[class*='success'], [class*='complete'], [class*='manage']")
                    if success_elements:
                        success = True
                        break
                except Exception:
                    pass
                time.sleep(2)
            
            if success:
                log_fn("   ✅ Đã nhận được xác nhận đăng bài thành công từ TikTok!")
            else:
                log_fn("   ℹ️  Hết thời gian chờ xác nhận, tiếp tục tiến trình...")
            return True
        else:
            log_fn("   ⚠️  Không tìm thấy nút đăng bài.")
            return False
            
    except Exception as e:
        log_fn(f"   ❌ Lỗi khi đăng video: {e}")
        return False
