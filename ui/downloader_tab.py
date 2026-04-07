import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QLabel, QProgressBar, QSpinBox, QFileDialog, QGroupBox, QMessageBox, QCheckBox, QTextEdit, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from core.downloader import ShortsDownloader

class FetcherThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks
        self.downloader = ShortsDownloader()
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            all_videos = []
            flat_tasks = []
            for t in self.tasks:
                for url in t['urls']:
                    flat_tasks.append({'url': url.strip(), 'limit': t['limit'], 'folder': t['folder'], 'task_id': t.get('task_id', 0)})
            
            total_channels = len(flat_tasks)
            self.current_channel_count = 0
            
            def fetch_channel(task):
                url = task['url']
                limit = task['limit']
                folder = task['folder']
                
                # Extract channel name for cleaner display
                display_name = url.split('/')[-1] if '/' in url else url
                if display_name.lower() == 'shorts' or display_name.lower() == 'reels':
                    display_name = url.split('/')[-2] if len(url.split('/')) > 1 else url
                    
                self.progress.emit(f"⏳ Đang kiểm tra {display_name}...")
                
                # Each thread needs its own downloader instance to prevent potential issues
                thread_downloader = ShortsDownloader()
                # Scan all videos on the channel (limit=None)
                videos = thread_downloader.check_channel(url, limit=None)
                
                for v in videos:
                    v['channel_url'] = url
                    v['folder'] = folder
                    v['task_id'] = task['task_id']
                    v['limit'] = task['limit']
                    
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
                        self.progress.emit(f"❌ Lỗi khi kiểm tra {url}: {e}")
                
            self.finished.emit(all_videos)
        except Exception as e:
            self.error.emit(str(e))

