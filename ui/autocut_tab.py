"""
AutoCut Tab - Video Editor UI Component
Adapted from standalone AutoCut application to work as a tab in AutoShorts
"""

import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QLineEdit, QFileDialog, QSpinBox, 
                             QDoubleSpinBox, QTextEdit, QProgressBar, QGroupBox, 
                             QFormLayout, QCheckBox, QComboBox, QColorDialog, 
                             QTimeEdit, QFrame, QGridLayout, QScrollArea, 
                             QMessageBox, QSlider, QApplication, QSizePolicy, 
                             QButtonGroup)
from PyQt6.QtCore import Qt, pyqtSignal, QTime, QTimer
from PyQt6.QtGui import QFont as QFont_GUI, QColor, QPixmap
from datetime import datetime
from PIL import Image

# Import from core module
from core.autocut_processor import (VideoProcessThread, SkipRangeWidget, 
                                   detect_gpu_encoder, FFMPEG_EXE, FFPROBE_EXE,
                                   run_ffmpeg_silent, EXE_DIR,
                                   detect_scene_cuts, get_scene_skip_ranges,
                                   SceneAnalysisThread, build_scene_split_log_details,
                                   VideoDownloaderThread, ThumbnailDownloaderThread,
                                   prepare_thumbnail_portrait,
                                   create_thumbnail_with_part_overlay,
                                   fetch_or_extract_thumbnail)
from core.subtitle_processor import (SubtitleConfig, SubtitleGeneratorThread)



