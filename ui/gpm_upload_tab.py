"""
ui/gpm_upload_tab.py
---------------------
Tab: 🚀 TikTok Upload via GPM Login

Features:
  - Scan GPM profiles via local API
  - Select profiles with checkboxes in a beautiful QTableWidget + filter by name
  - Assign shared folder OR per-profile folder inside the table dynamically
  - Configure caption mode, limit, delay
  - Save / Load config
  - Upload worker (background thread)
"""

import os
import json

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QDoubleSpinBox, QFileDialog, QGroupBox,
    QScrollArea, QFrame, QCheckBox, QRadioButton, QButtonGroup,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSizePolicy, QAbstractItemView, QComboBox, QProgressBar,
    QTextEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor

from core.gpm_uploader import GpmApi, GpmUploadThread
from ui.components import (
    PrimaryButton, SecondaryButton, DangerButton, GhostButton,
    StyledProgressBar, SmallDangerButton,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helper Custom Cell Widgets
# ─────────────────────────────────────────────────────────────────────────────

class CenteredCheckbox(QWidget):
    """A perfectly centered checkbox inside a table cell."""

    def __init__(self, checked=True, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        lay.addWidget(self.checkbox)

    def isChecked(self) -> bool:
        return self.checkbox.isChecked()

    def setChecked(self, checked: bool):
        self.checkbox.setChecked(checked)


class FolderSelectorWidget(QWidget):
    """LineEdit + Browse button inside a table cell."""

    def __init__(self, initial_path="", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(4)

        self.edit = QLineEdit(initial_path)
        self.edit.setPlaceholderText("Chọn thư mục video cho profile...")
        self.edit.setMinimumHeight(30)
        self.edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #CBD5E1;
                border-radius: 4px;
                padding: 2px 6px;
                background: transparent;
                color: #CBD5E1;
            }
        """)
        lay.addWidget(self.edit, 1)

        self.btn = QPushButton("📁")
        self.btn.setFixedWidth(34)
        self.btn.setMinimumHeight(30)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.setStyleSheet("""
            QPushButton {
                background: rgba(99,102,241,0.1);
                border: 1px solid #4A526A;
                border-radius: 4px;
                color: #A5B4FC;
            }
            QPushButton:hover {
                background: rgba(99,102,241,0.2);
            }
        """)
        self.btn.clicked.connect(self._browse)
        lay.addWidget(self.btn)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục video")
        if folder:
            self.edit.setText(os.path.normpath(folder))

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, text: str):
        self.edit.setText(text)


# ─────────────────────────────────────────────────────────────────────────────
# Scanner thread (non-blocking)
# ─────────────────────────────────────────────────────────────────────────────

class ScanThread(QThread):
    done    = pyqtSignal(list)   # list of profile dicts
    error   = pyqtSignal(str)

    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port

    def run(self):
        try:
            api      = GpmApi(host=self.host, port=self.port)
            profiles = api.get_profiles()
            self.done.emit(profiles)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Open Profiles thread (non-blocking)
# ─────────────────────────────────────────────────────────────────────────────

class OpenProfilesThread(QThread):
    log_message = pyqtSignal(str)
    finished    = pyqtSignal()

    def __init__(self, host, port, profiles: list[dict]):
        super().__init__()
        self.host = host
        self.port = port
        self.profiles = profiles

    def run(self):
        try:
            api = GpmApi(host=self.host, port=self.port)
            for idx, p in enumerate(self.profiles):
                pid = p["id"]
                pname = p.get("name", pid)
                self.log_message.emit(f"⏳ [{pname}] ({idx+1}/{len(self.profiles)}) Đang mở profile GPM...")
                try:
                    result = api.start_profile(pid)
                    if result:
                        self.log_message.emit(f"   ✅ [{pname}] Mở trình duyệt thành công!")
                    else:
                        self.log_message.emit(f"   ❌ [{pname}] Không thể khởi động profile.")
                except Exception as e:
                    self.log_message.emit(f"   ❌ [{pname}] Lỗi: {e}")
        except Exception as e:
            self.log_message.emit(f"❌ Lỗi kết nối GPM: {e}")
        self.finished.emit()


# ─────────────────────────────────────────────────────────────────────────────
# Main Tab
# ─────────────────────────────────────────────────────────────────────────────

class GpmUploadTab(QWidget):
    log_message = pyqtSignal(str)

    # Internal state
    _profiles: list[dict] = []          # raw from GPM API
    _pending_per_folders: dict = {}
    _pending_selected_ids: set = set()

    def __init__(self):
        super().__init__()
        self._worker       = None
        self._scan_thread  = None
        self._open_thread  = None
        self._build_ui()
        self._load_config_silent()

    # ─────────────────────────────────────────────────────────────────────────
    # BUILD UI
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 16)
        lay.setSpacing(14)

        # ── Header ────────────────────────────────────────────────────
        hdr = QLabel("🚀  TikTok Auto Upload — GPM Login")
        hdr.setFont(QFont("Inter", 17, QFont.Weight.Bold))
        hdr.setStyleSheet("color: #1E293B;")
        lay.addWidget(hdr)

        sub = QLabel(
            "Quét profile GPM Login · Chọn profile · Gán thư mục video · Tự động upload lên TikTok"
        )
        sub.setStyleSheet("color: #64748B; font-size: 12px;")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # ── Section 1: GPM Connection ─────────────────────────────────
        lay.addWidget(self._build_connection_group())

        # ── Section 2: Profile List ───────────────────────────────────
        lay.addWidget(self._build_profile_group())

        # ── Section 3: Upload Settings ────────────────────────────────
        lay.addWidget(self._build_settings_group())

        # ── Progress bar ──────────────────────────────────────────────
        self._progress_bar = StyledProgressBar()
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        lay.addWidget(self._progress_bar)

        # ── Status label ──────────────────────────────────────────────
        self._status_lbl = QLabel("Sẵn sàng.")
        self._status_lbl.setStyleSheet(
            "color: #64748B; font-size: 12px; font-weight: 600; "
            "background: transparent; border: none;"
        )
        self._status_lbl.setWordWrap(True)
        lay.addWidget(self._status_lbl)

        # ── Action buttons ────────────────────────────────────────────
        lay.addLayout(self._build_action_row())
        lay.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

    # ── Connection group ──────────────────────────────────────────────────────

    def _build_connection_group(self) -> QGroupBox:
        grp = self._make_group("🔗  Kết nối GPM Login")
        inner = QVBoxLayout()
        inner.setContentsMargins(12, 6, 12, 12)
        inner.setSpacing(8)

        row = QHBoxLayout()

        lbl_host = QLabel("GPM Host:")
        lbl_host.setFixedWidth(80)
        row.addWidget(lbl_host)

        self._host_edit = QLineEdit("http://127.0.0.1")
        self._host_edit.setFixedWidth(180)
        self._host_edit.setMinimumHeight(32)
        self._host_edit.setToolTip("Host của GPM Login API (mặc định: http://127.0.0.1)")
        row.addWidget(self._host_edit)

        row.addSpacing(12)

        lbl_port = QLabel("Port:")
        lbl_port.setFixedWidth(40)
        row.addWidget(lbl_port)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(19995)
        self._port_spin.setFixedWidth(90)
        self._port_spin.setMinimumHeight(32)
        row.addWidget(self._port_spin)

        row.addSpacing(16)

        self._scan_btn = PrimaryButton("🔍  Quét Profile")
        self._scan_btn.setMinimumHeight(36)
        self._scan_btn.setMinimumWidth(160)
        self._scan_btn.clicked.connect(self._scan_profiles)
        row.addWidget(self._scan_btn)

        row.addStretch()
        inner.addLayout(row)
        grp.setLayout(inner)
        return grp

    # ── Profile list group ────────────────────────────────────────────────────

    def _build_profile_group(self) -> QGroupBox:
        grp = self._make_group("👤  Danh sách Profile")
        outer_lay = QVBoxLayout()
        outer_lay.setContentsMargins(12, 6, 12, 12)
        outer_lay.setSpacing(8)

        # Filter + select-all bar
        ctrl_row = QHBoxLayout()

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("🔍 Lọc theo tên profile...")
        self._filter_edit.setMinimumHeight(30)
        self._filter_edit.textChanged.connect(self._apply_filter)
        ctrl_row.addWidget(self._filter_edit, 1)

        ctrl_row.addSpacing(8)

        sel_all_btn = SecondaryButton("☑ Chọn tất cả")
        sel_all_btn.setMinimumHeight(30)
        sel_all_btn.setFixedWidth(120)
        sel_all_btn.clicked.connect(lambda: self._set_all_selected(True))
        ctrl_row.addWidget(sel_all_btn)

        desel_btn = SecondaryButton("☐ Bỏ chọn")
        desel_btn.setMinimumHeight(30)
        desel_btn.setFixedWidth(100)
        desel_btn.clicked.connect(lambda: self._set_all_selected(False))
        ctrl_row.addWidget(desel_btn)

        ctrl_row.addSpacing(8)

        bulk_folder_btn = SecondaryButton("📁 Gán thư mục")
        bulk_folder_btn.setMinimumHeight(30)
        bulk_folder_btn.setFixedWidth(130)
        bulk_folder_btn.setToolTip(
            "Gán nhanh một thư mục video cho nhiều profile cùng lúc.\n"
            "Cách dùng: Bôi đen (chọn) các hàng muốn gán trong bảng dưới đây (hoặc tích chọn các checkbox),\n"
            "sau đó bấm nút này và chọn thư mục."
        )
        bulk_folder_btn.clicked.connect(self._bulk_assign_folder)
        ctrl_row.addWidget(bulk_folder_btn)

        outer_lay.addLayout(ctrl_row)

        # ── Mode toggle: shared folder / per-profile folder ────────────
        mode_row = QHBoxLayout()
        mode_lbl = QLabel("Chế độ thư mục video:")
        mode_lbl.setStyleSheet("font-weight: 700; background: transparent; border: none;")
        mode_row.addWidget(mode_lbl)
        mode_row.addSpacing(8)

        self._mode_shared_radio = QRadioButton("📁 Dùng chung 1 folder")
        self._mode_shared_radio.setChecked(True)
        self._mode_shared_radio.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_shared_radio)

        self._mode_per_radio = QRadioButton("📂 Folder riêng từng profile")
        self._mode_per_radio.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_per_radio)

        self._mode_btn_grp = QButtonGroup(self)
        self._mode_btn_grp.addButton(self._mode_shared_radio)
        self._mode_btn_grp.addButton(self._mode_per_radio)
        mode_row.addStretch()
        outer_lay.addLayout(mode_row)

        # ── Shared folder row ──────────────────────────────────────────
        self._shared_folder_widget = QWidget()
        sf_lay = QHBoxLayout(self._shared_folder_widget)
        sf_lay.setContentsMargins(0, 0, 0, 0)
        sf_lay.setSpacing(8)

        sf_lbl = QLabel("Thư mục video:")
        sf_lbl.setFixedWidth(120)
        sf_lay.addWidget(sf_lbl)

        self._shared_folder_edit = QLineEdit()
        self._shared_folder_edit.setPlaceholderText(
            "Chọn thư mục chứa video sẽ upload cho tất cả profile..."
        )
        self._shared_folder_edit.setMinimumHeight(32)
        sf_lay.addWidget(self._shared_folder_edit, 1)

        sf_browse = SecondaryButton("📁 Browse")
        sf_browse.setFixedWidth(90)
        sf_browse.setMinimumHeight(32)
        sf_browse.clicked.connect(self._browse_shared_folder)
        sf_lay.addWidget(sf_browse)

        outer_lay.addWidget(self._shared_folder_widget)

        # ── Table View ────────────────────────────────────────────
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Chọn", "Tên Profile", "GPM ID", "Thư mục Video"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setFixedHeight(260)
        
        # Style matching modern theme
        self._table.setStyleSheet("""
            QTableWidget {
                font-size: 13px;
                gridline-color: #1E2130;
                background-color: transparent;
                border: 1px solid #CBD5E1;
                border-radius: 6px;
            }
            QTableWidget::item { padding: 4px; }
            QHeaderView::section {
                background: #1E293B;
                color: #CBD5E1;
                font-weight: 600;
                padding: 6px 8px;
                border: none;
                border-right: 1px solid #334155;
            }
            QTableWidget::item:selected { background: rgba(99,102,241,0.15); color: #A5B4FC; }
        """)
        
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(0, 55)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(1, 240)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(2, 200)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        outer_lay.addWidget(self._table)

        self._no_profiles_lbl = QLabel(
            "Chưa có profile nào. Bấm 🔍 Quét Profile để tải danh sách từ GPM."
        )
        self._no_profiles_lbl.setStyleSheet(
            "color: #94A3B8; font-style: italic; background: transparent; border: none;"
        )
        self._no_profiles_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer_lay.addWidget(self._no_profiles_lbl)

        # ── Profile count badge ────────────────────────────────────────
        self._count_lbl = QLabel("0 profile")
        self._count_lbl.setStyleSheet(
            "color: #64748B; font-size: 11px; background: transparent; border: none;"
        )
        outer_lay.addWidget(self._count_lbl)

        grp.setLayout(outer_lay)
        self._on_mode_changed()   # set initial visibility
        return grp

    # ── Settings group ────────────────────────────────────────────────────────

    def _build_settings_group(self) -> QGroupBox:
        grp = self._make_group("⚙️  Cài đặt Upload")
        inner = QVBoxLayout()
        inner.setContentsMargins(12, 6, 12, 12)
        inner.setSpacing(10)

        # Row 1: Caption mode
        cap_row = QHBoxLayout()
        cap_lbl = QLabel("Caption:")
        cap_lbl.setFixedWidth(80)
        cap_row.addWidget(cap_lbl)

        self._cap_filename_radio = QRadioButton("Tên file")
        self._cap_filename_radio.setChecked(True)
        cap_row.addWidget(self._cap_filename_radio)

        self._cap_txt_radio = QRadioButton("File .txt cùng tên")
        self._cap_txt_radio.setToolTip(
            "Đọc file <tên_video>.txt cùng thư mục làm caption.\n"
            "Fallback về tên file nếu không tìm thấy."
        )
        cap_row.addWidget(self._cap_txt_radio)

        self._cap_fixed_radio = QRadioButton("Cố định:")
        cap_row.addWidget(self._cap_fixed_radio)

        self._cap_fixed_edit = QLineEdit()
        self._cap_fixed_edit.setPlaceholderText("Nhập caption cố định...")
        self._cap_fixed_edit.setMinimumHeight(30)
        self._cap_fixed_edit.setEnabled(False)
        cap_row.addWidget(self._cap_fixed_edit, 1)

        self._cap_btn_grp = QButtonGroup(self)
        self._cap_btn_grp.addButton(self._cap_filename_radio)
        self._cap_btn_grp.addButton(self._cap_txt_radio)
        self._cap_btn_grp.addButton(self._cap_fixed_radio)
        self._cap_fixed_radio.toggled.connect(
            lambda c: self._cap_fixed_edit.setEnabled(c)
        )

        inner.addLayout(cap_row)

        # Row 2: Videos per profile + delay + close after
        row2 = QHBoxLayout()

        vid_lbl = QLabel("Video/profile:")
        vid_lbl.setFixedWidth(100)
        row2.addWidget(vid_lbl)

        self._limit_spin = QSpinBox()
        self._limit_spin.setRange(0, 9999)
        self._limit_spin.setValue(5)
        self._limit_spin.setSpecialValueText("0 = Tất cả")
        self._limit_spin.setSuffix(" video")
        self._limit_spin.setFixedWidth(140)
        self._limit_spin.setMinimumHeight(32)
        row2.addWidget(self._limit_spin)

        row2.addSpacing(24)

        delay_lbl = QLabel("Delay giữa video:")
        row2.addWidget(delay_lbl)

        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(1.0, 600.0)
        self._delay_spin.setValue(30.0)
        self._delay_spin.setSingleStep(1.0)
        self._delay_spin.setSuffix(" giây")
        self._delay_spin.setFixedWidth(120)
        self._delay_spin.setMinimumHeight(32)
        row2.addWidget(self._delay_spin)

        row2.addStretch()
        inner.addLayout(row2)

        # Row 3: Concurrency settings
        row3 = QHBoxLayout()
        
        profiles_lbl = QLabel("Số profile chạy song song:")
        profiles_lbl.setFixedWidth(160)
        row3.addWidget(profiles_lbl)
        
        self._max_profiles_spin = QSpinBox()
        self._max_profiles_spin.setRange(1, 10)
        self._max_profiles_spin.setValue(3)
        self._max_profiles_spin.setSuffix(" profile")
        self._max_profiles_spin.setFixedWidth(110)
        self._max_profiles_spin.setMinimumHeight(32)
        row3.addWidget(self._max_profiles_spin)
        
        row3.addSpacing(24)
        
        tabs_lbl = QLabel("Số tab song song/profile:")
        row3.addWidget(tabs_lbl)
        
        self._max_tabs_spin = QSpinBox()
        self._max_tabs_spin.setRange(1, 10)
        self._max_tabs_spin.setValue(3)
        self._max_tabs_spin.setSuffix(" tab")
        self._max_tabs_spin.setFixedWidth(110)
        self._max_tabs_spin.setMinimumHeight(32)
        row3.addWidget(self._max_tabs_spin)
        
        row3.addStretch()
        inner.addLayout(row3)

        # Row 3: Extra options
        opt_row = QHBoxLayout()

        self._close_after_chk = QCheckBox("🔒 Đóng profile sau khi upload xong")
        self._close_after_chk.setToolTip(
            "Sau khi upload hết video của profile, gọi API đóng profile GPM."
        )
        opt_row.addWidget(self._close_after_chk)

        opt_row.addSpacing(24)

        self._move_done_chk = QCheckBox("📦 Chuyển video vào thư mục done/ sau upload")
        self._move_done_chk.setChecked(False)
        opt_row.addWidget(self._move_done_chk)

        opt_row.addSpacing(24)

        self._human_typing_chk = QCheckBox("⌨️ Gõ caption chống bot")
        self._human_typing_chk.setChecked(True)
        self._human_typing_chk.setToolTip(
            "Mô phỏng gõ caption từng ký tự một với độ trễ ngẫu nhiên siêu mượt (chống bot detection)."
        )
        opt_row.addWidget(self._human_typing_chk)

        opt_row.addStretch()
        inner.addLayout(opt_row)

        grp.setLayout(inner)
        return grp

    # ── Action row ────────────────────────────────────────────────────────────

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._save_btn = GhostButton("💾 Lưu Cấu Hình")
        self._save_btn.setMinimumHeight(42)
        self._save_btn.setMinimumWidth(130)
        self._save_btn.clicked.connect(self._save_config)
        row.addWidget(self._save_btn)

        self._load_btn = GhostButton("📂 Tải Cấu Hình")
        self._load_btn.setMinimumHeight(42)
        self._load_btn.setMinimumWidth(130)
        self._load_btn.clicked.connect(self._load_config)
        row.addWidget(self._load_btn)

        row.addStretch()

        # Nút Mở Profile Đã Chọn
        self._open_btn = SecondaryButton("🌐  Mở Profile Đã Chọn")
        self._open_btn.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        self._open_btn.setMinimumHeight(42)
        self._open_btn.setMinimumWidth(180)
        self._open_btn.clicked.connect(self._open_selected_profiles)
        row.addWidget(self._open_btn)

        self._stop_btn = DangerButton("⏹  Dừng")
        self._stop_btn.setMinimumHeight(42)
        self._stop_btn.setMinimumWidth(100)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_upload)
        row.addWidget(self._stop_btn)

        self._start_btn = PrimaryButton("▶  Bắt Đầu Upload")
        self._start_btn.setFont(QFont("Inter", 12, QFont.Weight.Bold))
        self._start_btn.setMinimumHeight(42)
        self._start_btn.setMinimumWidth(180)
        self._start_btn.clicked.connect(self._start_upload)
        row.addWidget(self._start_btn)

        return row

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _make_group(self, title: str) -> QGroupBox:
        g = QGroupBox(title)
        g.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
        """)
        return g

    def _on_mode_changed(self):
        shared = self._mode_shared_radio.isChecked()
        self._shared_folder_widget.setVisible(shared)
        # Dynamic table folder column visibility based on mode
        self._table.setColumnHidden(3, shared)

    def _browse_shared_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục video chung")
        if folder:
            self._shared_folder_edit.setText(os.path.normpath(folder))

    def _apply_filter(self, text: str):
        text = text.lower().strip()
        for r in range(self._table.rowCount()):
            name_item = self._table.item(r, 1)
            visible = True
            if text:
                name = name_item.text().lower() if name_item else ""
                visible = text in name
            self._table.setRowHidden(r, not visible)

    def _set_all_selected(self, value: bool):
        for r in range(self._table.rowCount()):
            if not self._table.isRowHidden(r):
                cb_widget = self._table.cellWidget(r, 0)
                if cb_widget:
                    cb_widget.setChecked(value)

    def _bulk_assign_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục video cho các profile")
        if not folder:
            return
        
        normalized_folder = os.path.normpath(folder)
        
        rows_to_set = set()
        selected_ranges = self._table.selectedRanges()
        for r_range in selected_ranges:
            for r in range(r_range.topRow(), r_range.bottomRow() + 1):
                rows_to_set.add(r)
                
        if not rows_to_set:
            # Fallback về các hàng được tích checkbox
            for r in range(self._table.rowCount()):
                cb_widget = self._table.cellWidget(r, 0)
                if cb_widget and cb_widget.isChecked():
                    rows_to_set.add(r)
                    
        if not rows_to_set:
            QMessageBox.warning(self, "Thông báo", "Vui lòng bôi đen (chọn) hoặc tích chọn các profile muốn gán thư mục.")
            return
            
        for r in rows_to_set:
            folder_widget = self._table.cellWidget(r, 3)
            if folder_widget:
                if hasattr(folder_widget, 'setText'):
                    folder_widget.setText(normalized_folder)
                elif hasattr(folder_widget, 'findChild'):
                    from PyQt6.QtWidgets import QLineEdit
                    edit = folder_widget.findChild(QLineEdit)
                    if edit:
                        edit.setText(normalized_folder)
                        
        # Tự động chuyển sang chế độ "Folder riêng từng profile" để hiển thị cột thư mục trên bảng
        if not self._mode_per_radio.isChecked():
            self._mode_per_radio.setChecked(True)
            self._on_mode_changed()
                
        self.log_message.emit(f"📁 Đã gán thư mục '{normalized_folder}' cho {len(rows_to_set)} profile.")

    # ─────────────────────────────────────────────────────────────────────────
    # SCAN PROFILES
    # ─────────────────────────────────────────────────────────────────────────

    def _scan_profiles(self):
        host = self._host_edit.text().strip()
        port = self._port_spin.value()

        self._scan_btn.setText("⏳ Đang quét...")
        self._scan_btn.setEnabled(False)
        self.log_message.emit(f"🔍 Đang quét profile GPM tại {host}:{port}...")

        self._scan_thread = ScanThread(host=host, port=port)
        self._scan_thread.done.connect(self._on_scan_done)
        self._scan_thread.error.connect(self._on_scan_error)
        self._scan_thread.start()

    def _on_scan_done(self, profiles: list):
        self._scan_btn.setText("🔍  Quét Profile")
        self._scan_btn.setEnabled(True)
        self._profiles = profiles
        self._rebuild_profile_table(profiles)
        n = len(profiles)
        self.log_message.emit(f"✅ Quét xong: {n} profile")
        self._count_lbl.setText(f"{n} profile")

    def _on_scan_error(self, err: str):
        self._scan_btn.setText("🔍  Quét Profile")
        self._scan_btn.setEnabled(True)
        self.log_message.emit(f"❌ Lỗi quét GPM: {err}")
        QMessageBox.critical(self, "Lỗi kết nối GPM", err)

    def _rebuild_profile_table(self, profiles: list):
        # 1. Save existing folders / selections from current table
        saved_folders = {}
        saved_selected = {}
        for r in range(self._table.rowCount()):
            pid_item = self._table.item(r, 2)
            if pid_item:
                pid = pid_item.text()
                cb_widget = self._table.cellWidget(r, 0)
                if cb_widget:
                    saved_selected[pid] = cb_widget.isChecked()
                folder_widget = self._table.cellWidget(r, 3)
                if folder_widget:
                    saved_folders[pid] = folder_widget.text()

        # Restore from pending configs if applicable
        if hasattr(self, '_pending_per_folders') and self._pending_per_folders:
            saved_folders.update(self._pending_per_folders)
            self._pending_per_folders = None
        if hasattr(self, '_pending_selected_ids') and self._pending_selected_ids:
            for pid in self._pending_selected_ids:
                saved_selected[pid] = True
            self._pending_selected_ids = None

        # 2. Rebuild rows
        self._table.setRowCount(0)
        
        if self._no_profiles_lbl:
            self._no_profiles_lbl.setVisible(len(profiles) == 0)
            
        for p in profiles:
            pid   = p.get("id", "") or p.get("profile_id", "")
            pname = p.get("name", "") or p.get("profile_name", pid)
            
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Column 0: Checkbox
            checked = saved_selected.get(pid, False)
            cb = CenteredCheckbox(checked)
            self._table.setCellWidget(row, 0, cb)

            # Column 1: Tên Profile
            name_item = QTableWidgetItem(pname)
            name_item.setFont(QFont("Inter", 11, QFont.Weight.Medium))
            self._table.setItem(row, 1, name_item)

            # Column 2: GPM ID
            id_item = QTableWidgetItem(pid)
            id_item.setForeground(QColor("#94A3B8"))
            self._table.setItem(row, 2, id_item)

            # Column 3: Folder
            folder_path = saved_folders.get(pid, "")
            fs_widget = FolderSelectorWidget(folder_path)
            self._table.setCellWidget(row, 3, fs_widget)

            self._table.setRowHeight(row, 40)

    # ─────────────────────────────────────────────────────────────────────────
    # START / STOP UPLOAD
    # ─────────────────────────────────────────────────────────────────────────

    def _start_upload(self):
        if self._worker and self._worker.isRunning():
            return

        # ── Validate & collect profiles to process ────────────────────
        shared_mode = self._mode_shared_radio.isChecked()
        shared_folder = self._shared_folder_edit.text().strip()

        if shared_mode and not shared_folder:
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng chọn thư mục video chung.")
            return

        selected_profiles = []
        if self._table.rowCount() > 0:
            for r in range(self._table.rowCount()):
                cb_widget = self._table.cellWidget(r, 0)
                if not cb_widget or not cb_widget.isChecked():
                    continue
                
                pid = self._table.item(r, 2).text()
                pname = self._table.item(r, 1).text()
                
                folder = shared_folder if shared_mode else ""
                if not shared_mode:
                    folder_widget = self._table.cellWidget(r, 3)
                    if folder_widget:
                        folder = folder_widget.text()

                if not folder:
                    QMessageBox.warning(
                        self, "Thiếu thông tin",
                        f"Profile '{pname}' chưa được gán thư mục video."
                    )
                    return
                
                selected_profiles.append({
                    "id":     pid,
                    "name":   pname,
                    "folder": folder,
                })
        else:
            QMessageBox.warning(
                self, "Chưa có profile",
                "Bấm 🔍 Quét Profile để tải danh sách profile từ GPM trước."
            )
            return

        if not selected_profiles:
            QMessageBox.warning(self, "Chưa chọn profile", "Hãy chọn ít nhất 1 profile.")
            return

        # ── Caption mode ──────────────────────────────────────────────
        if self._cap_txt_radio.isChecked():
            caption_mode = "txt_file"
        elif self._cap_fixed_radio.isChecked():
            caption_mode = "fixed"
        else:
            caption_mode = "filename"

        fixed_caption = self._cap_fixed_edit.text().strip()

        # ── Log summary ───────────────────────────────────────────────
        n = len(selected_profiles)
        self.log_message.emit(
            f"🚀 Bắt đầu upload: {n} profile · "
            f"{self._limit_spin.value() or 'tất cả'} video/profile · "
            f"delay {self._delay_spin.value()}s"
        )

        # ── Start worker ──────────────────────────────────────────────
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._set_input_enabled(False)

        self._worker = GpmUploadThread(
            profiles           = selected_profiles,
            gpm_host           = self._host_edit.text().strip(),
            gpm_port           = self._port_spin.value(),
            caption_mode       = caption_mode,
            fixed_caption      = fixed_caption,
            videos_per_profile = self._limit_spin.value(),
            delay_seconds      = self._delay_spin.value(),
            close_after        = self._close_after_chk.isChecked(),
            move_done          = self._move_done_chk.isChecked(),
            max_concurrent_profiles = self._max_profiles_spin.value(),
            parallel_tabs      = self._max_tabs_spin.value(),
            human_typing       = self._human_typing_chk.isChecked(),
        )
        self._worker.progress.connect(self._status_lbl.setText)
        self._worker.log_message.connect(self.log_message.emit)
        self._worker.percent.connect(self._progress_bar.setValue)
        self._worker.finished.connect(self._on_upload_done)
        self._worker.start()

    def _stop_upload(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._stop_btn.setEnabled(False)
            self._status_lbl.setText("⏹ Đang dừng...")
            self.log_message.emit("⏹ Người dùng yêu cầu dừng upload...")

    def _on_upload_done(self, success: int, failed: int):
        self._progress_bar.setVisible(False)
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._set_input_enabled(True)
        self._status_lbl.setText(
            f"✅ Hoàn tất — {success} video thành công, {failed} thất bại"
        )
        self._worker = None

    def _set_input_enabled(self, v: bool):
        self._scan_btn.setEnabled(v)
        self._host_edit.setEnabled(v)
        self._port_spin.setEnabled(v)
        self._shared_folder_edit.setEnabled(v)
        self._limit_spin.setEnabled(v)
        self._delay_spin.setEnabled(v)
        self._max_profiles_spin.setEnabled(v)
        self._max_tabs_spin.setEnabled(v)
        self._table.setEnabled(v)
        self._human_typing_chk.setEnabled(v)
        if hasattr(self, "_open_btn"):
            self._open_btn.setEnabled(v)

    def _open_selected_profiles(self):
        if self._worker and self._worker.isRunning():
            return
        if self._open_thread and self._open_thread.isRunning():
            return

        selected_profiles = []
        if self._table.rowCount() > 0:
            for r in range(self._table.rowCount()):
                cb_widget = self._table.cellWidget(r, 0)
                if cb_widget and cb_widget.isChecked():
                    pid = self._table.item(r, 2).text()
                    pname = self._table.item(r, 1).text()
                    selected_profiles.append({
                        "id": pid,
                        "name": pname
                    })
        else:
            QMessageBox.warning(
                self, "Chưa có profile",
                "Bấm 🔍 Quét Profile để tải danh sách profile từ GPM trước."
            )
            return

        if not selected_profiles:
            QMessageBox.warning(self, "Chưa chọn profile", "Hãy chọn ít nhất 1 profile.")
            return

        self.log_message.emit(f"👁️ Đang tiến hành mở {len(selected_profiles)} profile đã chọn...")
        self._status_lbl.setText("⏳ Đang mở các profile...")
        
        self._open_btn.setEnabled(False)
        self._start_btn.setEnabled(False)
        self._set_input_enabled(False)

        host = self._host_edit.text().strip()
        port = self._port_spin.value()

        self._open_thread = OpenProfilesThread(host=host, port=port, profiles=selected_profiles)
        self._open_thread.log_message.connect(self.log_message.emit)
        self._open_thread.finished.connect(self._on_open_profiles_done)
        self._open_thread.start()

    def _on_open_profiles_done(self):
        self._open_btn.setEnabled(True)
        self._start_btn.setEnabled(True)
        self._set_input_enabled(True)
        self._status_lbl.setText("Đã mở xong các profile đã chọn.")
        self._open_thread = None

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIG PERSISTENCE
    # ─────────────────────────────────────────────────────────────────────────

    def _config_path(self) -> str:
        import sys
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "settings", "gpm_upload_config.json")

    def _build_config_dict(self) -> dict:
        per_profile_folders = {}
        selected_ids = []
        
        for r in range(self._table.rowCount()):
            pid = self._table.item(r, 2).text()
            cb_widget = self._table.cellWidget(r, 0)
            if cb_widget and cb_widget.isChecked():
                selected_ids.append(pid)
            folder_widget = self._table.cellWidget(r, 3)
            if folder_widget:
                per_profile_folders[pid] = folder_widget.text()

        if self._cap_txt_radio.isChecked():
            caption_mode = "txt_file"
        elif self._cap_fixed_radio.isChecked():
            caption_mode = "fixed"
        else:
            caption_mode = "filename"

        return {
            "gpm_host":             self._host_edit.text().strip(),
            "gpm_port":             self._port_spin.value(),
            "folder_mode":          "shared" if self._mode_shared_radio.isChecked() else "per_profile",
            "shared_folder":        self._shared_folder_edit.text().strip(),
            "per_profile_folders":  per_profile_folders,
            "selected_profiles":    selected_ids,
            "caption_mode":         caption_mode,
            "fixed_caption":        self._cap_fixed_edit.text().strip(),
            "videos_per_profile":   self._limit_spin.value(),
            "delay_seconds":        self._delay_spin.value(),
            "close_after":          self._close_after_chk.isChecked(),
            "move_done":            self._move_done_chk.isChecked(),
            "max_concurrent_profiles": self._max_profiles_spin.value(),
            "parallel_tabs":           self._max_tabs_spin.value(),
            "human_typing":         self._human_typing_chk.isChecked(),
        }

    def _apply_config_dict(self, cfg: dict):
        self._host_edit.setText(cfg.get("gpm_host", "http://127.0.0.1"))
        self._port_spin.setValue(cfg.get("gpm_port", 19995))

        if cfg.get("folder_mode") == "per_profile":
            self._mode_per_radio.setChecked(True)
        else:
            self._mode_shared_radio.setChecked(True)

        self._shared_folder_edit.setText(cfg.get("shared_folder", ""))

        cap_mode = cfg.get("caption_mode", "filename")
        if cap_mode == "txt_file":
            self._cap_txt_radio.setChecked(True)
        elif cap_mode == "fixed":
            self._cap_fixed_radio.setChecked(True)
        else:
            self._cap_filename_radio.setChecked(True)

        self._cap_fixed_edit.setText(cfg.get("fixed_caption", ""))
        self._limit_spin.setValue(cfg.get("videos_per_profile", 5))
        self._delay_spin.setValue(cfg.get("delay_seconds", 30.0))
        self._max_profiles_spin.setValue(cfg.get("max_concurrent_profiles", 3))
        self._max_tabs_spin.setValue(cfg.get("parallel_tabs", 3))
        self._close_after_chk.setChecked(cfg.get("close_after", False))
        self._move_done_chk.setChecked(cfg.get("move_done", False))
        self._human_typing_chk.setChecked(cfg.get("human_typing", True))

        # Restore per-profile folders + selection
        per = cfg.get("per_profile_folders", {})
        selected = set(cfg.get("selected_profiles", []))
        
        for r in range(self._table.rowCount()):
            pid = self._table.item(r, 2).text()
            if pid in per:
                folder_widget = self._table.cellWidget(r, 3)
                if folder_widget:
                    folder_widget.setText(per[pid])
            cb_widget = self._table.cellWidget(r, 0)
            if cb_widget:
                cb_widget.setChecked(pid in selected)

        # Store for later when profiles are loaded
        self._pending_per_folders  = per
        self._pending_selected_ids = selected

    def _save_config(self):
        path = self._config_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._build_config_dict(), f, indent=2, ensure_ascii=False)
            QMessageBox.information(self, "Thành công", f"Đã lưu cấu hình:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu cấu hình:\n{e}")

    def _load_config(self):
        path = self._config_path()
        if not os.path.exists(path):
            QMessageBox.warning(self, "Chưa có cấu hình", "Chưa có file cấu hình nào được lưu.")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self._apply_config_dict(cfg)
            QMessageBox.information(self, "Thành công", "Đã tải cấu hình thành công!")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể tải cấu hình:\n{e}")

    def _load_config_silent(self):
        """Load config on startup without showing dialogs."""
        path = self._config_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self._apply_config_dict(cfg)
        except Exception:
            pass