class DownloaderThread(QThread):
    progress = pyqtSignal(str)
    percent = pyqtSignal(int)
    finished = pyqtSignal(int, int)      # successful, failed
    video_downloaded = pyqtSignal(str)   # emits video URL when downloaded

    WORKERS = 10  # default, overridden by UI spinbox

    def __init__(self, tasks_specs, total_target, skip_downloaded=True, workers=10):
        super().__init__()
        self.tasks_specs = tasks_specs
        self.total_target = total_target
        self.skip_downloaded = skip_downloaded
        self.downloader = ShortsDownloader()
        self.workers = workers
        self.is_running = True

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

        # Resolve paths once
        ffmpeg_location = self.downloader._find_ffmpeg()
        ytdlp_exe = self.downloader.get_ytdlp_exe()

        def download_one(video):
            url = video['url']
            channel_url = video.get('channel_url')
            tid = video.get('task_id', 0)
            label = f"[Task {tid + 1}]"
            
            vid_folder = video.get('folder', os.path.join(os.path.expanduser("~"), "Documents", "AutoShorts", "downloads"))
            if not os.path.exists(vid_folder):
                os.makedirs(vid_folder, exist_ok=True)

            # Already downloaded — skip
            if self.skip_downloaded and channel_url and \
                    self.downloader.history.is_downloaded(channel_url, url):
                self.progress.emit(f"{label} ⏭️ Bỏ qua (đã tải): {url}")
                return True, video

            self.progress.emit(f"{label} ⬇️ Bắt đầu tải: {url}")

            cmd = [
                ytdlp_exe, url,
                '-o', os.path.join(vid_folder, '%(title)s [%(id)s].%(ext)s'),
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
                '--merge-output-format', 'mp4',
                '--no-playlist', '--no-warnings',
                '--extractor-retries', '3',
                '--retries', '10',
                '--fragment-retries', '10',
            ]
            
            if ffmpeg_location:
                cmd.extend(['--ffmpeg-location', ffmpeg_location])

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            for line in proc.stdout:
                if not self.is_running:
                    proc.kill()
                    break
                stripped = line.strip()
                if stripped:
                    self.progress.emit(f"{label} {stripped}")
            proc.wait()

            ok = proc.returncode == 0
            if not self.is_running:
                return False, video
            
            vid_id = video.get('id', '')
            actual_new_file = 'unknown'
            if ok and vid_id:
                for f in os.listdir(vid_folder):
                    if f"[{vid_id}]." in f and os.path.isfile(os.path.join(vid_folder, f)):
                        if os.path.getsize(os.path.join(vid_folder, f)) > 0:
                            actual_new_file = f
                            break
                if actual_new_file == 'unknown':
                    ok = False

            if ok and channel_url:
                with lock:
                    self.downloader.history.add_to_history(
                        channel_url, url, video.get('view_count', 0)
                    )

            if ok:
                self.progress.emit(f"{label} ✅ Xong: {actual_new_file}")
                self.video_downloaded.emit(url)
            else:
                self.progress.emit(f"{label} ❌ Lỗi tải: {url} (exit={proc.returncode})")
                
            return ok, video

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
                            ok, video = future.result()
                            tid = video.get('task_id', 0)
                            spec = self.tasks_specs[tid]
                            
                            with lock:
                                spec['active'] -= 1
                                if ok:
                                    spec['success'] += 1
                                    successful[0] += 1
                                    slots_fulfilled[0] += 1
                                else:
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
                                            self.progress.emit(f"⚠️ Cạn dự phòng: Tác vụ {tid+1} không còn video nào để tải bù!")
                                            
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
        
        # URL Input
        self.url_input = QTextEdit()
        self.url_input.setPlaceholderText(
            "Nhập URL kênh YouTube (mỗi dòng một kênh)\nVí dụ:\nhttps://www.youtube.com/@ChannelA/shorts"
        )
        self.url_input.setMaximumHeight(80)
        self.url_input.setMinimumHeight(60)
        layout.addWidget(self.url_input)
        
        # Settings Row
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Download Top:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 999)
        self.limit_spin.setValue(50)
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
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.clicked.connect(self.browse_folder)
        row1.addWidget(self.browse_btn)

        row1.addSpacing(10)

        if self.remove_callback:
            self.remove_btn = QPushButton("❌ Xóa")
            self.remove_btn.setFixedWidth(60)
            self.remove_btn.clicked.connect(lambda: self.remove_callback(self))
            self.remove_btn.setStyleSheet("color: white; background-color: #d9534f; border-radius: 4px; font-weight: bold;")
            row1.addWidget(self.remove_btn)
            
        layout.addLayout(row1)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if folder:
            self.folder_input.setText(folder)
            
    def get_data(self):
        text = self.url_input.toPlainText()
        urls = [line.strip() for line in text.split('\n') if line.strip()]
        return {
            'urls': urls,
            'limit': self.limit_spin.value(),
            'folder': self.folder_input.text()
        }

    def set_data(self, data):
        if 'urls' in data:
            self.url_input.setPlainText("\n".join(data['urls']))
        if 'limit' in data:
            self.limit_spin.setValue(data['limit'])
        if 'folder' in data:
            self.folder_input.setText(data['folder'])

    def set_enabled(self, enabled):
        self.url_input.setEnabled(enabled)
        self.limit_spin.setEnabled(enabled)
        self.folder_input.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)
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
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # -- Tasks Area (Scrollable) --
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(500)
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
        tasks_action_layout.setContentsMargins(0, 0, 0, 0)
        tasks_action_layout.setSpacing(10)
        
        self.add_task_btn = QPushButton("➕ Thêm Tác Vụ")
        self.add_task_btn.setFixedHeight(40)
        self.add_task_btn.setStyleSheet("font-size: 13px; font-weight: bold; background-color: #5cb85c; color: white;")
        self.add_task_btn.clicked.connect(self.add_task_widget)
        tasks_action_layout.addWidget(self.add_task_btn, 1)

        self.save_cfg_btn = QPushButton("💾 Lưu cấu hình")
        self.save_cfg_btn.setFixedHeight(40)
        self.save_cfg_btn.setStyleSheet("font-size: 13px; font-weight: bold; background-color: #f0ad4e; color: white;")
        self.save_cfg_btn.clicked.connect(self.save_config)
        tasks_action_layout.addWidget(self.save_cfg_btn, 1)

        self.load_cfg_btn = QPushButton("📂 Tải cấu hình")
        self.load_cfg_btn.setFixedHeight(40)
        self.load_cfg_btn.setStyleSheet("font-size: 13px; font-weight: bold; background-color: #5bc0de; color: white;")
        self.load_cfg_btn.clicked.connect(self.load_config)
        tasks_action_layout.addWidget(self.load_cfg_btn, 1)

        layout.addWidget(tasks_action_container)

        # Add initial task
        self.add_task_widget(is_first=True)

        # -- Info Area --
        self.info_label = QLabel("Sẵn sàng.")
        self.info_label.setWordWrap(True)
        self.info_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.info_label.setStyleSheet("color: #888; font-weight: bold;")
        layout.addWidget(self.info_label)

        # -- Global Download Settings --
        dl_group = QGroupBox("Global Settings")
        dl_layout = QVBoxLayout()
        
        # Second row: Skip downloaded, threads count, Clear History
        row2 = QHBoxLayout()
        self.skip_downloaded_cb = QCheckBox("Bỏ qua video đã tải")
        self.skip_downloaded_cb.setChecked(True)
        self.skip_downloaded_cb.setToolTip("Bỏ qua các video đã được tải từ trước")
        row2.addWidget(self.skip_downloaded_cb)

        row2.addSpacing(20)
        row2.addWidget(QLabel("Số luồng tải:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 20)
        self.workers_spin.setValue(10)
        self.workers_spin.setFixedWidth(55)
        self.workers_spin.setToolTip("Số luồng tải song song (1-20). Cao quá có thể bị YouTube chặn.")
        row2.addWidget(self.workers_spin)

        row2.addStretch()
        
        clear_history_btn = QPushButton("🗑️ Clear History")
        clear_history_btn.setFixedWidth(120)
        clear_history_btn.clicked.connect(self.clear_download_history)
        clear_history_btn.setToolTip("Xóa toàn bộ lịch sử tải (có xác nhận)")
        row2.addWidget(clear_history_btn)
        
        dl_layout.addLayout(row2)
        dl_group.setLayout(dl_layout)
        layout.addWidget(dl_group)

        # Action Buttons --
        dl_actions_container = QWidget()
        dl_actions_layout = QHBoxLayout(dl_actions_container)
        dl_actions_layout.setContentsMargins(0, 0, 0, 0)
        dl_actions_layout.setSpacing(10)
        
        self.dl_btn = QPushButton("▶ Start Download")
        self.dl_btn.setFixedHeight(40)
        self.dl_btn.setStyleSheet("font-size: 14px; font-weight: bold; background-color: #0275d8; color: white;")
        self.dl_btn.clicked.connect(self.start_download)
        dl_actions_layout.addWidget(self.dl_btn, 1)
        
        self.stop_btn = QPushButton("⏹ Stop Download")
        self.stop_btn.setFixedHeight(40)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px; 
                font-weight: bold;
                background-color: #dc3545; 
                color: white;
            }
            QPushButton:disabled {
                background-color: #6c757d;
                color: #adb5bd;
            }
        """)
        self.stop_btn.clicked.connect(self.stop_download)
        self.stop_btn.setEnabled(False)
        dl_actions_layout.addWidget(self.stop_btn, 1)
        
        layout.addWidget(dl_actions_container)
        
        # -- Progress --
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        
        # Spacer
        layout.addStretch()
    
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
    
    def clear_download_history(self):
        """Clear download history with confirmation"""
        reply = QMessageBox.question(
            self,
            "Xóa lịch sử tải",
            "Bạn có chắc muốn xóa toàn bộ lịch sử tải?\n\nThao tác này không thể hoàn tác.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            from core.downloader import ShortsDownloader
            downloader = ShortsDownloader()
            downloader.history.clear_history()
            QMessageBox.information(self, "Thành công", "Đã xóa lịch sử tải!")
            self.log_message.emit("Đã xóa lịch sử tải")

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
    #  Start Download: check channels first, then download                 #
    # ------------------------------------------------------------------ #
    def start_download(self):
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
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.info_label.setText("🔍 Đang kiểm tra các kênh...")
        
        total_urls = sum(len(t['urls']) for t in tasks)
        self.log_message.emit(f"Bắt đầu kiểm tra {total_urls} kênh từ {len(tasks)} tác vụ...")

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
            self.stop_btn.setEnabled(False)
            return

        self.videos = videos
        total_found = len(videos)

        if not videos:
            self.info_label.setText("Không tìm thấy video nào.")
            self.log_message.emit("Không tìm thấy video nào để tải.")
            self.set_interaction(True)
            self.dl_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        # Filter out already-downloaded if needed
        import random
        skip_downloaded = self.skip_downloaded_cb.isChecked()
        available_videos = []
        if skip_downloaded:
            from core.downloader import ShortsDownloader
            downloader = ShortsDownloader()
            for video in videos:
                if not downloader.history.is_downloaded(video.get('channel_url'), video['url']):
                    available_videos.append(video)
        else:
            available_videos = videos.copy()

        pending_count = len(available_videos)
        already_downloaded = total_found - pending_count
        summary_text = (
            f"✅ Tổng cộng {total_found} video | "
            f"{already_downloaded} đã tải trước | "
            f"{pending_count} video chờ tải"
        )
        self.log_message.emit(summary_text)
        self.info_label.setText(summary_text)

        if not available_videos:
            QMessageBox.information(self, "Thông báo", "Tất cả video đều đã được tải!")
            self.set_interaction(True)
            self.dl_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            return

        # Group by task_id to apply limits per task correctly
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
            random.shuffle(vids) # Tự trộn tất cả video có sẵn của Tác vụ này vào 1 Biển dự phòng ngẫu nhiên
            target = min(len(vids), task_limit)
            tasks_specs[tid] = {
                'limit': task_limit,
                'target': target,
                'queue': vids,   
                'success': 0,
                'failed': 0,
                'active': 0
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

        # Step 2: download
        self.downloader_thread = DownloaderThread(
            tasks_specs,
            total_target, 
            skip_downloaded=False,  # Already filtered above
            workers=workers
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
        self.stop_btn.setEnabled(False)

    def stop_download(self):
        self.log_message.emit("⏹️ Đang dừng quá trình tải...")
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
        self.stop_btn.setEnabled(False)

        if hasattr(self, 'downloader_thread') and not self.downloader_thread.is_running:
            msg = f"⏹️ Đã dừng. Tải thành công {successful} video"
            self.info_label.setText(msg)
            QMessageBox.information(self, "Đã dừng", f"Quá trình tải đã bị dừng.\n\nĐã tải: {successful} video")
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
        for w in self.task_widgets:
            w.set_enabled(enabled)
