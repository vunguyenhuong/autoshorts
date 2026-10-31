"""
debug_capcut.py - Chẩn đoán file CapCut combination bị vỡ khung hình.

Cách dùng:
    python debug_capcut.py "C:\\CapCut\\CapCut Drafts\\1004\\Resources\\combination\\<file>"

Script thử nhiều cách giải mã (raw / XOR toàn file / XOR một phần đầu file)
rồi đếm số lỗi decode H.264 của FFmpeg cho từng cách để biết cách nào đúng.
"""
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.capcut_preprocessor import find_ffmpeg, find_ffprobe  # noqa: E402

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
KEY = int(sys.argv[2], 0) if len(sys.argv) > 2 else 0xA5
TABLE = bytes(i ^ KEY for i in range(256))
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def list_boxes(path, limit=12):
    out = []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            pos = 0
            while pos < size and len(out) < limit:
                f.seek(pos)
                hdr = f.read(16)
                if len(hdr) < 8:
                    break
                bsize, btype = struct.unpack(">I4s", hdr[:8])
                if bsize == 1:
                    bsize = struct.unpack(">Q", hdr[8:16])[0]
                elif bsize == 0:
                    bsize = size - pos
                out.append((btype.decode("latin1"), pos, bsize))
                if bsize < 8:
                    break
                pos += bsize
    except Exception as e:
        out.append(("ERR", 0, str(e)))
    return out


def make_variant(src, dst, xor_bytes):
    """xor_bytes=None -> XOR toàn file; =N -> chỉ XOR N byte đầu; =0 -> raw."""
    done = 0
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while True:
            chunk = fin.read(4 * 1024 * 1024)
            if not chunk:
                break
            if xor_bytes is None:
                chunk = chunk.translate(TABLE)
            elif done < xor_bytes:
                n = min(len(chunk), xor_bytes - done)
                chunk = chunk[:n].translate(TABLE) + chunk[n:]
            done += len(chunk)
            fout.write(chunk)


def count_errors(path):
    r = subprocess.run(
        [find_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    lines = [l for l in r.stderr.splitlines() if l.strip()]
    return len(lines), lines[:3]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    src = Path(sys.argv[1])
    print(f"File: {src}  ({src.stat().st_size / 1e6:.1f} MB)")
    print("Box raw :", list_boxes(src))

    variants = [("RAW (không XOR)", 0), ("XOR TOÀN FILE", None),
                ("XOR 1 MB đầu", 1 << 20), ("XOR 16 MB đầu", 16 << 20)]
    tmpdir = Path(tempfile.mkdtemp(prefix="capcut_dbg_"))
    for name, nbytes in variants:
        dst = tmpdir / "v.mp4"
        make_variant(src, dst, nbytes)
        boxes = list_boxes(dst, 6)
        n_err, sample = count_errors(dst)
        print(f"\n[{name}] boxes={[b[0] for b in boxes]}  decode_errors={n_err}")
        for s in sample:
            print("   ", s[:160])
        dst.unlink(missing_ok=True)
    try:
        tmpdir.rmdir()
    except OSError:
        pass


if __name__ == "__main__":
    main()
