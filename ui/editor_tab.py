import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QDoubleSpinBox, QSpinBox,
    QFileDialog, QGroupBox, QMessageBox, QCheckBox, QRadioButton, QColorDialog, QSlider, QScrollArea, QLineEdit, QComboBox, QButtonGroup
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from core.processor import ShortsProcessor
from ui.components import PrimaryButton, GhostButton, DangerButton, SmallDangerButton, StyledProgressBar

class VideoProcessorThread(QThread):
    progress = pyqtSignal(str) # Log message
    finished = pyqtSignal()
    
    def __init__(self, tasks, settings, processor):
        super().__init__()
        self.tasks = tasks
        self.settings = settings
        self.processor = processor
        self.is_running = True

    def run(self):
        self.progress.emit(f"🚀 Bắt đầu xử lý {len(self.tasks)} task...")
        try:
            for i, task in enumerate(self.tasks):
                if not self.is_running:
                    self.progress.emit("Bị gián đoạn bởi người dùng.")
                    break
                
                self.progress.emit(f"\n--- 🎞️ Đang chạy task {i+1}/{len(self.tasks)} ---")
                self.progress.emit(f"Nguồn: {task['source']}")
                self.progress.emit(f"Đích: {task['output']}")
                
                self.processor.process_compilations(
                    task['source'], 
                    task['output'], 
                    self.settings,
                    progress_callback=self.emit_log,
                    check_cancel=self.check_cancel
                )
        except Exception as e:
            self.progress.emit(f"Critical Error: {e}")
        self.finished.emit()

    def emit_log(self, msg):
        self.progress.emit(msg)

    def check_cancel(self):
        return not self.is_running
        
    def stop(self):
        self.is_running = False

class EstimationThread(QThread):
    """Background thread for calculating compilation estimation for multiple tasks"""
    finished = pyqtSignal(list, int)  # (list of (estimated, video_count), total_videos)
    
    def __init__(self, tasks_sources, settings, processor):
        super().__init__()
        self.tasks_sources = tasks_sources
        self.settings = settings
        self.processor = processor
    
    def run(self):
        results = []
        total_videos = 0
        try:
            for sources in self.tasks_sources:
                if not sources:
                    results.append((-1, 0))
                    continue
                
                task_estimated = 0
                task_video_count = 0
                for src in sources:
                    if not src or src == "Not Selected" or not os.path.exists(src):
                        continue
                    
                    # estimate_compilations now returns (estimated_compilations, valid_files_count)
                    estimated, video_count = self.processor.estimate_compilations(src, self.settings)
                    
                    task_estimated += estimated
                    task_video_count += video_count
                
                total_videos += task_video_count
                results.append((task_estimated, task_video_count))
                
            self.finished.emit(results, total_videos)
        except Exception as e:
            # Send an array of errors if it unexpectedly crashes
            self.finished.emit([(-1, 0)] * len(self.tasks_sources), 0)

