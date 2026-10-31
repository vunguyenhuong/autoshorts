"""
AutoSub Tab - Batch Auto Subtitle for Complete Videos
Input: a folder containing one or more finished videos
Output: subtitle burned directly into each video (in-place replacement)
Reuses subtitle logic from subtitle_processor.py (same as AutoCut)
"""

import os
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QFileDialog, QSpinBox,
    QDoubleSpinBox, QGroupBox, QFormLayout,
    QCheckBox, QComboBox, QColorDialog, QScrollArea,
    QMessageBox, QProgressBar, QSizePolicy, QFrame,
    QButtonGroup, QRadioButton
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor

from core.subtitle_processor import (
    SubtitleConfig,
    transcribe_audio, build_subtitle_blocks, generate_ass_file
)
from ui.components import PrimaryButton, GhostButton, DangerButton, StyledProgressBar


VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.wmv'}


def escape_ffmpeg_vf_path(path: str) -> str:
    r"""
    Escape file path for FFmpeg -vf ass='...' or subtitles='...' on Windows.
    - Convert backslashes to forward slashes.
    - Escape colons ':' -> '\:'
    - Escape single quotes "'" -> "\'\'"
    - Wrap in single quotes "'...'"
    """
    p = str(Path(path).resolve()).replace('\\', '/')
    p = p.replace(":", r"\:")
    p = p.replace("'", r"\'\'")
    return f"'{p}'"


# ---------------------------------------------------------------------------
#  BatchSubtitleWorker -- processes each video sequentially
# ---------------------------------------------------------------------------

class BatchSubtitleWorker(QThread):
    """
    Sequential worker: for each video in the list
      1. transcribe with faster-whisper
      2. build blocks & write .ass file
      3. burn ass into video via FFmpeg (replace original or save to folder)
    """
    progress = pyqtSignal(str)
    video_done = pyqtSignal(int, int, bool)   # (done_count, total, success)
    finished = pyqtSignal(int, int)            # (success_count, fail_count)

    def __init__(self, video_list: list, cfg: SubtitleConfig,
                 output_mode: str = "inplace",   # "inplace" | "folder"
                 output_folder: str = "",
                 ffmpeg_exe: str = "ffmpeg",
                 parent=None):
        super().__init__(parent)
        self.video_list = video_list
        self.cfg = cfg
        self.output_mode = output_mode
        self.output_folder = output_folder
        self.ffmpeg_exe = ffmpeg_exe
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        total = len(self.video_list)
        success = 0
        fail = 0

        self.progress.emit(f"[AutoSub] Bat dau xu ly {total} video...")

        for i, video_path in enumerate(self.video_list):
            if not self._is_running:
                self.progress.emit("[AutoSub] Da dung theo yeu cau nguoi dung.")
                break

            name = Path(video_path).name
            self.progress.emit(f"\n-- [{i+1}/{total}] {name} --")

            try:
                # Step 1: transcribe
                word_segs = transcribe_audio(
                    video_path,
                    model_size=self.cfg.model_size,
                    beam_size=getattr(self.cfg, 'beam_size', 5),
                    initial_prompt=getattr(self.cfg, 'initial_prompt', ''),
                    progress_callback=lambda m: self.progress.emit(m)
                )

                if not word_segs:
                    self.progress.emit("Khong tim thay loi noi -- bo qua.")
                    fail += 1
                    self.video_done.emit(i + 1, total, False)
                    continue

                # Step 2: build blocks & write .ass
                self.progress.emit(f"Chia cau ({len(word_segs)} tu)...")
                blocks = build_subtitle_blocks(word_segs, self.cfg)
                self.progress.emit(f"Tao duoc {len(blocks)} subtitle block.")

                stem = Path(video_path).stem
                ass_dir = os.path.join(os.path.dirname(video_path), "_subtitles")
                os.makedirs(ass_dir, exist_ok=True)
                ass_path = os.path.join(ass_dir, f"{stem}.ass")
                generate_ass_file(blocks, ass_path, self.cfg)
                self.progress.emit(f"Ghi file ASS: {Path(ass_path).name}")

                # Step 3: burn with FFmpeg
                if self.output_mode == "folder" and self.output_folder:
                    os.makedirs(self.output_folder, exist_ok=True)
                    out_path = os.path.join(self.output_folder, Path(video_path).name)
                else:
                    # inplace: use a temp name, then replace
                    base, ext = os.path.splitext(video_path)
                    out_path = base + "_subbed" + ext

                ass_escaped = escape_ffmpeg_vf_path(ass_path)
                cmd = [
                    self.ffmpeg_exe, '-y',
                    '-i', os.path.abspath(video_path),
                    '-vf', f"ass={ass_escaped}",
                    '-c:a', 'copy',
                    os.path.abspath(out_path)
                ]
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE

                self.progress.emit(f"Burn subtitle vao: {Path(out_path).name}...")
                res = subprocess.run(cmd, capture_output=True, text=True,
                                     startupinfo=startupinfo, timeout=1800)

                if res.returncode == 0 and os.path.exists(out_path):
                    if self.output_mode == "inplace":
                        os.replace(out_path, video_path)
                        self.progress.emit(f"OK - Da burn vao file goc: {name}")
                    else:
                        self.progress.emit(f"OK - Xuat ra: {Path(out_path).name}")
                    success += 1
                    self.video_done.emit(i + 1, total, True)
                else:
                    self.progress.emit(f"LOI FFmpeg: {res.stderr[-400:]}")
                    if os.path.exists(out_path):
                        try:
                            os.remove(out_path)
                        except Exception:
                            pass
                    fail += 1
                    self.video_done.emit(i + 1, total, False)

            except Exception as e:
                import traceback
                self.progress.emit(f"LOI: {e}")
                self.progress.emit(traceback.format_exc())
                fail += 1
                self.video_done.emit(i + 1, total, False)

        self.progress.emit(
            f"\nKet qua: {success} thanh cong, {fail} loi / {total} video."
        )
        self.finished.emit(success, fail)


