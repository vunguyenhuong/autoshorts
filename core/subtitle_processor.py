"""
Auto Subtitle Processor
Handles speech-to-text transcription (via faster-whisper) and ASS subtitle generation.
Integrates with AutoCut's existing FFmpeg pipeline.
"""

import os
import sys
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal


# ─────────────────────────────────────────────────────────────────────────────
#  SubtitleConfig — Serializable configuration for subtitle generation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SubtitleConfig:
    """
    All subtitle style and generation parameters in one place.
    Fully serializable to/from JSON via asdict() and SubtitleConfig(**dict).
    """
    enabled: bool = False

    # Whisper model
    model_size: str = "base"           # tiny | base | small | medium | large-v3-turbo | large-v3
    beam_size: int = 5                 # Beam Search decoding (1 = Greedy, 5 = High accuracy Beam Search)
    initial_prompt: str = ""           # Context prompt / Vocabulary hints / Punctuation rules

    # Font
    font_name: str = "Arial"           # Must support Unicode & Vietnamese
    font_size: int = 72                # px, suitable for 1080×1920

    # ASS colors (BGR hex format prefixed with &H and alpha byte: &HAABBGGRR)
    primary_color: str = "&H00FFFFFF"  # White text
    highlight_color: str = "&H0000FFFF"  # Yellow (active word) — BGR: 00FFFF = Yellow
    outline_color: str = "&H00000000"  # Black outline
    shadow_color: str = "&H80000000"   # Semi-transparent black shadow

    # Outline & Shadow
    outline_width: float = 3.0
    shadow_depth: float = 2.0

    # Position
    margin_v: int = 120                # px margin from bottom (safe area)

    # Segmentation
    max_chars_per_line: int = 40       # max chars per line before wrapping
    max_words_per_block: int = 5       # limit for words per subtitle block
    max_lines_per_block: int = 1       # max lines per subtitle block (1 or 2)
    silence_split_threshold: float = 0.8  # split block on silence > N seconds

    # Word highlight
    enable_word_highlight: bool = False  # Requires FFmpeg built with libass


# ─────────────────────────────────────────────────────────────────────────────
#  Transcription via faster-whisper
# ─────────────────────────────────────────────────────────────────────────────

