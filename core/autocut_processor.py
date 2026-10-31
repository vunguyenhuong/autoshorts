"""
AutoCut Video Editor - Core Processing Module
Contains video processing logic, GPU detection, and worker threads
"""

import sys
import os
import time
import random
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import textwrap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTimeEdit
from PyQt6.QtCore import QThread, pyqtSignal, QTime, Qt
from PyQt6.QtGui import QFont as QFont_GUI
from datetime import datetime
from core.subtitle_processor import (
    SubtitleConfig, transcribe_audio, build_subtitle_blocks, generate_ass_file
)


# ─────────────────────────────────────────────────────────────────────────────

def prepare_thumbnail_portrait(thumb_path: str, output_path: str) -> bool:
    """
    Convert thumbnail (bất kỳ tỉ lệ nào) sang khung dọc 1080×1920.
    - Nếu ảnh ngang (landscape): scale chiều rộng = 1080, phần thừa chiều cao
      được lấp bằng blur background (giống CapCut/TikTok style).
    - Nếu ảnh dọc: scale, crop center.
    Trả về True nếu thành công.
    """
    img = None
    try:
        img = Image.open(thumb_path).convert("RGBA")
    except Exception as e:
        print(f"PIL open error ({e}), converting via FFmpeg...")
        temp_png = thumb_path + ".converted.png"
        try:
            cmd = [FFMPEG_EXE, '-y', '-i', thumb_path, temp_png]
            run_ffmpeg_silent(cmd)
            if os.path.exists(temp_png):
                img = Image.open(temp_png).convert("RGBA")
                try:
                    os.remove(temp_png)
                except Exception:
                    pass
        except Exception as ex:
            print(f"FFmpeg image convert failed: {ex}")

    if img is None:
        return False

    try:
        orig_w, orig_h = img.size
        target_w, target_h = 1080, 1920

        # Tính tỉ lệ để vừa chiều rộng
        scale_by_w = target_w / orig_w
        fitted_h = int(orig_h * scale_by_w)

        if fitted_h >= target_h:
            # Đủ chiều cao — scale rồi crop center
            resized = img.resize((target_w, fitted_h), Image.LANCZOS)
            top = (fitted_h - target_h) // 2
            final = resized.crop((0, top, target_w, top + target_h))
        else:
            # Thiếu chiều cao — tạo blur background
            scale_by_h = target_h / orig_h
            bg_w = int(orig_w * scale_by_h)
            bg_h = target_h

            bg = img.resize((max(bg_w, target_w), bg_h), Image.LANCZOS).convert("RGB")
            if bg.size[0] < target_w:
                tmp = Image.new("RGB", (target_w, bg_h), (0, 0, 0))
                x_off = (target_w - bg.size[0]) // 2
                tmp.paste(bg, (x_off, 0))
                bg = tmp
            else:
                x_off = (bg.size[0] - target_w) // 2
                bg = bg.crop((x_off, 0, x_off + target_w, bg_h))

            try:
                from PIL import ImageFilter
                bg = bg.filter(ImageFilter.GaussianBlur(radius=20))
            except Exception:
                pass  # blur không bắt buộc

            # Dán foreground (ảnh gốc scale theo width) lên giữa
            fg = img.resize((target_w, fitted_h), Image.LANCZOS).convert("RGBA")
            canvas = bg.convert("RGBA")
            y_offset = (target_h - fitted_h) // 2
            canvas.paste(fg, (0, y_offset), fg)
            final = canvas

        final.convert("RGB").save(output_path, "PNG")
        return True
    except Exception as e:
        print(f"⚠️ prepare_thumbnail_portrait error: {e}")
        return False


