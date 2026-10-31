"""
Voice Clone & Voice Conversion Tab
UI Module for converting voice in Video A to target Voice B.
- Input Video A: .mp4
- Input Voice B: .mp4, .mp3, .wav, .m4a
- Auto audio extraction from Voice B
- Zero-Shot Voice Clone & RVC model conversion (.pth / .index)
- Full preservation of dialogue content, visual fidelity, and exact timing/lip-sync
- NVIDIA CUDA acceleration optimized for GTX 1050 Ti 4GB with CPU fallback
- High quality remuxing back into Video A (.mp4) via bundled FFmpeg
"""

import os
import sys
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QLineEdit, QFileDialog, QSpinBox,
    QDoubleSpinBox, QGroupBox, QFormLayout,
    QCheckBox, QComboBox, QSlider, QScrollArea,
    QMessageBox, QFrame, QButtonGroup, QRadioButton,
    QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QDragEnterEvent, QDropEvent

from core.voice_clone_processor import (
    VoiceCloneConfig,
    VoiceClonePipeline,
    MediaHelper,
    get_hardware_info
)
from ui.components import (
    PrimaryButton,
    GhostButton,
    DangerButton,
    StyledProgressBar,
    InfoBadge
)


# ─────────────────────────────────────────────────────────────────────────────
#  Background Worker Thread
# ─────────────────────────────────────────────────────────────────────────────

class VoiceCloneWorker(QThread):
    """Executes the Voice Conversion pipeline in a background thread."""
    progress = pyqtSignal(int, str)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, config: VoiceCloneConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self._pipeline = None
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True
        if self._pipeline:
            self._pipeline.stop()

    def run(self):
        try:
            self._pipeline = VoiceClonePipeline(
                config=self.config,
                progress_callback=lambda p, m: self.progress.emit(p, m),
                log_callback=lambda m: self.log_message.emit(m)
            )
            success, result = self._pipeline.run()
            self.finished.emit(success, result)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.log_message.emit(f"❌ Lỗi ngoại lệ trong Worker: {e}\n{tb}")
            self.finished.emit(False, str(e))


# ─────────────────────────────────────────────────────────────────────────────
#  Drag & Drop QLineEdit
# ─────────────────────────────────────────────────────────────────────────────

class DropLineEdit(QLineEdit):
    """QLineEdit with native Drag & Drop file support."""
    file_dropped = pyqtSignal(str)

    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                path = urls[0].toLocalFile()
                self.setText(path)
                self.file_dropped.emit(path)
                event.acceptProposedAction()
        else:
            super().dropEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  VoiceCloneTab Widget
# ─────────────────────────────────────────────────────────────────────────────

