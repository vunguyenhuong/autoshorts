import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QLabel, QFileDialog, QGroupBox, QMessageBox, QCheckBox,
    QTextEdit, QScrollArea, QSizePolicy, QComboBox, QDateEdit, QSpinBox, QPushButton, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate
from core.downloader import ShortsDownloader
from ui.components import (
    PrimaryButton, SecondaryButton, DangerButton, GhostButton,
    SuccessButton, SmallDangerButton, StyledProgressBar, InfoBadge
)

class FetcherThread(QThread):
    finished = pyqtSignal(list) # (videos)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks
        self.downloader = ShortsDownloader()
        self.is_running = True

    def stop(self):
        self.is_running = False

    def _adjust_channel_url(self, url, content_type):
        """
        Auto-adjust channel URL to point to the correct content type.
        If it's already a direct video link, return it as is.
        """
        import re
        url = url.strip().rstrip('/')
        
        # Check if it's a direct video link
        # YouTube: watch?v=, /shorts/, youtu.be/
        # Other platforms are usually direct links too
        video_patterns = [
            r'watch\?v=',
            r'/shorts/',
            r'youtu\.be/',
            r'facebook\.com/.+/videos/',
            r'tiktok\.com/.+/video/'
        ]
        if any(re.search(p, url) for p in video_patterns):
            return url

        # It's a channel link, apply adjustment
        # Remove existing /shorts or /videos suffix
        url = re.sub(r'/(shorts|videos)$', '', url)
        
        # Append the correct suffix
        if content_type == 'videos':
            url += '/videos'
        else:
            url += '/shorts'
        
        return url

    def run(self):
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            all_videos = []
            flat_tasks = []
            for t in self.tasks:
                content_type = t.get('content_type', 'shorts')
                for url in t['urls']:
                    # Auto-adjust URL based on content type
                    adjusted_url = self._adjust_channel_url(url.strip(), content_type)
                    flat_tasks.append({
                        'url': adjusted_url, 
                        'original_url': url.strip(),
                        'limit': t['limit'], 
                        'folder': t['folder'],
                        'folder_mode': t.get('folder_mode', 'flat'),
                        'task_id': t.get('task_id', 0),
                        'content_type': content_type
                    })
            
            total_channels = len(flat_tasks)
            self.current_channel_count = 0
            
            def fetch_channel(task):
                url = task['url']
                limit = task['limit']
                folder = task['folder']
                content_type = task.get('content_type', 'shorts')
                
                # Check if it's a direct video link
                import re
                video_patterns = [r'watch\?v=', r'/shorts/', r'youtu\.be/', r'facebook\.com/.+/videos/', r'tiktok\.com/.+/video/']
                is_direct_video = any(re.search(p, url) for p in video_patterns)
                
                if is_direct_video:
                    self.progress.emit(f"🎯 Nhận diện link video: {url.split('/')[-1][:20]}...")
                    # Fetch full metadata to get the actual channel URL, view count, etc.
                    thread_downloader = ShortsDownloader()
                    info = thread_downloader.get_video_info(url)
                    
                    if info:
                        channel_url = info.get('channel_url')
                        title = info.get('title', "Direct Video")
                        video_id = info.get('id', url.split('/')[-1])
                        view_count = info.get('view_count', 0)
                    else:
                        channel_url = None
                        title = "Direct Video"
                        video_id = url.split('/')[-1]
                        view_count = 0

                    videos = [{
                        'id': video_id,
                        'url': url,
                        'title': title,
                        'view_count': view_count
                    }]
                    display_name = "Video Trực Tiếp"
                else:
                    # Extract channel name for cleaner display
                    display_name = url.split('/')[-1] if '/' in url else url
                    if display_name.lower() in ('shorts', 'reels', 'videos'):
                        display_name = url.split('/')[-2] if len(url.split('/')) > 1 else url
                    
                    type_label = "📹 Videos" if content_type == 'videos' else "📱 Shorts"
                    self.progress.emit(f"⏳ [{type_label}] Đang quét kênh {display_name}...")
                    
                    # Each thread needs its own downloader instance to prevent potential issues
                    thread_downloader = ShortsDownloader()
                    # Scan all videos on the channel (limit=None)
                    videos = thread_downloader.check_channel(url, limit=None)
                
                for v in videos:
                    if is_direct_video:
                        v['channel_url'] = channel_url
                    else:
                        v['channel_url'] = url
                        
                    v['folder'] = folder
                    v['folder_mode'] = task.get('folder_mode', 'flat')
                    v['task_id'] = task['task_id']
                    v['limit'] = task['limit']
                    v['content_type'] = content_type
                    
                return display_name, videos

            with ThreadPoolExecutor(max_workers=min(10, total_channels or 1)) as executor:
                future_to_task = {executor.submit(fetch_channel, task): task for task in flat_tasks}
                
                for future in as_completed(future_to_task):
                    if not self.is_running:
                        break
                    task = future_to_task[future]
                    try:
                        display_name, videos = future.result()
                        self.current_channel_count += 1
                        self.progress.emit(
                            f"✔️ [{self.current_channel_count}/{total_channels}] {display_name}: "
                            f"Tìm thấy {len(videos)} video"
                        )
                        all_videos.extend(videos)
                    except Exception as e:
                        url = task['url']
            self.finished.emit(all_videos)
        except Exception as e:
            self.error.emit(str(e))