def fetch_or_extract_thumbnail(thumb_url: str, input_video: str, output_dir: str, progress_callback=None) -> str:
    """
    Tự động chuẩn bị ảnh bìa 9:16 portrait:
    1. Nếu thumb_url có sẵn (dạng URL http/https): Tải thumbnail bằng direct URL / YouTube API / yt-dlp / urllib.
    2. Nếu không có URL hoặc tải thất bại: Mặc định trích xuất frame 0 của input_video qua FFmpeg.
    3. Chuyển đổi về định dạng portrait 9:16 (prepare_thumbnail_portrait) và trả về đường dẫn file PNG.
    """
    os.makedirs(output_dir, exist_ok=True)
    portrait_path = os.path.join(output_dir, "_thumb_portrait.png")
    raw_thumb = os.path.join(output_dir, "_thumb_raw_temp.jpg")
    
    url = thumb_url.strip().strip('"\'') if thumb_url else ""
    got_raw = False

    # 1. Thử tải từ URL nếu có
    if url and (url.startswith("http://") or url.startswith("https://")):
        if progress_callback:
            progress_callback(f"🖼️ Đang lấy thumbnail từ link URL...")

        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        # 1.0 Tải trực tiếp thumbnail YouTube nếu là link youtu.be hoặc youtube.com
        import re
        yt_match = re.search(r'(?:v=|\/|embed\/|shorts\/)([a-zA-Z0-9_-]{11})', url)
        if yt_match:
            vid_id = yt_match.group(1)
            for quality in ['maxresdefault', 'hqdefault', 'mqdefault']:
                img_url = f"https://img.youtube.com/vi/{vid_id}/{quality}.jpg"
                try:
                    import urllib.request
                    req = urllib.request.Request(img_url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                    with urllib.request.urlopen(req, context=ssl_ctx, timeout=8) as resp, open(raw_thumb, 'wb') as f_out:
                        data = resp.read()
                        if len(data) > 2000:
                            f_out.write(data)
                            got_raw = True
                            if progress_callback:
                                progress_callback(f"✅ Đã tải thumbnail YouTube HD ({vid_id})")
                            break
                except Exception as e:
                    print(f"YouTube direct thumb download error ({quality}): {e}")

        # 1.1 Link ảnh trực tiếp
        if not got_raw and any(ext in url.lower() for ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp']):
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=12) as resp, open(raw_thumb, 'wb') as f_out:
                    f_out.write(resp.read())
                if os.path.exists(raw_thumb) and os.path.getsize(raw_thumb) > 1000:
                    got_raw = True
            except Exception as e:
                print(f"Direct thumb url download error: {e}")

        # 1.2 Link video (TikTok / Facebook...) -> dùng yt_dlp
        if not got_raw:
            try:
                import yt_dlp
                out_tmpl = str(Path(output_dir) / "_thumb_ytdlp")
                ydl_opts = {
                    'skip_download': True,
                    'writethumbnail': True,
                    'outtmpl': out_tmpl,
                    'quiet': True,
                    'no_warnings': True,
                    'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(url, download=True)
                for ext in [".jpg", ".jpeg", ".webp", ".png"]:
                    cand = f"{out_tmpl}.{ext}"
                    if os.path.exists(cand) and os.path.getsize(cand) > 1000:
                        raw_thumb = cand
                        got_raw = True
                        break
            except Exception as e:
                print(f"yt_dlp thumbnail error: {e}")

        # 1.3 Nếu chưa lấy được -> Thử urllib mở URL bất kỳ
        if not got_raw:
            try:
                import urllib.request
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
                with urllib.request.urlopen(req, context=ssl_ctx, timeout=10) as resp, open(raw_thumb, 'wb') as f_out:
                    data = resp.read()
                    if len(data) > 1000:
                        f_out.write(data)
                        got_raw = True
            except Exception as e:
                print(f"Generic urllib fallback error: {e}")

    # 2. Nếu không có URL hoặc tải URL thất bại → Trích xuất frame 0 của video
    if not got_raw and input_video and os.path.exists(input_video):
        if progress_callback:
            progress_callback("📸 Trích xuất frame đầu video làm thumbnail...")
        try:
            cmd = [
                FFMPEG_EXE, '-y', '-ss', '0', '-i', input_video,
                '-frames:v', '1', '-q:v', '2', raw_thumb
            ]
            run_ffmpeg_silent(cmd)
            if os.path.exists(raw_thumb) and os.path.getsize(raw_thumb) > 1000:
                got_raw = True
        except Exception as e:
            print(f"FFmpeg frame 0 extract error: {e}")

    # 3. Convert sang 1080x1920 portrait
    if got_raw and os.path.exists(raw_thumb):
        ok = prepare_thumbnail_portrait(raw_thumb, portrait_path)
        try:
            os.remove(raw_thumb)
        except Exception:
            pass
        if ok and os.path.exists(portrait_path):
            return portrait_path

    return ""


def embed_thumbnail_to_mp4(mp4_path: str, cover_jpg_path: str) -> bool:
    """
    Nhúng file ảnh bìa (.jpg) vào làm thumbnail/cover image đại diện của file video MP4.
    - Giúp file .mp4 hiển thị ảnh thumbnail trên Windows File Explorer / TikTok / Facebook / Youtube Uploader.
    - Không làm thay đổi chất lượng video hay luồng phát video bên trong.
    """
    if not os.path.exists(mp4_path) or not os.path.exists(cover_jpg_path):
        return False

    temp_output = mp4_path + ".thumb_embed.mp4"
    try:
        cmd = [
            FFMPEG_EXE, '-y',
            '-i', mp4_path,
            '-i', cover_jpg_path,
            '-map', '0:v',
            '-map', '0:a?',
            '-map', '1',
            '-c', 'copy',
            '-disposition:v:1', 'attached_pic',
            temp_output
        ]
        run_ffmpeg_silent(cmd)
        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, mp4_path)
            return True
        else:
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return False
    except Exception as e:
        print(f"⚠️ embed_thumbnail_to_mp4 error: {e}")
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except Exception:
                pass
        return False


def prepend_thumbnail_frame_to_video(mp4_path: str, thumb_jpg_path: str, frame_duration: float = 0.04) -> bool:
    """
    Chèn ảnh thumbnail làm frame đầu tiên của video output.
    - thumb_jpg_path: ảnh thumbnail đã có chữ tiêu đề + số phần (1080x1920).
    - frame_duration: thời lượng frame tĩnh ở đầu (giây). Mặc định 0.04s (~1 frame @25fps).
    Kết quả: khi mở/preview video, frame đầu tiên nhìn thấy chính là ảnh thumbnail.
    Trả về True nếu thành công.
    """
    if not os.path.exists(mp4_path) or not os.path.exists(thumb_jpg_path):
        return False

    temp_still = mp4_path + "._still.mp4"
    temp_output = mp4_path + "._prepend.mp4"
    concat_txt = mp4_path + "._concat.txt"
    try:
        # Bước 1: Tạo clip tĩnh từ ảnh thumbnail (1 frame, duration = frame_duration)
        cmd_still = [
            FFMPEG_EXE, '-y',
            '-loop', '1',
            '-i', thumb_jpg_path,
            '-t', str(frame_duration),
            '-vf', 'scale=1080:1920:flags=lanczos,format=yuv420p',
            '-r', '25',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
            '-an',
            temp_still
        ]
        run_ffmpeg_silent(cmd_still)
        if not os.path.exists(temp_still) or os.path.getsize(temp_still) == 0:
            return False

        # Bước 2: Ghép [still + video gốc] bằng concat demuxer
        with open(concat_txt, 'w', encoding='utf-8') as f:
            f.write(f"file '{temp_still}'\n")
            f.write(f"file '{mp4_path}'\n")

        cmd_concat = [
            FFMPEG_EXE, '-y',
            '-f', 'concat', '-safe', '0',
            '-i', concat_txt,
            '-c', 'copy',
            temp_output
        ]
        run_ffmpeg_silent(cmd_concat)

        if os.path.exists(temp_output) and os.path.getsize(temp_output) > 0:
            os.replace(temp_output, mp4_path)
            return True
        else:
            return False
    except Exception as e:
        print(f"⚠️ prepend_thumbnail_frame_to_video error: {e}")
        return False
    finally:
        for f in [temp_still, concat_txt]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except Exception:
                pass


def create_thumbnail_with_part_overlay(
    thumb_portrait_path: str,
    title_text: str,
    part_text: str,
    output_path: str,
    font_path: str = "",
    text_color: tuple = (255, 255, 255),
    border_color: tuple = (0, 0, 0),
    border_width: int = 6,
    title_y: int = 250,
    part_y: int = -1,
    title_font_size: int = 80,
    part_font_size: int = 120,
) -> bool:
    """
    Tạo file ảnh bìa thumbnail (1080x1920 portrait) chứa cả Tiêu đề (title_text) và Số phần (part_text e.g. TEIL 1 / Phần 1).
    - title_text: Tiêu đề video (vẽ ở vị trí title_y)
    - part_text: Số phần (vẽ ở vị trí part_y hoặc giữa màn hình)
    """
    try:
        if not os.path.exists(thumb_portrait_path):
            return False

        img = Image.open(thumb_portrait_path).convert("RGBA")
        canvas_w, canvas_h = img.size  # 1080, 1920

        # Load fonts
        title_font = None
        part_font = None
        for fp in [font_path, "arial.ttf", "C:/Windows/Fonts/arial.ttf"]:
            if fp and os.path.exists(fp):
                try:
                    if title_font is None:
                        title_font = ImageFont.truetype(fp, title_font_size)
                    if part_font is None:
                        part_font = ImageFont.truetype(fp, part_font_size)
                    break
                except Exception:
                    continue
        if title_font is None:
            try:
                title_font = ImageFont.truetype("arial.ttf", title_font_size)
                part_font = ImageFont.truetype("arial.ttf", part_font_size)
            except Exception:
                title_font = ImageFont.load_default()
                part_font = ImageFont.load_default()

        overlay = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        pill_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        pill_draw = ImageDraw.Draw(pill_layer)

        # 1. Vẽ Title text (Tiêu đề video - Tự động xuống dòng nếu quá dài)
        if title_text:
            max_title_w = 940  # Khung tối đa cho chữ (1080 - 140px lề)
            avg_char_w = draw.textlength("A", font=title_font) if hasattr(draw, 'textlength') else 30
            chars_per_line = max(10, int(max_title_w / max(1, avg_char_w)))
            wrapped_title = textwrap.fill(title_text, width=chars_per_line)

            if hasattr(draw, 'multiline_textbbox'):
                bbox = draw.multiline_textbbox((0, 0), wrapped_title, font=title_font, spacing=15)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                ox, oy = bbox[0], bbox[1]
            else:
                tw, th = draw.textsize(wrapped_title, font=title_font)
                ox, oy = 0, 0

            tx = (canvas_w - tw) // 2 - ox
            ty = title_y - oy if title_y > 0 else 250 - oy

            # Pill background cho multiline title
            pad_t = 24
            pill_t0 = tx + ox - pad_t
            pill_t1 = tx + ox + tw + pad_t
            pill_ty0 = ty + oy - pad_t // 2
            pill_ty1 = ty + oy + th + pad_t // 2
            if hasattr(pill_draw, 'rounded_rectangle'):
                pill_draw.rounded_rectangle([pill_t0, pill_ty0, pill_t1, pill_ty1], radius=18, fill=(0, 0, 0, 160))

            bw = max(4, border_width)
            for dx in range(-bw, bw + 1):
                for dy in range(-bw, bw + 1):
                    if abs(dx) == bw or abs(dy) == bw:
                        draw.multiline_text((tx + dx, ty + dy), wrapped_title, font=title_font, fill=(*border_color[:3], 255), align="center", spacing=15)
            draw.multiline_text((tx, ty), wrapped_title, font=title_font, fill=(*text_color[:3], 255), align="center", spacing=15)

        # 2. Vẽ Part text (Số phần e.g. TEIL 1 / Phần 1)
        if part_text:
            if hasattr(draw, 'textbbox'):
                bbox = draw.textbbox((0, 0), part_text, font=part_font)
                pw = bbox[2] - bbox[0]
                ph = bbox[3] - bbox[1]
                ox, oy = bbox[0], bbox[1]
            else:
                pw, ph = draw.textsize(part_text, font=part_font)
                ox, oy = 0, 0

            px = (canvas_w - pw) // 2 - ox
            py = part_y - oy if part_y > 0 else (1350 - oy if title_text else (canvas_h - ph) // 2 - oy)

            pad = 25
            pill_x0 = px + ox - pad
            pill_y0 = py + oy - pad // 2
            pill_x1 = px + ox + pw + pad
            pill_y1 = py + oy + ph + pad // 2
            if hasattr(pill_draw, 'rounded_rectangle'):
                pill_draw.rounded_rectangle([pill_x0, pill_y0, pill_x1, pill_y1], radius=20, fill=(0, 0, 0, 160))
            else:
                pill_draw.rectangle([pill_x0, pill_y0, pill_x1, pill_y1], fill=(0, 0, 0, 160))

            bw = max(4, border_width)
            for dx in range(-bw, bw + 1):
                for dy in range(-bw, bw + 1):
                    if abs(dx) == bw or abs(dy) == bw:
                        draw.text((px + dx, py + dy), part_text, font=part_font, fill=(*border_color[:3], 255))
            draw.text((px, py), part_text, font=part_font, fill=(255, 255, 255, 255))

        result = img.copy()
        result = Image.alpha_composite(result, pill_layer)
        result = Image.alpha_composite(result, overlay)

        ext = Path(output_path).suffix.lower()
        if ext in ['.jpg', '.jpeg']:
            result.convert("RGB").save(output_path, "JPEG", quality=95)
        else:
            result.convert("RGB").save(output_path, "PNG")
        return True
    except Exception as e:
        print(f"⚠️ create_thumbnail_with_part_overlay error: {e}")
        return False


class VideoDownloaderThread(QThread):
    """
    Background thread tải video từ URL bằng yt-dlp.
    Signals:
        progress(str)           - cập nhật tiến trình
        finished(bool, str, str)- (success, video_path, thumbnail_path)
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, str)  # success, video_path, thumb_path

    def __init__(self, url: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.url = url.strip()
        self.output_dir = output_dir
        self._cancelled = False

    def stop(self):
        self._cancelled = True

    def run(self):
        try:
            import yt_dlp
        except ImportError:
            self.progress.emit("❌ Thiếu thư viện yt-dlp. Hãy chạy: pip install yt-dlp")
            self.finished.emit(False, "", "")
            return

        os.makedirs(self.output_dir, exist_ok=True)

        # Lưu các path đã tải
        _downloaded_video = [""]
        _downloaded_thumb = [""]

        def _progress_hook(d):
            if self._cancelled:
                raise Exception("Cancelled by user")
            status = d.get("status", "")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
                downloaded = d.get("downloaded_bytes", 0)
                if total > 0:
                    pct = downloaded / total * 100
                    speed = d.get("speed", 0) or 0
                    speed_mb = speed / 1024 / 1024
                    eta = d.get("eta", 0) or 0
                    self.progress.emit(
                        f"⬇️ Đang tải: {pct:.1f}% | {speed_mb:.1f} MB/s | ETA: {eta}s"
                    )
                else:
                    self.progress.emit(f"⬇️ Đang tải... {downloaded / 1024 / 1024:.1f} MB")
            elif status == "finished":
                fp = d.get("filename", "")
                if fp:
                    _downloaded_video[0] = fp
                self.progress.emit(f"✅ Tải xong: {Path(d.get('filename', '')).name}")

        # Xác định đường dẫn ffmpeg để yt-dlp dùng khi merge streams
        _ffmpeg_dir = str(Path(FFMPEG_EXE).parent) if FFMPEG_EXE and os.path.exists(FFMPEG_EXE) else ""

        # Dùng cùng cấu hình với ShortsDownloader._build_ydl_opts để tránh lỗi 403 / merge
        ydl_opts = {
            # Ưu tiên H.264/AVC + m4a → fallback dần
            "format": (
                "bestvideo[height>=1080][vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height>=1080][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo+bestaudio/"
                "best[vcodec!=none]"
            ),
            "format_sort": ["res", "vcodec:avc", "ext:mp4:m4a"],
            "prefer_free_formats": False,
            "merge_output_format": "mp4",
            "outtmpl": str(Path(self.output_dir) / "%(title)s.%(ext)s"),
            "writethumbnail": True,
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            },
            # Ổn định
            "retries": 10,
            "fragment_retries": 10,
            "ignoreerrors": False,
            "no_warnings": True,
            "quiet": True,
            "noplaylist": True,
            # Remux về mp4 sau khi merge
            "postprocessors": [{
                "key": "FFmpegVideoRemuxer",
                "preferedformat": "mp4",
            }],
            "postprocessor_args": {
                "ffmpeg": ["-c", "copy"],
            },
            "progress_hooks": [_progress_hook],
            "keepvideo": False,
        }
        if _ffmpeg_dir:
            ydl_opts["ffmpeg_location"] = _ffmpeg_dir



        try:
            self.progress.emit(f"🔗 Đang phân tích URL: {self.url[:80]}...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url, download=True)
                video_path = ydl.prepare_filename(info)
                # Đảm bảo extension là .mp4
                if not video_path.endswith(".mp4"):
                    video_path = str(Path(video_path).with_suffix(".mp4"))

            if not os.path.exists(video_path):
                # Tìm file mp4 mới nhất trong output_dir
                mp4_files = sorted(
                    Path(self.output_dir).glob("*.mp4"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True
                )
                if mp4_files:
                    video_path = str(mp4_files[0])
                else:
                    self.progress.emit("❌ Không tìm thấy file video sau khi tải!")
                    self.finished.emit(False, "", "")
                    return

            self.progress.emit(f"✅ Video: {Path(video_path).name}")

            # Tìm thumbnail đã tải (yt-dlp lưu cùng tên, khác extension)
            thumb_path = ""
            stem = Path(video_path).stem
            for ext in [".jpg", ".jpeg", ".webp", ".png"]:
                candidate = str(Path(self.output_dir) / (stem + ext))
                if os.path.exists(candidate):
                    thumb_path = candidate
                    self.progress.emit(f"🖼️ Thumbnail: {Path(thumb_path).name}")
                    break

            if not thumb_path:
                self.progress.emit("ℹ️ Không tìm thấy thumbnail, sẽ dùng frame đầu video.")

            self.finished.emit(True, video_path, thumb_path)

        except Exception as e:
            if self._cancelled:
                self.progress.emit("⚠️ Đã huỷ tải video.")
                self.finished.emit(False, "", "")
            else:
                self.progress.emit(f"❌ Lỗi tải video: {e}")
                self.finished.emit(False, "", "")


class ThumbnailDownloaderThread(QThread):
    """
    Background thread chỉ tải thumbnail từ URL (YouTube, TikTok, Facebook, or direct image link) bằng yt-dlp / urllib.
    Signals:
        progress(str)           - cập nhật tiến trình
        finished(bool, str, str)- (success, thumbnail_path, error_message)
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, str)  # success, thumb_path, error_msg

    def __init__(self, url: str, output_dir: str, parent=None):
        super().__init__(parent)
        self.url = url.strip()
        self.output_dir = output_dir
        self._cancelled = False

    def stop(self):
        self._cancelled = True

    def run(self):
        url = self.url
        if not url:
            self.finished.emit(False, "", "URL rỗng")
            return

        os.makedirs(self.output_dir, exist_ok=True)
        self.progress.emit("🖼️ Đang lấy thumbnail từ link...")

        # Case 1: Link ảnh trực tiếp (.jpg, .jpeg, .png, .webp)
        url_lower = url.lower()
        if any(ext in url_lower for ext in ['.jpg', '.jpeg', '.png', '.webp']):
            try:
                import urllib.request
                parsed_ext = '.jpg'
                for ext in ['.png', '.webp', '.jpeg']:
                    if ext in url_lower:
                        parsed_ext = ext
                        break
                timestamp = int(time.time())
                out_path = os.path.join(self.output_dir, f"url_thumb_{timestamp}{parsed_ext}")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response, open(out_path, 'wb') as out_file:
                    out_file.write(response.read())
                if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                    self.progress.emit(f"✅ Đã tải thumbnail: {Path(out_path).name}")
                    self.finished.emit(True, out_path, "")
                    return
            except Exception as e:
                print(f"Direct image download failed: {e}")

        # Case 2: Link video (YouTube / TikTok / Facebook...) -> dùng yt-dlp skip download
        try:
            import yt_dlp
            timestamp = int(time.time())
            out_tmpl = str(Path(self.output_dir) / f"url_thumb_{timestamp}")
            ydl_opts = {
                'skip_download': True,
                'writethumbnail': True,
                'outtmpl': out_tmpl,
                'quiet': True,
                'no_warnings': True,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
                }
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.extract_info(url, download=True)

            # Tìm file thumbnail vừa tải
            thumb_path = ""
            for ext in [".jpg", ".jpeg", ".webp", ".png"]:
                candidate = f"{out_tmpl}.{ext}"
                if os.path.exists(candidate):
                    thumb_path = candidate
                    break
            
            if not thumb_path:
                for file in os.listdir(self.output_dir):
                    if file.startswith(f"url_thumb_{timestamp}") and any(file.endswith(e) for e in [".jpg", ".jpeg", ".webp", ".png"]):
                        thumb_path = os.path.join(self.output_dir, file)
                        break

            if thumb_path and os.path.exists(thumb_path):
                self.progress.emit(f"✅ Đã lấy thumbnail: {Path(thumb_path).name}")
                self.finished.emit(True, thumb_path, "")
            else:
                self.progress.emit("❌ Không tìm thấy thumbnail từ link này.")
                self.finished.emit(False, "", "Không tìm thấy thumbnail từ link này")

        except Exception as e:
            if self._cancelled:
                self.progress.emit("⚠️ Đã huỷ lấy thumbnail.")
                self.finished.emit(False, "", "Cancelled")
            else:
                self.progress.emit(f"❌ Lỗi lấy thumbnail: {e}")
                self.finished.emit(False, "", str(e))



# Paths for FFmpeg, FFprobe and Directories
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent))
    EXE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    EXE_DIR = BASE_DIR

