import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QLabel, QProgressBar, QSpinBox, QFileDialog, QGroupBox, QMessageBox, QTextEdit, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from core.adb_uploader import AdbUploadThread

class AdbTaskWidget(QGroupBox):
    def __init__(self, remove_callback=None, task_index=1):
        super().__init__(f"📱 Tác vụ ADB {task_index}")
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
        
        # Folder selection
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Thư mục Video:"))
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Chọn thư mục chứa video cần truyền")
        folder_row.addWidget(self.folder_input)
        
        self.browse_btn = QPushButton("📁 Browse")
        self.browse_btn.setFixedWidth(80)
        self.browse_btn.clicked.connect(self.browse_folder)
        folder_row.addWidget(self.browse_btn)
        layout.addLayout(folder_row)
        
        # Device Input
        self.device_input = QTextEdit()
        self.device_input.setPlaceholderText(
            "Nhập Device IDs (mỗi dòng một ID)\nVí dụ:\n192.168.1.100:5555\nemulator-5554\ndeviceABC123"
        )
        self.device_input.setMaximumHeight(80)
        self.device_input.setMinimumHeight(60)
        layout.addWidget(self.device_input)
        
        # Settings Row
        settings_row = QHBoxLayout()
        
        settings_row.addWidget(QLabel("Số video mỗi máy:"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 9999)
        self.limit_spin.setValue(10)
        self.limit_spin.setFixedWidth(60)
        settings_row.addWidget(self.limit_spin)

        settings_row.addSpacing(15)
        
        if self.remove_callback:
            self.remove_btn = QPushButton("❌ Xóa")
            self.remove_btn.setFixedWidth(60)
            self.remove_btn.clicked.connect(lambda: self.remove_callback(self))
            self.remove_btn.setStyleSheet("color: white; background-color: #d9534f; border-radius: 4px; font-weight: bold;")
            settings_row.addWidget(self.remove_btn)
            
        settings_row.addStretch()
            
        layout.addLayout(settings_row)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục Video")
        if folder:
            self.folder_input.setText(folder)
            
    def get_data(self):
        text = self.device_input.toPlainText()
        devices = [line.strip() for line in text.split('\n') if line.strip()]
        return {
            'devices': devices,
            'folder': self.folder_input.text().strip(),
            'limit': self.limit_spin.value()
        }

    def set_data(self, data):
        if 'devices' in data:
            self.device_input.setPlainText("\n".join(data['devices']))
        if 'folder' in data:
            self.folder_input.setText(data['folder'])
        if 'limit' in data:
            self.limit_spin.setValue(data['limit'])

    def set_enabled(self, enabled):
        self.folder_input.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)
        self.device_input.setEnabled(enabled)
        self.limit_spin.setEnabled(enabled)
        if hasattr(self, 'remove_btn'):
            self.remove_btn.setEnabled(enabled)

