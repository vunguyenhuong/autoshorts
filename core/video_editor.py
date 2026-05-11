"""
AutoCut Video Editor - Core Processing Module
Contains video processing logic, GPU detection, and worker threads
"""

import sys
import os
import time
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import textwrap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTimeEdit
from PyQt6.QtCore import QThread, pyqtSignal, QTime, Qt
from PyQt6.QtGui import QFont as QFont_GUI
from datetime import datetime


# Paths for FFmpeg and FFprobe
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    EXE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent  # Go up to AutoShorts directory
    EXE_DIR = BASE_DIR

FFMPEG_EXE = str(EXE_DIR / "ffmpeg" / "ffmpeg.exe")
FFPROBE_EXE = str(EXE_DIR / "ffmpeg" / "ffprobe.exe")


def run_ffmpeg_silent(cmd):
    """Run FFmpeg without showing console popup"""
    try:
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                encoding='utf-8',
                errors='replace'
            )
        return result
    except Exception as e:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        return result


def detect_gpu_encoder():
    """
    Auto-detect available GPU encoder on the system
    Supports: NVIDIA (NVENC), AMD (AMF), Intel (QSV), Apple (VideoToolbox)
    Returns: tuple (encoder_name, preset_args, quality_args) or None if no GPU
    """
    try:
        cmd = [FFMPEG_EXE, '-hide_banner', '-encoders']
        result = run_ffmpeg_silent(cmd)
        encoders_output = result.stdout.lower()
        
        # Check in priority order: NVIDIA > AMD > Intel > Apple
        if 'h264_nvenc' in encoders_output:
            return ('h264_nvenc', ['-preset', 'p4'], ['-cq', '23'])
        
        if 'h264_amf' in encoders_output:
            return ('h264_amf', ['-quality', 'balanced'], ['-rc', 'vbr_hq', '-qp_i', '23', '-qp_p', '23'])
        
        if 'h264_qsv' in encoders_output:
            return ('h264_qsv', ['-preset', 'medium'], ['-global_quality', '23'])
        
        if 'h264_videotoolbox' in encoders_output:
            return ('h264_videotoolbox', ['-profile:v', 'high'], ['-b:v', '5M'])
        
        return None
        
    except Exception as e:
        print(f"⚠️ Error detecting GPU: {e}")
        return None


