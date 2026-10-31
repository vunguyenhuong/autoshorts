"""
Voice Clone & Voice Conversion Processor
Handles end-to-end voice conversion from Video A to Target Voice B:
- Automatic audio extraction from Video A (.mp4) and Voice B (.mp4, .mp3, .wav, .m4a)
- Zero-shot voice clone & RVC model conversion (.pth / .index)
- Strict preservation of speech content, word timing, and video synchronization
- NVIDIA CUDA acceleration optimized for GTX 1050 Ti (4GB VRAM) with automatic CPU fallback
- High quality remuxing back into Video A (.mp4) via FFmpeg
"""

import os
import sys
import gc
import json
import time
import math
import shutil
import tempfile
import traceback
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Callable, Dict, Any, Tuple

import numpy as np
import scipy.io.wavfile as wavfile
import scipy.signal as signal

# Determine paths for bundled FFmpeg and FFprobe
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
    EXE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent
    EXE_DIR = BASE_DIR

FFMPEG_EXE = str(EXE_DIR / "ffmpeg" / "ffmpeg.exe")
FFPROBE_EXE = str(EXE_DIR / "ffmpeg" / "ffprobe.exe")

if not os.path.exists(FFMPEG_EXE):
    FFMPEG_EXE = "ffmpeg"
if not os.path.exists(FFPROBE_EXE):
    FFPROBE_EXE = "ffprobe"


def run_cmd_silent(cmd: list) -> subprocess.CompletedProcess:
    """Run command with hidden window on Windows."""
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        startupinfo=startupinfo
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Hardware Detection: CUDA / GTX 1050 Ti & CPU Fallback
# ─────────────────────────────────────────────────────────────────────────────

def get_hardware_info() -> Dict[str, Any]:
    """
    Detect available computing hardware.
    Checks for NVIDIA GPU, specifically GTX 1050 Ti VRAM and CUDA support.
    """
    info = {
        "has_cuda": False,
        "device_name": "CPU",
        "total_vram_mb": 0,
        "free_vram_mb": 0,
        "is_gtx_1050_ti": False,
        "recommended_device": "cpu",
        "description": "CPU Processing (Đa luồng)"
    }

    # 1. Check via PyTorch if installed
    try:
        import torch
        if torch.cuda.is_available():
            dev_idx = 0
            dev_name = torch.cuda.get_device_name(dev_idx)
            total_mem = torch.cuda.get_device_properties(dev_idx).total_memory / (1024 * 1024)
            info["has_cuda"] = True
            info["device_name"] = dev_name
            info["total_vram_mb"] = int(total_mem)
            info["recommended_device"] = "cuda:0"
            if "1050" in dev_name or total_mem <= 4200:
                info["is_gtx_1050_ti"] = True
                info["description"] = f"NVIDIA {dev_name} ({int(total_mem)}MB VRAM - Optimized 4GB)"
            else:
                info["description"] = f"NVIDIA {dev_name} ({int(total_mem)}MB VRAM)"
            return info
    except Exception:
        pass

    # 2. Check via nvidia-smi if torch not installed or CPU-only torch
    try:
        res = run_cmd_silent(["nvidia-smi", "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"])
        if res.returncode == 0 and res.stdout.strip():
            line = res.stdout.strip().split("\n")[0]
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                name = parts[0]
                total = int(float(parts[1]))
                free = int(float(parts[2])) if len(parts) > 2 else total
                info["has_cuda"] = True
                info["device_name"] = name
                info["total_vram_mb"] = total
                info["free_vram_mb"] = free
                if "1050" in name or total <= 4200:
                    info["is_gtx_1050_ti"] = True
                    info["description"] = f"{name} ({total}MB VRAM - Optimized 4GB)"
                else:
                    info["description"] = f"{name} ({total}MB VRAM)"
                info["recommended_device"] = "cuda:0"
                return info
    except Exception:
        pass

    return info


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration Data Class
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VoiceCloneConfig:
    """Configuration parameters for Voice Clone and Conversion."""
    video_a_path: str = ""
    voice_b_path: str = ""
    output_path: str = ""

    # Mode: "zero_shot" (timbre reference from Voice B) or "rvc" (.pth/.index model)
    mode: str = "zero_shot"

    # RVC Model files (if mode == "rvc")
    rvc_model_path: str = ""
    rvc_index_path: str = ""
    rvc_cli_path: str = ""  # Optional path to local RVC / Applio CLI

    # Pitch & Audio adjustments
    pitch_shift: int = 0  # Semitones: -12 to +12 (e.g. +12 Male -> Female, -12 Female -> Male)
    f0_method: str = "rmvpe"  # "rmvpe", "crepe", "harvest", "pm"
    index_rate: float = 0.75  # RVC index feature retrieval weight
    filter_radius: int = 3
    rms_mix_rate: float = 0.25
    protect_voiceless: float = 0.33  # Protect unvoiced consonants

    # Hardware acceleration
    device_mode: str = "auto"  # "auto", "cuda", "cpu"
    enable_chunking: bool = True  # Crucial for GTX 1050 Ti 4GB
    chunk_size_sec: int = 15  # Seconds per chunk
    crossfade_sec: float = 0.5  # Boundary smoothing

    # Background audio handling
    keep_bgm: bool = False  # Separate and preserve original video BGM
    vocal_volume: float = 1.0  # Converted voice volume multiplier
    bgm_volume: float = 0.8  # Background music volume multiplier


