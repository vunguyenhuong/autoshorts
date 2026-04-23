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
from core.video_editor import (VideoProcessThread, SkipRangeWidget, 
                               detect_gpu_encoder, FFMPEG_EXE, FFPROBE_EXE,
                               run_ffmpeg_silent, EXE_DIR)

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


class AutoCutTab(QWidget):
    """AutoCut Video Editor Tab"""
    log_message = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)

        # Variables
        self.video_duration = 0
        self.bg_color = (240, 240, 240)
        self.text_bg_color = (30, 30, 30, 200)
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

        # Subtitle variables (UI is currently hidden/overwritten)
        self.enable_subtitles = False
        self.is_generating_subtitles = False
        self.subtitle_generator = None
        self.subtitle_font_size = 40
        self.subtitle_border_width = 2
        self.subtitle_color = (255, 255, 255)
        self.subtitle_bg_color = (0, 0, 0, 150)
        self.current_srt_file = None

        # Batch Processing Variables
        self.processing_mode = "single"  # 'single' or 'batch'
        self.video_queue = []
        self.current_queue_index = 0
        self.total_queue_size = 0
        self.current_processing_video = None

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
        self.output_subfolder_radio.setToolTip("Mỗi video sẽ được xuất vào subfolder có tên là tiêu đề video đó")
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

        # Title Y position
        self.title_y_input = QSpinBox()
        self.title_y_input.setRange(0, 1920)
        self.title_y_input.setValue(200)
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
        self.part_y_input.setValue(1600)
        self.part_y_input.setSuffix(" px")
        self.part_y_input.valueChanged.connect(self.update_preview_debounced)
        part_details_layout.addRow("Vị trí Part (Y):", self.part_y_input)

        part_layout.addWidget(self.part_details_container)

        layout.addRow("Cấu hình Part:", part_group)

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
        subtitle_header.setStyleSheet("font-weight: bold; color: #2c3e50;")
        layout.addRow(subtitle_header)
        
        # Enable subtitle checkbox
        self.enable_subtitle_checkbox = QCheckBox("Bật phụ đề tự động")
        self.enable_subtitle_checkbox.setChecked(False)
        self.enable_subtitle_checkbox.toggled.connect(self.toggle_subtitle_controls)
        self.enable_subtitle_checkbox.toggled.connect(self.update_preview)
        layout.addRow("", self.enable_subtitle_checkbox)
        
        # Container for subtitle settings (hidden by default)
        self.subtitle_settings_container = QWidget()
        subtitle_settings_layout = QFormLayout(self.subtitle_settings_container)
        subtitle_settings_layout.setContentsMargins(10, 0, 0, 0)
        subtitle_settings_layout.setSpacing(8)
        
        # Language selection
        self.subtitle_language_combo = QComboBox()
        languages = SubtitleGenerator.get_supported_languages()
        for lang_name, lang_code in languages.items():
            self.subtitle_language_combo.addItem(lang_name, lang_code)
        subtitle_settings_layout.addRow("Ngôn ngữ:", self.subtitle_language_combo)
        
        # Whisper model size
        self.whisper_model_combo = QComboBox()
        models = SubtitleGenerator.get_available_models()
        model_descriptions = {
            'tiny': 'Tiny (Nhanh nhất, ~1GB RAM)',
            'base': 'Base (Cân bằng, ~1GB RAM)',
            'small': 'Small (Khuyến nghị, ~2GB RAM)',
            'medium': 'Medium (Chính xác, ~5GB RAM)',
            'large': 'Large (Tốt nhất, ~10GB RAM)'
        }
        for model in models:
            desc = model_descriptions.get(model, model)
            self.whisper_model_combo.addItem(desc, model)
        # Set default to 'small'
        self.whisper_model_combo.setCurrentIndex(2)
        subtitle_settings_layout.addRow("Model AI:", self.whisper_model_combo)
        
        # Subtitle status (will be updated during processing)
        self.subtitle_status_label = QLabel("Sẽ tự động tạo khi xử lý video")
        self.subtitle_status_label.setStyleSheet("color: #7f8c8d; font-size: 8pt; font-style: italic;")
        subtitle_settings_layout.addRow("Trạng thái:", self.subtitle_status_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #bdc3c7;")
        subtitle_settings_layout.addRow(separator)
        
        # Subtitle styling header
        style_header = QLabel("Tùy chỉnh hiển thị:")
        style_header.setStyleSheet("font-weight: bold; color: #2c3e50; margin-top: 5px;")
        subtitle_settings_layout.addRow(style_header)
        
        # Font size
        font_size_widget = QWidget()
        font_size_layout = QHBoxLayout(font_size_widget)
        font_size_layout.setContentsMargins(0, 0, 0, 0)
        
        self.subtitle_font_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.subtitle_font_size_slider.setRange(20, 80)
        self.subtitle_font_size_slider.setValue(40)
        self.subtitle_font_size_slider.valueChanged.connect(self.update_subtitle_font_size_display)
        self.subtitle_font_size_slider.valueChanged.connect(self.update_preview)
        font_size_layout.addWidget(self.subtitle_font_size_slider, 2)
        
        self.subtitle_font_size_label = QLabel("40px")
        self.subtitle_font_size_label.setFixedWidth(40)
        self.subtitle_font_size_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        font_size_layout.addWidget(self.subtitle_font_size_label)
        
        subtitle_settings_layout.addRow("Cỡ chữ:", font_size_widget)
        
        # Y Position
        self.subtitle_y_position_input = QSpinBox()
        self.subtitle_y_position_input.setRange(0, 1920)
        self.subtitle_y_position_input.setValue(1400)
        self.subtitle_y_position_input.setSuffix(" px")
        self.subtitle_y_position_input.valueChanged.connect(self.update_preview)
        subtitle_settings_layout.addRow("Vị trí Y:", self.subtitle_y_position_input)
        
        # Subtitle text color
        subtitle_color_widget = QWidget()
        subtitle_color_layout = QHBoxLayout(subtitle_color_widget)
        subtitle_color_layout.setContentsMargins(0, 0, 0, 0)
        
        self.subtitle_color_label = QLabel("")
        self.subtitle_color_label.setProperty("colorPreview", True)
        self.subtitle_color_label.setStyleSheet(f"background-color: rgb{self.subtitle_color};")
        subtitle_color_layout.addWidget(self.subtitle_color_label)
        
        subtitle_color_btn = QPushButton("⚙️")
        subtitle_color_btn.setObjectName("colorButton")
        subtitle_color_btn.clicked.connect(self.select_subtitle_color)
        subtitle_color_layout.addWidget(subtitle_color_btn)
        
        subtitle_settings_layout.addRow("Màu chữ:", subtitle_color_widget)
        
        # Subtitle background color
        subtitle_bg_widget = QWidget()
        subtitle_bg_layout = QHBoxLayout(subtitle_bg_widget)
        subtitle_bg_layout.setContentsMargins(0, 0, 0, 0)
        
        self.subtitle_bg_label = QLabel("")
        self.subtitle_bg_label.setProperty("colorPreview", True)
        self.subtitle_bg_label.setStyleSheet(f"background-color: rgba{self.subtitle_bg_color};")
        subtitle_bg_layout.addWidget(self.subtitle_bg_label)
        
        subtitle_bg_btn = QPushButton("⚙️")
        subtitle_bg_btn.setObjectName("colorButton")
        subtitle_bg_btn.clicked.connect(self.select_subtitle_bg_color)
        subtitle_bg_layout.addWidget(subtitle_bg_btn)
        
        subtitle_settings_layout.addRow("Nền chữ:", subtitle_bg_widget)
        
        # Border width
        border_width_widget = QWidget()
        border_width_layout = QHBoxLayout(border_width_widget)
        border_width_layout.setContentsMargins(0, 0, 0, 0)
        
        self.subtitle_border_slider = QSlider(Qt.Orientation.Horizontal)
        self.subtitle_border_slider.setRange(0, 5)
        self.subtitle_border_slider.setValue(2)
        self.subtitle_border_slider.valueChanged.connect(self.update_subtitle_border_display)
        self.subtitle_border_slider.valueChanged.connect(self.update_preview)
        border_width_layout.addWidget(self.subtitle_border_slider, 2)
        
        self.subtitle_border_label = QLabel("2px")
        self.subtitle_border_label.setFixedWidth(40)
        self.subtitle_border_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        border_width_layout.addWidget(self.subtitle_border_label)
        
        subtitle_settings_layout.addRow("Viền chữ:", border_width_widget)
        
        layout.addRow(self.subtitle_settings_container)
        
        # Initially hide subtitle settings
        self.subtitle_settings_container.setVisible(False)
        
        group.setLayout(layout)
        return group
    
    def toggle_subtitle_controls(self, checked):
        """Ẩn/hiện các controls của subtitle"""
        self.subtitle_settings_container.setVisible(checked)
        self.enable_subtitles = checked
    
    def update_subtitle_font_size_display(self, value):
        """Cập nhật hiển thị font size"""
        self.subtitle_font_size_label.setText(f"{value}px")
        self.subtitle_font_size = value
    
    def update_subtitle_border_display(self, value):
        """Cập nhật hiển thị border width"""
        self.subtitle_border_label.setText(f"{value}px")
        self.subtitle_border_width = value
    
    def select_subtitle_color(self):
        """Chọn màu chữ subtitle"""
        color = QColorDialog.getColor(QColor(*self.subtitle_color), self, "Chọn màu chữ subtitle")
        if color.isValid():
            self.subtitle_color = (color.red(), color.green(), color.blue())
            self.subtitle_color_label.setStyleSheet(f"background-color: rgb{self.subtitle_color};")
            self.update_preview()
    
    def select_subtitle_bg_color(self):
        """Chọn màu nền subtitle"""
        color = QColorDialog.getColor(
            QColor(self.subtitle_bg_color[0], self.subtitle_bg_color[1], 
                   self.subtitle_bg_color[2], self.subtitle_bg_color[3]), 
            self, "Chọn màu nền subtitle"
        )
        if color.isValid():
            self.subtitle_bg_color = (color.red(), color.green(), color.blue(), color.alpha())
            self.subtitle_bg_label.setStyleSheet(f"background-color: rgba{self.subtitle_bg_color};")
            self.update_preview()
    
    def generate_subtitles(self):
        """Tạo phụ đề từ video"""
        if not self.current_video_path or not os.path.exists(self.current_video_path):
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn video trước!")
            return
        
        if self.is_generating_subtitles:
            QMessageBox.information(self, "Thông báo", "Đang tạo phụ đề, vui lòng đợi...")
            return
        
        self.is_generating_subtitles = True
        self.generate_subtitle_btn.setEnabled(False)
        self.subtitle_progress.setVisible(True)
        self.subtitle_status_label.setText("Đang tạo phụ đề...")
        self.subtitle_status_label.setStyleSheet("color: #f39c12; font-size: 8pt; font-weight: bold;")
        
        # Get settings
        language_name = self.subtitle_language_combo.currentText()
        language_code = self.subtitle_language_combo.currentData()
        model_size = self.whisper_model_combo.currentData()
        
        self.log(f"🎤 Bắt đầu tạo phụ đề...")
        self.log(f"   Ngôn ngữ: {language_name}")
        self.log(f"   Model: {model_size}")
        
        # Create subtitle generator if not exists
        if self.subtitle_generator is None:
            try:
                self.subtitle_generator = SubtitleGenerator(model_size=model_size)
                self.log(f"✅ Đã khởi tạo Whisper AI (device: {self.subtitle_generator.device.upper()})")
            except Exception as e:
                self.log(f"❌ Lỗi khởi tạo Whisper: {str(e)}")
                self.is_generating_subtitles = False
                self.generate_subtitle_btn.setEnabled(True)
                self.subtitle_progress.setVisible(False)
                self.subtitle_status_label.setText("Lỗi khởi tạo AI")
                self.subtitle_status_label.setStyleSheet("color: #e74c3c; font-size: 8pt;")
                QMessageBox.critical(self, "Lỗi", f"Không thể khởi tạo Whisper AI:\n{str(e)}")
                return
        
        # Run transcription in a separate thread (simplified for now - will use QThread later)
        try:
            def progress_callback(message):
                self.log(message)
            
            # Transcribe
            transcription = self.subtitle_generator.transcribe_video(
                self.current_video_path,
                language=language_code,
                use_cache=True,
                progress_callback=progress_callback
            )
            
            # Generate SRT file
            output_dir = os.path.dirname(self.current_video_path)
            srt_filename = os.path.splitext(os.path.basename(self.current_video_path))[0] + ".srt"
            srt_path = os.path.join(output_dir, srt_filename)
            
            self.subtitle_generator.generate_srt(transcription, srt_path)
            self.current_srt_file = srt_path
            
            self.log(f"✅ Đã tạo phụ đề thành công: {srt_filename}")
            self.subtitle_status_label.setText(f"✅ Đã tạo: {srt_filename}")
            self.subtitle_status_label.setStyleSheet("color: #27ae60; font-size: 8pt; font-weight: bold;")
            
            QMessageBox.information(self, "Thành công", f"Đã tạo phụ đề thành công!\n\nFile: {srt_filename}")
            
        except Exception as e:
            self.log(f"❌ Lỗi tạo phụ đề: {str(e)}")
            self.subtitle_status_label.setText("❌ Lỗi tạo phụ đề")
            self.subtitle_status_label.setStyleSheet("color: #e74c3c; font-size: 8pt;")
            QMessageBox.critical(self, "Lỗi", f"Không thể tạo phụ đề:\n{str(e)}")
        
        finally:
            self.is_generating_subtitles = False
            self.generate_subtitle_btn.setEnabled(True)
            self.subtitle_progress.setVisible(False)


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

    def update_part_ui(self):
        """Ẩn/hiện cấu hình part"""
        is_checked = self.show_part_checkbox.isChecked()
        self.part_details_container.setVisible(is_checked)

    def detect_and_display_gpu(self):
        """Phát hiện và hiển thị thông tin GPU"""
        gpu_info = detect_gpu_encoder()
        if gpu_info:
            encoder_name, _, _ = gpu_info
            gpu_names = {
                'h264_nvenc': '✅ NVIDIA NVENC',
                'h264_amf': '✅ AMD AMF',
                'h264_qsv': '✅ Intel QSV',
                'h264_videotoolbox': '✅ Apple VideoToolbox'
            }
            display_name = gpu_names.get(encoder_name, f'✅ {encoder_name}')
            self.gpu_info_label.setText(f"Đã phát hiện: {display_name}")
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

        # Tạo QLabel để hiển thị thumbnail
        self.preview_label = QLabel()
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setMinimumHeight(240)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setText("Chưa có video")
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
                dummy_thread.create_overlay_image(current_preview_title, part_text, temp_overlay)

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
            self.text_bg_color = (color.red(), color.green(), color.blue(), 180)
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
        if mode == "single":
            self.video_input.setPlaceholderText("Chọn video...")
            if hasattr(self, 'batch_folder_container'):
                self.batch_folder_container.setVisible(False)
        else:
            self.video_input.setPlaceholderText("Chọn thư mục chứa video...")
            if hasattr(self, 'batch_folder_container'):
                self.batch_folder_container.setVisible(True)
            
        self.video_input.setText("")
        self.current_video_path = None
        
        # Xóa các widget cũ
        if hasattr(self, 'video_item_widgets'):
            for w in self.video_item_widgets:
                self.video_items_layout.removeWidget(w)
                w.deleteLater()
            self.video_item_widgets.clear()
        
        self.empty_video_label.setText("Chưa có video nào. Hãy chọn " + ("video" if mode == "single" else "thư mục") + " nguồn.")
        self.empty_video_label.setVisible(True)
        self.update_preview()

    def select_video(self):
        if self.processing_mode == "single":
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "Chọn video",
                "",
                "Video Files (*.mp4 *.avi *.mov *.mkv *.webm);;All Files (*)"
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
            
            video_extensions = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.MP4', '.AVI', '.MOV')
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
    
    def start_processing(self):
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
                    # Mỗi video xuất vào subfolder tên = tiêu đề video
                    safe_title = title.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
                    dest_dir = os.path.join(out_base, safe_title)
                elif use_distribute:
                    # Thu thập các thư mục đã có sẵn và đếm số lượng video (chỉ làm 1 lần)
                    if not hasattr(self, '_cached_distribute_folders'):
                        try:
                            subfolders = [d for d in os.listdir(out_base) if os.path.isdir(os.path.join(out_base, d))]
                            self._cached_distribute_folders = []
                            for d in subfolders:
                                folder_path = os.path.join(out_base, d)
                                current_count = 0
                                video_exts = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.MP4', '.AVI', '.MOV')
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
        
        # Generate subtitles automatically if enabled
        subtitle_file_to_use = None
        if self.enable_subtitles:
            self.log("🎤 Phụ đề được bật - bắt đầu tạo phụ đề tự động...")
            
            # Update progress bar to show subtitle generation
            self.progress_bar.setMaximum(0)  # Indeterminate mode
            self.progress_label.setText("Đang tạo phụ đề tự động...")
            self.status_display.setText("🟡 Đang tạo phụ đề...")
            
            self.subtitle_status_label.setText("Đang tạo phụ đề...")
            self.subtitle_status_label.setStyleSheet("color: #f39c12; font-size: 8pt; font-weight: bold;")
            
            # Get subtitle settings
            language_code = self.subtitle_language_combo.currentData()
            language_name = self.subtitle_language_combo.currentText()
            model_size = self.whisper_model_combo.currentData()
            
            self.log(f"   Ngôn ngữ: {language_name}")
            self.log(f"   Model: {model_size}")
            
            # Force UI update
            QApplication.processEvents()
            
            try:
                # Create subtitle generator if not exists
                if self.subtitle_generator is None or self.subtitle_generator.model_size != model_size:
                    self.progress_label.setText(f"Đang tải Whisper AI model ({model_size})...")
                    QApplication.processEvents()
                    
                    self.subtitle_generator = SubtitleGenerator(model_size=model_size)
                    self.log(f"✅ Đã khởi tạo Whisper AI (device: {self.subtitle_generator.device.upper()})")
                
                def progress_callback(message):
                    self.log(message)
                    # Update progress label with current step
                    if "Extracting audio" in message:
                        self.progress_label.setText("Đang trích xuất audio từ video...")
                    elif "Transcribing audio" in message:
                        self.progress_label.setText("Đang nhận dạng giọng nói (có thể mất vài phút)...")
                    elif "Using cached" in message:
                        self.progress_label.setText("Sử dụng phụ đề đã cache...")
                    elif "Transcription complete" in message:
                        self.progress_label.setText("Đang tạo file SRT...")
                    QApplication.processEvents()  # Update UI
                
                # Transcribe video
                self.progress_label.setText("Đang phân tích video...")
                QApplication.processEvents()
                
                transcription = self.subtitle_generator.transcribe_video(
                    src_file,
                    language=language_code,
                    use_cache=True,
                    progress_callback=progress_callback
                )
                
                # Generate SRT file
                self.progress_label.setText("Đang tạo file phụ đề SRT...")
                QApplication.processEvents()
                
                output_dir = os.path.dirname(src_file)
                srt_filename = os.path.splitext(os.path.basename(src_file))[0] + ".srt"
                srt_path = os.path.join(output_dir, srt_filename)
                
                self.subtitle_generator.generate_srt(transcription, srt_path)
                subtitle_file_to_use = srt_path
                
                self.log(f"✅ Đã tạo phụ đề: {srt_filename}")
                self.subtitle_status_label.setText(f"✅ Đã tạo: {srt_filename}")
                self.subtitle_status_label.setStyleSheet("color: #27ae60; font-size: 8pt; font-weight: bold;")
                
                # Reset progress bar
                self.progress_bar.setMaximum(100)
                self.progress_label.setText("Chuẩn bị xử lý video...")
                self.status_display.setText("🟡 Đang xử lý...")
                QApplication.processEvents()
                
            except Exception as e:
                self.log(f"❌ Lỗi tạo phụ đề: {str(e)}")
                self.subtitle_status_label.setText("❌ Lỗi tạo phụ đề")
                self.subtitle_status_label.setStyleSheet("color: #e74c3c; font-size: 8pt;")
                
                # Reset progress bar
                self.progress_bar.setMaximum(100)
                
                # Ask user if they want to continue without subtitles
                reply = QMessageBox.question(
                    self, 
                    "Lỗi tạo phụ đề",
                    f"Không thể tạo phụ đề:\n{str(e)}\n\nBạn có muốn tiếp tục xử lý video không có phụ đề?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply == QMessageBox.StandardButton.No:
                    # Reset UI
                    self.process_btn.setEnabled(True)
                    self.process_btn.setText("▶️ BẮT ĐẦU XỬ LÝ")
                    self.stop_btn.setEnabled(False)
                    self.progress_bar.setVisible(False)
                    self.status_display.setText("🔴 Đã hủy")
                    self.progress_label.setText("Đã hủy do lỗi tạo phụ đề")
                    return
        
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

        # Start processing thread với các tham số mới (bao gồm text border)
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
            
            # Subtitle parameters - use the generated subtitle file
            subtitle_file=subtitle_file_to_use,
            subtitle_font_size=self.subtitle_font_size,
            subtitle_y_position=self.subtitle_y_position_input.value() if hasattr(self, 'subtitle_y_position_input') else 1400
        )
        
        self.thread.progress.connect(self.update_progress)
        self.thread.finished.connect(self.processing_finished)
        self.thread.start()
    
    def update_progress(self, message):
        self.progress_label.setText(f"{message}")
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