class DownloaderThread(QThread):
    progress = pyqtSignal(str)
    percent = pyqtSignal(int)
    finished = pyqtSignal(int, int)      # successful, failed
    video_downloaded = pyqtSignal(str)   # emits video URL when downloaded

    WORKERS = 10  # default, overridden by UI spinbox

    def __init__(self, tasks_specs, total_target, skip_downloaded=True, workers=10, date_filter=None, selected_language=None, allow_vertical_long=False):
        super().__init__()
        self.tasks_specs = tasks_specs
        self.total_target = total_target
        self.skip_downloaded = skip_downloaded
        self.date_filter = date_filter
        self.selected_language = selected_language
        self.downloader = ShortsDownloader()
        self.workers = workers
        self.is_running = True
        self.allow_vertical_long = allow_vertical_long

    def stop(self):
        self.is_running = False

    def run(self):
        import os
        import subprocess
        import threading
        import concurrent.futures

        lock = threading.Lock()
        slots_fulfilled = [0]
        successful = [0]
        failed = [0]
        permanently_failed = [0]
        failed_urls = []

        # Resolve paths once
        ffmpeg_location = self.downloader._find_ffmpeg()
        ytdlp_exe = self.downloader.get_ytdlp_exe()

        def download_one(video):
            url = video['url']
            channel_url = video.get('channel_url')
            tid = video.get('task_id', 0)
            label = f"[Task {tid + 1}]"
            
            base_folder = video.get('folder', os.path.join(os.path.expanduser("~"), "Documents", "AutoShorts", "downloads"))
            folder_mode = video.get('folder_mode', 'flat')
            
            # Extract @username from channel URL (shared across modes)
            channel_username = None
            if channel_url:
                import re as _re
                m = _re.search(r'(@[\w.\-]+)', channel_url)
                if m:
                    channel_username = m.group(1)
                else:
                    seg = channel_url.rstrip('/').split('/')[-1]
                    if seg.lower() not in ('shorts', 'videos', 'reels'):
                        channel_username = seg
                    else:
                        channel_username = channel_url.rstrip('/').split('/')[-2]

            # Resolve actual save folder based on folder_mode
            if folder_mode == 'by_channel' and channel_username:
                vid_folder = os.path.join(base_folder, channel_username)
            elif folder_mode == 'map_existing' and channel_username:
                # Find an existing subfolder in base_folder that matches the channel username
                # Strips leading '@' for matching since folder may be named without '@'
                uname_bare = channel_username.lstrip('@')
                matched_dir = None
                if os.path.isdir(base_folder):
                    for entry in os.listdir(base_folder):
                        entry_path = os.path.join(base_folder, entry)
                        if os.path.isdir(entry_path):
                            if entry.lstrip('@').lower() == uname_bare.lower():
                                matched_dir = entry_path
                                break
                if matched_dir:
                    vid_folder = matched_dir
                else:
                    # Fallback: use base folder
                    vid_folder = base_folder
                    self.progress.emit(f"{label} ⚠️ Không tìm thấy folder trùng '{channel_username}' trong {base_folder} — lưu vào thư mục gốc.")
            elif folder_mode == 'map_username' and channel_username:
                # Similar to map_existing: look for existing subfolder matching @username.
                # Difference from map_existing: if not found, do NOT create; skip instead (with warning).
                uname_bare = channel_username.lstrip('@')
                matched_dir = None
                if os.path.isdir(base_folder):
                    for entry in os.listdir(base_folder):
                        entry_path = os.path.join(base_folder, entry)
                        if os.path.isdir(entry_path):
                            if entry.lstrip('@').lower() == uname_bare.lower():
                                matched_dir = entry_path
                                break
                if matched_dir:
                    vid_folder = matched_dir
                else:
                    self.progress.emit(f"{label} ⏭️ Bỏ qua (không có folder nào khớp '{channel_username}' trong {base_folder}): {url}")
                    return 'skipped', video
            else:
                vid_folder = base_folder
            
            if not os.path.exists(vid_folder):
                os.makedirs(vid_folder, exist_ok=True)

            # Already downloaded — skip
            if self.skip_downloaded and channel_url and \
                    self.downloader.history.is_downloaded(channel_url, url):
                self.progress.emit(f"{label} ⏭️ Bỏ qua (đã tải): {url}")
                return 'skipped', video

            import yt_dlp
            import re
            from datetime import datetime

            content_type = video.get('content_type', 'shorts')

            # ── Phase 1: Get metadata for filter checks (resolution, date) ──────────
            # Use android_vr (no JS runtime needed) just to get basic video info.
            # This does NOT need to return language-tagged m3u8 formats.
            info_opts = self.downloader._build_ydl_opts(vid_folder, ffmpeg_location, language=None)
            info_opts['noprogress'] = True

            info = None
            date_str = "Không rõ"
            vid_date = None

            try:
                with yt_dlp.YoutubeDL(info_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as e:
                err_type = type(e).__name__
                err_msg = str(e)
                self.progress.emit(f"{label} ❌ Không lấy được thông tin [{err_type}]: {url} — {err_msg}")
                with lock: failed_urls.append(url)
                return 'failed', video

            if not info:
                self.progress.emit(f"{label} ❌ Không lấy được thông tin (yt-dlp trả về rỗng): {url}")
                with lock: failed_urls.append(url)
                return 'failed', video

            if not channel_url:
                channel_url = info.get('uploader_url') or info.get('channel_url') or info.get('uploader_id')
            if not video.get('view_count'):
                video['view_count'] = info.get('view_count', 0)

            # 2. Check Resolution Filter
            width = info.get('width')
            height = info.get('height')
            if width and height:
                is_direct = video.get('channel_url') is None or "Video Trực Tiếp" in video.get('title', "")
                
                if content_type == 'videos' and width < height:
                    if self.allow_vertical_long:
                        self.progress.emit(f"{label} ℹ️ Tải video dài định dạng dọc theo tùy chọn: {url}")
                    elif is_direct:
                        self.progress.emit(f"{label} ⚠️ Cảnh báo: Video này là định dạng dọc nhưng bạn đang ở chế độ Video ngang. Vẫn tiếp tục tải...")
                    else:
                        self.progress.emit(f"{label} ⏭️ Bỏ qua (Video dọc không phù hợp chế độ Video ngang): {url}")
                        return 'skipped', video
                elif content_type == 'shorts' and width > height:
                    if is_direct:
                        self.progress.emit(f"{label} ⚠️ Cảnh báo: Video này là định dạng ngang nhưng bạn đang ở chế độ Shorts. Vẫn tiếp tục tải...")
                    else:
                        self.progress.emit(f"{label} ⏭️ Bỏ qua (Video ngang không phù hợp chế độ Shorts): {url}")
                        return 'skipped', video

            # 3. Check Date Filter
            udate = info.get('upload_date')
            ts = info.get('timestamp')

            if udate and len(udate) == 8:
                try:
                    vid_date = datetime.strptime(udate, '%Y%m%d').date()
                    date_str = vid_date.strftime('%d/%m/%Y')
                except: pass
            if not vid_date and ts:
                try:
                    vid_date = datetime.fromtimestamp(ts).date()
                    date_str = vid_date.strftime('%d/%m/%Y')
                except: pass

            if self.date_filter and self.date_filter.get('mode') != "Không lọc":
                is_direct = video.get('channel_url') is None or "Video Trực Tiếp" in video.get('title', "")
                df = self.date_filter.get('date_from')
                dt = self.date_filter.get('date_to')
                if vid_date and df and dt and not is_direct:
                    if vid_date < df:
                        with lock:
                            tid = video.get('task_id', 0)
                            spec = self.tasks_specs[tid]
                            spec['old_count'] = spec.get('old_count', 0) + 1
                            if spec['old_count'] >= 3 and not spec.get('early_stopped'):
                                spec['early_stopped'] = True
                                spec['queue'].clear()
                                self.progress.emit(f"{label} ⏭️ Đã chạm mốc các video cũ hơn {df.strftime('%d/%m/%Y')}. Ngừng quét sâu hơn kênh này.")
                        return 'skipped', video
                    elif vid_date > dt:
                        return 'skipped', video
                    else:
                        with lock:
                            tid = video.get('task_id', 0)
                            self.tasks_specs[tid]['old_count'] = 0

            ok = False

            # ── Phase 2a: Language-specific mode — subprocess yt-dlp + deno ──
            if self.selected_language and self.selected_language != "Mặc định":
                # Locate yt-dlp exe that supports deno (media-downloader's version is reliable)
                MD_YTDLP = r'C:/Users/Vu Nguyen Huong/AppData/Roaming/media-downloader/bin/yt-dlp.exe'
                MD_DENO  = r'C:/Users/Vu Nguyen Huong/AppData/Roaming/media-downloader/bin/deno.exe'
                ytdlp_exe = MD_YTDLP if os.path.exists(MD_YTDLP) else self.downloader.get_ytdlp_exe()
                deno_exe  = MD_DENO  if os.path.exists(MD_DENO)  else None

                # Step A: Run -F to get full format list
                list_cmd = [ytdlp_exe]
                if deno_exe:
                    list_cmd += ['--js-runtimes', f'deno:{deno_exe}']
                list_cmd += ['--no-playlist', '--quiet', '--no-warnings', '-F', url]

                try:
                    _no_window = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    fmt_result = subprocess.run(list_cmd, capture_output=True, text=True, timeout=60,
                                               creationflags=_no_window)
                    fmt_output = fmt_result.stdout + fmt_result.stderr
                except subprocess.TimeoutExpired:
                    self.progress.emit(f"{label} ⏭️ Timeout khi lấy format: {url}")
                    return 'skipped', video
                except Exception as e:
                    self.progress.emit(f"{label} ❌ Lỗi lấy format list: {e}")
                    with lock: failed_urls.append(url)
                    return 'failed', video

                # Step B: Parse -F output to find best [language] format at 1080p+
                target_lang = self.selected_language
                # Create multiple possible tags for better matching
                possible_tags = [f"[{target_lang}]"]
                if "-" in target_lang:
                    possible_tags.append(f"[{target_lang.split('-')[0]}]")
                
                chosen_format_id = None
                best_height = 0
                for line in fmt_output.splitlines():
                    if not any(tag in line for tag in possible_tags):
                        continue
                    res_match = re.search(r'(\d+)x(\d+)', line)
                    if not res_match:
                        continue
                    w, h = int(res_match.group(1)), int(res_match.group(2))
                    if w >= 1080 and w > best_height:
                        best_height = w
                        parts = line.split()
                        chosen_format_id = parts[0] if parts else None

                if not chosen_format_id:
                    self.progress.emit(f"{label} ⏭️ Không có bản {target_lang} 1080p, bỏ qua: {url}")
                    return 'skipped', video

                self.progress.emit(
                    f"{label} 🌐 Tìm thấy {target_lang} ID={chosen_format_id} ({best_height}p) | {date_str} → tải..."
                )

                # Step C: Download with the exact format_id via subprocess
                outtmpl = os.path.join(vid_folder, '%(title)s [%(id)s].%(ext)s')
                dl_cmd = [ytdlp_exe]
                if deno_exe:
                    dl_cmd += ['--js-runtimes', f'deno:{deno_exe}']
                dl_cmd += [
                    '--no-playlist',
                    '-f', chosen_format_id,
                    '--merge-output-format', 'mp4',
                    '-o', outtmpl,
                    '--no-warnings',
                    '--retries', '10',
                    url
                ]
                if ffmpeg_location:
                    dl_cmd += ['--ffmpeg-location', ffmpeg_location]

                try:
                    _no_window = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    dl_result = subprocess.run(dl_cmd, capture_output=True, text=True, timeout=300,
                                              creationflags=_no_window)
                    # Don't set ok strictly here, we will check the file later
                except subprocess.TimeoutExpired:
                    self.progress.emit(f"{label} ❌ Timeout khi tải: {url}")
                except Exception as e:
                    self.progress.emit(f"{label} ❌ Lỗi tải: {e}")

            # ── Phase 2b: Normal mode — Python yt-dlp ────────────────────────────────
            else:
                self.progress.emit(f"{label} ⬇️ Bắt đầu tải: {url} | Ngày đăng: {date_str}")
                dl_opts = self.downloader._build_ydl_opts(vid_folder, ffmpeg_location, language=None)
                dl_opts['noprogress'] = True
                try:
                    with yt_dlp.YoutubeDL(dl_opts) as dl_ydl:
                        dl_ydl.download([url])
                except Exception as e:
                    err_type = type(e).__name__
                    self.progress.emit(f"{label} ⚠️ Lỗi khi tải [{err_type}]: {str(e)}")

                
            if not self.is_running:
                return 'skipped', video
            
            # --- Robust Success Check: Check for the actual file ---
            # Give it a small moment for filesystem to settle after merge
            import time
            time.sleep(1.5)
            
            vid_id = video.get('id', '')
            actual_new_file = 'unknown'
            ok = False 
            
            if vid_id:
                # Try multiple matching strategies
                for f in os.listdir(vid_folder):
                    f_path = os.path.join(vid_folder, f)
                    if not os.path.isfile(f_path): continue
                    
                    # Strategy 1: Standard yt-dlp "[ID]."
                    if f"[{vid_id}]." in f and f.endswith('.mp4'):
                        if os.path.getsize(f_path) > 0:
                            actual_new_file = f
                            ok = True
                            break
                    
                    # Strategy 2: Filename is just the ID (common in some configs)
                    if f.startswith(vid_id) and f.endswith('.mp4'):
                        if os.path.getsize(f_path) > 0:
                            actual_new_file = f
                            ok = True
                            break

            if not ok:
                # Last ditch effort: find the newest video file in the folder created in last 2 mins
                try:
                    now = time.time()
                    newest_file = None
                    newest_time = 0
                    for f in os.listdir(vid_folder):
                        if f.endswith('.mp4'):
                            f_path = os.path.join(vid_folder, f)
                            mtime = os.path.getmtime(f_path)
                            if (now - mtime) < 150: # created in last 2.5 mins
                                if mtime > newest_time:
                                    newest_time = mtime
                                    newest_file = f
                    if newest_file:
                        actual_new_file = newest_file
                        ok = True
                except: pass

            if not ok:
                self.progress.emit(f"{label} ❌ Lỗi: Không tìm thấy file sau khi tải: {url}")

            # --- Rename file to clean title ---
            if ok and actual_new_file != 'unknown':
                try:
                    import re
                    # Remove the ID part completely
                    base_name, ext = os.path.splitext(actual_new_file)
                    new_base_name = base_name.replace(f" [{vid_id}]", "").replace(f"[{vid_id}]", "")
                    
                    # Remove emojis and weird symbols, leave letters (including unicode/vietnamese), numbers, spaces, and basic punctuation
                    new_base_name = re.sub(r'[^\w\s\-.,!?()\[\]]', '', new_base_name)
                    # Clean up multiple spaces
                    new_base_name = re.sub(r'\s+', ' ', new_base_name).strip()
                    
                    if not new_base_name:
                        new_base_name = vid_id  # Fallback just in case title consisted only of emojis
                        
                    new_name = new_base_name + ext
                    final_name = new_name
                    counter = 1
                    
                    old_path = os.path.join(vid_folder, actual_new_file)
                    new_path = os.path.join(vid_folder, final_name)
                    
                    # Prevent overwrites if the file already exists
                    while os.path.exists(new_path) and new_path != old_path:
                        final_name = f"{new_base_name} ({counter}){ext}"
                        new_path = os.path.join(vid_folder, final_name)
                        counter += 1
                        
                    if old_path != new_path:
                        os.rename(old_path, new_path)
                        actual_new_file = final_name
                except Exception as e:
                    pass # Safely ignore renaming errors and continue with old name

            # --- Strict Cleanup: Delete any non-mp4 files containing vid_id ---
            if vid_id:
                try:
                    for f in os.listdir(vid_folder):
                        f_path = os.path.join(vid_folder, f)
                        if os.path.isfile(f_path) and vid_id in f and not f.endswith('.mp4'):
                            try:
                                os.remove(f_path)
                            except: pass
                except: pass

            if ok:
                if channel_url:
                    with lock:
                        self.downloader.history.add_to_history(
                            channel_url, url, video.get('view_count', 0)
                        )
                else:
                    # Fallback: use video URL as channel key if resolution failed
                    with lock:
                        self.downloader.history.add_to_history(
                            "direct_links", url, video.get('view_count', 0)
                        )

                self.progress.emit(f"{label} ✅ Xong: {actual_new_file}")
                self.video_downloaded.emit(url)
                return 'success', video
            else:
                self.progress.emit(f"{label} ❌ Lỗi tải: {url}")
                with lock:
                    failed_urls.append(url)
                return 'failed', video

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as executor:
                active_futures = set()

                # Initial submissions for all slots
                for tid, spec in self.tasks_specs.items():
                    for _ in range(spec['target']):
                        if spec['queue']:
                            v = spec['queue'].pop(0)
                            spec['active'] += 1
                            future = executor.submit(download_one, v)
                            active_futures.add(future)

                # Wait dynamically for jobs to complete and replenish if failed
                while active_futures:
                    if not self.is_running:
                        for f in active_futures:
                            f.cancel()
                        break
                    done, active_futures = concurrent.futures.wait(
                        active_futures, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    
                    for future in done:
                        try:
                            status, video = future.result()
                            tid = video.get('task_id', 0)
                            spec = self.tasks_specs[tid]
                            
                            with lock:
                                spec['active'] -= 1
                                if status == 'success':
                                    spec['success'] += 1
                                    successful[0] += 1
                                    slots_fulfilled[0] += 1
                                elif status == 'failed':
                                    spec['failed'] += 1
                                    failed[0] += 1
                                    
                                    # Fallback: pop another video if we haven't reached the target
                                    if spec['success'] + spec['active'] < spec['target']:
                                        if spec['queue']:
                                            v_new = spec['queue'].pop(0)
                                            spec['active'] += 1
                                            new_future = executor.submit(download_one, v_new)
                                            active_futures.add(new_future)
                                            self.progress.emit(f"🔄 Vớt lỗi: Bơm thêm video dự phòng cho Tác vụ {tid+1}...")
                                        else:
                                            permanently_failed[0] += 1
                                            slots_fulfilled[0] += 1
                                            # Identify the channel name for better logging
                                            ch_url = video.get('channel_url', '')
                                            ch_name = ''
                                            if ch_url:
                                                import re as _cre
                                                _m = _cre.search(r'(@[\w.\-]+)', ch_url)
                                                ch_name = f" (kênh: {_m.group(1)})" if _m else f" (kênh: {ch_url.rstrip('/').split('/')[-1]})"
                                            self.progress.emit(f"⚠️ Cạn dự phòng: Tác vụ {tid+1}{ch_name} không còn video nào để tải bù!")
                                            
                                elif status == 'skipped':
                                    # Just pop another video, don't count as failed
                                    if spec['success'] + spec['active'] < spec['target']:
                                        if spec['queue']:
                                            v_new = spec['queue'].pop(0)
                                            spec['active'] += 1
                                            new_future = executor.submit(download_one, v_new)
                                            active_futures.add(new_future)
                                        else:
                                            permanently_failed[0] += 1
                                            slots_fulfilled[0] += 1
                                            ch_url2 = video.get('channel_url', '')
                                            ch_name2 = ''
                                            if ch_url2:
                                                import re as _cre2
                                                _m2 = _cre2.search(r'(@[\w.\-]+)', ch_url2)
                                                ch_name2 = f" (kênh: {_m2.group(1)})" if _m2 else f" (kênh: {ch_url2.rstrip('/').split('/')[-1]})"
                                            self.progress.emit(f"⚠️ Cạn dự phòng: Tác vụ {tid+1}{ch_name2} không còn video phù hợp!")
                                            
                                pct = int(slots_fulfilled[0] * 100 / self.total_target) if self.total_target > 0 else 100
                                self.percent.emit(pct)

                        except Exception as e:
                            self.progress.emit(f"❌ Worker lỗi: {e}")

            summary = f"✅ Hoàn tất! Đã tải {successful[0]} video"
            if permanently_failed[0] > 0:
                summary += f", thiếu {permanently_failed[0]} video do kênh đã bị vắt kiệt"
            self.progress.emit(summary)
            if self.total_target > 0:
                self.percent.emit(100)
                
            if failed_urls:
                try:
                    import sys
                    from datetime import datetime
                    if getattr(sys, 'frozen', False):
                        base_dir = os.path.dirname(sys.executable)
                    else:
                        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    
                    errorlink_dir = os.path.join(base_dir, "errorlink")
                    os.makedirs(errorlink_dir, exist_ok=True)
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    error_file = os.path.join(errorlink_dir, f"error_{timestamp}.txt")
                    
                    with open(error_file, "w", encoding="utf-8") as f:
                        for furl in set(failed_urls):
                            f.write(furl + "\n")
                            
                    self.progress.emit(f"📝 Đã xuất {len(set(failed_urls))} link lỗi ra: errorlink/error_{timestamp}.txt")
                except Exception as e:
                    self.progress.emit(f"❌ Lỗi ghi file errorlink: {e}")
                
        except Exception as e:
            self.progress.emit(f"Lỗi nghiêm trọng: {str(e)}")

        self.finished.emit(successful[0], failed[0])

class DownloadTaskWidget(QGroupBox):
    def __init__(self, remove_callback=None, task_index=1):
        super().__init__(f"📥 Task {task_index}")
        self.remove_callback = remove_callback
        
        # Style the groupbox
        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #ccc;
                border-radius: 6px;
                margin-top: 15px;
                background-color: rgba(0,0,0,0.02);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #333;
                font-weight: bold;
            }
        """)
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 15, 10, 10)
        
        # Content Type Selector Row
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Loại nội dung:"))
        self.content_type_cmb = QComboBox()
        self.content_type_cmb.addItems(["Shorts", "Videos (dài)"])
        self.content_type_cmb.setFixedWidth(140)
        self.content_type_cmb.setToolTip("Chọn loại video muốn tải: Shorts (video ngắn) hoặc Videos (video dài)")
        self.content_type_cmb.currentIndexChanged.connect(self._on_content_type_changed)
        type_row.addWidget(self.content_type_cmb)
        type_row.addStretch()
        layout.addLayout(type_row)
        
        # URL Input
        self.url_input = QTextEdit()
        self._update_placeholder()
        self.url_input.setMaximumHeight(80)
        self.url_input.setMinimumHeight(60)
        layout.addWidget(self.url_input)
        
        # Settings Row
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Download Top:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 999999)
        self.limit_spin.setSpecialValueText("0 (Tất cả)")
        self.limit_spin.setValue(20)
        self.limit_spin.setSuffix(" videos")
        row1.addWidget(self.limit_spin)

        row1.addWidget(QLabel("Save to:"))
        self.folder_input = QLineEdit()
        self.folder_input.setMinimumWidth(10) # Allow shrinking
        self.folder_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        import os
        self.folder_input.setText(os.path.join(os.path.expanduser("~"), "Documents", "AutoShorts", "downloads"))
        row1.addWidget(self.folder_input, 1) # Give it stretch
        
        self.browse_btn = QPushButton("📁 Browse")
        self.browse_btn.setFixedWidth(100)
        self.browse_btn.clicked.connect(self.browse_folder)
        row1.addWidget(self.browse_btn)

        if self.remove_callback:
            self.remove_btn = SmallDangerButton()
            self.remove_btn.setFixedSize(60, 28)
            self.remove_btn.setText("❌ Xóa")
            self.remove_btn.clicked.connect(lambda: self.remove_callback(self))
            row1.addWidget(self.remove_btn)

        layout.addLayout(row1)

        # Folder Mode Row
        row_folder_mode = QHBoxLayout()
        row_folder_mode.addWidget(QLabel("📂 Chế độ lưu:"))
        self.folder_mode_group = QButtonGroup(self)
        self.folder_mode_flat = QRadioButton("Thư mục chỉ định")
        self.folder_mode_flat.setChecked(True)
        self.folder_mode_flat.setToolTip("Tất cả video tải vào cùng 1 thư mục đã chọn.")
        self.folder_mode_by_channel = QRadioButton("Subfolder theo @username")
        self.folder_mode_by_channel.setToolTip("Tự động tạo subfolder riêng cho mỗi kênh, đặt tên theo @username.")
        self.folder_mode_map_existing = QRadioButton("Ánh xạ folder có sẵn")
        self.folder_mode_map_existing.setToolTip("Ánh xạ vào folder đã có sẵn — chọn folder từ danh sách con trong thư mục gốc.")
        self.folder_mode_map_username = QRadioButton("Folder có sẵn = @username")
        self.folder_mode_map_username.setToolTip("Tìm folder con trong thư mục gốc có tên trùng với @username của kênh, lưu vào đó.")
        self.folder_mode_group.addButton(self.folder_mode_flat, 0)
        self.folder_mode_group.addButton(self.folder_mode_by_channel, 1)
        self.folder_mode_group.addButton(self.folder_mode_map_existing, 2)
        self.folder_mode_group.addButton(self.folder_mode_map_username, 3)
        row_folder_mode.addWidget(self.folder_mode_flat)
        row_folder_mode.addSpacing(10)
        row_folder_mode.addWidget(self.folder_mode_by_channel)
        row_folder_mode.addSpacing(10)
        row_folder_mode.addWidget(self.folder_mode_map_existing)
        row_folder_mode.addSpacing(10)
        row_folder_mode.addWidget(self.folder_mode_map_username)
        row_folder_mode.addStretch()
        layout.addLayout(row_folder_mode)

    def _on_content_type_changed(self):
        self._update_placeholder()
    
    def _update_placeholder(self):
        if self.content_type_cmb.currentText() == "Shorts":
            self.url_input.setPlaceholderText(
                "Nhập URL kênh YouTube (mỗi dòng một kênh)\nVí dụ:\nhttps://www.youtube.com/@vunguyenhuong/shorts"
            )
        else:
            self.url_input.setPlaceholderText(
                "Nhập URL kênh YouTube (mỗi dòng một kênh)\nVí dụ:\nhttps://www.youtube.com/@vunguyenhuong/videos"
            )
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if folder:
            self.folder_input.setText(folder)
            
    def get_data(self):
        text = self.url_input.toPlainText()
        urls = [line.strip() for line in text.split('\n') if line.strip()]
        content_type = "shorts" if self.content_type_cmb.currentText() == "Shorts" else "videos"
        if self.folder_mode_by_channel.isChecked():
            folder_mode = "by_channel"
        elif self.folder_mode_map_existing.isChecked():
            folder_mode = "map_existing"
        elif self.folder_mode_map_username.isChecked():
            folder_mode = "map_username"
        else:
            folder_mode = "flat"
        return {
            'urls': urls,
            'limit': self.limit_spin.value(),
            'folder': self.folder_input.text(),
            'folder_mode': folder_mode,
            'content_type': content_type
        }

    def set_data(self, data):
        if 'urls' in data:
            self.url_input.setPlainText("\n".join(data['urls']))
        if 'limit' in data:
            self.limit_spin.setValue(data['limit'])
        if 'folder' in data:
            self.folder_input.setText(data['folder'])
        if 'folder_mode' in data:
            fm = data['folder_mode']
            if fm == 'by_channel':
                self.folder_mode_by_channel.setChecked(True)
            elif fm == 'map_existing':
                self.folder_mode_map_existing.setChecked(True)
            elif fm == 'map_username':
                self.folder_mode_map_username.setChecked(True)
            else:
                self.folder_mode_flat.setChecked(True)
        if 'content_type' in data:
            if data['content_type'] == 'videos':
                self.content_type_cmb.setCurrentText("Videos (dài)")
            else:
                self.content_type_cmb.setCurrentText("Shorts")

    def set_enabled(self, enabled):
        self.url_input.setEnabled(enabled)
        self.limit_spin.setEnabled(enabled)
        self.folder_input.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)
        self.content_type_cmb.setEnabled(enabled)
        self.folder_mode_flat.setEnabled(enabled)
        self.folder_mode_by_channel.setEnabled(enabled)
        self.folder_mode_map_existing.setEnabled(enabled)
        self.folder_mode_map_username.setEnabled(enabled)
        if hasattr(self, 'remove_btn'):
            self.remove_btn.setEnabled(enabled)

class DownloaderTab(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.videos = []  # Store found video dicts
        self.download_total = 0   # How many videos queued for this download run
        self.download_done = 0    # How many have finished in this run
        self.already_downloaded = 0 # How many were skipped because already in history
        self.total_found = 0      # Total videos found in all channels
        self._already_warned_urls = set()  # Guard: don't show history warning twice for same URL
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # -- Tasks Area (Scrollable) --
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(150)
        self.tasks_container = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setContentsMargins(5, 5, 5, 5)
        self.tasks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.tasks_container)
        layout.addWidget(self.scroll_area)

        # List to keep track of tasks widgets
        self.task_widgets = []
        self.task_counter = 0
        
        tasks_action_container = QWidget()
        tasks_action_layout = QHBoxLayout(tasks_action_container)
        tasks_action_layout.setContentsMargins(0, 16, 0, 0)
        tasks_action_layout.setSpacing(10)
        
        self.add_task_btn = SuccessButton("➕ Thêm Tác Vụ")
        self.add_task_btn.setFixedHeight(50)
        self.add_task_btn.clicked.connect(self.add_task_widget)
        tasks_action_layout.addWidget(self.add_task_btn, 1)

        self.save_cfg_btn = GhostButton("💾 Lưu cấu hình")
        self.save_cfg_btn.setFixedHeight(50)
        self.save_cfg_btn.clicked.connect(self.save_config)
        tasks_action_layout.addWidget(self.save_cfg_btn, 1)

        self.load_cfg_btn = GhostButton("📂 Tải cấu hình")
        self.load_cfg_btn.setFixedHeight(50)
        self.load_cfg_btn.clicked.connect(self.load_config)
        tasks_action_layout.addWidget(self.load_cfg_btn, 1)

        layout.addWidget(tasks_action_container)


        # Add initial task
        self.add_task_widget(is_first=True)

        # -- Info Area --
        self.info_label = QLabel("Sẵn sàng.")
        self.info_label.setWordWrap(True)
        self.info_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.info_label.setStyleSheet("color: #64748B; font-weight: 600; background: transparent; border: none;")
        layout.addWidget(self.info_label)

        # -- Global Download Settings --
        dl_group = QGroupBox("Global Settings")
        dl_layout = QVBoxLayout()
        
        # Second row: Skip downloaded, German-only, threads count, Clear History
        row2 = QHBoxLayout()
        self.skip_downloaded_cb = QCheckBox("Bỏ qua video đã tải")
        self.skip_downloaded_cb.setChecked(True)
        self.skip_downloaded_cb.setToolTip("Bỏ qua các video đã được tải từ trước")
        row2.addWidget(self.skip_downloaded_cb)

        row2.addSpacing(20)
        self.allow_vertical_long_cb = QCheckBox("Tải video dài khung hình dọc")
        self.allow_vertical_long_cb.setChecked(False)
        self.allow_vertical_long_cb.setToolTip("Cho phép tải video dài nhưng có khung hình dọc (width < height)")
        row2.addWidget(self.allow_vertical_long_cb)

        row2.addSpacing(20)
        row2.addWidget(QLabel("Ngôn ngữ lồng tiếng:"))
        self.language_cmb = QComboBox()
        self.language_cmb.addItems([
            "Mặc định",
            "en-US",
            "de-DE",
            "fr-FR",
            "ja-JP",
            "ko-KR",
            "vi-VN"
        ])
        self.language_cmb.setFixedWidth(120)
        self.language_cmb.setToolTip("Chọn ngôn ngữ lồng tiếng muốn tải (Mặc định là âm thanh gốc)")
        row2.addWidget(self.language_cmb)

        row2.addSpacing(20)
        row2.addWidget(QLabel("Số luồng tải:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 20)
        self.workers_spin.setValue(10)
        self.workers_spin.setFixedWidth(80)
        self.workers_spin.setToolTip("Số luồng tải song song (1-20). Cao quá có thể bị YouTube chặn.")
        row2.addWidget(self.workers_spin)

        row2.addStretch()
        
        clear_history_btn = QPushButton("🗑️ Clear History")
        clear_history_btn.setFixedWidth(140)
        clear_history_btn.clicked.connect(self.clear_download_history)
        clear_history_btn.setToolTip("Xóa toàn bộ lịch sử tải (có xác nhận)")
        row2.addWidget(clear_history_btn)
        
        dl_layout.addLayout(row2)

        # Date filter row
        row_date = QHBoxLayout()
        row_date.addWidget(QLabel("📅 Lọc ngày đăng:"))
        
        self.date_filter_cmb = QComboBox()
        self.date_filter_cmb.addItems([
            "Không lọc",
            "Tuần này",
            "Tháng này",
            "Năm này",
            "Từ ngày...",
            "Khoảng ngày...",
            "... ngày/tháng/năm trở lại",
        ])
        self.date_filter_cmb.setFixedWidth(210)
        self.date_filter_cmb.setToolTip("Chỉ tải video được đăng trong khoảng thời gian chọn")
        self.date_filter_cmb.currentIndexChanged.connect(self._on_date_filter_changed)
        row_date.addWidget(self.date_filter_cmb)

        # Date pickers (shown/hidden based on filter type)
        self.date_from_label = QLabel("Từ:")
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        self.date_from.setDisplayFormat("dd/MM/yyyy")
        self.date_from.setFixedWidth(150)

        self.date_to_label = QLabel("Đến:")
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        self.date_to.setDisplayFormat("dd/MM/yyyy")
        self.date_to.setFixedWidth(150)

        row_date.addWidget(self.date_from_label)
        row_date.addWidget(self.date_from)
        row_date.addWidget(self.date_to_label)
        row_date.addWidget(self.date_to)

        # Relative range: N days/months/years ago
        self.relative_spin = QSpinBox()
        self.relative_spin.setRange(1, 9999)
        self.relative_spin.setValue(30)
        self.relative_spin.setFixedWidth(100)
        self.relative_unit_cmb = QComboBox()
        self.relative_unit_cmb.addItems(["ngày", "tháng", "năm"])
        self.relative_unit_cmb.setFixedWidth(100)
        self.relative_ago_label = QLabel("trở lại")
        row_date.addWidget(self.relative_spin)
        row_date.addWidget(self.relative_unit_cmb)
        row_date.addWidget(self.relative_ago_label)

        row_date.addStretch()
        dl_layout.addLayout(row_date)

        # Hide date pickers initially
        self._on_date_filter_changed()

        dl_group.setLayout(dl_layout)
        layout.addWidget(dl_group)

        # Action Buttons -- ▶ Tải Ngay | ⏹ Stop | 🔍 Quét
        dl_actions_container = QWidget()
        dl_actions_layout = QHBoxLayout(dl_actions_container)
        dl_actions_layout.setContentsMargins(0, 0, 0, 0)
        dl_actions_layout.setSpacing(10)

        self.dl_btn = PrimaryButton("▶ Tải Ngay")
        self.dl_btn.setFixedHeight(50)
        self.dl_btn.clicked.connect(self.start_download)
        dl_actions_layout.addWidget(self.dl_btn, 2)

        self.stop_btn = DangerButton("⏹ Stop")
        self.stop_btn.setFixedHeight(50)
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)
        dl_actions_layout.addWidget(self.stop_btn, 1)

        self.scan_btn = SecondaryButton("🔍 Quét Dữ Liệu")
        self.scan_btn.setFixedHeight(50)
        self.scan_btn.clicked.connect(self.start_fetch)
        dl_actions_layout.addWidget(self.scan_btn, 1)

        layout.addWidget(dl_actions_container)
        
        # -- Progress --
        self.progress_bar = StyledProgressBar()
        layout.addWidget(self.progress_bar)
        
        # Spacer
        layout.addStretch()
    
    def _on_date_filter_changed(self):
        """Show/hide date picker widgets based on selected filter"""
        mode = self.date_filter_cmb.currentText() if hasattr(self, 'date_filter_cmb') else "Không lọc"
        show_from = mode in ("Từ ngày...", "Khoảng ngày...")
        show_to = mode == "Khoảng ngày..."
        show_relative = mode == "... ngày/tháng/năm trở lại"
        self.date_from_label.setVisible(show_from)
        self.date_from.setVisible(show_from)
        self.date_to_label.setVisible(show_to)
        self.date_to.setVisible(show_to)
        self.relative_spin.setVisible(show_relative)
        self.relative_unit_cmb.setVisible(show_relative)
        self.relative_ago_label.setVisible(show_relative)

    def _apply_date_filter(self, videos):
        """
        Filter videos list based on the selected date filter mode.
        Returns filtered list (all videos if mode is 'Không lọc').
        upload_date format from yt-dlp: 'YYYYMMDD' string or None.
        """
        from datetime import datetime, date, timedelta
        mode = self.date_filter_cmb.currentText()
        if mode == "Không lọc":
            return videos

        today = date.today()

        if mode == "Tuần này":
            # Monday of current week
            week_start = today - timedelta(days=today.weekday())
            date_from = week_start
            date_to = today
        elif mode == "Tháng này":
            date_from = today.replace(day=1)
            date_to = today
        elif mode == "Năm này":
            date_from = today.replace(month=1, day=1)
            date_to = today
        elif mode == "Từ ngày...":
            qd = self.date_from.date()
            date_from = date(qd.year(), qd.month(), qd.day())
            date_to = today
        elif mode == "Khoảng ngày...":
            qf = self.date_from.date()
            qt = self.date_to.date()
            date_from = date(qf.year(), qf.month(), qf.day())
            date_to = date(qt.year(), qt.month(), qt.day())
        elif mode == "... ngày/tháng/năm trở lại":
            n = self.relative_spin.value()
            unit = self.relative_unit_cmb.currentText()
            if unit == "ngày":
                date_from = today - timedelta(days=n)
            elif unit == "tháng":
                # approximate: subtract months manually
                month = today.month - n
                year = today.year + month // 12
                month = month % 12
                if month <= 0:
                    month += 12
                    year -= 1
                import calendar
                day = min(today.day, calendar.monthrange(year, month)[1])
                date_from = date(year, month, day)
            elif unit == "năm":
                date_from = today.replace(year=today.year - n)
            else:
                date_from = today - timedelta(days=n)
            date_to = today
        else:
            return videos

        filtered = []
        skipped = 0
        for v in videos:
            upload_date_str = v.get('upload_date')  # 'YYYYMMDD' or None
            timestamp = v.get('timestamp')           # unix ts or None

            vid_date = None
            if upload_date_str and len(upload_date_str) == 8:
                try:
                    vid_date = datetime.strptime(upload_date_str, '%Y%m%d').date()
                except ValueError:
                    pass
            if vid_date is None and timestamp:
                try:
                    vid_date = datetime.fromtimestamp(timestamp).date()
                except Exception:
                    pass

            if vid_date is None:
                # No date info — keep it to avoid silently dropping
                filtered.append(v)
                continue

            if date_from <= vid_date <= date_to:
                filtered.append(v)
            else:
                skipped += 1

        if skipped > 0:
            self.log_message.emit(f"📅 Bộ lọc ngày: bỏ qua {skipped} video ngoài khoảng [{date_from} → {date_to}]")
        return filtered

    def add_task_widget(self, is_first=False):
        self.task_counter += 1
        widget = DownloadTaskWidget(remove_callback=self.remove_task_widget, task_index=self.task_counter)
        if is_first:
            # Hide remove button for the first one if we want, but it's simpler to just let them have none.
            if hasattr(widget, 'remove_btn'):
                widget.remove_btn.hide()
        else:
            # Since first task doesn't get a remove button initially, if this is not first, make sure first task can be removed? 
            # Well, it's easier to just pass the callback to all. We only hide it for 'is_first' if it's the very first time.
            pass

        # Connect URL text changes to history check for direct video links
        widget.url_input.textChanged.connect(lambda: self._on_url_text_changed(widget))

        self.tasks_layout.addWidget(widget)
        self.task_widgets.append(widget)
        
        # Ensure at least 1 widget. If we have > 1, show their remove buttons
        if len(self.task_widgets) > 1:
            for w in self.task_widgets:
                if hasattr(w, 'remove_btn'):
                    w.remove_btn.show()

    def remove_task_widget(self, widget):
        if len(self.task_widgets) > 1:
            self.tasks_layout.removeWidget(widget)
            self.task_widgets.remove(widget)
            widget.deleteLater()
            
            # If only 1 left, hide its remove button
            if len(self.task_widgets) == 1:
                if hasattr(self.task_widgets[0], 'remove_btn'):
                    self.task_widgets[0].remove_btn.hide()
    
    def _on_url_text_changed(self, widget):
        """Triggered when url_input text changes. Checks each line that looks like a direct video link."""
        import re
        video_patterns = [
            r'watch\?v=', r'/shorts/', r'youtu\.be/',
            r'facebook\.com/.+/videos/', r'tiktok\.com/.+/video/'
        ]
        text = widget.url_input.toPlainText()
        current_lines = {l.strip() for l in text.splitlines() if l.strip()}

        # Prune warned URLs that are no longer in the text (user deleted them)
        self._already_warned_urls &= current_lines

        for line in current_lines:
            if line in self._already_warned_urls:
                continue  # already prompted for this URL this session
            if any(re.search(p, line) for p in video_patterns):
                self._check_direct_video_in_history(line)

    def _get_all_typed_urls(self):
        """Collect all non-empty URLs from all task widgets."""
        urls = []
        for w in self.task_widgets:
            text = w.url_input.toPlainText()
            for line in text.splitlines():
                line = line.strip()
                if line:
                    urls.append(line)
        return urls

    def _normalize_channel_key(self, url):
        """Return the normalized channel key the same way DownloadHistory does."""
        from core.downloader import ShortsDownloader
        d = ShortsDownloader()
        return d.history._normalize_url(url)

    def _check_direct_video_in_history(self, url):
        """
        Called when user types / pastes a URL that looks like a direct video link.
        If it already exists in history, ask whether to re-download.
        Returns True if the user wants to proceed (re-download), False otherwise.
        """
        import re
        video_patterns = [
            r'watch\?v=', r'/shorts/', r'youtu\.be/',
            r'facebook\.com/.+/videos/', r'tiktok\.com/.+/video/'
        ]
        if not any(re.search(p, url) for p in video_patterns):
            return  # not a direct video link — nothing to do

        from core.downloader import ShortsDownloader
        downloader = ShortsDownloader()
        # Check under all known channel keys for this video
        video_key = downloader.history._normalize_url(url)
        found_in = None
        for channel_key, channel_data in downloader.history.history.items():
            vids = channel_data.get('videos', []) if isinstance(channel_data, dict) else channel_data
            if video_key in vids:
                found_in = channel_key
                break

        if found_in is None:
            self._already_warned_urls.add(url)  # Mark as checked (not in history)
            return  # not in history — nothing to warn about

        self._already_warned_urls.add(url)  # Mark so we don't prompt again

        reply = QMessageBox.question(
            self,
            "Video đã được tải trước đó",
            f"Link này đã có trong lịch sử tải:\n{url}\n\nBạn có muốn tải lại không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.No:
            # Remove the URL from the text area that triggered the check
            for w in self.task_widgets:
                text = w.url_input.toPlainText()
                lines = [l for l in text.splitlines() if l.strip() != url]
                if len(lines) != len(text.splitlines()):
                    w.url_input.blockSignals(True)
                    w.url_input.setPlainText('\n'.join(lines))
                    w.url_input.blockSignals(False)
                    break
        # If Yes — leave the URL in place; the skip_downloaded checkbox will handle it,
        # or the user can uncheck it manually.

    def clear_download_history(self):
        """Clear download history — selectively by channel if URLs are typed, else clear all."""
        from core.downloader import ShortsDownloader
        import re

        typed_urls = self._get_all_typed_urls()

        # Detect which of the typed URLs look like channel links (not direct videos)
        video_patterns = [
            r'watch\?v=', r'/shorts/', r'youtu\.be/',
            r'facebook\.com/.+/videos/', r'tiktok\.com/.+/video/'
        ]
        channel_urls = []
        for u in typed_urls:
            if not any(re.search(p, u) for p in video_patterns):
                # It's a channel link — strip /shorts or /videos suffix for matching
                channel_urls.append(u)

        downloader = ShortsDownloader()

        if channel_urls:
            # ── Selective delete: only remove history entries for typed channels ──
            keys_to_delete = [downloader.history._normalize_url(u) for u in channel_urls]
            existing_keys = list(downloader.history.history.keys())
            matched = [k for k in existing_keys if k in keys_to_delete]

            if not matched:
                QMessageBox.information(
                    self, "Không tìm thấy",
                    "Không tìm thấy lịch sử nào cho các kênh bạn đã nhập.\n"
                    "Kiểm tra lại URL hoặc để trống để xóa toàn bộ."
                )
                return

            channel_list_str = '\n'.join(f'• {k}' for k in matched)
            reply = QMessageBox.question(
                self,
                "Xóa lịch sử theo kênh",
                f"Sẽ xóa lịch sử tải của {len(matched)} kênh sau:\n\n{channel_list_str}\n\n"
                f"Thao tác này không thể hoàn tác. Tiếp tục?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                for k in matched:
                    downloader.history.history.pop(k, None)
                downloader.history.save_history()
                QMessageBox.information(self, "Thành công", f"Đã xóa lịch sử của {len(matched)} kênh!")
                self.log_message.emit(f"🗑️ Đã xóa lịch sử {len(matched)} kênh: {', '.join(matched)}")
        else:
            # ── Delete all ──
            reply = QMessageBox.question(
                self,
                "Xóa toàn bộ lịch sử",
                "Không có kênh nào được nhập.\n\nBạn có chắc muốn xóa TOÀN BỘ lịch sử tải?\n\nThao tác này không thể hoàn tác.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                downloader.history.clear_history()
                QMessageBox.information(self, "Thành công", "Đã xóa toàn bộ lịch sử tải!")
                self.log_message.emit("🗑️ Đã xóa toàn bộ lịch sử tải")

    def save_config(self):
        import json
        import os
        settings_dir = os.path.join(os.getcwd(), "settings")
        os.makedirs(settings_dir, exist_ok=True)
        file_path = os.path.join(settings_dir, "downloader_config.json")
        
        tasks_data = [w.get_data() for w in self.task_widgets]
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "Thành công", f"Đã tự động lưu cấu hình vào:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu cấu hình:\n{e}")

    def load_config(self):
        import json
        import os
        file_path = os.path.join(os.getcwd(), "settings", "downloader_config.json")
        
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Chưa có cấu hình", "Bạn chưa lưu cấu hình Downloader nào (chưa có file downloader_config.json trong thư mục settings).")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)
            
            if not isinstance(tasks_data, list):
                raise ValueError("Định dạng file không hợp lệ (cần danh sách tác vụ).")
            
            # Xóa các tác vụ cũ
            while len(self.task_widgets) > 0:
                widget = self.task_widgets.pop()
                self.tasks_layout.removeWidget(widget)
                widget.deleteLater()
            self.task_counter = 0

            # Thêm tác vụ mới
            for i, data in enumerate(tasks_data):
                self.add_task_widget(is_first=(i==0))
                self.task_widgets[-1].set_data(data)
            
            # Trường hợp file json trống
            if not self.task_widgets:
                self.add_task_widget(is_first=True)

            QMessageBox.information(self, "Thành công", "Đã tải cấu hình Downloader tự động!")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể tải cấu hình:\n{e}")

    # ------------------------------------------------------------------ #
    #  Start Fetch: check channels first
    # ------------------------------------------------------------------ #
    def start_fetch(self):
        import time
        self.start_time = time.time()
        
        tasks = []
        for i, w in enumerate(self.task_widgets):
            data = w.get_data()
            if data['urls']:
                data['task_id'] = i
                tasks.append(data)
                
        if not tasks:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập ít nhất một URL kênh ở các tác vụ.")
            return

        self.set_interaction(False)
        self.dl_btn.setEnabled(False)
        if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.info_label.setText("🔍 Đang kiểm tra các kênh...")
        
        total_urls = sum(len(t['urls']) for t in tasks)
        self.log_message.emit(f"Bắt đầu kiểm tra {total_urls} kênh từ {len(tasks)} tác vụ...")

        self._last_fetched_urls = []
        for t in tasks:
            self._last_fetched_urls.extend(t['urls'])

        # Step 1: fetch channel video lists
        self.fetcher = FetcherThread(tasks)
        self.fetcher.progress.connect(self._on_fetch_progress)
        self.fetcher.finished.connect(self._on_fetch_done)
        self.fetcher.error.connect(self._on_fetch_error)
        self.fetcher.start()

    def _on_fetch_progress(self, msg):
        self.info_label.setText(msg)
        self.log_message.emit(msg)

    def _on_fetch_done(self, videos):
        if hasattr(self, 'fetcher') and not self.fetcher.is_running:
            self.info_label.setText("Đã dừng kiểm tra kênh.")
            self.set_interaction(True)
            self.dl_btn.setEnabled(True)
            if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        self.videos = videos
        total_found = len(videos)

        if not videos:
            self.info_label.setText("Không tìm thấy video nào.")
            self.log_message.emit("Không tìm thấy video nào để tải.")
            self.set_interaction(True)
            self.dl_btn.setEnabled(True)
            if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        # Cập nhật thông tin số lượng
        skip_downloaded = self.skip_downloaded_cb.isChecked()
        from core.downloader import ShortsDownloader
        downloader = ShortsDownloader()
        already_downloaded = 0
        if skip_downloaded:
            for video in videos:
                if downloader.history.is_downloaded(video.get('channel_url'), video['url']):
                    already_downloaded += 1

        pending_count = total_found - already_downloaded
        summary_text = (
            f"✅ Tổng quét {total_found} video | "
            f"{already_downloaded} đã tải trước | "
            f"{pending_count} video sẵn sàng tải"
        )
        self.log_message.emit(summary_text)
        self.info_label.setText(summary_text)

        # Nếu được gọi từ "Tải Ngay" khi chưa có dữ liệu → tự động chuyển sang tải
        if getattr(self, '_pending_download', False):
            self._pending_download = False
            self.set_interaction(True)
            self.dl_btn.setEnabled(True)
            if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.start_download()
            return
        
        self.set_interaction(True)
        self.dl_btn.setEnabled(True)
        if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    # ------------------------------------------------------------------ #
    #  Start Download: download from scanned videos
    # ------------------------------------------------------------------ #
    def start_download(self):
        current_urls = []
        for w in self.task_widgets:
            current_urls.extend(w.get_data()['urls'])
            
        needs_fetch = False
        if not hasattr(self, 'videos') or not self.videos:
            needs_fetch = True
        elif getattr(self, '_last_fetched_urls', None) != current_urls:
            needs_fetch = True
            
        if needs_fetch:
            # Chưa có dữ liệu hoặc danh sách thay đổi — tự động quét rồi tải
            self._pending_download = True
            self.info_label.setText("🔍 Cập nhật danh sách kênh, đang quét lại...")
            self.start_fetch()
            return

        self.set_interaction(False)
        self.dl_btn.setEnabled(False)
        if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        
        # Cập nhật limit VÀ folder từ UI cho từng video vì user có thể đã thay đổi
        task_limits = {}
        task_folders = {}
        for i, w in enumerate(self.task_widgets):
            data = w.get_data()
            task_limits[i] = data['limit']
            task_folders[i] = data['folder']  # Luôn lấy folder mới nhất từ UI

        available_videos = []
        skip_downloaded = self.skip_downloaded_cb.isChecked()
        from core.downloader import ShortsDownloader
        downloader = ShortsDownloader()
        
        for video in self.videos:
            tid = video.get('task_id', 0)
            if tid in task_limits:
                video['limit'] = task_limits[tid]
            if tid in task_folders:
                video['folder'] = task_folders[tid]  # Ghi đè folder bằng giá trị hiện tại từ UI
                
            if skip_downloaded:
                if not downloader.history.is_downloaded(video.get('channel_url'), video['url']):
                    available_videos.append(video)
            else:
                available_videos.append(video)

        total_found = len(self.videos)
        pending_count = len(available_videos)
        already_downloaded = total_found - pending_count

        # Get date filter parameters
        from datetime import date, timedelta
        mode = self.date_filter_cmb.currentText() if hasattr(self, 'date_filter_cmb') else "Không lọc"
        date_from = None
        date_to = None
        
        today = date.today()
        if mode == "Tuần này":
            date_from = today - timedelta(days=today.weekday())
            date_to = today
        elif mode == "Tháng này":
            date_from = today.replace(day=1)
            date_to = today
        elif mode == "Năm này":
            date_from = today.replace(month=1, day=1)
            date_to = today
        elif mode == "Từ ngày...":
            qd = self.date_from.date()
            date_from = date(qd.year(), qd.month(), qd.day())
            date_to = today
        elif mode == "Khoảng ngày...":
            qf = self.date_from.date()
            qt = self.date_to.date()
            date_from = date(qf.year(), qf.month(), qf.day())
            date_to = date(qt.year(), qt.month(), qt.day())
        elif mode == "... ngày/tháng/năm trở lại":
            n = self.relative_spin.value()
            unit = self.relative_unit_cmb.currentText()
            if unit == "ngày":
                date_from = today - timedelta(days=n)
            elif unit == "tháng":
                month = today.month - n
                year = today.year + month // 12
                month = month % 12
                if month <= 0:
                    month += 12
                    year -= 1
                import calendar
                day = min(today.day, calendar.monthrange(year, month)[1])
                date_from = date(year, month, day)
            elif unit == "năm":
                date_from = today.replace(year=today.year - n)
            else:
                date_from = today - timedelta(days=n)
            date_to = today

        date_filter_params = {
            'mode': mode,
            'date_from': date_from,
            'date_to': date_to
        }

        # Do NOT apply date filter here because we don't have accurate dates yet.
        # It will be applied dynamically inside DownloaderThread for each video.

        if not available_videos:
            QMessageBox.information(self, "Thông báo", "Tất cả video đều đã được tải hoặc không có video nào phù hợp với bộ lọc!")
            self.set_interaction(True)
            self.dl_btn.setEnabled(True)
            if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        # Group by task_id → then by channel_url to apply limit PER CHANNEL
        videos_by_task = {}
        for video in available_videos:
            tid = video.get('task_id', 0)
            if tid not in videos_by_task:
                videos_by_task[tid] = []
            videos_by_task[tid].append(video)
            
        tasks_specs = {}
        total_target = 0
        import random
        for tid, vids in videos_by_task.items():
            task_limit = vids[0].get('limit', 50)

            # ── Apply limit PER CHANNEL ──────────────────────────────────────
            # Group videos inside this task by channel_url
            by_channel = {}
            for v in vids:
                curl = v.get('channel_url', '__direct__')
                if curl not in by_channel:
                    by_channel[curl] = []
                by_channel[curl].append(v)

            channel_count = len(by_channel)

            # Chia thành: "initial" (đúng số chỉ tiêu) + "reserve" (phần còn lại làm dự phòng bù lỗi)
            initial_vids = []
            reserve_vids = []
            for curl, ch_vids in by_channel.items():
                if task_limit <= 0:
                    initial_vids.extend(ch_vids)  # 0 = tất cả, không cần reserve
                else:
                    initial_vids.extend(ch_vids[:task_limit])
                    reserve_vids.extend(ch_vids[task_limit:])  # phần dự phòng

            total_in_queue = len(initial_vids) + len(reserve_vids)
            if channel_count > 1:
                self.log_message.emit(
                    f"📋 [Task {tid+1}] Limit {task_limit if task_limit > 0 else '∞'} video/kênh × "
                    f"{channel_count} kênh = tối đa {len(initial_vids)} video "
                    f"(+{len(reserve_vids)} dự phòng bù lỗi)"
                )
            elif reserve_vids:
                self.log_message.emit(
                    f"📋 [Task {tid+1}] Chỉ tiêu {len(initial_vids)} video "
                    f"(+{len(reserve_vids)} dự phòng bù lỗi)"
                )

            # Ghép initial + reserve vào 1 queue: phần đầu = chỉ tiêu, phần sau = dự phòng
            # Chỉ trộn ngẫu nhiên nếu không dùng bộ lọc ngày
            if date_filter_params['mode'] == "Không lọc":
                random.shuffle(initial_vids)
                random.shuffle(reserve_vids)
            else:
                # Interleave initial videos by channel để download song song công bằng
                by_channel2 = {}
                for v in initial_vids:
                    curl = v.get('channel_url', 'unknown')
                    if curl not in by_channel2:
                        by_channel2[curl] = []
                    by_channel2[curl].append(v)
                
                if by_channel2:
                    interleaved = []
                    max_len = max(len(lst) for lst in by_channel2.values())
                    channel_lists = list(by_channel2.values())
                    for i in range(max_len):
                        for lst in channel_lists:
                            if i < len(lst):
                                interleaved.append(lst[i])
                    initial_vids = interleaved

            vids = initial_vids + reserve_vids  # queue = chỉ tiêu + dự phòng
            target = len(initial_vids)  # target = đúng số chỉ tiêu (không tính reserve)
            tasks_specs[tid] = {
                'limit': task_limit,
                'target': target,
                'queue': vids,
                'success': 0,
                'failed': 0,
                'active': 0,
                'early_stopped': False
            }
            total_target += target

        self.download_total = total_target
        self.download_done = 0
        self.already_downloaded = already_downloaded
        self.total_found = total_found
        self.log_message.emit(f"▶ Bắt đầu đưa {self.download_total} video vào máy tải...")
        self.info_label.setText(
            f"⬇️ Đang tải 0/{self.download_total} chỉ tiêu "
            f"(tổng quét: {self.total_found} | kho dự phòng: {len(available_videos) - self.download_total})"
        )

        workers = self.workers_spin.value()
        selected_language = self.language_cmb.currentText()
        allow_vertical_long = self.allow_vertical_long_cb.isChecked()

        if selected_language != "Mặc định":
            self.log_message.emit(f"🌐 Bộ lọc ngôn ngữ: {selected_language} đang bật — chỉ tải video có bản lồng tiếng phù hợp.")

        # Step 2: download
        self.downloader_thread = DownloaderThread(
            tasks_specs,
            total_target, 
            skip_downloaded=False,  # Already filtered above
            workers=workers,
            date_filter=date_filter_params,
            selected_language=selected_language,
            allow_vertical_long=allow_vertical_long
        )
        self.downloader_thread.percent.connect(self.progress_bar.setValue)
        self.downloader_thread.finished.connect(self._on_download_finished)
        self.downloader_thread.progress.connect(self.log_message.emit)
        self.downloader_thread.video_downloaded.connect(self._on_video_downloaded)
        self.downloader_thread.start()

    def _on_fetch_error(self, err):
        self.info_label.setText("Lỗi khi kiểm tra kênh.")
        QMessageBox.critical(self, "Lỗi", f"Không thể kiểm tra kênh: {err}")
        self.set_interaction(True)
        self.dl_btn.setEnabled(True)
        if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def stop_download(self):
        import time
        if hasattr(self, 'start_time'):
            elapsed = time.time() - self.start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            self.log_message.emit(f"⏱️ Tổng thời gian xử lý: {mins} phút {secs} giây.")
            
        self.log_message.emit("⏹️ Đang dừng quá trình tải/quét...")
        self.info_label.setText("Đang dừng...")
        self.stop_btn.setEnabled(False)
        if hasattr(self, 'fetcher') and self.fetcher.isRunning():
            self.fetcher.stop()
        if hasattr(self, 'downloader_thread') and self.downloader_thread.isRunning():
            self.downloader_thread.stop()

    def _on_video_downloaded(self, video_url):
        """Update UI when a video is downloaded"""
        self.download_done += 1
        self.info_label.setText(
            f"⬇️ Tiến độ tải... | Thành công: {self.download_done}/{self.download_total} "
            f"(Kho dự phòng bổ sung liên tục)"
        )

    def _on_download_finished(self, successful, failed):
        self.set_interaction(True)
        self.dl_btn.setEnabled(True)
        if hasattr(self, 'scan_btn'): self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if hasattr(self, 'downloader_thread') and not self.downloader_thread.is_running:
            import time
            time_str = ""
            if hasattr(self, 'start_time'):
                elapsed = time.time() - self.start_time
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                self.log_message.emit(f"⏱️ Tổng thời gian xử lý: {mins} phút {secs} giây.")
                time_str = f"\nThời gian xử lý: {mins} phút {secs} giây."
                
            msg = f"⏹️ Đã dừng. Tải thành công {successful} video"
            self.info_label.setText(msg)
            QMessageBox.information(self, "Đã dừng", f"Quá trình tải đã bị dừng.\n\nĐã tải: {successful} video{time_str}")
            return

        msg = f"✅ Đã tải xong {successful} video"
        if failed > 0:
            msg += f", {failed} lỗi"
        self.info_label.setText(msg)

        QMessageBox.information(
            self, "Hoàn tất",
            f"Quá trình tải hoàn tất!\n\nĐã tải thành công: {successful} video" +
            (f"\nLỗi: {failed} video" if failed > 0 else "")
        )

    def set_interaction(self, enabled):
        self.add_task_btn.setEnabled(enabled)
        if hasattr(self, 'language_cmb'):
            self.language_cmb.setEnabled(enabled)
        if hasattr(self, 'allow_vertical_long_cb'):
            self.allow_vertical_long_cb.setEnabled(enabled)
        for w in self.task_widgets:
            w.set_enabled(enabled)
