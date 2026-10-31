"""
core/capcut_preprocessor.py
---------------------------
Core processor for detecting, restoring, and converting CapCut pre-processed video files.

Handles:
1. CapCut pre-processed compound clips (XOR-obfuscated media, typically key 0xA5).
2. Missing / unfinalized / fragmented moov atom MP4 files.
3. Standard video files needing faststart optimization or remuxing.
4. Lossless stream copy (c copy) to preserve 100% original video/audio quality.
5. High-performance chunked byte translation with Python's C-accelerated translate().
6. GPU Hardware Acceleration: NVENC (NVIDIA), Intel QSV, AMD AMF with CPU fallback.

Technology Stack:
- FFmpeg làm engine xử lý video chuyên dụng.
- H.264 / libx264 (CPU) | h264_nvenc (NVIDIA) | h264_qsv (Intel) | h264_amf (AMD).
- AAC audio codec (320kbps, 48000 Hz) chuẩn hóa âm thanh.
- MP4 / ISO Base Media File Format (-f mp4) làm container đầu ra tiêu chuẩn.
- -movflags +faststart tối ưu hóa khả năng phát trực tuyến / streaming mượt mà.
- Ưu tiên Remux (-c copy lossless) giữ nguyên 100% chất lượng gốc khi có thể.
- Hỗ trợ Batch Processing / Queue và GPU Hardware Acceleration (NVENC, Intel QSV, AMD AMF) khi cần.
"""

import os
import sys
import json
import struct
import time
import uuid
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

# ─────────────────────────────────────────────────────────────────────────────
# Video Extensions & Constants
# ─────────────────────────────────────────────────────────────────────────────

VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v",
    ".ts", ".mts", ".m2ts", ".flv", ".wmv", ".3gp"
}

# Pre-computed translation tables for common XOR keys (0xA5 is standard CapCut)
XOR_KEY_CAPCUT = 0xA5
XOR_TABLE_CAPCUT = bytes([i ^ XOR_KEY_CAPCUT for i in range(256)])

# Windows flag to suppress console popup window
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# GPU Encoder options (in priority order)
GPU_ENCODERS = [
    ("h264_nvenc",  "NVIDIA NVENC"),
    ("h264_qsv",    "Intel QSV"),
    ("h264_amf",    "AMD AMF"),
]


# ─────────────────────────────────────────────────────────────────────────────
# GPU Hardware Acceleration Detection
# ─────────────────────────────────────────────────────────────────────────────

_gpu_encoder_cache: Optional[Tuple[str, str]] = None  # (encoder_id, display_name)
_gpu_cache_checked: bool = False


def detect_gpu_encoder(
    ffmpeg_bin: str,
    log_callback: Optional[Callable[[str], None]] = None
) -> Optional[Tuple[str, str]]:
    """
    Probe available GPU hardware encoders by attempting a 1-frame encode test.
    Returns (encoder_id, display_name) for the first working encoder, or None (CPU only).
    Results are cached globally after first detection.
    """
    global _gpu_encoder_cache, _gpu_cache_checked
    if _gpu_cache_checked:
        return _gpu_encoder_cache

    _gpu_cache_checked = True

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    for enc_id, enc_name in GPU_ENCODERS:
        try:
            cmd = [
                ffmpeg_bin, "-y",
                "-f", "lavfi", "-i", "color=black:s=64x64:r=1",
                "-vframes", "1",
                "-c:v", enc_id,
                "-f", "null", "-"
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW, timeout=8
            )
            if r.returncode == 0:
                _log(f"✅ GPU phát hiện thành công: {enc_name} ({enc_id})")
                _gpu_encoder_cache = (enc_id, enc_name)
                return _gpu_encoder_cache
        except Exception:
            pass

    _log("ℹ️ Không phát hiện GPU encoder, sử dụng CPU libx264.")
    _gpu_encoder_cache = None
    return None


def reset_gpu_cache():
    """Reset GPU detection cache (call after hardware change or settings reset)."""
    global _gpu_encoder_cache, _gpu_cache_checked
    _gpu_encoder_cache = None
    _gpu_cache_checked = False


# ─────────────────────────────────────────────────────────────────────────────
# FFmpeg & FFprobe Resolution
# ─────────────────────────────────────────────────────────────────────────────