def _find_ffmpeg_path():
    for base in [EXE_DIR, BASE_DIR]:
        for cand in [
            base / "ffmpeg" / "bin" / "ffmpeg.exe",
            base / "ffmpeg" / "ffmpeg.exe",
            base / "ffmpeg.exe"
        ]:
            if cand.exists():
                return str(cand)
    import shutil
    w = shutil.which("ffmpeg")
    return w or "ffmpeg.exe"

def _find_ffprobe_path():
    for base in [EXE_DIR, BASE_DIR]:
        for cand in [
            base / "ffmpeg" / "bin" / "ffprobe.exe",
            base / "ffmpeg" / "ffprobe.exe",
            base / "ffprobe.exe"
        ]:
            if cand.exists():
                return str(cand)
    import shutil
    w = shutil.which("ffprobe")
    return w or "ffprobe.exe"

FFMPEG_EXE = _find_ffmpeg_path()
FFPROBE_EXE = _find_ffprobe_path()


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


# Cache for GPU detection result
_gpu_encoder_cache = None

def detect_gpu_encoder():
    """
    Auto-detect available GPU encoder on the system
    Supports: NVIDIA (NVENC), AMD (AMF), Intel (QSV), Apple (VideoToolbox)
    Returns: dict with keys:
        'encoder'     : encoder name (e.g. 'h264_nvenc')
        'preset_args' : list of preset args
        'quality_args': list of quality args
        'hwaccel_args': list of hwaccel decode args (prepended before -i)
        'is_nvidia'   : bool - True if NVIDIA CUDA is available
    Or None if no GPU found.
    """
    global _gpu_encoder_cache
    if _gpu_encoder_cache is not None:
        return _gpu_encoder_cache
    
    try:
        cmd = [FFMPEG_EXE, '-hide_banner', '-encoders']
        result = run_ffmpeg_silent(cmd)
        encoders_output = result.stdout.lower()
        
        # Check in priority order: NVIDIA > AMD > Intel > Apple
        if 'h264_nvenc' in encoders_output:
            # Probe NVENC to verify GPU hardware is actually available and driver is working
            probe_cmd = [FFMPEG_EXE, '-y', '-hide_banner', '-f', 'lavfi', '-i', 'color=s=64x64:d=0.04', '-c:v', 'h264_nvenc', '-f', 'null', '-']
            probe_res = run_ffmpeg_silent(probe_cmd)
            if probe_res.returncode == 0:
                _gpu_encoder_cache = {
                    'encoder':      'h264_nvenc',
                    'preset_args':  ['-preset', 'p4', '-tune', 'hq'],
                    'quality_args': ['-rc', 'vbr', '-cq', '23', '-b:v', '0'],
                    'hwaccel_args': [],
                    'decoder_arg':  [],
                    'is_nvidia':    True,
                }
                return _gpu_encoder_cache
        elif 'h264_amf' in encoders_output:
            _gpu_encoder_cache = {
                'encoder':      'h264_amf',
                'preset_args':  ['-quality', 'speed'],
                'quality_args': ['-rc', 'vbr_hq', '-qp_i', '23', '-qp_p', '23'],
                'hwaccel_args': [],
                'decoder_arg':  [],
                'is_nvidia':    False,
            }
        elif 'h264_qsv' in encoders_output:
            # Dùng CPU decode để tránh lỗi format mismatch
            _gpu_encoder_cache = {
                'encoder':      'h264_qsv',
                'preset_args':  ['-preset', 'fast'],
                'quality_args': ['-global_quality', '23'],
                'hwaccel_args': [],
                'decoder_arg':  [],
                'is_nvidia':    False,
            }
        elif 'h264_videotoolbox' in encoders_output:
            _gpu_encoder_cache = {
                'encoder':      'h264_videotoolbox',
                'preset_args':  ['-profile:v', 'high'],
                'quality_args': ['-b:v', '5M'],
                'hwaccel_args': [],
                'decoder_arg':  [],
                'is_nvidia':    False,
            }
        else:
            _gpu_encoder_cache = None
        
        return _gpu_encoder_cache
        
    except Exception as e:
        print(f"⚠️ Error detecting GPU: {e}")
        return None