def transcribe_audio(video_path: str, model_size: str = "base",
                     beam_size: int = 5, initial_prompt: str = "",
                     progress_callback=None) -> list:
    """
    Transcribe speech in a video file using faster-whisper.
    Auto-detects language. Returns word-level segments.

    Args:
        video_path:        Path to the video file.
        model_size:        Whisper model size (tiny/base/small/medium/large-v3-turbo/large-v3).
        beam_size:         Beam Search size (1 = Greedy, 5 = Beam Search).
        initial_prompt:    Context prompt to guide vocabulary/punctuation.
        progress_callback: Optional callable(str) for progress messages.

    Returns:
        List of dicts: [{"word": str, "start": float, "end": float}, ...]
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError(
            "faster-whisper is not installed. "
            "Run: pip install faster-whisper"
        )

    def emit(msg):
        if progress_callback:
            progress_callback(msg)

    emit(f"🎙 Đang tải Whisper model '{model_size}'...")

    # Detect CUDA availability
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"
    except ImportError:
        device = "cpu"
        compute_type = "int8"

    emit(f"🖥️ Thiết bị: {device.upper()} | Compute: {compute_type}")

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    prompt_info = f" | Context Prompt: '{initial_prompt.strip()}'" if initial_prompt and initial_prompt.strip() else ""
    emit(f"🎯 Thiết lập: Beam Search (size={beam_size}){prompt_info}")
    emit(f"🔊 Đang phân tích âm thanh: {Path(video_path).name}...")

    transcribe_kwargs = {
        "word_timestamps": True,
        "beam_size": beam_size,
        "vad_filter": True,
        "vad_parameters": dict(min_silence_duration_ms=400),
        "repetition_penalty": 1.2,
    }
    if initial_prompt and initial_prompt.strip():
        transcribe_kwargs["initial_prompt"] = initial_prompt.strip()

    try:
        segments_gen, info = model.transcribe(video_path, **transcribe_kwargs)
        segments = list(segments_gen)
    except Exception as e:
        emit(f"⚠️ VAD filter gặp lỗi ({e}), chuyển sang chế độ phân tích không dùng VAD...")
        transcribe_kwargs["vad_filter"] = False
        segments_gen, info = model.transcribe(video_path, **transcribe_kwargs)
        segments = list(segments_gen)

    detected_lang = info.language
    lang_prob = info.language_probability
    emit(f"🌐 Ngôn ngữ phát hiện: {detected_lang.upper()} (confidence: {lang_prob:.0%})")

    word_segments = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                word_text = w.word.strip()
                if word_text:
                    word_segments.append({
                        "word": word_text,
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                    })

    emit(f"✅ Transcribe xong: {len(word_segments)} từ, thời lượng ~{info.duration:.1f}s")
    return word_segments


# ─────────────────────────────────────────────────────────────────────────────
#  Subtitle block builder — word → readable lines
# ─────────────────────────────────────────────────────────────────────────────

def build_subtitle_blocks(word_segments: list, config: SubtitleConfig) -> list:
    """
    Group words into readable subtitle blocks.

    Rules:
    - Max 2 lines per block.
    - Max config.max_chars_per_line characters per line.
    - Max config.max_words_per_block words per block (soft limit).
    - Force new block on silence gap > config.silence_split_threshold seconds.

    Returns:
        List of dicts:
        [{"start": float, "end": float, "lines": [str, ...], "words": [word_dict, ...]}, ...]
    """
    if not word_segments:
        return []

    blocks = []
    current_words = []
    max_lines = getattr(config, 'max_lines_per_block', 1)
    max_words = getattr(config, 'max_words_per_block', 5)

    def flush_block():
        """Flush current_words into a block entry."""
        if not current_words:
            return
        block_text = " ".join(w["word"] for w in current_words)
        lines = _wrap_text(block_text, config.max_chars_per_line)
        # Truncate to max_lines
        if len(lines) > max_lines:
            lines = lines[:max_lines]
        blocks.append({
            "start": current_words[0]["start"],
            "end": current_words[-1]["end"],
            "lines": lines,
            "words": list(current_words),
        })

    for i, word in enumerate(word_segments):
        # Check if we should start a new block
        should_split = False

        if current_words:
            # Rule 1: silence gap
            prev_end = current_words[-1]["end"]
            gap = word["start"] - prev_end
            if gap > config.silence_split_threshold:
                should_split = True

            # Rule 2: word count limit
            if len(current_words) >= max_words:
                should_split = True

            # Rule 3: would this word push us over max_lines?
            if not should_split:
                test_text = " ".join(w["word"] for w in current_words) + " " + word["word"]
                test_lines = _wrap_text(test_text, config.max_chars_per_line)
                if len(test_lines) > max_lines:
                    should_split = True

        if should_split:
            flush_block()
            current_words = []

        current_words.append(word)

    flush_block()
    return blocks


def _wrap_text(text: str, max_chars: int) -> list:
    """
    Wrap text into lines of at most max_chars characters,
    breaking only at word boundaries.
    Returns a list of line strings.
    """
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        if not current_line:
            current_line = word
        elif len(current_line) + 1 + len(word) <= max_chars:
            current_line += " " + word
        else:
            lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [""]


# ─────────────────────────────────────────────────────────────────────────────
#  ASS file generator
# ─────────────────────────────────────────────────────────────────────────────

def _sec_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format: H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))  # centiseconds
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_ass_file(blocks: list, output_path: str, config: SubtitleConfig,
                      video_width: int = 1080, video_height: int = 1920) -> str:
    """
    Generate an ASS subtitle file from subtitle blocks.

    Supports word-level highlight if config.enable_word_highlight is True.
    Each highlighted word is a separate Dialogue event with override tags.

    Args:
        blocks:       Output of build_subtitle_blocks().
        output_path:  Path to write the .ass file.
        config:       SubtitleConfig instance.
        video_width:  Target video width  (for PlayResX).
        video_height: Target video height (for PlayResY).

    Returns:
        The output_path string.
    """
    # ── ASS Header ────────────────────────────────────────────────────────────
    header = f"""\