# ---------------------------------------------------------------------------
#  AutoSubTab
# ---------------------------------------------------------------------------

class AutoSubTab(QWidget):
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        # Color state (RGB tuples for display)
        self._subtitle_color = (255, 255, 255)
        self._subtitle_hl_color = (255, 255, 0)

        # Worker ref
        self._worker = None

        # Settings directory
        import sys
        if getattr(sys, 'frozen', False):
            self._settings_dir = os.path.join(os.path.dirname(sys.executable), "settings")
        else:
            self._settings_dir = os.path.join(os.getcwd(), "settings")

        self._setup_ui()
        self._load_config(silent=True)

    # -- FFmpeg path -----------------------------------------------------------

    @staticmethod
    def _get_ffmpeg() -> str:
        try:
            from core.autocut_processor import FFMPEG_EXE
            return FFMPEG_EXE
        except Exception:
            import sys
            base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            candidate = os.path.join(base, 'ffmpeg', 'ffmpeg.exe')
            return candidate if os.path.exists(candidate) else 'ffmpeg'

    # -- UI -------------------------------------------------------------------

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)
        scroll.setWidget(body)

        # Header
        header = QFrame()
        header.setObjectName("SubHeader")
        header.setStyleSheet(
            "#SubHeader {"
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #7c3aed,stop:1 #4f46e5);"
            "border-radius: 10px; padding: 4px; }"
        )
        hl = QVBoxLayout(header)
        hl.setContentsMargins(20, 14, 20, 14)
        title_lbl = QLabel("AutoSub - Phu de tu dong cho video hoan chinh")
        title_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: white; background: transparent; border: none;")
        hl.addWidget(title_lbl)
        desc_lbl = QLabel(
            "Chon folder chua video >> Nhan dien giong noi (Whisper) >> Burn phu de ASS vao video"
        )
        desc_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.8); font-size: 11px; background: transparent; border: none;"
        )
        hl.addWidget(desc_lbl)
        root.addWidget(header)

        # Input folder
        input_group = QGroupBox("Thu muc nguon")
        ig_layout = QHBoxLayout(input_group)
        self.input_folder_edit = QLineEdit()
        self.input_folder_edit.setPlaceholderText("Thu muc chua video hoan chinh can sub...")
        self.input_folder_edit.textChanged.connect(self._refresh_video_list)
        ig_layout.addWidget(self.input_folder_edit, 1)
        browse_input_btn = QPushButton("Chon")
        browse_input_btn.setFixedWidth(80)
        browse_input_btn.clicked.connect(self._browse_input)
        ig_layout.addWidget(browse_input_btn)
        root.addWidget(input_group)

        # Scan mode
        scan_group = QGroupBox("Che do quet")
        sg_layout = QHBoxLayout(scan_group)
        self.scan_recursive_checkbox = QCheckBox("Quet ca subfolder (recursive)")
        self.scan_recursive_checkbox.setToolTip(
            "Bat: quet tat ca cac folder con ben trong thu muc nguon.\n"
            "Tat: chi quet truc tiep thu muc nguon."
        )
        self.scan_recursive_checkbox.stateChanged.connect(self._refresh_video_list)
        sg_layout.addWidget(self.scan_recursive_checkbox)
        sg_layout.addStretch()
        self.video_count_label = QLabel("Chua quet")
        self.video_count_label.setStyleSheet(
            "color: #6366f1; font-weight: 600; font-size: 11px; background: transparent; border: none;"
        )
        sg_layout.addWidget(self.video_count_label)
        root.addWidget(scan_group)

        # Output mode
        out_group = QGroupBox("Dau ra")
        og_layout = QVBoxLayout(out_group)
        mode_row = QHBoxLayout()
        self.out_mode_group = QButtonGroup(self)
        self.out_inplace_radio = QRadioButton("Burn thang vao file goc (In-place)")
        self.out_inplace_radio.setChecked(True)
        self.out_inplace_radio.setToolTip("Video goc se duoc thay the bang phien ban da co subtitle.")
        self.out_folder_radio = QRadioButton("Xuat ra thu muc khac")
        self.out_mode_group.addButton(self.out_inplace_radio, 0)
        self.out_mode_group.addButton(self.out_folder_radio, 1)
        self.out_inplace_radio.toggled.connect(self._on_output_mode_changed)
        mode_row.addWidget(self.out_inplace_radio)
        mode_row.addSpacing(20)
        mode_row.addWidget(self.out_folder_radio)
        mode_row.addStretch()
        og_layout.addLayout(mode_row)

        self.out_folder_widget = QWidget()
        ofw_layout = QHBoxLayout(self.out_folder_widget)
        ofw_layout.setContentsMargins(0, 0, 0, 0)
        self.output_folder_edit = QLineEdit()
        self.output_folder_edit.setPlaceholderText("Thu muc dich...")
        ofw_layout.addWidget(self.output_folder_edit, 1)
        browse_out_btn = QPushButton("Chon")
        browse_out_btn.setFixedWidth(80)
        browse_out_btn.clicked.connect(self._browse_output)
        ofw_layout.addWidget(browse_out_btn)
        og_layout.addWidget(self.out_folder_widget)
        self.out_folder_widget.setVisible(False)
        root.addWidget(out_group)

        # Subtitle settings
        sub_group = QGroupBox("Cai dat Subtitle")
        sub_layout = QFormLayout(sub_group)
        sub_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        sub_layout.setSpacing(8)
        sub_layout.setContentsMargins(12, 12, 12, 12)

        self.model_combo = QComboBox()
        self.model_combo.addItem("tiny  (nhanh nhat, kem chinh xac)", "tiny")
        self.model_combo.addItem("base  (can bang - mac dinh)", "base")
        self.model_combo.addItem("small  (chinh xac kha, nhanh)", "small")
        self.model_combo.addItem("medium  (chinh xac cao)", "medium")
        self.model_combo.addItem("large-v3-turbo  (cuc chuan + nhanh)", "large-v3-turbo")
        self.model_combo.addItem("large-v3  (chinh xac nhat, nang)", "large-v3")
        self.model_combo.setCurrentIndex(1)
        sub_layout.addRow("Whisper Model:", self.model_combo)

        # Beam Search size
        beam_widget = QWidget()
        beam_row = QHBoxLayout(beam_widget)
        beam_row.setContentsMargins(0, 0, 0, 0)
        beam_row.setSpacing(6)
        self.beam_size_spin = QSpinBox()
        self.beam_size_spin.setRange(1, 10)
        self.beam_size_spin.setValue(5)
        self.beam_size_spin.setToolTip(
            "1 = Greedy search (nhanh hon)\n"
            "5 = Beam Search (mac dinh, chinh xac hon gap nhieu lan)"
        )
        self.beam_size_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        beam_row.addWidget(self.beam_size_spin)
        sub_layout.addRow("Beam Search:", beam_widget)

        # Context Prompt
        self.initial_prompt_edit = QLineEdit()
        self.initial_prompt_edit.setPlaceholderText("Vi du: Tieng Viet chuan, ten rieng, tu vung cong nghe...")
        self.initial_prompt_edit.setToolTip(
            "Cung cap ngu canh goi y cho Whisper AI (ten rieng, dau cau, tu chuyen nganh)\n"
            "de AI uu tien nhan dien chuan xac nhat."
        )
        sub_layout.addRow("Context Prompt:", self.initial_prompt_edit)

        # Font
        font_widget = QWidget()
        font_row = QHBoxLayout(font_widget)
        font_row.setContentsMargins(0, 0, 0, 0)
        font_row.setSpacing(6)
        self.font_name_edit = QLineEdit("Arial")
        self.font_name_edit.setPlaceholderText("Font Unicode ho tro tieng Viet...")
        font_row.addWidget(self.font_name_edit, 2)
        font_row.addWidget(QLabel("Size:"))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(20, 200)
        self.font_size_spin.setValue(72)
        self.font_size_spin.setSuffix("pt")
        self.font_size_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        font_row.addWidget(self.font_size_spin)
        sub_layout.addRow("Font:", font_widget)

        # Colors
        color_widget = QWidget()
        color_row = QHBoxLayout(color_widget)
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.setSpacing(6)
        color_row.addWidget(QLabel("Chu:"))
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(24, 24)
        self.color_preview.setStyleSheet(
            f"background-color: rgb{self._subtitle_color}; border: 1px solid #555; border-radius: 3px;"
        )
        color_row.addWidget(self.color_preview)
        color_btn = QPushButton("...")
        color_btn.setMaximumWidth(32)
        color_btn.clicked.connect(self._pick_color)
        color_row.addWidget(color_btn)
        color_row.addSpacing(16)
        color_row.addWidget(QLabel("Highlight:"))
        self.hl_color_preview = QLabel()
        self.hl_color_preview.setFixedSize(24, 24)
        self.hl_color_preview.setStyleSheet(
            f"background-color: rgb{self._subtitle_hl_color}; border: 1px solid #555; border-radius: 3px;"
        )
        color_row.addWidget(self.hl_color_preview)
        hl_color_btn = QPushButton("...")
        hl_color_btn.setMaximumWidth(32)
        hl_color_btn.clicked.connect(self._pick_hl_color)
        color_row.addWidget(hl_color_btn)
        color_row.addStretch()
        sub_layout.addRow("Mau sac:", color_widget)

        # Style
        style_widget = QWidget()
        style_row = QHBoxLayout(style_widget)
        style_row.setContentsMargins(0, 0, 0, 0)
        style_row.setSpacing(6)
        style_row.addWidget(QLabel("Outline:"))
        self.outline_spin = QDoubleSpinBox()
        self.outline_spin.setRange(0.0, 10.0)
        self.outline_spin.setValue(3.0)
        self.outline_spin.setSingleStep(0.5)
        self.outline_spin.setDecimals(1)
        self.outline_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        style_row.addWidget(self.outline_spin)
        style_row.addWidget(QLabel("Shadow:"))
        self.shadow_spin = QDoubleSpinBox()
        self.shadow_spin.setRange(0.0, 10.0)
        self.shadow_spin.setValue(2.0)
        self.shadow_spin.setSingleStep(0.5)
        self.shadow_spin.setDecimals(1)
        self.shadow_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        style_row.addWidget(self.shadow_spin)
        style_row.addWidget(QLabel("Margin:"))
        self.margin_spin = QSpinBox()
        self.margin_spin.setRange(0, 1920)
        self.margin_spin.setValue(120)
        self.margin_spin.setSuffix("px")
        self.margin_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        style_row.addWidget(self.margin_spin)
        sub_layout.addRow("Style:", style_widget)

        # Word highlight
        self.word_hl_checkbox = QCheckBox("Word-level Highlight (tung tu doi mau khi noi)")
        self.word_hl_checkbox.setToolTip(
            "Tu dang duoc noi se doi mau sang mau Highlight.\n"
            "Yeu cau FFmpeg build voi libass. Mac dinh: TAT."
        )
        sub_layout.addRow("", self.word_hl_checkbox)

        # Max chars per line
        self.max_chars_spin = QSpinBox()
        self.max_chars_spin.setRange(10, 80)
        self.max_chars_spin.setValue(40)
        self.max_chars_spin.setToolTip("So ky tu toi da tren moi dong. Khuyen: 35-45.")
        self.max_chars_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_layout.addRow("Max ky tu/dong:", self.max_chars_spin)

        # Max words per block
        self.max_words_spin = QSpinBox()
        self.max_words_spin.setRange(1, 30)
        self.max_words_spin.setValue(5)
        self.max_words_spin.setToolTip("So tu toi da trong 1 cum subtitle. Khuyen: 4-6.")
        self.max_words_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_layout.addRow("Max tu/cum:", self.max_words_spin)

        # Max lines per block
        self.max_lines_spin = QSpinBox()
        self.max_lines_spin.setRange(1, 3)
        self.max_lines_spin.setValue(1)
        self.max_lines_spin.setToolTip("So dong toi da trong 1 cum subtitle (Mac dinh: 1 dong).")
        self.max_lines_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sub_layout.addRow("Max dong/cum:", self.max_lines_spin)

        root.addWidget(sub_group)

        # Config buttons
        cfg_row = QHBoxLayout()
        save_cfg_btn = GhostButton("Luu cau hinh")
        save_cfg_btn.clicked.connect(self._save_config)
        cfg_row.addWidget(save_cfg_btn)
        load_cfg_btn = GhostButton("Tai cau hinh")
        load_cfg_btn.clicked.connect(self._load_config)
        cfg_row.addWidget(load_cfg_btn)
        cfg_row.addStretch()
        root.addLayout(cfg_row)

        # Progress
        self.progress_bar = StyledProgressBar()
        self.progress_bar.setVisible(False)
        root.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "color: #6366f1; font-weight: 600; font-size: 11px; background: transparent; border: none;"
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        # Action buttons
        action_row = QHBoxLayout()
        self.run_btn = PrimaryButton("Bat dau AutoSub")
        self.run_btn.setFixedHeight(50)
        self.run_btn.clicked.connect(self._start)
        action_row.addWidget(self.run_btn, 2)

        self.stop_btn = DangerButton("Dung")
        self.stop_btn.setFixedHeight(50)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        action_row.addWidget(self.stop_btn, 1)
        root.addLayout(action_row)

        root.addStretch()

        # Assemble
        tab_layout = QVBoxLayout(self)
        tab_layout.setContentsMargins(0, 0, 0, 0)
        tab_layout.addWidget(scroll)

    # -- Helpers --------------------------------------------------------------

    def _browse_input(self):
        folder = QFileDialog.getExistingDirectory(self, "Chon thu muc nguon chua video")
        if folder:
            self.input_folder_edit.setText(folder)

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Chon thu muc dich")
        if folder:
            self.output_folder_edit.setText(folder)

    def _on_output_mode_changed(self):
        self.out_folder_widget.setVisible(self.out_folder_radio.isChecked())

    def _refresh_video_list(self):
        folder = self.input_folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            self.video_count_label.setText("Chua quet")
            return
        videos = self._collect_videos(folder)
        n = len(videos)
        if n == 0:
            self.video_count_label.setText("Khong co video")
        else:
            self.video_count_label.setText(f"{n} video")

    def _collect_videos(self, folder: str) -> list:
        """Collect video files from folder (and optionally subfolders)."""
        videos = []
        recursive = self.scan_recursive_checkbox.isChecked()
        if recursive:
            for root_dir, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
                for f in sorted(files):
                    if Path(f).suffix.lower() in VIDEO_EXTS:
                        videos.append(os.path.join(root_dir, f))
        else:
            try:
                for f in sorted(os.listdir(folder)):
                    if Path(f).suffix.lower() in VIDEO_EXTS:
                        videos.append(os.path.join(folder, f))
            except Exception:
                pass
        return videos

    def _build_config(self) -> SubtitleConfig:
        cfg = SubtitleConfig()
        cfg.enabled = True
        cfg.model_size = self.model_combo.currentData() or "base"
        cfg.beam_size = self.beam_size_spin.value()
        cfg.initial_prompt = self.initial_prompt_edit.text().strip()
        cfg.font_name = self.font_name_edit.text().strip() or "Arial"
        cfg.font_size = self.font_size_spin.value()
        cfg.outline_width = self.outline_spin.value()
        cfg.shadow_depth = self.shadow_spin.value()
        cfg.margin_v = self.margin_spin.value()
        cfg.enable_word_highlight = self.word_hl_checkbox.isChecked()
        cfg.max_chars_per_line = self.max_chars_spin.value()
        cfg.max_words_per_block = self.max_words_spin.value()
        cfg.max_lines_per_block = self.max_lines_spin.value()
        cfg.primary_color = self._rgb_to_ass(self._subtitle_color)
        cfg.highlight_color = self._rgb_to_ass(self._subtitle_hl_color)
        cfg.outline_color = "&H00000000"
        cfg.shadow_color = "&H80000000"
        return cfg

    @staticmethod
    def _rgb_to_ass(rgb: tuple, alpha: int = 0) -> str:
        r, g, b = rgb[0], rgb[1], rgb[2]
        return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

    def _pick_color(self):
        color = QColorDialog.getColor(QColor(*self._subtitle_color), self, "Chon mau chu subtitle")
        if color.isValid():
            self._subtitle_color = (color.red(), color.green(), color.blue())
            self.color_preview.setStyleSheet(
                f"background-color: rgb{self._subtitle_color}; border: 1px solid #555; border-radius: 3px;"
            )

    def _pick_hl_color(self):
        color = QColorDialog.getColor(QColor(*self._subtitle_hl_color), self, "Chon mau Highlight")
        if color.isValid():
            self._subtitle_hl_color = (color.red(), color.green(), color.blue())
            self.hl_color_preview.setStyleSheet(
                f"background-color: rgb{self._subtitle_hl_color}; border: 1px solid #555; border-radius: 3px;"
            )

    # -- Start / Stop ---------------------------------------------------------

    def _start(self):
        folder = self.input_folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Loi", "Vui long chon thu muc nguon hop le!")
            return

        videos = self._collect_videos(folder)
        if not videos:
            QMessageBox.warning(self, "Khong co video", "Khong tim thay video nao trong thu muc da chon!")
            return

        output_mode = "inplace" if self.out_inplace_radio.isChecked() else "folder"
        output_folder = ""
        if output_mode == "folder":
            output_folder = self.output_folder_edit.text().strip()
            if not output_folder:
                QMessageBox.warning(self, "Loi", "Vui long chon thu muc dich!")
                return

        cfg = self._build_config()
        ffmpeg = self._get_ffmpeg()

        self.run_btn.setEnabled(False)
        self.run_btn.setText("Dang xu ly...")
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setMaximum(len(videos))
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Dang xu ly 0 / {len(videos)} video...")

        self._worker = BatchSubtitleWorker(
            video_list=videos,
            cfg=cfg,
            output_mode=output_mode,
            output_folder=output_folder,
            ffmpeg_exe=ffmpeg,
            parent=self
        )
        self._worker.progress.connect(self.log_message)
        self._worker.video_done.connect(self._on_video_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self.log_message.emit("[AutoSub] Yeu cau dung da duoc gui...")
            self.stop_btn.setEnabled(False)

    def _on_video_done(self, done: int, total: int, success: bool):
        self.progress_bar.setValue(done)
        icon = "OK" if success else "LOI"
        self.status_label.setText(f"[{icon}] Xong {done} / {total} video")

    def _on_finished(self, success: int, fail: int):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Bat dau AutoSub")
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)

        if fail == 0:
            self.status_label.setText(f"Hoan tat! {success} video da co subtitle.")
            QMessageBox.information(self, "Hoan tat", f"Da burn subtitle thanh cong vao {success} video!")
        else:
            self.status_label.setText(f"{success} thanh cong, {fail} loi.")
            QMessageBox.warning(
                self, "Hoan tat (co loi)",
                f"{success} video thanh cong\n{fail} video loi\n\nXem log de biet chi tiet."
            )

    # -- Config persistence ---------------------------------------------------

    def _get_settings(self) -> dict:
        return {
            "input_folder": self.input_folder_edit.text(),
            "scan_recursive": self.scan_recursive_checkbox.isChecked(),
            "output_mode": "folder" if self.out_folder_radio.isChecked() else "inplace",
            "output_folder": self.output_folder_edit.text(),
            "model": self.model_combo.currentData(),
            "beam_size": self.beam_size_spin.value(),
            "initial_prompt": self.initial_prompt_edit.text(),
            "font_name": self.font_name_edit.text(),
            "font_size": self.font_size_spin.value(),
            "outline": self.outline_spin.value(),
            "shadow": self.shadow_spin.value(),
            "margin_v": self.margin_spin.value(),
            "word_hl": self.word_hl_checkbox.isChecked(),
            "max_chars": self.max_chars_spin.value(),
            "max_words": self.max_words_spin.value(),
            "max_lines": self.max_lines_spin.value(),
            "color": list(self._subtitle_color),
            "hl_color": list(self._subtitle_hl_color),
        }

    def _apply_settings(self, s: dict):
        if "input_folder" in s:
            self.input_folder_edit.setText(s["input_folder"])
        if "scan_recursive" in s:
            self.scan_recursive_checkbox.setChecked(bool(s["scan_recursive"]))
        if "output_mode" in s:
            if s["output_mode"] == "folder":
                self.out_folder_radio.setChecked(True)
            else:
                self.out_inplace_radio.setChecked(True)
        if "output_folder" in s:
            self.output_folder_edit.setText(s["output_folder"])
        if "model" in s:
            idx = self.model_combo.findData(s["model"])
            if idx >= 0:
                self.model_combo.setCurrentIndex(idx)
        if "beam_size" in s:
            self.beam_size_spin.setValue(int(s["beam_size"]))
        if "initial_prompt" in s:
            self.initial_prompt_edit.setText(str(s["initial_prompt"]))
        if "font_name" in s:
            self.font_name_edit.setText(s["font_name"])
        if "font_size" in s:
            self.font_size_spin.setValue(int(s["font_size"]))
        if "outline" in s:
            self.outline_spin.setValue(float(s["outline"]))
        if "shadow" in s:
            self.shadow_spin.setValue(float(s["shadow"]))
        if "margin_v" in s:
            self.margin_spin.setValue(int(s["margin_v"]))
        if "word_hl" in s:
            self.word_hl_checkbox.setChecked(bool(s["word_hl"]))
        if "max_chars" in s:
            self.max_chars_spin.setValue(int(s["max_chars"]))
        if "max_words" in s:
            self.max_words_spin.setValue(int(s["max_words"]))
        if "max_lines" in s:
            self.max_lines_spin.setValue(int(s["max_lines"]))
        if "color" in s:
            self._subtitle_color = tuple(s["color"])
            self.color_preview.setStyleSheet(
                f"background-color: rgb{self._subtitle_color}; border: 1px solid #555; border-radius: 3px;"
            )
        if "hl_color" in s:
            self._subtitle_hl_color = tuple(s["hl_color"])
            self.hl_color_preview.setStyleSheet(
                f"background-color: rgb{self._subtitle_hl_color}; border: 1px solid #555; border-radius: 3px;"
            )

    def _save_config(self):
        import json
        os.makedirs(self._settings_dir, exist_ok=True)
        path = os.path.join(self._settings_dir, "autosub_config.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._get_settings(), f, indent=4, ensure_ascii=False)
            QMessageBox.information(self, "Da luu", f"Cau hinh AutoSub da luu:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Loi", f"Khong the luu cau hinh:\n{e}")

    def _load_config(self, silent=False):
        import json
        if not isinstance(silent, bool):
            silent = False
        path = os.path.join(self._settings_dir, "autosub_config.json")
        if not os.path.exists(path):
            if not silent:
                QMessageBox.warning(self, "Chua co cau hinh", "Chua co file autosub_config.json trong thu muc settings.")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                s = json.load(f)
            self._apply_settings(s)
            if not silent:
                QMessageBox.information(self, "Da tai", "Cau hinh AutoSub da duoc tai!")
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Loi", f"Khong the tai cau hinh:\n{e}")