# ─────────────────────────────────────────────────────────────────────────────
#  MULTI-METHOD SCENE DETECTION ENGINE
#  Methods: Histogram Diff · SSIM · FFmpeg scdet · Adaptive Threshold · AI/Hybrid
# ─────────────────────────────────────────────────────────────────────────────

def _open_cv2_capture(video_path, start_sec=0.0):
    """Open an OpenCV VideoCapture and seek to start_sec. Returns (cap, fps)."""
    import cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    if start_sec > 0:
        cap.set(cv2.CAP_PROP_POS_MSEC, start_sec * 1000)
    return cap, fps


def _frame_at(cap, fps, target_sec):
    """Seek a VideoCapture to target_sec and read one frame. Returns BGR frame or None."""
    import cv2
    cap.set(cv2.CAP_PROP_POS_MSEC, target_sec * 1000)
    ret, frame = cap.read()
    return frame if ret else None


# ── Method 1: Histogram Difference ───────────────────────────────────────────

def _histogram_diff(prev_frame, curr_frame):
    """
    Compare two BGR frames via HSV histogram correlation.
    Returns dissimilarity score in [0, 1]: 0 = identical, 1 = completely different.
    """
    import cv2
    import numpy as np

    prev_hsv = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2HSV)
    curr_hsv = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2HSV)

    score = 0.0
    weights = [0.5, 0.3, 0.2]  # H, S, V
    for ch, w in enumerate(weights):
        h_prev = cv2.calcHist([prev_hsv], [ch], None, [64], [0, 256])
        h_curr = cv2.calcHist([curr_hsv], [ch], None, [64], [0, 256])
        cv2.normalize(h_prev, h_prev)
        cv2.normalize(h_curr, h_curr)
        corr = cv2.compareHist(h_prev, h_curr, cv2.HISTCMP_CORREL)  # 1=same
        score += w * (1.0 - corr)

    return float(np.clip(score, 0.0, 1.0))


# ── Method 2: SSIM (Structural Similarity) ───────────────────────────────────

def _ssim_diff(prev_frame, curr_frame):
    """
    Compare two BGR frames via SSIM on grayscale.
    Returns dissimilarity score in [0, 1]: 0 = identical, 1 = completely different.
    """
    import cv2
    try:
        from skimage.metrics import structural_similarity as ssim
        g1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        g2 = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY)
        # Resize to 160x90 for speed
        g1 = cv2.resize(g1, (160, 90))
        g2 = cv2.resize(g2, (160, 90))
        score, _ = ssim(g1, g2, full=True)
        return float(1.0 - max(0.0, score))
    except ImportError:
        # Fallback: mean absolute difference of grayscale
        import numpy as np
        g1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY).astype(float)
        g2 = cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY).astype(float)
        return float(np.mean(np.abs(g1 - g2)) / 255.0)


# ── Method 3: FFmpeg scdet (no OpenCV needed) ────────────────────────────────

def _detect_via_ffmpeg_scdet(video_path, start_sec, end_sec, threshold_pct):
    """
    Run FFmpeg with scdet filter and parse timestamps from stderr.
    threshold_pct: 0-100, higher = less sensitive.
    Returns list of absolute timestamps.
    """
    import re
    cmd = [FFMPEG_EXE, '-y']
    if start_sec and start_sec > 0:
        cmd += ['-ss', str(start_sec)]
    cmd += ['-i', video_path]
    if end_sec is not None:
        cmd += ['-t', str(max(0, end_sec - (start_sec or 0)))]
    cmd += ['-vf', f'scdet=threshold={threshold_pct:.1f}', '-f', 'null', '-']

    result = run_ffmpeg_silent(cmd)
    stderr = result.stderr or ''

    pattern = re.compile(r'pts_time[=:]\s*([\d.]+)', re.IGNORECASE)
    timestamps = []
    for m in pattern.finditer(stderr):
        t_rel = float(m.group(1))
        t_abs = t_rel + (start_sec or 0)
        if end_sec is None or t_abs <= end_sec:
            timestamps.append(t_abs)
    return sorted(timestamps)


# ── Adaptive Threshold ────────────────────────────────────────────────────────

def _adaptive_threshold(scores, k=2.0):
    """
    Auto-compute cut threshold = mean + k * std of the score array.
    Falls back to a sensible default if the array is too small.
    """
    import numpy as np
    if len(scores) < 4:
        return 0.35
    arr = np.array(scores, dtype=float)
    return float(np.mean(arr) + k * np.std(arr))


# ── Core OpenCV engine ────────────────────────────────────────────────────────

def _detect_opencv_hybrid(video_path, start_sec=0.0, end_sec=None,
                           sample_every_n_frames=2,
                           hist_weight=0.6, ssim_weight=0.4,
                           adaptive_k=2.0, min_scene_gap=0.5):
    """
    Full hybrid engine: sample video sequentially using cap.grab() for fast skipping
    without seeking, compute weighted (Histogram + SSIM) dissimilarity, then apply adaptive threshold.

    Returns list of absolute cut timestamps in seconds.
    """
    import cv2
    import numpy as np

    cap, fps = _open_cv2_capture(video_path, start_sec)

    frame_count_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    start_frame = int(start_sec * fps)
    end_frame   = int(end_sec * fps) if end_sec is not None else frame_count_total

    # Seek ONCE at the start to avoid decoder corruption warnings
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    scores       = []   # (timestamp, combined_score)
    frame_idx    = start_frame
    prev_frame   = None

    while frame_idx < end_frame:
        ret, frame = cap.read()
        if not ret:
            break

        if prev_frame is not None:
            # Resize for speed
            f1 = cv2.resize(prev_frame, (320, 180))
            f2 = cv2.resize(frame, (320, 180))

            h_score = _histogram_diff(f1, f2) if hist_weight > 0 else 0.0
            s_score = _ssim_diff(f1, f2) if ssim_weight > 0 else 0.0
            combined = hist_weight * h_score + ssim_weight * s_score
            t_abs = frame_idx / fps
            scores.append((t_abs, combined))

        prev_frame = frame
        frame_idx += 1

        # Fast grab() skip n-1 frames without decoding pixel data or seeking
        for _ in range(sample_every_n_frames - 1):
            if frame_idx >= end_frame:
                break
            if not cap.grab():
                break
            frame_idx += 1

    cap.release()

    if not scores:
        return [start_sec]

    # Adaptive threshold
    raw_scores = [s for _, s in scores]
    threshold  = _adaptive_threshold(raw_scores, k=adaptive_k)

    # Pick timestamps above threshold, enforcing min_scene_gap
    cuts = [start_sec]
    last_cut = start_sec
    for t, s in scores:
        if s >= threshold and (t - last_cut) >= min_scene_gap:
            cuts.append(t)
            last_cut = t

    return sorted(set(cuts))



# ── Public API ────────────────────────────────────────────────────────────────