class EditorTaskWidget(QGroupBox):
    def __init__(self, remove_callback=None, param_callback=None, task_index=1):
        super().__init__(f"🎞️ Task {task_index}")
        self.remove_callback = remove_callback
        self.param_callback = param_callback # triggers estimation
        
        # No inline groupbox style — delegated to global QSS
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 15, 10, 10)
        
        # Source
        src_layout = QHBoxLayout()
        self.src_btn = QPushButton("📁 Folder Nguồn")
        self.src_btn.setFixedWidth(140)
        self.src_btn.clicked.connect(self.browse_source)
        self.src_label = QLabel("Not Selected")
        self.src_label.setWordWrap(True)
        self.src_label.setStyleSheet("color: #64748B; font-size: 12px; background: transparent; border: none;")
        src_layout.addWidget(self.src_btn)
        src_layout.addWidget(self.src_label, 1) # Give stretch
        layout.addLayout(src_layout)

        # Output
        dst_layout = QHBoxLayout()
        self.dst_btn = QPushButton("📁 Folder Đích")
        self.dst_btn.setFixedWidth(140)
        self.dst_btn.clicked.connect(self.browse_output)
        self.dst_label = QLabel("Not Selected")
        self.dst_label.setWordWrap(True)
        self.dst_label.setStyleSheet("color: #64748B; font-size: 12px; background: transparent; border: none;")
        dst_layout.addWidget(self.dst_btn)
        dst_layout.addWidget(self.dst_label, 1) # Give stretch
        if self.remove_callback:
            self.remove_btn = SmallDangerButton("❌ Xóa")
            self.remove_btn.setFixedWidth(70)
            self.remove_btn.clicked.connect(lambda: self.remove_callback(self))
            dst_layout.addWidget(self.remove_btn)

        layout.addLayout(dst_layout)

        # Subfolder Mode Row
        subfolder_row = QHBoxLayout()
        subfolder_row.addWidget(QLabel("📂 Chế độ subfolder:"))
        self.subfolder_mode_group = QButtonGroup(self)
        self.subfolder_mode_direct = QRadioButton("Xử lý trực tiếp")
        self.subfolder_mode_direct.setChecked(True)
        self.subfolder_mode_direct.setToolTip("Xử lý video ngay trong folder nguồn, xuất thẳng ra folder đích.")
        self.subfolder_mode_auto = QRadioButton("Tự tạo folder theo tên nguồn")
        self.subfolder_mode_auto.setToolTip(
            "Folder nguồn chứa các subfolder B,C,D → tự tạo F/B, F/C, F/D trong folder đích."
        )
        self.subfolder_mode_map = QRadioButton("Ánh xạ vào folder đích có sẵn")
        self.subfolder_mode_map.setToolTip(
            "Folder đích đã có F1,F2,F3 → ánh xạ lần lượt theo thứ tự: subfolder nguồn B→F1, C→F2, D→F3."
        )
        self.subfolder_mode_group.addButton(self.subfolder_mode_direct, 0)
        self.subfolder_mode_group.addButton(self.subfolder_mode_auto, 1)
        self.subfolder_mode_group.addButton(self.subfolder_mode_map, 2)
        for rb in (self.subfolder_mode_direct, self.subfolder_mode_auto, self.subfolder_mode_map):
            rb.toggled.connect(self._on_subfolder_mode_changed)
        subfolder_row.addWidget(self.subfolder_mode_direct)
        subfolder_row.addSpacing(12)
        subfolder_row.addWidget(self.subfolder_mode_auto)
        subfolder_row.addSpacing(12)
        subfolder_row.addWidget(self.subfolder_mode_map)
        subfolder_row.addStretch()
        layout.addLayout(subfolder_row)

        # Estimation Label
        self.est_label = QLabel("Chưa chọn nguồn")
        self.est_label.setWordWrap(True)
        self.est_label.setStyleSheet("color: #64748B; font-size: 11px; font-style: italic; background: transparent; border: none;")
        layout.addWidget(self.est_label)

    def _on_subfolder_mode_changed(self):
        if self.param_callback:
            self.param_callback()

    def browse_source(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Source Directory")
        if folder:
            self.src_label.setText(folder)
            if self.param_callback:
                self.param_callback()

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if folder:
            self.dst_label.setText(folder)

    def get_subfolder_mode(self):
        if self.subfolder_mode_auto.isChecked():
            return 'auto_create'
        if self.subfolder_mode_map.isChecked():
            return 'map_existing'
        return 'direct'

    def get_data(self):
        return {
            'source': self.src_label.text(),
            'output': self.dst_label.text(),
            'subfolder_mode': self.get_subfolder_mode(),
        }

    def set_data(self, data):
        if 'source' in data:
            self.src_label.setText(data['source'])
        if 'output' in data:
            self.dst_label.setText(data['output'])
        if 'subfolder_mode' in data:
            mode = data['subfolder_mode']
            if mode == 'auto_create':
                self.subfolder_mode_auto.setChecked(True)
            elif mode == 'map_existing':
                self.subfolder_mode_map.setChecked(True)
            else:
                self.subfolder_mode_direct.setChecked(True)
        if self.param_callback:
            self.param_callback()

    def set_estimation(self, estimated, video_count, skip_merge, target_duration):
        if estimated == -1:
            self.est_label.setText("⚠️ Thư mục Nguồn Lỗi hoặc Trống")
        else:
            if skip_merge:
                if video_count > 0:
                    self.est_label.setText(f"📊 {video_count} video Nguồn -> Edit tách lẻ {video_count} video output.")
                else:
                    self.est_label.setText("⚠️ Không tìm thấy file video hợp lệ.")
            else:
                if estimated > 0:
                    self.est_label.setText(f"📊 {video_count} video Nguồn -> Dự kiến ghép thành {estimated} clip dài (~{target_duration}s).")
                else:
                    self.est_label.setText(f"⚠️ {video_count} video Nguồn -> Không đủ thời lượng cắt ghép (cần min {target_duration}s).")
        
    def set_enabled(self, enabled):
        self.src_btn.setEnabled(enabled)
        self.dst_btn.setEnabled(enabled)
        self.subfolder_mode_direct.setEnabled(enabled)
        self.subfolder_mode_auto.setEnabled(enabled)
        self.subfolder_mode_map.setEnabled(enabled)
        if hasattr(self, 'remove_btn'):
            self.remove_btn.setEnabled(enabled)


class EditorTab(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.processor_thread = None
        self.estimation_thread = None
        self.processor = ShortsProcessor()
        
        # Overlay Settings
        self.overlay_color = (0, 0, 0)
        self.overlay_opacity = 0
        
        # Debounce timer for estimation updates
        self.estimation_timer = QTimer()
        self.estimation_timer.setSingleShot(True)
        self.estimation_timer.timeout.connect(self.update_estimation)
        
        self.setup_ui()
        
        # Auto-load last saved configuration silently if it exists
        try:
            self.load_config(silent=True)
        except Exception:
            pass

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

        self.task_widgets = []
        self.task_counter = 0
        
        tasks_action_container = QWidget()
        tasks_action_layout = QHBoxLayout(tasks_action_container)
        tasks_action_layout.setContentsMargins(0, 16, 0, 0)
        tasks_action_layout.setSpacing(10)
        
        self.add_task_btn = PrimaryButton("➕ Thêm Tác Vụ")
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

        self.add_task_widget(is_first=True)

        # -- Parameters (Global) --
        param_group = QGroupBox("Global Editing Parameters")
        param_layout = QHBoxLayout()

        # Speed
        speed_layout = QVBoxLayout()
        speed_layout.addWidget(QLabel("Speed (x)"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.1, 10.0) 
        self.speed_spin.setSingleStep(0.1)
        self.speed_spin.setValue(1.0)
        self.speed_spin.valueChanged.connect(self.update_estimation_debounced)
        speed_layout.addWidget(self.speed_spin)
        param_layout.addLayout(speed_layout)

        # Scale X
        scalex_layout = QVBoxLayout()
        scalex_layout.addWidget(QLabel("Scale X"))
        self.scalex_spin = QDoubleSpinBox()
        self.scalex_spin.setRange(0.1, 5.0)
        self.scalex_spin.setSingleStep(0.05)
        self.scalex_spin.setValue(1.0)
        scalex_layout.addWidget(self.scalex_spin)
        param_layout.addLayout(scalex_layout)

        # Scale Y
        scaley_layout = QVBoxLayout()
        scaley_layout.addWidget(QLabel("Scale Y"))
        self.scaley_spin = QDoubleSpinBox()
        self.scaley_spin.setRange(0.1, 5.0)
        self.scaley_spin.setSingleStep(0.05)
        self.scaley_spin.setValue(1.0)
        scaley_layout.addWidget(self.scaley_spin)
        param_layout.addLayout(scaley_layout)
        
        # Offset X
        offx_layout = QVBoxLayout()
        offx_layout.addWidget(QLabel("Pos X (px)"))
        self.offx_spin = QSpinBox()
        self.offx_spin.setRange(-1000, 1000)
        self.offx_spin.setValue(0)
        offx_layout.addWidget(self.offx_spin)
        param_layout.addLayout(offx_layout)

        # Offset Y
        offy_layout = QVBoxLayout()
        offy_layout.addWidget(QLabel("Pos Y (px)"))
        self.offy_spin = QSpinBox()
        self.offy_spin.setRange(-1000, 1000)
        self.offy_spin.setValue(0)
        offy_layout.addWidget(self.offy_spin)
        param_layout.addLayout(offy_layout)
        
        # Min videos
        min_videos_layout = QVBoxLayout()
        min_videos_layout.addWidget(QLabel("Ghép tối thiểu (Video)"))
        self.min_videos_spin = QSpinBox()
        self.min_videos_spin.setRange(1, 100)
        self.min_videos_spin.setValue(2) # Default at least 2
        self.min_videos_spin.setToolTip("Số video tối thiểu cần ghép trong 1 clip")
        self.min_videos_spin.valueChanged.connect(self.update_estimation_debounced)
        min_videos_layout.addWidget(self.min_videos_spin)
        param_layout.addLayout(min_videos_layout)
        
        # Only under 1 min filter
        only_under_1min_layout = QVBoxLayout()
        only_under_1min_layout.addWidget(QLabel("Lọc Đầu Vào"))
        self.only_under_1min_checkbox = QCheckBox("Chỉ lấy video < 1p")
        self.only_under_1min_checkbox.stateChanged.connect(self.update_estimation_debounced)
        self.only_under_1min_checkbox.setToolTip("Loại bỏ hoàn toàn các video dài trên 1 phút khỏi danh sách xử lý")
        only_under_1min_layout.addWidget(self.only_under_1min_checkbox)
        
        self.trim_long_videos_checkbox = QCheckBox("Cắt ngẫu nhiên đuôi video > 1p")
        self.trim_long_videos_checkbox.stateChanged.connect(self.update_estimation_debounced)
        self.trim_long_videos_checkbox.setToolTip("Tự động cắt ngẫu nhiên phần đuôi các video dài trên 1 phút (giữ lại 30-55s)")
        only_under_1min_layout.addWidget(self.trim_long_videos_checkbox)
        
        param_layout.addLayout(only_under_1min_layout)
        
        # Target Duration
        self.duration_container = QWidget()
        duration_layout = QVBoxLayout(self.duration_container)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        duration_layout.addWidget(QLabel("Thời lượng video"))
        
        self.duration_under_1min = QRadioButton("< 1 phút (max 59s)")
        self.duration_under_1min.setChecked(True)
        self.duration_under_1min.setToolTip("Video tối đa 59s")
        self.duration_under_1min.toggled.connect(self.update_estimation_debounced)
        duration_layout.addWidget(self.duration_under_1min)
        
        self.duration_over_1min = QRadioButton("≥ 1 phút (min 60s)")
        self.duration_over_1min.setToolTip("Video tối thiểu 60s")
        self.duration_over_1min.toggled.connect(self.update_estimation_debounced)
        duration_layout.addWidget(self.duration_over_1min)
        
        self.duration_free = QRadioButton("Gộp thường (không cắt)")
        self.duration_free.setToolTip("Gộp video mà không cắt hay giới hạn thời lượng — video > 1 phút vẫn được giữ nguyên")
        self.duration_free.toggled.connect(self.update_estimation_debounced)
        duration_layout.addWidget(self.duration_free)
        
        param_layout.addWidget(self.duration_container)
        param_group.setLayout(param_layout)
        layout.addWidget(param_group)
        
        # -- Anti-Detect (Bypass TikTok) --
        anti_detect_group = QGroupBox("Hiệu ứng")
        anti_detect_layout = QHBoxLayout()
        
        self.hflip_checkbox = QCheckBox("Lật")
        self.hflip_checkbox.setStyleSheet("font-weight: bold; color: #d35400;")
        self.hflip_checkbox.setToolTip("Video đầu giữ nguyên, các video ghép phía sau sẽ được lật ngẫu nhiên")
        anti_detect_layout.addWidget(self.hflip_checkbox)
        
        self.random_color_checkbox = QCheckBox("Random màu sắc")
        self.random_color_checkbox.setStyleSheet("font-weight: bold; color: #d35400;")
        self.random_color_checkbox.setToolTip("Xáo trộn nhẹ độ sáng, tương phản để đổi mã pixel từng video")
        anti_detect_layout.addWidget(self.random_color_checkbox)

        self.film_grain_checkbox = QCheckBox("Nhiễu hạt")
        self.film_grain_checkbox.setStyleSheet("font-weight: bold; color: #d35400;")
        self.film_grain_checkbox.setToolTip("Phủ lớp nhiễu động siêu mờ để qua mặt check trùng khớp khung hình (Frame by Frame)")
        anti_detect_layout.addWidget(self.film_grain_checkbox)
        
        anti_detect_layout.addStretch()
        anti_detect_group.setLayout(anti_detect_layout)
        layout.addWidget(anti_detect_group)
        
        # -- Output Prefix --
        prefix_group = QGroupBox("Đổi tên File Đích")
        prefix_layout = QHBoxLayout()
        prefix_layout.addWidget(QLabel("Tiền tố (Prefix):"))
        self.output_prefix_input = QLineEdit()
        self.output_prefix_input.setPlaceholderText("VD: My Prefix -> Kết quả: My Prefix - ten_file_goc.mp4 (Để trống nếu muốn giữ nguyên)")
        prefix_layout.addWidget(self.output_prefix_input)

        prefix_layout.addSpacing(16)
        self.date_naming_checkbox = QCheckBox("📅 Tên theo ngày tháng (ddmmyyNN)")
        self.date_naming_checkbox.setToolTip(
            "Đặt tên file theo định dạng ngày tháng: ddmmyyNN (ví dụ: 14052601, 14052602...)\n"
            "Giống format bên AutoCut. Tự động tăng số thứ tự để không bao giờ trùng."
        )
        prefix_layout.addWidget(self.date_naming_checkbox)

        prefix_group.setLayout(prefix_layout)
        layout.addWidget(prefix_group)
        
        # -- Color Overlay Base Option --
        overlay_group = QGroupBox("Cấu hình chung")
        overlay_layout = QHBoxLayout()
        
        overlay_layout.addWidget(QLabel("Màu phủ:"))
        self.overlay_color_label = QLabel("")
        self.overlay_color_label.setProperty("colorPreview", True)
        self.overlay_color_label.setStyleSheet(f"background-color: rgb{self.overlay_color}; min-width: 30px;")
        overlay_layout.addWidget(self.overlay_color_label)

        overlay_color_btn = QPushButton("⚙️")
        overlay_color_btn.setMaximumWidth(30)
        overlay_color_btn.clicked.connect(self.select_overlay_color)
        overlay_layout.addWidget(overlay_color_btn)
        
        overlay_layout.addSpacing(10)

        overlay_layout.addWidget(QLabel("Mờ %:"))
        self.overlay_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.overlay_opacity_slider.setRange(0, 100)
        self.overlay_opacity_slider.setFixedWidth(80)
        self.overlay_opacity_slider.setValue(self.overlay_opacity)
        self.overlay_opacity_slider.valueChanged.connect(self.update_overlay_opacity_display)
        overlay_layout.addWidget(self.overlay_opacity_slider)

        self.overlay_opacity_label = QLabel(f"{self.overlay_opacity}%")
        self.overlay_opacity_label.setFixedWidth(35)
        overlay_layout.addWidget(self.overlay_opacity_label)
        
        overlay_layout.addSpacing(20)
        
        self.sort_by_views_radio = QRadioButton("Ưu tiên View Cao")
        self.sort_by_views_radio.setChecked(True)  
        self.sort_by_views_radio.toggled.connect(self.update_estimation_debounced)
        overlay_layout.addWidget(self.sort_by_views_radio)
        
        self.random_shuffle_radio = QRadioButton("Xáo trộn Video")
        self.random_shuffle_radio.toggled.connect(self.update_estimation_debounced)
        overlay_layout.addWidget(self.random_shuffle_radio)

        overlay_layout.addSpacing(20)

        self.skip_merge_checkbox = QCheckBox("Không Ghép (Chỉ Edit lẻ)")
        self.skip_merge_checkbox.setStyleSheet("font-weight: bold; color: #d35400;")
        self.skip_merge_checkbox.stateChanged.connect(self.update_estimation_debounced)
        self.skip_merge_checkbox.stateChanged.connect(self.toggle_duration_visibility)
        overlay_layout.addWidget(self.skip_merge_checkbox)
        
        overlay_layout.addSpacing(10)
        
        self.gpu_checkbox = QCheckBox("Sử dụng GPU")
        self.gpu_checkbox.setChecked(True)
        self.gpu_checkbox.setStyleSheet("font-weight: bold; color: #27ae60;")
        self.gpu_checkbox.setToolTip("Sử dụng Card đồ họa (NVIDIA/AMD/Intel) để xử lý nhanh hơn")
        overlay_layout.addWidget(self.gpu_checkbox)
        
        overlay_layout.addStretch()
        
        overlay_layout.addWidget(QLabel("Số luồng:"))
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 16)
        self.workers_spin.setValue(4)
        self.workers_spin.setFixedWidth(60)
        overlay_layout.addWidget(self.workers_spin)
        
        overlay_group.setLayout(overlay_layout)
        layout.addWidget(overlay_group)

        # -- Global Estimation Info --
        self.global_est_label = QLabel("📊 Thêm tác vụ và chọn Thư mục Nguồn để máy tính toán.")
        self.global_est_label.setWordWrap(True)
        self.global_est_label.setStyleSheet("color: #0d6efd; font-weight: bold; padding: 5px;")
        layout.addWidget(self.global_est_label)

        # -- Actions --
        actions_container = QWidget()
        actions_layout = QHBoxLayout(actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(10)
        
        self.run_btn = PrimaryButton("▶ Start Processing")
        self.run_btn.setFixedHeight(50)
        self.run_btn.clicked.connect(self.start_processing)
        actions_layout.addWidget(self.run_btn, 1)

        self.stop_btn = DangerButton("⏹ Stop Processing")
        self.stop_btn.setFixedHeight(50)
        self.stop_btn.clicked.connect(self.stop_processing)
        self.stop_btn.setEnabled(False)
        actions_layout.addWidget(self.stop_btn, 1)
        
        layout.addWidget(actions_container)
        
        # -- Progress Bar --
        self.progress_bar = StyledProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addStretch()

    def add_task_widget(self, is_first=False):
        self.task_counter += 1
        widget = EditorTaskWidget(
            remove_callback=self.remove_task_widget, 
            param_callback=self.update_estimation_debounced,
            task_index=self.task_counter
        )
        if is_first:
             if hasattr(widget, 'remove_btn'):
                 widget.remove_btn.hide()
                 
        self.tasks_layout.addWidget(widget)
        self.task_widgets.append(widget)
        
        if len(self.task_widgets) > 1:
            for w in self.task_widgets:
                if hasattr(w, 'remove_btn'):
                    w.remove_btn.show()
        self.update_estimation_debounced()

    def remove_task_widget(self, widget):
        if len(self.task_widgets) > 1:
            self.tasks_layout.removeWidget(widget)
            self.task_widgets.remove(widget)
            widget.deleteLater()
            
            if len(self.task_widgets) == 1:
                if hasattr(self.task_widgets[0], 'remove_btn'):
                    self.task_widgets[0].remove_btn.hide()
            self.update_estimation_debounced()

    def save_config(self):
        import json
        import os
        settings_dir = os.path.join(os.getcwd(), "settings")
        os.makedirs(settings_dir, exist_ok=True)
        file_path = os.path.join(settings_dir, "editor_config.json")
        
        # Save both tasks data and all global UI parameters
        config_data = {
            "tasks": [w.get_data() for w in self.task_widgets],
            "global_settings": self.get_current_settings()
        }
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "Thành công", f"Đã tự động lưu cấu hình vào:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu cấu hình:\n{e}")

    def apply_global_settings(self, s):
        """Restores all saved settings to the respective UI widgets safely."""
        # 1. Min videos to merge
        if 'min_videos' in s and hasattr(self, 'min_videos_spin'):
            self.min_videos_spin.setValue(int(s['min_videos']))
        
        # 2. Speeds
        if 'speed' in s and hasattr(self, 'speed_spin'):
            self.speed_spin.setValue(float(s['speed']))
            
        # 3. Scales
        if 'scale_x' in s and hasattr(self, 'scalex_spin'):
            self.scalex_spin.setValue(float(s['scale_x']))
        if 'scale_y' in s and hasattr(self, 'scaley_spin'):
            self.scaley_spin.setValue(float(s['scale_y']))
            
        # 4. Offsets (Positions)
        if 'offset_x' in s and hasattr(self, 'offx_spin'):
            self.offx_spin.setValue(int(s['offset_x']))
        if 'offset_y' in s and hasattr(self, 'offy_spin'):
            self.offy_spin.setValue(int(s['offset_y']))
            
        # 5. Skip merge mode (Không Ghép / Chỉ Edit lẻ)
        if 'skip_merge' in s and hasattr(self, 'skip_merge_checkbox'):
            self.skip_merge_checkbox.setChecked(bool(s['skip_merge']))
            self.toggle_duration_visibility()
            
        # 6. Sorting / prioritization (Ưu tiên view / Xáo trộn)
        if 'sort_by_views' in s and hasattr(self, 'sort_by_views_radio') and hasattr(self, 'random_shuffle_radio'):
            if s['sort_by_views']:
                self.sort_by_views_radio.setChecked(True)
            else:
                self.random_shuffle_radio.setChecked(True)
                
        # 7. Target Duration Selection
        if 'duration_mode' in s and hasattr(self, 'duration_under_1min') and hasattr(self, 'duration_free') and hasattr(self, 'duration_over_1min'):
            mode = s['duration_mode']
            if mode == 'max':
                self.duration_under_1min.setChecked(True)
            elif mode == 'free':
                self.duration_free.setChecked(True)
            else:
                self.duration_over_1min.setChecked(True)
                
        # 8. Overlay Color and Opacity
        if 'overlay_color' in s:
            self.overlay_color = tuple(s['overlay_color'])
            if hasattr(self, 'overlay_color_label'):
                self.overlay_color_label.setStyleSheet(f"background-color: rgb{self.overlay_color}; min-width: 30px;")
        if 'overlay_opacity' in s and hasattr(self, 'overlay_opacity_slider') and hasattr(self, 'overlay_opacity_label'):
            self.overlay_opacity = int(s['overlay_opacity'])
            self.overlay_opacity_slider.setValue(self.overlay_opacity)
            self.overlay_opacity_label.setText(f"{self.overlay_opacity}%")
            
        # 9. Thread Count
        if 'workers' in s and hasattr(self, 'workers_spin'):
            self.workers_spin.setValue(int(s['workers']))
            
        # 10. Anti-detect / Effects
        if 'hflip' in s and hasattr(self, 'hflip_checkbox'):
            self.hflip_checkbox.setChecked(bool(s['hflip']))
        if 'random_color' in s and hasattr(self, 'random_color_checkbox'):
            self.random_color_checkbox.setChecked(bool(s['random_color']))
        if 'film_grain' in s and hasattr(self, 'film_grain_checkbox'):
            self.film_grain_checkbox.setChecked(bool(s['film_grain']))
            
        # 11. Input Filtering
        if 'only_under_1min' in s and hasattr(self, 'only_under_1min_checkbox'):
            self.only_under_1min_checkbox.setChecked(bool(s['only_under_1min']))
        if 'trim_long_videos' in s and hasattr(self, 'trim_long_videos_checkbox'):
            self.trim_long_videos_checkbox.setChecked(bool(s['trim_long_videos']))
            
        # 12. Output Naming / Prefix
        if 'output_prefix' in s and hasattr(self, 'output_prefix_input'):
            self.output_prefix_input.setText(str(s['output_prefix']))
        if 'date_naming' in s and hasattr(self, 'date_naming_checkbox'):
            self.date_naming_checkbox.setChecked(bool(s['date_naming']))
            
        # 13. GPU Use
        if 'use_gpu' in s and hasattr(self, 'gpu_checkbox'):
            self.gpu_checkbox.setChecked(bool(s['use_gpu']))

    def load_config(self, silent=False):
        # PyQt6 clicked signal checked parameter is passed as first arg when connected directly.
        # Force silent=False if it's a bool that comes from a button click instead of an explicit silent=True call.
        if isinstance(silent, bool) and silent is False:
            pass
        elif not isinstance(silent, bool):
            silent = False

        import json
        import os
        file_path = os.path.join(os.getcwd(), "settings", "editor_config.json")
        
        if not os.path.exists(file_path):
            if not silent:
                QMessageBox.warning(self, "Chưa có cấu hình", "Bạn chưa lưu cấu hình Editor nào (chưa có file editor_config.json trong thư mục settings).")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # Support legacy format (list) and new format (dict)
            if isinstance(config_data, list):
                tasks_data = config_data
                global_settings = None
            elif isinstance(config_data, dict):
                tasks_data = config_data.get("tasks", [])
                global_settings = config_data.get("global_settings", None)
            else:
                raise ValueError("Định dạng cấu hình không hợp lệ.")
            
            # Clear old tasks
            while len(self.task_widgets) > 0:
                widget = self.task_widgets.pop()
                self.tasks_layout.removeWidget(widget)
                widget.deleteLater()
            self.task_counter = 0

            # Add tasks from file
            for i, data in enumerate(tasks_data):
                self.add_task_widget(is_first=(i==0))
                self.task_widgets[-1].set_data(data)
            
            # Fallback for empty list
            if not self.task_widgets:
                self.add_task_widget(is_first=True)

            # Apply saved global settings
            if global_settings:
                self.apply_global_settings(global_settings)

            self.update_estimation_debounced()
            if not silent:
                QMessageBox.information(self, "Thành công", "Đã tải cấu hình Editor tự động!")
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Lỗi", f"Không thể tải cấu hình:\n{e}")

    def update_overlay_opacity_display(self, value):
        self.overlay_opacity = value
        self.overlay_opacity_label.setText(f"{value}%")

    def select_overlay_color(self):
        color = QColorDialog.getColor(QColor(*self.overlay_color))
        if color.isValid():
            self.overlay_color = (color.red(), color.green(), color.blue())
            self.overlay_color_label.setStyleSheet(f"background-color: rgb{self.overlay_color}; min-width: 30px;")
            if hasattr(self, 'log_message'):
                self.log_message.emit(f"Đã chọn màu lớp phủ: RGB{self.overlay_color}")

    def get_target_duration(self):
        if self.duration_under_1min.isChecked():
            return 55
        elif self.duration_free.isChecked():
            return 60  # Dùng 60s làm target mặc định nhưng không giới hạn
        else:
            return 60
    
    def get_current_settings(self):
        return {
            'min_videos': getattr(self, 'min_videos_spin', None) and self.min_videos_spin.value() or 2,
            'speed': self.speed_spin.value(),
            'scale_x': self.scalex_spin.value(),
            'scale_y': self.scaley_spin.value(),
            'offset_x': self.offx_spin.value(),
            'offset_y': self.offy_spin.value(),
            'skip_merge': self.skip_merge_checkbox.isChecked(),
            'sort_by_views': self.sort_by_views_radio.isChecked(),
            'target_duration': self.get_target_duration(),
            'duration_mode': 'max' if self.duration_under_1min.isChecked() else ('free' if self.duration_free.isChecked() else 'min'),
            'overlay_color': self.overlay_color,
            'overlay_opacity': self.overlay_opacity,
            'workers': self.workers_spin.value(),
            'hflip': getattr(self, 'hflip_checkbox', None) and self.hflip_checkbox.isChecked(),
            'random_color': getattr(self, 'random_color_checkbox', None) and self.random_color_checkbox.isChecked(),
            'film_grain': getattr(self, 'film_grain_checkbox', None) and self.film_grain_checkbox.isChecked(),
            'only_under_1min': self.only_under_1min_checkbox.isChecked(),
            'trim_long_videos': getattr(self, 'trim_long_videos_checkbox', None) and self.trim_long_videos_checkbox.isChecked(),
            'output_prefix': getattr(self, 'output_prefix_input', None) and self.output_prefix_input.text().strip(),
            'date_naming': getattr(self, 'date_naming_checkbox', None) and self.date_naming_checkbox.isChecked(),
            'use_gpu': self.gpu_checkbox.isChecked(),
        }

    def toggle_duration_visibility(self):
        """Show/Hide duration selection depending on merge mode"""
        is_skipping = self.skip_merge_checkbox.isChecked()
        if hasattr(self, 'duration_container'):
            self.duration_container.setVisible(not is_skipping)

    def update_estimation_debounced(self):
        self.estimation_timer.stop()
        self.estimation_timer.start(500)
    
    def update_estimation(self):
        raw_tasks = [w.get_data() for w in self.task_widgets]
        
        self.global_est_label.setText("⏳ Đang thiết lập bảng tính dữ liệu...")
        self.run_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(0)
        
        settings = self.get_current_settings()
        
        tasks_sources = []
        for task in raw_tasks:
            if not task['source'] or task['source'] == "Not Selected" or not os.path.exists(task['source']):
                tasks_sources.append([])
                continue
                
            # Temporarily set output if missing to prevent expansion errors
            if not task.get('output') or task['output'] == "Not Selected":
                task['output'] = task['source']
                
            expanded = self._expand_subfolder_tasks([task], silent=True)
            sources = [t['source'] for t in expanded]
            tasks_sources.append(sources)
        
        if self.estimation_thread and self.estimation_thread.isRunning():
            try:
                self.estimation_thread.finished.disconnect()
            except:
                pass
            if not hasattr(self, '_old_threads'):
                self._old_threads = []
            self._old_threads.append(self.estimation_thread)
            self._old_threads = [t for t in self._old_threads if t.isRunning()]
        
        self.estimation_thread = EstimationThread(tasks_sources, settings, self.processor)
        self.estimation_thread.finished.connect(self.on_estimation_finished)
        self.estimation_thread.start()
    
    def on_estimation_finished(self, results, total_videos):
        self.progress_bar.setVisible(False)
        
        skip_merge = self.skip_merge_checkbox.isChecked()
        target_duration = self.get_target_duration()
        is_free_mode = hasattr(self, 'duration_free') and self.duration_free.isChecked()
        
        valid_tasks = 0
        total_estimated = 0
        
        for w, (est, v_count) in zip(self.task_widgets, results):
            w.set_estimation(est, v_count, skip_merge, target_duration)
            if est != -1:
                valid_tasks += 1
                if not skip_merge and est > 0:
                    total_estimated += est
        
        # Decide if can run
        can_run = False
        if skip_merge:
            can_run = total_videos > 0
            self.global_est_label.setText(f"📋 Tổng quát: Sẽ có {total_videos} video độc lập được xuất ra từ {valid_tasks} tác vụ.")
        else:
            can_run = total_estimated > 0
            if is_free_mode:
                self.global_est_label.setText(f"📋 Tổng quát: Dự kiến xuất {total_estimated} clip gộp (không giới hạn thời lượng) từ tổng số {total_videos} video gốc.")
            else:
                self.global_est_label.setText(f"📋 Tổng quát: Dự kiến xuất {total_estimated} clip dài (~{target_duration}s) từ tổng số {total_videos} video gốc.")
            
        self.run_btn.setEnabled(can_run)


    def _expand_subfolder_tasks(self, raw_tasks, silent=False):
        """
        Expand tasks that use subfolder modes into individual (source, output) pairs.
        
        - direct: pass through as-is.
        - auto_create: enumerate subdirs of source, create matching subdirs in output.
          e.g. source=A (has B,C,D), output=F → tasks for (A/B→F/B), (A/C→F/C), (A/D→F/D)
        - map_existing: enumerate subdirs of source (sorted), enumerate subdirs of output (sorted),
          zip them 1-to-1: source_subfolder[i] → output_subfolder[i]
          e.g. source subs [B,C,D], output subs [F1,F2,F3] → (A/B→F/F1), (A/C→F/F2), (A/D→F/F3)
        """
        def _log(msg):
            if not silent:
                self.log_message.emit(msg)
                
        expanded = []
        for task in raw_tasks:
            mode = task.get('subfolder_mode', 'direct')
            src_root = task['source']
            dst_root = task['output']

            if mode == 'direct':
                expanded.append(task)
                continue

            # Collect source subdirectories — strategy depends on mode:
            # • auto_create: only folders that currently have videos (skip empties)
            # • map_existing: ALL subfolders sorted alphabetically (ignore video presence)
            #   so the index-based mapping stays stable across multiple runs even after
            #   videos are processed and moved to unused_videos.
            video_exts = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv'}
            _SKIP_DIRS = {'unused_videos'}  # created by processor, never a real channel folder

            try:
                if mode == 'map_existing':
                    # Stable mapping: include every subfolder regardless of content
                    src_subs = sorted([
                        d for d in os.listdir(src_root)
                        if os.path.isdir(os.path.join(src_root, d))
                        and d not in _SKIP_DIRS
                    ])
                else:
                    # auto_create: only process folders that still have videos
                    src_subs = sorted([
                        d for d in os.listdir(src_root)
                        if os.path.isdir(os.path.join(src_root, d))
                        and d not in _SKIP_DIRS
                        and any(
                            f.lower().endswith(tuple(video_exts))
                            for f in os.listdir(os.path.join(src_root, d))
                        )
                    ])
            except Exception as e:
                _log(f"⚠️ Không đọc được subfolder của nguồn '{src_root}': {e}")
                expanded.append(task)  # fall back to direct
                continue

            if not src_subs:
                _log(f"⚠️ Không tìm thấy subfolder có video trong: {src_root}. Xử lý trực tiếp.")
                expanded.append(task)
                continue

            if mode == 'auto_create':
                for sub in src_subs:
                    new_task = dict(task)
                    new_task['source'] = os.path.join(src_root, sub)
                    new_task['output'] = os.path.join(dst_root, sub)
                    os.makedirs(new_task['output'], exist_ok=True)
                    new_task['subfolder_mode'] = 'direct'
                    expanded.append(new_task)
                _log(
                    f"📂 [auto_create] Tìm thấy {len(src_subs)} subfolder trong '{os.path.basename(src_root)}': "
                    + ", ".join(src_subs)
                )

            elif mode == 'map_existing':
                try:
                    dst_subs = sorted([
                        d for d in os.listdir(dst_root)
                        if os.path.isdir(os.path.join(dst_root, d))
                    ])
                except Exception as e:
                    _log(f"⚠️ Không đọc được subfolder của đích '{dst_root}': {e}")
                    expanded.append(task)
                    continue

                if not dst_subs:
                    _log(f"⚠️ Folder đích '{dst_root}' không có subfolder nào để ánh xạ. Xử lý trực tiếp.")
                    expanded.append(task)
                    continue

                pairs = list(zip(src_subs, dst_subs))
                mapping_info = ", ".join(f"{s}→{d}" for s, d in pairs)
                _log(
                    f"📂 [map_existing] Ánh xạ {len(pairs)} cặp folder: {mapping_info}"
                )
                for src_sub, dst_sub in pairs:
                    new_task = dict(task)
                    new_task['source'] = os.path.join(src_root, src_sub)
                    new_task['output'] = os.path.join(dst_root, dst_sub)
                    new_task['subfolder_mode'] = 'direct'
                    expanded.append(new_task)

                if len(src_subs) > len(dst_subs):
                    unmatched = src_subs[len(dst_subs):]
                    _log(
                        f"⚠️ {len(unmatched)} subfolder nguồn không có cặp đích (thiếu folder): {', '.join(unmatched)}"
                    )
                elif len(dst_subs) > len(src_subs):
                    unmatched = dst_subs[len(src_subs):]
                    _log(
                        f"⚠️ {len(unmatched)} subfolder đích không có cặp nguồn: {', '.join(unmatched)}"
                    )

        return expanded

    def start_processing(self):
        import time
        self.start_time = time.time()
        
        raw_tasks = []
        for i, w in enumerate(self.task_widgets):
            data = w.get_data()
            if data['source'] != "Not Selected" and data['output'] != "Not Selected":
                raw_tasks.append(data)
                
        if not raw_tasks:
            QMessageBox.warning(self, "Lỗi Input", "Vui lòng chỉ định rõ thư mục Nguồn và Đích ở ít nhất 1 tác vụ!")
            return

        # Expand subfolder tasks before processing
        tasks = self._expand_subfolder_tasks(raw_tasks)

        if not tasks:
            QMessageBox.warning(self, "Lỗi", "Không có tác vụ nào được tạo sau khi xử lý chế độ subfolder!")
            return

        settings = self.get_current_settings()

        self.run_btn.setEnabled(False)
        self.run_btn.setText("⏳ Processing...")
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(0)
        
        self.processor_thread = VideoProcessorThread(tasks, settings, self.processor)
        self.processor_thread.progress.connect(self.propagate_log)
        self.processor_thread.finished.connect(self.on_finished)
        self.processor_thread.start()
    
    def stop_processing(self):
        if self.processor_thread and self.processor_thread.isRunning():
            self.processor_thread.stop()
            self.log_message.emit("⏹️ Stopping processing...")
            self.stop_btn.setEnabled(False)
            self.progress_bar.setVisible(False)

    def propagate_log(self, msg):
        self.log_message.emit(msg)

    def on_finished(self):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶ Start Processing")
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        
        import time
        if hasattr(self, 'start_time'):
            elapsed = time.time() - self.start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            self.log_message.emit(f"⏱️ Tổng thời gian xử lý: {mins} phút {secs} giây.")
        
        if self.processor_thread and not self.processor_thread.is_running:
            QMessageBox.information(self, "Stopped", "Processing was stopped by user.")
        else:
            QMessageBox.information(self, "Finished", "Hoàn tất xử lý hàng loạt tất cả các tác vụ Editor!")

