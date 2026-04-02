from PyQt6.QtWidgets import QMainWindow, QTabWidget, QVBoxLayout, QHBoxLayout, QWidget, QTextEdit, QLabel, QPushButton
from PyQt6.QtCore import pyqtSlot, Qt
from ui.downloader_tab import DownloaderTab
from ui.editor_tab import EditorTab
from ui.autocut_tab import AutoCutTab
from ui.adb_tab import AdbTab
from ui.toggle_switch import ToggleSwitch
import datetime

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoTiktok - 0395.080.513")
        self.resize(1920, 1080)
        self.showMaximized()  # Open maximized
        
        # Set application icon
        import os
        from PyQt6.QtGui import QIcon
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        # Global Header
        from PyQt6.QtWidgets import QFrame
        from PyQt6.QtGui import QFont
        
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

        title = QLabel("AutoTiktok")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: white;")
        header_layout.addWidget(title)

        subtitle = QLabel("Tool nội bộ thuộc quyền sở hữu của HuongVN & AnhTitan")
        subtitle.setFont(QFont("Segoe UI", 9))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: rgba(255, 255, 255, 0.9);")
        header_layout.addWidget(subtitle)

        self.layout.addWidget(header_frame)
        
        # Tabs
        self.tabs = QTabWidget()
        self.downloader_tab = DownloaderTab()
        self.editor_tab = EditorTab()
        self.autocut_tab = AutoCutTab()
        self.adb_tab = AdbTab()

        self.tabs.addTab(self.downloader_tab, "Downloader")
        self.tabs.addTab(self.editor_tab, "Editor & Merger")
        self.tabs.addTab(self.autocut_tab, "AutoCut Editor")
        self.tabs.addTab(self.adb_tab, "ADB Uploader")
        
        # Create corner widget for theme toggle
        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(10, 0, 10, 0)
        corner_layout.setSpacing(8)
        
        self.theme_label = QLabel("🌙")
        self.theme_label.setStyleSheet("font-size: 16px;")
        corner_layout.addWidget(self.theme_label)
        
        self.theme_toggle = ToggleSwitch()
        self.theme_toggle.setChecked(False)
        self.theme_toggle.stateChanged.connect(self.toggle_theme)
        corner_layout.addWidget(self.theme_toggle)
        
        # Set corner widget to tab bar
        self.tabs.setCornerWidget(corner_widget, Qt.Corner.TopRightCorner)
        
        self.layout.addWidget(self.tabs)

        # Logging Area
        log_header = QHBoxLayout()
        self.log_label = QLabel("Process Log:")
        log_header.addWidget(self.log_label)
        log_header.addStretch()
        self.clear_log_btn = QPushButton("🗑️ Clear Logs")
        self.clear_log_btn.setFixedWidth(110)
        self.clear_log_btn.clicked.connect(self._clear_logs)
        log_header.addWidget(self.clear_log_btn)
        self.layout.addLayout(log_header)
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFixedHeight(100)
        self.layout.addWidget(self.log_area)
        
        # Global Footer
        footer_label = QLabel("Copyright © 2026 HuongVN. All rights reserved ❤️")
        footer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_label.setStyleSheet("""
            QLabel {
                color: #7f8c8d;
                font-size: 9pt;
                padding: 8px;
                background-color: rgba(0, 0, 0, 0.02);
                border-top: 1px solid rgba(0, 0, 0, 0.1);
            }
        """)
        self.layout.addWidget(footer_label)

        # Connect Signals
        self.downloader_tab.log_message.connect(self.append_log)
        self.editor_tab.log_message.connect(self.append_log)
        self.autocut_tab.log_message.connect(self.append_log)
        self.adb_tab.log_message.connect(self.append_log)
        
        # Hide/show log area based on active tab
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        # Connect threads logs inside tabs if they aren't fully bubbled? 
        # (Bubbled via log_message in respective classes)

    def on_tab_changed(self, index):
        """Hide log area when on AutoCut tab to save space"""
        if index == 2:  # AutoCut Editor tab
            self.log_label.hide()
            self.clear_log_btn.hide()
            self.log_area.hide()
        else:
            self.log_label.show()
            self.clear_log_btn.show()
            self.log_area.show()
    
    def toggle_theme(self, state):
        """Toggle between light and dark theme"""
        import qdarktheme
        
        if state:
            # Dark mode (switch ON)
            qdarktheme.setup_theme("dark", custom_colors={"primary": "#e63946"})
            self.theme_label.setText("☀️")
        else:
            # Light mode (switch OFF)
            qdarktheme.setup_theme("light")
            self.theme_label.setText("🌙")

    def _clear_logs(self):
        self.log_area.clear()

    @pyqtSlot(str)
    def append_log(self, msg):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_area.append(f"[{timestamp}] {msg}")