def detect_scene_cuts(video_path, start_time=0, end_time=None,
                      threshold=27.0, method="hybrid"):
    """
    Detect scene cut timestamps using a multi-method hybrid engine.

    Methods:
        "hybrid"     – OpenCV Histogram + SSIM + Adaptive Threshold (best quality)
        "histogram"  – Histogram difference only (fast)
        "ssim"       – SSIM only (accurate but slower)
        "ffmpeg"     – FFmpeg scdet filter (no OpenCV required)
        "pyscene"    – PySceneDetect ContentDetector (original)

    Args:
        video_path  : Path to the source video file.
        start_time  : Analysis window start (seconds). Default 0.
        end_time    : Analysis window end (seconds). None = full video.
        threshold   : Sensitivity control.
                        hybrid/histogram/ssim → adaptive_k (1.0–4.0, default ~2)
                        ffmpeg               → scdet threshold 0–100
                        pyscene              → ContentDetector threshold (default 27)
        method      : Detection strategy (see above).

    Returns:
        Sorted list of floats – absolute scene-start timestamps in seconds.
        Always includes start_time as the first element.
    """
    start_sec = float(start_time) if start_time else 0.0
    end_sec   = float(end_time)   if end_time is not None else None

    try:
        if method == "ffmpeg":
            timestamps = _detect_via_ffmpeg_scdet(
                video_path, start_sec, end_sec,
                threshold_pct=threshold
            )

        elif method == "pyscene":
            from scenedetect import open_video, SceneManager
            from scenedetect.detectors import ContentDetector
            video = open_video(video_path)
            if start_sec > 0:
                video.seek(start_sec)
            sm = SceneManager()
            sm.add_detector(ContentDetector(threshold=threshold))
            sm.detect_scenes(video, end_time=end_sec, show_progress=False)
            timestamps = [s.get_seconds() for s, _ in sm.get_scene_list()]

        elif method in ("histogram", "ssim", "hybrid"):
            # Map threshold param → adaptive_k (user sets 1–4)
            adaptive_k = max(0.5, float(threshold))

            if method == "histogram":
                timestamps = _detect_opencv_hybrid(
                    video_path, start_sec, end_sec,
                    hist_weight=1.0, ssim_weight=0.0,
                    adaptive_k=adaptive_k
                )
            elif method == "ssim":
                timestamps = _detect_opencv_hybrid(
                    video_path, start_sec, end_sec,
                    hist_weight=0.0, ssim_weight=1.0,
                    adaptive_k=adaptive_k,
                    sample_every_n_frames=3
                )
            else:  # hybrid
                timestamps = _detect_opencv_hybrid(
                    video_path, start_sec, end_sec,
                    hist_weight=0.6, ssim_weight=0.4,
                    adaptive_k=adaptive_k
                )
        else:
            raise ValueError(f"Unknown method: {method!r}")

        # Normalise: ensure start is always included, deduplicate, sort
        if not timestamps or timestamps[0] > start_sec + 0.1:
            timestamps.insert(0, start_sec)
        timestamps = sorted(set(round(t, 3) for t in timestamps))
        return timestamps

    except ImportError as e:
        print(f"⚠️ Missing dependency for method='{method}': {e}")
        # Cascade: try ffmpeg scdet as last resort
        try:
            ts = _detect_via_ffmpeg_scdet(video_path, start_sec, end_sec, 40.0)
            if not ts or ts[0] > start_sec + 0.1:
                ts.insert(0, start_sec)
            return sorted(set(round(t, 3) for t in ts))
        except Exception:
            return [start_sec]
    except Exception as e:
        print(f"⚠️ Scene detection error ({method}): {e}")
        return [start_sec]




def get_scene_skip_ranges(scene_timestamps, end_time, delete_percent=30,
                          min_scene_duration=1.5, seed=None):
    """
    Randomly select N% of scenes to delete and return as skip_ranges.

    Args:
        scene_timestamps  : List of scene-start timestamps (seconds).
        end_time          : Absolute end of the video segment (seconds or None).
        delete_percent    : Percentage of scenes to delete (0–90).
        min_scene_duration: Scenes shorter than this value (seconds) are
                            protected and never deleted.
        seed              : Optional int seed for reproducibility.

    Returns:
        Sorted list of (start, end) float tuples – ranges to skip.
    """
    try:
        if not scene_timestamps or delete_percent <= 0:
            return []

        end_val = float(end_time) if end_time is not None else (max(scene_timestamps) + 10.0)
        boundaries = sorted(scene_timestamps) + [end_val]
        scenes = []
        for i in range(len(boundaries) - 1):
            s_start = boundaries[i]
            s_end   = boundaries[i + 1]
            dur     = s_end - s_start
            if dur > 0:
                scenes.append((s_start, s_end, dur))

        if not scenes:
            return []

        # Only scenes that meet the minimum duration are candidates
        deletable = [(s, e, d) for s, e, d in scenes if d >= min_scene_duration]
        if not deletable:
            return []

        # Keep at least 1 scene if possible
        n_delete = max(1, round(len(deletable) * delete_percent / 100))
        n_delete = min(n_delete, max(0, len(deletable) - 1))

        if n_delete <= 0:
            return []

        rng = random.Random(seed)
        to_delete = rng.sample(deletable, n_delete)

        skip_ranges = sorted([(s, e) for s, e, _ in to_delete], key=lambda x: x[0])
        return skip_ranges
    except Exception as e:
        print(f"⚠️ get_scene_skip_ranges error: {e}")
        return []



def format_seconds(seconds):
    """Format seconds into HH:MM:SS.s string."""
    if seconds is None:
        return "N/A"
    try:
        seconds = float(seconds)
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = seconds % 60
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:04.1f}"
        else:
            return f"{mins:02d}:{secs:04.1f}"
    except Exception:
        return str(seconds)


def build_scene_split_log_details(video_path, start_sec, end_sec, method, threshold, delete_pct, min_dur, timestamps, skip_ranges):
    """
    Build a comprehensive multi-line log report of scene split analysis.
    """
    filename = Path(video_path).name
    lines = []
    lines.append("=" * 55)
    lines.append(f"🎬 BẢNG PHÂN TÍCH TÁCH CẢNH (SCENE ANALYSIS REPORT)")
    lines.append("=" * 55)
    lines.append(f"📄 Video: {filename}")
    lines.append(f"⚙️ Phương pháp: {str(method).upper()}")
    lines.append(f"🎛️ Cấu hình: Threshold={threshold} | Xóa ngẫu nhiên={delete_pct}% | Cảnh tối thiểu={min_dur}s")
    lines.append(f"⏱️ Khoảng xử lý: {format_seconds(start_sec)} ➔ {format_seconds(end_sec) if end_sec is not None else 'Đến hết video'}")
    lines.append("-" * 55)

    if not timestamps or len(timestamps) < 1:
        lines.append("⚠️ Không tìm thấy điểm cắt cảnh nào. Giữ nguyên video gốc.")
        lines.append("=" * 55)
        return lines

    end_val = float(end_sec) if end_sec is not None else (max(timestamps) + 1.0)
    boundaries = sorted(timestamps) + [end_val]

    scenes = []
    for i in range(len(boundaries) - 1):
        s_start = boundaries[i]
        s_end   = boundaries[i + 1]
        dur     = s_end - s_start
        if dur > 0:
            scenes.append((i + 1, s_start, s_end, dur))

    lines.append(f"📌 Nhận diện tổng cộng {len(scenes)} cảnh:")
    for idx, s, e, d in scenes:
        lines.append(f"   • Cảnh {idx:02d}: {format_seconds(s)}  ➔  {format_seconds(e)}  (thời lượng: {d:.1f}s)")

    lines.append("-" * 55)
    lines.append("🎲 PHÂN BỔ GIỮ / XÓA CẢNH NGẪU NHIÊN:")

    skip_set = set((round(s, 2), round(e, 2)) for s, e in skip_ranges)

    deleted_count = 0
    kept_count = 0
    total_deleted_sec = 0.0

    for idx, s, e, d in scenes:
        is_deleted = any(abs(s - ks) < 0.2 and abs(e - ke) < 0.2 for ks, ke in skip_set)
        if is_deleted:
            deleted_count += 1
            total_deleted_sec += d
            lines.append(f"   ❌ [XÓA] Cảnh {idx:02d}: {format_seconds(s)}  ➔  {format_seconds(e)}  ({d:.1f}s)")
        else:
            kept_count += 1
            lines.append(f"   ✅ [GIỮ] Cảnh {idx:02d}: {format_seconds(s)}  ➔  {format_seconds(e)}  ({d:.1f}s)")

    total_orig_duration = sum(d for _, _, _, d in scenes)
    final_duration = max(0.0, total_orig_duration - total_deleted_sec)

    lines.append("-" * 55)
    lines.append("📊 TỔNG KẾT PHÂN TÍCH:")
    lines.append(f"   • Tổng số cảnh: {len(scenes)}")
    lines.append(f"   • Cảnh được GIỮ: {kept_count}")
    lines.append(f"   • Cảnh ngẫu nhiên bị XÓA: {deleted_count}")
    lines.append(f"   • Tổng thời lượng đã cắt giảm: {total_deleted_sec:.1f} giây")
    lines.append(f"   • Thời lượng còn lại sau tách cảnh: {format_seconds(final_duration)}")
    lines.append("=" * 55)

    return lines