def find_ffmpeg() -> str:
    """Find local or system ffmpeg binary."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    candidates = [
        os.path.join(base_dir, "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(base_dir, "ffmpeg", "ffmpeg.exe"),
        os.path.join(base_dir, "ffmpeg.exe"),
        "ffmpeg.exe",
        "ffmpeg"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "ffmpeg"


def find_ffprobe() -> str:
    """Find local or system ffprobe binary."""
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    candidates = [
        os.path.join(base_dir, "ffmpeg", "bin", "ffprobe.exe"),
        os.path.join(base_dir, "ffmpeg", "ffprobe.exe"),
        os.path.join(base_dir, "ffprobe.exe"),
        "ffprobe.exe",
        "ffprobe"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "ffprobe"


# ─────────────────────────────────────────────────────────────────────────────
# Format Formatting Helpers
# ─────────────────────────────────────────────────────────────────────────────

def format_size(size_bytes: int) -> str:
    """Format bytes to human readable string (KB, MB, GB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def format_duration(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds < 0:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ─────────────────────────────────────────────────────────────────────────────
# Detection Engine
# ─────────────────────────────────────────────────────────────────────────────

def detect_video_file(file_path: str) -> Dict[str, Any]:
    """
    Examines file header and container structure to determine whether it is:
    - CapCut Pre-processed XOR (key 0xA5 or other key)
    - Standard MP4 / QuickTime / other video
    - Corrupted / Fragmented
    """
    path = Path(file_path)
    if not path.is_file():
        return {
            "file_path": str(path),
            "file_name": path.name,
            "exists": False,
            "size_bytes": 0,
            "size_str": "0 B",
            "type": "not_found",
            "is_capcut": False,
            "xor_key": None,
            "status_text": "Không tìm thấy file",
            "badge_color": "#EF4444",
            "needs_restoration": False,
        }

    size_bytes = path.stat().st_size
    size_str = format_size(size_bytes)

    if size_bytes < 16:
        return {
            "file_path": str(path),
            "file_name": path.name,
            "exists": True,
            "size_bytes": size_bytes,
            "size_str": size_str,
            "type": "empty_or_too_small",
            "is_capcut": False,
            "xor_key": None,
            "status_text": "File quá nhỏ hoặc rỗng",
            "badge_color": "#EF4444",
            "needs_restoration": False,
        }

    try:
        with open(file_path, "rb") as f:
            head = f.read(512)
    except Exception as e:
        return {
            "file_path": str(path),
            "file_name": path.name,
            "exists": True,
            "size_bytes": size_bytes,
            "size_str": size_str,
            "type": "read_error",
            "is_capcut": False,
            "xor_key": None,
            "status_text": f"Lỗi đọc: {e}",
            "badge_color": "#EF4444",
            "needs_restoration": False,
        }

    # 1. Check if raw header has standard MP4/MOV signatures
    raw_has_ftyp = b"ftyp" in head[:128]
    raw_has_moov = b"moov" in head[:128]

    # 2. Check for CapCut XOR (first try standard 0xA5)
    xor_a5 = head.translate(XOR_TABLE_CAPCUT)
    if b"ftyp" in xor_a5[:128] or b"moov" in xor_a5[:128]:
        return {
            "file_path": str(path),
            "file_name": path.name,
            "exists": True,
            "size_bytes": size_bytes,
            "size_str": size_str,
            "type": "capcut_xor",
            "is_capcut": True,
            "xor_key": 0xA5,
            "key_hex": "0xA5",
            "status_text": "CapCut Pre-processed (XOR 0xA5)",
            "badge_color": "#8B5CF6",  # Purple
            "needs_restoration": True,
            "description": "File tiền xử lý của CapCut được mã hóa XOR 0xA5. Sẽ khôi phục Lossless 100%."
        }

    # 3. Check if XOR with other single-byte key
    if len(head) >= 8:
        # If byte 4..7 is ftyp xor'd with k
        guessed_key = head[4] ^ 0x66  # 'f'
        if guessed_key != 0:
            candidate_ftyp = bytes([b ^ guessed_key for b in head[4:8]])
            if candidate_ftyp == b"ftyp":
                return {
                    "file_path": str(path),
                    "file_name": path.name,
                    "exists": True,
                    "size_bytes": size_bytes,
                    "size_str": size_str,
                    "type": "capcut_xor",
                    "is_capcut": True,
                    "xor_key": guessed_key,
                    "key_hex": f"0x{guessed_key:02X}",
                    "status_text": f"CapCut Pre-processed (XOR 0x{guessed_key:02X})",
                    "badge_color": "#8B5CF6",
                    "needs_restoration": True,
                    "description": f"File tiền xử lý CapCut với key XOR 0x{guessed_key:02X}. Khôi phục Lossless."
                }

    # Scan any single byte key in 0..255
    if not raw_has_ftyp and not raw_has_moov:
        for k in range(1, 256):
            if k == 0xA5:
                continue
            table = bytes([i ^ k for i in range(256)])
            dec_chunk = head[:128].translate(table)
            if b"ftyp" in dec_chunk:
                return {
                    "file_path": str(path),
                    "file_name": path.name,
                    "exists": True,
                    "size_bytes": size_bytes,
                    "size_str": size_str,
                    "type": "capcut_xor",
                    "is_capcut": True,
                    "xor_key": k,
                    "key_hex": f"0x{k:02X}",
                    "status_text": f"CapCut Pre-processed (XOR 0x{k:02X})",
                    "badge_color": "#8B5CF6",
                    "needs_restoration": True,
                    "description": f"File tiền xử lý CapCut với key XOR 0x{k:02X}."
                }

    # 4. If raw header has ftyp, verify with ffprobe
    if raw_has_ftyp or raw_has_moov:
        # Check if ffprobe reads duration properly
        ffprobe_bin = find_ffprobe()
        cmd = [
            ffprobe_bin, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ]
        try:
            p = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=CREATE_NO_WINDOW, timeout=5
            )
            out = p.stdout.strip()
            if p.returncode == 0 and out:
                duration_sec = float(out)
                dur_str = format_duration(duration_sec)
                return {
                    "file_path": str(path),
                    "file_name": path.name,
                    "exists": True,
                    "size_bytes": size_bytes,
                    "size_str": size_str,
                    "type": "standard_video",
                    "is_capcut": False,
                    "xor_key": None,
                    "duration_sec": duration_sec,
                    "duration_str": dur_str,
                    "status_text": f"Video MP4 chuẩn ({dur_str})",
                    "badge_color": "#10B981",  # Emerald Green
                    "needs_restoration": False,
                    "description": "Video MP4 tiêu chuẩn có thể phát bình thường."
                }
            elif "moov atom not found" in p.stderr.lower():
                return {
                    "file_path": str(path),
                    "file_name": path.name,
                    "exists": True,
                    "size_bytes": size_bytes,
                    "size_str": size_str,
                    "type": "fragmented_moov",
                    "is_capcut": False,
                    "xor_key": None,
                    "status_text": "MP4 thiếu header moov",
                    "badge_color": "#F59E0B",  # Amber
                    "needs_restoration": True,
                    "description": "Video bị lỗi thiếu moov atom (kết xuất dở dang). Cần khôi phục index."
                }
        except Exception:
            pass

        return {
            "file_path": str(path),
            "file_name": path.name,
            "exists": True,
            "size_bytes": size_bytes,
            "size_str": size_str,
            "type": "standard_video",
            "is_capcut": False,
            "xor_key": None,
            "status_text": "Video MP4",
            "badge_color": "#10B981",
            "needs_restoration": False,
            "description": "Video MP4 thông thường."
        }

    # 5. Check if it's another video format (MKV, AVI, etc.)
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return {
            "file_path": str(path),
            "file_name": path.name,
            "exists": True,
            "size_bytes": size_bytes,
            "size_str": size_str,
            "type": "other_video",
            "is_capcut": False,
            "xor_key": None,
            "status_text": f"Video {ext.upper().replace('.', '')}",
            "badge_color": "#3B82F6",  # Blue
            "needs_restoration": True,
            "description": f"Video định dạng {ext.upper()}. Sẽ chuyển sang MP4 chuẩn H.264/AAC."
        }

    # 6. Unknown / Unrecognized file
    return {
        "file_path": str(path),
        "file_name": path.name,
        "exists": True,
        "size_bytes": size_bytes,
        "size_str": size_str,
        "type": "unknown",
        "is_capcut": False,
        "xor_key": None,
        "status_text": "Định dạng không xác định",
        "badge_color": "#64748B",  # Gray
        "needs_restoration": True,
        "description": "Không tìm thấy cấu trúc MP4 hoặc mã hóa CapCut quen thuộc. Vẫn có thể thử khôi phục."
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stream XOR Decoding (Chunked, C-Accelerated)
# ─────────────────────────────────────────────────────────────────────────────

def stream_xor_decode(
    src_path: Path,
    dst_path: Path,
    key: int = XOR_KEY_CAPCUT,
    chunk_size: int = 4 * 1024 * 1024,  # 4 MB
    progress_callback: Optional[Callable[[float], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None
):
    """
    Decodes an XOR-obfuscated file in 4MB chunks using Python's native C-based
    bytes.translate(), processing at 1GB+/second while keeping RAM usage near zero.
    """
    xor_table = bytes([i ^ key for i in range(256)])
    total_size = src_path.stat().st_size
    processed = 0

    with open(src_path, "rb") as fin, open(dst_path, "wb") as fout:
        while True:
            if cancel_callback and cancel_callback():
                raise InterruptedError("Tiến trình bị hủy bởi người dùng.")

            chunk = fin.read(chunk_size)
            if not chunk:
                break

            fout.write(chunk.translate(xor_table))
            processed += len(chunk)

            if progress_callback and total_size > 0:
                progress_callback(min(1.0, processed / total_size))


def _nal_chain_ok(buf: bytes) -> bool:
    """True if buf is a valid sequence of 4-byte length-prefixed NAL units (AVC/HEVC)."""
    o, n = 0, len(buf)
    if n < 5:
        return False
    while o + 4 <= n:
        ln = int.from_bytes(buf[o:o + 4], "big")
        if ln == 0 or o + 4 + ln > n:
            return False
        o += 4 + ln
    return o == n


def _find_top_box(path: Path, box_type: bytes) -> Optional[Tuple[int, int]]:
    """Return (start, end) of the first top-level MP4 box of given type."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        pos = 0
        while pos + 8 <= size:
            f.seek(pos)
            hdr = f.read(16)
            bsize, btype = struct.unpack(">I4s", hdr[:8])
            if bsize == 1 and len(hdr) >= 16:
                bsize = struct.unpack(">Q", hdr[8:16])[0]
            elif bsize == 0:
                bsize = size - pos
            if bsize < 8:
                return None
            if btype == box_type:
                return pos, min(pos + bsize, size)
            pos += bsize
    return None


def repair_mixed_xor(
    src_path: Path,
    dec_path: Path,
    key: int,
    ffprobe_bin: str,
    log_callback: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Some CapCut combination files only XOR-encrypt alternating segments of mdat
    (the rest is plain). A whole-file XOR corrupts the plain segments and causes
    smeared / broken frames. Using the fully XOR-decoded file (valid moov) we
    locate every video packet, test whether the XOR or the raw bytes form a valid
    NAL chain, and restore raw bytes for plain segments in dec_path (in place).
    Returns True if any segment was repaired.
    """
    def _log(m: str):
        if log_callback:
            log_callback(m)

    try:
        r = subprocess.run(
            [ffprobe_bin, "-v", "error", "-select_streams", "v:0", "-show_packets",
             "-show_entries", "packet=pos,size", "-of", "json", str(dec_path)],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=120,
        )
        packets = json.loads(r.stdout).get("packets", [])
        mdat = _find_top_box(dec_path, b"mdat")
    except Exception:
        return False
    if not packets or not mdat:
        return False

    table = bytes(i ^ key for i in range(256))
    state = "X"
    runs: List[List[Any]] = []  # [state, start_pos]
    with open(src_path, "rb") as f:
        for p in packets:
            try:
                pos, size = int(p["pos"]), int(p["size"])
            except (KeyError, ValueError):
                continue
            f.seek(pos)
            b = f.read(size)
            if _nal_chain_ok(b.translate(table)):
                state = "X"
            elif _nal_chain_ok(b):
                state = "R"
            if not runs or runs[-1][0] != state:
                runs.append([state, pos])

    plain = [i for i, (s, _) in enumerate(runs) if s == "R"]
    if not plain:
        return False

    _log(f"🧩 Phát hiện file mã hóa xen kẽ: {len(plain)} đoạn plain / {len(runs)} đoạn. Đang sửa...")
    mdat_start, mdat_end = mdat
    with open(src_path, "rb") as fsrc, open(dec_path, "r+b") as fdst:
        for i in plain:
            start = runs[i][1]
            end = runs[i + 1][1] if i + 1 < len(runs) else mdat_end
            start, end = max(start, mdat_start), min(end, mdat_end)
            if end <= start:
                continue
            fsrc.seek(start)
            fdst.seek(start)
            remaining = end - start
            while remaining > 0:
                chunk = fsrc.read(min(4 * 1024 * 1024, remaining))
                if not chunk:
                    break
                fdst.write(chunk)
                remaining -= len(chunk)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Video Restoration & Conversion Core
# ─────────────────────────────────────────────────────────────────────────────

def _build_remux_cmd(
    ffmpeg_bin: str,
    src: str,
    dst: str,
    tolerant: bool = False,
    faststart: bool = True,
) -> List[str]:
    """
    Build a lossless remux (stream copy) command to MP4 (ISO Base Media File Format).
    Prioritizes preserving 100% original video/audio quality (-c copy).
    'tolerant' mode adds PTS/DTS recovery flags to fix lag/drop frames from timestamp drift.
    """
    cmd = [ffmpeg_bin, "-y"]
    if tolerant:
        cmd.extend([
            "-err_detect", "ignore_err",
            "-fflags", "+genpts+igndts",
            "-avoid_negative_ts", "make_zero",
        ])
    cmd.extend(["-i", src, "-map", "0", "-c", "copy"])
    if faststart:
        cmd.extend(["-movflags", "+faststart"])
    if tolerant:
        cmd.extend(["-vsync", "vfr"])
    cmd.extend(["-f", "mp4", dst])
    return cmd


def _build_video_copy_audio_aac_cmd(
    ffmpeg_bin: str,
    src: str,
    dst: str,
    audio_bitrate: str = "320k",
    faststart: bool = True,
) -> List[str]:
    """
    Build a hybrid command preserving 100% original video quality (-c:v copy)
    while converting audio stream to standard AAC in an MP4 container.
    """
    cmd = [
        ffmpeg_bin, "-y",
        "-err_detect", "ignore_err",
        "-fflags", "+genpts+igndts",
        "-avoid_negative_ts", "make_zero",
        "-i", src,
        "-map", "0:v:0?",
        "-map", "0:a:0?",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-ar", "48000",
    ]
    if faststart:
        cmd.extend(["-movflags", "+faststart"])
    cmd.extend(["-f", "mp4", dst])
    return cmd


def _build_transcode_cmd(
    ffmpeg_bin: str,
    src: str,
    dst: str,
    gpu_encoder: Optional[Tuple[str, str]],
    crf: int = 15,
    audio_bitrate: str = "320k",
    extra_input_flags: Optional[List[str]] = None,
    faststart: bool = True,
) -> Tuple[List[str], str]:
    """
    Build a high-quality transcode FFmpeg command into MP4 (ISO Base Media File Format).
    Video: GPU Hardware Acceleration (NVENC, Intel QSV, AMD AMF) or CPU libx264 (H.264).
    Audio: standard AAC codec at 320kbps / 48000 Hz.
    Container: MP4 with -movflags +faststart.
    Returns (cmd_list, method_description).
    """
    cmd = [ffmpeg_bin, "-y"]
    if extra_input_flags:
        cmd.extend(extra_input_flags)
    cmd.extend(["-i", src, "-map", "0:v:0?", "-map", "0:a:0?"])

    if gpu_encoder:
        enc_id, enc_name = gpu_encoder
        if enc_id == "h264_nvenc":
            cmd.extend([
                "-c:v", "h264_nvenc",
                "-preset", "p5",
                "-rc", "vbr",
                "-cq", str(crf),
                "-b:v", "0",
                "-pix_fmt", "yuv420p",
            ])
        elif enc_id == "h264_qsv":
            cmd.extend([
                "-c:v", "h264_qsv",
                "-global_quality", str(crf),
                "-preset", "slower",
                "-pix_fmt", "yuv420p",
            ])
        elif enc_id == "h264_amf":
            cmd.extend([
                "-c:v", "h264_amf",
                "-quality", "quality",
                "-rc", "cqp",
                "-qp_i", str(crf),
                "-qp_p", str(crf),
                "-pix_fmt", "yuv420p",
            ])
        method = f"Transcode GPU {enc_name} (H.264) + AAC"
    else:
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", str(crf),
            "-pix_fmt", "yuv420p",
            "-x264-params", "ref=5:bframes=3:me=hex:subme=7:analyse=all",
        ])
        method = f"Transcode CPU libx264 (H.264 CRF {crf}) + AAC"

    cmd.extend([
        "-c:a", "aac",
        "-b:a", audio_bitrate,
        "-ar", "48000",
    ])
    if faststart:
        cmd.extend(["-movflags", "+faststart"])
    cmd.extend(["-f", "mp4", dst])
    return cmd, method


def restore_capcut_file(
    src_file: str,
    output_path: str,
    detection_info: Optional[Dict[str, Any]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    cancel_callback: Optional[Callable[[], bool]] = None,
    log_callback: Optional[Callable[[str], None]] = None,
    prefer_lossless: bool = True,
    use_gpu: bool = True,
    faststart: bool = True,
) -> Dict[str, Any]:
    """
    Restores a CapCut pre-processed file or converts an unstandardized video
    to a fully compliant, high-quality standard MP4 (ISO Base Media File Format).

    Technology Stack & Priority Flow:
    1. Decode XOR bitstream (CapCut compound clips key 0xA5 / detected key)
    2. Remux priority (-c copy lossless):
       a. Pure Stream Copy: -c copy -movflags +faststart -f mp4 (100% original quality)
       b. Tolerant Stream Copy: PTS/DTS recovery flags to fix drift / sync errors
       c. Video Stream Copy + AAC Audio: -c:v copy -c:a aac -b:a 320k -movflags +faststart
    3. High-quality transcode fallback (when Remux not possible or prefer_lossless=False):
       a. GPU Hardware Acceleration (NVENC, Intel QSV, AMD AMF) H.264 + AAC
       b. CPU fallback: libx264 CRF 15, preset slow + AAC
    4. Output: MP4 container with -movflags +faststart for immediate playback.
    """
    src_path = Path(src_file)
    dst_path = Path(output_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    def _progress(pct: float, text: str):
        if progress_callback:
            progress_callback(pct, text)

    def _is_cancelled():
        return cancel_callback() if cancel_callback else False

    start_time = time.time()

    if detection_info is None:
        detection_info = detect_video_file(str(src_path))

    is_capcut = detection_info.get("is_capcut", False)
    xor_key = detection_info.get("xor_key")
    file_type = detection_info.get("type", "unknown")

    ffmpeg_bin = find_ffmpeg()

    # Detect GPU encoder once per file (cached globally across batch)
    gpu_encoder: Optional[Tuple[str, str]] = None
    if use_gpu:
        gpu_encoder = detect_gpu_encoder(ffmpeg_bin, log_callback=_log)

    _log(f"▶ Khởi tạo xử lý: {src_path.name}")
    _log(f"   Kích thước nguồn: {format_size(src_path.stat().st_size)}")
    _log(f"   Định dạng nhận diện: {detection_info.get('status_text', 'N/A')}")
    if gpu_encoder:
        _log(f"   🎮 GPU Encoder: {gpu_encoder[1]} ({gpu_encoder[0]})")
    else:
        _log(f"   🖥️  Encoder: CPU libx264 CRF 15 (preset slow)")

    # Generate unique temporary file name
    uid = uuid.uuid4().hex[:8]
    tmp_decoded = dst_path.parent / f".tmp_{uid}_{src_path.stem}.mp4"

    method_used = "N/A"

    try:
        # ─────────────────────────────────────────────────────────────────
        # CASE 1: CapCut Pre-processed XOR (Key 0xA5 or detected key)
        # ─────────────────────────────────────────────────────────────────
        if is_capcut or xor_key is not None:
            key = xor_key if xor_key is not None else XOR_KEY_CAPCUT
            _log(f"🔄 [1/3] Giải mã byte CapCut (XOR {hex(key)})...")
            _progress(0.05, f"Giải mã XOR {hex(key)}...")

            # XOR decode with sub-progress (from 5% to 45%)
            def _xor_progress(sub_pct: float):
                _progress(0.05 + sub_pct * 0.40, f"Giải mã XOR ({int(sub_pct * 100)}%)...")

            stream_xor_decode(
                src_path, tmp_decoded, key=key,
                progress_callback=_xor_progress,
                cancel_callback=cancel_callback
            )

            if _is_cancelled():
                raise InterruptedError("Tiến trình bị hủy bởi người dùng.")

            # Validate decoded file
            if not tmp_decoded.exists() or tmp_decoded.stat().st_size == 0:
                raise RuntimeError("Giải mã thất bại, file tạm rỗng.")

            with open(tmp_decoded, "rb") as f:
                head = f.read(64)
            if b"ftyp" not in head and b"moov" not in head:
                _log("⚠️ Cảnh báo: Header sau giải mã không chứa ftyp/moov, tiếp tục thử FFmpeg...")

            # Fix files where only alternating segments are XOR-encrypted
            _progress(0.46, "Kiểm tra vùng mã hóa xen kẽ...")
            repair_mixed_xor(src_path, tmp_decoded, key, find_ffprobe(), log_callback=_log)

            # ── Step 2: Remux Lossless (Ưu tiên -c copy giữ nguyên 100% chất lượng)
            if prefer_lossless:
                _log("🎬 [2/3] Ưu tiên Remux Lossless (-c copy + faststart)...")
                _progress(0.47, "Thử Stream Copy Lossless...")

                cmd_copy = _build_remux_cmd(ffmpeg_bin, str(tmp_decoded), str(dst_path), tolerant=False, faststart=faststart)
                r = subprocess.run(cmd_copy, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)

                if r.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 0:
                    method_used = "Lossless Remux (-c copy + faststart)"
                    _log(f"✅ Hoàn tất với Stream Copy Lossless: {dst_path.name}")
                else:
                    _log("⚠️ Stream copy thất bại, thử Tolerant Remux (sửa PTS/DTS timestamps)...")
                    _progress(0.52, "Tolerant Remux (sửa timestamps)...")

                    cmd_tol = _build_remux_cmd(ffmpeg_bin, str(tmp_decoded), str(dst_path), tolerant=True, faststart=faststart)
                    r_tol = subprocess.run(cmd_tol, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)

                    if r_tol.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 0:
                        method_used = "Tolerant Lossless Remux (PTS/DTS fixed)"
                        _log(f"✅ Hoàn tất với Tolerant Remux: {dst_path.name}")
                    else:
                        _log("⚠️ Thử giữ nguyên Video (-c:v copy) và chuẩn hóa Audio AAC...")
                        _progress(0.55, "Thử Video Copy + Audio AAC...")
                        cmd_vcopy = _build_video_copy_audio_aac_cmd(ffmpeg_bin, str(tmp_decoded), str(dst_path), faststart=faststart)
                        r_vcopy = subprocess.run(cmd_vcopy, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                        if r_vcopy.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 0:
                            method_used = "Video Lossless Copy (-c:v copy) + AAC Audio"
                            _log(f"✅ Hoàn tất với Video Copy + AAC: {dst_path.name}")

            # ── Step 3: High-quality transcode fallback if remux failed or prefer_lossless=False
            if method_used == "N/A":
                _log("ℹ️ [3/3] Chuyển sang mã hóa H.264/AAC chất lượng cao (GPU/CPU fallback)...")
                _progress(0.58, "Chuyển mã H.264/AAC...")

                extra_flags = [
                    "-err_detect", "ignore_err",
                    "-fflags", "+genpts+igndts",
                    "-avoid_negative_ts", "make_zero",
                ]
                cmd_trans, method_used = _build_transcode_cmd(
                    ffmpeg_bin, str(tmp_decoded), str(dst_path),
                    gpu_encoder=gpu_encoder,
                    crf=15, audio_bitrate="320k",
                    extra_input_flags=extra_flags,
                    faststart=faststart,
                )
                _log(f"   Encoder: {method_used}")
                r_trans = subprocess.run(
                    cmd_trans, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
                )

                # CPU fallback if GPU failed
                if (r_trans.returncode != 0 or not dst_path.exists() or dst_path.stat().st_size == 0) and gpu_encoder:
                    _log("⚠️ GPU encode thất bại, fallback về CPU libx264...")
                    _progress(0.62, "Fallback CPU libx264 CRF 15...")
                    cmd_cpu, method_used = _build_transcode_cmd(
                        ffmpeg_bin, str(tmp_decoded), str(dst_path),
                        gpu_encoder=None, crf=15, audio_bitrate="320k",
                        extra_input_flags=extra_flags,
                        faststart=faststart,
                    )
                    r_trans = subprocess.run(
                        cmd_cpu, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
                    )

                if r_trans.returncode != 0 or not dst_path.exists() or dst_path.stat().st_size == 0:
                    err_snippet = r_trans.stderr[-1200:] if r_trans.stderr else "Lỗi không xác định"
                    raise RuntimeError(f"FFmpeg thất bại:\n{err_snippet}")
                _log(f"✅ Hoàn tất chuyển mã ({method_used}): {dst_path.name}")

        # ─────────────────────────────────────────────────────────────────
        # CASE 2: Fragmented Moov / Unfinalized MP4
        # ─────────────────────────────────────────────────────────────────
        elif file_type == "fragmented_moov":
            _log("🔧 Sửa chữa moov atom và khôi phục index MP4...")
            _progress(0.30, "Đang sửa chữa index moov...")

            if prefer_lossless:
                cmd_tol = _build_remux_cmd(ffmpeg_bin, str(src_path), str(dst_path), tolerant=True, faststart=faststart)
                r = subprocess.run(cmd_tol, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                if r.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 0:
                    method_used = "Re-indexed Tolerant Remux (PTS/DTS fixed)"

            if method_used == "N/A":
                _log("ℹ️ Remux thất bại, chuyển sang transcode H.264/AAC chất lượng cao...")
                _progress(0.50, "Transcode sửa chữa...")
                extra_flags = ["-err_detect", "ignore_err", "-fflags", "+genpts+igndts", "-avoid_negative_ts", "make_zero"]
                cmd_trans, method_used = _build_transcode_cmd(
                    ffmpeg_bin, str(src_path), str(dst_path),
                    gpu_encoder=gpu_encoder, crf=15, audio_bitrate="320k",
                    extra_input_flags=extra_flags,
                    faststart=faststart,
                )
                r_trans = subprocess.run(cmd_trans, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)

                if (r_trans.returncode != 0 or not dst_path.exists() or dst_path.stat().st_size == 0) and gpu_encoder:
                    _log("⚠️ GPU encode thất bại, fallback CPU libx264...")
                    cmd_cpu, method_used = _build_transcode_cmd(
                        ffmpeg_bin, str(src_path), str(dst_path),
                        gpu_encoder=None, crf=15, audio_bitrate="320k",
                        extra_input_flags=extra_flags,
                        faststart=faststart,
                    )
                    r_trans = subprocess.run(cmd_cpu, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)

                if r_trans.returncode != 0:
                    raise RuntimeError(f"Không thể sửa chữa video bị thiếu moov: {r_trans.stderr[-600:]}")

        # ─────────────────────────────────────────────────────────────────
        # CASE 3: Standard Video or Other Video Formats
        # ─────────────────────────────────────────────────────────────────
        else:
            _log("🎬 Tiêu chuẩn hóa video sang chuẩn MP4 faststart...")
            if prefer_lossless:
                _progress(0.20, "Thử Stream Copy MP4 chuẩn...")
                cmd_copy = _build_remux_cmd(ffmpeg_bin, str(src_path), str(dst_path), tolerant=False, faststart=faststart)
                r_copy = subprocess.run(cmd_copy, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)

                if r_copy.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 0:
                    method_used = "Stream Copy + Faststart"
                else:
                    _progress(0.35, "Tolerant Remux...")
                    cmd_tol = _build_remux_cmd(ffmpeg_bin, str(src_path), str(dst_path), tolerant=True, faststart=faststart)
                    r_tol = subprocess.run(cmd_tol, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)

                    if r_tol.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 0:
                        method_used = "Tolerant Remux + Faststart"
                    else:
                        _progress(0.40, "Thử Video Stream Copy + Audio AAC...")
                        cmd_vcopy = _build_video_copy_audio_aac_cmd(ffmpeg_bin, str(src_path), str(dst_path), faststart=faststart)
                        r_vcopy = subprocess.run(cmd_vcopy, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
                        if r_vcopy.returncode == 0 and dst_path.exists() and dst_path.stat().st_size > 0:
                            method_used = "Video Stream Copy + AAC Audio"

            if method_used == "N/A":
                _progress(0.45, "Chuyển đổi H.264/AAC chất lượng cao...")
                cmd_trans, method_used = _build_transcode_cmd(
                    ffmpeg_bin, str(src_path), str(dst_path),
                    gpu_encoder=gpu_encoder, crf=15, audio_bitrate="320k",
                    faststart=faststart,
                )
                r_trans = subprocess.run(cmd_trans, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)

                if (r_trans.returncode != 0 or not dst_path.exists() or dst_path.stat().st_size == 0) and gpu_encoder:
                    _log("⚠️ GPU encode thất bại, fallback CPU libx264...")
                    cmd_cpu, method_used = _build_transcode_cmd(
                        ffmpeg_bin, str(src_path), str(dst_path),
                        gpu_encoder=None, crf=15, audio_bitrate="320k",
                        faststart=faststart,
                    )
                    r_trans = subprocess.run(cmd_cpu, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)

                if r_trans.returncode != 0:
                    raise RuntimeError(f"Lỗi chuyển đổi: {r_trans.stderr[-600:]}")

        # ─────────────────────────────────────────────────────────────────
        # Final Verification
        # ─────────────────────────────────────────────────────────────────
        if not dst_path.exists() or dst_path.stat().st_size == 0:
            raise RuntimeError("File kết quả không tồn tại hoặc có kích thước 0 byte.")

        elapsed = time.time() - start_time
        final_size = dst_path.stat().st_size
        _progress(1.0, "Hoàn tất")
        _log(f"🎉 Khôi phục thành công: {dst_path.name}")
        _log(f"   Dung lượng đầu ra: {format_size(final_size)} | Phương thức: {method_used}")
        _log(f"   Thời gian: {elapsed:.2f}s")

        return {
            "success": True,
            "output_path": str(dst_path),
            "output_size": final_size,
            "output_size_str": format_size(final_size),
            "elapsed_seconds": elapsed,
            "elapsed_str": f"{elapsed:.1f}s",
            "method": method_used,
            "error": None
        }

    except InterruptedError:
        raise
    except Exception as e:
        _log(f"❌ Lỗi nghiêm trọng: {e}")
        raise
    finally:
        # Safely cleanup temporary file
        if tmp_decoded.exists():
            try:
                tmp_decoded.unlink(missing_ok=True)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Background Batch Processing Thread
# ─────────────────────────────────────────────────────────────────────────────

class CapCutBatchWorker(QThread):
    """
    Background worker thread for processing batches of CapCut pre-processed files.
    Supports GPU Hardware Acceleration (NVENC, Intel QSV, AMD AMF) with CPU libx264 fallback.
    """
    file_started = pyqtSignal(int, str)              # (row_index, filename)
    file_progress = pyqtSignal(int, float, str)      # (row_index, percent 0..1, status_text)
    file_completed = pyqtSignal(int, dict)           # (row_index, result_dict)
    file_failed = pyqtSignal(int, str)               # (row_index, error_message)
    batch_progress = pyqtSignal(int, int, float)     # (done_count, total_count, overall_pct)
    batch_finished = pyqtSignal(int, int, int)       # (success_count, failed_count, total_count)
    log_message = pyqtSignal(str)                    # log message for terminal

    def __init__(
        self,
        tasks: List[Dict[str, Any]],
        output_dir: Optional[str] = None,
        same_dir: bool = True,
        suffix: str = "_converted.mp4",
        prefer_lossless: bool = True,
        use_gpu: bool = True,
        faststart: bool = True,
        parent=None
    ):
        super().__init__(parent)
        self.tasks = tasks  # list of dicts: {"index": i, "path": path, "detection": info}
        self.output_dir = output_dir
        self.same_dir = same_dir
        self.suffix = suffix
        self.prefer_lossless = prefer_lossless
        self.use_gpu = use_gpu
        self.faststart = faststart
        self._is_running = True
        self._is_paused = False

    def stop(self):
        self._is_running = False

    def pause(self):
        self._is_paused = True

    def resume(self):
        self._is_paused = False

    def is_cancelled(self) -> bool:
        return not self._is_running

    def run(self):
        total = len(self.tasks)
        success_count = 0
        failed_count = 0

        self.log_message.emit(f"🚀 Bắt đầu khôi phục hàng loạt {total} video CapCut...")

        # Pre-detect GPU once for the entire batch (cached globally)
        ffmpeg_bin = find_ffmpeg()
        gpu = detect_gpu_encoder(ffmpeg_bin, log_callback=self.log_message.emit) if self.use_gpu else None
        if gpu:
            self.log_message.emit(f"🎮 GPU Batch Encoder: {gpu[1]} ({gpu[0]})")
        else:
            self.log_message.emit("🖥️  CPU Batch Encoder: libx264 CRF 15 (preset slow)")

        for step, task in enumerate(self.tasks):
            if not self._is_running:
                self.log_message.emit("⏹️ Đã dừng tiến trình theo yêu cầu người dùng.")
                break

            # Handle pause
            while self._is_paused and self._is_running:
                time.sleep(0.2)

            idx = task["index"]
            src_path = Path(task["path"])
            detection = task.get("detection")

            self.file_started.emit(idx, src_path.name)
            self.file_progress.emit(idx, 0.0, "Đang chuẩn bị...")

            # Determine output path
            if self.same_dir or not self.output_dir:
                base_name = src_path.stem
                if base_name.endswith(".tmp"):
                    base_name = base_name[:-4]
                out_name = f"{base_name}{self.suffix}"
                out_path = src_path.parent / out_name
            else:
                out_dir = Path(self.output_dir)
                out_name = f"{src_path.stem}{self.suffix}"
                out_path = out_dir / out_name

            # Ensure unique output name if collision
            counter = 1
            while out_path.exists() and str(out_path.resolve()) == str(src_path.resolve()):
                out_path = out_path.with_name(f"{src_path.stem}_{counter}{self.suffix}")
                counter += 1

            def _on_progress(pct: float, text: str):
                self.file_progress.emit(idx, pct, text)

            try:
                res = restore_capcut_file(
                    src_file=str(src_path),
                    output_path=str(out_path),
                    detection_info=detection,
                    progress_callback=_on_progress,
                    cancel_callback=self.is_cancelled,
                    log_callback=self.log_message.emit,
                    prefer_lossless=self.prefer_lossless,
                    use_gpu=self.use_gpu,
                    faststart=self.faststart,
                )

                success_count += 1
                self.file_completed.emit(idx, res)

            except InterruptedError:
                self.file_failed.emit(idx, "Đã hủy")
                self.log_message.emit(f"⏹️ File {src_path.name} bị hủy.")
                failed_count += 1
                break

            except Exception as e:
                failed_count += 1
                err_msg = str(e)
                self.file_failed.emit(idx, err_msg)
                self.log_message.emit(f"❌ LỖI [{src_path.name}]: {err_msg}")

            done_count = step + 1
            overall_pct = done_count / total
            self.batch_progress.emit(done_count, total, overall_pct)

        self.log_message.emit(
            f"📊 Kết quả hoàn thành: {success_count} thành công, {failed_count} lỗi / {total} video."
        )
        self.batch_finished.emit(success_count, failed_count, total)