class PreviewPopup(QWidget):
    """Popup window để hiển thị preview ở kích thước lớn hơn"""
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preview - Xem phóng to")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowStaysOnTopHint)
        
        # Set window size
        self.resize(600, 1000)
        
        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title
        title = QLabel("🔍 Preview - Xem phóng to")
        title.setFont(QFont_GUI("Segoe UI", 14, QFont_GUI.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #2c3e50; padding: 10px;")
        layout.addWidget(title)
        
        # Preview label
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #2c3e50;
                border: 3px solid #34495e;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        
        # Scale pixmap to fit window (keep aspect ratio)
        if pixmap and not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                560,  # Width
                900,  # Height
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled_pixmap)
        else:
            self.preview_label.setText("Không có preview")
            self.preview_label.setStyleSheet(self.preview_label.styleSheet() + "color: #7f8c8d; font-size: 12pt;")
        
        layout.addWidget(self.preview_label, 1)
        
        # Close button
        close_btn = QPushButton("✕ Đóng")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-weight: 600;
                font-size: 11pt;
                min-height: 35px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
        """)
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        # Center window on screen
        self.center_on_screen()
    
    def center_on_screen(self):
        """Center the window on the screen"""
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)


class VideoItemWidget(QFrame):
    preview_requested = pyqtSignal(str, float)
    title_changed = pyqtSignal()
    stats_changed = pyqtSignal()

    def __init__(self, path, original_duration, parent=None):
        super().__init__(parent)
        self.path = path
        self.duration = original_duration
        self.skip_widgets = []
        self.setup_ui()
    
    def setup_ui(self):
        self.setFrameShape(QFrame.Shape.NoFrame)
        # Styling delegated to global QSS VideoItemWidget selector
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header: Path and Preview
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        path_label = QLabel(f"📄 .../{Path(self.path).name}")
        path_label.setToolTip(self.path)
        path_label.setStyleSheet("color: #9d93c0; font-size: 11px; border: none; background: transparent; font-weight: 500;")
        header_layout.addWidget(path_label, stretch=1)
        
        preview_btn = QPushButton("👁 Preview")
        preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        preview_btn.setStyleSheet("""
            QPushButton {
                background-color: #2c2840;
                color: #c4b5fd;
                border: 1px solid #3d3660;
                border-radius: 6px;
                padding: 4px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #3d3660; border-color: #7c3aed; }
        """)
        preview_btn.clicked.connect(lambda: self.preview_requested.emit(self.path, self.duration))
        header_layout.addWidget(preview_btn)
        
        main_layout.addLayout(header_layout)

        # Title Input
        title_layout = QHBoxLayout()
        title_label = QLabel("Tiêu đề:")
        title_label.setStyleSheet("color: #ede9ff; font-weight: 600; font-size: 12px; border: none;")
        title_label.setFixedWidth(55)
        title_layout.addWidget(title_label)

        stem = Path(self.path).stem
        self.title_input = QLineEdit()
        self.title_input.setText(stem)
        self.title_input.textChanged.connect(lambda: self.title_changed.emit())
        self.title_input.setStyleSheet("""
            QLineEdit {
                border: 1.5px solid #3d3660;
                border-radius: 6px;
                background-color: #2c2840;
                padding: 6px 10px;
                color: #ede9ff;
                font-size: 13px;
                font-weight: 500;
            }
            QLineEdit:focus {
                border-color: #8b5cf6;
                background-color: #362f52;
            }
        """)
        title_layout.addWidget(self.title_input)
        main_layout.addLayout(title_layout)

        # Cut range
        cut_layout = QHBoxLayout()
        cut_layout.setContentsMargins(0, 0, 0, 0)
        
        cut_icon = QLabel("✂ Khoảng cắt:")
        cut_icon.setStyleSheet("color: #ede9ff; font-weight: 600; font-size: 12px; border: none;")
        cut_icon.setFixedWidth(85)
        cut_layout.addWidget(cut_icon)
        
        self.cut_start = QTimeEdit()
        self.cut_start.setDisplayFormat("HH:mm:ss")
        self.cut_start.setTime(QTime(0, 0, 0))
        self.cut_start.setFixedWidth(100)
        self.cut_start.setStyleSheet("QTimeEdit { border: 1.5px solid #3d3660; border-radius: 6px; padding: 3px 6px; background-color: #2c2840; color: #ede9ff; }")
        self.cut_start.timeChanged.connect(lambda: self.stats_changed.emit())
        cut_layout.addWidget(self.cut_start)

        to_label = QLabel(" đến ")
        to_label.setStyleSheet("color: #9d93c0; font-size: 12px; border: none;")
        cut_layout.addWidget(to_label)

        self.cut_end = QTimeEdit()
        self.cut_end.setDisplayFormat("HH:mm:ss")
        h = int(self.duration // 3600)
        m = int((self.duration % 3600) // 60)
        s = int(self.duration % 60)
        self.cut_end.setTime(QTime(h, m, s))
        self.cut_end.setFixedWidth(100)
        self.cut_end.setStyleSheet("QTimeEdit { border: 1.5px solid #3d3660; border-radius: 6px; padding: 3px 6px; background-color: #2c2840; color: #ede9ff; }")
        self.cut_end.timeChanged.connect(lambda: self.stats_changed.emit())
        cut_layout.addWidget(self.cut_end)
        
        cut_layout.addStretch() # Prevents stretching
        main_layout.addLayout(cut_layout)

        # Skip range separator/header
        skip_header_layout = QHBoxLayout()
        skip_header_layout.setContentsMargins(0, 4, 0, 0)
        
        skip_label = QLabel("⏭ Bỏ qua đoạn:")
        skip_label.setStyleSheet("color: #ede9ff; font-weight: 600; font-size: 12px; border: none;")
        skip_header_layout.addWidget(skip_label)

        add_skip_btn = QPushButton("+ Thêm khoảng")
        add_skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_skip_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a78bfa;
                border: 1px dashed #7c3aed;
                border-radius: 5px;
                padding: 3px 8px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover { background-color: rgba(139,92,246,0.15); }
        """)
        add_skip_btn.clicked.connect(self.add_skip_range)
        skip_header_layout.addWidget(add_skip_btn)
        skip_header_layout.addStretch()
        main_layout.addLayout(skip_header_layout)

        # Skip container (No heavy borders)
        self.skip_container_widget = QWidget()
        self.skip_container_widget.setStyleSheet("background: transparent; border: none;")
        self.skip_container = QVBoxLayout(self.skip_container_widget)
        self.skip_container.setSpacing(4)
        self.skip_container.setContentsMargins(0, 0, 0, 0)

        self.skip_placeholder = QLabel("Chưa có đoạn bỏ qua nào")
        self.skip_placeholder.setStyleSheet("color: #5a5278; font-style: italic; font-size: 11px; padding: 4px 0;")
        self.skip_container.addWidget(self.skip_placeholder)

        main_layout.addWidget(self.skip_container_widget)
        
        # Stats summary label
        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("color: #a78bfa; font-size: 11px; font-weight: bold; background-color: rgba(139,92,246,0.12); padding: 4px 8px; border-radius: 6px;")
        self.stats_label.hide()
        main_layout.addWidget(self.stats_label)

    def add_skip_range(self):
        self.skip_placeholder.setVisible(False)
        skip_widget = SkipRangeWidget(len(self.skip_widgets))
        skip_widget.removed.connect(self.remove_skip_range)
        if hasattr(skip_widget, 'time_changed'):
            skip_widget.time_changed.connect(lambda: self.stats_changed.emit())
        self.skip_container.addWidget(skip_widget)
        self.skip_widgets.append(skip_widget)
        self.stats_changed.emit()
        
    def remove_skip_range(self, widget):
        self.skip_container.removeWidget(widget)
        self.skip_widgets.remove(widget)
        widget.deleteLater()
        for i, w in enumerate(self.skip_widgets):
            w.index = i
            w.findChild(QLabel).setText(f"Đoạn {i + 1}:")
        if not self.skip_widgets:
            self.skip_placeholder.setVisible(True)
        self.stats_changed.emit()

    def get_skip_ranges(self):
        ranges = []
        for w in self.skip_widgets:
            start, end = w.get_times()
            if start < end:
                ranges.append((start, end))
        ranges.sort(key=lambda x: x[0])
        return ranges

    def get_cut_times(self):
        def time_to_sec(qtime):
            return qtime.hour() * 3600 + qtime.minute() * 60 + qtime.second()
        return time_to_sec(self.cut_start.time()), time_to_sec(self.cut_end.time())

    def update_stats(self, speed, segment_sec, global_start, global_end, merge_last, merge_threshold):
        self.calculated_segments = 0
        self.calculated_last_duration = 0
        try:
            start_sec, end_sec = self.get_cut_times()
            skip_ranges = self.get_skip_ranges()
        except:
            return

        # Apply global trim
        if global_start > 0:
            start_sec = max(start_sec, global_start)
        if global_end > 0:
            max_end = max(0, self.duration - global_end)
            end_sec = min(end_sec, max_end)
            
        if start_sec >= end_sec:
            self.stats_label.setText("⚠ Bị cắt hết (Bắt đầu >= Kết thúc)")
            self.stats_label.setStyleSheet("color: #e11d48; font-size: 11px; font-weight: bold; background-color: #ffe4e6; padding: 4px 8px; border-radius: 4px;")
            self.stats_label.show()
            return
            
        total_duration = end_sec - start_sec
        
        skip_ranges.sort(key=lambda x: x[0])
        current_start = start_sec
        current_end = end_sec
        for skip_start, skip_end in skip_ranges:
            if skip_end <= current_start or skip_start >= current_end:
                continue
            effective_skip_start = max(skip_start, current_start)
            effective_skip_end = min(skip_end, current_end)
            if effective_skip_start > current_start:
                total_duration -= (effective_skip_end - effective_skip_start)
            current_start = effective_skip_end
            if current_start >= current_end:
                break
                
        total_duration = max(0, total_duration)
        
        if speed > 0:
            total_duration = total_duration / speed
            
        if segment_sec > 0 and total_duration > 0:
            segments = int(total_duration / segment_sec)
            remainder = total_duration % segment_sec
            
            if remainder < 0.1:
                last_duration = segment_sec
            else:
                last_duration = remainder
                segments += 1
                
            if merge_last and segments > 1 and last_duration < merge_threshold:
                segments -= 1
                last_duration += segment_sec
                
            self.calculated_segments = segments
            self.calculated_last_duration = last_duration
                
            m = int(last_duration // 60)
            s = int(last_duration % 60)
            formatted_last = f"{m}p {s}s"
            
            total_m = int(total_duration // 60)
            total_s = int(total_duration % 60)
            formatted_total = f"{total_m}p {total_s}s"
                
            self.stats_label.setText(f"📊 Kết quả: Tổng dài {formatted_total} | Chia làm {segments} Video | Video cuối cùng dài: {formatted_last}")
            self.stats_label.setStyleSheet("color: #0284c7; font-size: 11.5px; font-weight: bold; background-color: #f0f9ff; padding: 6px 10px; border-radius: 5px;")
            self.stats_label.show()
        else:
            if total_duration > 0:
                self.calculated_segments = 1
                self.calculated_last_duration = total_duration
            self.stats_label.hide()


class DraggablePreviewLabel(QLabel):
    """
    Subclass of QLabel that allows interactive dragging to adjust Subtitle Margin Bottom (px).
    """
    position_changed = pyqtSignal(int)  # Emits margin_v (px from bottom)

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.is_dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = True
            self._update_margin_from_event(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            self._update_margin_from_event(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
        super().mouseReleaseEvent(event)

    def _update_margin_from_event(self, event):
        h = self.height()
        if h <= 0:
            return
        mouse_y = event.position().y()
        # Map label mouse Y (0..h) to video canvas Y (0..1920)
        video_y = (mouse_y / float(h)) * 1920.0
        # Margin from bottom: 1920 - video_y
        margin_v = int(round(1920.0 - video_y))
        margin_v = max(0, min(1920, margin_v))
        self.position_changed.emit(margin_v)


class AutoCutTab(QWidget):
    """AutoCut Video Editor Tab"""
    log_message = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)

        # Variables
        self.video_duration = 0
        self.bg_color = (0, 0, 0)
        self.text_bg_color = (0, 0, 0, 255)
        self.text_color = (255, 255, 255)
        self.text_border_color = (255, 255, 255)  # Màu viền TEXT mặc định (trắng)
        self.text_border_width = 0  # Độ dày viền TEXT mặc định (0 = không có viền)
        self.overlay_color = (0, 0, 0)
        self.overlay_opacity = 0
        self.skip_widgets = []  # Danh sách các widget bỏ qua
        self.stop_btn = None
        self.current_video_path = None
        self.width_scale = 1.0
        self.height_scale = 1.0
        self.original_video_width = None
        self.original_video_height = None
        self.current_preview_pixmap = None  # Store current preview for popup
        
        # Timer cho debounce preview khi gõ tiêu đề
        self.preview_timer = QTimer()
        self.preview_timer.setSingleShot(True)
        self.preview_timer.timeout.connect(self.update_preview)

        # Subtitle variables (Auto Subtitle feature)
        self.subtitle_config = SubtitleConfig()  # All subtitle settings
        self._subtitle_threads = {}    # video_path -> SubtitleGeneratorThread
        self._pending_subtitle_files = {}  # video_path -> ass_file_path (ready to use)
        self._subtitle_color = (255, 255, 255)      # White (display in color picker)
        self._subtitle_hl_color = (255, 255, 0)     # Yellow highlight (display)
        self.is_generating_subtitles = False
        self.subtitle_generator = None
        self.subtitle_font_size = 72
        self.subtitle_border_width = 3
        self.subtitle_color = (255, 255, 255)
        self.subtitle_bg_color = (0, 0, 0, 150)
        self.current_srt_file = None

        # Batch Processing Variables
        self.processing_mode = "single"  # 'single' or 'batch'
        self.video_queue = []
        self.current_queue_index = 0
        self.total_queue_size = 0
        self.current_processing_video = None

        # Thumbnail background variables
        self.source_thumbnail_path = ""   # Path thumbnail gốc (từ URL hoặc manual)
        self.use_video_thumbnail = False  # Bật/tắt dùng thumbnail làm nền
        self._downloader_thread = None    # VideoDownloaderThread reference
        self._thumb_downloader_thread = None  # ThumbnailDownloaderThread reference

        # Setup UI
        self.setup_ui()

    def setup_ui(self):
        """Setup giao diện đơn giản, hài hòa"""
        # Apply clean, modern theme

        # Tạo scroll area cho toàn bộ tool
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Main widget bên trong scroll area
        main_widget = QWidget()
        scroll_area.setWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Main content - using grid layout for stability
        self.content_widget = QWidget()
        self.content_layout = QGridLayout(self.content_widget)
        self.content_layout.setSpacing(15)
        self.content_layout.setContentsMargins(0, 0, 0, 0)

        self.left_panel = self.create_left_panel()
        self.right_panel = self.create_right_panel()

        layout.addWidget(self.content_widget, 1)

        # Initial layout placement - add panels to grid
        self.content_layout.addWidget(self.left_panel, 0, 0)
        self.content_layout.addWidget(self.right_panel, 0, 1)
        self.content_layout.setColumnStretch(0, 1)
        self.content_layout.setColumnStretch(1, 1)

        # Footer with progress and log
        self.create_footer(layout)
        
        # Create main layout for the tab and add scroll area
        main_tab_layout = QVBoxLayout(self)
        main_tab_layout.setContentsMargins(0, 0, 0, 0)
        main_tab_layout.addWidget(scroll_area)

        # Default output
        default_output = str(Path.home() / "Documents" / "VideoEditor" / "Output")
        self.output_input.setText(default_output)

        # Ẩn batch folder option khi mặc định là single mode
        if hasattr(self, 'batch_folder_container'):
            self.batch_folder_container.setVisible(False)

        # Auto-load config nếu có
        self.load_config(silent=True)

    def create_header(self, parent_layout):
        """Tạo header đơn giản"""
        header_frame = QFrame()
        header_frame.setMaximumHeight(80)
        header_frame.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3498db, stop:1 #2c3e50);
                border-radius: 6px;
            }
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel("AutoCut - Video Editor")
        title.setFont(QFont_GUI("Segoe UI", 20, QFont_GUI.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: white;")
        header_layout.addWidget(title)

        subtitle = QLabel("Tool nội bộ thuộc quyền sở hữu của HuongVN & AnhTitan")
        subtitle.setFont(QFont_GUI("Segoe UI", 9))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.9);")
        header_layout.addWidget(subtitle)

        parent_layout.addWidget(header_frame)

    def create_left_panel(self):
        """Tạo panel bên trái với các cài đặt chính"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # File settings
        file_group = self.create_file_group()
        layout.addWidget(file_group)

        # Danh sách cấu hình video (Thay thế time settings và skip ranges)
        self.video_list_group = QGroupBox("Danh sách cấu hình Video")
        video_list_layout = QVBoxLayout(self.video_list_group)
        
        self.video_scroll_area = QScrollArea()
        self.video_scroll_area.setWidgetResizable(True)
        self.video_scroll_area.setMinimumHeight(150)
        self.video_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.video_items_container = QWidget()
        self.video_items_layout = QVBoxLayout(self.video_items_container)
        self.video_items_layout.setSpacing(5)
        self.video_items_layout.setContentsMargins(5, 5, 5, 5)
        
        self.empty_video_label = QLabel("Chưa có video nào. Hãy chọn thư mục hoặc video nguồn.")
        self.empty_video_label.setStyleSheet("color: #7f8c8d; font-style: italic; padding: 20px;")
        self.empty_video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_items_layout.addWidget(self.empty_video_label)
        self.video_items_layout.addStretch()
        
        self.video_scroll_area.setWidget(self.video_items_container)
        video_list_layout.addWidget(self.video_scroll_area)
        
        layout.addWidget(self.video_list_group, stretch=1)

        # Processing settings
        settings_group = self.create_settings_group()
        layout.addWidget(settings_group)

        return panel

    def create_right_panel(self):
        """Tạo panel bên phải với style và preview"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)

        # Style settings
        style_group = self.create_style_group()
        layout.addWidget(style_group)

        # Info panel
        info_group = self.create_info_group()
        layout.addWidget(info_group)

        layout.addStretch()
        return panel

    def create_file_group(self):
        from PyQt6.QtWidgets import QRadioButton, QButtonGroup
        group = QGroupBox("")
        layout = QFormLayout()
        layout.setSpacing(8)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        # Chế độ xử lý
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Xử lý 1 Video đơn lẻ", "single")
        self.mode_combo.addItem("Xử lý Hàng loạt (Thư mục)", "batch")
        self.mode_combo.addItem("🌐 Xử lý từ URL (YouTube / TikTok...)", "url")
        self.mode_combo.currentIndexChanged.connect(self.update_processing_mode)
        layout.addRow("Chế độ:", self.mode_combo)

        # Video input
        video_widget = QWidget()
        video_layout = QHBoxLayout(video_widget)
        video_layout.setContentsMargins(0, 0, 0, 0)

        self.video_input = QLineEdit()
        self.video_input.setPlaceholderText("Chọn video...")
        video_layout.addWidget(self.video_input, 3)

        video_btn = QPushButton("🗂️")
        video_btn.setObjectName("fileButton")
        video_btn.setToolTip("Chọn video nguồn")
        video_btn.clicked.connect(self.select_video)
        video_layout.addWidget(video_btn, 1)

        layout.addRow("Nguồn:", video_widget)

        # Output directory
        output_widget = QWidget()
        output_layout = QHBoxLayout(output_widget)
        output_layout.setContentsMargins(0, 0, 0, 0)

        self.output_input = QLineEdit()
        self.output_input.setPlaceholderText("Thư mục xuất...")
        output_layout.addWidget(self.output_input, 3)

        output_btn = QPushButton("🗂️")
        output_btn.setObjectName("fileButton")
        output_btn.setToolTip("Chọn thư mục xuất video")
        output_btn.clicked.connect(self.select_output)
        output_layout.addWidget(output_btn, 1)

        layout.addRow("Xuất:", output_widget)

        # Batch output folder mode (only relevant for batch)
        self.batch_folder_container = QWidget()
        batch_folder_layout = QHBoxLayout(self.batch_folder_container)
        batch_folder_layout.setContentsMargins(0, 0, 0, 0)
        batch_folder_layout.setSpacing(12)

        self.output_flat_radio = QRadioButton("Xuất chung 1 thư mục")
        self.output_flat_radio.setChecked(True)
        self.output_flat_radio.setToolTip("Tất cả video con được xuất thẳng vào thư mục đích")
        batch_folder_layout.addWidget(self.output_flat_radio)

        self.output_subfolder_radio = QRadioButton("Chia folder riêng (tên = tên video)")
        self.output_subfolder_radio.setToolTip("Mỗi video sẽ được xuất vào subfolder riêng, tên folder = tên file video gốc (không phải tiêu đề)")
        batch_folder_layout.addWidget(self.output_subfolder_radio)

        self.output_distribute_radio = QRadioButton("Mỗi video gốc ánh xạ vào 1 folder có sẵn")
        self.output_distribute_radio.setToolTip("Video cấu hình 1 -> thả tất cả clip cắt ra vào Folder 1. Cấu hình 2 -> thả vào Folder 2...")
        batch_folder_layout.addWidget(self.output_distribute_radio)

        self.batch_output_btn_group = QButtonGroup(self)
        self.batch_output_btn_group.addButton(self.output_flat_radio)
        self.batch_output_btn_group.addButton(self.output_subfolder_radio)
        self.batch_output_btn_group.addButton(self.output_distribute_radio)

        batch_folder_layout.addStretch()
        layout.addRow("Output (Batch):", self.batch_folder_container)

        # URL download section — chỉ hiện khi mode == 'url'
        self.url_section_container = QWidget()
        url_section_layout = QFormLayout(self.url_section_container)
        url_section_layout.setContentsMargins(0, 0, 0, 0)
        url_section_layout.setSpacing(6)

        url_widget = QWidget()
        url_layout = QHBoxLayout(url_widget)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(5)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Dán link YouTube / TikTok / Facebook...")
        self.url_input.setToolTip("Dán link video vào đây và nhấn 'Tải' để tự động tải về")
        url_layout.addWidget(self.url_input, 4)

        self.download_btn = QPushButton("⬇️ Tải")
        self.download_btn.setObjectName("downloadButton")
        self.download_btn.setToolTip("Tải video từ URL về thư mục xuất")
        self.download_btn.setStyleSheet("""
            QPushButton {
                background-color: #7C3AED;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: 700;
                font-size: 12px;
                min-width: 70px;
            }
            QPushButton:hover { background-color: #6D28D9; }
            QPushButton:pressed { background-color: #5B21B6; }
            QPushButton:disabled { background-color: #9CA3AF; }
        """)
        self.download_btn.clicked.connect(self.download_from_url)
        url_layout.addWidget(self.download_btn, 1)

        self.cancel_download_btn = QPushButton("✕")
        self.cancel_download_btn.setToolTip("Huỷ tải")
        self.cancel_download_btn.setVisible(False)
        self.cancel_download_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC2626;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 5px 10px;
                font-weight: 700;
                font-size: 12px;
                min-width: 32px;
            }
            QPushButton:hover { background-color: #B91C1C; }
        """)
        self.cancel_download_btn.clicked.connect(self.cancel_download)
        url_layout.addWidget(self.cancel_download_btn)

        url_section_layout.addRow("URL:", url_widget)

        layout.addRow("", self.url_section_container)
        self.url_section_container.setVisible(False)  # Ẩn theo mặc định

        # Thumbnail Section — Hiển thị ô nhập URL + Nút Lấy Thumb vật lý
        self.thumb_section_container = QWidget()
        thumb_section_layout = QHBoxLayout(self.thumb_section_container)
        thumb_section_layout.setContentsMargins(0, 2, 0, 2)
        thumb_section_layout.setSpacing(6)

        self.thumb_url_input = QLineEdit()
        self.thumb_url_input.setPlaceholderText("Link video/ảnh lấy thumb (để trống tự lấy frame đầu)...")
        self.thumb_url_input.setToolTip(
            "Dán link YouTube / TikTok / Facebook hoặc link ảnh trực tiếp vào đây để lấy thumbnail làm ảnh bìa.\n"
            "Nếu để trống, hệ thống sẽ tự động trích xuất frame đầu tiên của video làm ảnh bìa."
        )
        thumb_section_layout.addWidget(self.thumb_url_input)

        self.fetch_thumb_btn = QPushButton("🖼️ Get Thumb")
        self.fetch_thumb_btn.setToolTip("Nhấn để thử tải/trích xuất thumbnail ngay lập tức")
        self.fetch_thumb_btn.clicked.connect(self.on_fetch_thumb_clicked)
        thumb_section_layout.addWidget(self.fetch_thumb_btn)

        layout.addRow("Thumbnail:", self.thumb_section_container)

        self.thumb_status_label = QLabel("ℹ️ Để trống = tự lấy frame đầu video")
        self.thumb_status_label.setStyleSheet("color: #9CA3AF; font-size: 10px; font-style: italic;")
        self.thumb_status_label.setWordWrap(True)
        layout.addRow("", self.thumb_status_label)

        # Title Y position
        self.title_y_input = QSpinBox()
        self.title_y_input.setRange(0, 1920)
        self.title_y_input.setValue(250)
        self.title_y_input.setSuffix(" px")
        self.title_y_input.valueChanged.connect(self.update_preview_debounced)
        layout.addRow("Vị trí Tiêu đề (Y):", self.title_y_input)

        group.setLayout(layout)
        return group

    def create_settings_group(self):
        group = QGroupBox("")
        layout = QFormLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.setFormAlignment(Qt.AlignmentFlag.AlignTop)

        # Speed
        self.speed_input = QDoubleSpinBox()
        self.speed_input.setRange(0.25, 4.0)
        self.speed_input.setValue(1.0)
        self.speed_input.setSingleStep(0.1)
        self.speed_input.setSuffix("x")
        self.speed_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.speed_input.valueChanged.connect(self.update_duration_display)

        layout.addRow("Tốc độ video:", self.speed_input)

        # Segment
        self.segment_input = QSpinBox()
        self.segment_input.setRange(0, 3600)
        self.segment_input.setValue(0)
        self.segment_input.setSuffix("s")
        self.segment_input.setSpecialValueText("Không cắt")
        self.segment_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.segment_input.valueChanged.connect(self.update_segments_count)

        layout.addRow("Cắt mỗi (sau speed):", self.segment_input)

        # Merge Last Segment
        merge_widget = QWidget()
        merge_layout = QHBoxLayout(merge_widget)
        merge_layout.setContentsMargins(0, 0, 0, 0)
        merge_layout.setSpacing(8)

        self.merge_last_checkbox = QCheckBox("Gộp video cuối nếu <")
        self.merge_last_checkbox.setChecked(False)
        self.merge_last_checkbox.toggled.connect(self.update_segments_count)
        merge_layout.addWidget(self.merge_last_checkbox)

        self.merge_threshold_input = QSpinBox()
        self.merge_threshold_input.setRange(1, 3600)
        self.merge_threshold_input.setValue(10)
        self.merge_threshold_input.setSuffix("s")
        self.merge_threshold_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.merge_threshold_input.valueChanged.connect(self.update_segments_count)
        merge_layout.addWidget(self.merge_threshold_input)

        layout.addRow("Tùy chọn gộp:", merge_widget)

        # Global Trim (Batch)
        global_trim_widget = QWidget()
        global_trim_layout = QHBoxLayout(global_trim_widget)
        global_trim_layout.setContentsMargins(0, 0, 0, 0)
        global_trim_layout.setSpacing(8)

        from_lbl = QLabel("Từ:")
        from_lbl.setFixedWidth(28)
        global_trim_layout.addWidget(from_lbl)

        self.global_trim_start = QSpinBox()
        self.global_trim_start.setRange(0, 3600)
        self.global_trim_start.setValue(0)
        self.global_trim_start.setSuffix("s")
        self.global_trim_start.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.global_trim_start.setToolTip("Bắt đầu xử lý từ giây thứ N (các video chung).")
        global_trim_layout.addWidget(self.global_trim_start)

        tail_lbl = QLabel("Bỏ đuôi:")
        tail_lbl.setFixedWidth(50)
        global_trim_layout.addWidget(tail_lbl)

        self.global_trim_end = QSpinBox()
        self.global_trim_end.setRange(0, 3600)
        self.global_trim_end.setValue(0)
        self.global_trim_end.setSuffix("s")
        self.global_trim_end.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.global_trim_end.setToolTip("Cắt bỏ N giây phần cuối (các video chung).")
        global_trim_layout.addWidget(self.global_trim_end)

        layout.addRow("Cắt thời gian chung:", global_trim_widget)

        # Part settings
        part_group = QWidget()
        part_layout = QVBoxLayout(part_group)
        part_layout.setContentsMargins(0, 0, 0, 0)

        # Checkbox
        self.show_part_checkbox = QCheckBox("Hiển thị số phần")
        self.show_part_checkbox.setChecked(True)
        self.show_part_checkbox.toggled.connect(self.update_part_ui)
        self.show_part_checkbox.toggled.connect(self.update_preview)
        part_layout.addWidget(self.show_part_checkbox)

        # Container for part details
        self.part_details_container = QWidget()
        part_details_layout = QFormLayout(self.part_details_container)
        part_details_layout.setContentsMargins(10, 0, 0, 0)

        self.part_suffix = QLineEdit()
        self.part_suffix.setText("Part")
        self.part_suffix.textChanged.connect(self.update_preview_debounced)
        part_details_layout.addRow("Tiền tố:", self.part_suffix)

        self.part_position_combo = QComboBox()
        self.part_position_combo.addItem("Cùng dòng tiêu đề", "inline")
        self.part_position_combo.addItem("Dưới cùng", "bottom")
        self.part_position_combo.currentIndexChanged.connect(self.update_preview)
        part_details_layout.addRow("Vị trí:", self.part_position_combo)

        # Part Y position
        self.part_y_input = QSpinBox()
        self.part_y_input.setRange(0, 1920)
        self.part_y_input.setValue(1450)
        self.part_y_input.setSuffix(" px")
        self.part_y_input.valueChanged.connect(self.update_preview_debounced)
        part_details_layout.addRow("Vị trí Part (Y):", self.part_y_input)

        part_layout.addWidget(self.part_details_container)

        layout.addRow("Cấu hình Part:", part_group)

        # ── SCENE SPLIT ─────────────────────────────────────────────────────
        scene_sep = QLabel("\u2702 T\u00e1ch C\u1ea3nh (Scene Split):")
        scene_sep.setStyleSheet(
            "font-weight: 700; color: #a78bfa; font-size: 11px; "
            "margin-top: 6px; background: transparent; border: none;"
        )
        layout.addRow(scene_sep)

        scene_outer = QWidget()
        scene_outer_layout = QVBoxLayout(scene_outer)
        scene_outer_layout.setContentsMargins(0, 0, 0, 0)
        scene_outer_layout.setSpacing(6)

        # Checkbox enable
        self.scene_split_checkbox = QCheckBox("K\u00edch ho\u1ea1t t\u00e1ch c\u1ea3nh t\u1ef1 \u0111\u1ed9ng")
        self.scene_split_checkbox.setChecked(False)
        self.scene_split_checkbox.setToolTip(
            "Dùng engine phân tích cảnh đa phương pháp.\n"
            "Sau đó xóa ngẫu nhiên N% số cảnh tìm được."
        )
        scene_outer_layout.addWidget(self.scene_split_checkbox)

        # Detail container (hidden when unchecked)
        self.scene_split_details = QWidget()
        scene_detail_layout = QFormLayout(self.scene_split_details)
        scene_detail_layout.setContentsMargins(10, 0, 0, 0)
        scene_detail_layout.setSpacing(6)
        scene_detail_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # ── Method selector ──
        self.scene_method_combo = QComboBox()
        self.scene_method_combo.addItem("Hybrid  (Histogram + SSIM + Adaptive)", "hybrid")
        self.scene_method_combo.addItem("Histogram  (nhanh, phù hợp video phim)", "histogram")
        self.scene_method_combo.addItem("SSIM  (chính xác hơn, chậm hơn)", "ssim")
        self.scene_method_combo.addItem("FFmpeg scdet  (không cần OpenCV)", "ffmpeg")
        self.scene_method_combo.addItem("PySceneDetect  (ContentDetector)", "pyscene")
        self.scene_method_combo.setToolTip(
            "Chọn thuật toán phát hiện cảnh:\n"
            "• Hybrid   – Kết hợp Histogram + SSIM + Adaptive Threshold (khuyên dùng)\n"
            "• Histogram – So sánh histogram màu HSV giữa các frame\n"
            "• SSIM     – So sánh cấu trúc ảnh (Structural Similarity)\n"
            "• FFmpeg   – Dùng filter scdet của FFmpeg (fallback khi thiếu OpenCV)\n"
            "• PySceneDetect – ContentDetector của thư viện scenedetect"
        )
        self.scene_method_combo.currentIndexChanged.connect(self._on_scene_method_changed)
        scene_detail_layout.addRow("Ph\u01b0\u01a1ng ph\u00e1p:", self.scene_method_combo)

        # ── Threshold / Sensitivity ──
        self.scene_threshold_label_item = QLabel("Adaptive K (1\u20134):")
        self.scene_threshold_input = QDoubleSpinBox()
        self.scene_threshold_input.setRange(1.0, 4.0)
        self.scene_threshold_input.setValue(2.0)
        self.scene_threshold_input.setSingleStep(0.1)
        self.scene_threshold_input.setDecimals(1)
        self.scene_threshold_input.setToolTip(
            "Hybrid/Histogram/SSIM: Adaptive K — threshold = mean + K×std\n"
            "Cao = ít cảnh hơn (chỉ cắt mạnh), thấp = nhiều cảnh hơn.\n"
            "Khuyên: 1.5–2.5"
        )
        self.scene_threshold_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        scene_detail_layout.addRow(self.scene_threshold_label_item, self.scene_threshold_input)

        # ── Delete percent ──
        self.scene_delete_pct_input = QSpinBox()
        self.scene_delete_pct_input.setRange(0, 90)
        self.scene_delete_pct_input.setValue(30)
        self.scene_delete_pct_input.setSuffix("%")
        self.scene_delete_pct_input.setSingleStep(5)
        self.scene_delete_pct_input.setToolTip(
            "X\u00f3a ng\u1eabu nhi\u00ean bao nhi\u00eau % s\u1ed1 c\u1ea3nh t\u00ecm \u0111\u01b0\u1ee3c.\n"
            "0% = kh\u00f4ng x\u00f3a c\u1ea3nh n\u00e0o. 90% = x\u00f3a h\u1ea7u h\u1ebft."
        )
        self.scene_delete_pct_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        scene_detail_layout.addRow("X\u00f3a ng\u1eabu nhi\u00ean:", self.scene_delete_pct_input)

        # ── Min scene duration ──
        self.scene_min_dur_input = QDoubleSpinBox()
        self.scene_min_dur_input.setRange(0.1, 60.0)
        self.scene_min_dur_input.setValue(1.5)
        self.scene_min_dur_input.setSuffix("s")
        self.scene_min_dur_input.setSingleStep(0.5)
        self.scene_min_dur_input.setDecimals(1)
        self.scene_min_dur_input.setToolTip(
            "C\u1ea3nh ng\u1eafn h\u01a1n gi\u00e1 tr\u1ecb n\u00e0y s\u1ebd KH\u00d4NG b\u1ecb x\u00f3a.\n"
            "Gi\u00fap tr\u00e1nh m\u1ea5t c\u00e1c c\u1ea3nh qu\u00e1 ng\u1eafn."
        )
        self.scene_min_dur_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        scene_detail_layout.addRow("Th\u1eddi l\u01b0\u1ee3ng t\u1ed1i thi\u1ec3u:", self.scene_min_dur_input)

        # ── Analyze button + status ──
        analyze_row = QWidget()
        analyze_row_layout = QHBoxLayout(analyze_row)
        analyze_row_layout.setContentsMargins(0, 0, 0, 0)
        analyze_row_layout.setSpacing(8)

        self.scene_analyze_btn = QPushButton("\U0001f3ac Ph\u00e2n t\u00edch c\u1ea3nh")
        self.scene_analyze_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scene_analyze_btn.setToolTip(
            "Ch\u1ea1y ph\u00e2n t\u00edch c\u1ea3nh tr\u00ean video \u0111\u1ea7u ti\u00ean \u0111\u1ec3 xem tr\u01b0\u1edbc k\u1ebft qu\u1ea3.\n"
            "K\u1ebft qu\u1ea3 s\u1ebd \u0111\u01b0\u1ee3c d\u00f9ng khi nh\u1ea5n Start Processing."
        )
        self.scene_analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #6d28d9; }
            QPushButton:disabled { background-color: #4b5563; color: #9ca3af; }
        """)
        self.scene_analyze_btn.clicked.connect(self.run_scene_analysis_preview)
        analyze_row_layout.addWidget(self.scene_analyze_btn)
        analyze_row_layout.addStretch()
        scene_detail_layout.addRow("", analyze_row)

        self.scene_status_label = QLabel("Ch\u01b0a ph\u00e2n t\u00edch")
        self.scene_status_label.setStyleSheet(
            "color: #6b7280; font-size: 10px; font-style: italic; "
            "background: transparent; border: none;"
        )
        self.scene_status_label.setWordWrap(True)
        scene_detail_layout.addRow("", self.scene_status_label)

        scene_outer_layout.addWidget(self.scene_split_details)
        self.scene_split_details.setVisible(False)
        self.scene_split_checkbox.toggled.connect(self.scene_split_details.setVisible)

        layout.addRow("", scene_outer)
        # ── END SCENE SPLIT ──────────────────────────────────────────────────

        # ── TRANSITION / FADE ───────────────────────────────────────────────
        trans_sep = QLabel("✨ Hiệu ứng chuyển cảnh (Transitions):")
        trans_sep.setStyleSheet(
            "font-weight: 700; color: #38bdf8; font-size: 11px; "
            "margin-top: 6px; background: transparent; border: none;"
        )
        layout.addRow(trans_sep)

        trans_outer = QWidget()
        trans_outer_layout = QVBoxLayout(trans_outer)
        trans_outer_layout.setContentsMargins(0, 0, 0, 0)
        trans_outer_layout.setSpacing(6)

        self.fade_transition_checkbox = QCheckBox("Hiệu ứng mượt chuyển cảnh (Fade In/Out)")
        self.fade_transition_checkbox.setChecked(True)
        self.fade_transition_checkbox.setToolTip(
            "Tự động mờ dần hình ảnh và âm thanh (Fade In / Fade Out) khi nối các cảnh,\n"
            "giúp các đoạn cắt cảnh mượt mà tự nhiên, không bị giật hay gắt."
        )
        trans_outer_layout.addWidget(self.fade_transition_checkbox)

        self.fade_details_container = QWidget()
        fade_detail_layout = QFormLayout(self.fade_details_container)
        fade_detail_layout.setContentsMargins(10, 0, 0, 0)
        fade_detail_layout.setSpacing(6)

        self.fade_duration_input = QDoubleSpinBox()
        self.fade_duration_input.setRange(0.1, 2.0)
        self.fade_duration_input.setValue(0.3)
        self.fade_duration_input.setSingleStep(0.1)
        self.fade_duration_input.setDecimals(1)
        self.fade_duration_input.setSuffix(" giây")
        self.fade_duration_input.setToolTip("Thời lượng làm mượt (Fade) đầu và cuối mỗi cảnh (Khuyên dùng: 0.2s - 0.5s).")
        self.fade_duration_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        fade_detail_layout.addRow("Thời lượng Fade:", self.fade_duration_input)

        trans_outer_layout.addWidget(self.fade_details_container)
        self.fade_transition_checkbox.toggled.connect(self.fade_details_container.setVisible)

        layout.addRow("", trans_outer)
        # ── END TRANSITION ──────────────────────────────────────────────────

        # ── AUTO SUBTITLE ────────────────────────────────────────────────────
        sub_sep = QLabel("🎙 Auto Subtitle (Phụ đề tự động):")
        sub_sep.setStyleSheet(
            "font-weight: 700; color: #f59e0b; font-size: 11px; "
            "margin-top: 6px; background: transparent; border: none;"
        )
        layout.addRow(sub_sep)

        sub_outer = QWidget()
        sub_outer_layout = QVBoxLayout(sub_outer)
        sub_outer_layout.setContentsMargins(0, 0, 0, 0)
        sub_outer_layout.setSpacing(6)

        # Enable checkbox
        self.subtitle_enable_checkbox = QCheckBox("Kích hoạt Auto Subtitle (faster-whisper)")
        self.subtitle_enable_checkbox.setChecked(False)
        self.subtitle_enable_checkbox.setToolTip(
            "Tự động nhận diện giọng nói và tạo phụ đề đồng bộ.\n"
            "Yêu cầu: pip install faster-whisper\n"
            "Tự phát hiện ngôn ngữ (tiếng Việt, Anh, …)."
        )
        sub_outer_layout.addWidget(self.subtitle_enable_checkbox)

        # Detail container (collapsed when disabled)
        self.subtitle_details = QWidget()
        sub_detail_layout = QFormLayout(self.subtitle_details)
        sub_detail_layout.setContentsMargins(10, 0, 0, 0)
        sub_detail_layout.setSpacing(6)
        sub_detail_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Whisper model
        self.subtitle_model_combo = QComboBox()
        self.subtitle_model_combo.addItem("tiny  (nhanh nhất, kém chính xác)", "tiny")
        self.subtitle_model_combo.addItem("base  (cân bằng – khuyên dùng)", "base")
        self.subtitle_model_combo.addItem("small  (tốt hơn, chậm hơn)", "small")
        self.subtitle_model_combo.addItem("medium  (chính xác cao)", "medium")
        self.subtitle_model_combo.addItem("large-v3-turbo  (cực chuẩn + nhanh)", "large-v3-turbo")
        self.subtitle_model_combo.addItem("large-v3  (chính xác nhất, rất chậm)", "large-v3")
        self.subtitle_model_combo.setCurrentIndex(1)  # base
        self.subtitle_model_combo.setToolTip(
            "Model Whisper nhỏ hơn = nhanh hơn nhưng kém chính xác hơn.\n"
            "Khuyên dùng: base (đủ tốt cho tiếng Việt/Anh) hoặc large-v3-turbo."
        )
        sub_detail_layout.addRow("Whisper Model:", self.subtitle_model_combo)

        # Beam Search size
        beam_widget = QWidget()
        beam_row = QHBoxLayout(beam_widget)
        beam_row.setContentsMargins(0, 0, 0, 0)
        beam_row.setSpacing(6)
        self.subtitle_beam_size_spin = QSpinBox()
        self.subtitle_beam_size_spin.setRange(1, 10)
        self.subtitle_beam_size_spin.setValue(5)
        self.subtitle_beam_size_spin.setToolTip(
            "1 = Greedy search (nhanh hơn)\n"
            "5 = Beam Search (mặc định, chính xác hơn gấp nhiều lần)"
        )
        self.subtitle_beam_size_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        beam_row.addWidget(self.subtitle_beam_size_spin)
        sub_detail_layout.addRow("Beam Search:", beam_widget)

        # Context Prompt
        self.subtitle_initial_prompt_input = QLineEdit()
        self.subtitle_initial_prompt_input.setPlaceholderText("Ví dụ: Tiếng Việt chuẩn, tên riêng, từ vựng công nghệ...")
        self.subtitle_initial_prompt_input.setToolTip(
            "Cung cấp ngữ cảnh gợi ý cho Whisper AI (tên riêng, dấu câu, từ chuyên ngành)\n"
            "để AI ưu tiên nhận diện chuẩn xác nhất."
        )
        sub_detail_layout.addRow("Context Prompt:", self.subtitle_initial_prompt_input)

        # Font settings row
        sub_font_widget = QWidget()
        sub_font_layout = QHBoxLayout(sub_font_widget)
        sub_font_layout.setContentsMargins(0, 0, 0, 0)
        sub_font_layout.setSpacing(6)

        self.subtitle_font_name_input = QLineEdit()
        self.subtitle_font_name_input.setText("Arial")
        self.subtitle_font_name_input.setPlaceholderText("Font hỗ trợ Unicode...")
        self.subtitle_font_name_input.setToolTip(
            "Tên font hỗ trợ Unicode và tiếng Việt.\n"
            "Ví dụ: Arial, Oswald-Bold, Be Vietnam Pro\n"
            "Font phải được cài trong hệ thống hoặc trong thư mục fonts/."
        )
        sub_font_layout.addWidget(self.subtitle_font_name_input, 2)

        sub_font_layout.addWidget(QLabel("Size:"))
        self.subtitle_font_size_input = QSpinBox()
        self.subtitle_font_size_input.setRange(20, 200)
        self.subtitle_font_size_input.setValue(72)
        self.subtitle_font_size_input.setSuffix("pt")
        self.subtitle_font_size_input.setToolTip("Cỡ chữ subtitle. Khuyên dùng: 60-80 cho video 1080×1920.")
        self.subtitle_font_size_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_font_layout.addWidget(self.subtitle_font_size_input)
        sub_detail_layout.addRow("Font:", sub_font_widget)

        # Colors row
        sub_color_widget = QWidget()
        sub_color_layout = QHBoxLayout(sub_color_widget)
        sub_color_layout.setContentsMargins(0, 0, 0, 0)
        sub_color_layout.setSpacing(6)

        # Text color
        sub_color_layout.addWidget(QLabel("Chữ:"))
        self.subtitle_color_preview = QLabel()
        self.subtitle_color_preview.setFixedSize(24, 24)
        self.subtitle_color_preview.setStyleSheet(
            f"background-color: rgb{self._subtitle_color}; border: 1px solid #555; border-radius: 3px;"
        )
        sub_color_layout.addWidget(self.subtitle_color_preview)
        sub_color_btn = QPushButton("⚙️")
        sub_color_btn.setObjectName("colorButton")
        sub_color_btn.setFixedWidth(32)
        sub_color_btn.clicked.connect(self._pick_subtitle_color)
        sub_color_layout.addWidget(sub_color_btn)

        # Highlight color
        sub_color_layout.addWidget(QLabel("Highlight:"))
        self.subtitle_hl_color_preview = QLabel()
        self.subtitle_hl_color_preview.setFixedSize(24, 24)
        self.subtitle_hl_color_preview.setStyleSheet(
            f"background-color: rgb{self._subtitle_hl_color}; border: 1px solid #555; border-radius: 3px;"
        )
        sub_color_layout.addWidget(self.subtitle_hl_color_preview)
        sub_hl_btn = QPushButton("⚙️")
        sub_hl_btn.setObjectName("colorButton")
        sub_hl_btn.setFixedWidth(32)
        sub_hl_btn.clicked.connect(self._pick_subtitle_hl_color)
        sub_color_layout.addWidget(sub_hl_btn)
        sub_color_layout.addStretch()
        sub_detail_layout.addRow("Màu sắc:", sub_color_widget)

        # Outline / Shadow / Margin
        sub_style_widget = QWidget()
        sub_style_layout = QHBoxLayout(sub_style_widget)
        sub_style_layout.setContentsMargins(0, 0, 0, 0)
        sub_style_layout.setSpacing(6)

        sub_style_layout.addWidget(QLabel("Outline:"))
        self.subtitle_outline_input = QDoubleSpinBox()
        self.subtitle_outline_input.setRange(0.0, 10.0)
        self.subtitle_outline_input.setValue(3.0)
        self.subtitle_outline_input.setSingleStep(0.5)
        self.subtitle_outline_input.setDecimals(1)
        self.subtitle_outline_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_style_layout.addWidget(self.subtitle_outline_input)

        sub_style_layout.addWidget(QLabel("Shadow:"))
        self.subtitle_shadow_input = QDoubleSpinBox()
        self.subtitle_shadow_input.setRange(0.0, 10.0)
        self.subtitle_shadow_input.setValue(2.0)
        self.subtitle_shadow_input.setSingleStep(0.5)
        self.subtitle_shadow_input.setDecimals(1)
        self.subtitle_shadow_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_style_layout.addWidget(self.subtitle_shadow_input)

        sub_style_layout.addWidget(QLabel("Margin ↑:"))
        self.subtitle_margin_input = QSpinBox()
        self.subtitle_margin_input.setRange(0, 1920)
        self.subtitle_margin_input.setValue(120)
        self.subtitle_margin_input.setSuffix("px")
        self.subtitle_margin_input.setToolTip("Khoảng cách từ mép dưới màn hình (0 - 1920px). Tùy chỉnh vị trí phụ đề từ đáy lên đỉnh video.")
        self.subtitle_margin_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_style_layout.addWidget(self.subtitle_margin_input)
        sub_detail_layout.addRow("Style:", sub_style_widget)

        # Word highlight checkbox
        self.subtitle_word_hl_checkbox = QCheckBox("Word-level Highlight (từng từ đổi màu khi nói)")
        self.subtitle_word_hl_checkbox.setChecked(False)
        self.subtitle_word_hl_checkbox.setToolTip(
            "Từ đang được nói sẽ đổi màu sang màu Highlight.\n"
            "Yêu cầu FFmpeg được build với libass.\n"
            "Mặc định: TẮT (an toàn hơn cho mọi FFmpeg build)."
        )
        sub_detail_layout.addRow("", self.subtitle_word_hl_checkbox)

        # Max chars per line
        self.subtitle_max_chars_input = QSpinBox()
        self.subtitle_max_chars_input.setRange(10, 80)
        self.subtitle_max_chars_input.setValue(40)
        self.subtitle_max_chars_input.setToolTip(
            "Số ký tự tối đa trên mỗi dòng trước khi xuống dòng.\n"
            "Khuyên dùng: 35-45 cho video dọc 1080p."
        )
        self.subtitle_max_chars_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_detail_layout.addRow("Max ký tự/dòng:", self.subtitle_max_chars_input)

        # Max words per block
        self.subtitle_max_words_input = QSpinBox()
        self.subtitle_max_words_input.setRange(1, 30)
        self.subtitle_max_words_input.setValue(5)
        self.subtitle_max_words_input.setToolTip(
            "Số từ tối đa hiển thị trong 1 cụm subtitle.\n"
            "Khuyên dùng: 4-6 từ để câu thoại xuất hiện ngắn gọn, nhịp nhanh chuẩn TikTok/Shorts."
        )
        self.subtitle_max_words_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_detail_layout.addRow("Max từ/cụm:", self.subtitle_max_words_input)

        # Max lines per block
        self.subtitle_max_lines_input = QSpinBox()
        self.subtitle_max_lines_input.setRange(1, 3)
        self.subtitle_max_lines_input.setValue(1)
        self.subtitle_max_lines_input.setToolTip(
            "Số dòng tối đa hiển thị trong 1 cụm subtitle (Mặc định: 1 dòng)."
        )
        self.subtitle_max_lines_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_detail_layout.addRow("Max dòng/cụm:", self.subtitle_max_lines_input)

        # Test subtitle button
        sub_test_row = QWidget()
        sub_test_layout = QHBoxLayout(sub_test_row)
        sub_test_layout.setContentsMargins(0, 0, 0, 0)
        sub_test_layout.setSpacing(8)

        self.subtitle_test_btn = QPushButton("🔍 Test Subtitle (video đầu)")
        self.subtitle_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.subtitle_test_btn.setToolTip(
            "Chạy thử nhận diện giọng nói trên video đầu tiên.\n"
            "File ASS sẽ được tạo trong thư mục xuất/subtitles/.\n"
            "Không tạo video, chỉ kiểm tra kết quả subtitle."
        )
        self.subtitle_test_btn.setStyleSheet("""
            QPushButton {
                background-color: #d97706;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 5px 12px;
                font-weight: 600;
                font-size: 11px;
            }
            QPushButton:hover { background-color: #b45309; }
            QPushButton:disabled { background-color: #4b5563; color: #9ca3af; }
        """)
        self.subtitle_test_btn.clicked.connect(self._run_subtitle_test)
        sub_test_layout.addWidget(self.subtitle_test_btn)
        sub_test_layout.addStretch()
        sub_detail_layout.addRow("", sub_test_row)

        # Status label
        self.subtitle_status_label = QLabel("Chưa tạo subtitle")
        self.subtitle_status_label.setStyleSheet(
            "color: #6b7280; font-size: 10px; font-style: italic; "
            "background: transparent; border: none;"
        )
        self.subtitle_status_label.setWordWrap(True)
        sub_detail_layout.addRow("", self.subtitle_status_label)

        self.subtitle_details.setLayout(sub_detail_layout)
        sub_outer_layout.addWidget(self.subtitle_details)
        self.subtitle_details.setVisible(False)
        self.subtitle_enable_checkbox.toggled.connect(self.subtitle_details.setVisible)
        self.subtitle_enable_checkbox.toggled.connect(self._on_subtitle_toggled)
        self.subtitle_enable_checkbox.toggled.connect(self.update_preview_debounced)
        self.subtitle_font_name_input.textChanged.connect(self.update_preview_debounced)
        self.subtitle_font_size_input.valueChanged.connect(self.update_preview_debounced)
        self.subtitle_outline_input.valueChanged.connect(self.update_preview_debounced)
        self.subtitle_shadow_input.valueChanged.connect(self.update_preview_debounced)
        self.subtitle_margin_input.valueChanged.connect(self.update_preview_debounced)
        self.subtitle_max_chars_input.valueChanged.connect(self.update_preview_debounced)
        self.subtitle_max_words_input.valueChanged.connect(self.update_preview_debounced)
        self.subtitle_max_lines_input.valueChanged.connect(self.update_preview_debounced)

        layout.addRow("", sub_outer)
        # ── END AUTO SUBTITLE ────────────────────────────────────────────────

        # GPU - with auto-detection
        gpu_widget = QWidget()
        gpu_layout = QVBoxLayout(gpu_widget)
        gpu_layout.setContentsMargins(0, 0, 0, 0)
        gpu_layout.setSpacing(5)

        self.gpu_checkbox = QCheckBox("Sử dụng GPU (Hardware Acceleration)")
        self.gpu_checkbox.setChecked(True)
        gpu_layout.addWidget(self.gpu_checkbox)

        # GPU info label
        self.gpu_info_label = QLabel()
        self.gpu_info_label.setStyleSheet("color: #64748B; font-size: 8pt; font-style: italic; margin-left: 20px; background: transparent; border: none;")
        gpu_layout.addWidget(self.gpu_info_label)

        # Detect GPU on startup
        self.detect_and_display_gpu()

        layout.addRow("", gpu_widget)

        group.setLayout(layout)
        return group
    def create_style_group(self):
        group = QGroupBox("")
        layout = QGridLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 15, 10, 10)

        # Colors
        color_label = QLabel("Màu sắc & Nền:")
        color_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        layout.addWidget(color_label, 0, 0, 1, 3)

        # Blur background checkbox
        self.blur_bg_checkbox = QCheckBox("Làm mờ nền (Blur)")
        self.blur_bg_checkbox.setChecked(False)
        self.blur_bg_checkbox.toggled.connect(self.update_preview)
        layout.addWidget(self.blur_bg_checkbox, 1, 0, 1, 3)

        # Blur strength slider container (hidden by default, shown when blur is checked)
        self.blur_strength_container = QWidget()
        blur_strength_layout = QHBoxLayout(self.blur_strength_container)
        blur_strength_layout.setContentsMargins(20, 0, 0, 0) # Indent

        blur_strength_layout.addWidget(QLabel("Độ mờ:"))
        self.blur_strength_slider = QSlider(Qt.Orientation.Horizontal)
        self.blur_strength_slider.setRange(0, 100)
        self.blur_strength_slider.setValue(40)
        self.blur_strength_slider.valueChanged.connect(self.update_blur_strength_display)
        self.blur_strength_slider.sliderReleased.connect(self.update_preview) # Update preview on release
        blur_strength_layout.addWidget(self.blur_strength_slider)

        self.blur_strength_label = QLabel("40")
        self.blur_strength_label.setFixedWidth(30)
        blur_strength_layout.addWidget(self.blur_strength_label)

        layout.addWidget(self.blur_strength_container, 2, 0, 1, 3)
        self.blur_strength_container.setVisible(False)
        self.blur_bg_checkbox.toggled.connect(self.blur_strength_container.setVisible)

        # Background color
        self.bg_color_label_text = QLabel("Màu nền:")
        layout.addWidget(self.bg_color_label_text, 3, 0)

        self.bg_color_label = QLabel("")
        self.bg_color_label.setProperty("colorPreview", True)
        self.bg_color_label.setStyleSheet(f"background-color: rgb{self.bg_color};")
        layout.addWidget(self.bg_color_label, 3, 1)

        self.bg_btn = QPushButton("⚙️")
        self.bg_btn.setObjectName("colorButton")
        self.bg_btn.clicked.connect(self.select_bg_color)
        layout.addWidget(self.bg_btn, 3, 2)

        # Text background
        layout.addWidget(QLabel("Nền chữ:"), 4, 0)

        self.text_bg_label = QLabel("")
        self.text_bg_label.setProperty("colorPreview", True)
        self.text_bg_label.setStyleSheet(f"background-color: rgba{self.text_bg_color};")
        layout.addWidget(self.text_bg_label, 4, 1)

        text_bg_btn = QPushButton("⚙️")
        text_bg_btn.setObjectName("colorButton")
        text_bg_btn.clicked.connect(self.select_text_bg_color)
        layout.addWidget(text_bg_btn, 4, 2)

        # Text color
        layout.addWidget(QLabel("Màu chữ:"), 5, 0)

        self.text_color_label = QLabel("")
        self.text_color_label.setProperty("colorPreview", True)
        self.text_color_label.setStyleSheet(f"background-color: rgb{self.text_color};")
        layout.addWidget(self.text_color_label, 5, 1)

        text_color_btn = QPushButton("⚙️")
        text_color_btn.setObjectName("colorButton")
        text_color_btn.clicked.connect(self.select_text_color)
        layout.addWidget(text_color_btn, 5, 2)

        # Font
        font_label = QLabel("Font chữ:")
        font_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-top: 5px;")
        layout.addWidget(font_label, 6, 0, 1, 3)

        self.font_combo = QComboBox()
        self.load_fonts()
        self.font_combo.currentIndexChanged.connect(self.update_preview)
        layout.addWidget(self.font_combo, 7, 0, 1, 3)

        # Text border settings - VIỀN QUANH CHỮ
        text_border_label = QLabel("Viền chữ:")
        text_border_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-top: 10px;")
        layout.addWidget(text_border_label, 8, 0, 1, 3)

        # Text border color
        layout.addWidget(QLabel("Màu viền chữ:"), 9, 0)

        self.text_border_color_label = QLabel("")
        self.text_border_color_label.setProperty("colorPreview", True)
        self.text_border_color_label.setStyleSheet(f"background-color: rgb{self.text_border_color};")
        layout.addWidget(self.text_border_color_label, 9, 1)

        text_border_color_btn = QPushButton("⚙️")
        text_border_color_btn.setObjectName("colorButton")
        text_border_color_btn.clicked.connect(self.select_text_border_color)
        layout.addWidget(text_border_color_btn, 9, 2)

        # Text border width
        layout.addWidget(QLabel("Độ dày viền chữ:"), 10, 0)

        text_border_width_widget = QWidget()
        text_border_width_layout = QHBoxLayout(text_border_width_widget)
        text_border_width_layout.setContentsMargins(0, 0, 0, 0)

        self.text_border_width_slider = QSlider(Qt.Orientation.Horizontal)
        self.text_border_width_slider.setRange(0, 10)  # 0-10px cho viền chữ
        self.text_border_width_slider.setValue(0)
        self.text_border_width_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.text_border_width_slider.setTickInterval(1)
        self.text_border_width_slider.valueChanged.connect(self.update_text_border_width_display)
        text_border_width_layout.addWidget(self.text_border_width_slider, 2)

        self.text_border_width_label = QLabel("0px")
        self.text_border_width_label.setFixedWidth(40)
        self.text_border_width_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.text_border_width_label.setStyleSheet("font-weight: bold;")
        text_border_width_layout.addWidget(self.text_border_width_label)

        layout.addWidget(text_border_width_widget, 10, 1, 1, 2)

        # Trộn màu toàn bộ video (Color Overlay)
        overlay_label = QLabel("Phủ màu toàn video:")
        overlay_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-top: 10px;")
        layout.addWidget(overlay_label, 11, 0, 1, 3)

        layout.addWidget(QLabel("Màu lớp phủ:"), 12, 0)
        self.overlay_color_label = QLabel("")
        self.overlay_color_label.setProperty("colorPreview", True)
        self.overlay_color_label.setStyleSheet(f"background-color: rgb{self.overlay_color};")
        layout.addWidget(self.overlay_color_label, 12, 1)

        overlay_color_btn = QPushButton("⚙️")
        overlay_color_btn.setObjectName("colorButton")
        overlay_color_btn.clicked.connect(self.select_overlay_color)
        layout.addWidget(overlay_color_btn, 12, 2)

        layout.addWidget(QLabel("Độ mờ (%):"), 13, 0)
        overlay_opacity_widget = QWidget()
        overlay_opacity_layout = QHBoxLayout(overlay_opacity_widget)
        overlay_opacity_layout.setContentsMargins(0, 0, 0, 0)

        self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_opacity_slider.setRange(0, 100)
        self.overlay_opacity_slider.setValue(self.overlay_opacity)
        self.overlay_opacity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.overlay_opacity_slider.setTickInterval(10)
        self.overlay_opacity_slider.valueChanged.connect(self.update_overlay_opacity_display)
        self.overlay_opacity_slider.sliderReleased.connect(self.update_preview)
        overlay_opacity_layout.addWidget(self.overlay_opacity_slider, 2)

        self.overlay_opacity_label = QLabel(f"{self.overlay_opacity}%")
        self.overlay_opacity_label.setFixedWidth(40)
        self.overlay_opacity_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.overlay_opacity_label.setStyleSheet("font-weight: bold;")
        overlay_opacity_layout.addWidget(self.overlay_opacity_label)

        layout.addWidget(overlay_opacity_widget, 13, 1, 1, 2)

        # --- Save / Load Config buttons ---
        config_label = QLabel("Cấu hình:")
        config_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-top: 10px;")
        layout.addWidget(config_label, 14, 0, 1, 3)

        config_btn_widget = QWidget()
        config_btn_layout = QHBoxLayout(config_btn_widget)
        config_btn_layout.setContentsMargins(0, 0, 0, 0)
        config_btn_layout.setSpacing(8)

        save_cfg_btn = QPushButton("💾 Lưu cấu hình")
        save_cfg_btn.setObjectName("saveCfgButton")
        save_cfg_btn.setToolTip("Lưu tất cả thông số hiện tại (trừ nguồn video & thư mục xuất)")
        save_cfg_btn.setStyleSheet("""
            QPushButton {
                background-color: #4F46E5;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 6px 10px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #6366F1; }
            QPushButton:pressed { background-color: #4338CA; }
        """)
        save_cfg_btn.clicked.connect(self.save_config)
        config_btn_layout.addWidget(save_cfg_btn)

        load_cfg_btn = QPushButton("📂 Tải cấu hình")
        load_cfg_btn.setObjectName("loadCfgButton")
        load_cfg_btn.setToolTip("Tải lại cấu hình đã lưu")
        load_cfg_btn.setStyleSheet("""
            QPushButton {
                background-color: #F1F3F7;
                color: #4F46E5;
                border: 1px solid #CBD5E1;
                border-radius: 7px;
                padding: 6px 10px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #E8EBF2;
                border-color: #6366F1;
            }
            QPushButton:pressed { background-color: #E2E8F0; }
        """)
        load_cfg_btn.clicked.connect(self.load_config)
        config_btn_layout.addWidget(load_cfg_btn)

        layout.addWidget(config_btn_widget, 15, 0, 1, 3)

        group.setLayout(layout)
        return group

    def update_overlay_opacity_display(self, value):
        self.overlay_opacity = value
        self.overlay_opacity_label.setText(f"{value}%")

    def select_overlay_color(self):
        color = QColorDialog.getColor(QColor(*self.overlay_color))
        if color.isValid():
            self.overlay_color = (color.red(), color.green(), color.blue())
            self.overlay_color_label.setStyleSheet(f"background-color: rgb{self.overlay_color};")
            self.log(f"Đã chọn màu lớp phủ: RGB{self.overlay_color}")
            if self.current_video_path:
                self.update_preview()

    def update_blur_strength_display(self, value):
        self.blur_strength_label.setText(str(value))

    # ── Config Save / Load ────────────────────────────────────────────────────

    def _get_config_path(self):
        """Trả về đường dẫn file config JSON (ngang hàng với exe khi đã build)"""
        import sys
        if getattr(sys, "frozen", False):
            # Đang chạy từ file .exe (PyInstaller) → lưu cạnh exe
            base = Path(sys.executable).parent / "settings"
        else:
            # Đang chạy trong môi trường dev
            base = Path(__file__).parent.parent / "settings"
        base.mkdir(parents=True, exist_ok=True)
        return base / "autocut_config.json"

    def save_config(self):
        """Lưu tất cả thông số (trừ chế độ xử lý, nguồn video, xuất video) vào JSON"""
        import json
        reply = QMessageBox.question(
            self,
            "Xác nhận lưu cấu hình",
            "Bạn có chắc muốn lưu cấu hình hiện tại?\n"
            "(Cấu hình cũ sẽ bị ghi đè)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        config = {
            # Tốc độ & cắt
            "speed": self.speed_input.value(),
            "segment_duration": self.segment_input.value(),
            "merge_last": self.merge_last_checkbox.isChecked(),
            "merge_threshold": self.merge_threshold_input.value(),
            "global_trim_start": self.global_trim_start.value(),
            "global_trim_end": self.global_trim_end.value(),
            # Part
            "show_part": self.show_part_checkbox.isChecked(),
            "part_suffix": self.part_suffix.text(),
            "part_position": self.part_position_combo.currentData(),
            "part_y": self.part_y_input.value(),
            # Vị trí tiêu đề
            "title_y": self.title_y_input.value(),
            # GPU
            "use_gpu": self.gpu_checkbox.isChecked(),
            # Màu sắc
            "bg_color": list(self.bg_color),
            "text_bg_color": list(self.text_bg_color),
            "text_color": list(self.text_color),
            "text_border_color": list(self.text_border_color),
            "text_border_width": self.text_border_width_slider.value(),
            "overlay_color": list(self.overlay_color),
            "overlay_opacity": self.overlay_opacity_slider.value(),
            # Blur
            "blur_background": self.blur_bg_checkbox.isChecked(),
            "blur_strength": self.blur_strength_slider.value(),
            # Zoom
            "width_scale": self.width_scale_input.value(),
            "height_scale": self.height_scale_input.value(),
            # Font
            "font_index": self.font_combo.currentIndex(),
            # Auto Subtitle
            "subtitle_enabled": self.subtitle_enable_checkbox.isChecked() if hasattr(self, 'subtitle_enable_checkbox') else False,
            "subtitle_model": self.subtitle_model_combo.currentData() if hasattr(self, 'subtitle_model_combo') else "base",
            "subtitle_beam_size": self.subtitle_beam_size_spin.value() if hasattr(self, 'subtitle_beam_size_spin') else 5,
            "subtitle_initial_prompt": self.subtitle_initial_prompt_input.text() if hasattr(self, 'subtitle_initial_prompt_input') else "",
            "subtitle_font_name": self.subtitle_font_name_input.text() if hasattr(self, 'subtitle_font_name_input') else "Arial",
            "subtitle_font_size": self.subtitle_font_size_input.value() if hasattr(self, 'subtitle_font_size_input') else 72,
            "subtitle_outline": self.subtitle_outline_input.value() if hasattr(self, 'subtitle_outline_input') else 3.0,
            "subtitle_shadow": self.subtitle_shadow_input.value() if hasattr(self, 'subtitle_shadow_input') else 2.0,
            "subtitle_margin_v": self.subtitle_margin_input.value() if hasattr(self, 'subtitle_margin_input') else 120,
            "subtitle_max_chars": self.subtitle_max_chars_input.value() if hasattr(self, 'subtitle_max_chars_input') else 40,
            "subtitle_max_words": self.subtitle_max_words_input.value() if hasattr(self, 'subtitle_max_words_input') else 5,
            "subtitle_max_lines": self.subtitle_max_lines_input.value() if hasattr(self, 'subtitle_max_lines_input') else 1,
            "subtitle_word_hl": self.subtitle_word_hl_checkbox.isChecked() if hasattr(self, 'subtitle_word_hl_checkbox') else False,
            "subtitle_color": list(self._subtitle_color),
            "subtitle_hl_color": list(self._subtitle_hl_color),
        }
        try:
            path = self._get_config_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self.log(f"✅ Đã lưu cấu hình vào: {path}")
        except Exception as e:
            self.log(f"❌ Lỗi lưu cấu hình: {e}")

    def load_config(self, silent=False):
        """Tải cấu hình từ JSON và áp dụng lên UI"""
        import json
        path = self._get_config_path()
        if not path.exists():
            if not silent:
                self.log("⚠️ Chưa có file cấu hình nào được lưu.")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            # Tốc độ & cắt
            self.speed_input.setValue(cfg.get("speed", 1.0))
            self.segment_input.setValue(cfg.get("segment_duration", 0))
            self.merge_last_checkbox.setChecked(cfg.get("merge_last", False))
            self.merge_threshold_input.setValue(cfg.get("merge_threshold", 10))
            self.global_trim_start.setValue(cfg.get("global_trim_start", 0))
            self.global_trim_end.setValue(cfg.get("global_trim_end", 0))
            # Part
            self.show_part_checkbox.setChecked(cfg.get("show_part", True))
            self.part_suffix.setText(cfg.get("part_suffix", "Part"))
            pos_data = cfg.get("part_position", "inline")
            idx = self.part_position_combo.findData(pos_data)
            if idx >= 0:
                self.part_position_combo.setCurrentIndex(idx)
            self.part_y_input.setValue(cfg.get("part_y", 1450))
            # Vị trí tiêu đề
            self.title_y_input.setValue(cfg.get("title_y", 250))
            # GPU
            self.gpu_checkbox.setChecked(cfg.get("use_gpu", True))
            # Màu sắc
            if "bg_color" in cfg:
                self.bg_color = tuple(cfg["bg_color"])
                self.bg_color_label.setStyleSheet(f"background-color: rgb{self.bg_color};")
            if "text_bg_color" in cfg:
                self.text_bg_color = tuple(cfg["text_bg_color"])
                self.text_bg_label.setStyleSheet(f"background-color: rgba{self.text_bg_color};")
            if "text_color" in cfg:
                self.text_color = tuple(cfg["text_color"])
                self.text_color_label.setStyleSheet(f"background-color: rgb{self.text_color};")
            if "text_border_color" in cfg:
                self.text_border_color = tuple(cfg["text_border_color"])
                self.text_border_color_label.setStyleSheet(f"background-color: rgb{self.text_border_color};")
            self.text_border_width_slider.setValue(cfg.get("text_border_width", 0))
            if "overlay_color" in cfg:
                self.overlay_color = tuple(cfg["overlay_color"])
                self.overlay_color_label.setStyleSheet(f"background-color: rgb{self.overlay_color};")
            self.overlay_opacity_slider.setValue(cfg.get("overlay_opacity", 0))
            # Blur
            self.blur_bg_checkbox.setChecked(cfg.get("blur_background", False))
            self.blur_strength_slider.setValue(cfg.get("blur_strength", 40))
            # Zoom
            self.width_scale_input.setValue(cfg.get("width_scale", 1.0))
            self.height_scale_input.setValue(cfg.get("height_scale", 1.0))
            # Font
            font_idx = cfg.get("font_index", 0)
            if 0 <= font_idx < self.font_combo.count():
                self.font_combo.setCurrentIndex(font_idx)

            # Auto Subtitle
            if hasattr(self, 'subtitle_enable_checkbox'):
                self.subtitle_enable_checkbox.setChecked(cfg.get("subtitle_enabled", False))
            if hasattr(self, 'subtitle_model_combo'):
                model_val = cfg.get("subtitle_model", "base")
                idx_m = self.subtitle_model_combo.findData(model_val)
                if idx_m >= 0:
                    self.subtitle_model_combo.setCurrentIndex(idx_m)
            if hasattr(self, 'subtitle_beam_size_spin'):
                self.subtitle_beam_size_spin.setValue(cfg.get("subtitle_beam_size", 5))
            if hasattr(self, 'subtitle_initial_prompt_input'):
                self.subtitle_initial_prompt_input.setText(cfg.get("subtitle_initial_prompt", ""))
            if hasattr(self, 'subtitle_font_name_input'):
                self.subtitle_font_name_input.setText(cfg.get("subtitle_font_name", "Arial"))
            if hasattr(self, 'subtitle_font_size_input'):
                self.subtitle_font_size_input.setValue(cfg.get("subtitle_font_size", 72))
            if hasattr(self, 'subtitle_outline_input'):
                self.subtitle_outline_input.setValue(cfg.get("subtitle_outline", 3.0))
            if hasattr(self, 'subtitle_shadow_input'):
                self.subtitle_shadow_input.setValue(cfg.get("subtitle_shadow", 2.0))
            if hasattr(self, 'subtitle_margin_input'):
                self.subtitle_margin_input.setValue(cfg.get("subtitle_margin_v", 120))
            if hasattr(self, 'subtitle_max_chars_input'):
                self.subtitle_max_chars_input.setValue(cfg.get("subtitle_max_chars", 40))
            if hasattr(self, 'subtitle_max_words_input'):
                self.subtitle_max_words_input.setValue(cfg.get("subtitle_max_words", 5))
            if hasattr(self, 'subtitle_max_lines_input'):
                self.subtitle_max_lines_input.setValue(cfg.get("subtitle_max_lines", 1))
            if hasattr(self, 'subtitle_word_hl_checkbox'):
                self.subtitle_word_hl_checkbox.setChecked(cfg.get("subtitle_word_hl", False))
            if "subtitle_color" in cfg:
                self._subtitle_color = tuple(cfg["subtitle_color"])
                if hasattr(self, 'subtitle_color_preview'):
                    self.subtitle_color_preview.setStyleSheet(
                        f"background-color: rgb{self._subtitle_color}; border: 1px solid #555; border-radius: 3px;"
                    )
            if "subtitle_hl_color" in cfg:
                self._subtitle_hl_color = tuple(cfg["subtitle_hl_color"])
                if hasattr(self, 'subtitle_hl_color_preview'):
                    self.subtitle_hl_color_preview.setStyleSheet(
                        f"background-color: rgb{self._subtitle_hl_color}; border: 1px solid #555; border-radius: 3px;"
                    )

            if not silent:
                self.log(f"✅ Đã tải cấu hình từ: {path}")
        except Exception as e:
            if not silent:
                self.log(f"❌ Lỗi tải cấu hình: {e}")

    # ── End Config ────────────────────────────────────────────────────────────

    def update_part_ui(self):
        """Ẩn/hiện cấu hình part"""
        is_checked = self.show_part_checkbox.isChecked()
        self.part_details_container.setVisible(is_checked)

    def detect_and_display_gpu(self):
        """Phát hiện và hiển thị thông tin GPU"""
        gpu_info = detect_gpu_encoder()
        if gpu_info:
            # gpu_info là dict: {'encoder': ..., 'preset_args': ..., 'hwaccel_args': ..., ...}
            encoder_name = gpu_info['encoder']
            gpu_names = {
                'h264_nvenc': '✅ NVIDIA NVENC (CUDA)',
                'h264_amf': '✅ AMD AMF',
                'h264_qsv': '✅ Intel QSV',
                'h264_videotoolbox': '✅ Apple VideoToolbox'
            }
            display_name = gpu_names.get(encoder_name, f'✅ {encoder_name}')
            hw = ' '.join(gpu_info.get('hwaccel_args', []))
            hw_label = f" | hw: {hw}" if hw else ""
            self.gpu_info_label.setText(f"Đã phát hiện: {display_name}{hw_label}")
            self.gpu_info_label.setStyleSheet("color: #27ae60; font-size: 8pt; font-weight: 500; margin-left: 20px;")
        else:
            self.gpu_info_label.setText("⚠️ Không tìm thấy GPU, sẽ sử dụng CPU (libx264)")
            self.gpu_info_label.setStyleSheet("color: #e67e22; font-size: 8pt; font-style: italic; margin-left: 20px;")
            # Tự động tắt GPU checkbox nếu không có GPU
            self.gpu_checkbox.setChecked(False)


    def create_info_group(self):
        group = QGroupBox("")
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 15, 10, 10)

        # Duration
        duration_widget = QWidget()
        duration_layout = QHBoxLayout(duration_widget)
        duration_layout.setContentsMargins(0, 0, 0, 0)

        duration_label = QLabel("Thời gian làm việc:")
        duration_label.setStyleSheet("font-weight: bold;")
        duration_layout.addWidget(duration_label)

        self.duration_display = QLabel("00:00:00")
        self.duration_display.setStyleSheet("""
            font-weight: 700;
            color: #34D399;
            background-color: rgba(16,185,129,0.1);
            border: 1px solid rgba(16,185,129,0.2);
            border-radius: 5px;
            padding: 3px 10px;
        """)
        duration_layout.addWidget(self.duration_display)
        duration_layout.addStretch()

        layout.addWidget(duration_widget)

        # Segments
        segments_widget = QWidget()
        segments_layout = QHBoxLayout(segments_widget)
        segments_layout.setContentsMargins(0, 0, 0, 0)

        segments_label = QLabel("Số video ước tính:")
        segments_label.setStyleSheet("font-weight: bold;")
        segments_layout.addWidget(segments_label)

        self.segments_count = QLabel("1")
        self.segments_count.setStyleSheet("""
            font-weight: 700;
            color: #F87171;
            min-width: 24px;
            qproperty-alignment: AlignCenter;
        """)
        segments_layout.addWidget(self.segments_count)
        segments_layout.addStretch()

        layout.addWidget(segments_widget)

        # Last Segment Duration
        last_segment_widget = QWidget()
        last_segment_layout = QHBoxLayout(last_segment_widget)
        last_segment_layout.setContentsMargins(0, 0, 0, 0)

        last_segment_label = QLabel("Thời lượng video cuối:")
        last_segment_label.setStyleSheet("font-weight: bold;")
        last_segment_layout.addWidget(last_segment_label)

        self.last_segment_duration_display = QLabel("00:00:00")
        self.last_segment_duration_display.setStyleSheet("""
            font-weight: 700;
            color: #A78BFA;
            min-width: 24px;
            qproperty-alignment: AlignCenter;
        """)
        last_segment_layout.addWidget(self.last_segment_duration_display)
        last_segment_layout.addStretch()

        layout.addWidget(last_segment_widget)

        # Skip count
        skip_widget = QWidget()
        skip_layout = QHBoxLayout(skip_widget)
        skip_layout.setContentsMargins(0, 0, 0, 0)

        skip_label = QLabel("Số đoạn bỏ qua:")
        skip_label.setStyleSheet("font-weight: bold;")
        skip_layout.addWidget(skip_label)

        self.skip_count = QLabel("0")
        self.skip_count.setStyleSheet("""
            font-weight: 700;
            color: #FCD34D;
            min-width: 24px;
            qproperty-alignment: AlignCenter;
        """)
        skip_layout.addWidget(self.skip_count)
        skip_layout.addStretch()

        layout.addWidget(skip_widget)

        # Text border info
        text_border_widget = QWidget()
        text_border_layout = QHBoxLayout(text_border_widget)
        text_border_layout.setContentsMargins(0, 0, 0, 0)

        text_border_info_label = QLabel("Viền chữ:")
        text_border_info_label.setStyleSheet("font-weight: bold;")
        text_border_layout.addWidget(text_border_info_label)

        self.text_border_info = QLabel("Không có")
        self.text_border_info.setStyleSheet("""
            font-weight: 700;
            color: #818CF8;
            background-color: rgba(99,102,241,0.1);
            border: 1px solid rgba(99,102,241,0.2);
            border-radius: 5px;
            padding: 3px 10px;
        """)
        text_border_layout.addWidget(self.text_border_info)
        text_border_layout.addStretch()

        layout.addWidget(text_border_widget)

        # Status
        self.status_display = QLabel("🟢 Sẵn sàng")
        self.status_display.setStyleSheet("""
            font-weight: 600;
            color: #34D399;
            background-color: rgba(16,185,129,0.1);
            border: 1px solid rgba(16,185,129,0.2);
            border-radius: 6px;
            padding: 8px 12px;
            margin-top: 4px;
            qproperty-alignment: AlignCenter;
        """)
        layout.addWidget(self.status_display)

        # Zoom controls
        zoom_label = QLabel("Zoom Video (Scale):")
        zoom_label.setStyleSheet("font-weight: 700; color: #CBD5E1; margin-top: 8px; background: transparent; border: none;")
        layout.addWidget(zoom_label)

        zoom_widget = QWidget()
        zoom_layout = QHBoxLayout(zoom_widget)
        zoom_layout.setContentsMargins(0, 0, 0, 0)

        zoom_layout.addWidget(QLabel("Width:"))
        self.width_scale_input = QDoubleSpinBox()
        self.width_scale_input.setRange(0.1, 3.0)
        self.width_scale_input.setValue(1.0)
        self.width_scale_input.setSingleStep(0.05)
        self.width_scale_input.setSuffix("x")
        self.width_scale_input.valueChanged.connect(self.update_preview_debounced)
        zoom_layout.addWidget(self.width_scale_input)

        zoom_layout.addWidget(QLabel("Height:"))
        self.height_scale_input = QDoubleSpinBox()
        self.height_scale_input.setRange(0.1, 3.0)
        self.height_scale_input.setValue(1.0)
        self.height_scale_input.setSingleStep(0.05)
        self.height_scale_input.setSuffix("x")
        self.height_scale_input.valueChanged.connect(self.update_preview_debounced)
        zoom_layout.addWidget(self.height_scale_input)

        layout.addWidget(zoom_widget)

        # Preview info
        self.preview_info = QLabel("Chưa có video")
        self.preview_info.setStyleSheet("""
            color: #7f8c8d;
            font-size: 8pt;
            font-style: italic;
            margin-top: 5px;
            qproperty-alignment: AlignCenter;
        """)
        layout.addWidget(self.preview_info)

        # Preview container with magnifying glass button
        preview_header_widget = QWidget()
        preview_header_layout = QHBoxLayout(preview_header_widget)
        preview_header_layout.setContentsMargins(0, 0, 0, 0)
        preview_header_layout.setSpacing(10)

        preview_label = QLabel("Video Preview (9:16):")
        preview_label.setStyleSheet("font-weight: bold; color: #2c3e50; margin-top: 10px;")
        preview_header_layout.addWidget(preview_label)

        # Magnifying glass button
        self.magnify_btn = QPushButton("🔍")
        self.magnify_btn.setToolTip("Xem preview ở kích thước lớn hơn")
        self.magnify_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 3px;
                padding: 2px 6px;
                font-size: 11pt;
                min-width: 28px;
                max-width: 28px;
                min-height: 24px;
                max-height: 24px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.magnify_btn.clicked.connect(self.show_preview_popup)
        self.magnify_btn.setEnabled(False)  # Disabled until preview is available
        preview_header_layout.addWidget(self.magnify_btn)

        preview_header_layout.addStretch()
        layout.addWidget(preview_header_widget)

        # Tạo QLabel để hiển thị thumbnail (DraggablePreviewLabel hỗ trợ kéo thả vị trí subtitle)
        self.preview_label = DraggablePreviewLabel()
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setMinimumHeight(240)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setText("Chưa có video")
        self.preview_label.setToolTip("Kéo thả trên khung preview để điều chỉnh vị trí Subtitle (Margin Bottom)")
        self.preview_label.position_changed.connect(self._on_preview_position_dragged)
        self.preview_label.setStyleSheet("""
            QLabel {
                color: #7f8c8d;
                font-style: italic;
                font-size: 10pt;
                background-color: #2c3e50;
                border: 2px solid #34495e;
                border-radius: 8px;
                min-height: 320px;
                max-height: 320px;
                qproperty-alignment: AlignCenter;
            }
        """)
        layout.addWidget(self.preview_label)

        # Control buttons
        control_widget = QWidget()
        control_layout = QHBoxLayout(control_widget)
        control_layout.setContentsMargins(0, 10, 0, 0)
        control_layout.setSpacing(10)

        self.process_btn = QPushButton("▶️ Start Processing")
        self.process_btn.setObjectName("processButton")
        self.process_btn.setToolTip("Bắt đầu xử lý video với các cài đặt hiện tại")
        self.process_btn.setFixedHeight(50)
        self.process_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                background-color: #27ae60;
                color: white;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2ecc71;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.process_btn.clicked.connect(self.start_processing)
        control_layout.addWidget(self.process_btn)

        self.stop_btn = QPushButton("⏹️ Stop Processing")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.setToolTip("Dừng quá trình xử lý đang chạy")
        self.stop_btn.setFixedHeight(50)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                background-color: #c0392b;
                color: white;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e74c3c;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
            }
        """)
        self.stop_btn.clicked.connect(self.stop_processing)
        self.stop_btn.setEnabled(False)
        control_layout.addWidget(self.stop_btn)

        layout.addWidget(control_widget)

        # Setup debounce timer
        self.debounce_timer = QTimer()
        self.debounce_timer.setSingleShot(True)
        self.debounce_timer.setInterval(800) # 800ms debounce
        self.debounce_timer.timeout.connect(self.update_preview)

        layout.addStretch()
        group.setLayout(layout)
        return group

    def update_preview_debounced(self):
        """Debounce update_preview calls to avoid lag"""
        self.debounce_timer.start()

    def create_footer(self, parent_layout):
        """Tạo footer với progress và log"""
        # Progress area - chỉ giữ phần progress, không có nút Start nữa
        progress_widget = QWidget()
        progress_layout = QHBoxLayout(progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)

        self.progress_label = QLabel("Sẵn sàng")
        self.progress_label.setWordWrap(True)
        self.progress_label.setStyleSheet("color: #7f8c8d; font-size: 9pt;")
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        progress_layout.addWidget(self.progress_bar, 1)

        parent_layout.addWidget(progress_widget)

        # Log — removed (routed to global Process Log via signal)


    def load_fonts(self):
        self.font_combo.addItem("Arial (mặc định)", "")
        fonts_dir = EXE_DIR / "fonts"
        if fonts_dir.exists():
            for font_file in fonts_dir.glob("*.ttf"):
                self.font_combo.addItem(font_file.stem, str(font_file))
            for font_file in fonts_dir.glob("*.otf"):
                self.font_combo.addItem(font_file.stem, str(font_file))
        
        # Set Oswald-Medium as default
        index = self.font_combo.findText("Oswald-Medium")
        if index >= 0:
            self.font_combo.setCurrentIndex(index)

    def time_to_seconds(self, qtime):
        return qtime.hour() * 3600 + qtime.minute() * 60 + qtime.second()

    def seconds_to_qtime(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return QTime(hours, minutes, secs)

    def format_time(self, seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def calculate_work_duration(self):
        """Tính thời gian làm việc thực tế cho Video hiển thị chung"""
        if not hasattr(self, 'video_item_widgets') or len(self.video_item_widgets) == 0:
            return 0
            
        widget = self.video_item_widgets[0]
        try:
            start_sec, end_sec = widget.get_cut_times()
            skip_ranges = widget.get_skip_ranges()
        except:
            return 0

        total_duration = max(0, end_sec - start_sec)
        skip_ranges.sort(key=lambda x: x[0])

        current_start = start_sec
        current_end = end_sec

        for skip_start, skip_end in skip_ranges:
            if skip_end <= current_start or skip_start >= current_end:
                continue

            effective_skip_start = max(skip_start, current_start)
            effective_skip_end = min(skip_end, current_end)

            if effective_skip_start > current_start:
                total_duration -= (effective_skip_end - effective_skip_start)

            current_start = effective_skip_end
            if current_start >= current_end:
                break

        return max(0, total_duration)

    def update_duration_display(self):
        """Cập nhật hiển thị thời gian khi thay đổi các tham số"""
        # Tính thời gian làm việc theo video gốc
        work_duration = self.calculate_work_duration()

        # Áp dụng speed
        speed = self.speed_input.value()
        if speed > 0:
            adjusted_duration = work_duration / speed
        else:
            adjusted_duration = work_duration

        # Cập nhật hiển thị
        self.duration_display.setText(self.format_time(adjusted_duration))

        # Cập nhật số segment
        self.update_segments_count()

    def update_segments_count(self):
        """Cập nhật số lượng video segment ước tính"""
        total_segments = 0
        last_duration = 0
        
        if hasattr(self, 'video_item_widgets') and self.video_item_widgets:
            speed = self.speed_input.value()
            segment_sec = self.segment_input.value()
            global_start = self.global_trim_start.value() if hasattr(self, 'global_trim_start') else 0
            global_end = self.global_trim_end.value() if hasattr(self, 'global_trim_end') else 0
            merge_last = self.merge_last_checkbox.isChecked()
            merge_threshold = self.merge_threshold_input.value()
            
            for w in self.video_item_widgets:
                w.update_stats(speed, segment_sec, global_start, global_end, merge_last, merge_threshold)
                if hasattr(w, 'calculated_segments'):
                    total_segments += w.calculated_segments
                if hasattr(w, 'calculated_last_duration') and w.calculated_last_duration > 0:
                    last_duration = w.calculated_last_duration
                    
        if hasattr(self, 'segments_count'):
            self.segments_count.setText(str(max(0, total_segments)))
        if hasattr(self, 'last_segment_duration_display'):
            self.last_segment_duration_display.setText(self.format_time(last_duration))

    def update_preview(self):
        """Cập nhật preview khi thay đổi zoom - scale riêng width/height như CapCut"""
        self.width_scale = self.width_scale_input.value()
        self.height_scale = self.height_scale_input.value()

        # Nếu có video, tạo thumbnail và cập nhật preview
        if self.current_video_path and os.path.exists(self.current_video_path):
            try:
                # Lấy kích thước video gốc
                cmd_probe = [
                    FFPROBE_EXE,
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height',
                    '-of', 'csv=p=0',
                    self.current_video_path
                ]
                result = run_ffmpeg_silent(cmd_probe)
                self.original_video_width, self.original_video_height = map(int, result.stdout.strip().split(','))

                # Scale video để fit vào 1080 width (giữ tỷ lệ)
                max_width = 1080
                if self.original_video_width > max_width:
                    fit_scale = max_width / self.original_video_width
                    fit_width = max_width
                    fit_height = int(self.original_video_height * fit_scale)
                else:
                    fit_width = self.original_video_width
                    fit_height = self.original_video_height

                # Áp dụng scale RIÊNG CHO width và height (KHÔNG giữ tỷ lệ - giống CapCut)
                final_width = int(fit_width * self.width_scale)
                final_height = int(fit_height * self.height_scale)

                # Cập nhật thông tin kích thước
                self.preview_info.setText(f"Gốc: {self.original_video_width}×{self.original_video_height} | Zoom: {final_width}×{final_height}")

                # Tạo thumbnail tạm thời
                temp_dir = os.path.join(os.path.dirname(self.current_video_path), "temp_preview")
                os.makedirs(temp_dir, exist_ok=True)
                temp_thumbnail = os.path.join(temp_dir, "preview_thumbnail.jpg")

                # Lấy màu nền hiện tại
                bg_hex = f"0x{self.bg_color[0]:02x}{self.bg_color[1]:02x}{self.bg_color[2]:02x}"

                # Tính toán vị trí overlay - video nằm giữa khung 1080x1920
                overlay_x = (1080 - final_width) // 2
                overlay_y = (1920 - final_height) // 2

                # Tạo filter cho preview
                if self.blur_bg_checkbox.isChecked():
                    blur_strength = self.blur_strength_slider.value()
                    eff_blur = max(1, blur_strength / 4)
                    filter_complex = (
                        f"[0:v]split=2[fg_source][bg_source];"
                        f"[bg_source]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur={eff_blur}:3,scale=1080:1920[bg_blurred];"
                        f"[fg_source]scale={final_width}:{final_height}:flags=lanczos[scaled];"
                        f"[bg_blurred][scaled]overlay={overlay_x}:{overlay_y}[base];"
                    )
                else:
                    filter_complex = (
                        f"[0:v]scale={final_width}:{final_height}:flags=lanczos[scaled];"
                        f"color=c={bg_hex}:s=1080x1920:d=1[bg];"
                        f"[bg][scaled]overlay={overlay_x}:{overlay_y}[base];"
                    )

                # Tạo overlay text tạm thời
                temp_overlay = os.path.join(temp_dir, "preview_overlay.png")

                # Tạo dummy thread instance để dùng hàm create_overlay_image
                dummy_thread = VideoProcessThread(
                    "", "", "", 1.0, 0, False, "", (0,0,0),
                    self.text_bg_color, self.text_color,
                    self.font_combo.currentData(), 0, 0, [],
                    original_video_width=self.original_video_width,
                    original_video_height=self.original_video_height,
                    text_border_color=self.text_border_color,
                    text_border_width=self.text_border_width,
                    blur_background=self.blur_bg_checkbox.isChecked(),
                    blur_strength=self.blur_strength_slider.value(),
                    show_part=self.show_part_checkbox.isChecked(),
                    part_position=self.part_position_combo.currentData(),
                    title_y=self.title_y_input.value(),
                    part_y=self.part_y_input.value(),

                    merge_last_segment=False,
                    merge_threshold=0,
                    overlay_color=self.overlay_color,
                    overlay_opacity=self.overlay_opacity
                )

                # Lấy title từ Box video hiện hành
                current_preview_title = Path(self.current_video_path).stem
                if hasattr(self, 'video_item_widgets'):
                    for w in self.video_item_widgets:
                        if w.path == self.current_video_path:
                            current_preview_title = w.title_input.text()
                            break

                part_text = f"{self.part_suffix.text()} 1" if self.show_part_checkbox.isChecked() else ""
                
                sub_preview_kwargs = {}
                if hasattr(self, 'subtitle_enable_checkbox') and self.subtitle_enable_checkbox.isChecked():
                    sub_preview_kwargs = {
                        'subtitle_preview_text': "Lorem ipsum dolor sit amet",
                        'subtitle_margin_v': self.subtitle_margin_input.value(),
                        'subtitle_font_size': self.subtitle_font_size_input.value(),
                        'subtitle_font_name': self.subtitle_font_name_input.text().strip() or "Arial",
                        'subtitle_color': self._subtitle_color,
                        'subtitle_outline': self.subtitle_outline_input.value()
                    }

                dummy_thread.create_overlay_image(current_preview_title, part_text, temp_overlay, **sub_preview_kwargs)

                # Thêm lớp màu overlay nếu có opacity > 0
                if self.overlay_opacity > 0:
                    alpha = self.overlay_opacity / 100.0
                    overlay_hex = f"0x{self.overlay_color[0]:02x}{self.overlay_color[1]:02x}{self.overlay_color[2]:02x}"
                    filter_complex += f"[base]drawbox=x=0:y=0:w=1080:h=1920:color={overlay_hex}@{alpha}:t=fill[base_with_overlay];"
                    filter_complex += f"[base_with_overlay][1:v]overlay=0:0"
                else:
                    # Thêm overlay vào filter
                    filter_complex += f"[base][1:v]overlay=0:0"

                if not os.path.exists(temp_overlay):
                    raise Exception(f"Không thể tạo file overlay: {temp_overlay}")

                cmd = [
                    FFMPEG_EXE,
                    '-y',
                    '-ss', '0',
                    '-i', self.current_video_path,
                    '-i', temp_overlay,
                    '-filter_complex', filter_complex,
                    '-frames:v', '1',
                    '-q:v', '2',
                    temp_thumbnail
                ]

                # Debug: Print command
                # print("FFmpeg CMD:", " ".join(cmd))

                result = run_ffmpeg_silent(cmd)
                if result.returncode != 0:
                    raise Exception(f"FFmpeg error: {result.stderr}")

                # Cleanup overlay
                if os.path.exists(temp_overlay):
                    try:
                        os.remove(temp_overlay)
                    except:
                        pass

                # Hiển thị thumbnail
                pixmap = QPixmap(temp_thumbnail)
                if not pixmap.isNull():
                    # Store the full-size pixmap for popup
                    self.current_preview_pixmap = pixmap

                    # Scale pixmap để vừa với khung preview (tỷ lệ 9:16)
                    scaled_pixmap = pixmap.scaled(
                        180,  # Width cố định cho preview 9:16
                        320,  # Height cố định
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    self.preview_label.setPixmap(scaled_pixmap)

                    # Enable magnify button
                    self.magnify_btn.setEnabled(True)
                else:
                    self.preview_label.setText(f"Video: {Path(self.current_video_path).name}")
                    self.current_preview_pixmap = None
                    self.magnify_btn.setEnabled(False)

                # Xóa file thumbnail tạm
                if os.path.exists(temp_thumbnail):
                    os.remove(temp_thumbnail)

            except Exception as e:
                print(f"Lỗi khi tạo preview: {e}")
                self.preview_label.setText(f"Video: {Path(self.current_video_path).name}")
                self.preview_info.setText(f"Lỗi tạo preview: {str(e)[:50]}")
                self.current_preview_pixmap = None
                self.magnify_btn.setEnabled(False)
        else:
            # Nếu chưa có video - hiển thị khung 9:16 trống với màu nền
            self.preview_info.setText("Chưa có video")
            self.preview_label.setText("Chưa có video")
            self.current_preview_pixmap = None
            self.magnify_btn.setEnabled(False)

    def show_preview_popup(self):
        """Hiển thị popup với preview phóng to"""
        if self.current_preview_pixmap and not self.current_preview_pixmap.isNull():
            self.popup = PreviewPopup(self.current_preview_pixmap, self)
            self.popup.show()
        else:
            self.log("⚠️ Chưa có preview để hiển thị")

    def select_bg_color(self):
        color = QColorDialog.getColor(QColor(*self.bg_color))
        if color.isValid():
            self.bg_color = (color.red(), color.green(), color.blue())
            self.bg_color_label.setStyleSheet(f"background-color: rgb{self.bg_color};")
            self.log(f"Đã chọn màu nền: RGB{self.bg_color}")
            # Bỏ chọn blur nếu chọn màu nền
            if self.blur_bg_checkbox.isChecked():
                self.blur_bg_checkbox.setChecked(False)
            # Cập nhật preview nếu có video
            if self.current_video_path:
                self.update_preview()

    def select_text_bg_color(self):
        color = QColorDialog.getColor(QColor(*self.text_bg_color[:3]))
        if color.isValid():
            self.text_bg_color = (color.red(), color.green(), color.blue(), 255)
            self.text_bg_label.setStyleSheet(f"background-color: rgba{self.text_bg_color};")
            self.log(f"Đã chọn màu nền chữ: RGB{self.text_bg_color[:3]}")
            if self.current_video_path:
                self.update_preview()

    def select_text_color(self):
        color = QColorDialog.getColor(QColor(*self.text_color))
        if color.isValid():
            self.text_color = (color.red(), color.green(), color.blue())
            self.text_color_label.setStyleSheet(f"background-color: rgb{self.text_color};")
            self.log(f"Đã chọn màu chữ: RGB{self.text_color}")
            if self.current_video_path:
                self.update_preview()

    def select_text_border_color(self):
        """Chọn màu cho viền TEXT"""
        color = QColorDialog.getColor(QColor(*self.text_border_color))
        if color.isValid():
            self.text_border_color = (color.red(), color.green(), color.blue())
            self.text_border_color_label.setStyleSheet(f"background-color: rgb{self.text_border_color};")
            self.log(f"Đã chọn màu viền chữ: RGB{self.text_border_color}")
            # Cập nhật thông tin viền chữ
            self.update_text_border_info()
            if self.current_video_path:
                self.update_preview()

    def update_text_border_width_display(self):
        """Cập nhật hiển thị độ dày viền TEXT"""
        text_border_width = self.text_border_width_slider.value()
        self.text_border_width = text_border_width
        self.text_border_width_label.setText(f"{text_border_width}px")

        # Cập nhật thông tin viền chữ
        self.update_text_border_info()

        if text_border_width > 0:
            self.log(f"Độ dày viền chữ: {text_border_width}px")
        else:
            self.log("Đã tắt viền chữ")

        if self.current_video_path:
            self.update_preview_debounced()

    def update_text_border_info(self):
        """Cập nhật thông tin hiển thị về viền TEXT"""
        if self.text_border_width > 0:
            border_text = f"{self.text_border_width}px, RGB{self.text_border_color}"
            self.text_border_info.setText(border_text)
            self.text_border_info.setStyleSheet("""
                font-weight: bold;
                color: #8e44ad;
                background-color: #f4ecf7;
                border-radius: 3px;
                padding: 3px 8px;
            """)
        else:
            self.text_border_info.setText("Không có")
            self.text_border_info.setStyleSheet("""
                font-weight: bold;
                color: #7f8c8d;
                background-color: #f8f9fa;
                border-radius: 3px;
                padding: 3px 8px;
            """)

    def update_processing_mode(self):
        mode = self.mode_combo.currentData()
        self.processing_mode = mode

        # Ẩn/hiện URL section
        if hasattr(self, 'url_section_container'):
            self.url_section_container.setVisible(mode == "url")

        if mode == "single":
            self.video_input.setPlaceholderText("Chọn video...")
            self.video_input.setEnabled(True)
            if hasattr(self, 'batch_folder_container'):
                self.batch_folder_container.setVisible(False)
        elif mode == "url":
            # Khi URL mode: ẩn video input row (dùng URL input thay thế)
            self.video_input.setPlaceholderText("(Video sẽ tự tải từ URL)")
            self.video_input.setEnabled(False)
            if hasattr(self, 'batch_folder_container'):
                self.batch_folder_container.setVisible(False)
        else:
            self.video_input.setPlaceholderText("Chọn thư mục chứa video...")
            self.video_input.setEnabled(True)
            if hasattr(self, 'batch_folder_container'):
                self.batch_folder_container.setVisible(True)
            
        if mode != "url":
            self.video_input.setText("")
        self.current_video_path = None
        
        # Xóa các widget cũ
        if hasattr(self, 'video_item_widgets'):
            for w in self.video_item_widgets:
                self.video_items_layout.removeWidget(w)
                w.deleteLater()
            self.video_item_widgets.clear()
        
        if mode == "url":
            self.empty_video_label.setText("Dán URL vào ô bên trên rồi nhấn '▶️ Start Processing' để tự động tải và xử lý.")
        else:
            self.empty_video_label.setText("Chưa có video nào. Hãy chọn " + ("video" if mode == "single" else "thư mục") + " nguồn.")
        self.empty_video_label.setVisible(True)
        self.update_preview()


    # ── URL Download & Thumbnail ───────────────────────────────────────────────

    def on_fetch_thumb_clicked(self):
        """Xử lý khi người dùng nhấn nút '🖼️ Get Thumb' vật lý."""
        url = self.thumb_url_input.text().strip() if hasattr(self, 'thumb_url_input') else ""
        vid = self.current_video_path if hasattr(self, 'current_video_path') and self.current_video_path else ""
        
        if not url and not vid:
            QMessageBox.warning(self, "Cảnh báo", "Vui lòng nhập link URL thumbnail hoặc chọn video nguồn trước khi lấy thumbnail!")
            return
        
        self.log("🖼️ Đang thử tải/trích xuất thumbnail...")
        out_dir = os.path.dirname(vid) if vid else os.path.expanduser("~/Downloads")
        res = fetch_or_extract_thumbnail(url, vid, out_dir, progress_callback=self.log)
        
        if res and os.path.exists(res):
            self.source_thumbnail_path = res
            self.log("✅ Đã lấy thumbnail thành công!")
            QMessageBox.information(self, "Thành công", "✅ Đã lấy thumbnail thành công!")
            self.update_preview_debounced()
        else:
            self.log("❌ Không thể lấy thumbnail từ link URL hay video!")
            QMessageBox.warning(self, "Lỗi", "❌ Không thể lấy thumbnail từ link URL hay video nguồn!")

    def _on_use_thumbnail_changed(self, state):
        """Callback khi bật/tắt checkbox dùng thumbnail làm nền."""
        self.use_video_thumbnail = bool(state)
        if hasattr(self, 'thumb_url_widget'):
            self.thumb_url_widget.setEnabled(self.use_video_thumbnail)
        
        if self.use_video_thumbnail:
            if self.source_thumbnail_path and os.path.exists(self.source_thumbnail_path):
                self.thumb_status_label.setText(f"✅ Thumbnail: {Path(self.source_thumbnail_path).name}")
                self.thumb_status_label.setStyleSheet("color: #10B981; font-size: 10px; font-weight: bold;")
            elif hasattr(self, 'thumb_url_input') and self.thumb_url_input.text().strip():
                self.thumb_status_label.setText("⚠️ Nhấn 'Lấy Thumb' hoặc bắt đầu để tải thumb từ link")
                self.thumb_status_label.setStyleSheet("color: #F59E0B; font-size: 10px; font-style: italic;")
            else:
                self.thumb_status_label.setText("ℹ️ Để trống = tự lấy frame đầu video")
                self.thumb_status_label.setStyleSheet("color: #9CA3AF; font-size: 10px; font-style: italic;")
                self.log("ℹ️ Bật thumbnail nền — nếu không nhập link thumb, mặc định sẽ lấy frame đầu của video.")
        else:
            self.thumb_status_label.setText("Đã tắt thumbnail nền")
            self.thumb_status_label.setStyleSheet("color: #9CA3AF; font-size: 10px; font-style: italic;")

    def _on_thumb_url_changed(self, text: str):
        """Callback khi ô link thumbnail thay đổi."""
        url = text.strip()
        if not url:
            self.source_thumbnail_path = ""
            if self.use_video_thumbnail:
                self.thumb_status_label.setText("ℹ️ Để trống = tự lấy frame đầu video")
                self.thumb_status_label.setStyleSheet("color: #9CA3AF; font-size: 10px; font-style: italic;")
        else:
            if self.source_thumbnail_path:
                self.source_thumbnail_path = ""
            if self.use_video_thumbnail:
                self.thumb_status_label.setText("⚠️ Nhấn 'Lấy Thumb' để tải từ link")
                self.thumb_status_label.setStyleSheet("color: #F59E0B; font-size: 10px; font-style: italic;")

    def fetch_thumbnail_from_url(self):
        """Tải riêng thumbnail từ ô link thumbnail."""
        if not hasattr(self, 'thumb_url_input'):
            return

        url = self.thumb_url_input.text().strip()
        if not url:
            self.source_thumbnail_path = ""
            self.thumb_status_label.setText("ℹ️ Để trống = tự lấy frame đầu video")
            self.thumb_status_label.setStyleSheet("color: #9CA3AF; font-size: 10px; font-style: italic;")
            self.log("ℹ️ Ô link thumbnail rỗng. Mặc định sẽ lấy frame đầu của video làm thumb khi xử lý.")
            return

        output_dir = self.output_input.text().strip()
        if not output_dir:
            output_dir = str(Path.home() / "Documents" / "VideoEditor" / "Output")

        download_dir = os.path.join(output_dir, "_thumbnails")

        # Huỷ thread cũ nếu đang chạy
        if hasattr(self, '_thumb_downloader_thread') and self._thumb_downloader_thread and self._thumb_downloader_thread.isRunning():
            self._thumb_downloader_thread.stop()
            self._thumb_downloader_thread.wait(1000)

        self.log(f"🖼️ Đang lấy thumbnail từ link: {url[:80]}...")
        self.fetch_thumb_btn.setEnabled(False)
        self.fetch_thumb_btn.setText("⏳ Đang lấy...")
        self.thumb_status_label.setText("⏳ Đang tải thumbnail...")
        self.thumb_status_label.setStyleSheet("color: #F59E0B; font-size: 10px; font-weight: bold;")

        self._thumb_downloader_thread = ThumbnailDownloaderThread(url, download_dir, parent=self)
        self._thumb_downloader_thread.progress.connect(self.log)
        self._thumb_downloader_thread.finished.connect(self._on_thumbnail_fetch_finished)
        self._thumb_downloader_thread.finished.connect(self._thumb_downloader_thread.deleteLater)
        self._thumb_downloader_thread.start()

    def _on_thumbnail_fetch_finished(self, success: bool, thumb_path: str, error_msg: str):
        """Callback khi tải xong thumbnail từ URL."""
        if hasattr(self, 'fetch_thumb_btn'):
            self.fetch_thumb_btn.setEnabled(True)
            self.fetch_thumb_btn.setText("🖼️ Lấy Thumb")

        if success and thumb_path and os.path.exists(thumb_path):
            self.source_thumbnail_path = thumb_path
            self.use_video_thumbnail = True
            self.use_thumbnail_checkbox.setChecked(True)
            self.thumb_status_label.setText(f"✅ Thumbnail: {Path(thumb_path).name}")
            self.thumb_status_label.setStyleSheet("color: #10B981; font-size: 10px; font-weight: bold;")
            self.log(f"✅ Đã tải thumbnail thành công: {Path(thumb_path).name}")
        else:
            self.source_thumbnail_path = ""
            self.thumb_status_label.setText("❌ Lỗi lấy thumb (sẽ dùng frame đầu)")
            self.thumb_status_label.setStyleSheet("color: #EF4444; font-size: 10px;")
            self.log(f"⚠️ Lỗi lấy thumbnail từ link: {error_msg}. Sẽ dùng frame đầu của video khi xử lý.")

    def download_from_url(self):
        """Bắt đầu tải video từ URL nhập vào."""
        url = self.url_input.text().strip()
        if not url:
            self.log("⚠️ Vui lòng nhập URL trước khi tải!")
            return

        if not (url.startswith("http://") or url.startswith("https://") or url.startswith("www.")):
            self.log("❌ URL không hợp lệ! Vui lòng dán đúng link video (bắt đầu bằng http:// hoặc https://).")
            return

        output_dir = self.output_input.text().strip()
        if not output_dir:
            self.log("⚠️ Vui lòng chọn thư mục xuất trước!")
            return

        # Download thư mục con riêng trong output
        download_dir = os.path.join(output_dir, "_downloaded")

        # Huỷ thread cũ nếu có
        if self._downloader_thread and self._downloader_thread.isRunning():
            self._downloader_thread.stop()
            self._downloader_thread.wait(2000)

        self.log(f"🔗 Bắt đầu tải: {url[:80]}...")
        self.download_btn.setEnabled(False)
        self.download_btn.setText("⏳ Đang tải...")
        self.cancel_download_btn.setVisible(True)
        self.thumb_status_label.setText("⬇️ Đang tải video...")
        self.thumb_status_label.setStyleSheet("color: #F59E0B; font-size: 10px; font-weight: bold;")

        self._downloader_thread = VideoDownloaderThread(url, download_dir, parent=self)
        self._downloader_thread.progress.connect(self._on_download_progress)
        self._downloader_thread.finished.connect(self._on_download_finished)
        self._downloader_thread.finished.connect(self._downloader_thread.deleteLater)
        self._downloader_thread.start()

    def cancel_download(self):
        """Huỷ bỏ quá trình tải video."""
        if self._downloader_thread and self._downloader_thread.isRunning():
            self._downloader_thread.stop()
            self.log("⚠️ Đang huỷ tải video...")
        self.download_btn.setEnabled(True)
        self.download_btn.setText("⬇️ Tải")
        self.cancel_download_btn.setVisible(False)
        self.thumb_status_label.setText("Đã huỷ tải")
        self.thumb_status_label.setStyleSheet("color: #EF4444; font-size: 10px;")

    def _on_download_progress(self, message: str):
        """Hiển thị tiến trình tải video."""
        self.log(message)
        # Cập nhật status label với thông tin ngắn gọn
        short = message[:60] + "..." if len(message) > 60 else message
        self.thumb_status_label.setText(short)

    def _on_download_finished(self, success: bool, video_path: str, thumb_path: str):
        """Callback khi tải video hoàn tất."""
        self.download_btn.setEnabled(True)
        self.download_btn.setText("⬇️ Tải")
        self.cancel_download_btn.setVisible(False)

        if not success:
            self.log("❌ Tải video thất bại.")
            self.thumb_status_label.setText("❌ Tải thất bại")
            self.thumb_status_label.setStyleSheet("color: #EF4444; font-size: 10px;")
            return

        self.log(f"✅ Tải xong: {Path(video_path).name}")

        # Lưu thumbnail path
        if thumb_path and os.path.exists(thumb_path):
            self.source_thumbnail_path = thumb_path
            self.use_thumbnail_checkbox.setChecked(True)
            self.use_video_thumbnail = True
            self.thumb_status_label.setText(f"✅ Thumbnail: {Path(thumb_path).name}")
            self.thumb_status_label.setStyleSheet("color: #10B981; font-size: 10px; font-weight: bold;")
            self.log(f"🖼️ Thumbnail đã sẵn sàng: {Path(thumb_path).name}")
        else:
            # Không có thumbnail → sẽ lấy frame đầu video khi xử lý
            self.source_thumbnail_path = ""
            self.thumb_status_label.setText("ℹ️ Sẽ dùng frame đầu video")
            self.thumb_status_label.setStyleSheet("color: #6B7280; font-size: 10px; font-style: italic;")
            self.log("ℹ️ Không có thumbnail riêng, sẽ lấy frame đầu video khi xử lý.")

        # Tự động load video vào danh sách
        if video_path and os.path.exists(video_path):
            self.process_selected_input(video_path, is_dir=False)
        else:
            self.log("⚠️ Không tìm thấy file video sau khi tải!")

    def _on_url_download_then_process(self, success: bool, video_path: str, thumb_path: str):
        """Callback đặc biệt khi nhấn Start Processing ở URL mode: tải xong → tự xử lý."""
        self.download_btn.setEnabled(True)
        self.download_btn.setText("⬇️ Tải")
        self.cancel_download_btn.setVisible(False)

        if not success or not video_path:
            self.log("❌ Tải video thất bại, không thể tiếp tục xử lý.")
            self.thumb_status_label.setText("❌ Tải thất bại")
            self.thumb_status_label.setStyleSheet("color: #EF4444; font-size: 10px;")
            return

        self.log(f"✅ Tải xong: {Path(video_path).name} → bắt đầu xử lý...")

        # Lưu thumbnail
        if thumb_path and os.path.exists(thumb_path):
            self.source_thumbnail_path = thumb_path
            self.use_video_thumbnail = True
            self.thumb_status_label.setText(f"✅ Thumbnail: {Path(thumb_path).name}")
            self.thumb_status_label.setStyleSheet("color: #10B981; font-size: 10px; font-weight: bold;")
        else:
            self.source_thumbnail_path = ""
            self.thumb_status_label.setText("ℹ️ Sẽ dùng frame đầu video")
            self.thumb_status_label.setStyleSheet("color: #6B7280; font-size: 10px;")

        # Load video vào list rồi tự động start_processing
        if os.path.exists(video_path):
            self.process_selected_input(video_path, is_dir=False)
            # Sau khi load xong, gọi start_processing (video đã có trong list)
            self.start_processing()
        else:
            self.log("⚠️ File video không tồn tại sau khi tải!")

    # ── End URL Download ───────────────────────────────────────────────────────

    def select_video(self):
        if self.processing_mode == "single":
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Chọn video",
                "",
                "Video Files (*.mp4 *.avi *.mov *.mkv *.webm *.m4a);;All Files (*)"
            )
            if filename:
                self.process_selected_input(filename, is_dir=False)
        else:
            dirname = QFileDialog.getExistingDirectory(self, "Chọn thư mục chứa video")
            if dirname:
                self.process_selected_input(dirname, is_dir=True)

    def process_selected_input(self, path, is_dir=False):
        # Kiểm tra thuộc tính list
        if not hasattr(self, 'video_item_widgets'):
            self.video_item_widgets = []
            
        # Xóa các widget cũ
        for w in self.video_item_widgets:
            self.video_items_layout.removeWidget(w)
            w.deleteLater()
        self.video_item_widgets.clear()
        self.empty_video_label.setVisible(False)

        videos_to_process = []

        if not is_dir:
            self.current_video_path = path
            self.video_input.setText(path)
            self.log(f"📂 Đã chọn video: {Path(path).name}")
            videos_to_process.append(path)
        else:
            self.video_input.setText(path)
            self.log(f"📂 Đã chọn thư mục: {path}")
            
            video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4a', '.MP4', '.AVI', '.MOV', '.M4A')
            for root, dirs, files in os.walk(path):
                for file in files:
                    if file.lower().endswith(video_extensions):
                        videos_to_process.append(os.path.join(root, file))
            
            if videos_to_process:
                self.current_video_path = videos_to_process[0]
                self.log(f"Tìm thấy {len(videos_to_process)} video trong thư mục.")
            else:
                self.log(f"❌ Không tìm thấy video nào trong thư mục!")
                self.empty_video_label.setText("Không tìm thấy video nào trong thư mục.")
                self.empty_video_label.setVisible(True)
                self.current_video_path = None
                return

        # Tạo widget cho mỗi video
        for video_path in videos_to_process:
            try:
                cmd = [
                    FFPROBE_EXE, '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1', video_path
                ]
                result = run_ffmpeg_silent(cmd)
                duration = float(result.stdout.strip())
            except Exception as e:
                self.log(f"Lỗi khi đọc file {Path(video_path).name}: {e}")
                duration = 0.0
                
            item = VideoItemWidget(video_path, duration)
            item.preview_requested.connect(self.load_preview_from_item)
            item.title_changed.connect(self.on_title_changed)
            item.stats_changed.connect(self.update_segments_count)
            
            self.video_items_layout.insertWidget(self.video_items_layout.count() - 1, item)
            self.video_item_widgets.append(item)
            QApplication.processEvents()

        # Cập nhật thông số lần đầu cho toàn bộ danh sách
        self.update_segments_count()

        # Tải preview cho video đầu tiên
        if self.video_item_widgets:
            first_item = self.video_item_widgets[0]
            self.load_preview_from_item(first_item.path, first_item.duration)

    def load_preview_from_item(self, path, duration):
        """Thay đổi video preview khi người dùng ấn nút Preview trên item"""
        self.current_video_path = path
        self.video_duration = duration
        self.log(f"👁 Chuyển sang Preview: {Path(path).name} ({self.format_time(duration)})")
        
        try:
            cmd_size = [
                FFPROBE_EXE, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height', '-of', 'csv=p=0', path
            ]
            result_size = run_ffmpeg_silent(cmd_size)
            w, h = map(int, result_size.stdout.strip().split(','))
            self.original_video_width = w
            self.original_video_height = h
        except:
            pass
            
        self.update_preview()
            
    def on_title_changed(self):
        """Kích hoạt khi người dùng gõ tiêu đề ở bất kỳ video nào"""
        if self.current_video_path:
            # Chỉ update preview nếu video đang sửa tiêu đề khớp với video đang preview
            # (Hoặc cứ update nếu muốn đơn giản, ở đây dùng timer để tránh lag)
            self.preview_timer.start(700) # Đợi 0.7s sau khi ngừng gõ mới render lại preview
            

    
    def select_output(self):
        dirname = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất")
        if dirname:
            self.output_input.setText(dirname)
            self.log(f"📁 Đã chọn thư mục xuất: {dirname}")
    
    def log(self, message):
        """Route all log messages to the global Process Log via signal."""
        self.log_message.emit(message)

    # ── Scene Split helpers ───────────────────────────────────────────────────

    def get_scene_split_params(self):
        """Return current scene-split settings as a dict (or None if disabled)."""
        if not hasattr(self, 'scene_split_checkbox') or not self.scene_split_checkbox.isChecked():
            return None
        return {
            "threshold":    self.scene_threshold_input.value(),
            "delete_pct":   self.scene_delete_pct_input.value(),
            "min_dur":      self.scene_min_dur_input.value(),
            "method":       self.scene_method_combo.currentData() if hasattr(self, 'scene_method_combo') else "hybrid",
        }

    def _on_scene_method_changed(self, _index):
        """Update threshold label/range/default when method dropdown changes."""
        method = self.scene_method_combo.currentData()
        if method in ("hybrid", "histogram", "ssim"):
            self.scene_threshold_label_item.setText("Adaptive K (1-4):")
            self.scene_threshold_input.setRange(0.5, 5.0)
            self.scene_threshold_input.setSingleStep(0.1)
            self.scene_threshold_input.setValue(2.0)
            self.scene_threshold_input.setToolTip(
                "Adaptive K -- threshold = mean + K x std\n"
                "Cao = it canh hon (chi cat manh), thap = nhieu canh hon.\n"
                "Khuyen: 1.5-2.5"
            )
        elif method == "ffmpeg":
            self.scene_threshold_label_item.setText("scdet threshold (0-100):")
            self.scene_threshold_input.setRange(0.0, 100.0)
            self.scene_threshold_input.setSingleStep(5.0)
            self.scene_threshold_input.setValue(40.0)
            self.scene_threshold_input.setToolTip(
                "FFmpeg scdet threshold (0-100).\n"
                "Thap = nhay hon (nhieu canh), cao = it nhay (it canh).\n"
                "Mac dinh: 40."
            )
        elif method == "pyscene":
            self.scene_threshold_label_item.setText("ContentDetector threshold:")
            self.scene_threshold_input.setRange(1.0, 100.0)
            self.scene_threshold_input.setSingleStep(1.0)
            self.scene_threshold_input.setValue(27.0)
            self.scene_threshold_input.setToolTip(
                "PySceneDetect ContentDetector threshold.\n"
                "Thap = nhay hon, cao = it canh hon.\n"
                "Mac dinh: 27. Dai thuc te: 10-40."
            )


    def run_scene_analysis_preview(self):
        """Run scene detection asynchronously in background thread so UI never freezes."""
        if not hasattr(self, 'video_item_widgets') or not self.video_item_widgets:
            self.scene_status_label.setText("Chưa có video nào được chọn.")
            self.scene_status_label.setStyleSheet(
                "color: #f59e0b; font-size: 10px; background: transparent; border: none;")
            return

        first_widget = self.video_item_widgets[0]
        video_path   = first_widget.path
        start_sec, end_sec = first_widget.get_cut_times()
        threshold    = self.scene_threshold_input.value()
        delete_pct   = self.scene_delete_pct_input.value()
        min_dur      = self.scene_min_dur_input.value()
        method       = self.scene_method_combo.currentData() if hasattr(self, 'scene_method_combo') else "hybrid"

        self.scene_analyze_btn.setEnabled(False)
        self.scene_status_label.setText(f"⏳ Đang phân tích [{method}]... (xem nhật ký ở bảng log)")
        self.scene_status_label.setStyleSheet(
            "color: #a78bfa; font-size: 10px; font-style: italic; background: transparent; border: none;")

        self._analysis_thread = SceneAnalysisThread(
            video_path, start_sec, end_sec, threshold, delete_pct, min_dur, method=method, seed=42
        )
        self._analysis_thread.log_msg.connect(self.log)
        self._analysis_thread.analysis_finished.connect(
            lambda timestamps, skip_ranges, n_scenes, n_deleted, total_deleted_sec, err_msg, report_lines:
            self._on_scene_analysis_finished(timestamps, skip_ranges, n_scenes, n_deleted, total_deleted_sec, err_msg, report_lines, method, threshold)
        )
        self._analysis_thread.start()

    def _on_scene_analysis_finished(self, timestamps, skip_ranges, n_scenes, n_deleted, total_deleted_sec, err_msg, report_lines, method, threshold):
        self.scene_analyze_btn.setEnabled(True)
        if err_msg:
            self.scene_status_label.setText(f"❌ Lỗi: {err_msg[:80]}")
            self.scene_status_label.setStyleSheet(
                "color: #f87171; font-size: 10px; background: transparent; border: none;")
            self.log(f"Scene detection lỗi: {err_msg}")
        else:
            msg = (
                f"✅ [{method.upper()}] Tìm được {n_scenes} cảnh  |  "
                f"Sẽ xóa ~{n_deleted} cảnh (~{total_deleted_sec:.1f}s)"
            )
            self.scene_status_label.setText(msg)
            self.scene_status_label.setStyleSheet(
                "color: #34d399; font-size: 10px; font-weight: 600; "
                "background: transparent; border: none;")

            # Print detailed report to the process log panel
            for line in report_lines:
                self.log(line)

    # End Scene Split


    # ── Auto Subtitle helpers ─────────────────────────────────────────────────

    def _on_subtitle_toggled(self, enabled: bool):
        """Called when the Auto Subtitle checkbox is toggled."""
        self.subtitle_config.enabled = enabled
        if enabled:
            self.log("🎙 Auto Subtitle đã bật. Kéo thả trên khung Preview để chỉnh vị trí.")
        else:
            self.log("🎙 Auto Subtitle đã tắt.")
        self.update_preview_debounced()

    def _on_preview_position_dragged(self, margin_v: int):
        """Called when user drags vertically on the preview label to adjust subtitle margin."""
        if hasattr(self, 'subtitle_enable_checkbox') and self.subtitle_enable_checkbox.isChecked():
            self.subtitle_margin_input.blockSignals(True)
            self.subtitle_margin_input.setValue(margin_v)
            self.subtitle_margin_input.blockSignals(False)
            self.update_preview_debounced()


    def _build_subtitle_config_from_ui(self) -> "SubtitleConfig":
        """Read all subtitle UI controls and return a populated SubtitleConfig."""
        cfg = SubtitleConfig()
        cfg.enabled = self.subtitle_enable_checkbox.isChecked()
        cfg.model_size = self.subtitle_model_combo.currentData() or "base"
        cfg.beam_size = self.subtitle_beam_size_spin.value() if hasattr(self, 'subtitle_beam_size_spin') else 5
        cfg.initial_prompt = self.subtitle_initial_prompt_input.text().strip() if hasattr(self, 'subtitle_initial_prompt_input') else ""
        cfg.font_name = self.subtitle_font_name_input.text().strip() or "Arial"
        cfg.font_size = self.subtitle_font_size_input.value()
        cfg.outline_width = self.subtitle_outline_input.value()
        cfg.shadow_depth = self.subtitle_shadow_input.value()
        cfg.margin_v = self.subtitle_margin_input.value()
        cfg.enable_word_highlight = self.subtitle_word_hl_checkbox.isChecked()
        cfg.max_chars_per_line = self.subtitle_max_chars_input.value()
        cfg.max_words_per_block = self.subtitle_max_words_input.value() if hasattr(self, 'subtitle_max_words_input') else 5
        cfg.max_lines_per_block = self.subtitle_max_lines_input.value() if hasattr(self, 'subtitle_max_lines_input') else 1

        # Convert RGB display tuples to ASS color strings (&HAABBGGRR)
        cfg.primary_color = self._rgb_to_ass_color(self._subtitle_color)
        cfg.highlight_color = self._rgb_to_ass_color(self._subtitle_hl_color)
        cfg.outline_color = "&H00000000"   # black
        cfg.shadow_color = "&H80000000"    # semi-transparent black
        return cfg

    @staticmethod
    def _rgb_to_ass_color(rgb: tuple, alpha: int = 0) -> str:
        """Convert an (R, G, B) tuple to ASS color format &HAABBGGRR."""
        r, g, b = rgb[0], rgb[1], rgb[2]
        return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

    def _pick_subtitle_color(self):
        """Open color picker for subtitle text color."""
        color = QColorDialog.getColor(QColor(*self._subtitle_color), self, "Chọn màu chữ subtitle")
        if color.isValid():
            self._subtitle_color = (color.red(), color.green(), color.blue())
            self.subtitle_color_preview.setStyleSheet(
                f"background-color: rgb{self._subtitle_color}; border: 1px solid #555; border-radius: 3px;"
            )

    def _pick_subtitle_hl_color(self):
        """Open color picker for word-highlight color."""
        color = QColorDialog.getColor(QColor(*self._subtitle_hl_color), self, "Chọn màu Highlight")
        if color.isValid():
            self._subtitle_hl_color = (color.red(), color.green(), color.blue())
            self.subtitle_hl_color_preview.setStyleSheet(
                f"background-color: rgb{self._subtitle_hl_color}; border: 1px solid #555; border-radius: 3px;"
            )

    def _run_subtitle_test(self):
        """Run subtitle generation on the first video as a dry-run (no video output)."""
        if not hasattr(self, 'video_item_widgets') or not self.video_item_widgets:
            self.subtitle_status_label.setText("⚠️ Chưa có video nào được chọn.")
            self.subtitle_status_label.setStyleSheet(
                "color: #f59e0b; font-size: 10px; background: transparent; border: none;"
            )
            return

        output_dir = self.output_input.text().strip()
        if not output_dir:
            self.subtitle_status_label.setText("⚠️ Chưa chọn thư mục xuất.")
            return

        video_path = self.video_item_widgets[0].path
        cfg = self._build_subtitle_config_from_ui()

        self.subtitle_test_btn.setEnabled(False)
        self.subtitle_status_label.setText("⏳ Đang transcribe... (xem nhật ký ở bảng log)")
        self.subtitle_status_label.setStyleSheet(
            "color: #a78bfa; font-size: 10px; font-style: italic; background: transparent; border: none;"
        )

        thread = SubtitleGeneratorThread(video_path, output_dir, cfg, parent=self)
        thread.progress.connect(self.log)
        thread.finished.connect(self._on_subtitle_test_finished)
        thread.finished.connect(thread.deleteLater)
        self._subtitle_test_thread = thread  # keep reference
        thread.start()

    def _on_subtitle_test_finished(self, success: bool, ass_path: str, error: str):
        """Callback for the test subtitle generation."""
        self.subtitle_test_btn.setEnabled(True)
        if success:
            self.subtitle_status_label.setText(f"✅ Test OK → {Path(ass_path).name}")
            self.subtitle_status_label.setStyleSheet(
                "color: #34d399; font-size: 10px; font-weight: 600; background: transparent; border: none;"
            )
            self.log(f"✅ Subtitle test thành công: {ass_path}")
        else:
            self.subtitle_status_label.setText(f"❌ Lỗi: {error[:80]}")
            self.subtitle_status_label.setStyleSheet(
                "color: #f87171; font-size: 10px; background: transparent; border: none;"
            )

    def _generate_subtitle_for_video(self, video_path: str, output_dir: str,
                                     cfg: "SubtitleConfig", on_done) -> "SubtitleGeneratorThread":
        """
        Spin up a SubtitleGeneratorThread for video_path.
        on_done(success, ass_path, error) is called when finished.
        Returns the thread (caller must keep a reference).
        """
        thread = SubtitleGeneratorThread(video_path, output_dir, cfg, parent=self)
        thread.progress.connect(self.log)
        thread.finished.connect(on_done)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        return thread

    # ── End Auto Subtitle helpers ──────────────────────────────────────────────


    def start_processing(self):
        import time
        self.start_time = time.time()

        # URL mode: nếu chưa có video trong list → tự tải trước
        if self.processing_mode == "url":
            url = self.url_input.text().strip() if hasattr(self, 'url_input') else ""
            out_dir = self.output_input.text().strip()

            if not out_dir:
                self.log("❌ Vui lòng chọn thư mục xuất trước!")
                return

            if not url:
                self.log("❌ Vui lòng nhập URL video trước!")
                return

            if not (url.startswith("http://") or url.startswith("https://") or url.startswith("www.")):
                self.log("❌ URL không hợp lệ! Vui lòng dán đúng link video (bắt đầu bằng http:// hoặc https://).")
                return

            # Nếu chưa có video nào trong list → tải rồi tự xử lý
            if not hasattr(self, 'video_item_widgets') or not self.video_item_widgets:
                self.log("🔗 Đang tải video từ URL, sau đó sẽ tự xử lý...")
                # Kết nối tạm để sau khi tải xong tự động gọi lại start_processing
                download_dir = os.path.join(out_dir, "_downloaded")
                if self._downloader_thread and self._downloader_thread.isRunning():
                    self._downloader_thread.stop()
                    self._downloader_thread.wait(2000)

                self.download_btn.setEnabled(False)
                self.download_btn.setText("⏳ Đang tải...")
                self.cancel_download_btn.setVisible(True)
                self.thumb_status_label.setText("⬇️ Đang tải video...")
                self.thumb_status_label.setStyleSheet("color: #F59E0B; font-size: 10px; font-weight: bold;")

                self._downloader_thread = VideoDownloaderThread(url, download_dir, parent=self)
                self._downloader_thread.progress.connect(self._on_download_progress)
                # Kết nối finished vào callback đặc biệt: tải xong → tự start_processing
                self._downloader_thread.finished.connect(self._on_url_download_then_process)
                self._downloader_thread.finished.connect(self._downloader_thread.deleteLater)
                self._downloader_thread.start()
                return  # Chờ download xong

        if not hasattr(self, 'video_item_widgets') or not self.video_item_widgets:
            self.log("❌ Vui lòng chọn " + ("video" if self.processing_mode == 'single' else "thư mục") + " đầu vào!")
            self.status_display.setText("🔴 Thiếu đầu vào")
            self.status_display.setStyleSheet(self.status_display.styleSheet().replace("#27ae60", "#e74c3c").replace("#e8f6f3", "#fadbd8"))
            return
        
        if not self.output_input.text():
            self.log("❌ Vui lòng chọn thư mục xuất!")
            self.status_display.setText("🔴 Thiếu thư mục")
            self.status_display.setStyleSheet(self.status_display.styleSheet().replace("#27ae60", "#e74c3c").replace("#e8f6f3", "#fadbd8"))
            return

        # Nếu bật thumbnail và ô link thumb có nhập link mà chưa tải -> tự tải thumb trước
        thumb_url = self.thumb_url_input.text().strip() if hasattr(self, 'thumb_url_input') else ""
        if self.use_video_thumbnail and thumb_url and not self.source_thumbnail_path:
            self.log("🖼️ Đang tự động tải thumbnail từ link đã nhập...")
            self.fetch_thumbnail_from_url()
            if hasattr(self, '_thumb_downloader_thread') and self._thumb_downloader_thread:
                self._thumb_downloader_thread.wait(10000)

        # Prepare processing queue
        self.video_queue = []
        input_path = self.video_input.text()
        out_base = self.output_input.text()

        # Dọn dẹp cache của distribute nếu có
        if hasattr(self, '_cached_distribute_folders'):
            del self._cached_distribute_folders
        if hasattr(self, '_distribute_assignments'):
            del self._distribute_assignments

        for widget in self.video_item_widgets:
            src_file = widget.path
            title = widget.title_input.text().strip()
            if not title:
                self.log(f"❌ Video {Path(src_file).name} thiếu tiêu đề!")
                return
            
            # Lấy skip ranges từ widget
            try:
                skip_ranges = widget.get_skip_ranges()
            except Exception as e:
                self.log(f"❌ Lỗi skip range ở video {Path(src_file).name}")
                return
                
            start_time, end_time = widget.get_cut_times()
            
            # Áp dụng cấu hình cắt thời gian chung (nếu có)
            global_start = self.global_trim_start.value()
            global_trim_end_val = self.global_trim_end.value()
            
            if global_start > 0:
                start_time = max(start_time, global_start)
            
            if global_trim_end_val > 0:
                # Giới hạn end_time lại
                max_end = max(0, widget.duration - global_trim_end_val)
                end_time = min(end_time, max_end)
                
            if start_time >= end_time:
                self.log(f"❌ Video {Path(src_file).name} bị cắt sai (Thời gian bắt đầu >= kết thúc). Vui lòng kiểm tra lại cấu hình Cắt thời gian chung!")
                return
            
            if self.processing_mode == "single":
                dest_dir = out_base
            else:
                # Kiểm tra chế độ output của batch
                use_subfolder = hasattr(self, 'output_subfolder_radio') and self.output_subfolder_radio.isChecked()
                use_distribute = hasattr(self, 'output_distribute_radio') and self.output_distribute_radio.isChecked()
                
                if use_subfolder:
                    # Mỗi video xuất vào subfolder tên = tên file video gốc (stem)
                    video_stem = Path(src_file).stem
                    safe_stem = video_stem.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
                    dest_dir = os.path.join(out_base, safe_stem)
                elif use_distribute:
                    # Thu thập các thư mục đã có sẵn và đếm số lượng video (chỉ làm 1 lần)
                    if not hasattr(self, '_cached_distribute_folders'):
                        try:
                            subfolders = [d for d in os.listdir(out_base) if os.path.isdir(os.path.join(out_base, d))]
                            self._cached_distribute_folders = []
                            for d in subfolders:
                                folder_path = os.path.join(out_base, d)
                                current_count = 0
                                video_exts = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.m4a', '.MP4', '.AVI', '.MOV', '.M4A')
                                try:
                                    for f in os.listdir(folder_path):
                                        if f.endswith(video_exts) and os.path.isfile(os.path.join(folder_path, f)):
                                            current_count += 1
                                except Exception:
                                    pass
                                self._cached_distribute_folders.append({'name': d, 'count': current_count})
                            
                            # Tính toán phân bổ tối ưu (LPT - Longest Processing Time first)
                            if self._cached_distribute_folders:
                                # Lưu lại số lượng ban đầu để in log
                                initial_counts = {f['name']: f['count'] for f in self._cached_distribute_folders}
                                
                                jobs = []
                                for idx, w in enumerate(self.video_item_widgets):
                                    clips = getattr(w, 'calculated_segments', 1)
                                    if clips <= 0: clips = 1
                                    jobs.append({'idx': idx, 'clips': clips})
                                
                                # Xếp video tạo ra nhiều clip nhất trước để phân bổ công bằng hơn
                                jobs.sort(key=lambda x: x['clips'], reverse=True)
                                
                                self._distribute_assignments = {}
                                for job in jobs:
                                    # Tìm folder đang có ít video nhất hiện tại
                                    best_folder = min(self._cached_distribute_folders, key=lambda x: x['count'])
                                    self._distribute_assignments[job['idx']] = best_folder['name']
                                    # Cộng thêm số clip dự kiến vào folder này
                                    best_folder['count'] += job['clips']
                                    
                                # Ghi log chi tiết tổng hợp
                                self.log("="*45)
                                self.log("📊 BẢNG TÍNH TOÁN PHÂN BỔ THƯ MỤC")
                                self.log("="*45)
                                for f in self._cached_distribute_folders:
                                    name = f['name']
                                    initial = initial_counts[name]
                                    final = f['count']
                                    added = final - initial
                                    self.log(f"📁 [{name}]: Có sẵn {initial} video | Nhận thêm {added} clip -> Dự kiến: {final} video")
                                self.log("="*45)
                        except Exception as e:
                            self.log(f"Lỗi tính toán phân bổ folder: {e}")
                            self._cached_distribute_folders = []
                            self._distribute_assignments = {}
                    
                    if self._cached_distribute_folders:
                        current_idx = self.video_item_widgets.index(widget)
                        target_sub = getattr(self, '_distribute_assignments', {}).get(current_idx)
                        
                        if not target_sub:
                            # Fallback an toàn
                            best_folder = min(self._cached_distribute_folders, key=lambda x: x['count'])
                            target_sub = best_folder['name']
                            best_folder['count'] += max(1, getattr(widget, 'calculated_segments', 1))
                            
                        dest_dir = os.path.join(out_base, target_sub)
                        estimated_clips = getattr(widget, 'calculated_segments', 1)
                        self.log(f"  Phân phối video '{title}' ({estimated_clips} clips) vào mục: {target_sub}")
                    else:
                        dest_dir = out_base # Fallback nếu ko có subfolder nào
                else:
                    try:
                        rel_path = os.path.relpath(os.path.dirname(src_file), input_path)
                        if rel_path == '.':
                            dest_dir = out_base
                        else:
                            dest_dir = os.path.join(out_base, rel_path)
                    except:
                        dest_dir = out_base

            self.video_queue.append({
                "src_file": src_file,
                "dest_dir": dest_dir,
                "title": title,
                "start_time": start_time,
                "end_time": end_time,
                "skip_ranges": skip_ranges
            })

        if not self.video_queue:
            self.log("❌ Không tìm thấy video hợp lệ để xử lý!")
            return

        self.total_queue_size = len(self.video_queue)
        self.current_queue_index = 0
        
        # Prepare UI for processing
        self.process_btn.setEnabled(False)
        self.process_btn.setText("⏳ ĐANG XỬ LÝ...")
        self.stop_btn.setEnabled(True)  # Kích hoạt nút Stop
        self.progress_bar.setVisible(True)
        self.status_display.setText("🟡 Đang xử lý...")
        self.status_display.setStyleSheet(self.status_display.styleSheet().replace("#27ae60", "#f39c12").replace("#e8f6f3", "#fef9e7").replace("#e74c3c", "#f39c12"))
        self.progress_label.setText("Đang chuẩn bị xử lý...")

        self.process_next_in_queue()

    def process_next_in_queue(self):
        if self.current_queue_index >= self.total_queue_size:
            self.all_processing_finished()
            return

        job = self.video_queue[self.current_queue_index]
        src_file = job["src_file"]
        dest_dir = job["dest_dir"]
        current_title = job["title"]
        start_time = job["start_time"]
        end_time = job["end_time"]
        skip_ranges = job["skip_ranges"]
        
        self.current_processing_video = src_file
        
        self.log(f"▶️ Bắt đầu xử lý {self.current_queue_index + 1}/{self.total_queue_size}: {Path(src_file).name}")
        self.progress_label.setText(f"Đang xử lý {self.current_queue_index + 1}/{self.total_queue_size}...")

        # Get all parameters
        font_path = self.font_combo.currentData()
        
        # Lấy tỉ lệ zoom
        width_scale = self.width_scale_input.value()
        height_scale = self.height_scale_input.value()
        
        # Lấy text border settings
        text_border_color = self.text_border_color
        text_border_width = self.text_border_width
        
        # Subtitle config
        subtitle_config = self._build_subtitle_config_from_ui()

        # Scene Split parameters (processed in background thread to prevent UI freezing)
        scene_params = self.get_scene_split_params()

        # Determine original sizes for the current video to allow correct zoom (each video might have different dimensions)
        try:
            cmd_size = [
                FFPROBE_EXE, '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height', '-of', 'csv=p=0', src_file
            ]
            result_size = run_ffmpeg_silent(cmd_size)
            orig_w, orig_h = map(int, result_size.stdout.strip().split(','))
        except:
            orig_w, orig_h = self.original_video_width or 1080, self.original_video_height or 1920

        # Start processing thread với các tham số mới (bao gồm text border và scene_params)
        self.thread = VideoProcessThread(
            src_file,
            dest_dir,
            current_title,
            self.speed_input.value(),
            self.segment_input.value(),
            self.gpu_checkbox.isChecked(),
            self.part_suffix.text(),
            self.bg_color,
            self.text_bg_color,
            self.text_color,
            font_path,
            start_time,    # Thời gian theo video gốc
            end_time,      # Thời gian theo video gốc (Lưu ý: batch có thể bị lỗi nếu video ngắn hơn end_time)
            skip_ranges,   # Danh sách các khoảng bỏ qua
            width_scale,   # Tỉ lệ zoom chiều ngang
            height_scale,  # Tỉ lệ zoom chiều dọc
            orig_w,        # Kích thước video gốc
            orig_h,        # Kích thước video gốc
            text_border_color,  # Màu viền TEXT
            text_border_width,  # Độ dày viền TEXT
            self.blur_bg_checkbox.isChecked(), # Blur background
            self.blur_strength_slider.value(), # Blur strength
            self.show_part_checkbox.isChecked(),
            self.part_position_combo.currentData(),
            title_y=self.title_y_input.value(),
            part_y=self.part_y_input.value(),

            merge_last_segment=self.merge_last_checkbox.isChecked(),
            merge_threshold=self.merge_threshold_input.value(),
            overlay_color=self.overlay_color,
            overlay_opacity=self.overlay_opacity,
            
            # Subtitle parameters
            subtitle_config=subtitle_config,
            subtitle_font_size=self.subtitle_font_size,
            subtitle_y_position=1400,
            scene_params=scene_params,
            enable_fade_transition=self.fade_transition_checkbox.isChecked() if hasattr(self, 'fade_transition_checkbox') else True,
            fade_duration=self.fade_duration_input.value() if hasattr(self, 'fade_duration_input') else 0.3,

            # Thumbnail background
            use_video_thumbnail=True,
            source_thumbnail_path=self.thumb_url_input.text().strip() if hasattr(self, 'thumb_url_input') else "",
        )
        
        self.thread.progress.connect(self.update_progress)
        self.thread.finished.connect(self.processing_finished)
        self.thread.start()
    
    def update_progress(self, message):
        if message.startswith("🐛 CMD:"):
            self.progress_label.setText("⚙️ Đang chạy lệnh FFmpeg xử lý video...")
        else:
            # Truncate if any other status message is unusually long to protect the layout
            display_msg = message if len(message) <= 120 else message[:117] + "..."
            self.progress_label.setText(display_msg)
        self.log(message)
    
    def stop_processing(self):
        """Dừng quá trình xử lý"""
        if hasattr(self, 'thread') and self.thread.isRunning():
            reply = QMessageBox.question(self, "Xác nhận", 
                                        "Bạn có chắc muốn dừng quá trình xử lý?",
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                self.thread.terminate()
                self.thread.wait()
                self.process_btn.setEnabled(True)
                self.process_btn.setText("▶️ BẮT ĐẦU XỬ LÝ")
                self.stop_btn.setEnabled(False)
                self.progress_bar.setVisible(False)
                self.status_display.setText("🔴 Đã dừng")
                self.status_display.setStyleSheet(self.status_display.styleSheet().replace("#27ae60", "#e74c3c").replace("#e8f6f3", "#fadbd8").replace("#f39c12", "#e74c3c"))
                self.progress_label.setText("Đã dừng bởi người dùng")
                
                import time
                if hasattr(self, 'start_time'):
                    elapsed = time.time() - self.start_time
                    mins = int(elapsed // 60)
                    secs = int(elapsed % 60)
                    self.log(f"⏱️ Tổng thời gian xử lý: {mins} phút {secs} giây.")
                    
                self.log("⚠️ Đã dừng quá trình xử lý")

    def processing_finished(self, success, message):
        if success:
            self.log(f"✅ Hoàn thành: {message}")
            self.current_queue_index += 1
            if self.current_queue_index < self.total_queue_size:
                # Tiêp tục xử lý file tiếp theo
                self.process_next_in_queue()
            else:
                self.all_processing_finished()
        else:
            self.log(f"❌ Lỗi ở video thứ {self.current_queue_index + 1}: {message}")
            self.progress_bar.setVisible(False)
            self.process_btn.setEnabled(True)
            self.process_btn.setText("▶️ BẮT ĐẦU XỬ LÝ")
            self.stop_btn.setEnabled(False)
            self.status_display.setText("🔴 Lỗi xử lý")
            self.status_display.setStyleSheet(self.status_display.styleSheet().replace("#f39c12", "#e74c3c").replace("#fef9e7", "#fadbd8").replace("#27ae60", "#e74c3c"))
            self.progress_label.setText(f"Có lỗi xảy ra ở {Path(self.current_processing_video).name}!")

    def all_processing_finished(self):
        self.progress_bar.setVisible(False)
        self.process_btn.setEnabled(True)
        self.process_btn.setText("▶️ BẮT ĐẦU XỬ LÝ")
        self.stop_btn.setEnabled(False)  # Vô hiệu hóa nút Stop
        
        self.status_display.setText("🟢 Hoàn thành toàn bộ!")
        self.status_display.setStyleSheet(self.status_display.styleSheet().replace("#f39c12", "#27ae60").replace("#fef9e7", "#e8f6f3").replace("#e74c3c", "#27ae60"))
        self.progress_label.setText("Đã xử lý xong tất cả các video!")
        self.log(f"🎉 Hoàn tất quá trình xử lý hàng loạt ({self.total_queue_size} file)!")
        
        import time
        if hasattr(self, 'start_time'):
            elapsed = time.time() - self.start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            self.log(f"⏱️ Tổng thời gian xử lý: {mins} phút {secs} giây.")