class SceneAnalysisThread(QThread):
    """Background worker thread for scene detection analysis to keep UI smooth and non-blocking."""
    log_msg = pyqtSignal(str)
    analysis_finished = pyqtSignal(list, list, int, int, float, str, list)  # timestamps, skip_ranges, n_scenes, n_deleted, total_deleted_sec, error_msg, report_lines

    def __init__(self, video_path, start_sec, end_sec, threshold, delete_pct, min_dur, method="hybrid", seed=42):
        super().__init__()
        self.video_path = video_path
        self.start_sec = start_sec
        self.end_sec = end_sec
        self.threshold = threshold
        self.delete_pct = delete_pct
        self.min_dur = min_dur
        self.method = method
        self.seed = seed

    def run(self):
        try:
            self.log_msg.emit(f"🎬 Bắt đầu phân tích tách cảnh cho {Path(self.video_path).name} (Thuật toán: {str(self.method).upper()})...")
            timestamps = detect_scene_cuts(
                self.video_path,
                start_time=self.start_sec,
                end_time=self.end_sec,
                threshold=self.threshold,
                method=self.method
            )
            n_scenes = max(0, len(timestamps) - 1) if len(timestamps) > 1 else len(timestamps)

            skip_ranges = get_scene_skip_ranges(
                timestamps,
                end_time=self.end_sec,
                delete_percent=self.delete_pct,
                min_scene_duration=self.min_dur,
                seed=self.seed
            )

            total_deleted_sec = sum(e - s for s, e in skip_ranges)
            n_deleted = len(skip_ranges)

            report_lines = build_scene_split_log_details(
                self.video_path, self.start_sec, self.end_sec,
                self.method, self.threshold, self.delete_pct, self.min_dur,
                timestamps, skip_ranges
            )

            self.analysis_finished.emit(timestamps, skip_ranges, n_scenes, n_deleted, total_deleted_sec, "", report_lines)
        except Exception as e:
            self.analysis_finished.emit([], [], 0, 0, 0.0, str(e), [])



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
        self.subtitle_config = kwargs.get('subtitle_config', None)
        self.subtitle_file = kwargs.get('subtitle_file', None)
        self.subtitle_font_size = kwargs.get('subtitle_font_size', 40)
        self.subtitle_y_position = kwargs.get('subtitle_y_position', 1400)
        self.scene_params = kwargs.get('scene_params', None)
        self.enable_fade_transition = kwargs.get('enable_fade_transition', True)
        self.fade_duration = kwargs.get('fade_duration', 0.3)
        # Thumbnail background
        self.use_video_thumbnail = kwargs.get('use_video_thumbnail', False)
        self.source_thumbnail_path = kwargs.get('source_thumbnail_path', '')
        self.thumb_part_font_size = kwargs.get('thumb_part_font_size', 130)

        
        self._gpu_info = None # Cache for GPU detection
        self.is_cancelled = False  # Flag for cancellation
        
    def stop(self):
        """Stop the processing thread"""
        self.is_cancelled = True
        
    def create_overlay_image(self, title_text, part_text, output_path, **kwargs):
        """Create full-frame overlay image (1080x1920) with Title, Part, and optional Subtitle preview"""
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

        # Draw dummy subtitle sample ("Lorem ipsum dolor sit amet") if provided
        sub_text = kwargs.get('subtitle_preview_text', None)
        if sub_text:
            sub_margin_v = kwargs.get('subtitle_margin_v', 120)
            sub_font_size = kwargs.get('subtitle_font_size', 72)
            sub_font_name = kwargs.get('subtitle_font_name', 'Arial')
            sub_color = kwargs.get('subtitle_color', (255, 255, 255))
            sub_outline = kwargs.get('subtitle_outline', 3)

            try:
                if sub_font_name and os.path.exists(sub_font_name):
                    sub_font = ImageFont.truetype(sub_font_name, sub_font_size)
                else:
                    sub_font = ImageFont.truetype(f"{sub_font_name}.ttf", sub_font_size)
            except Exception:
                try:
                    sub_font = ImageFont.truetype("arial.ttf", sub_font_size)
                except Exception:
                    sub_font = ImageFont.load_default()

            if hasattr(draw, 'multiline_textbbox'):
                bbox = draw.multiline_textbbox((0, 0), sub_text, font=sub_font)
                sw = bbox[2] - bbox[0]
                sh = bbox[3] - bbox[1]
                sox, soy = bbox[0], bbox[1]
            else:
                sw, sh = draw.textsize(sub_text, font=sub_font)
                sox, soy = 0, 0

            # Y position centered above margin_v from bottom (1920)
            sub_y = canvas_height - sub_margin_v - sh
            sub_x = (canvas_width - sw) // 2

            # Draw black border / shadow outline
            outline_px = int(round(sub_outline))
            if outline_px > 0:
                for dx in range(-outline_px, outline_px + 1):
                    for dy in range(-outline_px, outline_px + 1):
                        if abs(dx) == outline_px or abs(dy) == outline_px:
                            draw.text(
                                (sub_x + dx - sox, sub_y + dy - soy),
                                sub_text,
                                font=sub_font,
                                fill=(0, 0, 0, 255)
                            )

            # Draw main text (white / custom color)
            fill_rgba = (sub_color[0], sub_color[1], sub_color[2], 255) if len(sub_color)==3 else sub_color
            draw.text(
                (sub_x - sox, sub_y - soy),
                sub_text,
                font=sub_font,
                fill=fill_rgba
            )
        
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
            # Khi dùng thumbnail: tạo canvas trong suốt (sẽ được thay thế sau khi có thumbnail portrait)
            self.create_overlay_image(self.title_text, default_part_text, title_path)
            
            self.progress.emit("📊 Đang lấy thông tin video...")
            total_duration = self.get_video_duration(self.input_video)
            
            video_width, video_height = self.get_video_dimensions(self.input_video)
            self.original_video_width = video_width
            self.original_video_height = video_height

            # ── Chuẩn bị thumbnail portrait (từ URL hoặc frame 0 video) ──────────────
            thumb_portrait_path = fetch_or_extract_thumbnail(
                getattr(self, 'source_thumbnail_path', ''),
                self.input_video,
                self.output_dir,
                progress_callback=self.progress.emit
            )

            # If scene_params provided, run scene detection in this background thread
            if hasattr(self, 'scene_params') and self.scene_params and self.scene_params.get("delete_pct", 0) > 0:
                sp = self.scene_params
                method_name = sp.get("method", "hybrid")
                self.progress.emit(f"🎬 Đang phân tích tách cảnh cho {Path(self.input_video).name} ({method_name.upper()})...")
                try:
                    scene_timestamps = detect_scene_cuts(
                        self.input_video,
                        start_time=self.start_time,
                        end_time=self.end_time,
                        threshold=sp.get("threshold", 2.0),
                        method=method_name
                    )
                    scene_skips = get_scene_skip_ranges(
                        scene_timestamps,
                        end_time=self.end_time,
                        delete_percent=sp.get("delete_pct", 30),
                        min_scene_duration=sp.get("min_dur", 1.5),
                        seed=42
                    )
                    report_lines = build_scene_split_log_details(
                        self.input_video, self.start_time, self.end_time,
                        method_name, sp.get("threshold", 2.0),
                        sp.get("delete_pct", 30), sp.get("min_dur", 1.5),
                        scene_timestamps, scene_skips
                    )
                    for line in report_lines:
                        self.progress.emit(line)

                    # Merge scene skips into self.skip_ranges
                    self.skip_ranges = sorted(self.skip_ranges + scene_skips, key=lambda x: x[0])
                except Exception as e:
                    self.progress.emit(f"⚠️ Lỗi tách cảnh (bỏ qua): {e}")

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
                
                # (thumb_portrait_path đã được chuẩn bị ở trên, không cần fetch lại)

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

                    # ── Xuất file ảnh bìa Thumbnail (.jpg) và chèn vào đầu video ──
                    if thumb_portrait_path and os.path.exists(thumb_portrait_path):
                        part_display_text = f"{self.part_suffix} {segment_num}" if self.show_part else ""
                        output_thumb_file = os.path.splitext(output_file)[0] + ".jpg"
                        ok_t = create_thumbnail_with_part_overlay(
                            thumb_portrait_path,
                            full_title,
                            part_display_text,
                            output_thumb_file,
                            font_path=self.font_path or "",
                            text_color=self.text_color,
                            border_color=self.text_border_color,
                            border_width=max(4, self.text_border_width) if self.text_border_width > 0 else 5,
                            title_y=self.title_y if self.title_y > 0 else 250,
                            part_y=self.part_y if self.part_y > 0 else -1,
                            title_font_size=80,
                            part_font_size=self.thumb_part_font_size,
                        )
                        if ok_t:
                            # Chèn thumbnail làm frame đầu tiên của video output
                            if prepend_thumbnail_frame_to_video(output_file, output_thumb_file):
                                self.progress.emit(f"🖼️ Đã chèn thumbnail làm frame đầu: {Path(output_file).name}")
                            # Nhúng thumbnail làm cover image cho file MP4 (hiển thị trên Windows Explorer)
                            if embed_thumbnail_to_mp4(output_file, output_thumb_file):
                                self.progress.emit(f"📌 Đã nhúng thumbnail vào video: {Path(output_file).name}")
                            # Xóa file .jpg tạm
                            try:
                                if os.path.exists(output_thumb_file):
                                    os.remove(output_thumb_file)
                            except Exception:
                                pass
                    
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

                default_part_text = f"{self.part_suffix} 1" if self.show_part else ""
                self.create_overlay_image(self.title_text, default_part_text, title_path)

                self.create_segment_from_ranges(
                    time_ranges,
                    0,
                    work_duration,
                    title_path,
                    output_file,
                    video_width,
                    video_height
                )

                # ── Xuất file ảnh bìa Thumbnail (.jpg) và chèn vào đầu video ──
                if thumb_portrait_path and os.path.exists(thumb_portrait_path):
                    part_display_text = f"{self.part_suffix} 1" if self.show_part else ""
                    output_thumb_file = os.path.splitext(output_file)[0] + ".jpg"
                    ok_t = create_thumbnail_with_part_overlay(
                        thumb_portrait_path,
                        self.title_text,
                        part_display_text,
                        output_thumb_file,
                        font_path=self.font_path or "",
                        text_color=self.text_color,
                        border_color=self.text_border_color,
                        border_width=max(4, self.text_border_width) if self.text_border_width > 0 else 5,
                        title_y=self.title_y if self.title_y > 0 else 250,
                        part_y=self.part_y if self.part_y > 0 else -1,
                        title_font_size=80,
                        part_font_size=self.thumb_part_font_size,
                    )
                    if ok_t:
                        # Chèn thumbnail làm frame đầu tiên của video output
                        if prepend_thumbnail_frame_to_video(output_file, output_thumb_file):
                            self.progress.emit(f"🖼️ Đã chèn thumbnail làm frame đầu: {Path(output_file).name}")
                        # Nhúng thumbnail làm cover image cho file MP4 (hiển thị trên Windows Explorer)
                        if embed_thumbnail_to_mp4(output_file, output_thumb_file):
                            self.progress.emit(f"📌 Đã nhúng thumbnail vào video: {Path(output_file).name}")
                        # Xóa file .jpg tạm
                        try:
                            if os.path.exists(output_thumb_file):
                                os.remove(output_thumb_file)
                        except Exception:
                            pass
                
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
                    os.path.join(self.output_dir, "_thumb_*.png"),
                    os.path.join(self.output_dir, "_thumb_*.jpg"),
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
    
    def render_and_burn_final(self, input_clip, title_image, output_file, video_width, video_height):
        """
        Render final segment video.
        If subtitle_config is enabled:
        1. Transcribe assembled cut segment audio (input_clip) at 1.0x speed for maximum Whisper accuracy.
        2. Scale word timestamps by 1 / self.speed so subtitle timing matches speed-adjusted speech.
        3. Generate segment ASS file.
        4. Render final video with speed (setpts/atempo), overlays, and burn-in subtitle in a single FFmpeg pass.
        """
        sub_cfg = getattr(self, 'subtitle_config', None)
        ass_path = None

        if sub_cfg and getattr(sub_cfg, 'enabled', False):
            try:
                self.progress.emit(f"🎙 Đang nhận diện lời nói cho {Path(output_file).name}...")
                word_segments = transcribe_audio(
                    input_clip,
                    model_size=sub_cfg.model_size,
                    beam_size=getattr(sub_cfg, 'beam_size', 5),
                    initial_prompt=getattr(sub_cfg, 'initial_prompt', ''),
                    progress_callback=lambda msg: self.progress.emit(msg)
                )

                if word_segments:
                    # Scale timestamps to match adjusted speed (1 / self.speed)
                    eff_speed = self.speed if (hasattr(self, 'speed') and self.speed > 0) else 1.0
                    if eff_speed != 1.0:
                        self.progress.emit(f"⚡ Điều chỉnh tốc độ subtitle theo tốc độ video ({eff_speed}x)...")
                        for w in word_segments:
                            w["start"] = round(w["start"] / eff_speed, 3)
                            w["end"] = round(w["end"] / eff_speed, 3)

                    blocks = build_subtitle_blocks(word_segments, sub_cfg)
                    ass_path = output_file + ".ass"
                    generate_ass_file(blocks, ass_path, sub_cfg, video_width=1080, video_height=1920)

                    self.subtitle_file = ass_path
                    self.progress.emit(f"🔥 Đang dựng video & chèn subtitle (tốc độ {eff_speed}x)...")
                else:
                    self.progress.emit(f"ℹ️ Không thấy lời nói trong {Path(output_file).name}.")
                    self.subtitle_file = None

            except Exception as e:
                self.progress.emit(f"⚠️ Lỗi tạo subtitle ({e}), dựng video không subtitle.")
                self.subtitle_file = None

        try:
            self.process_final_video(input_clip, title_image, output_file, video_width, video_height)
        finally:
            if ass_path and os.path.exists(ass_path):
                try:
                    os.remove(ass_path)
                except Exception:
                    pass
            self.subtitle_file = None


    def create_segment_from_ranges(self, time_ranges, start_offset, duration_needed, 
                                   title_image, output_file, video_width, video_height):
        """Create segment from multiple time ranges"""
        temp_clips = []
        remaining_duration = duration_needed
        
        temp_clips = []
        remaining_duration = duration_needed
        
        fade_dur = self.fade_duration if (hasattr(self, 'enable_fade_transition') and self.enable_fade_transition) else 0.0

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
            self.extract_clip(clip_start, clip_duration, temp_clip, fade_duration=fade_dur)
            temp_clips.append(temp_clip)
            
            remaining_duration -= clip_duration
            start_offset = 0
        
        if len(temp_clips) == 1:
            self.render_and_burn_final(temp_clips[0], title_image, output_file, video_width, video_height)
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
            
            self.render_and_burn_final(merged_clip, title_image, output_file, video_width, video_height)

            
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
    
    def extract_clip(self, start_time, duration, output_path, fade_duration=0.0):
        """Extract a clip from the original video with optional smooth Fade In/Out transition"""
        if fade_duration > 0 and duration > (fade_duration * 2):
            st_out = max(0.0, duration - fade_duration)
            vf = f"fade=t=in:st=0:d={fade_duration:.2f},fade=t=out:st={st_out:.2f}:d={fade_duration:.2f}"
            af = f"afade=t=in:st=0:d={fade_duration:.2f},afade=t=out:st={st_out:.2f}:d={fade_duration:.2f}"
            cmd = [
                FFMPEG_EXE, '-y',
                '-ss', str(start_time),
                '-i', self.input_video,
                '-t', str(duration),
                '-vf', vf,
                '-af', af,
                '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '20',
                '-c:a', 'aac',
                output_path
            ]
        else:
            cmd = [
                FFMPEG_EXE, '-y',
                '-ss', str(start_time),
                '-i', self.input_video,
                '-t', str(duration),
                '-c', 'copy',
                output_path
            ]
        run_ffmpeg_silent(cmd)
    
    @staticmethod
    def _build_subtitle_filter(subtitle_file: str, subtitle_font_size: int = 40,
                               subtitle_y_position: int = 1400,
                               video_height: int = 1920) -> str:
        """
        Build the FFmpeg subtitle filter string for a given subtitle file.

        Supports both ASS files (native style embedded, no force_style) and
        SRT/VTT files (force_style with sensible defaults).

        Args:
            subtitle_file:      Absolute path to the subtitle file.
            subtitle_font_size: Font size used only for SRT/VTT force_style.
            subtitle_y_position: Y position (px) for SRT/VTT (MarginV = height - y).
            video_height:       Video height in pixels.

        Returns:
            FFmpeg filter fragment string, e.g.
            "subtitles='D\\:/path/to/file.ass'" or
            "subtitles='D\\:/path/to/file.srt':force_style='...'".
        """
        # Normalise path: forward slashes, escape colon for Windows drive letter
        norm = subtitle_file.replace('\\', '/')
        # Escape colon(s) — only the drive-letter colon on Windows
        escaped = norm.replace(':', '\\:')

        ext = Path(subtitle_file).suffix.lower()
        if ext == '.ass':
            # ASS has embedded styles — do NOT use force_style to avoid overriding them
            return f"subtitles='{escaped}'"
        else:
            # SRT / VTT — inject minimal force_style
            margin_v = max(0, video_height - subtitle_y_position)
            style = (
                f"FontSize={subtitle_font_size},"
                f"Alignment=2,"
                f"MarginV={margin_v},"
                f"PrimaryColour=&HFFFFFF,"
                f"OutlineColour=&H000000,"
                f"Outline=2,"
                f"Shadow=1,"
                f"BorderStyle=1"
            )
            return f"subtitles='{escaped}':force_style='{style}'"

    def process_final_video(self, input_clip, title_image, output_file, video_width, video_height):
        """Process final video with overlay and speed"""
        hwaccel_args = []
        decoder_arg  = []

        if self.use_gpu:
            if self._gpu_info is None:
                self._gpu_info = detect_gpu_encoder()

            if self._gpu_info:
                gpu          = self._gpu_info
                encoder_name = gpu['encoder']
                preset_args  = gpu['preset_args']
                quality_args = gpu['quality_args']
                hwaccel_args = gpu.get('hwaccel_args', [])
                decoder_arg  = gpu.get('decoder_arg', [])
                video_codec  = ['-c:v', encoder_name] + preset_args + quality_args

                hw_desc = ' '.join(hwaccel_args + decoder_arg) or 'CPU decode'
                self.progress.emit(f"🎮 GPU: {hw_desc} → encode={encoder_name} preset={preset_args[1] if len(preset_args)>1 else '-'}")
            else:
                video_codec = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20']
                self.progress.emit("⚠️ Không tìm thấy GPU encoder, dùng CPU (libx264)")
        else:
            video_codec = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20']
        
        bg_hex = f"0x{self.bg_color[0]:02x}{self.bg_color[1]:02x}{self.bg_color[2]:02x}"
        is_audio_only = (video_width == 0 or video_height == 0)
        # Thumbnail chỉ dùng cho ảnh bìa (.jpg), video (.mp4) luôn dựng theo setting ban đầu
        use_thumb_as_bg = False

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
            if use_thumb_as_bg:
                # Thumbnail là background, overlay text+video lên
                if self.speed != 1.0:
                    filter_complex = (
                        f"[1:v]loop=loop=-1:size=1:start=0,setpts=N/FRAME_RATE/TB,scale=1080:1920:flags=lanczos[bg];"
                        f"[bg][0:a];"
                        f"[0:a]atempo={self.speed}[audio]"
                    )
                    audio_map = ['-map', '[audio]']
                else:
                    filter_complex = (
                        f"[1:v]loop=loop=-1:size=1:start=0,setpts=N/FRAME_RATE/TB,scale=1080:1920:flags=lanczos[bg]"
                    )
                    audio_map = ['-map', '0:a?']
                filter_complex += ";[bg]null[video_with_title]"
            else:
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
                sub_filter = self._build_subtitle_filter(
                    self.subtitle_file, self.subtitle_font_size,
                    self.subtitle_y_position, video_height
                )
                filter_complex += f";[video_with_title]{sub_filter}[out]"
            else:
                filter_complex += ";[video_with_title]null[out]"
                
        elif self.speed != 1.0:
            if use_thumb_as_bg:
                # Thumbnail là background, video overlay lên
                filter_complex = (
                    f"[0:v]setpts={1/self.speed}*PTS,"
                    f"scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"[1:v]loop=loop=-1:size=1:start=0,setpts=N/FRAME_RATE/TB,scale=1080:1920:flags=lanczos[bg];"
                    f"[bg][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[video_with_title];"
                )
            elif self.blur_background:
                filter_complex = (
                    f"[0:v]split=2[fg_source][bg_source];"
                    f"[bg_source]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur={eff_blur}:3,scale=1080:1920[bg_blurred];"
                    f"[fg_source]setpts={1/self.speed}*PTS,scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"[bg_blurred][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[base];"
                )
                if hasattr(self, 'overlay_opacity') and self.overlay_opacity > 0:
                    alpha = self.overlay_opacity / 100.0
                    overlay_hex = f"0x{self.overlay_color[0]:02x}{self.overlay_color[1]:02x}{self.overlay_color[2]:02x}"
                    filter_complex += f"[base]drawbox=x=0:y=0:w=1080:h=1920:color={overlay_hex}@{alpha}:t=fill[base_with_overlay];"
                    filter_complex += f"[base_with_overlay][1:v]overlay=0:0[video_with_title];"
                else:
                    filter_complex += f"[base][1:v]overlay=0:0[video_with_title];"
            else:
                filter_complex = (
                    f"[0:v]setpts={1/self.speed}*PTS,"
                    f"scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"color=c={bg_hex}:s=1080x1920[bg];"
                    f"[bg][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[base];"
                )
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
                sub_filter = self._build_subtitle_filter(
                    self.subtitle_file, self.subtitle_font_size,
                    self.subtitle_y_position, video_height
                )
                filter_complex += f";[video_with_title]{sub_filter}[out]"
            else:
                filter_complex += ";[video_with_title]null[out]"
                
            audio_map = ['-map', '[audio]']
        else:
            if use_thumb_as_bg:
                # Thumbnail là background, video overlay lên
                filter_complex = (
                    f"[0:v]scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"[1:v]loop=loop=-1:size=1:start=0,setpts=N/FRAME_RATE/TB,scale=1080:1920:flags=lanczos[bg];"
                    f"[bg][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[video_with_title]"
                )
            elif self.blur_background:
                filter_complex = (
                    f"[0:v]split=2[fg_source][bg_source];"
                    f"[bg_source]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur={eff_blur}:3,scale=1080:1920[bg_blurred];"
                    f"[fg_source]scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"[bg_blurred][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[base];"
                )
                if hasattr(self, 'overlay_opacity') and self.overlay_opacity > 0:
                    alpha = self.overlay_opacity / 100.0
                    overlay_hex = f"0x{self.overlay_color[0]:02x}{self.overlay_color[1]:02x}{self.overlay_color[2]:02x}"
                    filter_complex += f"[base]drawbox=x=0:y=0:w=1080:h=1920:color={overlay_hex}@{alpha}:t=fill[base_with_overlay];"
                    filter_complex += f"[base_with_overlay][1:v]overlay=0:0[video_with_title]"
                else:
                    filter_complex += f"[base][1:v]overlay=0:0[video_with_title]"
            else:
                filter_complex = (
                    f"[0:v]scale={scaled_width}:{scaled_height}:flags=lanczos[scaled];"
                    f"color=c={bg_hex}:s=1080x1920[bg];"
                    f"[bg][scaled]overlay={overlay_x}:{overlay_y}:shortest=1[base];"
                )
                if hasattr(self, 'overlay_opacity') and self.overlay_opacity > 0:
                    alpha = self.overlay_opacity / 100.0
                    overlay_hex = f"0x{self.overlay_color[0]:02x}{self.overlay_color[1]:02x}{self.overlay_color[2]:02x}"
                    filter_complex += f"[base]drawbox=x=0:y=0:w=1080:h=1920:color={overlay_hex}@{alpha}:t=fill[base_with_overlay];"
                    filter_complex += f"[base_with_overlay][1:v]overlay=0:0[video_with_title]"
                else:
                    filter_complex += f"[base][1:v]overlay=0:0[video_with_title]"
                
            # Add subtitle filter if subtitle file exists
            if not use_thumb_as_bg:
                if self.subtitle_file and os.path.exists(self.subtitle_file):
                    sub_filter = self._build_subtitle_filter(
                        self.subtitle_file, self.subtitle_font_size,
                        self.subtitle_y_position, video_height
                    )
                    filter_complex += f";[video_with_title]{sub_filter}[out]"
                else:
                    filter_complex += ";[video_with_title]null[out]"
            else:
                if self.subtitle_file and os.path.exists(self.subtitle_file):
                    sub_filter = self._build_subtitle_filter(
                        self.subtitle_file, self.subtitle_font_size,
                        self.subtitle_y_position, video_height
                    )
                    filter_complex += f";[video_with_title]{sub_filter}[out]"
                else:
                    filter_complex += ";[video_with_title]null[out]"
                    
            audio_map = ['-map', '0:a?']


        def _build_cmd(use_hwaccel):
            """Build FFmpeg command with correct arg order:
            ffmpeg -y [hwaccel_args] [decoder_arg] -i video -i image ...
            """
            c = [FFMPEG_EXE, '-y']
            if use_hwaccel and hwaccel_args:
                c.extend(hwaccel_args)   # -vsync 0 -hwaccel cuvid
                c.extend(decoder_arg)    # -c:v h264_cuvid  (TRƯỚC -i)
            c.extend(['-i', input_clip,
                       '-i', title_image,
                       '-filter_complex', filter_complex,
                       '-map', '[out]'])
            c.extend(audio_map)
            c.extend(video_codec)
            c.extend(['-c:a', 'aac', '-b:a', '192k',
                      '-movflags', '+faststart', '-pix_fmt', 'yuv420p'])
            if is_audio_only:
                c.append('-shortest')
            c.append(output_file)
            return c

        self.progress.emit(f"🔄 Đang xử lý: {output_file}")

        # --- Lần 1: GPU encode (CPU decode + GPU NVENC/AMF/QSV/VT encode) ---
        cmd = _build_cmd(use_hwaccel=False)
        cmd_preview = ' '.join(str(a) for a in cmd[:16])
        self.progress.emit(f"🐛 CMD: {cmd_preview} ...")
        result = run_ffmpeg_silent(cmd)

        # --- Nếu fail và đang dùng GPU encode, tự fallback về full CPU decode + CPU encode (libx264) ---
        is_gpu_codec = self.use_gpu and self._gpu_info is not None
        if result.returncode != 0 and is_gpu_codec:
            stderr_short = '\n'.join(result.stderr.strip().splitlines()[-6:])
            self.progress.emit(f"⚠️ GPU encode lỗi (code {result.returncode}), fallback CPU encode (libx264)...")
            self.progress.emit(f"   Lỗi: {stderr_short}")

            # Fallback: CPU decode + CPU encode (libx264)
            cpu_video_codec = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20']
            cmd_fallback = [FFMPEG_EXE, '-y',
                            '-i', input_clip, '-i', title_image,
                            '-filter_complex', filter_complex, '-map', '[out]']
            cmd_fallback.extend(audio_map)
            cmd_fallback.extend(cpu_video_codec)
            cmd_fallback.extend(['-c:a', 'aac', '-b:a', '192k',
                                  '-movflags', '+faststart', '-pix_fmt', 'yuv420p'])
            if is_audio_only:
                cmd_fallback.append('-shortest')
            cmd_fallback.append(output_file)

            self.progress.emit(f"🔄 Fallback CMD (CPU decode + CPU encode)...")
            result = run_ffmpeg_silent(cmd_fallback)

        # --- Kiểm tra kết quả cuối ---
        if result.returncode != 0:
            stderr_lines = result.stderr.strip().splitlines() if result.stderr else []
            # Hiển thị toàn bộ stderr để debug
            self.progress.emit(f"❌ FFmpeg thất bại (code {result.returncode}):")
            for line in stderr_lines[-20:]:
                self.progress.emit(f"   {line}")
            raise RuntimeError(
                f"FFmpeg failed code={result.returncode}\n"
                + '\n'.join(stderr_lines[-15:])
            )
        
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