class AdbTab(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # -- Tasks Area (Scrollable) --
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setMinimumHeight(400)
        self.tasks_container = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_container)
        self.tasks_layout.setContentsMargins(5, 5, 5, 5)
        self.tasks_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.tasks_container)
        layout.addWidget(self.scroll_area)

        # List to keep track of tasks widgets
        self.task_widgets = []
        self.task_counter = 0
        
        tasks_action_layout = QHBoxLayout()
        tasks_action_layout.setSpacing(10)
        
        self.add_task_btn = QPushButton("➕ Thêm Tác Vụ")
        self.add_task_btn.setFixedHeight(40)
        self.add_task_btn.setMinimumWidth(80)
        self.add_task_btn.setStyleSheet("font-size: 13px; font-weight: bold; background-color: #5cb85c; color: white;")
        self.add_task_btn.clicked.connect(self.add_task_widget)
        tasks_action_layout.addWidget(self.add_task_btn, 1)

        self.save_cfg_btn = QPushButton("💾 Lưu Cấu Hình")
        self.save_cfg_btn.setFixedHeight(40)
        self.save_cfg_btn.setMinimumWidth(80)
        self.save_cfg_btn.setStyleSheet("font-size: 13px; font-weight: bold; background-color: #f0ad4e; color: white;")
        self.save_cfg_btn.clicked.connect(self.save_config)
        tasks_action_layout.addWidget(self.save_cfg_btn, 1)

        self.load_cfg_btn = QPushButton("📂 Tải Cấu Hình")
        self.load_cfg_btn.setFixedHeight(40)
        self.load_cfg_btn.setMinimumWidth(80)
        self.load_cfg_btn.setStyleSheet("font-size: 13px; font-weight: bold; background-color: #5bc0de; color: white;")
        self.load_cfg_btn.clicked.connect(self.load_config)
        tasks_action_layout.addWidget(self.load_cfg_btn, 1)

        layout.addLayout(tasks_action_layout)

        # Add initial task
        self.add_task_widget(is_first=True)

        # -- Info Area --
        self.info_label = QLabel("Sẵn sàng truyền dữ liệu.")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("color: #888; font-weight: bold;")
        layout.addWidget(self.info_label)

        # Action Buttons --
        actions_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("▶ Bắt đầu truyền ADB")
        self.start_btn.setFixedHeight(40)
        self.start_btn.setStyleSheet("font-size: 14px; font-weight: bold; background-color: #0275d8; color: white;")
        self.start_btn.clicked.connect(self.start_transfer)
        actions_layout.addWidget(self.start_btn, 1)
        
        self.stop_btn = QPushButton("⏹ Dừng lại")
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
        self.stop_btn.clicked.connect(self.stop_transfer)
        self.stop_btn.setEnabled(False)
        actions_layout.addWidget(self.stop_btn, 1)
        
        layout.addLayout(actions_layout)
        
        # -- Progress --
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

    def add_task_widget(self, is_first=False):
        self.task_counter += 1
        widget = AdbTaskWidget(remove_callback=self.remove_task_widget, task_index=self.task_counter)
        if is_first:
            if hasattr(widget, 'remove_btn'):
                widget.remove_btn.hide()

        self.tasks_layout.addWidget(widget)
        self.task_widgets.append(widget)
        
        if len(self.task_widgets) > 1:
            for w in self.task_widgets:
                if hasattr(w, 'remove_btn'):
                    w.remove_btn.show()

    def remove_task_widget(self, widget):
        if len(self.task_widgets) > 1:
            self.tasks_layout.removeWidget(widget)
            self.task_widgets.remove(widget)
            widget.deleteLater()
            
            if len(self.task_widgets) == 1:
                if hasattr(self.task_widgets[0], 'remove_btn'):
                    self.task_widgets[0].remove_btn.hide()

    def save_config(self):
        settings_dir = os.path.join(os.getcwd(), "settings")
        os.makedirs(settings_dir, exist_ok=True)
        file_path = os.path.join(settings_dir, "adb_config.json")
        
        tasks_data = [w.get_data() for w in self.task_widgets]
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(tasks_data, f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "Thành công", f"Đã tự động lưu cấu hình vào:\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu cấu hình:\n{e}")

    def load_config(self):
        file_path = os.path.join(os.getcwd(), "settings", "adb_config.json")
        
        if not os.path.exists(file_path):
            QMessageBox.warning(self, "Chưa có cấu hình", "Bạn chưa lưu cấu hình ADB nào.")
            return

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tasks_data = json.load(f)
            
            if not isinstance(tasks_data, list):
                raise ValueError("Định dạng file không hợp lệ.")
            
            while len(self.task_widgets) > 0:
                widget = self.task_widgets.pop()
                self.tasks_layout.removeWidget(widget)
                widget.deleteLater()
            self.task_counter = 0

            for i, data in enumerate(tasks_data):
                self.add_task_widget(is_first=(i==0))
                self.task_widgets[-1].set_data(data)
            
            if not self.task_widgets:
                self.add_task_widget(is_first=True)

            QMessageBox.information(self, "Thành công", "Đã tải cấu hình ADB thành công!")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể tải cấu hình:\n{e}")

    def start_transfer(self):
        tasks = []
        for i, w in enumerate(self.task_widgets):
            data = w.get_data()
            if not data['folder']:
                QMessageBox.warning(self, "Lỗi", f"Tác vụ {i+1} chưa chọn thư mục gửi video.")
                return
            if not data['devices']:
                QMessageBox.warning(self, "Lỗi", f"Tác vụ {i+1} chưa nhập Device IDs.")
                return
            tasks.append(data)

        if not tasks:
            return

        self.set_interaction(False)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.info_label.setText("🚀 Đang chạy truyền xuất video...")
        
        total_devices = sum(len(t['devices']) for t in tasks)
        self.log_message.emit(f"Bắt đầu truyền video cho {total_devices} thiết bị từ {len(tasks)} tác vụ...")

        self.thread = AdbUploadThread(tasks)
        self.thread.progress.connect(self._on_progress)
        self.thread.percent.connect(self.progress_bar.setValue)
        self.thread.log_message.connect(self.log_message.emit)
        self.thread.finished.connect(self._on_finished)
        self.thread.start()

    def _on_progress(self, msg):
        self.info_label.setText(msg)

    def stop_transfer(self):
        self.log_message.emit("⏹️ Người dùng yêu cầu dừng quá trình push...")
        self.info_label.setText("Đang dừng...")
        self.stop_btn.setEnabled(False)
        if hasattr(self, 'thread') and self.thread.isRunning():
            self.thread.stop()

    def _on_finished(self, successful, failed):
        self.set_interaction(True)
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if hasattr(self, 'thread') and not self.thread.is_running:
            msg = f"⏹️ Đã dừng. Push thành công {successful} file."
            self.info_label.setText(msg)
            QMessageBox.information(self, "Đã dừng", msg)
            return

        msg = f"✅ Đã truyền xong: {successful} thành công | {failed} lỗi"
        self.info_label.setText(msg)

        if failed == 0:
            QMessageBox.information(self, "Hoàn tất", f"Quá trình truyền ADB hoàn tất!\nTruyền thành công {successful} file.")
        else:
            QMessageBox.warning(self, "Hoàn tất (Có lỗi)", f"Thành công: {successful} file\nThất bại: {failed} file.\nKiểm tra log để biết chi tiết.")

    def set_interaction(self, enabled):
        self.add_task_btn.setEnabled(enabled)
        for w in self.task_widgets:
            w.set_enabled(enabled)
