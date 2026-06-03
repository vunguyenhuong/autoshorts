"""ui/yt_search_tab.py — YouTube Channel Finder Tab"""
from __future__ import annotations
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QGroupBox, QRadioButton, QButtonGroup,
    QSpinBox, QFileDialog, QApplication, QFrame, QProgressBar, QComboBox,
    QDialog, QDialogButtonBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl
from PyQt6.QtGui import QFont, QColor, QDesktopServices, QKeySequence, QShortcut
from ui.components import PrimaryButton, SecondaryButton, GhostButton


# ── Worker Thread ──────────────────────────────────────────────────────────────

class SearchThread(QThread):
    results_ready = pyqtSignal(list)
    error         = pyqtSignal(str)
    status        = pyqtSignal(str)
    MODE_KEYWORD  = "keyword"
    MODE_RELATED  = "related"

    def __init__(self, mode: str, query: str, max_results: int = 20,
                 gl: str = "", hl: str = "",
                 sub_min: int = 0, sub_max: int = 0,
                 verify_country: bool = False,
                 use_api: bool = False, api_key: str = ""):
        super().__init__()
        self.mode = mode
        self.query = query
        self.max_results = max_results
        self.gl = gl
        self.hl = hl
        self.sub_min = sub_min
        self.sub_max = sub_max
        self.verify_country = verify_country
        self.use_api = use_api
        self.api_key = api_key

    def run(self):
        try:
            from core.yt_search import (
                search_channels, search_channels_multi,
                get_related_channels,
                fetch_channel_metadata_batch, COUNTRY_CODE_DISPLAY,
                search_channels_api, search_channels_multi_api,
                get_related_channels_api,
            )
            country_info = f" [{self.gl}]" if self.gl else ""

            # ── Chế độ YouTube Data API v3 ──────────────────────────────────
            if self.use_api:
                def _api_prog(a, b=None):
                    if isinstance(a, str):
                        self.status.emit(a)
                    elif b is not None:
                        self.status.emit(f"🔍 [API] Từ khóa {a}/{b} xong...")

                raw_kws = [k.strip() for k in self.query.split(",") if k.strip()]
                try:
                    if self.mode == self.MODE_KEYWORD:
                        if len(raw_kws) > 1:
                            self.status.emit(f"🔍 [API] Tìm {len(raw_kws)} từ khóa{country_info}...")
                            channels = search_channels_multi_api(
                                raw_kws, self.max_results,
                                api_key=self.api_key,
                                region_code=self.gl,
                                relevance_language=self.hl,
                                country_filter=self.gl,   # lọc theo snippet.country
                                sub_min=self.sub_min,
                                sub_max=self.sub_max,
                                progress_cb=_api_prog,
                            )
                        else:
                            self.status.emit(f"🔍 [API] Tìm kênh: \"{self.query}\"{country_info}...")
                            channels = search_channels_api(
                                self.query, self.max_results,
                                api_key=self.api_key,
                                region_code=self.gl,
                                relevance_language=self.hl,
                                country_filter=self.gl,   # lọc theo snippet.country
                                sub_min=self.sub_min,
                                sub_max=self.sub_max,
                                progress_cb=_api_prog,
                            )
                    else:
                        self.status.emit(f"🔗 [API] Tìm kênh liên quan{country_info}...")
                        channels = get_related_channels_api(
                            self.query, self.max_results,
                            api_key=self.api_key,
                            region_code=self.gl,
                            relevance_language=self.hl,
                        )
                except Exception as e:
                    self.error.emit(str(e))
                    return

                self.results_ready.emit(channels[:self.max_results])
                return

            # ── Chế độ yt-dlp (mặc định) ────────────────────────────────────
            need_filter = self.verify_country or (self.sub_min > 0) or (self.sub_max > 0)
            candidates_multiplier = 5 if need_filter else 1

            # Phase 1: Search
            if self.mode == self.MODE_KEYWORD:
                raw_kws = [k.strip() for k in self.query.split(",") if k.strip()]
                if len(raw_kws) > 1:
                    kw_display = ", ".join(f"\"{k}\"" for k in raw_kws)
                    self.status.emit(f"🔍 Tìm {len(raw_kws)} từ khóa song song{country_info}...")

                    def _kw_prog(done, total):
                        self.status.emit(f"🔍 Từ khóa {done}/{total} xong...")

                    channels = search_channels_multi(
                        raw_kws, self.max_results,
                        gl=self.gl, hl=self.hl,
                        progress_cb=_kw_prog,
                        candidates_multiplier=candidates_multiplier,
                    )
                else:
                    self.status.emit(f"🔍 Đang tìm kênh: \"{self.query}\"{country_info}...")
                    channels = search_channels(
                        self.query, self.max_results,
                        gl=self.gl, hl=self.hl,
                        candidates_multiplier=candidates_multiplier,
                    )
            else:
                self.status.emit(f"🔗 Đang tìm kênh liên quan{country_info}...")
                channels = get_related_channels(self.query, self.max_results, gl=self.gl, hl=self.hl)

            if not channels:
                self.results_ready.emit([])
                return

            # Phase 2: Luôn fetch metadata để lấy sub count
            total = len(channels)
            self.status.emit(f"📊 Đang lấy thông tin {total} kênh...")

            def _prog(cur, tot):
                self.status.emit(f"📊 Thông tin kênh {cur}/{tot}...")

            fetch_channel_metadata_batch(channels, max_workers=4, progress_cb=_prog)

            # Phase 3: Filter
            if need_filter:
                filtered = []
                for ch in channels:
                    if self.verify_country and self.gl:
                        if ch.channel_country_code.upper() != self.gl.upper():
                            continue
                    sub_n = ch.subscriber_count_num
                    if self.sub_min > 0 and sub_n < self.sub_min:
                        continue
                    if self.sub_max > 0 and sub_n > self.sub_max:
                        continue
                    filtered.append(ch)
                    if len(filtered) >= self.max_results:
                        break
                channels = filtered

            self.results_ready.emit(channels[:self.max_results])
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n{traceback.format_exc()[:500]}")


# ── Main Tab Widget ────────────────────────────────────────────────────────────


