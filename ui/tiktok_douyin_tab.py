"""
ui/tiktok_douyin_tab.py
-----------------------
Tab for downloading TikTok and Douyin videos.
Similar UX to DownloaderTab (YouTube) but dedicated to TikTok/Douyin.

Supports:
  - Multiple video links (one per line)
  - Channel/profile links with configurable limit (0 = all)
  - Best quality up to 1080p, no watermark (via tikwm API)
  - Concurrent downloads (configurable workers)
"""

import os
import time

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel,
    QFileDialog, QGroupBox, QLineEdit, QSpinBox, QFrame,
    QScrollArea, QCheckBox, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

from core.tiktok_douyin import TiktokDouyinDownloader
from ui.components import (
    PrimaryButton, SecondaryButton, DangerButton, StyledProgressBar
)


# ─────────────────────────────────────────────────────────────────────────────
# Worker Thread
# ─────────────────────────────────────────────────────────────────────────────

class SocialDownloadThread(QThread):
    progress    = pyqtSignal(str)
    percent     = pyqtSignal(int)
    finished    = pyqtSignal(int, int)   # success, failed

    def __init__(self, tasks, output_folder, workers=3):
        """
        tasks: list of dicts
            {'type': 'video',   'url': str}
            {'type': 'channel', 'url': str, 'limit': int}
        """
        super().__init__()
        self.tasks         = tasks
        self.output_folder = output_folder
        self.workers       = workers
        self.is_running    = True
        self._dl           = TiktokDouyinDownloader()

    def stop(self):
        self.is_running = False

    # ──────────────────────────────────────────────────────────────────────────
    def run(self):
        import concurrent.futures
        import threading

        os.makedirs(self.output_folder, exist_ok=True)

        # ─── Phase 1: Resolve all tasks → flat list of video URLs ─────────────
        # Channel scans call tikwm API sequentially (handled by global lock inside).
        all_videos = []

        for task in self.tasks:
            if not self.is_running:
                break

            url   = task["url"].strip()
            ttype = task["type"]

            if ttype == "channel":
                limit = task.get("limit", 0)
                self.progress.emit(
                    f"🔍 Quét kênh: {url}"
                    + (f" (tối đa {limit})" if limit else " (toàn bộ)")
                )
                is_douyin = "douyin.com" in url.lower()
                if is_douyin:
                    videos = self._dl.fetch_channel_ytdlp(
                        url, limit=limit,
                        progress_callback=lambda m: self.progress.emit(m),
                    )
                else:
                    videos = self._dl.fetch_channel_videos(
                        url, limit=limit,
                        progress_callback=lambda m: self.progress.emit(m),
                    )
                all_videos.extend(videos)
            else:
                all_videos.append({"url": url, "title": url, "id": ""})

        if not all_videos:
            self.progress.emit("⚠️ Không có video nào để tải.")
            self.finished.emit(0, 0)
            return

        total = len(all_videos)
        self.progress.emit(f"📋 Tổng {total} video sẽ được tải → {self.output_folder}")

        # ─── Phase 2: Download ─────────────────────────────────────────────────
        # IMPORTANT: download_video() internally uses a global lock for the
        # tikwm API call (so only 1 API request fires at a time even with
        # multiple workers), but the actual HTTP byte-streaming runs in parallel.
        # This gives us:
        #   • No tikwm rate-limit errors (serial API calls)
        #   • Still fast (parallel streaming after each URL is resolved)

        lock    = threading.Lock()
        success = [0]
        failed  = [0]
        done    = [0]

        def download_one(video):
            if not self.is_running:
                return

            url     = video["url"]
            display = (video.get("title") or url)[:60]

            with lock:
                idx = done[0] + 1
            self.progress.emit(f"⬇️ [{idx}/{total}] {display}")

            ok, fname = self._dl.download_video(
                url, self.output_folder,
                progress_callback=lambda m: self.progress.emit(m),
            )

            with lock:
                done[0] += 1
                if ok:
                    success[0] += 1
                    self.progress.emit(f"✅ Xong: {fname}")
                else:
                    failed[0] += 1
                    self.progress.emit(f"❌ Thất bại: {display}")
                self.percent.emit(int(done[0] * 100 / total))

        # Cap workers at total videos; never exceed 5 to avoid hammering tikwm
        max_w = min(self.workers, total, 5)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_w) as executor:
            futs = [executor.submit(download_one, v) for v in all_videos]
            concurrent.futures.wait(futs)

        self.progress.emit(
            f"🎉 Hoàn tất! ✅ {success[0]} thành công  ❌ {failed[0]} thất bại"
        )
        self.finished.emit(success[0], failed[0])


