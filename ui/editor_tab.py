import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QDoubleSpinBox, QSpinBox,
    QFileDialog, QGroupBox, QMessageBox, QCheckBox, QRadioButton, QColorDialog, QSlider, QScrollArea, QLineEdit
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
    
    def __init__(self, sources, settings, processor):
        super().__init__()
        self.sources = sources
        self.settings = settings
        self.processor = processor
    
    def run(self):
        results = []
        total_videos = 0
        try:
            for src in self.sources:
                if not src or src == "Not Selected" or not os.path.exists(src):
                    results.append((-1, 0))
                    continue
                
                # estimate_compilations now returns (estimated_compilations, valid_files_count)
                estimated, video_count = self.processor.estimate_compilations(src, self.settings)
                
                total_videos += video_count
                results.append((estimated, video_count))
                
            self.finished.emit(results, total_videos)
        except Exception as e:
            # Send an array of errors if it unexpectedly crashes
            self.finished.emit([(-1, 0)] * len(self.sources), 0)

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

        # Estimation Label
        self.est_label = QLabel("Chưa chọn nguồn")
        self.est_label.setWordWrap(True)
        self.est_label.setStyleSheet("color: #64748B; font-size: 11px; font-style: italic; background: transparent; border: none;")
        layout.addWidget(self.est_label)

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
            
    def get_data(self):
        return {
            'source': self.src_label.text(),
            'output': self.dst_label.text()
        }

    def set_data(self, data):
        if 'source' in data:
            self.src_label.setText(data['source'])
        if 'output' in data:
            self.dst_label.setText(data['output'])
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
        file_path = os.path.join(os.getcwd(), "settings", "editor_config.json")
        
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Chưa có cấu hình", "Bạn chưa lưu cấu hình Editor nào (chưa có file editor_config.json trong thư mục settings).")
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

            self.update_estimation_debounced()
            QMessageBox.information(self, "Thành công", "Đã tải cấu hình Editor tự động!")
        except Exception as e:
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
        return 55 if self.duration_under_1min.isChecked() else 60
    
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
            'duration_mode': 'max' if self.duration_under_1min.isChecked() else 'min',
            'overlay_color': self.overlay_color,
            'overlay_opacity': self.overlay_opacity,
            'workers': self.workers_spin.value(),
            'hflip': getattr(self, 'hflip_checkbox', None) and self.hflip_checkbox.isChecked(),
            'random_color': getattr(self, 'random_color_checkbox', None) and self.random_color_checkbox.isChecked(),
            'film_grain': getattr(self, 'film_grain_checkbox', None) and self.film_grain_checkbox.isChecked(),
            'only_under_1min': self.only_under_1min_checkbox.isChecked(),
            'trim_long_videos': getattr(self, 'trim_long_videos_checkbox', None) and self.trim_long_videos_checkbox.isChecked(),
            'output_prefix': getattr(self, 'output_prefix_input', None) and self.output_prefix_input.text().strip()
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
        sources = [w.get_data()['source'] for w in self.task_widgets]
        
        self.global_est_label.setText("⏳ Đang thiết lập bảng tính dữ liệu...")
        self.run_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(0)
        
        settings = self.get_current_settings()
        
        if self.estimation_thread and self.estimation_thread.isRunning():
            try:
                self.estimation_thread.finished.disconnect()
            except:
                pass
            if not hasattr(self, '_old_threads'):
                self._old_threads = []
            self._old_threads.append(self.estimation_thread)
            self._old_threads = [t for t in self._old_threads if t.isRunning()]
        
        self.estimation_thread = EstimationThread(sources, settings, self.processor)
        self.estimation_thread.finished.connect(self.on_estimation_finished)
        self.estimation_thread.start()
    
    def on_estimation_finished(self, results, total_videos):
        self.progress_bar.setVisible(False)
        
        skip_merge = self.skip_merge_checkbox.isChecked()
        target_duration = self.get_target_duration()
        
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
            self.global_est_label.setText(f"📋 Tổng quát: Dự kiến xuất {total_estimated} clip dài (~{target_duration}s) từ tổng số {total_videos} video gốc.")
            
        self.run_btn.setEnabled(can_run)


    def start_processing(self):
        tasks = []
        for i, w in enumerate(self.task_widgets):
            data = w.get_data()
            if data['source'] != "Not Selected" and data['output'] != "Not Selected":
                tasks.append(data)
                
        if not tasks:
            QMessageBox.warning(self, "Lỗi Input", "Vui lòng chỉ định rõ thư mục Nguồn và Đích ở ít nhất 1 tác vụ!")
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
        
        if self.processor_thread and not self.processor_thread.is_running:
            QMessageBox.information(self, "Stopped", "Processing was stopped by user.")
        else:
            QMessageBox.information(self, "Finished", "Hoàn tất xử lý hàng loạt tất cả các tác vụ Editor!")

