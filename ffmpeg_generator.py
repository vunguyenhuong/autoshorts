import sys
import os
import subprocess
import tempfile
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QFileDialog, QLineEdit, QSlider, QDoubleSpinBox, 
                             QPushButton, QTextEdit, QFrame, QGroupBox, QCheckBox, 
                             QGraphicsView, QGraphicsScene, QGraphicsRectItem, 
                             QGraphicsPixmapItem, QGraphicsItem)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QRectF, QPointF, QObject
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QIcon, QFont, QColor, QPixmap, QPen, QBrush, QPainter

# --- Viewport Components ---

class HandleItem(QGraphicsRectItem):
    """Resizing handles for squash/stretch"""
    def __init__(self, host_item, pos_type):
        super().__init__(-6, -6, 12, 12, host_item)
        self.host = host_item
        self.pos_type = pos_type # 'left', 'right', 'top', 'bottom'
        self.setBrush(QBrush(QColor("#38bdf8")))
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(Qt.CursorShape.SizeHorCursor if pos_type in ['left', 'right'] else Qt.CursorShape.SizeVerCursor)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and not self.host.is_internal_update:
            new_pos = value
            # Constrain handle movement to one axis
            if self.pos_type in ['left', 'right']:
                new_pos.setY(0)
                self.host.on_handle_move(self.pos_type, new_pos.x())
            else:
                new_pos.setX(0)
                self.host.on_handle_move(self.pos_type, new_pos.y())
            return new_pos
        return super().itemChange(change, value)

class VideoViewportItem(QObject, QGraphicsPixmapItem):
    """The interactive video box on the canvas"""
    changed = pyqtSignal()

    def __init__(self, width, height):
        super().__init__()
        QGraphicsPixmapItem.__init__(self)
        self.orig_w = width
        self.orig_h = height
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.is_internal_update = False
        
        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsMovable | 
                      QGraphicsItem.GraphicsItemFlag.ItemIsSelectable |
                      QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        
        # Overlay a border
        self.border = QGraphicsRectItem(self)
        self.border.setPen(QPen(QColor("#38bdf8"), 2))
        
        # Handles
        self.handles = {
            'left': HandleItem(self, 'left'),
            'right': HandleItem(self, 'right'),
            'top': HandleItem(self, 'top'),
            'bottom': HandleItem(self, 'bottom')
        }
        self.update_geometry()

    def update_geometry(self):
        curr_w = self.orig_w * self.scale_x
        curr_h = self.orig_h * self.scale_y
        
        rect = QRectF(-curr_w/2, -curr_h/2, curr_w, curr_h)
        self.border.setRect(rect)
        
        self.is_internal_update = True
        self.handles['left'].setPos(-curr_w/2, 0)
        self.handles['right'].setPos(curr_w/2, 0)
        self.handles['top'].setPos(0, -curr_h/2)
        self.handles['bottom'].setPos(0, curr_h/2)
        self.is_internal_update = False

    def on_handle_move(self, pos_type, offset):
        if pos_type == 'right':
            new_w = offset * 2
            self.scale_x = max(0.1, new_w / self.orig_w)
        elif pos_type == 'left':
            new_w = -offset * 2
            self.scale_x = max(0.1, new_w / self.orig_w)
        elif pos_type == 'top':
            new_h = -offset * 2
            self.scale_y = max(0.1, new_h / self.orig_h)
        elif pos_type == 'bottom':
            new_h = offset * 2
            self.scale_y = max(0.1, new_h / self.orig_h)
            
        self.update_geometry()
        self.changed.emit()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            self.changed.emit()
        return super().itemChange(change, value)

    def set_scales(self, sx, sy):
        self.scale_x = sx
        self.scale_y = sy
        self.update_geometry()

# --- Main App ---

