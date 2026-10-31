"""
ui/capcut_tab.py
----------------
UI Module for CapCut Pre-processed -> MP4 converter.
Allows drag-and-drop of multiple files, automatic format detection,
batch processing with real-time per-file progress, and 100% lossless restoration.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QProgressBar, QFileDialog, QGroupBox, QRadioButton, QButtonGroup,
    QLineEdit, QCheckBox, QFrame, QMessageBox, QMenu, QScrollArea,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QSize, QUrl
from PyQt6.QtGui import (
    QFont, QColor, QDragEnterEvent, QDragLeaveEvent, QDropEvent,
    QCursor, QAction
)

from ui.components import (
    PrimaryButton, SecondaryButton, DangerButton, GhostButton,
    SmallDangerButton, StyledProgressBar, InfoBadge
)
import ui.theme as theme
from core.capcut_preprocessor import (
    VIDEO_EXTENSIONS, detect_video_file, format_size,
    CapCutBatchWorker, find_ffmpeg, detect_gpu_encoder
)


# ─────────────────────────────────────────────────────────────────────────────
# Quick Background Scan Thread for Added Files
# ─────────────────────────────────────────────────────────────────────────────

class FileScannerThread(QThread):
    """Scans and detects video format for newly added files in the background."""
    file_detected = pyqtSignal(int, dict)  # (row_index, detection_info)
    scan_finished = pyqtSignal()

    def __init__(self, items_to_scan: List[tuple[int, str]], parent=None):
        super().__init__(parent)
        self.items = items_to_scan  # [(row_idx, file_path), ...]
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        for row_idx, file_path in self.items:
            if self._stopped:
                break
            try:
                info = detect_video_file(file_path)
            except Exception as e:
                info = {
                    "file_path": file_path,
                    "file_name": Path(file_path).name,
                    "exists": True,
                    "size_bytes": 0,
                    "size_str": "N/A",
                    "type": "error",
                    "is_capcut": False,
                    "xor_key": None,
                    "status_text": f"Lỗi đọc: {e}",
                    "badge_color": "#EF4444",
                    "needs_restoration": False,
                }
            self.file_detected.emit(row_idx, info)
        self.scan_finished.emit()


# ─────────────────────────────────────────────────────────────────────────────
# Drag & Drop Zone Widget
# ─────────────────────────────────────────────────────────────────────────────

class DropZoneWidget(QFrame):
    """
    Interactive Drag & Drop area with visual feedback on hover/drag-over.
    """
    files_dropped = pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._dark = False
        self._is_drag_active = False
        self.setMinimumHeight(130)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._build_ui()
        self._refresh_style()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_lbl = QLabel("📥")
        self.icon_lbl.setFont(QFont("Segoe UI Emoji", 26))
        self.icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon_lbl)

        self.title_lbl = QLabel("KÉO & THẢ CÁC FILE VIDEO VÀO ĐÂY")
        self.title_lbl.setFont(QFont("Inter", 13, QFont.Weight.Bold))
        self.title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title_lbl)

        self.sub_lbl = QLabel("Hỗ trợ kéo nhiều file cùng lúc · Tự nhận diện CapCut Pre-processed (XOR 0xA5) & Khôi phục Lossless")
        self.sub_lbl.setFont(QFont("Inter", 11))
        self.sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.sub_lbl)

    def _refresh_style(self):
        dark = self._dark
        active = self._is_drag_active

        if active:
            bg = "rgba(99, 102, 241, 0.15)" if dark else "rgba(79, 70, 229, 0.1)"
            border = "2px dashed #6366F1"
            title_color = "#818CF8" if dark else "#4F46E5"
        else:
            bg = "#161922" if dark else "#F8FAFC"
            border = "2px dashed #2D3244" if dark else "2px dashed #CBD5E1"
            title_color = "#F1F5F9" if dark else "#1E293B"

        sub_color = "#94A3B8" if dark else "#64748B"

        self.setStyleSheet(f"""
            DropZoneWidget {{
                background-color: {bg};
                border: {border};
                border-radius: 10px;
            }}
        """)
        self.title_lbl.setStyleSheet(f"color: {title_color}; background: transparent; border: none;")
        self.sub_lbl.setStyleSheet(f"color: {sub_color}; background: transparent; border: none;")

    def apply_theme(self, dark: bool):
        self._dark = dark
        self._refresh_style()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self._is_drag_active = True
            self._refresh_style()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._is_drag_active = False
        self._refresh_style()
        event.accept()

    def dropEvent(self, event: QDropEvent):
        self._is_drag_active = False
        self._refresh_style()

        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                p = url.toLocalFile()
                if os.path.exists(p):
                    paths.append(p)
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()


# ─────────────────────────────────────────────────────────────────────────────
# CapCut Tab Main Widget
# ─────────────────────────────────────────────────────────────────────────────

class CapCutTab(QWidget):
    """
    Main tab for CapCut Pre-processed -> MP4 converter module.
    """
    log_message = pyqtSignal(str)

    COLUMNS = [
        ("#", 50, Qt.AlignmentFlag.AlignCenter),
        ("Tên file", 280, Qt.AlignmentFlag.AlignLeft),
        ("Dung lượng", 100, Qt.AlignmentFlag.AlignCenter),
        ("Định dạng nhận diện", 210, Qt.AlignmentFlag.AlignCenter),
        ("Tiến trình", 160, Qt.AlignmentFlag.AlignCenter),
        ("Trạng thái", 160, Qt.AlignmentFlag.AlignCenter),
        ("Thao tác", 120, Qt.AlignmentFlag.AlignCenter),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = theme.is_dark()
        self._tasks: List[Dict[str, Any]] = []  # items in queue
        self._worker: Optional[CapCutBatchWorker] = None
        self._scan_thread: Optional[FileScannerThread] = None

        self._build_ui()
        self.apply_theme(self._dark)
        self._detect_gpu_badge()

    def _detect_gpu_badge(self):
        """Probes GPU hardware encoder once on startup to update status badge."""
        try:
            ffmpeg_bin = find_ffmpeg()
            gpu = detect_gpu_encoder(ffmpeg_bin)
            if gpu:
                self.badge_gpu.setText(f"🎮 GPU: {gpu[1]}")
                self.badge_gpu.setStyleSheet("""
                    QLabel {
                        background: rgba(16, 185, 129, 0.12);
                        color: #10B981;
                        border: 1px solid rgba(16, 185, 129, 0.3);
                        border-radius: 5px;
                        padding: 3px 8px;
                        font-weight: 700;
                        font-size: 11px;
                    }
                """)
            else:
                self.badge_gpu.setText("🖥️ CPU: libx264")
                self.badge_gpu.setStyleSheet("""
                    QLabel {
                        background: rgba(100, 116, 139, 0.12);
                        color: #94A3B8;
                        border: 1px solid rgba(100, 116, 139, 0.3);
                        border-radius: 5px;
                        padding: 3px 8px;
                        font-weight: 700;
                        font-size: 11px;
                    }
                """)
        except Exception:
            pass

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(6, 6, 6, 16)
        lay.setSpacing(14)

        # ── 1. Header Section ─────────────────────────────────────────────────
        hdr_box = QVBoxLayout()
        hdr_box.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        self.title_lbl = QLabel("🔄  CapCut Pre-processed → MP4")
        self.title_lbl.setFont(QFont("Inter", 17, QFont.Weight.Bold))
        top_row.addWidget(self.title_lbl)

        self.badge_lossless = QLabel("💎 Ưu tiên Remux (-c copy)")
        self.badge_lossless.setStyleSheet("""
            QLabel {
                background: rgba(16, 185, 129, 0.12);
                color: #10B981;
                border: 1px solid rgba(16, 185, 129, 0.3);
                border-radius: 5px;
                padding: 3px 8px;
                font-weight: 700;
                font-size: 11px;
            }
        """)
        top_row.addWidget(self.badge_lossless)

        self.badge_faststart = QLabel("⚡ Tối ưu +faststart")
        self.badge_faststart.setStyleSheet("""
            QLabel {
                background: rgba(99, 102, 241, 0.12);
                color: #818CF8;
                border: 1px solid rgba(99, 102, 241, 0.3);
                border-radius: 5px;
                padding: 3px 8px;
                font-weight: 700;
                font-size: 11px;
            }
        """)
        top_row.addWidget(self.badge_faststart)

        self.badge_gpu = QLabel("🎮 GPU Hardware Acceleration")
        self.badge_gpu.setStyleSheet("""
            QLabel {
                background: rgba(245, 158, 11, 0.12);
                color: #F59E0B;
                border: 1px solid rgba(245, 158, 11, 0.3);
                border-radius: 5px;
                padding: 3px 8px;
                font-weight: 700;
                font-size: 11px;
            }
        """)
        top_row.addWidget(self.badge_gpu)
        top_row.addStretch()

        hdr_box.addLayout(top_row)

        self.desc_lbl = QLabel(
            "Công nghệ sử dụng FFmpeg làm engine xử lý video, container đầu ra MP4 (ISO Base Media File Format) kết hợp H.264/libx264 và AAC. "
            "Hệ thống ưu tiên Remux (-c copy) giữ nguyên 100% chất lượng gốc và gắn cờ -movflags +faststart tối ưu phát nhanh. "
            "Hỗ trợ xử lý hàng loạt (Batch Processing / Queue) và GPU Hardware Acceleration (NVENC, Intel QSV, AMD AMF) khi cần."
        )
        self.desc_lbl.setStyleSheet("color: #64748B; font-size: 12px;")
        self.desc_lbl.setWordWrap(True)
        hdr_box.addWidget(self.desc_lbl)

        lay.addLayout(hdr_box)

        # ── 2. Drag & Drop Zone ───────────────────────────────────────────────
        self.drop_zone = DropZoneWidget()
        self.drop_zone.files_dropped.connect(self.add_paths)
        lay.addWidget(self.drop_zone)

        # Drop Zone Buttons Row
        dz_btns = QHBoxLayout()
        dz_btns.setSpacing(8)

        self.btn_add_files = PrimaryButton("📂  Chọn file video")
        self.btn_add_files.setFixedHeight(34)
        self.btn_add_files.clicked.connect(self._choose_files)
        dz_btns.addWidget(self.btn_add_files)

        self.btn_add_folder = SecondaryButton("📁  Chọn cả thư mục")
        self.btn_add_folder.setFixedHeight(34)
        self.btn_add_folder.clicked.connect(self._choose_folder)
        dz_btns.addWidget(self.btn_add_folder)

        dz_btns.addStretch()

        self.btn_rescan = GhostButton("🔍 Quét lại định dạng")
        self.btn_rescan.setFixedHeight(34)
        self.btn_rescan.clicked.connect(self._rescan_all)
        dz_btns.addWidget(self.btn_rescan)

        self.btn_clear = GhostButton("🧹 Xóa danh sách")
        self.btn_clear.setFixedHeight(34)
        self.btn_clear.clicked.connect(self._clear_table)
        dz_btns.addWidget(self.btn_clear)

        lay.addLayout(dz_btns)

        # ── 3. Output Configuration Card ──────────────────────────────────────
        self.grp_output = QGroupBox("⚙️  Cấu hình xuất file & Tùy chọn")
        grp_lay = QVBoxLayout(self.grp_output)
        grp_lay.setContentsMargins(14, 10, 14, 12)
        grp_lay.setSpacing(8)

        # Output radio buttons
        radio_row = QHBoxLayout()
        radio_row.setSpacing(16)

        self.radio_same_dir = QRadioButton("Lưu cùng thư mục với file gốc (hậu tố: _converted.mp4)")
        self.radio_same_dir.setChecked(True)
        self.radio_same_dir.toggled.connect(self._on_output_mode_changed)
        radio_row.addWidget(self.radio_same_dir)

        self.radio_custom_dir = QRadioButton("Lưu vào thư mục chỉ định:")
        self.radio_custom_dir.toggled.connect(self._on_output_mode_changed)
        radio_row.addWidget(self.radio_custom_dir)

        self.txt_custom_dir = QLineEdit()
        self.txt_custom_dir.setPlaceholderText("Chọn thư mục lưu kết quả...")
        self.txt_custom_dir.setEnabled(False)
        self.txt_custom_dir.setMinimumHeight(28)
        radio_row.addWidget(self.txt_custom_dir, 1)

        self.btn_browse_dir = SecondaryButton("Chọn...")
        self.btn_browse_dir.setFixedHeight(28)
        self.btn_browse_dir.setEnabled(False)
        self.btn_browse_dir.clicked.connect(self._browse_custom_dir)
        radio_row.addWidget(self.btn_browse_dir)

        grp_lay.addLayout(radio_row)

        # Checkboxes row
        opt_row = QHBoxLayout()
        opt_row.setSpacing(18)

        self.chk_lossless = QCheckBox("Ưu tiên Remux Stream Copy (-c copy lossless)")
        self.chk_lossless.setChecked(True)
        self.chk_lossless.setToolTip("Ưu tiên giữ nguyên bitstream gốc từ CapCut (-c copy), không giải mã nén lại để bảo toàn 100% chất lượng và tốc độ tức thì.")
        opt_row.addWidget(self.chk_lossless)

        self.chk_gpu = QCheckBox("Tăng tốc GPU (NVENC / Intel QSV / AMD AMF)")
        self.chk_gpu.setChecked(True)
        self.chk_gpu.setToolTip("Khi cần chuyển mã (transcode), tự động kích hoạt GPU phần cứng (NVIDIA NVENC, Intel QSV, AMD AMF) trước khi fallback về CPU libx264.")
        opt_row.addWidget(self.chk_gpu)

        self.chk_faststart = QCheckBox("Tối ưu streaming (-movflags +faststart)")
        self.chk_faststart.setChecked(True)
        self.chk_faststart.setToolTip("Gắn cờ -movflags +faststart để đưa moov atom lên đầu container MP4, cho phép phát ngay lập tức trên web/app.")
        opt_row.addWidget(self.chk_faststart)

        self.chk_open_folder = QCheckBox("Tự động mở thư mục khi xử lý xong")
        self.chk_open_folder.setChecked(True)
        opt_row.addWidget(self.chk_open_folder)

        opt_row.addStretch()
        grp_lay.addLayout(opt_row)

        lay.addWidget(self.grp_output)

        # ── 4. File Table Card ────────────────────────────────────────────────
        self.grp_table = QGroupBox("📋  Danh sách video cần xử lý")
        tbl_lay = QVBoxLayout(self.grp_table)
        tbl_lay.setContentsMargins(8, 8, 8, 8)
        tbl_lay.setSpacing(6)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(260)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 45)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # File name stretches
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 95)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 220)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(4, 160)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, 160)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(6, 110)

        tbl_lay.addWidget(self.table)
        lay.addWidget(self.grp_table)

        # ── 5. Batch Action Card & Overall Progress ────────────────────────────
        self.grp_action = QFrame()
        self.grp_action.setObjectName("BatchActionFrame")
        act_lay = QVBoxLayout(self.grp_action)
        act_lay.setContentsMargins(14, 12, 14, 12)
        act_lay.setSpacing(10)

        # Stats & Progress Label Row
        stat_row = QHBoxLayout()
        self.lbl_stats = QLabel("Chưa có video nào trong danh sách.")
        self.lbl_stats.setFont(QFont("Inter", 11, QFont.Weight.Medium))
        stat_row.addWidget(self.lbl_stats)

        stat_row.addStretch()

        self.lbl_status = QLabel("Sẵn sàng.")
        self.lbl_status.setFont(QFont("Inter", 11))
        self.lbl_status.setStyleSheet("color: #64748B;")
        stat_row.addWidget(self.lbl_status)
        act_lay.addLayout(stat_row)

        # Overall progress bar
        self.overall_progress_bar = QProgressBar()
        self.overall_progress_bar.setFixedHeight(8)
        self.overall_progress_bar.setTextVisible(False)
        self.overall_progress_bar.setValue(0)
        act_lay.addWidget(self.overall_progress_bar)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_open_out_dir = SecondaryButton("📂  Mở thư mục xuất")
        self.btn_open_out_dir.setFixedHeight(38)
        self.btn_open_out_dir.clicked.connect(self._open_output_dir)
        btn_row.addWidget(self.btn_open_out_dir)

        btn_row.addStretch()

        self.btn_stop = DangerButton("⏹  Dừng lại")
        self.btn_stop.setFixedWidth(130)
        self.btn_stop.setFixedHeight(38)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_batch)
        btn_row.addWidget(self.btn_stop)

        self.btn_start = PrimaryButton("🚀  Bắt đầu khôi phục")
        self.btn_start.setMinimumWidth(190)
        self.btn_start.setFixedHeight(38)
        self.btn_start.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._start_batch)
        btn_row.addWidget(self.btn_start)

        act_lay.addLayout(btn_row)
        lay.addWidget(self.grp_action)

        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ── Styling & Theming ─────────────────────────────────────────────────────

    def apply_theme(self, dark: bool):
        self._dark = dark
        self.drop_zone.apply_theme(dark)

        # Colors from theme palette
        c = theme.DARK if dark else theme.LIGHT

        self.title_lbl.setStyleSheet(f"color: {c['text']}; background: transparent; border: none;")
        self.desc_lbl.setStyleSheet(f"color: {c['text_muted']}; background: transparent; border: none;")

        # Group box styling
        grp_style = f"""
            QGroupBox {{
                background-color: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                font-weight: 700;
                font-size: 13px;
                color: {c['text']};
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {c['text']};
                background: transparent;
            }}
        """
        self.grp_output.setStyleSheet(grp_style)
        self.grp_table.setStyleSheet(grp_style)

        # Batch action frame
        self.grp_action.setStyleSheet(f"""
            #BatchActionFrame {{
                background-color: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
        """)
        self.lbl_stats.setStyleSheet(f"color: {c['text']}; background: transparent; border: none;")

        # Progress bar
        self.overall_progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: {c['surface2']};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {c['primary']}, stop:1 {c['primary_hover']});
                border-radius: 4px;
            }}
        """)

        # Table styling
        self._apply_table_style()

        # Update rows badges and cell widgets
        for row in range(self.table.rowCount()):
            self._update_row_widgets_style(row)

    def _apply_table_style(self):
        c = theme.DARK if self._dark else theme.LIGHT
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {c['surface']};
                alternate-background-color: {c['surface2']};
                gridline-color: {c['border']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                font-size: 12px;
                color: {c['text']};
            }}
            QTableWidget::item {{
                padding: 4px 6px;
                border-bottom: 1px solid {c['border']};
            }}
            QTableWidget::item:selected {{
                background-color: rgba(99, 102, 241, 0.18);
                color: {c['text']};
            }}
            QHeaderView::section {{
                background-color: {c['surface2']};
                color: {c['text_sub']};
                font-weight: 700;
                font-size: 12px;
                border: none;
                border-bottom: 2px solid {c['border_hover']};
                border-right: 1px solid {c['border']};
                padding: 6px 8px;
            }}
            QHeaderView::section:last {{
                border-right: none;
            }}
        """)

    def _update_row_widgets_style(self, row: int):
        # Trigger redraw of row widgets if needed
        pass

    # ── Path & File Management ────────────────────────────────────────────────

    def _choose_files(self):
        filter_str = (
            "Tất cả video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.ts *.mts *.m2ts);;"
            "Video MP4 (*.mp4);;Tất cả các file (*.*)"
        )
        files, _ = QFileDialog.getOpenFileNames(
            self, "Chọn các file video cần khôi phục", "", filter_str
        )
        if files:
            self.add_paths(files)

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa video CapCut")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths: List[str]):
        """Accepts a list of file and folder paths, adds valid videos to queue."""
        expanded_files = []
        for p_str in paths:
            p = Path(p_str)
            if p.is_file():
                expanded_files.append(str(p.resolve()))
            elif p.is_dir():
                for root, _, files in os.walk(p):
                    for f in files:
                        f_path = Path(root) / f
                        ext = f_path.suffix.lower()
                        # Also include .tmp files or extensionless files that could be CapCut renders
                        if ext in VIDEO_EXTENSIONS or ext == ".tmp":
                            expanded_files.append(str(f_path.resolve()))

        # Filter out duplicates already in tasks
        existing_paths = {t["path"] for t in self._tasks}
        new_items = []
        for f in expanded_files:
            if f not in existing_paths:
                new_items.append(f)
                existing_paths.add(f)

        if not new_items:
            if not self._tasks:
                self.log_message.emit("ℹ️ Không tìm thấy video hợp lệ trong đường dẫn đã chọn.")
            return

        self.log_message.emit(f"📥 Đã thêm {len(new_items)} file vào danh sách. Đang tiến hành phân tích nhận diện...")

        start_row = len(self._tasks)
        items_to_scan = []

        self.table.setSortingEnabled(False)
        for i, f_path in enumerate(new_items):
            row_idx = start_row + i
            p = Path(f_path)
            size_bytes = p.stat().st_size if p.exists() else 0
            size_str = format_size(size_bytes)

            task_item = {
                "index": row_idx,
                "path": f_path,
                "name": p.name,
                "size_bytes": size_bytes,
                "size_str": size_str,
                "detection": None,
                "status": "pending",
                "output_path": None,
            }
            self._tasks.append(task_item)
            items_to_scan.append((row_idx, f_path))

            self._insert_table_row(row_idx, task_item)

        self._update_stats_label()
        self.btn_start.setEnabled(True)

        # Launch background scanning thread to probe format without UI stutter
        self._start_scan_thread(items_to_scan)

    def _insert_table_row(self, row: int, task: Dict[str, Any]):
        self.table.insertRow(row)
        self.table.setRowHeight(row, 44)

        # Col 0: Index
        it_idx = QTableWidgetItem(str(row + 1))
        it_idx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 0, it_idx)

        # Col 1: Filename
        it_name = QTableWidgetItem(f"🎬 {task['name']}")
        it_name.setToolTip(f"Đường dẫn đầy đủ:\n{task['path']}")
        f = it_name.font()
        f.setWeight(QFont.Weight.Medium)
        it_name.setFont(f)
        self.table.setItem(row, 1, it_idx)
        self.table.setItem(row, 1, it_name)

        # Col 2: Size
        it_size = QTableWidgetItem(task["size_str"])
        it_size.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, 2, it_size)

        # Col 3: Format detection badge
        lbl_badge = QLabel("🔍 Đang nhận diện...")
        lbl_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_badge.setStyleSheet("""
            QLabel {
                background: rgba(148, 163, 184, 0.15);
                color: #64748B;
                border-radius: 4px;
                padding: 4px 8px;
                font-weight: 600;
                font-size: 11px;
            }
        """)
        self.table.setCellWidget(row, 3, lbl_badge)

        # Col 4: Progress widget (ProgressBar + percentage)
        prog_widget = QWidget()
        prog_lay = QHBoxLayout(prog_widget)
        prog_lay.setContentsMargins(6, 4, 6, 4)
        prog_lay.setSpacing(6)

        pbar = QProgressBar()
        pbar.setFixedHeight(8)
        pbar.setTextVisible(False)
        pbar.setValue(0)
        pbar.setStyleSheet("""
            QProgressBar {
                background: #E2E8F0;
                border-radius: 4px;
                border: none;
            }
            QProgressBar::chunk {
                background: #6366F1;
                border-radius: 4px;
            }
        """)
        prog_lay.addWidget(pbar, 1)

        lbl_pct = QLabel("0%")
        lbl_pct.setFixedWidth(34)
        lbl_pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lbl_pct.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 600;")
        prog_lay.addWidget(lbl_pct)

        prog_widget.pbar = pbar
        prog_widget.lbl_pct = lbl_pct
        self.table.setCellWidget(row, 4, prog_widget)

        # Col 5: Status label
        lbl_status = QLabel("Chờ xử lý")
        lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_status.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 500;")
        self.table.setCellWidget(row, 5, lbl_status)

        # Col 6: Action buttons widget
        act_widget = QWidget()
        act_lay = QHBoxLayout(act_widget)
        act_lay.setContentsMargins(4, 2, 4, 2)
        act_lay.setSpacing(4)
        act_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_loc = QPushButton("📂")
        btn_loc.setToolTip("Mở thư mục chứa file")
        btn_loc.setFixedSize(26, 26)
        btn_loc.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_loc.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                font-size: 12px;
                padding: 0;
            }
            QPushButton:hover { background: #E2E8F0; }
        """)
        btn_loc.clicked.connect(lambda _, r=row: self._locate_file(r))
        act_lay.addWidget(btn_loc)

        btn_del = QPushButton("✕")
        btn_del.setToolTip("Xóa khỏi danh sách")
        btn_del.setFixedSize(26, 26)
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #EF4444;
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 4px;
                font-size: 11px;
                font-weight: 700;
                padding: 0;
            }
            QPushButton:hover { background: rgba(239, 68, 68, 0.15); border-color: #EF4444; }
        """)
        btn_del.clicked.connect(lambda _, r=row: self._remove_row(r))
        act_lay.addWidget(btn_del)

        self.table.setCellWidget(row, 6, act_widget)

    def _start_scan_thread(self, items_to_scan: List[tuple[int, str]]):
        if self._scan_thread and self._scan_thread.isRunning():
            self._scan_thread.stop()
            self._scan_thread.wait(1000)

        self._scan_thread = FileScannerThread(items_to_scan, self)
        self._scan_thread.file_detected.connect(self._on_file_detected)
        self._scan_thread.scan_finished.connect(self._on_scan_finished)
        self._scan_thread.start()

    def _on_file_detected(self, row_idx: int, info: Dict[str, Any]):
        if row_idx >= len(self._tasks):
            return
        self._tasks[row_idx]["detection"] = info

        # Update badge widget
        badge = self.table.cellWidget(row_idx, 3)
        if isinstance(badge, QLabel):
            txt = info.get("status_text", "Không xác định")
            color = info.get("badge_color", "#64748B")
            badge.setText(txt)
            badge.setToolTip(info.get("description", ""))
            badge.setStyleSheet(f"""
                QLabel {{
                    background: {color}22;
                    color: {color};
                    border: 1px solid {color}55;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-weight: 700;
                    font-size: 11px;
                }}
            """)

        self._update_stats_label()

    def _on_scan_finished(self):
        self._update_stats_label()

    def _rescan_all(self):
        if not self._tasks:
            return
        items = [(i, t["path"]) for i, t in enumerate(self._tasks)]
        for i, _ in items:
            badge = self.table.cellWidget(i, 3)
            if isinstance(badge, QLabel):
                badge.setText("🔍 Đang nhận diện...")
        self._start_scan_thread(items)
        self.log_message.emit("🔍 Đang quét lại định dạng toàn bộ danh sách...")

    def _clear_table(self):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "Cảnh báo", "Đang có tiến trình xử lý video. Vui lòng dừng lại trước khi xóa danh sách.")
            return

        self._tasks.clear()
        self.table.setRowCount(0)
        self.overall_progress_bar.setValue(0)
        self.lbl_status.setText("Đã xóa danh sách.")
        self.btn_start.setEnabled(False)
        self._update_stats_label()
        self.log_message.emit("🧹 Đã dọn sạch danh sách video.")

    def _remove_row(self, row: int):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "Cảnh báo", "Không thể xóa dòng khi đang xử lý hàng loạt.")
            return

        if 0 <= row < len(self._tasks):
            del self._tasks[row]
            self.table.removeRow(row)

            # Re-index remaining rows
            for r in range(self.table.rowCount()):
                self._tasks[r]["index"] = r
                item = self.table.item(r, 0)
                if item:
                    item.setText(str(r + 1))
                # Rebind action buttons
                act_widget = self.table.cellWidget(r, 6)
                if act_widget:
                    buttons = act_widget.findChildren(QPushButton)
                    if len(buttons) >= 2:
                        buttons[0].clicked.disconnect()
                        buttons[0].clicked.connect(lambda _, r_cur=r: self._locate_file(r_cur))
                        buttons[1].clicked.disconnect()
                        buttons[1].clicked.connect(lambda _, r_cur=r: self._remove_row(r_cur))

            self._update_stats_label()
            if not self._tasks:
                self.btn_start.setEnabled(False)

    def _update_stats_label(self):
        total = len(self._tasks)
        if total == 0:
            self.lbl_stats.setText("Chưa có video nào trong danh sách.")
            return

        capcut_count = sum(1 for t in self._tasks if (t.get("detection") or {}).get("is_capcut", False))
        standard_count = sum(1 for t in self._tasks if (t.get("detection") or {}).get("type") == "standard_video")
        done_count = sum(1 for t in self._tasks if t.get("status") == "completed")

        txt = (
            f"Tổng: <b>{total}</b> video  |  "
            f"<span style='color:#8B5CF6'>🟣 CapCut Pre-processed: <b>{capcut_count}</b></span>  |  "
            f"<span style='color:#10B981'>🟢 MP4 chuẩn: <b>{standard_count}</b></span>  |  "
            f"<span style='color:#3B82F6'>✅ Đã hoàn tất: <b>{done_count}/{total}</b></span>"
        )
        self.lbl_stats.setText(txt)

    # ── Output Directory Handling ─────────────────────────────────────────────

    def _on_output_mode_changed(self):
        is_custom = self.radio_custom_dir.isChecked()
        self.txt_custom_dir.setEnabled(is_custom)
        self.btn_browse_dir.setEnabled(is_custom)

    def _browse_custom_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu file sau khi khôi phục")
        if d:
            self.txt_custom_dir.setText(d)

    def _open_output_dir(self):
        """Opens output directory or first file's folder in Explorer."""
        if self.radio_custom_dir.isChecked() and self.txt_custom_dir.text().strip():
            target_dir = self.txt_custom_dir.text().strip()
        elif self._tasks:
            target_dir = str(Path(self._tasks[0]["path"]).parent)
        else:
            QMessageBox.information(self, "Thông báo", "Chưa có thư mục đầu ra để mở.")
            return

        if os.path.exists(target_dir):
            os.startfile(target_dir)
        else:
            QMessageBox.warning(self, "Lỗi", f"Thư mục không tồn tại:\n{target_dir}")

    def _locate_file(self, row: int):
        if 0 <= row < len(self._tasks):
            # If converted file exists, highlight it; else highlight source file
            out_p = self._tasks[row].get("output_path")
            target = out_p if (out_p and os.path.exists(out_p)) else self._tasks[row]["path"]

            if os.path.exists(target):
                subprocess.Popen(f'explorer /select,"{os.path.abspath(target)}"')
            else:
                QMessageBox.warning(self, "Lỗi", f"File không tồn tại:\n{target}")

    def _play_file(self, row: int):
        if 0 <= row < len(self._tasks):
            out_p = self._tasks[row].get("output_path")
            target = out_p if (out_p and os.path.exists(out_p)) else self._tasks[row]["path"]
            if os.path.exists(target):
                os.startfile(target)
            else:
                QMessageBox.warning(self, "Lỗi", f"Không tìm thấy file để mở:\n{target}")

    # ── Context Menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item:
            return
        row = item.row()
        menu = QMenu(self)

        act_play = QAction("▶ Phát / Mở video", self)
        act_play.triggered.connect(lambda: self._play_file(row))
        menu.addAction(act_play)

        act_loc = QAction("📂 Mở thư mục chứa file", self)
        act_loc.triggered.connect(lambda: self._locate_file(row))
        menu.addAction(act_loc)

        menu.addSeparator()

        act_del = QAction("✕ Xóa khỏi danh sách", self)
        act_del.triggered.connect(lambda: self._remove_row(row))
        menu.addAction(act_del)

        menu.exec(QCursor.pos())

    # ── Batch Processing Execution ────────────────────────────────────────────

    def _start_batch(self):
        if not self._tasks:
            QMessageBox.information(self, "Thông báo", "Vui lòng thêm ít nhất một video vào danh sách.")
            return

        if self._worker and self._worker.isRunning():
            return

        # Prepare parameters
        same_dir = self.radio_same_dir.isChecked()
        custom_dir = self.txt_custom_dir.text().strip() if not same_dir else None

        if not same_dir and (not custom_dir or not os.path.exists(custom_dir)):
            QMessageBox.warning(self, "Lỗi thư mục", "Vui lòng chọn thư mục đích hợp lệ trước khi bắt đầu.")
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_clear.setEnabled(False)
        self.overall_progress_bar.setValue(0)
        self.lbl_status.setText("Đang xử lý...")

        # Reset task progress UI
        for r in range(len(self._tasks)):
            self._tasks[r]["status"] = "processing"
            self._set_row_progress(r, 0.0, "Chờ đến lượt...")
            self._set_row_status(r, "⏳ Đang chờ...", "#64748B")

        # Create worker thread
        self._worker = CapCutBatchWorker(
            tasks=self._tasks,
            output_dir=custom_dir,
            same_dir=same_dir,
            suffix="_converted.mp4",
            prefer_lossless=self.chk_lossless.isChecked(),
            use_gpu=self.chk_gpu.isChecked(),
            faststart=self.chk_faststart.isChecked(),
            parent=self
        )
        self._worker.file_started.connect(self._on_worker_file_started)
        self._worker.file_progress.connect(self._on_worker_file_progress)
        self._worker.file_completed.connect(self._on_worker_file_completed)
        self._worker.file_failed.connect(self._on_worker_file_failed)
        self._worker.batch_progress.connect(self._on_worker_batch_progress)
        self._worker.batch_finished.connect(self._on_worker_batch_finished)
        self._worker.log_message.connect(self.log_message.emit)

        self._worker.start()

    def _stop_batch(self):
        if self._worker and self._worker.isRunning():
            self.lbl_status.setText("Đang dừng...")
            self._worker.stop()
            self.btn_stop.setEnabled(False)
            self.log_message.emit("⏹️ Đang yêu cầu dừng tiến trình...")

    def _set_row_progress(self, row: int, pct: float, text: str):
        widget = self.table.cellWidget(row, 4)
        if widget and hasattr(widget, "pbar") and hasattr(widget, "lbl_pct"):
            val = int(pct * 100)
            widget.pbar.setValue(val)
            widget.lbl_pct.setText(f"{val}%")

    def _set_row_status(self, row: int, text: str, color_hex: str = "#64748B"):
        lbl = self.table.cellWidget(row, 5)
        if isinstance(lbl, QLabel):
            lbl.setText(text)
            lbl.setStyleSheet(f"color: {color_hex}; font-size: 11px; font-weight: 600;")

    # ── Worker Slots ──────────────────────────────────────────────────────────

    def _on_worker_file_started(self, row: int, filename: str):
        self._set_row_progress(row, 0.05, "Bắt đầu...")
        self._set_row_status(row, "🔄 Đang xử lý...", "#8B5CF6")
        self.lbl_status.setText(f"Đang xử lý: {filename}")

    def _on_worker_file_progress(self, row: int, pct: float, text: str):
        self._set_row_progress(row, pct, text)
        self._set_row_status(row, f"🔄 {text}", "#6366F1")

    def _on_worker_file_completed(self, row: int, res: Dict[str, Any]):
        self._tasks[row]["status"] = "completed"
        self._tasks[row]["output_path"] = res["output_path"]
        self._set_row_progress(row, 1.0, "Xong")
        self._set_row_status(row, "✅ Hoàn tất", "#10B981")
        self._update_stats_label()

    def _on_worker_file_failed(self, row: int, err_msg: str):
        self._tasks[row]["status"] = "failed"
        self._set_row_status(row, "❌ Lỗi", "#EF4444")
        self._update_stats_label()

    def _on_worker_batch_progress(self, done_count: int, total_count: int, overall_pct: float):
        self.overall_progress_bar.setValue(int(overall_pct * 100))
        self.lbl_status.setText(f"Đã xử lý {done_count}/{total_count} video ({int(overall_pct * 100)}%)")

    def _on_worker_batch_finished(self, success_count: int, failed_count: int, total_count: int):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_clear.setEnabled(True)

        self.overall_progress_bar.setValue(100)
        self.lbl_status.setText(f"Hoàn thành: {success_count}/{total_count} video thành công.")
        self._update_stats_label()

        # Show notification
        msg = f"Đã khôi phục thành công {success_count}/{total_count} video."
        if failed_count > 0:
            msg += f"\nCó {failed_count} file gặp lỗi (xem chi tiết tại Process Log)."

        QMessageBox.showinfo = QMessageBox.information
        QMessageBox.information(self, "Hoàn tất khôi phục", msg)

        # Auto open folder if requested
        if self.chk_open_folder.isChecked() and success_count > 0:
            self._open_output_dir()