class SkipRangeWidget(QWidget):
    """Widget for a single skip range"""
    removed = pyqtSignal(QWidget)
    
    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.setup_ui()
    
    def setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)
        
        self.setStyleSheet("""
            QWidget { background-color: #f8fafc; border-radius: 4px; border: 1px solid #e2e8f0; }
            QLabel { border: none; font-size: 11px; color: #475569; }
            QTimeEdit { border: 1px solid #cbd5e1; border-radius: 4px; padding: 2px; font-size: 11px; background-color: white; }
        """)
        
        # Label showing index
        label = QLabel(f"Đoạn {self.index + 1}:")
        label.setStyleSheet("font-weight: 600; color: #334155; min-width: 45px;")
        layout.addWidget(label)
        
        # From
        layout.addWidget(QLabel("Từ:"))
        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("HH:mm:ss")
        self.start_time.setTime(QTime(0, 0, 0))
        self.start_time.setFixedWidth(70)
        layout.addWidget(self.start_time)
        
        # To
        layout.addWidget(QLabel("đến"))
        self.end_time = QTimeEdit()
        self.end_time.setDisplayFormat("HH:mm:ss")
        self.end_time.setTime(QTime(0, 0, 30))
        self.end_time.setFixedWidth(70)
        layout.addWidget(self.end_time)
        
        layout.addStretch()
        
        # Remove button
        remove_btn = QPushButton("✕")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #ef4444;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
                min-width: 22px; max-width: 22px;
                min-height: 22px; max-height: 22px;
            }
            QPushButton:hover { background-color: #fee2e2; }
        """)
        remove_btn.clicked.connect(self.remove_self)
        layout.addWidget(remove_btn)
    
    def remove_self(self):
        self.removed.emit(self)
    
    def get_times(self):
        """Return start and end time in seconds"""
        return (self.time_to_seconds(self.start_time.time()),
                self.time_to_seconds(self.end_time.time()))
    
    def time_to_seconds(self, qtime):
        """Convert QTime to seconds"""
        return qtime.hour() * 3600 + qtime.minute() * 60 + qtime.second()


class VideoProcessThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, input_video, output_dir, title_text, speed, segment_duration, 
                 use_gpu, part_suffix, bg_color, text_bg_color, text_color, font_path,
                 start_time, end_time, skip_ranges, width_scale=1.0, height_scale=1.0,
                 original_video_width=None, original_video_height=None,
                 text_border_color=(255, 255, 255), text_border_width=0,
                 blur_background=False, blur_strength=40,
                 show_part=True, part_position="inline",
                 title_y=200, part_y=1600,
                 merge_last_segment=False, merge_threshold=10, **kwargs):
        super().__init__()
        self.input_video = input_video
        self.output_dir = output_dir
        self.title_text = title_text
        self.speed = speed
        self.segment_duration = segment_duration
        self.use_gpu = use_gpu
        self.part_suffix = part_suffix
        self.bg_color = bg_color
        self.text_bg_color = text_bg_color
        self.text_color = text_color
        self.font_path = font_path
        self.start_time = start_time
        self.end_time = end_time
        self.skip_ranges = skip_ranges
        self.width_scale = width_scale
        self.height_scale = height_scale
        self.original_video_width = original_video_width
        self.original_video_height = original_video_height
        self.text_border_color = text_border_color
        self.text_border_width = text_border_width
        self.blur_background = blur_background
        self.blur_strength = blur_strength
        self.show_part = show_part
        self.part_position = part_position
        self.title_y = title_y
        self.part_y = part_y
        self.merge_last_segment = merge_last_segment
        self.merge_threshold = merge_threshold
        
        # Additional kwargs
        self.overlay_color = kwargs.get('overlay_color', (0, 0, 0))
        self.overlay_opacity = kwargs.get('overlay_opacity', 0)
        self.subtitle_file = kwargs.get('subtitle_file', None)
        self.subtitle_font_size = kwargs.get('subtitle_font_size', 40)
        self.subtitle_y_position = kwargs.get('subtitle_y_position', 1400)
        
        self.is_cancelled = False  # Flag for cancellation
        
    def stop(self):
        """Stop the processing thread"""
        self.is_cancelled = True
        
    def create_overlay_image(self, title_text, part_text, output_path):
        """Create full-frame overlay image (1080x1920) with Title and Part"""
        try:
            if self.font_path and os.path.exists(self.font_path):
                font = ImageFont.truetype(self.font_path, 50)
            else:
                font = ImageFont.truetype("arial.ttf", 50)
        except:
            try:
                font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 50)
            except:
                font = ImageFont.load_default()
        
        canvas_width = 1080
        canvas_height = 1920
        max_text_width = 980
        padding = 40
        border_radius = 20
        
        # Create transparent full frame image
        img = Image.new('RGBA', (canvas_width, canvas_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Helper function to draw a text block
        def draw_text_block(text, y_pos):
            if not text:
                return
                
            avg_char_width = draw.textlength("A", font=font)
            chars_per_line = int(max_text_width / avg_char_width)
            wrapped_text = textwrap.fill(text, width=chars_per_line)
            
            if hasattr(draw, 'multiline_textbbox'):
                bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=15)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                offset_x = bbox[0]
                offset_y = bbox[1]
            else:
                text_width, text_height = draw.multiline_textsize(wrapped_text, font=font, spacing=15)
                offset_x = 0
                offset_y = 0
            
            box_width = text_width + padding * 2
            box_height = text_height + padding * 2
            
            box_x = (canvas_width - box_width) // 2
            box_y = y_pos
            
            # Draw background box (rounded)
            if hasattr(draw, 'rounded_rectangle'):
                draw.rounded_rectangle(
                    [box_x, box_y, box_x + box_width, box_y + box_height],
                    radius=border_radius,
                    fill=self.text_bg_color
                )
            else:
                draw.rectangle(
                    [box_x, box_y, box_x + box_width, box_y + box_height],
                    fill=self.text_bg_color
                )
            
            # Calculate text position
            target_text_x = box_x + padding
            target_text_y = box_y + padding
            draw_x = target_text_x - offset_x
            draw_y = target_text_y - offset_y
            
            # Draw border
            if self.text_border_width > 0:
                for dx in range(-self.text_border_width, self.text_border_width + 1):
                    for dy in range(-self.text_border_width, self.text_border_width + 1):
                        if abs(dx) == self.text_border_width or abs(dy) == self.text_border_width:
                            draw.multiline_text(
                                (draw_x + dx, draw_y + dy),
                                wrapped_text,
                                font=font,
                                fill=self.text_border_color,
                                spacing=15,
                                align='center'
                            )
            
            # Draw main text
            draw.multiline_text(
                (draw_x, draw_y),
                wrapped_text,
                font=font,
                fill=self.text_color,
                spacing=15,
                align='center'
            )
            
        # Handle drawing based on position
        if self.part_position == "inline" or not part_text:
            full_text = f"{title_text} {part_text}" if part_text else title_text
            draw_text_block(full_text, self.title_y)
        else:
            draw_text_block(title_text, self.title_y)
            draw_text_block(part_text, self.part_y)
        
        img.save(output_path)
        
    def get_video_duration(self, video_path):
        """Get video duration using ffprobe"""
        cmd = [
            FFPROBE_EXE,
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            video_path
        ]
        result = run_ffmpeg_silent(cmd)
        return float(result.stdout.strip())
    
    def get_video_dimensions(self, video_path):
        """Get original video dimensions"""
        cmd = [
            FFPROBE_EXE,
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=p=0',
            video_path
        ]
        result = run_ffmpeg_silent(cmd)
        stdout = result.stdout.strip()
        if not stdout:
            return 0, 0
            
        try:
            width, height = map(int, stdout.split(','))
            return width, height
        except Exception:
            return 0, 0
    
    def calculate_segments(self, total_duration):
        """Calculate segments after removing skip ranges"""
        work_duration = self.end_time - self.start_time
        
        for skip_start, skip_end in self.skip_ranges:
            if skip_start < skip_end:
                skip_in_range_start = max(skip_start, self.start_time)
                skip_in_range_end = min(skip_end, self.end_time)
                if skip_in_range_end > skip_in_range_start:
                    work_duration -= (skip_in_range_end - skip_in_range_start)
        
        adjusted_duration = work_duration / self.speed if self.speed > 0 else work_duration
        
        if self.segment_duration > 0:
            num_segments = int(adjusted_duration / self.segment_duration)
            remainder = adjusted_duration % self.segment_duration
            
            if self.merge_last_segment and num_segments >= 1 and remainder > 0 and remainder < self.merge_threshold:
                pass
            elif remainder > 0:
                num_segments += 1
        else:
            num_segments = 1
            
        return num_segments, adjusted_duration, work_duration
    
    def get_time_ranges(self, total_duration):
        """Create list of time ranges to process (excluding all skip ranges)"""
        if not self.skip_ranges:
            return [(self.start_time, min(self.end_time, total_duration))]
        
        sorted_skips = sorted(self.skip_ranges, key=lambda x: x[0])
        
        ranges = []
        current_start = self.start_time
        end_time = min(self.end_time, total_duration)
        
        for skip_start, skip_end in sorted_skips:
            if skip_end <= current_start or skip_start >= end_time:
                continue
            
            effective_skip_start = max(skip_start, current_start)
            effective_skip_end = min(skip_end, end_time)
            
            if effective_skip_start > current_start:
                ranges.append((current_start, effective_skip_start))
            
            current_start = effective_skip_end
            
            if current_start >= end_time:
                break
        
        if current_start < end_time:
            ranges.append((current_start, end_time))
        
        return ranges
    
    def run(self):
        try:
            os.makedirs(self.output_dir, exist_ok=True)
            
            self.progress.emit("🖼️ Đang tạo hình nền tiêu đề...")
            title_path = os.path.join(self.output_dir, "title_overlay.png")
            default_part_text = f"{self.part_suffix} 1" if self.show_part else ""
            self.create_overlay_image(self.title_text, default_part_text, title_path)
            
            self.progress.emit("📊 Đang lấy thông tin video...")
            total_duration = self.get_video_duration(self.input_video)
            
            video_width, video_height = self.get_video_dimensions(self.input_video)
            self.original_video_width = video_width
            self.original_video_height = video_height
            
            time_ranges = self.get_time_ranges(total_duration)
            
            if not time_ranges:
                self.finished.emit(False, "Không có khoảng thời gian nào để xử lý!")
                return
            
            work_duration = sum(end - start for start, end in time_ranges)
            adjusted_duration = work_duration / self.speed if self.speed > 0 else work_duration
            
            self.progress.emit(f"📽️ Video gốc: {self.format_time(total_duration)} ({video_width}x{video_height})")
            self.progress.emit(f"✂️ Khoảng cắt: {self.format_time(self.start_time)} - {self.format_time(self.end_time)}")
            
            if self.skip_ranges:
                self.progress.emit("⏭️ Các đoạn bỏ qua:")
                for i, (skip_start, skip_end) in enumerate(self.skip_ranges, 1):
                    self.progress.emit(f"   {i}. {self.format_time(skip_start)} - {self.format_time(skip_end)}")
            
            self.progress.emit(f"⏱️ Thời gian làm việc (gốc): {self.format_time(work_duration)}")
            self.progress.emit(f"⚡ Sau tốc độ {self.speed}x: {self.format_time(adjusted_duration)}")
            self.progress.emit(f"🔍 Zoom: {self.width_scale:.2f}x (W) × {self.height_scale:.2f}x (H)")
            
            if self.text_border_width > 0:
                border_info = f"Viền chữ: {self.text_border_width}px, RGB{self.text_border_color}"
                self.progress.emit(f"🖌️ {border_info}")
            
            max_width = 1080
            if video_width > max_width:
                fit_scale = max_width / video_width
                fit_width = max_width
                fit_height = int(video_height * fit_scale)
            else:
                fit_width = video_width
                fit_height = video_height
            
            final_width = int(fit_width * self.width_scale)
            final_height = int(fit_height * self.height_scale)
            
            self.progress.emit(f"📏 Kích thước video: {final_width}×{final_height} (gốc: {video_width}×{video_height})")
            
            if self.segment_duration > 0:
                num_segments = int(adjusted_duration / self.segment_duration)
                remainder = adjusted_duration - (num_segments * self.segment_duration)
                
                if remainder > 0:
                    threshold = self.segment_duration * 0.2
                    if remainder < threshold and num_segments >= 1:
                        self.progress.emit(f"👌 Phần dư {self.format_time(remainder)} < 20%, sẽ gộp vào part cuối.")
                    else:
                        num_segments += 1
                
                if num_segments == 0:
                    num_segments = 1
                
                num_segments, adjusted_duration, work_duration = self.calculate_segments(work_duration)
                
                self.progress.emit(f"🎬 Sẽ tạo {num_segments} video con...")
                
                current_time = 0
                segment_num = 1
                
                for segment_idx in range(num_segments):
                    if segment_idx == num_segments - 1:
                        segment_duration_needed = adjusted_duration - current_time
                    else:
                        segment_duration_needed = self.segment_duration
                    
                    source_duration_needed = segment_duration_needed * self.speed
                    
                    self.progress.emit(f"\n📦 Đang xử lý video {segment_num}/{num_segments}...")
                    self.progress.emit(f"   Segment: {self.format_time(segment_duration_needed)} (output)")
                    self.progress.emit(f"   Nguồn: {self.format_time(source_duration_needed)} (gốc)")
                    
                    if self.show_part:
                        if self.part_position == "inline":
                            part_text = f"{self.part_suffix} {segment_num}"
                            full_title = f"{self.title_text} {part_text}"
                            part_overlay = ""
                        else:
                            part_text = f"{self.part_suffix} {segment_num}"
                            full_title = self.title_text
                            part_overlay = part_text
                    else:
                        full_title = self.title_text
                        part_overlay = ""
                    
                    segment_title_path = os.path.join(self.output_dir, f"title_part_{segment_num:03d}.png")
                    self.create_overlay_image(full_title, part_overlay, segment_title_path)
                    
                    date_str = datetime.now().strftime("%d%m%y")
                    base_name = f"{date_str}{segment_num:02d}"
                    output_file = os.path.join(self.output_dir, f"{base_name}.mp4")
                    counter = 1
                    while os.path.exists(output_file):
                        output_file = os.path.join(self.output_dir, f"{base_name}{counter}.mp4")
                        counter += 1
                    
                    self.create_segment_from_ranges(
                        time_ranges, 
                        current_time * self.speed,
                        source_duration_needed,
                        segment_title_path,
                        output_file,
                        video_width,
                        video_height
                    )
                    
                    current_time += segment_duration_needed
                    segment_num += 1
                
                self.finished.emit(True, f"✅ Đã tạo thành công {num_segments} video!")
            else:
                self.progress.emit("🎥 Đang xử lý video toàn bộ...")
                
                date_str = datetime.now().strftime("%d%m%y")
                base_name = f"{date_str}"
                output_file = os.path.join(self.output_dir, f"{base_name}.mp4")
                counter = 1
                while os.path.exists(output_file):
                    output_file = os.path.join(self.output_dir, f"{base_name}{counter}.mp4")
                    counter += 1
                
                self.create_segment_from_ranges(
                    time_ranges,
                    0,
                    work_duration,
                    title_path,
                    output_file,
                    video_width,
                    video_height
                )
                
                self.finished.emit(True, "✅ Đã xử lý video thành công!")
                
        except Exception as e:
            self.finished.emit(False, f"❌ Lỗi: {str(e)}")
        finally:
            # Dọn dẹp TẤT CẢ file tạm trong output_dir
            if 'title_path' in locals() and hasattr(self, 'output_dir') and os.path.exists(self.output_dir):
                import glob
                temp_patterns = [
                    os.path.join(self.output_dir, "title_overlay.png"),
                    os.path.join(self.output_dir, "title_part_*.png"),
                    os.path.join(self.output_dir, "temp_*.mp4"),
                    os.path.join(self.output_dir, "temp_merged.mp4"),
                    os.path.join(self.output_dir, "concat_list.txt"),
                ]
                for pattern in temp_patterns:
                    for f in glob.glob(pattern):
                        for _ in range(5):
                            try:
                                os.remove(f)
                                break
                            except OSError:
                                import time
                                time.sleep(0.3)
    
    def create_segment_from_ranges(self, time_ranges, start_offset, duration_needed, 
                                   title_image, output_file, video_width, video_height):
        """Create segment from multiple time ranges"""
        temp_clips = []
        remaining_duration = duration_needed
        
        for range_start, range_end in time_ranges:
            if remaining_duration <= 0:
                break
            
            range_duration = range_end - range_start
            
            if start_offset >= range_duration:
                start_offset -= range_duration
                continue
            
            clip_start = range_start + start_offset
            clip_duration = min(remaining_duration, range_duration - start_offset)
            
            temp_clip = os.path.join(self.output_dir, f"temp_{len(temp_clips)}.mp4")
            self.extract_clip(clip_start, clip_duration, temp_clip)
            temp_clips.append(temp_clip)
            
            remaining_duration -= clip_duration
            start_offset = 0
        
        if len(temp_clips) == 1:
            self.process_final_video(temp_clips[0], title_image, output_file, video_width, video_height)
        else:
            concat_file = os.path.join(self.output_dir, "concat_list.txt")
            with open(concat_file, 'w') as f:
                for clip in temp_clips:
                    f.write(f"file '{clip}'\n")
            
            merged_clip = os.path.join(self.output_dir, "temp_merged.mp4")
            concat_cmd = [
                FFMPEG_EXE, '-y', '-f', 'concat', '-safe', '0',
                '-i', concat_file, '-c', 'copy', merged_clip
            ]
            run_ffmpeg_silent(concat_cmd)
            
            self.process_final_video(merged_clip, title_image, output_file, video_width, video_height)
            
            if os.path.exists(merged_clip):
                for _ in range(5):
                    try:
                        os.remove(merged_clip)
                        break
                    except OSError:
                        time.sleep(0.5)
            
            if os.path.exists(concat_file):
                for _ in range(5):
                    try:
                        os.remove(concat_file)
                        break
                    except OSError:
                        time.sleep(0.5)
        
        for clip in temp_clips:
            if os.path.exists(clip):
                for _ in range(5):
                    try:
                        os.remove(clip)
                        break
                    except OSError:
                        time.sleep(0.5)
    
    def extract_clip(self, start_time, duration, output_path):
        """Extract a clip from the original video"""
        cmd = [
            FFMPEG_EXE, '-y',
            '-ss', str(start_time),
            '-i', self.input_video,
            '-t', str(duration),
            '-c', 'copy',
            output_path
        ]
        run_ffmpeg_silent(cmd)
    
    def process_final_video(self, input_clip, title_image, output_file, video_width, video_height):
        """Process final video with overlay and speed"""
        if self.use_gpu:
            gpu_info = detect_gpu_encoder()
            if gpu_info:
                encoder_name, preset_args, quality_args = gpu_info
                video_codec = ['-c:v', encoder_name] + preset_args + quality_args
                self.progress.emit(f"🎮 Sử dụng GPU encoder: {encoder_name}")
            else:
                video_codec = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '23']
                self.progress.emit("⚠️ Không tìm thấy GPU encoder, sử dụng CPU (libx264)")
        else:
            video_codec = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '23']
        
        bg_hex = f"0x{self.bg_color[0]:02x}{self.bg_color[1]:02x}{self.bg_color[2]:02x}"
        
        is_audio_only = (video_width == 0 or video_height == 0)
        
        max_width = 1080
        if is_audio_only:
            scaled_width = 0
            scaled_height = 0
            overlay_x = 0
            overlay_y = 0
        else:
            if video_width > max_width:
                fit_scale = max_width / video_width
                fit_width = max_width
                fit_height = int(video_height * fit_scale)
            else:
                fit_width = video_width
                fit_height = video_height
            
            scaled_width = int(fit_width * self.width_scale)
            scaled_height = int(fit_height * self.height_scale)
            
            overlay_x = (1080 - scaled_width) // 2
            overlay_y = (1920 - scaled_height) // 2
        
        self.progress.emit(f"📐 Vị trí video trong khung 9:16: x={overlay_x}, y={overlay_y}")
        
        eff_blur = max(1, self.blur_strength / 4)
        
        if is_audio_only:
            if self.speed != 1.0:
                filter_complex = (
                    f"color=c={bg_hex}:s=1080x1920:r=30[bg];"
                    f"[bg][1:v]overlay=0:0[base];"
                    f"[0:a]atempo={self.speed}[audio]"
                )
                audio_map = ['-map', '[audio]']
            else:
                filter_complex = (
                    f"color=c={bg_hex}:s=1080x1920:r=30[bg];"
                    f"[bg][1:v]overlay=0:0[base]"
                )
                audio_map = ['-map', '0:a?']

            if hasattr(self, 'overlay_opacity') and self.overlay_opacity > 0:
                alpha = self.overlay_opacity / 100.0
                overlay_hex = f"0x{self.overlay_color[0]:02x}{self.overlay_color[1]:02x}{self.overlay_color[2]:02x}"
                filter_complex += f";[base]drawbox=x=0:y=0:w=1080:h=1920:color={overlay_hex}@{alpha}:t=fill[video_with_title]"
            else:
                filter_complex += f";[base]copy[video_with_title]"
                
            if self.subtitle_file and os.path.exists(self.subtitle_file):
                subtitle_path_normalized = self.subtitle_file.replace('\\', '/')
                subtitle_path_escaped = subtitle_path_normalized.replace(':', '\\:')
                margin_v = 1920 - self.subtitle_y_position
                subtitle_style = (
                    f"FontSize={self.subtitle_font_size},"
                    f"Alignment=2,"
                    f"MarginV={margin_v},"
                    f"PrimaryColour=&HFFFFFF,"
                    f"OutlineColour=&H000000,"
                    f"Outline=2,"
                    f"BorderStyle=1"
                )
                filter_complex += f";[video_with_title]subtitles='{subtitle_path_escaped}':force_style='{subtitle_style}'[out]"
            else:
                filter_complex += ";[video_with_title]null[out]"
                
        elif self.speed != 1.0:
            if self.blur_background:
                filter_complex = (
                    f"[0:v]split=2[fg_source][bg_source];"
                    f"[bg_source]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur={eff_blur}:3,scale=1080:1920[bg_blurred];"
                    f"[fg_source]setpts={1/self.speed}*PTS,scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"[bg_blurred][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[base];"
                )
            else:
                filter_complex = (
                    f"[0:v]setpts={1/self.speed}*PTS,"
                    f"scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"color=c={bg_hex}:s=1080x1920[bg];"
                    f"[bg][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[base];"
                )
            
            # Apply color overlay if opacity > 0
            if hasattr(self, 'overlay_opacity') and self.overlay_opacity > 0:
                alpha = self.overlay_opacity / 100.0
                overlay_hex = f"0x{self.overlay_color[0]:02x}{self.overlay_color[1]:02x}{self.overlay_color[2]:02x}"
                filter_complex += f"[base]drawbox=x=0:y=0:w=1080:h=1920:color={overlay_hex}@{alpha}:t=fill[base_with_overlay];"
                filter_complex += f"[base_with_overlay][1:v]overlay=0:0[video_with_title];"
            else:
                filter_complex += f"[base][1:v]overlay=0:0[video_with_title];"
                
            filter_complex += f"[0:a]atempo={self.speed}[audio]"
            
            # Add subtitle filter if subtitle file exists
            if self.subtitle_file and os.path.exists(self.subtitle_file):
                # Escape subtitle file path for FFmpeg
                subtitle_path_escaped = self.subtitle_file.replace('\\', '/').replace(':', '\\:')
                
                # Calculate subtitle position from bottom
                margin_v = 1920 - self.subtitle_y_position
                
                # Build subtitle style
                subtitle_style = (
                    f"FontSize={self.subtitle_font_size},"
                    f"Alignment=2,"  # Bottom center
                    f"MarginV={margin_v},"
                    f"PrimaryColour=&HFFFFFF,"  # White text
                    f"OutlineColour=&H000000,"  # Black outline
                    f"Outline=2,"
                    f"BorderStyle=1"
                )
                
                filter_complex += f";[video_with_title]subtitles={subtitle_path_escaped}:force_style='{subtitle_style}'[out]"
            else:
                filter_complex += ";[video_with_title]null[out]"
                
            audio_map = ['-map', '[audio]']
        else:
            if self.blur_background:
                filter_complex = (
                    f"[0:v]split=2[fg_source][bg_source];"
                    f"[bg_source]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur={eff_blur}:3,scale=1080:1920[bg_blurred];"
                    f"[fg_source]scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"[bg_blurred][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[base];"
                )
            else:
                filter_complex = (
                    f"[0:v]scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"color=c={bg_hex}:s=1080x1920[bg];"
                    f"[bg][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[base];"
                )
                
            # Apply color overlay if opacity > 0
            if hasattr(self, 'overlay_opacity') and self.overlay_opacity > 0:
                alpha = self.overlay_opacity / 100.0
                overlay_hex = f"0x{self.overlay_color[0]:02x}{self.overlay_color[1]:02x}{self.overlay_color[2]:02x}"
                filter_complex += f"[base]drawbox=x=0:y=0:w=1080:h=1920:color={overlay_hex}@{alpha}:t=fill[base_with_overlay];"
                filter_complex += f"[base_with_overlay][1:v]overlay=0:0[video_with_title]"
            else:
                filter_complex += f"[base][1:v]overlay=0:0[video_with_title]"
                
            # Add subtitle filter if subtitle file exists
                if self.subtitle_file and os.path.exists(self.subtitle_file):
                    # For FFmpeg subtitles filter on Windows:
                    # 1. Convert backslashes to forward slashes
                    # 2. Escape colons with backslash
                    # 3. Wrap entire path in single quotes
                    subtitle_path_normalized = self.subtitle_file.replace('\\', '/')
                    subtitle_path_escaped = subtitle_path_normalized.replace(':', '\\:')
                    
                    # Calculate subtitle position from bottom
                    margin_v = 1920 - self.subtitle_y_position
                    
                    # Build subtitle style
                    subtitle_style = (
                        f"FontSize={self.subtitle_font_size},"
                        f"Alignment=2,"  # Bottom center
                        f"MarginV={margin_v},"
                        f"PrimaryColour=&HFFFFFF,"  # White text
                        f"OutlineColour=&H000000,"  # Black outline
                        f"Outline=2,"
                        f"BorderStyle=1"
                    )
                    
                    # Use subtitles filter with escaped path
                    filter_complex += f";[video_with_title]subtitles='{subtitle_path_escaped}':force_style='{subtitle_style}'[out]"
                else:
                    filter_complex += ";[video_with_title]null[out]"
                    
            audio_map = ['-map', '0:a?']

        cmd = [
            FFMPEG_EXE, '-y',
            '-i', input_clip,
            '-i', title_image,
            '-filter_complex', filter_complex,
            '-map', '[out]'
        ]

        cmd.extend(audio_map)
        cmd.extend(video_codec)
        
        output_args = [
            '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart',
            '-pix_fmt', 'yuv420p'
        ]
        if is_audio_only:
            output_args.append('-shortest')
        output_args.append(output_file)
        
        cmd.extend(output_args)

        self.progress.emit(f"🔄 Đang xử lý: {output_file}")
        
        # Log FFmpeg command for debugging (only if subtitle is enabled)
        if self.subtitle_file:
            cmd_str = ' '.join([f'"{arg}"' if ' ' in str(arg) else str(arg) for arg in cmd])
            self.progress.emit(f"🐛 FFmpeg command: {cmd_str[:200]}...")  # First 200 chars
        
        result = run_ffmpeg_silent(cmd)
        
        # Check if FFmpeg succeeded
        if result.returncode != 0:
            error_msg = f"FFmpeg failed with code {result.returncode}"
            if result.stderr:
                # Get last 1000 chars of stderr (usually contains the actual error)
                stderr_lines = result.stderr.strip().split('\n')
                relevant_error = '\n'.join(stderr_lines[-10:])  # Last 10 lines
                error_msg += f"\n{relevant_error}"
            self.progress.emit(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
        
        # Verify output file was created
        if not os.path.exists(output_file):
            raise RuntimeError(f"Output file was not created: {output_file}")
        
        file_size = os.path.getsize(output_file) / (1024 * 1024)  # MB
        self.progress.emit(f"✅ Video created: {file_size:.1f} MB")

        if os.path.exists(title_image):
            for i in range(5):
                try:
                    os.remove(title_image)
                    break
                except OSError:
                    time.sleep(0.5)

    def format_time(self, seconds):
        """Format seconds to HH:MM:SS"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
