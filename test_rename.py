import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QLineEdit, QFileDialog, QListWidget, QMessageBox
)
from PyQt6.QtCore import Qt

class RenameApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("File Renamer Tool")
        self.resize(500, 400)
        self.files_to_rename = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Chọn files
        file_layout = QHBoxLayout()
        self.btn_select = QPushButton("📁 Chọn Files")
        self.btn_select.clicked.connect(self.select_files)
        file_layout.addWidget(self.btn_select)
        
        self.lbl_count = QLabel("0 files được chọn")
        file_layout.addWidget(self.lbl_count)
        file_layout.addStretch()
        layout.addLayout(file_layout)

        # Ô nhập Prefix
        prefix_layout = QHBoxLayout()
        prefix_layout.addWidget(QLabel("Prefix (Tiền tố):"))
        self.input_prefix = QLineEdit()
        self.input_prefix.setPlaceholderText("VD: PrefixCuaToi")
        prefix_layout.addWidget(self.input_prefix)
        layout.addLayout(prefix_layout)

        # Danh sách file preview
        layout.addWidget(QLabel("Danh sách file:"))
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        # Nút thực thi
        self.btn_rename = QPushButton("▶ Thực hiện Rename")
        self.btn_rename.setStyleSheet("background-color: #28a745; color: white; font-weight: bold; padding: 10px; border-radius: 5px;")
        self.btn_rename.clicked.connect(self.rename_files)
        layout.addWidget(self.btn_rename)

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Chọn các file cần rename", "", "All Files (*)")
        if files:
            self.files_to_rename = files
            self.lbl_count.setText(f"{len(self.files_to_rename)} files được chọn")
            self.list_widget.clear()
            for f in self.files_to_rename:
                self.list_widget.addItem(os.path.basename(f))

    def rename_files(self):
        prefix = self.input_prefix.text().strip()
        if not prefix:
            QMessageBox.warning(self, "Lỗi Input", "Vui lòng nhập prefix!")
            return
            
        if not self.files_to_rename:
            QMessageBox.warning(self, "Lỗi Input", "Vui lòng chọn ít nhất 1 file để rename!")
            return

        success_count = 0
        for file_path in self.files_to_rename:
            directory = os.path.dirname(file_path)
            original_basename = os.path.basename(file_path)
            
            # Format: [prefix] - [tên file gốc]
            new_basename = f"{prefix} - {original_basename}"
            new_path = os.path.join(directory, new_basename)
            
            try:
                os.rename(file_path, new_path)
                success_count += 1
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể đổi tên file:\n{original_basename}\nLỗi: {e}")
                
        QMessageBox.information(self, "Hoàn tất", f"Đã rename thành công {success_count}/{len(self.files_to_rename)} files.")
        
        # Reset giao diện sau khi rename
        self.files_to_rename = []
        self.list_widget.clear()
        self.lbl_count.setText("0 files được chọn")
        # self.input_prefix.clear() # Giữ nguyên prefix nếu user muốn dùng tiếp

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = RenameApp()
    window.show()
    sys.exit(app.exec())