[Script Info]
Title: AutoShorts Auto Subtitle
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: {video_width}
PlayResY: {video_height}
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{config.font_name},{config.font_size},{config.primary_color},{config.highlight_color},{config.outline_color},{config.shadow_color},-1,0,0,0,100,100,0,0,1,{config.outline_width:.1f},{config.shadow_depth:.1f},2,20,20,{config.margin_v},1
Style: Highlight,{config.font_name},{config.font_size},{config.highlight_color},{config.highlight_color},{config.outline_color},{config.shadow_color},-1,0,0,0,100,100,0,0,1,{config.outline_width:.1f},{config.shadow_depth:.1f},2,20,20,{config.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    dialogue_lines = []

    for block in blocks:
        start_ts = _sec_to_ass_time(block["start"])
        end_ts = _sec_to_ass_time(block["end"])
        block_text = "\\N".join(block["lines"])  # ASS newline

        if config.enable_word_highlight and len(block["words"]) > 1:
            # One Dialogue event per word: the active word is yellow, rest white
            for wi, active_word in enumerate(block["words"]):
                w_start = _sec_to_ass_time(active_word["start"])
                w_end = _sec_to_ass_time(active_word["end"])

                # Rebuild display text with highlight on active word
                words_in_block = block["words"]
                highlighted_parts = []
                for j, w in enumerate(words_in_block):
                    if j == wi:
                        highlighted_parts.append(
                            f"{{\\c{config.highlight_color}\\3c{config.outline_color}}}"
                            f"{w['word']}"
                            f"{{\\c{config.primary_color}\\3c{config.outline_color}}}"
                        )
                    else:
                        highlighted_parts.append(w["word"])

                raw_text = " ".join(highlighted_parts)
                # Rebuild as 2 lines preserving the highlight wrapping
                lines_rebuilt = _rebuild_highlighted_lines(
                    words_in_block, wi, config.max_chars_per_line,
                    config.primary_color, config.highlight_color,
                    config.outline_color,
                    max_lines=getattr(config, 'max_lines_per_block', 1)
                )
                display_text = "\\N".join(lines_rebuilt)

                dialogue_lines.append(
                    f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{display_text}"
                )
        else:
            # Simple block — one event per block
            dialogue_lines.append(
                f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{block_text}"
            )

    ass_content = header + "\n".join(dialogue_lines) + "\n"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8-sig") as f:
        f.write(ass_content)

    return output_path


def _rebuild_highlighted_lines(words: list, active_idx: int, max_chars: int,
                                primary_color: str, highlight_color: str,
                                outline_color: str, max_lines: int = 1) -> list:
    """
    Re-wrap words into ≤max_lines lines, injecting ASS color override tags for the
    active word at active_idx.
    """
    # First compute the raw line breaks (using plain text)
    plain_words = [w["word"] for w in words]
    lines_indices = []  # list of (start_idx, end_idx) of words per line
    line_start = 0
    current_len = 0

    for i, word in enumerate(plain_words):
        if i == line_start:
            current_len = len(word)
        elif current_len + 1 + len(word) <= max_chars:
            current_len += 1 + len(word)
        else:
            lines_indices.append((line_start, i - 1))
            line_start = i
            current_len = len(word)

    lines_indices.append((line_start, len(plain_words) - 1))

    # Truncate to max_lines
    lines_indices = lines_indices[:max_lines]

    result_lines = []
    for (li_start, li_end) in lines_indices:
        parts = []
        for i in range(li_start, li_end + 1):
            word = plain_words[i]
            if i == active_idx:
                parts.append(
                    f"{{\\c{highlight_color}\\3c{outline_color}}}{word}"
                    f"{{\\c{primary_color}\\3c{outline_color}}}"
                )
            else:
                parts.append(word)
        result_lines.append(" ".join(parts))

    return result_lines if result_lines else [""]


# ─────────────────────────────────────────────────────────────────────────────
#  SubtitleGeneratorThread — QThread worker
# ─────────────────────────────────────────────────────────────────────────────

class SubtitleGeneratorThread(QThread):
    """
    Background worker that:
    1. Transcribes audio with faster-whisper (word-level).
    2. Builds subtitle blocks.
    3. Generates an ASS file.

    Signals:
        progress(str)               – status message for log panel
        finished(bool, str, str)    – (success, ass_file_path, error_message)
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, str)

    def __init__(self, video_path: str, output_dir: str,
                 config: SubtitleConfig,
                 video_width: int = 1080, video_height: int = 1920,
                 parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.output_dir = output_dir
        self.config = config
        self.video_width = video_width
        self.video_height = video_height

    def run(self):
        try:
            self.progress.emit(
                f"🎙 [Auto Subtitle] Bắt đầu xử lý: {Path(self.video_path).name}"
            )

            # Step 1: Transcribe
            word_segments = transcribe_audio(
                self.video_path,
                model_size=self.config.model_size,
                beam_size=getattr(self.config, 'beam_size', 5),
                initial_prompt=getattr(self.config, 'initial_prompt', ''),
                progress_callback=lambda msg: self.progress.emit(msg)
            )

            if not word_segments:
                self.progress.emit("⚠️ Không nhận diện được lời nói trong video.")
                self.finished.emit(False, "", "Không tìm thấy lời nói")
                return

            # Step 2: Build blocks
            self.progress.emit(f"📝 Đang chia câu subtitle ({len(word_segments)} từ)...")
            blocks = build_subtitle_blocks(word_segments, self.config)
            self.progress.emit(f"✅ Tạo được {len(blocks)} subtitle block.")

            # Step 3: Generate ASS file
            stem = Path(self.video_path).stem
            subtitle_dir = os.path.join(self.output_dir, "subtitles")
            ass_path = os.path.join(subtitle_dir, f"{stem}.ass")
            self.progress.emit(f"💾 Đang xuất file ASS: {ass_path}")

            generate_ass_file(
                blocks, ass_path, self.config,
                video_width=self.video_width,
                video_height=self.video_height
            )

            self.progress.emit(f"✅ Subtitle đã tạo: {Path(ass_path).name}")
            self.finished.emit(True, ass_path, "")

        except ImportError as e:
            msg = str(e)
            self.progress.emit(f"❌ Thiếu thư viện: {msg}")
            self.finished.emit(False, "", msg)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.progress.emit(f"❌ Lỗi tạo subtitle: {e}")
            self.progress.emit(tb)
            self.finished.emit(False, "", str(e))