class YtSearchTab(QWidget):
    log_message = pyqtSignal(str)
    COL_CHECK   = 0
    COL_NAME    = 1
    COL_COUNTRY = 2
    COL_SUBS    = 3
    COL_DESC    = 4
    COL_URL     = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: SearchThread | None = None
        self._results = []
        self._setup_ui()
        self._load_api_key()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # Header
        title = QLabel("🔎  YouTube Channel Finder")
        title.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #6366F1; background: transparent; border: none;")
        root.addWidget(title)

        sub = QLabel("Tìm kênh YouTube theo từ khóa hoặc kênh liên quan · Click URL để mở Chrome · Hỗ trợ lọc theo quốc gia")
        sub.setStyleSheet("color: #64748B; background: transparent; border: none; font-size: 12px;")
        root.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#E2E8F0;border:none;max-height:1px;")
        root.addWidget(sep)

        # ── Search Config ─────────────────────────────────────────────────────
        cfg = QGroupBox("Cài đặt tìm kiếm")
        cl = QVBoxLayout(cfg); cl.setSpacing(10)

        # Row 0: Search engine + API key
        row_engine = QHBoxLayout()
        engine_lbl = QLabel("🔧 Phương thức:")
        engine_lbl.setFixedWidth(110)
        row_engine.addWidget(engine_lbl)

        from PyQt6.QtWidgets import QCheckBox
        self._use_api_cb = QCheckBox("Dùng YouTube Data API v3 (chính xác hơn)")
        self._use_api_cb.setChecked(False)
        self._use_api_cb.setStyleSheet(
            "font-weight: 600; color: #6366F1;"
        )
        self._use_api_cb.toggled.connect(self._on_api_mode_toggled)
        row_engine.addWidget(self._use_api_cb)
        row_engine.addSpacing(16)

        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("Nhập YouTube Data API v3 key...")
        self._api_key_input.setMinimumHeight(34)
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setFixedWidth(310)
        self._api_key_input.setVisible(False)
        row_engine.addWidget(self._api_key_input)

        self._api_show_btn = QPushButton("👁")
        self._api_show_btn.setFixedSize(34, 34)
        self._api_show_btn.setCheckable(True)
        self._api_show_btn.setToolTip("Hiện/ẩn API key")
        self._api_show_btn.setVisible(False)
        self._api_show_btn.setStyleSheet(
            "QPushButton { background:#F1F5F9; border:1px solid #CBD5E1; border-radius:6px; }"
            "QPushButton:checked { background:#6366F1; color:white; }"
        )
        self._api_show_btn.toggled.connect(
            lambda on: self._api_key_input.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )
        row_engine.addWidget(self._api_show_btn)

        self._api_save_btn = QPushButton("💾 Lưu")
        self._api_save_btn.setFixedHeight(34)
        self._api_save_btn.setFixedWidth(72)
        self._api_save_btn.setVisible(False)
        self._api_save_btn.setStyleSheet(
            "QPushButton { background:#EEF2FF; color:#4F46E5; border:1px solid #A5B4FC;"
            "  border-radius:6px; font-weight:600; }"
            "QPushButton:hover { background:#4F46E5; color:white; }"
        )
        self._api_save_btn.clicked.connect(self._save_api_key)
        row_engine.addWidget(self._api_save_btn)

        self._api_test_btn = QPushButton("✅ Test")
        self._api_test_btn.setFixedHeight(34)
        self._api_test_btn.setFixedWidth(76)
        self._api_test_btn.setVisible(False)
        self._api_test_btn.setStyleSheet(
            "QPushButton { background:#F0FDF4; color:#16A34A; border:1px solid #86EFAC;"
            "  border-radius:6px; font-weight:600; }"
            "QPushButton:hover { background:#16A34A; color:white; }"
        )
        self._api_test_btn.clicked.connect(self._test_api_key)
        row_engine.addWidget(self._api_test_btn)

        self._api_quota_lbl = QLabel("⚡ 10,000 units/ngày")
        self._api_quota_lbl.setVisible(False)
        self._api_quota_lbl.setStyleSheet(
            "color:#F59E0B; font-size:11px; font-style:italic; background:transparent; border:none;"
        )
        row_engine.addWidget(self._api_quota_lbl)
        row_engine.addStretch()
        cl.addLayout(row_engine)

        # Row 1: Mode
        row_mode = QHBoxLayout()
        row_mode.addWidget(QLabel("Chế độ:"))
        self._mode_group = QButtonGroup(self)
        self._rb_keyword = QRadioButton("🔤  Tìm theo từ khóa")
        self._rb_keyword.setChecked(True)
        self._rb_related = QRadioButton("🔗  Kênh liên quan từ URL")
        self._mode_group.addButton(self._rb_keyword, 0)
        self._mode_group.addButton(self._rb_related, 1)
        self._rb_keyword.toggled.connect(self._on_mode_changed)
        row_mode.addWidget(self._rb_keyword)
        row_mode.addSpacing(20)
        row_mode.addWidget(self._rb_related)
        row_mode.addStretch()
        cl.addLayout(row_mode)

        # Row 2: Input + country + max
        row_input = QHBoxLayout()
        self._input_lbl = QLabel("Từ khóa:")
        self._input_lbl.setFixedWidth(85)
        row_input.addWidget(self._input_lbl)

        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("Ví dụ: kochen, küche, rezept  ·  Nhiều từ khóa cách nhau bằng dấu phẩy")
        self._query_input.setMinimumHeight(36)
        self._query_input.returnPressed.connect(self._start_search)
        row_input.addWidget(self._query_input, 1)

        row_input.addSpacing(10)

        # Country filter
        country_lbl = QLabel("🌍 Quốc gia:")
        row_input.addWidget(country_lbl)
        self._country_cmb = QComboBox()
        self._country_cmb.setFixedWidth(220)
        self._country_cmb.setMinimumHeight(36)
        self._country_cmb.setToolTip(
            "Lọc kết quả theo quốc gia/ngôn ngữ.\n"
            "Ví dụ: chọn Đức → YouTube trả kênh tiếng Đức."
        )
        from core.yt_search import get_country_labels
        for lbl in get_country_labels():
            self._country_cmb.addItem(lbl)
        row_input.addWidget(self._country_cmb)

        row_input.addSpacing(10)
        row_input.addWidget(QLabel("Số kết quả:"))
        self._max_spin = QSpinBox()
        self._max_spin.setRange(5, 50)
        self._max_spin.setValue(20)
        self._max_spin.setFixedWidth(90)
        self._max_spin.setSuffix(" kênh")
        row_input.addWidget(self._max_spin)
        cl.addLayout(row_input)

        # Row 3: Subscriber range filter
        row_sub = QHBoxLayout()
        row_sub.addWidget(QLabel("👥 Lọc Sub:"))
        self._sub_range_cmb = QComboBox()
        self._sub_range_cmb.setFixedWidth(180)
        self._sub_range_cmb.setMinimumHeight(34)
        _SUB_PRESETS = [
            ("Tất cả", 0, 0),
            ("< 1K", 0, 1_000),
            ("1K – 10K", 1_000, 10_000),
            ("10K – 100K", 10_000, 100_000),
            ("100K – 1M", 100_000, 1_000_000),
            ("1M – 10M", 1_000_000, 10_000_000),
            ("> 10M", 10_000_000, 0),
            ("Tùy chỉnh...", -1, -1),
        ]
        self._sub_presets = _SUB_PRESETS
        for lbl, _, __ in _SUB_PRESETS:
            self._sub_range_cmb.addItem(lbl)
        self._sub_range_cmb.currentIndexChanged.connect(self._on_sub_range_changed)
        row_sub.addWidget(self._sub_range_cmb)
        row_sub.addSpacing(8)

        self._sub_min_lbl = QLabel("Từ:")
        self._sub_min_spin = QSpinBox()
        self._sub_min_spin.setRange(0, 999_999_999)
        self._sub_min_spin.setValue(0)
        self._sub_min_spin.setFixedWidth(110)
        self._sub_min_spin.setSingleStep(1000)
        self._sub_min_spin.setSuffix(" sub")
        self._sub_max_lbl = QLabel("đến:")
        self._sub_max_spin = QSpinBox()
        self._sub_max_spin.setRange(0, 999_999_999)
        self._sub_max_spin.setValue(0)
        self._sub_max_spin.setFixedWidth(110)
        self._sub_max_spin.setSingleStep(1000)
        self._sub_max_spin.setSuffix(" sub")
        row_sub.addWidget(self._sub_min_lbl)
        row_sub.addWidget(self._sub_min_spin)
        row_sub.addWidget(self._sub_max_lbl)
        row_sub.addWidget(self._sub_max_spin)
        self._sub_min_lbl.setVisible(False)
        self._sub_min_spin.setVisible(False)
        self._sub_max_lbl.setVisible(False)
        self._sub_max_spin.setVisible(False)

        row_sub.addSpacing(20)
        from PyQt6.QtWidgets import QCheckBox
        self._verify_country_cb = QCheckBox("✅ Chỉ lấy kênh đúng quốc gia chọn")
        self._verify_country_cb.setChecked(False)
        self._verify_country_cb.setToolTip(
            "Sau khi tìm, sẽ kiểm tra từng kênh xem có thuộc quốc gia đã chọn không.\n"
            "Lưu ý: chậu hơn vì phải vào trang từng kênh.\n"
            "(Với chế độ API: country lấy thẳng từ YouTube, rất chính xác)"
        )
        row_sub.addWidget(self._verify_country_cb)
        row_sub.addStretch()
        cl.addLayout(row_sub)

        # Row 4: Search btn + progress
        row_btn = QHBoxLayout()
        self._search_btn = PrimaryButton("🔍  Tìm kiếm")
        self._search_btn.setFixedHeight(42)
        self._search_btn.setMinimumWidth(140)
        self._search_btn.clicked.connect(self._start_search)
        row_btn.addWidget(self._search_btn)

        self._stop_btn = QPushButton("⏹  Dừng")
        self._stop_btn.setFixedHeight(42)
        self._stop_btn.setFixedWidth(100)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_search)
        self._stop_btn.setStyleSheet("""
            QPushButton { background:#FEF2F2; color:#DC2626; border:1px solid #FCA5A5;
                border-radius:7px; font-weight:600; font-size:13px; }
            QPushButton:hover { background:#DC2626; color:white; }
            QPushButton:disabled { background:transparent; color:#CBD5E1; border-color:#E2E8F0; }
        """)
        row_btn.addWidget(self._stop_btn)
        row_btn.addSpacing(12)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(8)
        self._progress.setVisible(False)
        self._progress.setTextVisible(False)
        row_btn.addWidget(self._progress, 1)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(
            "color:#6366F1;font-size:12px;font-style:italic;background:transparent;border:none;"
        )
        row_btn.addWidget(self._status_lbl, 2)
        cl.addLayout(row_btn)
        root.addWidget(cfg)

        # ── Results Table ─────────────────────────────────────────────────────
        res_group = QGroupBox("Kết quả  ·  Click vào URL để mở Chrome")
        rl = QVBoxLayout(res_group); rl.setSpacing(6)

        info_row = QHBoxLayout()
        self._count_lbl = QLabel("Chưa có kết quả.")
        self._count_lbl.setStyleSheet("color:#64748B;font-size:12px;background:transparent;border:none;")
        info_row.addWidget(self._count_lbl)
        info_row.addStretch()
        self._select_all_btn = GhostButton("☑  Chọn tất cả")
        self._select_all_btn.setFixedHeight(28)
        self._select_all_btn.clicked.connect(self._select_all)
        info_row.addWidget(self._select_all_btn)
        self._deselect_btn = GhostButton("☐  Bỏ chọn")
        self._deselect_btn.setFixedHeight(28)
        self._deselect_btn.clicked.connect(self._deselect_all)
        info_row.addWidget(self._deselect_btn)
        rl.addLayout(info_row)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["✓", "Kênh", "🌏 Quốc gia", "Subscribers", "Mô tả", "🔗 URL (click để mở)"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)
        self._table.setSortingEnabled(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.cellClicked.connect(self._on_cell_clicked)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(self.COL_CHECK,   QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(self.COL_CHECK, 36)
        hh.setSectionResizeMode(self.COL_NAME,    QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(self.COL_NAME, 190)
        hh.setSectionResizeMode(self.COL_COUNTRY, QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(self.COL_COUNTRY, 110)
        hh.setSectionResizeMode(self.COL_SUBS,    QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(self.COL_SUBS, 110)
        hh.setSectionResizeMode(self.COL_DESC,    QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(self.COL_URL,     QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(self.COL_URL, 270)
        self._table.setMinimumHeight(300)
        self._table.setMouseTracking(True)
        rl.addWidget(self._table)
        root.addWidget(res_group, 1)

        # ── Action Bar ────────────────────────────────────────────────────────
        act_group = QGroupBox("Hành động")
        al = QHBoxLayout(act_group); al.setSpacing(8)

        self._copy_sel_btn = SecondaryButton("📋  Copy URL đã chọn")
        self._copy_sel_btn.setFixedHeight(40)
        self._copy_sel_btn.setToolTip("Copy URL các kênh đã tích ✓")
        self._copy_sel_btn.clicked.connect(self._copy_selected_urls)
        al.addWidget(self._copy_sel_btn)

        self._copy_all_btn = GhostButton("📋  Copy tất cả URL")
        self._copy_all_btn.setFixedHeight(40)
        self._copy_all_btn.clicked.connect(self._copy_all_urls)
        al.addWidget(self._copy_all_btn)

        self._export_btn = GhostButton("📄  Xuất .txt")
        self._export_btn.setFixedHeight(40)
        self._export_btn.clicked.connect(self._export_txt)
        al.addWidget(self._export_btn)

        # ━━ 3 tính năng mới ━━
        self._export_excel_btn = SecondaryButton("📊  Xuất Excel")
        self._export_excel_btn.setFixedHeight(40)
        self._export_excel_btn.setToolTip("Xuất danh sách kênh ra file .xlsx (yêu cầu openpyxl) hoặc .csv")
        self._export_excel_btn.clicked.connect(self._export_excel)
        al.addWidget(self._export_excel_btn)

        self._view_web_btn = GhostButton("🌐  Xem trên web")
        self._view_web_btn.setFixedHeight(40)
        self._view_web_btn.setToolTip("Tạo file HTML và mở trong trình duyệt")
        self._view_web_btn.clicked.connect(self._view_in_browser)
        al.addWidget(self._view_web_btn)

        self._fullscreen_btn = GhostButton("⛶  Bảng toàn màn hình")
        self._fullscreen_btn.setFixedHeight(40)
        self._fullscreen_btn.setToolTip("Mở bảng kết quả dạng popup toàn màn hình")
        self._fullscreen_btn.clicked.connect(self._open_fullscreen)
        al.addWidget(self._fullscreen_btn)

        al.addStretch()
        self._result_info_lbl = QLabel("")
        self._result_info_lbl.setStyleSheet(
            "color:#10B981;font-weight:600;font-size:12px;background:transparent;border:none;"
        )
        al.addWidget(self._result_info_lbl)
        root.addWidget(act_group)


    # ── Helpers ───────────────────────────────────────────────────────────────

    def _on_mode_changed(self):
        if self._rb_keyword.isChecked():
            self._input_lbl.setText("Từ khóa:")
            self._query_input.setPlaceholderText(
                "Ví dụ: pokedex, pokemon  ·  Nhiều từ khóa cách nhau bằng dấu phẩy"
            )
        else:
            self._input_lbl.setText("URL kênh:")
            self._query_input.setPlaceholderText("Ví dụ: https://www.youtube.com/@mkbhd")

    def _on_api_mode_toggled(self, checked: bool):
        """Hiện/ẩn API key widgets khi toggle chế độ API."""
        self._api_key_input.setVisible(checked)
        self._api_show_btn.setVisible(checked)
        self._api_save_btn.setVisible(checked)
        self._api_test_btn.setVisible(checked)
        self._api_quota_lbl.setVisible(checked)
        # Khi dùng API, verify_country không cần thiết (API trả country chính xác)
        self._verify_country_cb.setEnabled(not checked)
        if checked:
            self._verify_country_cb.setToolTip(
                "Chế độ API đã trả country chính xác — không cần bật tùy chọn này."
            )
        else:
            self._verify_country_cb.setToolTip(
                "Sau khi tìm, sẽ kiểm tra từng kênh xem có thuộc quốc gia đã chọn không.\n"
                "Lưu ý: chậu hơn vì phải vào trang từng kênh."
            )

    def _load_api_key(self):
        """Load API key đã lưu vào ô input."""
        try:
            from core.yt_search import load_api_key
            key = load_api_key()
            if key:
                self._api_key_input.setText(key)
        except Exception:
            pass

    def _save_api_key(self):
        """Lưu API key vào file settings."""
        try:
            from core.yt_search import save_api_key
            key = self._api_key_input.text().strip()
            save_api_key(key)
            self._result_info_lbl.setText("💾 Đã lưu API key!")
            self.log_message.emit(f"[YT Finder] Đã lưu API key.")
        except Exception as e:
            self._result_info_lbl.setText(f"❌ Lỗi lưu: {e}")

    def _test_api_key(self):
        """Test API key có hợp lệ không."""
        from core.yt_search import validate_api_key
        key = self._api_key_input.text().strip()
        if not key:
            self._result_info_lbl.setText("⚠️  Chưa nhập API key!")
            return
        self._api_test_btn.setEnabled(False)
        self._api_test_btn.setText("...")

        class _TestThread(QThread):
            done = pyqtSignal(bool, str)
            def __init__(self, k): super().__init__(); self._k = k
            def run(self):
                ok, msg = validate_api_key(self._k)
                self.done.emit(ok, msg)

        t = _TestThread(key)
        t.done.connect(self._on_api_test_done)
        t.finished.connect(lambda: (t.deleteLater(), setattr(self, '_test_thread', None)))
        self._test_thread = t
        t.start()

    def _on_api_test_done(self, ok: bool, msg: str):
        self._api_test_btn.setEnabled(True)
        self._api_test_btn.setText("✅ Test")
        color = "#16A34A" if ok else "#DC2626"
        self._result_info_lbl.setStyleSheet(
            f"color:{color};font-weight:600;font-size:12px;background:transparent;border:none;"
        )
        self._result_info_lbl.setText(msg)
        self.log_message.emit(f"[YT Finder] Test API: {msg}")

    def _on_sub_range_changed(self, idx: int):
        lbl, mn, mx = self._sub_presets[idx]
        custom = (mn == -1)
        self._sub_min_lbl.setVisible(custom)
        self._sub_min_spin.setVisible(custom)
        self._sub_max_lbl.setVisible(custom)
        self._sub_max_spin.setVisible(custom)
        if not custom and mn >= 0:
            self._sub_min_spin.setValue(mn)
            self._sub_max_spin.setValue(mx)

    def _get_sub_range(self):
        idx = self._sub_range_cmb.currentIndex()
        lbl, mn, mx = self._sub_presets[idx]
        if lbl == "Tất cả":
            return 0, 0
        if mn == -1:  # custom
            return self._sub_min_spin.value(), self._sub_max_spin.value()
        return mn, mx

    def _set_searching(self, on: bool):
        self._search_btn.setEnabled(not on)
        self._stop_btn.setEnabled(on)
        self._progress.setVisible(on)
        self._query_input.setEnabled(not on)
        self._rb_keyword.setEnabled(not on)
        self._rb_related.setEnabled(not on)
        self._country_cmb.setEnabled(not on)
        self._sub_range_cmb.setEnabled(not on)
        self._use_api_cb.setEnabled(not on)
        self._api_key_input.setEnabled(not on)
        self._api_save_btn.setEnabled(not on)
        self._api_test_btn.setEnabled(not on)
        if not on:
            self._status_lbl.setText("")

    def _get_gl_hl(self):
        from core.yt_search import get_country_code_by_label, get_gl_hl
        label = self._country_cmb.currentText()
        code = get_country_code_by_label(label)
        return get_gl_hl(code)

    # ── Search ────────────────────────────────────────────────────────────────

    def _start_search(self):
        query = self._query_input.text().strip()
        if not query:
            self._query_input.setFocus()
            return

        mode = SearchThread.MODE_KEYWORD if self._rb_keyword.isChecked() else SearchThread.MODE_RELATED
        gl, hl = self._get_gl_hl()
        max_r = self._max_spin.value()

        self._table.setRowCount(0)
        self._results = []
        self._count_lbl.setText("Đang tìm kiếm...")
        self._result_info_lbl.setText("")
        self._set_searching(True)

        sub_min, sub_max = self._get_sub_range()
        verify = self._verify_country_cb.isChecked() and bool(gl)
        use_api = self._use_api_cb.isChecked()
        api_key = self._api_key_input.text().strip() if use_api else ""

        if use_api and not api_key:
            self._count_lbl.setText("⚠️ Chế độ API cần nhập API key!")
            self._set_searching(False)
            return

        self._thread = SearchThread(
            mode, query, max_r, gl=gl, hl=hl,
            sub_min=sub_min, sub_max=sub_max,
            verify_country=verify,
            use_api=use_api, api_key=api_key,
        )
        self._thread.results_ready.connect(self._on_results)
        self._thread.error.connect(self._on_error)
        self._thread.status.connect(lambda m: self._status_lbl.setText(m))
        self._thread.finished.connect(lambda: self._set_searching(False))
        self._thread.start()

        country_label = self._country_cmb.currentText().strip()
        sub_info = f" | Sub: {sub_min:,}–{sub_max:,}" if sub_min or sub_max else ""
        api_info = " | [YouTube API]" if use_api else " | [yt-dlp]"
        kws = [k.strip() for k in query.split(",") if k.strip()]
        if len(kws) > 1:
            self.log_message.emit(
                f"[YT Finder] Multi-search {len(kws)} từ khóa: {', '.join(kws)} | {country_label}{sub_info}{api_info}"
            )
        else:
            self.log_message.emit(
                f"[YT Finder] Tìm: \"{query}\" | {country_label}{sub_info}{api_info}"
            )

    def _stop_search(self):
        if self._thread and self._thread.isRunning():
            self._thread.terminate()
            self._thread.wait(3000)
            if self._thread.isRunning():
                self._thread.quit()
        self._set_searching(False)
        self._count_lbl.setText("Đã dừng.")
        self._status_lbl.setText("")

    # ── Results ───────────────────────────────────────────────────────────────

    def _on_results(self, channels: list):
        self._results = channels
        self._populate_table(channels)
        n = len(channels)
        self._count_lbl.setText(f"Tìm thấy {n} kênh.")
        self.log_message.emit(f"[YT Finder] Tìm thấy {n} kênh.")

    def _on_error(self, err: str):
        self._count_lbl.setText(f"❌ Lỗi: {err}")
        self.log_message.emit(f"[YT Finder] Lỗi: {err}")

    def _populate_table(self, channels: list):
        from core.yt_search import COUNTRY_CODE_DISPLAY
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        for ch in channels:
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Checkbox
            chk = QTableWidgetItem()
            chk.setCheckState(Qt.CheckState.Unchecked)
            chk.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, self.COL_CHECK, chk)

            # Name + handle
            display = ch.name
            if ch.handle and not ch.handle.startswith("/channel/"):
                display += f"\n{ch.handle}"
            name_item = QTableWidgetItem(display)
            name_item.setFont(QFont("Inter", 11, QFont.Weight.Bold))
            self._table.setItem(row, self.COL_NAME, name_item)

            # Country (real, fetched)
            cc = ch.channel_country_code.upper()
            country_display = COUNTRY_CODE_DISPLAY.get(cc, cc) if cc else "—"
            country_item = QTableWidgetItem(country_display)
            country_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if cc:
                country_item.setForeground(QColor("#059669"))
            self._table.setItem(row, self.COL_COUNTRY, country_item)

            # Subscribers — ưu tiên text đã format, fallback từ sub_num
            from core.yt_search import _fmt_subscribers
            if ch.subscribers:
                sub_display = ch.subscribers
            elif ch.subscriber_count_num > 0:
                sub_display = _fmt_subscribers(ch.subscriber_count_num)
            else:
                sub_display = "—"
            sub_item = QTableWidgetItem(sub_display)
            sub_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            sub_item.setForeground(QColor("#6366F1") if sub_display != "—" else QColor("#94A3B8"))
            self._table.setItem(row, self.COL_SUBS, sub_item)

            # Description
            desc = ch.description.replace("\n", " ").strip()
            if len(desc) > 120:
                desc = desc[:117] + "..."
            desc_item = QTableWidgetItem(desc or "—")
            desc_item.setForeground(QColor("#64748B"))
            self._table.setItem(row, self.COL_DESC, desc_item)

            # URL — styled as link
            url_item = QTableWidgetItem(ch.url)
            url_item.setForeground(QColor("#3B82F6"))
            url_item.setToolTip("Click để mở trong Chrome / trình duyệt")
            self._table.setItem(row, self.COL_URL, url_item)

            self._table.setRowHeight(row, 48)
        self._table.setSortingEnabled(True)

    # ── Cell click → open browser ─────────────────────────────────────────────

    def _on_cell_clicked(self, row: int, col: int):
        """Click vào cột URL → mở Chrome. Click cột khác → toggle checkbox."""
        if col == self.COL_URL:
            url_item = self._table.item(row, self.COL_URL)
            if url_item and url_item.text():
                from core.yt_search import open_url_in_browser
                open_url_in_browser(url_item.text())
                self._result_info_lbl.setText("🌐 Đang mở trình duyệt...")
        elif col != self.COL_CHECK:
            # Toggle checkbox khi click vào hàng
            chk = self._table.item(row, self.COL_CHECK)
            if chk:
                new_state = (Qt.CheckState.Unchecked
                             if chk.checkState() == Qt.CheckState.Checked
                             else Qt.CheckState.Checked)
                chk.setCheckState(new_state)

    # ── Select helpers ────────────────────────────────────────────────────────

    def _select_all(self):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, self.COL_CHECK)
            if item:
                item.setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, self.COL_CHECK)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _get_checked_urls(self) -> list[str]:
        return [
            self._table.item(r, self.COL_URL).text()
            for r in range(self._table.rowCount())
            if self._table.item(r, self.COL_CHECK)
            and self._table.item(r, self.COL_CHECK).checkState() == Qt.CheckState.Checked
            and self._table.item(r, self.COL_URL)
        ]

    def _get_all_urls(self) -> list[str]:
        return [
            self._table.item(r, self.COL_URL).text()
            for r in range(self._table.rowCount())
            if self._table.item(r, self.COL_URL)
        ]

    # ── Actions ───────────────────────────────────────────────────────────────

    def _copy_selected_urls(self):
        urls = self._get_checked_urls()
        if not urls:
            self._result_info_lbl.setText("⚠️  Chưa chọn kênh nào!")
            return
        QApplication.clipboard().setText("\n".join(urls))
        self._result_info_lbl.setText(f"✅  Đã copy {len(urls)} URL!")
        self.log_message.emit(f"[YT Finder] Copy {len(urls)} URL.")

    def _copy_all_urls(self):
        urls = self._get_all_urls()
        if not urls:
            self._result_info_lbl.setText("⚠️  Không có kết quả!")
            return
        QApplication.clipboard().setText("\n".join(urls))
        self._result_info_lbl.setText(f"✅  Đã copy tất cả {len(urls)} URL!")
        self.log_message.emit(f"[YT Finder] Copy tất cả {len(urls)} URL.")

    def _export_txt(self):
        urls = self._get_checked_urls() or self._get_all_urls()
        if not urls:
            self._result_info_lbl.setText("⚠️  Không có kết quả!")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất danh sách kênh",
            os.path.join(os.path.expanduser("~"), "Desktop", "youtube_channels.txt"),
            "Text Files (*.txt)"
        )
        if not path:
            return
        lines = []
        url_set = set(urls)
        for row in range(self._table.rowCount()):
            url_item = self._table.item(row, self.COL_URL)
            name_item = self._table.item(row, self.COL_NAME)
            if url_item and url_item.text() in url_set:
                name = (name_item.text() if name_item else "").split("\n")[0]
                lines += [f"# {name}", url_item.text(), ""]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._result_info_lbl.setText(f"✅  Đã xuất {len(urls)} kênh!")
            self.log_message.emit(f"[YT Finder] Xuất {len(urls)} kênh → {path}")
        except Exception as e:
            self._result_info_lbl.setText(f"❌  Lỗi: {e}")

    # ── Context Menu ──────────────────────────────────────────────────────────

    def _show_context_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        menu = QMenu(self)
        url_item = self._table.item(row, self.COL_URL)
        name_item = self._table.item(row, self.COL_NAME)

        if url_item and url_item.text():
            url = url_item.text()
            menu.addAction("🌐  Mở trong Chrome").triggered.connect(
                lambda: __import__('core.yt_search', fromlist=['open_url_in_browser']).open_url_in_browser(url)
            )
            menu.addAction("📋  Copy URL").triggered.connect(
                lambda: QApplication.clipboard().setText(url)
            )

        if name_item:
            parts = name_item.text().split("\n")
            handle = parts[1] if len(parts) > 1 and parts[1].startswith("@") else ""
            if handle:
                menu.addAction(f"@  Copy Handle ({handle})").triggered.connect(
                    lambda: QApplication.clipboard().setText(handle)
                )

        menu.addSeparator()
        if url_item and url_item.text():
            menu.addAction("🔗  Tìm kênh liên quan").triggered.connect(
                lambda: self._find_related_from_url(url_item.text())
            )
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _find_related_from_url(self, channel_url: str):
        self._rb_related.setChecked(True)
        self._query_input.setText(channel_url)
        self._start_search()

    # ── Helper: collect table rows as list of dicts ──────────────────────────

    def _get_table_rows(self) -> list[dict]:
        """Trả về danh sách dict từng hàng trong bảng kết quả."""
        rows = []
        for r in range(self._table.rowCount()):
            def cell(c):
                item = self._table.item(r, c)
                return item.text() if item else ""
            name_raw = cell(self.COL_NAME)
            parts = name_raw.split("\n")
            name = parts[0]
            handle = parts[1] if len(parts) > 1 else ""
            rows.append({
                "name":    name,
                "handle":  handle,
                "country": cell(self.COL_COUNTRY),
                "subs":    cell(self.COL_SUBS),
                "desc":    cell(self.COL_DESC),
                "url":     cell(self.COL_URL),
            })
        return rows

    # ── Export Excel ─────────────────────────────────────────────────────

    def _export_excel(self):
        """Xuất kết quả ra file Excel (.xlsx) hoặc CSV nếu không có openpyxl."""
        rows = self._get_table_rows()
        if not rows:
            self._result_info_lbl.setText("⚠️  Không có kết quả!")
            return

        # Kiểm tra có openpyxl không
        try:
            import openpyxl
            has_openpyxl = True
        except ImportError:
            has_openpyxl = False

        if has_openpyxl:
            path, _ = QFileDialog.getSaveFileName(
                self, "Xuất Excel",
                os.path.join(os.path.expanduser("~"), "Desktop", "youtube_channels.xlsx"),
                "Excel Files (*.xlsx)"
            )
            if not path:
                return
            self._write_excel(path, rows)
        else:
            # Fallback: xuất CSV
            path, _ = QFileDialog.getSaveFileName(
                self, "Xuất CSV (openpyxl chưa được cài)",
                os.path.join(os.path.expanduser("~"), "Desktop", "youtube_channels.csv"),
                "CSV Files (*.csv)"
            )
            if not path:
                return
            self._write_csv(path, rows)

    def _write_excel(self, path: str, rows: list[dict]):
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "YouTube Channels"

        # Header
        headers = ["Tên kênh", "Handle", "Quốc gia", "Subscribers", "Mô tả", "URL"]
        HEADER_FILL  = PatternFill("solid", fgColor="4F46E5")
        HEADER_FONT  = Font(bold=True, color="FFFFFF", size=11)
        ALT_FILL     = PatternFill("solid", fgColor="EEF2FF")
        LINK_FONT    = Font(color="2563EB", underline="single")
        thin = Side(style="thin", color="D1D5DB")
        cell_border  = Border(left=thin, right=thin, top=thin, bottom=thin)

        for col, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=col, value=h)
            c.font = HEADER_FONT
            c.fill = HEADER_FILL
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = cell_border
        ws.row_dimensions[1].height = 24

        # Data rows
        col_widths = [30, 22, 14, 14, 50, 45]
        for r_idx, row in enumerate(rows, 2):
            vals = [row["name"], row["handle"], row["country"],
                    row["subs"],  row["desc"],   row["url"]]
            fill = ALT_FILL if r_idx % 2 == 0 else None
            for col_idx, val in enumerate(vals, 1):
                c = ws.cell(row=r_idx, column=col_idx, value=val)
                c.border = cell_border
                c.alignment = Alignment(vertical="center", wrap_text=(col_idx == 5))
                if fill:
                    c.fill = fill
                # URL → hyperlink + font xanh
                if col_idx == 6 and val.startswith("http"):
                    c.hyperlink = val
                    c.font = LINK_FONT
            ws.row_dimensions[r_idx].height = 20

        # Column widths
        for col_idx, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # Freeze header
        ws.freeze_panes = "A2"

        # Auto filter
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows)+1}"

        try:
            wb.save(path)
            self._result_info_lbl.setText(f"✅  Đã xuất {len(rows)} kênh → Excel!")
            self.log_message.emit(f"[YT Finder] Xuất Excel {len(rows)} kênh → {path}")
            # Mở file sau khi xuất
            import subprocess
            subprocess.Popen(["explorer", path])
        except Exception as e:
            self._result_info_lbl.setText(f"❌  Lỗi: {e}")

    def _write_csv(self, path: str, rows: list[dict]):
        import csv
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=["name","handle","country","subs","desc","url"])
                w.writeheader()
                w.writerows(rows)
            self._result_info_lbl.setText(f"✅  Đã xuất {len(rows)} kênh → CSV!")
            self.log_message.emit(f"[YT Finder] Xuất CSV {len(rows)} kênh → {path}")
            import subprocess
            subprocess.Popen(["explorer", path])
        except Exception as e:
            self._result_info_lbl.setText(f"❌  Lỗi: {e}")

    # ── View in Browser (HTML) ────────────────────────────────────────────

    def _view_in_browser(self):
        """Tạo file HTML đẹp và mở trong trình duyệt mặc định."""
        rows = self._get_table_rows()
        if not rows:
            self._result_info_lbl.setText("⚠️  Không có kết quả!")
            return

        keyword = self._query_input.text().strip() or "YouTube Channels"
        country = self._country_cmb.currentText().strip()
        html = self._build_html(rows, keyword, country)

        # Lưu vào file tạm
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", encoding="utf-8",
            delete=False, prefix="yt_channels_"
        )
        tmp.write(html)
        tmp.close()

        from core.yt_search import open_url_in_browser
        open_url_in_browser(tmp.name)
        self._result_info_lbl.setText("🌐 Đã mở trình duyệt!")
        self.log_message.emit(f"[YT Finder] Mở HTML trong trình duyệt: {tmp.name}")

    def _build_html(self, rows: list[dict], keyword: str, country: str) -> str:
        """Tạo nội dung HTML đẹp với tìm kiếm + sort + filter quốc gia + copy."""
        import json as _json
        # Build rows JS data array for rich HTML
        js_rows = []
        countries_set = set()
        for i, r in enumerate(rows):
            sub_raw = r["subs"]  # e.g. "1.2M subs", "45K subs"
            # Parse sub number for correct numeric sort
            sub_num = 0
            import re as _re
            m = _re.match(r'([\d.]+)([MKk]?)', sub_raw.replace(',', ''))
            if m:
                n, unit = float(m.group(1)), m.group(2).upper()
                sub_num = int(n * (1_000_000 if unit == 'M' else 1_000 if unit == 'K' else 1))
            country_d = r["country"]
            countries_set.add(country_d)
            js_rows.append({
                "i": i + 1,
                "name": r["name"],
                "handle": r["handle"],
                "country": country_d,
                "subs": r["subs"],
                "sub_num": sub_num,
                "desc": r["desc"],
                "url": r["url"],
            })
        countries_sorted = sorted(c for c in countries_set if c and c != '—')
        country_options = '<option value="">🌍 Tất cả quốc gia</option>'
        for c in countries_sorted:
            c_esc = c.replace('"', '&quot;')
            country_options += f'<option value="{c_esc}">{c_esc}</option>'
        js_data = _json.dumps(js_rows, ensure_ascii=False)
        kw_esc = keyword.replace('<', '&lt;').replace('"', '&quot;')
        country_esc = country.replace('<', '&lt;')
        n_total = len(rows)

        return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Channels — {kw_esc}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Inter', sans-serif; background: #0F172A; color: #E2E8F0; min-height: 100vh; padding: 24px 32px; }}