# ─────────────────────────────────────────────────────────────────────────────
# Main Tab Widget
# ─────────────────────────────────────────────────────────────────────────────

class TiktokDouyinTab(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._worker = None
        self._build_ui()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 16)
        lay.setSpacing(14)

        # ── Header ────────────────────────────────────────────────────────
        hdr = QLabel("🎵  TikTok / Douyin Downloader")
        hdr.setFont(QFont("Inter", 17, QFont.Weight.Bold))
        hdr.setStyleSheet("color: #1E293B;")
        lay.addWidget(hdr)

        sub = QLabel(
            "Dán link video hoặc link kênh vào ô bên dưới · Mỗi link 1 dòng · "
            "Không watermark · Chất lượng tốt nhất (tối đa 1080p)"
        )
        sub.setStyleSheet("color: #64748B; font-size: 12px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # ── URL Input ────────────────────────────────────────────────────
        url_grp = self._make_group("📋  Danh sách Link")
        url_inner = QVBoxLayout()
        url_inner.setContentsMargins(12, 6, 12, 12)
        url_inner.setSpacing(6)

        self._url_edit = QTextEdit()
        self._url_edit.setPlaceholderText(
            "Dán link vào đây, mỗi link 1 dòng:\n"
            "\n"
            "• Link video đơn:\n"
            "  https://vt.tiktok.com/ZSxdY6GN2/\n"
            "  https://www.tiktok.com/@user/video/123456789\n"
            "  https://v.douyin.com/abcde/\n"
            "\n"
            "• Link kênh (tải nhiều video):\n"
            "  https://www.tiktok.com/@username\n"
            "  https://www.douyin.com/user/MS4wLjABAAAAxxx"
        )
        self._url_edit.setMinimumHeight(200)
        self._url_edit.setFont(QFont("Consolas", 11))
        url_inner.addWidget(self._url_edit)

        url_grp.setLayout(url_inner)
        lay.addWidget(url_grp)

        # ── Settings ─────────────────────────────────────────────────────
        cfg_grp = self._make_group("⚙️  Cài đặt")
        cfg_lay = QVBoxLayout()
        cfg_lay.setContentsMargins(12, 6, 12, 12)
        cfg_lay.setSpacing(10)

        # Save folder
        folder_row = QHBoxLayout()
        folder_lbl = QLabel("Thư mục lưu:")
        folder_lbl.setFixedWidth(110)
        folder_row.addWidget(folder_lbl)

        self._folder_edit = QLineEdit()
        default = os.path.join(
            os.path.expanduser("~"), "Documents", "AutoShorts", "TikTokDownloads"
        )
        self._folder_edit.setText(default)
        self._folder_edit.setMinimumHeight(32)
        folder_row.addWidget(self._folder_edit, 1)

        browse_btn = SecondaryButton("📁 Browse")
        browse_btn.setFixedWidth(90)
        browse_btn.setMinimumHeight(32)
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse_btn)
        cfg_lay.addLayout(folder_row)

        # Channel limit + workers
        row2 = QHBoxLayout()

        limit_lbl = QLabel("Limit (kênh):")
        limit_lbl.setFixedWidth(110)
        row2.addWidget(limit_lbl)

        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(0, 999999)
        self._limit_spin.setValue(20)
        self._limit_spin.setSpecialValueText("0 = Tải tất cả")
        self._limit_spin.setSuffix(" video")
        self._limit_spin.setFixedWidth(150)
        self._limit_spin.setMinimumHeight(32)
        self._limit_spin.setToolTip(
            "Số video tối đa sẽ tải từ MỖI kênh.\n"
            "0 = tải toàn bộ.\nKhông ảnh hưởng đến link video đơn."
        )
        row2.addWidget(self._limit_spin)

        row2.addSpacing(24)

        workers_lbl = QLabel("Tải song song:")
        row2.addWidget(workers_lbl)
        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(1, 10)
        self._workers_spin.setValue(3)
        self._workers_spin.setSuffix(" luồng")
        self._workers_spin.setFixedWidth(110)
        self._workers_spin.setMinimumHeight(32)
        row2.addWidget(self._workers_spin)
        row2.addStretch()

        cfg_lay.addLayout(row2)
        cfg_grp.setLayout(cfg_lay)
        lay.addWidget(cfg_grp)

        # ── Progress bar ─────────────────────────────────────────────────
        self._progress_bar = StyledProgressBar()
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        lay.addWidget(self._progress_bar)

        # ── Action buttons ────────────────────────────────────────────────
        act_row = QHBoxLayout()
        act_row.addStretch()

        self._clear_btn = SecondaryButton("🗑 Xóa URL")
        self._clear_btn.setMinimumWidth(110)
        self._clear_btn.setMinimumHeight(38)
        self._clear_btn.clicked.connect(lambda: self._url_edit.clear())
        act_row.addWidget(self._clear_btn)

        act_row.addSpacing(8)

        self._start_btn = PrimaryButton("🚀  Bắt đầu Tải")
        self._start_btn.setMinimumWidth(160)
        self._start_btn.setMinimumHeight(38)
        self._start_btn.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        self._start_btn.clicked.connect(self._toggle)
        act_row.addWidget(self._start_btn)

        lay.addLayout(act_row)
        lay.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    def _make_group(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        g.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)
        return g

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Chọn thư mục lưu video", self._folder_edit.text()
        )
        if folder:
            self._folder_edit.setText(os.path.normpath(folder))

    def _toggle(self):
        # Stop if running
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._start_btn.setText("Đang dừng...")
            self._start_btn.setEnabled(False)
            return

        # ── Parse URLs ────────────────────────────────────────────────────
        raw = self._url_edit.toPlainText().strip()
        if not raw:
            self.log_message.emit("❌ Vui lòng nhập ít nhất 1 link!")
            return

        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        if not lines:
            return

        folder = self._folder_edit.text().strip()
        if not folder:
            self.log_message.emit("❌ Vui lòng chọn thư mục lưu!")
            return

        limit   = self._limit_spin.value()
        workers = self._workers_spin.value()

        dl = TiktokDouyinDownloader()
        tasks = []
        for line in lines:
            if dl.is_channel_url(line):
                tasks.append({"type": "channel", "url": line, "limit": limit})
                self.log_message.emit(f"📡 Kênh: {line} (limit={limit or 'tất cả'})")
            else:
                tasks.append({"type": "video", "url": line})

        n_vid = sum(1 for t in tasks if t["type"] == "video")
        n_ch  = sum(1 for t in tasks if t["type"] == "channel")
        parts = []
        if n_vid:
            parts.append(f"{n_vid} video đơn")
        if n_ch:
            parts.append(f"{n_ch} kênh")
        self.log_message.emit(f"🚀 Bắt đầu tải: {', '.join(parts)} → {folder}")

        # ── Start worker ──────────────────────────────────────────────────
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._start_btn.setText("⏹  Dừng")
        self._start_btn.setStyleSheet(
            "QPushButton { background: #EF4444; color: white; border-radius: 8px; font-size:12px; font-weight:bold; }"
            "QPushButton:hover { background: #DC2626; }"
        )

        self._worker = SocialDownloadThread(tasks, folder, workers=workers)
        self._worker.progress.connect(self.log_message.emit)
        self._worker.percent.connect(self._progress_bar.setValue)
        self._worker.finished.connect(self._on_done)
        self._worker.start()

    def _on_done(self, success, failed):
        self._start_btn.setText("🚀  Bắt đầu Tải")
        self._start_btn.setStyleSheet("")
        self._start_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._worker = None
