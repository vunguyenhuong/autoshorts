from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame,
    QSizePolicy, QApplication, QSplitter, QScrollArea
)
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSlot
from PyQt6.QtGui import QFont, QIcon
import datetime

from ui.downloader_tab import DownloaderTab
from ui.editor_tab import EditorTab
from ui.autocut_tab import AutoCutTab
from ui.adb_tab import AdbTab
from ui.tiktok_douyin_tab import TiktokDouyinTab
from ui.gpm_upload_tab import GpmUploadTab
from ui.yt_search_tab import YtSearchTab
from ui.components import SidebarNavButton, TerminalLog
from core.downloader import YtdlpUpdater
import ui.theme as theme


class SidebarWidget(QFrame):
    """Left navigation sidebar."""

    nav_items = [
        ("📥", "Downloader"),
        ("✂️",  "Editor"),
        ("🎬", "AutoCut"),
        ("📱", "ADB"),
        ("🎵", "TikTok DL"),
        ("🔎", "YT Finder"),
        ("🚀", "TikTok UP"),
    ]

    def __init__(self, on_navigate, parent=None):
        super().__init__(parent)
        self.on_navigate = on_navigate
        self.setFixedWidth(220)
        self.setObjectName("Sidebar")
        self._is_dark = False
        self._apply_sidebar_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── App brand ──────────────────────────────────────────────────────
        brand = QWidget()
        brand.setFixedHeight(72)
        brand.setStyleSheet("background: transparent;")
        bl = QHBoxLayout(brand)
        bl.setContentsMargins(18, 0, 18, 0)
        bl.setSpacing(10)

        logo = QLabel("⚡")
        logo.setFont(QFont("Segoe UI Emoji", 20))
        logo.setStyleSheet("color: #6366F1; background: transparent; border: none;")
        bl.addWidget(logo)

        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        self.app_name_lbl = QLabel("Auto Tiktok")
        self.app_name_lbl.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        name_col.addWidget(self.app_name_lbl)

        self.sub_lbl = QLabel("HuongVN")
        self.sub_lbl.setFont(QFont("Inter", 9))
        name_col.addWidget(self.sub_lbl)
        bl.addLayout(name_col)
        bl.addStretch()
        root.addWidget(brand)

        # ── Separator ──────────────────────────────────────────────────────
        self._sep = QFrame()
        self._sep.setFixedHeight(1)
        root.addWidget(self._sep)

        root.addSpacing(8)

        # ── Nav section label ──────────────────────────────────────────────
        self._nav_label = QLabel("  MENU")
        self._nav_label.setFont(QFont("Inter", 9, QFont.Weight.Bold))
        self._nav_label.setFixedHeight(24)
        root.addWidget(self._nav_label)
        root.addSpacing(4)

        # ── Nav buttons ────────────────────────────────────────────────────
        self._nav_btns: list[SidebarNavButton] = []
        for i, (icon, label) in enumerate(self.nav_items):
            btn = SidebarNavButton(icon, label)
            btn.clicked.connect(lambda checked, idx=i: self._select(idx))
            root.addWidget(btn)
            self._nav_btns.append(btn)

        root.addStretch()

        # ── Separator ──────────────────────────────────────────────────────
        self._sep2 = QFrame()
        self._sep2.setFixedHeight(1)
        root.addWidget(self._sep2)

        # ── Footer: theme toggle ───────────────────────────────────────────
        footer = QWidget()
        footer.setFixedHeight(56)
        footer.setStyleSheet("background: transparent;")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(18, 0, 18, 0)
        fl.setSpacing(10)

        self.theme_btn = QPushButton("☀️  Light Mode")
        self.theme_btn.setCheckable(True)
        self.theme_btn.setChecked(False)
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #475569;
                border: 1px solid #2D3244;
                border-radius: 7px;
                padding: 5px 10px;
                font-size: 11px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:checked {
                background: rgba(99,102,241,0.12);
                color: #818CF8;
                border-color: #6366F1;
            }
            QPushButton:hover { background: #1C1F28; border-color: #4A526A; }
        """)
        fl.addWidget(self.theme_btn)
        root.addWidget(footer)

        # Default: select first (deferred — called after pages are created)
        self._pending_select = 0

    def _apply_sidebar_style(self):
        dark = self._is_dark
        if dark:
            bg = "#0A0C12"
            border = "#1E2130"
            sep_color = "#1E2130"
            nav_color = "color: #3D4663; background: transparent; border: none; letter-spacing: 2px; padding: 0 16px;"
            app_color = "color: #F1F5F9; background: transparent; border: none;"
            sub_color = "color: #334155; background: transparent; border: none;"
        else:
            bg = "#F0F2F8"
            border = "#DDE1EF"
            sep_color = "#DDE1EF"
            nav_color = "color: #94A3B8; background: transparent; border: none; letter-spacing: 2px; padding: 0 16px;"
            app_color = "color: #0F172A; background: transparent; border: none;"
            sub_color = "color: #64748B; background: transparent; border: none;"

        self.setStyleSheet(f"""
            #Sidebar {{ background-color: {bg}; border-right: 1px solid {border}; }}
        """)
        if hasattr(self, '_sep'):
            self._sep.setStyleSheet(f"background: {sep_color}; border: none;")
        if hasattr(self, '_sep2'):
            self._sep2.setStyleSheet(f"background: {sep_color}; border: none;")
        if hasattr(self, '_nav_label'):
            self._nav_label.setStyleSheet(nav_color)
        if hasattr(self, 'app_name_lbl'):
            self.app_name_lbl.setStyleSheet(app_color)
        if hasattr(self, 'sub_lbl'):
            self.sub_lbl.setStyleSheet(sub_color)

    def apply_theme(self, dark: bool):
        self._is_dark = dark
        self._apply_sidebar_style()
        # Update theme button style
        if dark:
            self.theme_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #3D4663;
                    border: 1px solid #2D3244; border-radius: 7px;
                    padding: 5px 10px; font-size: 11px; font-weight: 600; text-align: left;
                }
                QPushButton:checked {
                    background: rgba(99,102,241,0.12); color: #818CF8; border-color: #6366F1;
                }
                QPushButton:hover { background: #1C1F28; border-color: #4A526A; }
            """)
        else:
            self.theme_btn.setStyleSheet("""
                QPushButton {
                    background: transparent; color: #64748B;
                    border: 1px solid #CBD5E1; border-radius: 7px;
                    padding: 5px 10px; font-size: 11px; font-weight: 600; text-align: left;
                }
                QPushButton:checked {
                    background: rgba(79,70,229,0.08); color: #4F46E5; border-color: #4F46E5;
                }
                QPushButton:hover { background: #E8EBF2; border-color: #94A3B8; }
            """)
        # Update nav button styles
        for btn in self._nav_btns:
            btn.apply_theme(dark)

    def _select(self, idx: int):
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == idx)
        self.on_navigate(idx)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AutoTiktok — 0395.080.513")
        self.resize(1920, 1080)
        self.showMaximized()

        # App icon
        import os
        icon_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "icons", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Windows AppUserModelID
        try:
            from ctypes import windll
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("huongvn.autotiktok.1.0")
        except Exception:
            pass

        self._build_ui()
        
        # ── yt-dlp Auto Update ───────────────────────────────────────────
        # Determine settings directory
        import sys
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        settings_dir = os.path.join(base_dir, "settings")
        if not os.path.exists(settings_dir):
            os.makedirs(settings_dir)
            
        self.updater = YtdlpUpdater(settings_dir)
        self.updater.run_update(callback=self.append_log)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(1)
        self.splitter.setStyleSheet("QSplitter::handle { background-color: #CBD5E1; }")
        root.addWidget(self.splitter)

        # ── Main area (sidebar + pages) ─────────────────────────────────────
        main_area = QWidget()
        main_area.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_area.setMinimumHeight(1)
        ma_layout = QHBoxLayout(main_area)
        ma_layout.setContentsMargins(0, 0, 0, 0)
        ma_layout.setSpacing(0)

        # Sidebar
        self.sidebar = SidebarWidget(on_navigate=self._navigate)
        self.sidebar.theme_btn.toggled.connect(self._toggle_theme)
        ma_layout.addWidget(self.sidebar)

        # Pages
        self.pages = QStackedWidget()

        # ── Tabs ──────────────────────────────────────────────────────────
        self.downloader_tab = DownloaderTab()
        self.editor_tab = EditorTab()
        self.autocut_tab = AutoCutTab()
        self.adb_tab = AdbTab()
        self.social_dl_tab = TiktokDouyinTab()
        self.yt_search_tab = YtSearchTab()
        self.gpm_upload_tab = GpmUploadTab()

        for tab in (self.downloader_tab, self.editor_tab, self.autocut_tab, self.adb_tab, self.social_dl_tab, self.yt_search_tab, self.gpm_upload_tab):
            wrapper = QWidget()
            wl = QVBoxLayout(wrapper)
            wl.setContentsMargins(16, 16, 16, 16)
            wl.setSpacing(0)
            wl.addWidget(tab)
            self.pages.addWidget(wrapper)

        self.main_scroll = QScrollArea()
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setWidget(self.pages)
        self.main_scroll.setFrameShape(QFrame.Shape.NoFrame)

        ma_layout.addWidget(self.main_scroll, 1)
        self.splitter.addWidget(main_area)

        # Now sidebar is ready — set default page
        self.sidebar._select(0)

        # ── Log area ────────────────────────────────────────────────────────
        self.log_container = QWidget()
        self.log_container.setObjectName("LogContainer")
        self.log_container.setStyleSheet(
            "background: #F0F2F8; border-top: 1px solid #DDE1EF;"
        )
        
        lc_layout = QVBoxLayout(self.log_container)
        lc_layout.setContentsMargins(0, 0, 0, 0)
        lc_layout.setSpacing(0)

        # ── Log header bar ──────────────────────────────────────────────────
        self.log_header_bar = QWidget()
        self.log_header_bar.setFixedHeight(50)
        self.log_header_bar.setAutoFillBackground(True)
        self.log_header_bar.setStyleSheet("background-color: #F0F2F8; border-bottom: 1px solid #DDE1EF;")
        log_header_layout = QHBoxLayout(self.log_header_bar)
        log_header_layout.setContentsMargins(14, 0, 10, 0)
        log_header_layout.setSpacing(8)

        self.log_title_lbl = QLabel("🖥  Process Log")
        self.log_title_lbl.setFont(QFont("Inter", 10, QFont.Weight.Bold))
        self.log_title_lbl.setStyleSheet("color: #64748B; background: transparent; border: none; letter-spacing: 0.5px;")
        log_header_layout.addWidget(self.log_title_lbl)
        log_header_layout.addStretch()

        self.clear_btn = QPushButton("✕ Clear")
        self.clear_btn.setFixedSize(64, 22)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #64748B;
                border: 1px solid #CBD5E1;
                border-radius: 5px;
                font-size: 11px;
                font-weight: 600;
                padding: 0;
            }
            QPushButton:hover { color: #DC2626; border-color: #DC2626; }
        """)
        self.clear_btn.clicked.connect(self._clear_logs)
        log_header_layout.addWidget(self.clear_btn)
        lc_layout.addWidget(self.log_header_bar)

        # ── Log text area ───────────────────────────────────────────────────
        self.log_area = TerminalLog()
        self.log_area.apply_theme(dark=False)  # start in light mode
        self.log_area.setMinimumHeight(150)
        self.log_area_wrapper = QWidget()
        self.log_area_wrapper.setAutoFillBackground(True)
        self.log_area_wrapper.setStyleSheet("background-color: #F0F2F8;")
        lw = QVBoxLayout(self.log_area_wrapper)
        lw.setContentsMargins(10, 4, 10, 8)
        lw.setSpacing(0)
        lw.addWidget(self.log_area)
        lc_layout.addWidget(self.log_area_wrapper, 1)
        
        self.splitter.addWidget(self.log_container)
        self.splitter.setSizes([700, 300])



        # ── Connect signals ─────────────────────────────────────────────────
        self.downloader_tab.log_message.connect(self.append_log)
        self.editor_tab.log_message.connect(self.append_log)
        self.autocut_tab.log_message.connect(self.append_log)
        self.adb_tab.log_message.connect(self.append_log)
        self.social_dl_tab.log_message.connect(self.append_log)
        self.yt_search_tab.log_message.connect(self.append_log)
        self.gpm_upload_tab.log_message.connect(self.append_log)

    # ── Navigation ──────────────────────────────────────────────────────────

    def _navigate(self, idx: int):
        self.pages.setCurrentIndex(idx)

    # ── Theme toggle ────────────────────────────────────────────────────────

    def _toggle_theme(self, dark: bool):
        app = QApplication.instance()
        theme.apply_theme(app, dark)
        self.sidebar.theme_btn.setText("🌙  Dark Mode" if dark else "☀️  Light Mode")
        # Sidebar
        self.sidebar.apply_theme(dark)
        # TerminalLog
        self.log_area.apply_theme(dark)

        if dark:
            lc_bg      = "#0A0C12"
            lc_border  = "#1E2130"
            title_color = "#475569"
            btn_qss = """QPushButton { background: transparent; color: #475569;
                border: 1px solid #2D3244; border-radius: 5px;
                font-size: 11px; font-weight: 600; padding: 0; }
                QPushButton:hover { color: #F87171; border-color: #EF4444; }"""
        else:
            lc_bg      = "#F0F2F8"
            lc_border  = "#DDE1EF"
            title_color = "#64748B"
            btn_qss = """QPushButton { background: transparent; color: #64748B;
                border: 1px solid #CBD5E1; border-radius: 5px;
                font-size: 11px; font-weight: 600; padding: 0; }
                QPushButton:hover { color: #DC2626; border-color: #DC2626; }"""

        # Direct style on each widget — no objectName cascade
        self.splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {lc_border}; }}")
        self.log_container.setStyleSheet(
            f"background: {lc_bg}; border-top: 1px solid {lc_border};"
        )
        self.log_header_bar.setStyleSheet(
            f"background-color: {lc_bg}; border-bottom: 1px solid {lc_border};"
        )
        self.log_area_wrapper.setStyleSheet(f"background-color: {lc_bg};")
        self.log_title_lbl.setStyleSheet(
            f"color: {title_color}; background: transparent; border: none; letter-spacing: 0.5px;"
        )
        self.clear_btn.setStyleSheet(btn_qss)

        # Pages background
        self.pages.setStyleSheet("" if dark else "QStackedWidget { background: #F8F9FB; }")




    # ── Logs ────────────────────────────────────────────────────────────────

    def _clear_logs(self):
        self.log_area.clear()

    @pyqtSlot(str)
    def append_log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_area.append_log(f"[{ts}] {msg}")

    def closeEvent(self, event):
        """Gracefully stop all background workers before closing to avoid crash."""
        # Stop GPM upload worker nếu đang chạy
        try:
            worker = getattr(self.gpm_upload_tab, '_worker', None)
            if worker and worker.isRunning():
                worker.stop()
                worker.wait(8000)  # Chờ tối đa 8 giây
        except Exception:
            pass

        # Stop GPM open-profiles thread nếu đang chạy
        try:
            open_thread = getattr(self.gpm_upload_tab, '_open_thread', None)
            if open_thread and open_thread.isRunning():
                open_thread.quit()
                open_thread.wait(3000)
        except Exception:
            pass

        # Stop các tab worker khác nếu có
        for tab_name in ('downloader_tab', 'editor_tab', 'autocut_tab', 'adb_tab', 'social_dl_tab', 'yt_search_tab'):
            try:
                tab = getattr(self, tab_name, None)
                if tab is None:
                    continue
                for attr in ('_worker', '_thread', '_scan_thread'):
                    t = getattr(tab, attr, None)
                    if t and hasattr(t, 'isRunning') and t.isRunning():
                        if hasattr(t, 'stop'):
                            t.stop()
                        t.quit()
                        t.wait(3000)
            except Exception:
                pass

        event.accept()

