"""
ui/tiktok_checker_tab.py
------------------------
Tab kiểm tra thông tin kênh TikTok.
- Nhập 1 hoặc nhiều username/URL (mỗi dòng 1 cái)
- Bấm Check → fill kết quả vào bảng
- Có thể copy/export kết quả
"""

import csv
import io
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLabel,
    QGroupBox, QFrame, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSizePolicy, QFileDialog,
    QApplication, QProgressBar, QSpinBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QBrush

from ui.components import PrimaryButton, SecondaryButton, DangerButton
from core.tiktok_checker import fetch_channel_info


# ─────────────────────────────────────────────────────────────────────────────
# Worker Thread
# ─────────────────────────────────────────────────────────────────────────────

class CheckerThread(QThread):
    """Chạy fetch_channel_info song song cho danh sách usernames."""
    log        = pyqtSignal(str)
    row_ready  = pyqtSignal(dict)          # mỗi kênh xong → gửi kết quả
    progress   = pyqtSignal(int, int)      # (done, total)
    finished_  = pyqtSignal()

    def __init__(self, usernames: list[str], workers: int = 5):
        super().__init__()
        self._usernames = usernames
        self._workers   = max(1, min(workers, 10))
        self._stop      = False

    def stop(self):
        self._stop = True

    def run(self):
        import concurrent.futures
        import threading

        total   = len(self._usernames)
        done    = [0]
        lock    = threading.Lock()

        def check_one(u: str):
            if self._stop:
                return
            result = fetch_channel_info(u, progress_callback=self.log.emit)
            self.row_ready.emit(result)
            with lock:
                done[0] += 1
                self.progress.emit(done[0], total)

        max_w = min(self._workers, total)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_w) as ex:
            futs = [ex.submit(check_one, u) for u in self._usernames]
            concurrent.futures.wait(futs)

        self.finished_.emit()


# ─────────────────────────────────────────────────────────────────────────────
# Tab Widget
# ─────────────────────────────────────────────────────────────────────────────

# Columns: (header label, result key, alignment)
COLUMNS = [
    ("STT",         None,            Qt.AlignmentFlag.AlignCenter),
    ("Username",    "username",      Qt.AlignmentFlag.AlignLeft),
    ("Nickname",    "nickname",      Qt.AlignmentFlag.AlignLeft),
    ("Followers",   "followers_fmt", Qt.AlignmentFlag.AlignCenter),
    ("Following",   "following_fmt", Qt.AlignmentFlag.AlignCenter),
    ("Likes",       "likes_fmt",     Qt.AlignmentFlag.AlignCenter),
    ("Videos",      "video_count_fmt", Qt.AlignmentFlag.AlignCenter),
    ("Verified",    "verified",      Qt.AlignmentFlag.AlignCenter),
    ("Bio",         "bio",           Qt.AlignmentFlag.AlignLeft),
    ("Trạng thái",  "status",        Qt.AlignmentFlag.AlignCenter),
]