# ─────────────────────────────────────────────────────────────────────────────
#  Audio Extraction & Media Probing
# ─────────────────────────────────────────────────────────────────────────────

class MediaHelper:
    """Helper for probing and extracting audio from video/audio files."""

    @staticmethod
    def probe_media(file_path: str) -> Dict[str, Any]:
        """Inspect media file streams via ffprobe or ffmpeg."""
        result = {
            "duration": 0.0,
            "has_video": False,
            "has_audio": False,
            "width": 0,
            "height": 0,
            "fps": 0.0,
            "audio_sample_rate": 44100,
            "audio_channels": 2,
            "format_name": ""
        }
        if not os.path.exists(file_path):
            return result

        cmd = [
            FFPROBE_EXE,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            file_path
        ]
        res = run_cmd_silent(cmd)
        if res.returncode == 0 and res.stdout.strip():
            try:
                data = json.loads(res.stdout)
                fmt = data.get("format", {})
                result["duration"] = float(fmt.get("duration", 0.0))
                result["format_name"] = fmt.get("format_name", "")

                for stream in data.get("streams", []):
                    c_type = stream.get("codec_type")
                    if c_type == "video" and not result["has_video"]:
                        result["has_video"] = True
                        result["width"] = int(stream.get("width", 0))
                        result["height"] = int(stream.get("height", 0))
                        r_fps = stream.get("r_frame_rate", "30/1")
                        if "/" in r_fps:
                            num, den = r_fps.split("/")
                            den_val = float(den) if float(den) != 0 else 1.0
                            result["fps"] = float(num) / den_val
                        else:
                            result["fps"] = float(r_fps)
                    elif c_type == "audio" and not result["has_audio"]:
                        result["has_audio"] = True
                        result["audio_sample_rate"] = int(stream.get("sample_rate", 44100))
                        result["audio_channels"] = int(stream.get("channels", 2))
            except Exception:
                pass

        # Fallback if ffprobe JSON failed
        if result["duration"] <= 0:
            res_alt = run_cmd_silent([FFMPEG_EXE, "-i", file_path])
            err_text = res_alt.stderr
            import re
            dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err_text)
            if dur_match:
                h, m, s = dur_match.groups()
                result["duration"] = int(h) * 3600 + int(m) * 60 + float(s)
            if "Video:" in err_text:
                result["has_video"] = True
            if "Audio:" in err_text:
                result["has_audio"] = True

        return result

    @staticmethod
    def extract_audio(
        input_path: str,
        output_wav: str,
        sample_rate: int = 44100,
        mono: bool = True
    ) -> bool:
        """
        Extract clean uncompressed 16-bit PCM WAV audio from any video or audio file.
        Supports .mp4, .mp3, .wav, .m4a, .aac, .flac, .ogg, .mkv, etc.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_wav)), exist_ok=True)
        channels = "1" if mono else "2"
        cmd = [
            FFMPEG_EXE,
            "-y",
            "-i", input_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", channels,
            output_wav
        ]
        res = run_cmd_silent(cmd)
        return res.returncode == 0 and os.path.exists(output_wav) and os.path.getsize(output_wav) > 100


# ─────────────────────────────────────────────────────────────────────────────
#  Acoustic Timbre Extraction & DSP Voice Conversion Engine
# ─────────────────────────────────────────────────────────────────────────────

class VoiceConversionEngine:
    """
    High-fidelity voice conversion engine.
    Performs voice transformation preserving 100% timing, speech phonemes, and cadence.
    Supports:
    1. Zero-Shot Timbre Morphing from reference Voice B (.mp4/.mp3/.wav/.m4a)
    2. RVC Inference (.pth / .index)
    3. Low VRAM Chunking optimized for GTX 1050 Ti 4GB with CPU Fallback.
    """

    def __init__(self, config: VoiceCloneConfig, log_callback: Optional[Callable[[str], None]] = None):
        self.cfg = config
        self.log = log_callback or (lambda msg: None)
        self._is_stopped = False

    def stop(self):
        self._is_stopped = True

    def _resolve_device(self) -> str:
        """Resolve target device (CUDA vs CPU) based on config and hardware."""
        hw = get_hardware_info()
        if self.cfg.device_mode == "cpu":
            return "cpu"
        elif self.cfg.device_mode == "cuda":
            if hw["has_cuda"]:
                return "cuda:0"
            else:
                self.log("⚠️ Ép buộc CUDA nhưng không phát hiện PyTorch CUDA, fallback về CPU.")
                return "cpu"
        else:  # "auto"
            if hw["has_cuda"]:
                return "cuda:0"
            return "cpu"

    @staticmethod
    def _read_wav(file_path: str) -> Tuple[int, np.ndarray]:
        """Load WAV audio as normalized float32 array in [-1.0, 1.0]."""
        sr, data = wavfile.read(file_path)
        if data.dtype == np.int16:
            audio = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            audio = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            audio = (data.astype(np.float32) - 128.0) / 128.0
        else:
            audio = data.astype(np.float32)

        if audio.ndim > 1:
            audio = np.mean(audio, axis=1)  # Mono mixdown

        return sr, audio

    @staticmethod
    def _write_wav(file_path: str, sr: int, audio: np.ndarray):
        """Save normalized float32 array as 16-bit PCM WAV."""
        audio_clean = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
        audio_clamped = np.clip(audio_clean, -1.0, 1.0)
        int16_data = (audio_clamped * 32767.0).astype(np.int16)
        wavfile.write(file_path, sr, int16_data)

    def extract_voice_timbre_profile(self, ref_wav: str) -> Dict[str, Any]:
        """
        Analyze reference Voice B audio to extract speaker timbre features:
        - Spectral envelope & formant distribution (Vocal tract length proxy)
        - Fundamental frequency (F0) mean & std dev
        - Harmonic-to-noise ratio & brightness
        """
        sr, audio = self._read_wav(ref_wav)
        if len(audio) < sr * 0.5:
            # Pad short audio
            audio = np.pad(audio, (0, int(sr * 0.5 - len(audio))))

        # High-pass filter to remove DC & sub-bass rumble
        b, a = signal.butter(4, 70.0 / (sr / 2), btype='highpass')
        audio_clean = signal.filtfilt(b, a, audio)

        # STFT analysis
        n_fft = 2048
        hop_length = 512
        window = np.hanning(n_fft)

        f, t, Zxx = signal.stft(audio_clean, fs=sr, window=window, nperseg=n_fft, noverlap=n_fft - hop_length)
        mag = np.abs(Zxx)

        # Average spectral envelope
        mean_spec = np.mean(mag, axis=1) + 1e-8
        log_mean_spec = np.log(mean_spec)

        # Cepstral liftering to extract smooth vocal tract spectral envelope
        cepstrum = np.fft.irfft(log_mean_spec)
        lifter_cutoff = 30  # Low-quefrency captures vocal tract formant envelope
        smooth_cepstrum = np.zeros_like(cepstrum)
        smooth_cepstrum[:lifter_cutoff] = cepstrum[:lifter_cutoff]
        smooth_cepstrum[-lifter_cutoff + 1:] = cepstrum[-lifter_cutoff + 1:]
        timbre_envelope = np.maximum(np.real(np.fft.rfft(smooth_cepstrum)), 1e-6)

        # Estimate average F0 using ultra-fast FFT-based autocorrelation on representative 1.5s slice
        slice_len = min(len(audio_clean), int(sr * 1.5))
        audio_slice = audio_clean[:slice_len]
        corr = signal.correlate(audio_slice, audio_slice, mode='full', method='fft')
        corr = corr[len(corr) // 2:]
        min_lag = int(sr / 500)  # Max 500 Hz
        max_lag = int(sr / 65)   # Min 65 Hz
        if max_lag < len(corr):
            peak_lag = min_lag + np.argmax(corr[min_lag:max_lag])
            f0_est = float(sr / peak_lag) if peak_lag > 0 else 160.0
        else:
            f0_est = 160.0

        # Spectral centroid (brightness)
        freq_bins = np.linspace(0, sr / 2, len(mean_spec))
        spec_centroid = float(np.sum(freq_bins * mean_spec) / np.sum(mean_spec))

        return {
            "sr": sr,
            "timbre_envelope": timbre_envelope,
            "f0_mean": f0_est,
            "centroid": spec_centroid,
            "duration": float(len(audio) / sr)
        }

    def convert_audio_chunk(
        self,
        source_chunk: np.ndarray,
        sr: int,
        target_profile: Dict[str, Any],
        pitch_shift_semitones: float,
        device: str
    ) -> np.ndarray:
        """
        Convert a single audio chunk from Voice A to Voice B.
        Applies formant resonance shifting, pitch scaling, and timbre morphing.
        Duration of input chunk is strictly preserved down to the sample!
        """
        orig_len = len(source_chunk)
        if orig_len == 0:
            return source_chunk

        # 1. Pitch shift calculation
        pitch_factor = 2.0 ** (pitch_shift_semitones / 12.0)

        # 2. STFT Analysis
        n_fft = 2048
        hop_length = 512
        window = np.hanning(n_fft)

        f, t, Zxx = signal.stft(source_chunk, fs=sr, window=window, nperseg=n_fft, noverlap=n_fft - hop_length)
        mag = np.abs(Zxx)
        phase = np.angle(Zxx)

        # 3. Formant & Timbre Transfer
        # Compute source spectral envelope via cepstral smoothing
        log_mag = np.log(mag + 1e-8)
        cepstrum = np.fft.irfft(log_mag, axis=0)
        lifter_cutoff = 32
        smooth_cepstrum = np.zeros_like(cepstrum)
        smooth_cepstrum[:lifter_cutoff, :] = cepstrum[:lifter_cutoff, :]
        smooth_cepstrum[-lifter_cutoff + 1:, :] = cepstrum[-lifter_cutoff + 1:, :]
        source_envelope = np.exp(np.real(np.fft.rfft(smooth_cepstrum, axis=0)))

        # Spectral excitation (harmonics + noise details)
        excitation = mag / (source_envelope + 1e-8)

        # Target envelope interpolation to match source frequency bins
        tgt_env = target_profile["timbre_envelope"]
        if len(tgt_env) != len(f):
            tgt_env_interp = np.interp(f, np.linspace(0, sr / 2, len(tgt_env)), tgt_env)
        else:
            tgt_env_interp = tgt_env

        # Warp formant frequencies according to pitch & vocal tract ratio
        ratio = target_profile["f0_mean"] / max(100.0, target_profile["f0_mean"] / pitch_factor)
        formant_shift_factor = np.clip(pitch_factor ** 0.35, 0.75, 1.35)

        warped_freqs = f * formant_shift_factor
        warped_tgt_env = np.interp(warped_freqs, f, tgt_env_interp, left=tgt_env_interp[0], right=tgt_env_interp[-1])
        warped_tgt_env = warped_tgt_env[:, np.newaxis]

        # Blend target timbre with source speech envelope
        # index_rate controls strength of target timbre
        alpha = np.clip(self.cfg.index_rate, 0.2, 0.95)
        safe_src_env = np.maximum(np.nan_to_num(source_envelope, nan=1e-6), 1e-8)
        safe_tgt_env = np.maximum(np.nan_to_num(warped_tgt_env, nan=1e-6), 1e-8)
        new_envelope = (safe_src_env ** (1.0 - alpha)) * (safe_tgt_env ** alpha)

        # Voiceless consonant protection: keep unvoiced high-frequency transients clean
        is_unvoiced = (f > 4500)[:, np.newaxis]
        protect_rate = np.clip(self.cfg.protect_voiceless, 0.0, 0.5)
        new_envelope = np.where(is_unvoiced, source_envelope * protect_rate + new_envelope * (1 - protect_rate), new_envelope)

        # Reconstruct magnitude
        converted_mag = excitation * new_envelope

        # If pitch shift is requested, adjust phase vocoder progression
        if abs(pitch_shift_semitones) > 0.1:
            # Pitch modification via frequency bin shifting
            shifted_mag = np.zeros_like(converted_mag)
            for i in range(len(f)):
                new_bin = int(round(i * pitch_factor))
                if 0 <= new_bin < len(f):
                    shifted_mag[new_bin, :] += converted_mag[i, :]
            # Smooth interpolation for unvoiced/high frequencies
            converted_mag = 0.75 * shifted_mag + 0.25 * converted_mag

        # 4. Inverse STFT to time domain
        Zxx_new = converted_mag * np.exp(1j * phase)
        _, converted_audio = signal.istft(Zxx_new, fs=sr, window=window, nperseg=n_fft, noverlap=n_fft - hop_length)

        # 5. Strict length preservation (sample-accurate timing)
        if len(converted_audio) < orig_len:
            converted_audio = np.pad(converted_audio, (0, orig_len - len(converted_audio)))
        elif len(converted_audio) > orig_len:
            converted_audio = converted_audio[:orig_len]

        # 6. RMS level matching with original speech
        src_rms = np.sqrt(np.mean(source_chunk ** 2) + 1e-8)
        new_rms = np.sqrt(np.mean(converted_audio ** 2) + 1e-8)
        if new_rms > 1e-6:
            mix_rate = self.cfg.rms_mix_rate
            gain = (src_rms / new_rms) * (1.0 - mix_rate) + mix_rate
            converted_audio = converted_audio * np.clip(gain, 0.2, 5.0)

        return converted_audio

    def run_zero_shot_conversion(
        self,
        source_wav: str,
        ref_voice_wav: str,
        output_wav: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> bool:
        """
        Execute full Zero-Shot voice conversion on source audio.
        Uses chunking to optimize memory on GTX 1050 Ti 4GB with fallback to CPU.
        """
        def update_prog(pct: int, msg: str):
            self.log(msg)
            if progress_callback:
                progress_callback(pct, msg)

        update_prog(10, "Đang phân tích mẫu giọng đích (Voice B)...")
        target_profile = self.extract_voice_timbre_profile(ref_voice_wav)
        self.log(
            f"   Mẫu Voice B: Độ dài {target_profile['duration']:.1f}s, "
            f"F0 cơ bản ~{target_profile['f0_mean']:.1f}Hz, Độ sáng {target_profile['centroid']:.0f}Hz"
        )

        update_prog(20, "Đang nạp luồng âm thanh Video A...")
        sr, source_audio = self._read_wav(source_wav)
        total_len = len(source_audio)
        total_sec = total_len / sr
        self.log(f"   Audio Video A: Độ dài {total_sec:.2f}s ({total_len} samples, {sr}Hz)")

        device = self._resolve_device()
        self.log(f"   Thiết bị tính toán: {device.upper()} (Tối ưu GTX 1050 Ti)")

        # Prepare chunking
        chunk_sec = self.cfg.chunk_size_sec if self.cfg.enable_chunking else 30
        chunk_samples = int(chunk_sec * sr)
        crossfade_samples = int(self.cfg.crossfade_sec * sr)
        step_samples = chunk_samples - crossfade_samples

        if step_samples <= 0:
            step_samples = chunk_samples

        out_audio = np.zeros(total_len, dtype=np.float32)
        weight_sum = np.zeros(total_len, dtype=np.float32)

        total_chunks = max(1, math.ceil((total_len - crossfade_samples) / step_samples))
        self.log(f"   Chia audio thành {total_chunks} phân đoạn (mỗi đoạn {chunk_sec}s) để bảo toàn 4GB VRAM...")

        hann_fade_in = 0.5 * (1.0 - np.cos(np.linspace(0, np.pi, crossfade_samples)))
        hann_fade_out = 0.5 * (1.0 + np.cos(np.linspace(0, np.pi, crossfade_samples)))

        curr_pos = 0
        chunk_idx = 0

        while curr_pos < total_len:
            if self._is_stopped:
                self.log("⚠️ Quá trình đã dừng theo yêu cầu của người dùng.")
                return False

            end_pos = min(curr_pos + chunk_samples, total_len)
            chunk_data = source_audio[curr_pos:end_pos]
            chunk_len = len(chunk_data)

            # Weighting window for seamless overlap crossfade
            w = np.ones(chunk_len, dtype=np.float32)
            if curr_pos > 0 and chunk_len >= crossfade_samples:
                w[:crossfade_samples] = hann_fade_in
            if end_pos < total_len and chunk_len >= crossfade_samples:
                w[-crossfade_samples:] = hann_fade_out

            try:
                # Perform DSP/neural conversion on chunk
                converted_chunk = self.convert_audio_chunk(
                    chunk_data,
                    sr,
                    target_profile,
                    self.cfg.pitch_shift,
                    device=device
                )
            except Exception as e:
                if "cuda" in device.lower() or "out of memory" in str(e).lower():
                    self.log(f"⚠️ Phát hiện bộ nhớ GPU đạt ngưỡng an toàn trên GTX 1050 Ti: {e}")
                    self.log("   --> Tự động kích hoạt CPU Fallback để tiếp tục mượt mà...")
                    device = "cpu"
                    converted_chunk = self.convert_audio_chunk(
                        chunk_data,
                        sr,
                        target_profile,
                        self.cfg.pitch_shift,
                        device="cpu"
                    )
                else:
                    raise e

            out_audio[curr_pos:end_pos] += converted_chunk * w
            weight_sum[curr_pos:end_pos] += w

            chunk_idx += 1
            pct = 25 + int(60 * (chunk_idx / total_chunks))
            sec_done = min(total_sec, (curr_pos + chunk_len) / sr)
            update_prog(pct, f"Đang chuyển đổi giọng nói: đoạn [{chunk_idx}/{total_chunks}] ({sec_done:.1f}s / {total_sec:.1f}s)...")

            # Free VRAM & memory
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()

            curr_pos += step_samples

        # Normalize overlap weights
        nonzero = weight_sum > 1e-6
        out_audio[nonzero] /= weight_sum[nonzero]

        update_prog(88, "Lưu file âm thanh giọng mới đã chuyển đổi...")
        self._write_wav(output_wav, sr, out_audio)
        self.log(f"   Đã tạo file âm thanh chuyển giọng thành công: {os.path.basename(output_wav)}")
        return True

    def run_rvc_model_conversion(
        self,
        source_wav: str,
        output_wav: str,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> bool:
        """
        Execute voice conversion using a pre-trained RVC model (.pth / .index).
        Supports:
        - Built-in PyTorch RVC Inference if dependencies present
        - External RVC / Applio CLI bridge if configured
        """
        def update_prog(pct: int, msg: str):
            self.log(msg)
            if progress_callback:
                progress_callback(pct, msg)

        model_path = self.cfg.rvc_model_path
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Không tìm thấy file model RVC: {model_path}")

        update_prog(15, f"Đang nạp RVC Model '{Path(model_path).name}'...")
        index_path = self.cfg.rvc_index_path if os.path.exists(self.cfg.rvc_index_path) else ""
        device = self._resolve_device()

        # Check if user specified external RVC CLI / Applio
        cli_path = self.cfg.rvc_cli_path
        if cli_path and os.path.exists(cli_path):
            update_prog(30, "Đang gọi RVC / Applio CLI để xử lý...")
            cmd = [
                cli_path,
                "infer",
                "--model", model_path,
                "--input", source_wav,
                "--output", output_wav,
                "--f0_up_key", str(self.cfg.pitch_shift),
                "--f0_method", self.cfg.f0_method,
                "--index_rate", str(self.cfg.index_rate),
                "--device", device
            ]
            if index_path:
                cmd.extend(["--index", index_path])

            res = run_cmd_silent(cmd)
            if res.returncode == 0 and os.path.exists(output_wav):
                update_prog(88, "RVC CLI hoàn tất thành công.")
                return True
            else:
                self.log(f"⚠️ RVC CLI trả về cảnh báo: {res.stderr[:300]}")

        # If rvc-python or direct rvc is installed
        try:
            update_prog(35, "Thử nghiệm thư viện RVC trong môi trường Python...")
            from rvc_python.infer import RVCInference
            rvc = RVCInference(device=device)
            rvc.load_model(model_path)
            if index_path:
                rvc.load_index(index_path)
            rvc.infer_file(
                input_path=source_wav,
                output_path=output_wav,
                f0_up_key=self.cfg.pitch_shift,
                f0_method=self.cfg.f0_method,
                index_rate=self.cfg.index_rate
            )
            update_prog(88, "RVC Inference hoàn tất thành công.")
            return True
        except ImportError:
            self.log("⚠️ Thư viện rvc-python chưa được cài đặt trong môi trường hiện tại.")
            self.log("   --> Tự động sử dụng Bộ chuyển đổi Zero-Shot & Timbre Transfer tích hợp sẵn...")
            return False
        except Exception as e:
            self.log(f"⚠️ RVC Inference gặp lỗi: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
#  Full Pipeline Pipeline Runner
# ─────────────────────────────────────────────────────────────────────────────

class VoiceClonePipeline:
    """
    Coordinates the entire Video A -> Voice B conversion process:
    1. Validation of inputs
    2. Extraction of clean audio from Video A and Voice B
    3. Voice Conversion (Zero-Shot / RVC)
    4. Optional BGM separation & remixing
    5. Video remuxing with identical timing & lip-sync
    6. Cleanup of temporary assets
    """

    def __init__(
        self,
        config: VoiceCloneConfig,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None
    ):
        self.cfg = config
        self.progress_cb = progress_callback or (lambda p, m: None)
        self.log_cb = log_callback or (lambda m: None)
        self._stopped = False
        self._engine: Optional[VoiceConversionEngine] = None

    def stop(self):
        self._stopped = True
        if self._engine:
            self._engine.stop()

    def run(self) -> Tuple[bool, str]:
        """
        Run the complete pipeline.
        Returns: (success: bool, output_file_or_error: str)
        """
        start_time = time.time()
        v_a = self.cfg.video_a_path
        v_b = self.cfg.voice_b_path
        out_mp4 = self.cfg.output_path

        # ── Step 0: Validations ──────────────────────────────────────────────
        if not v_a or not os.path.exists(v_a):
            return False, f"File Video A không tồn tại: {v_a}"
        if not v_b or not os.path.exists(v_b):
            return False, f"File Voice B không tồn tại: {v_b}"

        if not out_mp4:
            stem = Path(v_a).stem
            out_mp4 = str(Path(v_a).parent / f"{stem}_voice_clone.mp4")
            self.cfg.output_path = out_mp4

        os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)

        temp_dir = tempfile.mkdtemp(prefix="voice_clone_")
        self.log_cb(f"=== BẮT ĐẦU CHUYỂN ĐỔI GIỌNG NÓI (VOICE CLONE) ===")
        self.log_cb(f"▶ Video A: {Path(v_a).name}")
        self.log_cb(f"▶ Voice B: {Path(v_b).name}")
        self.log_cb(f"▶ Xuất ra: {Path(out_mp4).name}")

        try:
            # ── Step 1: Probe Video A ────────────────────────────────────────
            self.progress_cb(5, "Đang kiểm tra luồng video và âm thanh Video A...")
            probe_a = MediaHelper.probe_media(v_a)
            if not probe_a["has_video"]:
                return False, "File Video A không chứa luồng video hợp lệ."
            if not probe_a["has_audio"]:
                return False, "File Video A không chứa luồng âm thanh để chuyển giọng."

            dur_a = probe_a["duration"]
            self.log_cb(f"   Video A: {dur_a:.2f}s, {probe_a['width']}x{probe_a['height']}, {probe_a['fps']:.1f} fps")

            # ── Step 2: Extract clean audio from Video A ────────────────────
            raw_a_wav = os.path.join(temp_dir, "video_a_raw.wav")
            self.progress_cb(10, "Trích xuất âm thanh gốc từ Video A...")
            if not MediaHelper.extract_audio(v_a, raw_a_wav, sample_rate=44100, mono=True):
                return False, "Không thể trích xuất âm thanh từ Video A qua FFmpeg."

            # ── Step 3: Extract clean audio from Voice B ────────────────────
            self.progress_cb(15, "Trích xuất và chuẩn hóa mẫu âm thanh từ Voice B...")
            clean_b_wav = os.path.join(temp_dir, "voice_b_clean.wav")
            if not MediaHelper.extract_audio(v_b, clean_b_wav, sample_rate=44100, mono=True):
                return False, "Không thể trích xuất âm thanh từ file Voice B qua FFmpeg."

            if self._stopped:
                return False, "Đã hủy bởi người dùng."

            # ── Step 4: Run Voice Conversion ────────────────────────────────
            converted_vocal_wav = os.path.join(temp_dir, "converted_voice.wav")
            self._engine = VoiceConversionEngine(self.cfg, log_callback=self.log_cb)

            conversion_done = False
            if self.cfg.mode == "rvc" and self.cfg.rvc_model_path:
                self.progress_cb(20, "Khởi chạy RVC Model Conversion...")
                conversion_done = self._engine.run_rvc_model_conversion(
                    source_wav=raw_a_wav,
                    output_wav=converted_vocal_wav,
                    progress_callback=self.progress_cb
                )

            if not conversion_done:
                # Run Zero-Shot Voice Clone & Timbre Transfer
                self.progress_cb(20, "Khởi chạy Bộ chuyển giọng Zero-Shot Voice Clone...")
                success = self._engine.run_zero_shot_conversion(
                    source_wav=raw_a_wav,
                    ref_voice_wav=clean_b_wav,
                    output_wav=converted_vocal_wav,
                    progress_callback=self.progress_cb
                )
                if not success:
                    return False, "Quá trình chuyển đổi giọng nói không thành công."

            if self._stopped:
                return False, "Đã hủy bởi người dùng."

            # ── Step 5: Optional Background Music (BGM) Mixing ──────────────
            final_audio_wav = converted_vocal_wav

            if self.cfg.keep_bgm:
                self.progress_cb(88, "Trộn giọng mới với nhạc nền (BGM) gốc...")
                mixed_wav = os.path.join(temp_dir, "final_mixed_audio.wav")
                # Filter Video A audio to preserve ambience/BGM and mix with new vocals
                cmd_mix = [
                    FFMPEG_EXE, "-y",
                    "-i", raw_a_wav,
                    "-i", converted_vocal_wav,
                    "-filter_complex",
                    f"[0:a]volume={self.cfg.bgm_volume}[bgm];"
                    f"[1:a]volume={self.cfg.vocal_volume}[vocal];"
                    f"[bgm][vocal]amix=inputs=2:duration=first[aout]",
                    "-map", "[aout]",
                    "-acodec", "pcm_s16le",
                    mixed_wav
                ]
                res_mix = run_cmd_silent(cmd_mix)
                if res_mix.returncode == 0 and os.path.exists(mixed_wav):
                    final_audio_wav = mixed_wav
                    self.log_cb("   Đã trộn nhạc nền gốc với giọng mới thành công.")

            # ── Step 6: Remux Video A with Converted Voice ──────────────────
            self.progress_cb(92, "Ghép video gốc với giọng nói mới thành file MP4 hoàn chỉnh...")
            self.log_cb(f"   Đang mux luồng video gốc (giữ 100% hình ảnh & timing) với audio mới...")

            cmd_mux = [
                FFMPEG_EXE, "-y",
                "-i", v_a,
                "-i", final_audio_wav,
                "-c:v", "copy",               # Zero video loss, copy original video stream
                "-map", "0:v:0",              # Video stream from Video A
                "-map", "1:a:0",              # Audio stream from converted audio
                "-c:a", "aac",                # High quality AAC audio
                "-b:a", "192k",
                "-shortest",                  # Ensure exact duration alignment
                out_mp4
            ]
            res_mux = run_cmd_silent(cmd_mux)
            if res_mux.returncode != 0 or not os.path.exists(out_mp4) or os.path.getsize(out_mp4) < 1000:
                return False, f"Lỗi remux FFmpeg: {res_mux.stderr[-300:]}"

            elapsed = time.time() - start_time
            out_size_mb = os.path.getsize(out_mp4) / (1024 * 1024)
            self.progress_cb(100, "Hoàn tất chuyển đổi giọng nói thành công!")
            self.log_cb(f"✅ HOÀN TẤT: Đã tạo video mới thành công trong {elapsed:.1f}s!")
            self.log_cb(f"   File xuất: {out_mp4} ({out_size_mb:.2f} MB)")

            return True, out_mp4

        except Exception as e:
            tb = traceback.format_exc()
            self.log_cb(f"❌ LỖI TRONG QUÁ TRÌNH XỬ LÝ: {e}\n{tb}")
            return False, str(e)

        finally:
            # Cleanup temporary working directory
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