class VoiceCloneTab(QWidget):
    """Main Voice Clone & Voice Conversion Tab Widget."""
    log_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._is_dark = False
        self._setup_ui()
        self._detect_hardware()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        body = QWidget()
        root = QVBoxLayout(body)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)
        scroll.setWidget(body)

        # ── 1. Header Banner ────────────────────────────────────────────────
        self.header_frame = QFrame()
        self.header_frame.setObjectName("VCHeader")
        self.header_frame.setStyleSheet(
            "#VCHeader {"
            "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4F46E5,stop:1 #7C3AED);"
            "border-radius: 10px; padding: 4px; }"
        )
        hl = QVBoxLayout(self.header_frame)
        hl.setContentsMargins(20, 14, 20, 14)

        title_lbl = QLabel("🗣️ Voice Clone & Voice Conversion")
        title_lbl.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title_lbl.setStyleSheet("color: white; background: transparent; border: none;")
        hl.addWidget(title_lbl)

        desc_lbl = QLabel(
            "Chuyển đổi giọng nói Video A sang Giọng B | Giữ nguyên lời thoại, khẩu hình & timing | Hỗ trợ CUDA GTX 1050 Ti & CPU Fallback"
        )
        desc_lbl.setStyleSheet("color: rgba(255,255,255,0.85); font-size: 11px; background: transparent; border: none;")
        hl.addWidget(desc_lbl)
        root.addWidget(self.header_frame)

        # ── 2. Hardware Status Card ─────────────────────────────────────────
        hw_box = QGroupBox("Phần cứng xử lý & Tối ưu hóa")
        hw_layout = QHBoxLayout(hw_box)
        self.hw_status_lbl = QLabel("Đang kiểm tra phần cứng...")
        self.hw_status_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        hw_layout.addWidget(self.hw_status_lbl, 1)

        self.refresh_hw_btn = GhostButton("🔄 Quét lại")
        self.refresh_hw_btn.setFixedWidth(90)
        self.refresh_hw_btn.clicked.connect(self._detect_hardware)
        hw_layout.addWidget(self.refresh_hw_btn)
        root.addWidget(hw_box)

        # ── 3. Source Video A Card ──────────────────────────────────────────
        v_a_box = QGroupBox("Video Nguồn A (Chứa hình ảnh & lời thoại cần chuyển giọng)")
        v_a_layout = QVBoxLayout(v_a_box)

        v_a_row = QHBoxLayout()
        self.video_a_edit = DropLineEdit("Kéo thả hoặc chọn file video nguồn (.mp4)...")
        self.video_a_edit.textChanged.connect(self._on_video_a_changed)
        self.video_a_edit.file_dropped.connect(self._on_video_a_changed)
        v_a_row.addWidget(self.video_a_edit, 1)

        browse_a_btn = QPushButton("Chọn Video A")
        browse_a_btn.setFixedWidth(110)
        browse_a_btn.clicked.connect(self._browse_video_a)
        v_a_row.addWidget(browse_a_btn)
        v_a_layout.addLayout(v_a_row)

        self.video_a_info_lbl = QLabel("Chưa chọn video nguồn.")
        self.video_a_info_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        v_a_layout.addWidget(self.video_a_info_lbl)
        root.addWidget(v_a_box)

        # ── 4. Target Voice B Card ──────────────────────────────────────────
        v_b_box = QGroupBox("Mẫu Giọng Đích B (Người nói muốn nhái / chuyển sang)")
        v_b_layout = QVBoxLayout(v_b_box)

        v_b_row = QHBoxLayout()
        self.voice_b_edit = DropLineEdit("Kéo thả hoặc chọn file mẫu giọng B (.mp4, .mp3, .wav, .m4a)...")
        self.voice_b_edit.textChanged.connect(self._on_voice_b_changed)
        self.voice_b_edit.file_dropped.connect(self._on_voice_b_changed)
        v_b_row.addWidget(self.voice_b_edit, 1)

        browse_b_btn = QPushButton("Chọn Voice B")
        browse_b_btn.setFixedWidth(110)
        browse_b_btn.clicked.connect(self._browse_voice_b)
        v_b_row.addWidget(browse_b_btn)

        self.play_b_btn = GhostButton("🔊 Nghe thử")
        self.play_b_btn.setFixedWidth(90)
        self.play_b_btn.clicked.connect(self._preview_voice_b)
        self.play_b_btn.setEnabled(False)
        v_b_row.addWidget(self.play_b_btn)
        v_b_layout.addLayout(v_b_row)

        b_hint_row = QHBoxLayout()
        self.voice_b_info_lbl = QLabel("Chưa chọn file mẫu giọng B.")
        self.voice_b_info_lbl.setStyleSheet("color: #64748B; font-size: 11px;")
        b_hint_row.addWidget(self.voice_b_info_lbl, 1)

        tip_lbl = QLabel("💡 Tự động trích xuất âm thanh chuẩn nếu chọn file video hoặc file nhạc")
        tip_lbl.setStyleSheet("color: #818CF8; font-size: 11px; font-style: italic;")
        b_hint_row.addWidget(tip_lbl)
        v_b_layout.addLayout(b_hint_row)
        root.addWidget(v_b_box)

        # ── 5. Conversion Settings Card ─────────────────────────────────────
        cfg_box = QGroupBox("Cài đặt Chuyển đổi Giọng nói & Tối ưu hóa")
        cfg_layout = QVBoxLayout(cfg_box)

        # Engine Mode Selection
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Chế độ chuyển giọng:"))
        self.mode_group = QButtonGroup(self)
        self.mode_zero_shot_radio = QRadioButton("🎙️ Zero-Shot Voice Clone (Trực tiếp từ mẫu Voice B - Không cần train)")
        self.mode_zero_shot_radio.setChecked(True)
        self.mode_rvc_radio = QRadioButton("🤖 RVC Model (.pth / .index đã huấn luyện)")
        self.mode_group.addButton(self.mode_zero_shot_radio, 0)
        self.mode_group.addButton(self.mode_rvc_radio, 1)
        self.mode_zero_shot_radio.toggled.connect(self._on_mode_changed)

        mode_row.addWidget(self.mode_zero_shot_radio)
        mode_row.addSpacing(15)
        mode_row.addWidget(self.mode_rvc_radio)
        mode_row.addStretch()
        cfg_layout.addLayout(mode_row)

        # RVC Model configuration container (hidden by default)
        self.rvc_container = QWidget()
        rvc_form = QFormLayout(self.rvc_container)
        rvc_form.setContentsMargins(10, 8, 10, 8)

        # RVC .pth file
        pth_row = QHBoxLayout()
        self.rvc_pth_edit = DropLineEdit("Đường dẫn file RVC Model (.pth)...")
        pth_row.addWidget(self.rvc_pth_edit, 1)
        browse_pth_btn = QPushButton("Chọn .pth")
        browse_pth_btn.setFixedWidth(85)
        browse_pth_btn.clicked.connect(self._browse_rvc_pth)
        pth_row.addWidget(browse_pth_btn)
        rvc_form.addRow("RVC Model (.pth):", pth_row)

        # RVC .index file
        idx_row = QHBoxLayout()
        self.rvc_idx_edit = DropLineEdit("Đường dẫn file Index (.index) - Tùy chọn...")
        idx_row.addWidget(self.rvc_idx_edit, 1)
        browse_idx_btn = QPushButton("Chọn .index")
        browse_idx_btn.setFixedWidth(85)
        browse_idx_btn.clicked.connect(self._browse_rvc_idx)
        idx_row.addWidget(browse_idx_btn)
        rvc_form.addRow("RVC Index (.index):", idx_row)

        self.rvc_container.setVisible(False)
        cfg_layout.addWidget(self.rvc_container)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #E2E8F0; max-height: 1px;")
        cfg_layout.addWidget(sep)

        # Pitch Shift adjustment
        pitch_row = QHBoxLayout()
        pitch_row.addWidget(QLabel("Điều chỉnh cao độ (Pitch Shift):"))

        self.pitch_slider = QSlider(Qt.Orientation.Horizontal)
        self.pitch_slider.setRange(-24, 24)
        self.pitch_slider.setValue(0)
        self.pitch_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.pitch_slider.setTickInterval(4)
        self.pitch_slider.setFixedWidth(200)

        self.pitch_spin = QSpinBox()
        self.pitch_spin.setRange(-24, 24)
        self.pitch_spin.setValue(0)
        self.pitch_spin.setSuffix(" semitones")
        self.pitch_spin.setFixedWidth(110)

        self.pitch_slider.valueChanged.connect(self.pitch_spin.setValue)
        self.pitch_spin.valueChanged.connect(self.pitch_slider.setValue)

        pitch_row.addWidget(self.pitch_slider)
        pitch_row.addWidget(self.pitch_spin)
        pitch_row.addSpacing(10)

        # Quick preset buttons
        btn_keep_pitch = GhostButton("Giữ nguyên (0)")
        btn_keep_pitch.clicked.connect(lambda: self.pitch_spin.setValue(0))
        pitch_row.addWidget(btn_keep_pitch)

        btn_m2f = GhostButton("Nam ➔ Nữ (+12)")
        btn_m2f.clicked.connect(lambda: self.pitch_spin.setValue(12))
        pitch_row.addWidget(btn_m2f)

        btn_f2m = GhostButton("Nữ ➔ Nam (-12)")
        btn_f2m.clicked.connect(lambda: self.pitch_spin.setValue(-12))
        pitch_row.addWidget(btn_f2m)
        pitch_row.addStretch()
        cfg_layout.addLayout(pitch_row)

        # Algorithm & Hardware Row
        row_settings = QHBoxLayout()

        # F0 Extraction Method
        row_settings.addWidget(QLabel("Thuật toán F0:"))
        self.f0_combo = QComboBox()
        self.f0_combo.addItem("rmvpe (Khuyên dùng - Độ chính xác cao nhất)", "rmvpe")
        self.f0_combo.addItem("pm (Nhanh nhất - Phù hợp CPU)", "pm")
        self.f0_combo.addItem("harvest (Mượt mà)", "harvest")
        self.f0_combo.addItem("crepe (Chi tiết cao)", "crepe")
        self.f0_combo.setFixedWidth(260)
        row_settings.addWidget(self.f0_combo)

        row_settings.addSpacing(20)

        # Hardware Selector
        row_settings.addWidget(QLabel("Thiết bị xử lý:"))
        self.device_combo = QComboBox()
        self.device_combo.addItem("⚡ Tự động (Ưu tiên CUDA GPU)", "auto")
        self.device_combo.addItem("🟢 Ép buộc NVIDIA CUDA (GTX 1050 Ti)", "cuda")
        self.device_combo.addItem("💻 Ép buộc CPU Fallback", "cpu")
        self.device_combo.setFixedWidth(220)
        row_settings.addWidget(self.device_combo)

        row_settings.addStretch()
        cfg_layout.addLayout(row_settings)

        # Low VRAM Optimization for GTX 1050 Ti 4GB
        vram_row = QHBoxLayout()
        self.chunk_checkbox = QCheckBox("Tối ưu hóa GTX 1050 Ti 4GB (Chia nhỏ audio thành phân đoạn 15s tránh tràn VRAM)")
        self.chunk_checkbox.setChecked(True)
        vram_row.addWidget(self.chunk_checkbox)
        vram_row.addStretch()
        cfg_layout.addLayout(vram_row)

        # Background Audio Handling
        bgm_box = QGroupBox("Xử lý âm thanh nền & Nhạc nền (BGM) của Video A")
        bgm_box_layout = QVBoxLayout(bgm_box)

        bgm_mode_row = QHBoxLayout()
        self.bgm_replace_radio = QRadioButton("Thay thế toàn bộ âm thanh bằng giọng mới")
        self.bgm_replace_radio.setChecked(True)
        self.bgm_keep_radio = QRadioButton("Giữ lại nhạc nền & âm thanh môi trường (Trộn BGM + Giọng mới)")
        bgm_mode_row.addWidget(self.bgm_replace_radio)
        bgm_mode_row.addSpacing(20)
        bgm_mode_row.addWidget(self.bgm_keep_radio)
        bgm_mode_row.addStretch()
        bgm_box_layout.addLayout(bgm_mode_row)

        root.addWidget(cfg_box)
        root.addWidget(bgm_box)

        # ── 6. Output Destination Card ──────────────────────────────────────
        out_box = QGroupBox("File Video Đầu Ra (.mp4)")
        out_layout = QVBoxLayout(out_box)

        out_row = QHBoxLayout()
        self.output_edit = DropLineEdit("Đường dẫn file video đầu ra (.mp4)...")
        out_row.addWidget(self.output_edit, 1)

        browse_out_btn = QPushButton("Chọn nơi lưu")
        browse_out_btn.setFixedWidth(110)
        browse_out_btn.clicked.connect(self._browse_output)
        out_row.addWidget(browse_out_btn)

        self.open_folder_btn = GhostButton("📂 Mở thư mục")
        self.open_folder_btn.setFixedWidth(100)
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        out_row.addWidget(self.open_folder_btn)
        out_layout.addLayout(out_row)
        root.addWidget(out_box)

        # ── 7. Control & Progress Bar ───────────────────────────────────────
        ctl_box = QGroupBox("Điều khiển & Tiến trình")
        ctl_layout = QVBoxLayout(ctl_box)

        btn_row = QHBoxLayout()
        self.start_btn = PrimaryButton("🚀 Bắt đầu Chuyển giọng (Start Conversion)")
        self.start_btn.setFixedHeight(38)
        self.start_btn.clicked.connect(self._start_conversion)
        btn_row.addWidget(self.start_btn, 2)

        self.stop_btn = DangerButton("⏹ Dừng lại (Stop)")
        self.stop_btn.setFixedHeight(38)
        self.stop_btn.clicked.connect(self._stop_conversion)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.stop_btn, 1)
        ctl_layout.addLayout(btn_row)

        self.progress_bar = StyledProgressBar()
        self.progress_bar.setValue(0)
        ctl_layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("Sẵn sàng.")
        self.status_lbl.setStyleSheet("color: #64748B; font-weight: 600; font-size: 12px;")
        ctl_layout.addWidget(self.status_lbl)
        root.addWidget(ctl_box)

        root.addStretch()

        # Wrap in main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    # ── Hardware Detection ──────────────────────────────────────────────────

    def _detect_hardware(self):
        hw = get_hardware_info()
        if hw["has_cuda"]:
            dev_name = hw["device_name"]
            vram = hw["total_vram_mb"]
            free = hw["free_vram_mb"]
            text = f"🟢 Phát hiện {dev_name} ({vram}MB VRAM, Khả dụng: {free}MB) — Đã kích hoạt tăng tốc CUDA & tối ưu VRAM."
            self.hw_status_lbl.setStyleSheet("color: #10B981; font-weight: 600;")
        else:
            text = "💻 Chế độ CPU Fallback — Đa luồng xử lý ổn định (Không phát hiện NVIDIA CUDA)."
            self.hw_status_lbl.setStyleSheet("color: #6366F1; font-weight: 600;")
        self.hw_status_lbl.setText(text)

    # ── File Browsers & Handlers ────────────────────────────────────────────

    def _browse_video_a(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn Video Nguồn A",
            "",
            "Video Files (*.mp4 *.mkv *.mov *.avi *.webm);;Tất cả tệp (*.*)"
        )
        if path:
            self.video_a_edit.setText(path)
            self._on_video_a_changed(path)

    def _browse_voice_b(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn Mẫu Giọng Đích B",
            "",
            "Media Files (*.mp4 *.mp3 *.wav *.m4a *.aac *.flac *.mkv);;Audio Files (*.mp3 *.wav *.m4a *.aac);;Video Files (*.mp4 *.mkv);;Tất cả tệp (*.*)"
        )
        if path:
            self.voice_b_edit.setText(path)
            self._on_voice_b_changed(path)

    def _browse_rvc_pth(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn RVC Model Weights (.pth)",
            "",
            "PyTorch Weights (*.pth);;Tất cả tệp (*.*)"
        )
        if path:
            self.rvc_pth_edit.setText(path)

    def _browse_rvc_idx(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn RVC Feature Index (.index)",
            "",
            "Index Files (*.index);;Tất cả tệp (*.*)"
        )
        if path:
            self.rvc_idx_edit.setText(path)

    def _browse_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Chọn Nơi Lưu Video Đầu Ra",
            self.output_edit.text() or "output_voice_clone.mp4",
            "MP4 Video (*.mp4);;Tất cả tệp (*.*)"
        )
        if path:
            if not path.lower().endswith(".mp4"):
                path += ".mp4"
            self.output_edit.setText(path)

    def _open_output_folder(self):
        out_path = self.output_edit.text().strip()
        folder = os.path.dirname(out_path) if out_path else os.getcwd()
        if os.path.exists(folder):
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", folder])
        else:
            QMessageBox.warning(self, "Thông báo", f"Thư mục không tồn tại: {folder}")

    def _on_video_a_changed(self, path: str):
        if not path or not os.path.exists(path):
            self.video_a_info_lbl.setText("Chưa chọn video nguồn hợp lệ.")
            return

        probe = MediaHelper.probe_media(path)
        if probe["has_video"]:
            dur = probe["duration"]
            audio_info = f"{probe['audio_sample_rate']}Hz" if probe["has_audio"] else "Không có audio"
            self.video_a_info_lbl.setText(
                f"✅ Video hợp lệ: Thời lượng {dur:.1f}s | Độ phân giải {probe['width']}x{probe['height']} | "
                f"FPS: {probe['fps']:.1f} | Audio: {audio_info}"
            )
            # Auto populate output path
            if not self.output_edit.text() or "_voice_clone.mp4" in self.output_edit.text():
                p = Path(path)
                out = str(p.parent / f"{p.stem}_voice_clone.mp4")
                self.output_edit.setText(out)
        else:
            self.video_a_info_lbl.setText("⚠️ File không chứa luồng video hợp lệ.")

    def _on_voice_b_changed(self, path: str):
        if not path or not os.path.exists(path):
            self.voice_b_info_lbl.setText("Chưa chọn file mẫu giọng B hợp lệ.")
            self.play_b_btn.setEnabled(False)
            return

        probe = MediaHelper.probe_media(path)
        dur = probe["duration"]
        fmt = Path(path).suffix.upper()
        if dur > 0:
            self.voice_b_info_lbl.setText(
                f"✅ Mẫu Voice B: Định dạng {fmt} | Thời lượng {dur:.1f}s | "
                f"Tần số: {probe['audio_sample_rate']}Hz ({probe['audio_channels']} kênh)"
            )
            self.play_b_btn.setEnabled(True)
        else:
            self.voice_b_info_lbl.setText(f"File mẫu Voice B: {fmt}")
            self.play_b_btn.setEnabled(True)

    def _preview_voice_b(self):
        path = self.voice_b_edit.text().strip()
        if path and os.path.exists(path):
            try:
                if sys.platform == "win32":
                    os.startfile(path)
                else:
                    subprocess.Popen(["xdg-open", path])
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"Không thể phát file: {e}")

    def _on_mode_changed(self):
        is_rvc = self.mode_rvc_radio.isChecked()
        self.rvc_container.setVisible(is_rvc)

    # ── Pipeline Execution ──────────────────────────────────────────────────

    def _start_conversion(self):
        v_a = self.video_a_edit.text().strip()
        v_b = self.voice_b_edit.text().strip()
        out = self.output_edit.text().strip()

        if not v_a or not os.path.exists(v_a):
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng chọn file Video Nguồn A (.mp4) hợp lệ!")
            return

        if not v_b or not os.path.exists(v_b):
            QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng chọn file Mẫu Giọng Đích B hợp lệ!")
            return

        if not out:
            p = Path(v_a)
            out = str(p.parent / f"{p.stem}_voice_clone.mp4")
            self.output_edit.setText(out)

        # Build Config
        config = VoiceCloneConfig(
            video_a_path=v_a,
            voice_b_path=v_b,
            output_path=out,
            mode="rvc" if self.mode_rvc_radio.isChecked() else "zero_shot",
            rvc_model_path=self.rvc_pth_edit.text().strip(),
            rvc_index_path=self.rvc_idx_edit.text().strip(),
            pitch_shift=self.pitch_spin.value(),
            f0_method=self.f0_combo.currentData(),
            device_mode=self.device_combo.currentData(),
            enable_chunking=self.chunk_checkbox.isChecked(),
            chunk_size_sec=15,
            keep_bgm=self.bgm_keep_radio.isChecked()
        )

        # UI state
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("Đang khởi tạo quá trình chuyển đổi...")

        self.log_message.emit("=" * 60)
        self.log_message.emit("🎙️ BẮT ĐẦU QUÁ TRÌNH VOICE CLONE / VOICE CONVERSION")
        self.log_message.emit(f"   Video A: {v_a}")
        self.log_message.emit(f"   Voice B: {v_b}")
        self.log_message.emit(f"   Đầu ra:  {out}")
        self.log_message.emit(f"   Chế độ:  {config.mode.upper()} | Pitch: {config.pitch_shift:+d}")

        # Worker launch
        self._worker = VoiceCloneWorker(config, self)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.log_message.connect(self._on_worker_log)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _stop_conversion(self):
        if self._worker and self._worker.isRunning():
            self.status_lbl.setText("Đang dừng quá trình...")
            self._worker.stop()
            self.stop_btn.setEnabled(False)

    def _on_worker_progress(self, pct: int, msg: str):
        self.progress_bar.setValue(pct)
        self.status_lbl.setText(f"[{pct}%] {msg}")

    def _on_worker_log(self, msg: str):
        self.log_message.emit(msg)

    def _on_worker_finished(self, success: bool, result: str):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if success:
            self.progress_bar.setValue(100)
            self.status_lbl.setText("✅ Hoàn tất chuyển đổi giọng nói thành công!")
            QMessageBox.information(
                self,
                "Thành công",
                f"Đã xuất video mới thành công với giọng nói mới:\n\n{result}"
            )
        else:
            self.status_lbl.setText(f"❌ Thất bại: {result}")
            QMessageBox.critical(
                self,
                "Lỗi xử lý",
                f"Quá trình chuyển đổi giọng nói gặp lỗi:\n\n{result}"
            )

    # ── Theme Support ───────────────────────────────────────────────────────

    def apply_theme(self, dark: bool):
        self._is_dark = dark
        if dark:
            self.header_frame.setStyleSheet(
                "#VCHeader {"
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #3730A3,stop:1 #5B21B6);"
                "border-radius: 10px; padding: 4px; }"
            )
        else:
            self.header_frame.setStyleSheet(
                "#VCHeader {"
                "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4F46E5,stop:1 #7C3AED);"
                "border-radius: 10px; padding: 4px; }"
            )