class TiktokCheckerTab(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._worker    = None
        self._results   = []          # list of dicts
        self._row_count = 0
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
        hdr = QLabel("🔎  TikTok Channel Checker")
        hdr.setFont(QFont("Inter", 17, QFont.Weight.Bold))
        hdr.setStyleSheet("color: #1E293B;")
        lay.addWidget(hdr)

        sub = QLabel(
            "Nhập username hoặc link kênh TikTok · Mỗi dòng 1 kênh · "
            "Xem followers, likes, số video, ..."
        )
        sub.setStyleSheet("color: #64748B; font-size: 12px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # ── Input group ───────────────────────────────────────────────────
        inp_grp = self._make_group("📋  Danh sách kênh")
        inp_lay = QVBoxLayout()
        inp_lay.setContentsMargins(12, 6, 12, 12)
        inp_lay.setSpacing(6)

        self._input_edit = QTextEdit()
        self._input_edit.setPlaceholderText(
            "Nhập username hoặc link kênh, mỗi dòng 1 cái:\n\n"
            "  username_abc\n"
            "  @another_user\n"
            "  https://www.tiktok.com/@someone"
        )
        self._input_edit.setMinimumHeight(160)
        self._input_edit.setFont(QFont("Consolas", 11))
        inp_lay.addWidget(self._input_edit)

        # Workers row
        workers_row = QHBoxLayout()
        workers_lbl = QLabel("⚡ Luồng song song:")
        workers_lbl.setStyleSheet("color: #475569; font-size: 12px;")
        workers_row.addWidget(workers_lbl)

        self._workers_spin = QSpinBox()
        self._workers_spin.setRange(1, 10)
        self._workers_spin.setValue(5)
        self._workers_spin.setSuffix(" luồng")
        self._workers_spin.setFixedWidth(110)
        self._workers_spin.setMinimumHeight(28)
        self._workers_spin.setToolTip(
            "Số kênh check cùng lúc.\n"
            "Cao hơn = nhanh hơn nhưng có thể bị rate-limit.\n"
            "Khuyến nghị: 3-5"
        )
        workers_row.addWidget(self._workers_spin)
        workers_row.addStretch()
        inp_lay.addLayout(workers_row)

        inp_grp.setLayout(inp_lay)
        lay.addWidget(inp_grp)

        # ── Progress bar ──────────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet("""
            QProgressBar {
                background: #E2E8F0;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6366F1, stop:1 #818CF8);
                border-radius: 4px;
            }
        """)
        lay.addWidget(self._progress_bar)

        # ── Action buttons ────────────────────────────────────────────────
        act_row = QHBoxLayout()

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #64748B; font-size: 12px;")
        act_row.addWidget(self._status_lbl)
        act_row.addStretch()

        self._clear_input_btn = SecondaryButton("🗑 Xóa Input")
        self._clear_input_btn.setMinimumHeight(38)
        self._clear_input_btn.clicked.connect(self._input_edit.clear)
        act_row.addWidget(self._clear_input_btn)

        act_row.addSpacing(6)

        self._clear_table_btn = SecondaryButton("🧹 Xóa Bảng")
        self._clear_table_btn.setMinimumHeight(38)
        self._clear_table_btn.clicked.connect(self._clear_table)
        act_row.addWidget(self._clear_table_btn)

        act_row.addSpacing(6)

        self._export_btn = SecondaryButton("💾 Xuất CSV")
        self._export_btn.setMinimumHeight(38)
        self._export_btn.clicked.connect(self._export_csv)
        act_row.addWidget(self._export_btn)

        act_row.addSpacing(8)

        self._check_btn = PrimaryButton("🚀  Kiểm tra")
        self._check_btn.setMinimumWidth(150)
        self._check_btn.setMinimumHeight(38)
        self._check_btn.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        self._check_btn.clicked.connect(self._toggle)
        act_row.addWidget(self._check_btn)

        lay.addLayout(act_row)

        # ── Results table ─────────────────────────────────────────────────
        tbl_grp = self._make_group("📊  Kết quả")
        tbl_lay = QVBoxLayout()
        tbl_lay.setContentsMargins(8, 6, 8, 8)
        tbl_lay.setSpacing(0)

        self._table = QTableWidget()
        self._table.setColumnCount(len(COLUMNS))
        self._table.setHorizontalHeaderLabels([c[0] for c in COLUMNS])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        # Bio column gets extra stretch
        bio_col = next(i for i, c in enumerate(COLUMNS) if c[1] == "bio")
        self._table.horizontalHeader().setSectionResizeMode(bio_col, QHeaderView.ResizeMode.Stretch)

        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.setMinimumHeight(320)
        self._table.setSortingEnabled(True)

        self._apply_table_style()

        tbl_lay.addWidget(self._table)
        tbl_grp.setLayout(tbl_lay)
        lay.addWidget(tbl_grp)

        lay.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ── Styling helpers ───────────────────────────────────────────────────────

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

    def _apply_table_style(self):
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #FFFFFF;
                alternate-background-color: #F8FAFF;
                gridline-color: #E2E8F0;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
                font-size: 12px;
                color: #1E293B;
            }
            QTableWidget::item {
                padding: 6px 10px;
            }
            QTableWidget::item:selected {
                background-color: rgba(99, 102, 241, 0.15);
                color: #1E293B;
            }
            QHeaderView::section {
                background-color: #F1F5F9;
                color: #475569;
                font-weight: 700;
                font-size: 12px;
                border: none;
                border-bottom: 2px solid #CBD5E1;
                border-right: 1px solid #E2E8F0;
                padding: 8px 10px;
            }
            QHeaderView::section:last {
                border-right: none;
            }
        """)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _toggle(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._check_btn.setText("Đang dừng...")
            self._check_btn.setEnabled(False)
            return

        raw = self._input_edit.toPlainText().strip()
        if not raw:
            self.log_message.emit("❌ Vui lòng nhập ít nhất 1 username hoặc link kênh!")
            return

        usernames = [line.strip() for line in raw.splitlines() if line.strip()]
        if not usernames:
            return

        total = len(usernames)
        self.log_message.emit(f"🚀 Bắt đầu kiểm tra {total} kênh TikTok...")
        self._status_lbl.setText(f"Đang kiểm tra 0/{total}...")

        self._progress_bar.setMaximum(total)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._check_btn.setText("⏹  Dừng")
        self._check_btn.setStyleSheet(
            "QPushButton { background: #EF4444; color: white; border-radius: 8px; "
            "font-size:12px; font-weight:bold; }"
            "QPushButton:hover { background: #DC2626; }"
        )

        workers = self._workers_spin.value()
        self.log_message.emit(f"⚡ Check song song: {workers} luồng")
        self._worker = CheckerThread(usernames, workers=workers)
        self._worker.log.connect(self.log_message.emit)
        self._worker.row_ready.connect(self._on_row_ready)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_.connect(self._on_done)
        self._worker.start()

    def _on_row_ready(self, result: dict):
        """Thêm 1 hàng kết quả vào bảng."""
        self._results.append(result)
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._row_count = row + 1

        is_ok = result.get("status") == "ok"

        for col_idx, (_, key, align) in enumerate(COLUMNS):
            if key is None:
                # STT
                item = QTableWidgetItem(str(row + 1))
            elif key == "verified":
                val = result.get("verified", False)
                item = QTableWidgetItem("✅" if val else "—")
            elif key == "status":
                if is_ok:
                    item = QTableWidgetItem("✅ OK")
                else:
                    err = result.get("error", "Lỗi")
                    item = QTableWidgetItem(f"❌ {err}")
            else:
                val = result.get(key, "")
                item = QTableWidgetItem(str(val) if val is not None else "—")

            item.setTextAlignment(int(align) | int(Qt.AlignmentFlag.AlignVCenter))

            # Row color
            if not is_ok:
                item.setForeground(QBrush(QColor("#DC2626")))
            elif col_idx == COLUMNS.index(next(c for c in COLUMNS if c[1] == "followers_fmt")):
                item.setForeground(QBrush(QColor("#4F46E5")))

            self._table.setItem(row, col_idx, item)

        self._table.scrollToBottom()

    def _on_progress(self, done: int, total: int):
        self._progress_bar.setValue(done)
        self._status_lbl.setText(f"Đang kiểm tra {done}/{total}...")
        self.log_message.emit(f"📊 Tiến độ: {done}/{total}")

    def _on_done(self):
        self._check_btn.setText("🚀  Kiểm tra")
        self._check_btn.setStyleSheet("")
        self._check_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        ok    = sum(1 for r in self._results if r.get("status") == "ok")
        err   = len(self._results) - ok
        total = len(self._results)
        self._status_lbl.setText(
            f"Hoàn tất: {total} kênh · ✅ {ok} thành công · ❌ {err} lỗi"
        )
        self.log_message.emit(
            f"🎉 Kiểm tra xong! ✅ {ok} thành công  ❌ {err} lỗi"
        )
        self._worker = None

    def _clear_table(self):
        self._table.setRowCount(0)
        self._results.clear()
        self._row_count = 0
        self._status_lbl.setText("")

    def _export_csv(self):
        if not self._results:
            self.log_message.emit("⚠️ Không có dữ liệu để xuất!")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Lưu file CSV", "tiktok_channels.csv",
            "CSV Files (*.csv);;All Files (*)"
        )
        if not path:
            return

        headers = [c[0] for c in COLUMNS[1:]]   # bỏ cột STT
        keys    = [c[1] for c in COLUMNS[1:]]

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for r in self._results:
                    row_data = []
                    for k in keys:
                        if k == "verified":
                            row_data.append("Verified" if r.get("verified") else "")
                        elif k == "status":
                            row_data.append("OK" if r.get("status") == "ok" else r.get("error", "Error"))
                        else:
                            row_data.append(r.get(k, ""))
                    writer.writerow(row_data)

            self.log_message.emit(f"✅ Đã xuất CSV: {path}")
        except Exception as e:
            self.log_message.emit(f"❌ Lỗi xuất CSV: {e}")
