import os
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, 
    QLabel, QProgressBar, QSpinBox, QFileDialog, QGroupBox, QMessageBox, QTextEdit, QScrollArea,
    QRadioButton, QButtonGroup
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

        # Quick create folder row
        device_action_row = QHBoxLayout()
        self.quick_create_folder_btn = QPushButton("📁 Tạo nhánh (Sub-folder) bằng tên Devices ID")
        self.quick_create_folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover { background-color: #218838; }
        """)
        self.quick_create_folder_btn.setToolTip("Tự động tạo các thư mục con trong 'Thư mục Video' tương ứng với mỗi Device ID đã nhập")
        self.quick_create_folder_btn.clicked.connect(self.quick_create_folders)
        device_action_row.addWidget(self.quick_create_folder_btn)
        device_action_row.addStretch()
        layout.addLayout(device_action_row)
        
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

        # Scan mode row
        scan_row = QHBoxLayout()
        scan_row_label = QLabel("Chế độ quét:")
        scan_row_label.setStyleSheet("font-weight: bold; color: #333;")
        scan_row.addWidget(scan_row_label)

        self.scan_folder_radio = QRadioButton("📁 Folder gốc")
        self.scan_folder_radio.setChecked(True)
        self.scan_folder_radio.setToolTip("Chỉ lấy video trực tiếp trong thư mục đã chọn, bỏ qua subfolder")
        scan_row.addWidget(self.scan_folder_radio)

        self.scan_paired_radio = QRadioButton("📂 1 Máy → 1 Folder")
        self.scan_paired_radio.setToolTip("Mỗi thiết bị được gán với 1 subfolder tương ứng (theo thứ tự A-Z)")
        scan_row.addWidget(self.scan_paired_radio)

        self.scan_random_radio = QRadioButton("🔀 Ngẫu nhiên (quét cả subfolder)")
        self.scan_random_radio.setToolTip("Quét đệ quy tất cả subfolder và trộn đều video ngẫu nhiên")
        scan_row.addWidget(self.scan_random_radio)

        self.scan_btn_group = QButtonGroup(self)
        self.scan_btn_group.addButton(self.scan_folder_radio)
        self.scan_btn_group.addButton(self.scan_paired_radio)
        self.scan_btn_group.addButton(self.scan_random_radio)

        scan_row.addStretch()
        layout.addLayout(scan_row)

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục Video")
        if folder:
            self.folder_input.setText(folder)
            
    def get_data(self):
        text = self.device_input.toPlainText()
        devices = [line.strip() for line in text.split('\n') if line.strip()]
        # Xác định scan_mode
        if hasattr(self, 'scan_paired_radio') and self.scan_paired_radio.isChecked():
            scan_mode = 'paired'  # Mỗi máy → 1 subfolder
        elif hasattr(self, 'scan_random_radio') and self.scan_random_radio.isChecked():
            scan_mode = 'random'  # Ngẫu nhiên quét subfolder
        else:
            scan_mode = 'flat'    # Chỉ lấy file ở root
        return {
            'devices': devices,
            'folder': self.folder_input.text().strip(),
            'limit': self.limit_spin.value(),
            'scan_mode': scan_mode
        }

    def set_data(self, data):
        if 'devices' in data:
            self.device_input.setPlainText("\n".join(data['devices']))
        if 'folder' in data:
            self.folder_input.setText(data['folder'])
        if 'limit' in data:
            self.limit_spin.setValue(data['limit'])
        # Hỗ trợ cả trường hợp cũ (scan_recursive) và mới (scan_mode)
        if hasattr(self, 'scan_paired_radio'):
            scan_mode = data.get('scan_mode', '')
            scan_recursive = data.get('scan_recursive', False)
            if scan_mode == 'paired':
                self.scan_paired_radio.setChecked(True)
            elif scan_mode == 'random' or scan_recursive:
                self.scan_random_radio.setChecked(True)
            else:
                self.scan_folder_radio.setChecked(True)

    def set_enabled(self, enabled):
        self.folder_input.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)
        self.device_input.setEnabled(enabled)
        self.quick_create_folder_btn.setEnabled(enabled)
        self.limit_spin.setEnabled(enabled)
        if hasattr(self, 'scan_folder_radio'):
            self.scan_folder_radio.setEnabled(enabled)
        if hasattr(self, 'scan_paired_radio'):
            self.scan_paired_radio.setEnabled(enabled)
        if hasattr(self, 'scan_random_radio'):
            self.scan_random_radio.setEnabled(enabled)
        if hasattr(self, 'remove_btn'):
            self.remove_btn.setEnabled(enabled)

    def quick_create_folders(self):
        folder = self.folder_input.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn 'Thư mục Video' hợp lệ trước.")
            return
        
        text = self.device_input.toPlainText()
        devices = [line.strip() for line in text.split('\n') if line.strip()]
        if not devices:
            QMessageBox.warning(self, "Lỗi", "Vui lòng nhập danh sách Device IDs.")
            return

        created = 0
        for device in devices:
            safe_device = device.replace(':', '_').replace('/', '_').replace('\\', '_')
            path = os.path.join(folder, safe_device)
            if not os.path.exists(path):
                try:
                    os.makedirs(path)
                    created += 1
                except:
                    pass
        
        if created > 0:
            QMessageBox.information(self, "Thành công", f"Đã tự động tạo mới {created} thư mục con.")
        else:
            QMessageBox.information(self, "Thông báo", "Tất cả các thư mục con đã tồn tại hoặc không thể tạo.")

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

        self.clean_done_btn = QPushButton("🗑️ Dọn folder Done")
        self.clean_done_btn.setFixedHeight(40)
        self.clean_done_btn.setToolTip("Xóa vĩnh viễn tất cả video trong các thư mục 'done' của các tác vụ đang cấu hình")
        self.clean_done_btn.setStyleSheet("""
            QPushButton {
                font-size: 13px;
                font-weight: bold;
                background-color: #6c757d;
                color: white;
            }
            QPushButton:hover {
                background-color: #5a6268;
            }
        """)
        self.clean_done_btn.clicked.connect(self.clean_done_folders)
        actions_layout.addWidget(self.clean_done_btn, 1)

        self.check_unused_btn = QPushButton("🔍 Kiểm tra video còn lại")
        self.check_unused_btn.setFixedHeight(40)
        self.check_unused_btn.setToolTip("Kiểm tra bao nhiêu video chưa được truyền trong các tác vụ")
        self.check_unused_btn.setStyleSheet("""
            QPushButton {
                font-size: 13px;
                font-weight: bold;
                background-color: #17a2b8;
                color: white;
            }
            QPushButton:hover {
                background-color: #138496;
            }
        """)
        self.check_unused_btn.clicked.connect(self.check_unused_videos)
        actions_layout.addWidget(self.check_unused_btn, 1)
        
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

    def check_unused_videos(self):
        """Kiểm tra và đếm số lượng video chưa sử dụng trong các tác vụ, chi tiết đến từng folder."""
        valid_exts = ('.mp4', '.mov', '.avi', '.mkv', '.wmv')
        total_unused_all = 0
        details = []

        for i, w in enumerate(self.task_widgets):
            data = w.get_data()
            folder = data.get('folder', '').strip()
            if not folder or not os.path.isdir(folder):
                continue
            
            scan_mode = data.get('scan_mode', 'flat')
            task_unused = 0
            
            self.log_message.emit(f"▶ Bắt đầu kiểm tra Tác vụ {i+1} (<b style='color: #d63384;'>{os.path.basename(folder)}</b>):")
            
            try:
                if scan_mode == 'paired':
                    subfolders = [
                        d for d in os.listdir(folder)
                        if os.path.isdir(os.path.join(folder, d)) and d.lower() != 'done'
                    ]
                    self.log_message.emit(f"   ► Phát hiện <b style='color: #fd7e14;'>{len(subfolders)} subfolder</b> hợp lệ:")
                    for sf in sorted(subfolders):
                        sf_path = os.path.join(folder, sf)
                        sub_unused = len([
                            f for f in os.listdir(sf_path)
                            if os.path.isfile(os.path.join(sf_path, f)) and f.lower().endswith(valid_exts)
                        ])
                        task_unused += sub_unused
                        if sub_unused > 0:
                            self.log_message.emit(f"   • {sf}: <b style='color: #007bff; font-size: 14px;'>{sub_unused} video</b>")
                        else:
                            self.log_message.emit(f"   • {sf}: <b style='color: #dc3545;'>Hết video</b>")
                elif scan_mode == 'random':
                    for root, dirs, files in os.walk(folder):
                        dirs[:] = [d for d in dirs if d.lower() != 'done']
                        task_unused += len([
                            f for f in files
                            if f.lower().endswith(valid_exts)
                        ])
                    self.log_message.emit(f"   • Tất cả subfolder gộp lại: <b style='color: #007bff; font-size: 14px;'>{task_unused} video</b>")
                else: # flat
                    task_unused = len([
                        f for f in os.listdir(folder)
                        if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith(valid_exts)
                    ])
                    self.log_message.emit(f"   • Thư mục gốc: <b style='color: #007bff; font-size: 14px;'>{task_unused} video</b>")
            except Exception as e:
                self.log_message.emit(f"❌ Lỗi kiểm tra tác vụ {i+1}: {e}")
                
            total_unused_all += task_unused

        if total_unused_all == 0:
            self.log_message.emit("🔍 Kiểm tra xong: <b>Không còn video nào chưa dùng</b> trong các tác vụ hợp lệ.")
            QMessageBox.information(self, "Thông báo", "Không còn video nào chưa sử dụng hoặc chưa cấu hình tác vụ hợp lệ.")
            return

        self.log_message.emit(f"✅ Hoàn tất kiểm tra: Tổng cộng còn <b style='color: #28a745; font-size: 15px;'>{total_unused_all} video</b> chưa dùng.")
        QMessageBox.information(self, "Kết quả kiểm tra", f"Tìm thấy tổng cộng: {total_unused_all} video chưa sử dụng.\nChi tiết đã được in ra bảng Log.")

    def clean_done_folders(self):
        """Xóa vĩnh viễn tất cả video trong các thư mục 'done' của mọi tác vụ."""
        import shutil

        # Thu thập tất cả các thư mục done cần dọn
        done_dirs_to_clean = []
        for w in self.task_widgets:
            data = w.get_data()
            folder = data.get('folder', '').strip()
            if not folder or not os.path.isdir(folder):
                continue

            scan_mode = data.get('scan_mode', 'flat')

            if scan_mode == 'paired':
                # Mỗi subfolder có folder done riêng
                try:
                    subfolders = [
                        d for d in os.listdir(folder)
                        if os.path.isdir(os.path.join(folder, d)) and d.lower() != 'done'
                    ]
                    for sf in subfolders:
                        done_path = os.path.join(folder, sf, 'done')
                        if os.path.isdir(done_path):
                            done_dirs_to_clean.append(done_path)
                except Exception:
                    pass
            else:
                # Flat / random: done nằm ở root folder
                done_path = os.path.join(folder, 'done')
                if os.path.isdir(done_path):
                    done_dirs_to_clean.append(done_path)

        if not done_dirs_to_clean:
            QMessageBox.information(self, "Thông báo", "Không tìm thấy thư mục 'done' nào cần dọn.")
            return

        # Đếm tổng số file
        total_files = 0
        for d in done_dirs_to_clean:
            try:
                total_files += len([
                    f for f in os.listdir(d)
                    if os.path.isfile(os.path.join(d, f))
                ])
            except Exception:
                pass

        # Hiển thị danh sách thư mục và xin xác nhận
        dirs_preview = "\n".join(f"  • {d}" for d in done_dirs_to_clean[:10])
        if len(done_dirs_to_clean) > 10:
            dirs_preview += f"\n  ... và {len(done_dirs_to_clean) - 10} thư mục khác"

        reply = QMessageBox.warning(
            self,
            "⚠️ Xác nhận xóa vĩnh viễn",
            f"Bạn có chắc muốn xóa vĩnh viễn {total_files} file "
            f"trong {len(done_dirs_to_clean)} thư mục 'done'?\n\n"
            f"{dirs_preview}\n\n"
            "⚠️ Hành động này KHÔNG THỂ HOÀN TÁC!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Tiến hành xóa vĩnh viễn
        deleted_files = total_files # dùng lại số đếm bên trên
        deleted_empty_subfolders = 0
        errors = 0
        
        for done_dir in done_dirs_to_clean:
            try:
                if os.path.isdir(done_dir):
                    shutil.rmtree(done_dir) # xóa hoàn toàn thư mục done
            except Exception as e:
                self.log_message.emit(f"❌ Lỗi xóa folder done '{done_dir}': {e}")
                errors += 1

        msg = f"🗑️ Đã dọn dẹp {deleted_files} file từ thư mục 'done'."
        if errors:
            msg += f"\n({errors} lỗi)"
            
        self.log_message.emit(msg.replace('\n', ' - '))
        self.info_label.setText(msg)
        QMessageBox.information(self, "Hoàn tất", msg)