.page-header {{ margin-bottom: 18px; }}
.page-header h1 {{ font-size: 22px; font-weight: 700; color: #A5B4FC; letter-spacing: -.4px; margin-bottom: 4px; }}
.page-header .meta {{ color: #64748B; font-size: 12.5px; }}
.page-header .meta strong {{ color: #C7D2FE; }}
.toolbar {{
  display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap;
  background: #1E293B; border: 1px solid #334155; border-radius: 10px;
  padding: 10px 14px;
}}
#search-box {{
  flex: 1; min-width: 200px; padding: 8px 13px; font-size: 13px;
  background: #0F172A; border: 1px solid #334155; border-radius: 7px;
  color: #E2E8F0; outline: none; font-family: inherit;
}}
#search-box:focus {{ border-color: #6366F1; box-shadow: 0 0 0 2px rgba(99,102,241,.25); }}
#country-filter {{
  padding: 8px 12px; font-size: 13px;
  background: #0F172A; border: 1px solid #334155; border-radius: 7px;
  color: #E2E8F0; font-family: inherit; cursor: pointer; outline: none;
}}
#country-filter:focus {{ border-color: #6366F1; }}
.badge {{ background: #312E81; color: #A5B4FC; padding: 5px 14px;
  border-radius: 20px; font-size: 12px; font-weight: 700; white-space: nowrap; }}
.toolbar-btn {{
  padding: 7px 14px; border-radius: 7px; border: 1px solid #334155;
  font-size: 12px; font-weight: 600; cursor: pointer; font-family: inherit;
  background: #1E293B; color: #94A3B8; transition: all .15s; white-space: nowrap;
}}
.toolbar-btn:hover {{ background: #334155; color: #E2E8F0; }}
.toolbar-btn.green {{ background: #064E3B; color: #34D399; border-color: #065F46; }}
.toolbar-btn.green:hover {{ background: #065F46; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
thead {{ position: sticky; top: 0; z-index: 10; }}
th {{
  background: #1E293B; padding: 11px 14px; font-weight: 600; color: #64748B;
  text-align: left; border-bottom: 2px solid #334155;
  cursor: pointer; user-select: none; white-space: nowrap; font-size: 11px;
  text-transform: uppercase; letter-spacing: .04em;
}}
th:hover {{ color: #A5B4FC; }}
th.sorted-asc::after  {{ content: ' ▲'; font-size: 9px; color: #6366F1; }}
th.sorted-desc::after {{ content: ' ▼'; font-size: 9px; color: #6366F1; }}
td {{ padding: 10px 14px; border-bottom: 1px solid rgba(51,65,85,.5); vertical-align: middle; }}
tr:hover td {{ background: #1A2744; }}
tr:nth-child(even) td {{ background: rgba(30,41,59,.35); }}
.num {{ color: #475569; font-size: 12px; text-align: center; width: 36px; }}
.name-cell .ch-name {{ color: #C7D2FE; font-weight: 600; font-size: 13.5px; }}
.name-cell .ch-name:hover {{ color: #818CF8; }}
.name-cell .ch-handle {{ display: block; color: #475569; font-size: 11px; margin-top: 2px; }}
.center {{ text-align: center; }}
.country-tag {{
  display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 12px;
  font-weight: 500; background: rgba(5,150,105,.15); color: #34D399; white-space: nowrap;
}}
.country-tag.empty {{ background: rgba(71,85,105,.2); color: #475569; }}
.subs-cell {{ color: #818CF8; font-weight: 700; white-space: nowrap; text-align: center; }}
.subs-cell.empty {{ color: #334155; }}
.desc-cell {{ color: #64748B; font-size: 12px; max-width: 300px; line-height: 1.5; }}
.open-btn {{
  display: inline-block; padding: 4px 12px; border-radius: 6px; font-size: 12px;
  font-weight: 600; text-decoration: none; white-space: nowrap;
  border: 1px solid #0EA5E9; color: #38BDF8; transition: all .15s;
}}
.open-btn:hover {{ background: #0EA5E9; color: #fff; }}
.copy-btn {{
  display: inline-block; margin-left: 6px; padding: 3px 8px; border-radius: 5px;
  font-size: 11px; font-weight: 600; cursor: pointer; border: 1px solid #334155;
  background: transparent; color: #475569; font-family: inherit; transition: all .13s;
}}
.copy-btn:hover {{ background: #334155; color: #E2E8F0; }}
.copy-btn.copied {{ background: #064E3B; color: #34D399; border-color: #065F46; }}
.hidden {{ display: none !important; }}
::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: #0F172A; }}
::-webkit-scrollbar-thumb {{ background: #334155; border-radius: 3px; }}
</style>
</head>
<body>
<div class="page-header">
  <h1>🔎 YouTube Channel Finder</h1>
  <p class="meta">
    Từ khóa: <strong>{kw_esc}</strong>
    &nbsp;·&nbsp; Quốc gia: <strong>{country_esc}</strong>
    &nbsp;·&nbsp; Tìm thấy: <strong style="color:#34D399">{n_total} kênh</strong>
  </p>
</div>
<div class="toolbar">
  <input id="search-box" type="text" placeholder="🔍 Tìm nhanh: tên kênh, quốc gia, sub..." oninput="applyFilters()">
  <select id="country-filter" onchange="applyFilters()">{country_options}</select>
  <span class="badge" id="count-badge">{n_total} kênh</span>
  <button class="toolbar-btn" onclick="copyAll()">📋 Copy tất cả URL</button>
  <button class="toolbar-btn green" onclick="exportCSV()">📊 Xuất CSV</button>
</div>
<table id="main-table">
  <thead>
    <tr>
      <th onclick="sortTable(0)">#</th>
      <th onclick="sortTable(1)">Kênh</th>
      <th onclick="sortTable(2)">🌏 Quốc gia</th>
      <th onclick="sortTable(3)">Subscribers</th>
      <th>Mô tả</th>
      <th>Link</th>
    </tr>
  </thead>
  <tbody id="table-body"></tbody>
</table>
<script>
const ALL_DATA = {js_data};
let filtered = [...ALL_DATA];
let sortDir = {{}};

function render() {{
  const tbody = document.getElementById('table-body');
  if (!filtered.length) {{
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:40px;color:#475569">Không có kết quả</td></tr>';
    document.getElementById('count-badge').textContent = '0 kênh';
    return;
  }}
  tbody.innerHTML = filtered.map((r, idx) => {{
      <td class="desc-cell">${{esc(r.desc)}}</td>
      <td class="center">
        <a class="open-btn" href="${{r.url}}" target="_blank">Mở ↗</a>
        <button class="copy-btn" onclick="copyUrl(this, '${{r.url.replace(/'/g,"\'")}}')">copy</button>
      </td>
    </tr>`;
  }}).join('');
  document.getElementById('count-badge').textContent = filtered.length + ' kênh';
}}

function esc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

function applyFilters() {{
  const q = document.getElementById('search-box').value.toLowerCase();
  const ctr = document.getElementById('country-filter').value;
  filtered = ALL_DATA.filter(r => {{
    const matchQ = !q || (r.name+r.handle+r.desc+r.url+r.subs+r.country).toLowerCase().includes(q);
    const matchC = !ctr || r.country === ctr;
    return matchQ && matchC;
  }});
  sortDir = {{}};
  document.querySelectorAll('th').forEach(th => th.className = '');
  render();
}}

function sortTable(col) {{
  const keys = ['i','name','country','sub_num'];
  if (col >= keys.length) return;
  const key = keys[col];
  const asc = !sortDir[col];
  sortDir = {{}}; sortDir[col] = asc;
  document.querySelectorAll('th').forEach((th,i) => {{
    th.className = i===col ? (asc?'sorted-asc':'sorted-desc') : '';
  }});
  filtered.sort((a,b) => {{
    const va = a[key], vb = b[key];
    if (typeof va === 'number') return asc ? va-vb : vb-va;
    return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  }});
  render();
}}

function copyUrl(btn, url) {{
  navigator.clipboard.writeText(url).then(() => {{
    btn.textContent = '✓ ok';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = 'copy'; btn.classList.remove('copied'); }}, 1500);
  }});
}}

function copyAll() {{
  const urls = filtered.map(r => r.url).join('\\n');
  navigator.clipboard.writeText(urls).then(() => {{
    const btn = event.target;
    btn.textContent = '✅ Đã copy ' + filtered.length + ' URL!';
    setTimeout(() => btn.textContent = '📋 Copy tất cả URL', 2000);
  }});
}}

function exportCSV() {{
  const header = ['Tên kênh','Handle','Quốc gia','Subscribers','Mô tả','URL'];
  const csvRows = [header.map(h => `"${{h}}"`).join(',')];
  filtered.forEach(r => {{
    csvRows.push([r.name, r.handle, r.country, r.subs, r.desc, r.url]
      .map(v => `"${{String(v).replace(/"/g,'""')}}"` ).join(','));
  }});
  const blob = new Blob(["\uFEFF" + csvRows.join('\n')], {{type: 'text/csv;charset=utf-8'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'youtube_channels.csv';
  a.click();
}}

render();
</script>
</body>
</html>"""

    # ── Fullscreen Popup Table ────────────────────────────────────────────

    def _open_fullscreen(self):
        """Mở popup bảng kết quả toàn màn hình."""
        if not self._results:
            self._result_info_lbl.setText("⚠️  Không có kết quả!")
            return
        dlg = _FullscreenTableDialog(self._results, self._query_input.text().strip(), self)
        dlg.showMaximized()
        dlg.exec()


# ── Fullscreen Table Dialog ────────────────────────────────────────────

class _FullscreenTableDialog(QDialog):
    """Popup bảng kết quả toàn màn hình — hỗ trợ tìm kiếm nhanh + sort."""

    def __init__(self, channels: list, keyword: str, parent=None):
        super().__init__(parent)
        self._channels = channels
        self._keyword = keyword
        self.setWindowTitle(f"🔎 YouTube Channels — {keyword}")
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowMaximizeButtonHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self._setup_ui()
        self._populate()
        # ESC đóng
        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc.activated.connect(self.close)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header row
        hdr = QHBoxLayout()
        title = QLabel(f"🔎  YouTube Channels — <b style='color:#6366F1'>{self._keyword}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setFont(QFont("Inter", 15, QFont.Weight.Bold))
        hdr.addWidget(title)
        hdr.addStretch()
        self._fs_count_lbl = QLabel(f"{len(self._channels)} kênh")
        self._fs_count_lbl.setStyleSheet(
            "color:#6366F1;font-weight:600;font-size:13px;"
            "background:#EEF2FF;padding:4px 12px;border-radius:12px;"
        )
        hdr.addWidget(self._fs_count_lbl)
        layout.addLayout(hdr)

        # Search bar
        search_row = QHBoxLayout()
        search_lbl = QLabel("🔍  Tìm nhanh:")
        search_lbl.setStyleSheet("color:#64748B;font-size:13px;")
        search_row.addWidget(search_lbl)
        self._fs_search = QLineEdit()
        self._fs_search.setPlaceholderText("Nhập tên kênh, quốc gia, sub...")
        self._fs_search.setMinimumHeight(36)
        self._fs_search.textChanged.connect(self._filter_table)
        self._fs_search.setStyleSheet(
            "QLineEdit { border:1.5px solid #CBD5E1; border-radius:8px;"
            "  padding:5px 12px; font-size:13px; background:white; }"
            "QLineEdit:focus { border-color:#6366F1; }"
        )
        search_row.addWidget(self._fs_search, 1)
        layout.addLayout(search_row)

        # Table
        self._fs_table = QTableWidget(0, 6)
        self._fs_table.setHorizontalHeaderLabels(
            ["#", "Kênh", "🌏 Quốc gia", "Subscribers", "Mô tả", "🔗 URL"]
        )
        self._fs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._fs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._fs_table.setAlternatingRowColors(True)
        self._fs_table.verticalHeader().setVisible(False)
        self._fs_table.setShowGrid(False)
        self._fs_table.setSortingEnabled(True)
        self._fs_table.setStyleSheet("""
            QTableWidget { font-size: 13px; gridline-color: #F1F5F9; }
            QTableWidget::item { padding: 6px 10px; }
            QHeaderView::section {
                background: #1E293B; color: white;
                font-weight: 600; padding: 10px 12px;
                border: none; border-right: 1px solid #334155;
            }
            QTableWidget::item:selected { background: #EEF2FF; color: #1E293B; }
            QTableWidget::item:alternate { background: #F8FAFC; }
        """)
        hh = self._fs_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed);  hh.resizeSection(0, 40)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive); hh.resizeSection(1, 220)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive); hh.resizeSection(2, 110)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive); hh.resizeSection(3, 110)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive); hh.resizeSection(5, 280)
        self._fs_table.cellDoubleClicked.connect(self._on_dbl_click)
        layout.addWidget(self._fs_table, 1)

        # Bottom bar
        bot = QHBoxLayout()

        def _mk_btn(label, bg, fg, border, hover_bg):
            b = QPushButton(label)
            b.setFixedHeight(36)
            b.setStyleSheet(
                f"QPushButton{{background:{bg};color:{fg};border:1px solid {border};"
                f"border-radius:7px;font-weight:600;padding:0 14px;}}"
                f"QPushButton:hover{{background:{hover_bg};color:white;}}"
            )
            return b

        copy_sel_btn = _mk_btn("📋 Copy URL đã chọn", "#EEF2FF", "#4F46E5", "#A5B4FC", "#4F46E5")
        copy_sel_btn.clicked.connect(self._copy_selected)
        bot.addWidget(copy_sel_btn)

        copy_all_btn = _mk_btn("📋 Copy tất cả URL", "#F0FDF4", "#16A34A", "#86EFAC", "#16A34A")
        copy_all_btn.clicked.connect(self._copy_all)
        bot.addWidget(copy_all_btn)

        export_excel_btn = _mk_btn("📊 Xuất Excel", "#FFF7ED", "#C2410C", "#FED7AA", "#C2410C")
        export_excel_btn.clicked.connect(self._export_excel)
        bot.addWidget(export_excel_btn)

        export_txt_btn = _mk_btn("📄 Xuất .txt", "#F8FAFC", "#475569", "#CBD5E1", "#475569")
        export_txt_btn.clicked.connect(self._export_txt)
        bot.addWidget(export_txt_btn)

        bot.addStretch()
        self._fs_info_lbl = QLabel("")
        self._fs_info_lbl.setStyleSheet(
            "color:#10B981;font-weight:600;font-size:12px;background:transparent;border:none;"
        )
        bot.addWidget(self._fs_info_lbl)

        close_btn = _mk_btn("❌ Đóng (ESC)", "#FEF2F2", "#DC2626", "#FCA5A5", "#DC2626")
        close_btn.clicked.connect(self.close)
        bot.addWidget(close_btn)
        layout.addLayout(bot)

    def _populate(self):
        from core.yt_search import COUNTRY_CODE_DISPLAY, _fmt_subscribers
        self._fs_table.setSortingEnabled(False)
        self._fs_table.setRowCount(0)
        self._all_data = []
        for idx, ch in enumerate(self._channels):
            cc = ch.channel_country_code.upper()
            country_d = COUNTRY_CODE_DISPLAY.get(cc, cc) if cc else "—"
            if ch.subscribers:
                sub_d = ch.subscribers
            elif ch.subscriber_count_num > 0:
                sub_d = _fmt_subscribers(ch.subscriber_count_num)
            else:
                sub_d = "—"
            name_full = ch.name + (f"\n{ch.handle}" if ch.handle else "")
            desc = ch.description.replace("\n", " ").strip()[:150]
            self._all_data.append((idx+1, name_full, country_d, sub_d, desc, ch.url))

        self._render_rows(self._all_data)
        self._fs_table.setSortingEnabled(True)

    def _render_rows(self, data):
        self._fs_table.setSortingEnabled(False)
        self._fs_table.setRowCount(0)
        for row_data in data:
            row = self._fs_table.rowCount()
            self._fs_table.insertRow(row)

            num_item = QTableWidgetItem(str(row_data[0]))
            num_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            num_item.setForeground(QColor("#94A3B8"))
            self._fs_table.setItem(row, 0, num_item)

            name_item = QTableWidgetItem(row_data[1])
            name_item.setFont(QFont("Inter", 11, QFont.Weight.Bold))
            self._fs_table.setItem(row, 1, name_item)

            country_item = QTableWidgetItem(row_data[2])
            country_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if row_data[2] and row_data[2] != "—":
                country_item.setForeground(QColor("#059669"))
            self._fs_table.setItem(row, 2, country_item)

            sub_item = QTableWidgetItem(row_data[3])
            sub_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            sub_item.setForeground(QColor("#6366F1") if row_data[3] != "—" else QColor("#94A3B8"))
            self._fs_table.setItem(row, 3, sub_item)

            desc_item = QTableWidgetItem(row_data[4])
            desc_item.setForeground(QColor("#64748B"))
            self._fs_table.setItem(row, 4, desc_item)

            url_item = QTableWidgetItem(row_data[5])
            url_item.setForeground(QColor("#3B82F6"))
            url_item.setToolTip("Double-click để mở trong trình duyệt")
            self._fs_table.setItem(row, 5, url_item)

            self._fs_table.setRowHeight(row, 46)
        self._fs_table.setSortingEnabled(True)

    def _filter_table(self, text: str):
        q = text.lower().strip()
        if not q:
            self._render_rows(self._all_data)
            self._fs_count_lbl.setText(f"{len(self._all_data)} kênh")
            return
        filtered = [
            d for d in self._all_data
            if q in str(d).lower()
        ]
        self._render_rows(filtered)
        self._fs_count_lbl.setText(f"{len(filtered)} kênh")

    def _on_dbl_click(self, row: int, col: int):
        url_item = self._fs_table.item(row, 5)
        if url_item and url_item.text():
            from core.yt_search import open_url_in_browser
            open_url_in_browser(url_item.text())

    def _get_visible_urls(self) -> list[str]:
        return [
            self._fs_table.item(r, 5).text()
            for r in range(self._fs_table.rowCount())
            if self._fs_table.item(r, 5) and not self._fs_table.isRowHidden(r)
        ]

    def _copy_selected(self):
        urls = self._get_visible_urls()
        if urls:
            QApplication.clipboard().setText("\n".join(urls))
            self._fs_info_lbl.setText(f"✅ Đã copy {len(urls)} URL!")

    def _copy_all(self):
        urls = self._get_visible_urls()
        if urls:
            QApplication.clipboard().setText("\n".join(urls))
            self._fs_info_lbl.setText(f"✅ Đã copy {len(urls)} URL!")

    def _export_excel(self):
        if not self._channels:
            return
        try:
            import openpyxl
        except ImportError:
            self._export_txt()
            return
        import os
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất Excel",
            os.path.join(os.path.expanduser("~"), "Desktop", "youtube_channels.xlsx"),
            "Excel Files (*.xlsx)"
        )
        if not path:
            return
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from core.yt_search import COUNTRY_CODE_DISPLAY, _fmt_subscribers
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "YouTube Channels"
        headers = ["#", "Tên kênh", "Handle", "Quốc gia", "Subscribers", "Mô tả", "URL"]
        hfill = PatternFill("solid", fgColor="4F46E5")
        hfont = Font(bold=True, color="FFFFFF", size=11)
        alt   = PatternFill("solid", fgColor="EEF2FF")
        link_font = Font(color="2563EB", underline="single")
        thin = Side(style="thin", color="D1D5DB")
        bdr  = Border(left=thin, right=thin, top=thin, bottom=thin)
        for ci, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=ci, value=h)
            c.font = hfont; c.fill = hfill
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = bdr
        ws.row_dimensions[1].height = 24
        for ri, ch in enumerate(self._channels, 2):
            cc = ch.channel_country_code.upper()
            country_d = COUNTRY_CODE_DISPLAY.get(cc, cc) if cc else "—"
            sub_d = ch.subscribers or (_fmt_subscribers(ch.subscriber_count_num) if ch.subscriber_count_num else "—")
            vals = [ri-1, ch.name, ch.handle, country_d, sub_d, ch.description[:120], ch.url]
            fill = alt if ri % 2 == 0 else None
            for ci, val in enumerate(vals, 1):
                c = ws.cell(row=ri, column=ci, value=val)
                c.border = bdr
                c.alignment = Alignment(vertical="center", wrap_text=(ci==6))
                if fill: c.fill = fill
                if ci == 7 and str(val).startswith("http"):
                    c.hyperlink = val; c.font = link_font
            ws.row_dimensions[ri].height = 20
        for ci, w in enumerate([6, 28, 20, 14, 14, 45, 42], 1):
            ws.column_dimensions[get_column_letter(ci)].width = w
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(self._channels)+1}"
        try:
            wb.save(path)
            self._fs_info_lbl.setText(f"✅ Đã xuất {len(self._channels)} kênh → Excel!")
            import subprocess
            subprocess.Popen(["explorer", path])
        except Exception as e:
            self._fs_info_lbl.setText(f"❌ Lỗi: {e}")

    def _export_txt(self):
        if not self._channels:
            return
        import os
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất .txt",
            os.path.join(os.path.expanduser("~"), "Desktop", "youtube_channels.txt"),
            "Text Files (*.txt)"
        )
        if not path:
            return
        lines = []
        for ch in self._channels:
            lines += [f"# {ch.name}", ch.url, ""]
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            self._fs_info_lbl.setText(f"✅ Đã xuất {len(self._channels)} kênh!")
        except Exception as e:
            self._fs_info_lbl.setText(f"❌ Lỗi: {e}")