class FFmpegGenerator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎬 FFmpeg Viewport Debugger (Squash & Stretch)")
        self.setMinimumSize(1100, 850)
        
        # Detect local ffmpeg
        self.ffmpeg_bin = self._get_ffmpeg_bin()
        self.ffprobe_bin = self.ffmpeg_bin.replace("ffmpeg.exe", "ffprobe.exe") if "ffmpeg.exe" in self.ffmpeg_bin else "ffprobe"
        
        # State
        self.current_video = ""
        self.video_orig_w = 1920
        self.video_orig_h = 1080
        self.canvas_w = 1080
        self.canvas_h = 1920
        self.logic_block = False # Prevent feedback loops
        
        self.init_ui()
        # self.on_file_selected("ffmpeg/input.mp4") # Load default for testing if exists

    def _get_ffmpeg_bin(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        local_ffmpeg = os.path.join(base_dir, "ffmpeg", "ffmpeg.exe")
        return local_ffmpeg if os.path.exists(local_ffmpeg) else "ffmpeg"

    def init_ui(self):
        # Apply premium dark theme
        self.setStyleSheet("""
            QMainWindow { background-color: #0f172a; }
            QLabel { color: #f8fafc; font-size: 11px; }
            QGroupBox { color: #38bdf8; font-weight: bold; border: 1px solid #334155; margin-top: 10px; padding: 10px; border-radius: 8px; }
            QDoubleSpinBox { background-color: #1e293b; color: white; border: 1px solid #334155; padding: 3px; border-radius: 4px; }
            QTextEdit { background-color: #020617; border: 1px solid #38bdf8; border-radius: 6px; }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setSpacing(20)

        # Left Column: Viewport
        left_panel = QVBoxLayout()
        
        # Viewport Header
        vp_header = QLabel("🖥️ VIEWPORT (CANVAS 1080x1920)")
        vp_header.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8;")
        left_panel.addWidget(vp_header)

        # Graphics Scene
        self.scene = QGraphicsScene(0, 0, 337, 600) # (1080x1920 scaled by ~0.31)
        self.scene.setBackgroundBrush(QBrush(QColor("#1e293b")))
        
        # Reference Rect (The Short video limit)
        self.ref_frame = QGraphicsRectItem(0, 0, 337, 600)
        self.ref_frame.setPen(QPen(QColor("#f43f5e"), 2, Qt.PenStyle.DashLine))
        self.scene.addItem(self.ref_frame)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setFixedSize(360, 650)
        self.view.setStyleSheet("background-color: #020617; border: 2px solid #334155; border-radius: 12px;")
        left_panel.addWidget(self.view)
        
        # Instructional Label
        help_label = QLabel("💡 Kéo Video để chỉnh tâm | Kéo cạnh để Bóp dẹt (Rescale)")
        help_label.setStyleSheet("color: #94a3b8; font-style: italic;")
        left_panel.addWidget(help_label)
        
        layout.addLayout(left_panel, 0)

        # Right Column: Controls & Command
        right_panel = QVBoxLayout()
        
        # File Area
        file_group = QGroupBox("📥 SOURCE")
        file_layout = QVBoxLayout()
        self.file_label = QLabel("Chưa chọn file")
        self.file_label.setWordWrap(True)
        self.file_label.setStyleSheet("color: #94a3b8; font-family: 'Consolas';")
        file_layout.addWidget(self.file_label)
        browse_btn = QPushButton("📂 Chọn Video...")
        browse_btn.clicked.connect(self.browse_video)
        file_layout.addWidget(browse_btn)
        file_group.setLayout(file_layout)
        right_panel.addWidget(file_group)

        # Params Area
        params_group = QGroupBox("⚙️ PARAMETERS")
        p_layout = QVBoxLayout()
        
        # Speed
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Tốc độ:"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 3.0)
        self.speed_spin.setValue(1.0)
        self.speed_spin.valueChanged.connect(self.on_param_ui_change)
        speed_row.addWidget(self.speed_spin)
        p_layout.addLayout(speed_row)

        # Scale X (Width)
        sx_row = QHBoxLayout()
        sx_row.addWidget(QLabel("Scale Ngang (W):"))
        self.sx_spin = QDoubleSpinBox()
        self.sx_spin.setRange(0.1, 5.0)
        self.sx_spin.setValue(1.0)
        self.sx_spin.setSingleStep(0.05)
        self.sx_spin.valueChanged.connect(self.on_param_ui_change)
        sx_row.addWidget(self.sx_spin)
        p_layout.addLayout(sx_row)

        # Scale Y (Height)
        sy_row = QHBoxLayout()
        sy_row.addWidget(QLabel("Scale Dọc (H):"))
        self.sy_spin = QDoubleSpinBox()
        self.sy_spin.setRange(0.1, 5.0)
        self.sy_spin.setValue(1.0)
        self.sy_spin.setSingleStep(0.05)
        self.sy_spin.valueChanged.connect(self.on_param_ui_change)
        sy_row.addWidget(self.sy_spin)
        p_layout.addLayout(sy_row)

        # Offsets (Visible for debug)
        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("Offset X:"))
        self.offx_spin = QDoubleSpinBox()
        self.offx_spin.setRange(-2000, 2000)
        self.offx_spin.valueChanged.connect(self.on_param_ui_change)
        offset_row.addWidget(self.offx_spin)
        offset_row.addWidget(QLabel("Y:"))
        self.offy_spin = QDoubleSpinBox()
        self.offy_spin.setRange(-2000, 2000)
        self.offy_spin.valueChanged.connect(self.on_param_ui_change)
        offset_row.addWidget(self.offy_spin)
        p_layout.addLayout(offset_row)

        params_group.setLayout(p_layout)
        right_panel.addWidget(params_group)

        # Command Output
        right_panel.addWidget(QLabel("📜 GENERATED FFMPEG COMMAND:"))
        self.cmd_view = QTextEdit()
        self.cmd_view.setReadOnly(True)
        self.cmd_view.setStyleSheet("color: #38bdf8; font-family: 'Consolas'; font-size: 12px; padding: 8px;")
        right_panel.addWidget(self.cmd_view)

        # Buttons
        copy_btn = QPushButton("📋 Copy Command")
        copy_btn.setFixedHeight(40)
        copy_btn.clicked.connect(self.copy_cmd)
        right_panel.addWidget(copy_btn)

        run_btn = QPushButton("🔥 RUN PREVIEW")
        run_btn.setFixedHeight(50)
        run_btn.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; font-size: 14px;")
        run_btn.clicked.connect(self.run_preview)
        right_panel.addWidget(run_btn)
        
        layout.addLayout(right_panel, 1)

        # Logic: Create Video Box on Scene
        self.v_item = VideoViewportItem(200, 150) # Placeholder
        self.v_item.setPos(168, 300) # Center of 337x600
        self.v_item.changed.connect(self.on_canvas_change)
        self.scene.addItem(self.v_item)

    # --- Video Processing Logic ---

    def browse_video(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn Video Source", "", "Video Files (*.mp4 *.mov *.mkv)")
        if file_path:
            self.on_file_selected(file_path)

    def on_file_selected(self, file_path):
        if not os.path.exists(file_path): return
        self.current_video = file_path
        self.file_label.setText(f"File: {os.path.basename(file_path)}")
        
        w, h = self.get_video_dims(file_path)
        self.video_orig_w = w
        self.video_orig_h = h
        
        thumb_path = self.get_thumbnail(file_path)
        if thumb_path:
            pix = QPixmap(thumb_path)
            v_scale = 337 / w if w > h else 300 / h
            display_w, display_h = int(w * v_scale), int(h * v_scale)
            
            self.scene.removeItem(self.v_item)
            self.v_item = VideoViewportItem(display_w, display_h)
            self.v_item.setPixmap(pix.scaled(display_w, display_h, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.v_item.setPos(168.5, 300) 
            self.v_item.changed.connect(self.on_canvas_change)
            self.scene.addItem(self.v_item)
            self.on_canvas_change()

    def get_video_dims(self, path):
        try:
            cmd = [self.ffprobe_bin, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", path]
            res = subprocess.check_output(cmd, text=True).strip().split('x')
            return int(res[0]), int(res[1])
        except: return 1280, 720

    def get_thumbnail(self, path):
        temp_thumb = os.path.join(tempfile.gettempdir(), f"autoshort_thumb_{os.path.getmtime(path)}.jpg")
        if not os.path.exists(temp_thumb):
            cmd = [self.ffmpeg_bin, "-y", "-i", path, "-ss", "00:00:01", "-vframes", "1", "-f", "image2", temp_thumb]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return temp_thumb if os.path.exists(temp_thumb) else None

    # --- Sync Logic ---

    def on_canvas_change(self):
        if self.logic_block: return
        self.logic_block = True
        self.sx_spin.setValue(self.v_item.scale_x)
        self.sy_spin.setValue(self.v_item.scale_y)
        viz_center_x, viz_center_y = 168.5, 300
        viz_off_x = self.v_item.pos().x() - viz_center_x
        viz_off_y = self.v_item.pos().y() - viz_center_y
        factor = 1080 / 337
        self.offx_spin.setValue(int(viz_off_x * factor))
        self.offy_spin.setValue(int(viz_off_y * factor))
        self.logic_block = False
        self.update_command()

    def on_param_ui_change(self):
        if self.logic_block: return
        self.logic_block = True
        self.v_item.set_scales(self.sx_spin.value(), self.sy_spin.value())
        factor = 337 / 1080
        viz_center_x, viz_center_y = 168.5, 300
        self.v_item.setPos(viz_center_x + (self.offx_spin.value() * factor), viz_center_y + (self.offy_spin.value() * factor))
        self.logic_block = False
        self.update_command()

    def update_command(self):
        input_f = self.current_video or "input.mp4"
        speed = self.speed_spin.value()
        sx, sy = self.sx_spin.value(), self.sy_spin.value()
        ox, oy = self.offx_spin.value(), self.offy_spin.value()
        cmd = (
            f'"{self.ffmpeg_bin}" -y ^\n'
            f'  -hwaccel cuda -hwaccel_output_format cuda ^\n'
            f'  -extra_hw_frames 8 ^\n'
            f'  -i "{input_f}" ^\n'
            f'  -filter_complex ^\n'
            f'  "[0:v]hwdownload,format=yuv420p,setpts=PTS/{speed},scale=iw*{sx:.3f}:ih*{sy:.3f}, '
            f'pad=w=\'max(iw,1080)\':h=\'max(ih,1920)\':x=\'(ow-iw)/2\':y=\'(oh-ih)/2\', '
            f'crop=1080:1920:(iw-1080)/2+{-ox:.0f}:(ih-1920)/2+{-oy:.0f}, '
            f'format=yuv420p,hwupload_cuda,format=nv12[v]; '
            f'[0:a]atempo={speed}[a]" ^\n'
            f'  -map "[v]" -map "[a]" ^\n'
            f'  -c:v h264_nvenc -preset p5 -cq 18 -b:v 0 ^\n'
            f'  -c:a aac -b:a 192k -r 30 -shortest ^\n'
            f'  "output_preview.mp4"'
        )
        self.cmd_view.setText(cmd)

    def copy_cmd(self):
        QApplication.clipboard().setText(self.cmd_view.toPlainText().replace(" ^\n", " "))

    def run_preview(self):
        cmd = self.cmd_view.toPlainText().replace(" ^\n", " ")
        subprocess.Popen(cmd, shell=True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FFmpegGenerator()
    window.show()
    sys.exit(app.exec())
