"""Find exact byte offset where XOR flips inside I-frame packet 150 by decoding candidates."""
import sys, json, subprocess, struct, io
sys.path.insert(0, r"f:\Code\AutoShorts")
from core.capcut_preprocessor import find_ffmpeg, find_ffprobe

S = r"C:\CapCut\CapCut Drafts\1004\Resources\combination\DAA3C26C-1894-421c-B8F9-4C01C53403B3_video.mp4"
D = r"f:\Code\AutoShorts\scratch_dec.mp4"
KEY = 0x7B
T = bytes(i ^ KEY for i in range(256))
PIDX = int(sys.argv[1]) if len(sys.argv) > 1 else 150

dec = open(D, "rb").read()
i = dec.find(b"avcC")
conf = dec[i + 4:i + 4 + 2048]
nsps = conf[5] & 0x1F
o = 6
ps = b""
for _ in range(nsps):
    l = struct.unpack(">H", conf[o:o + 2])[0]
    ps += b"\x00\x00\x00\x01" + conf[o + 2:o + 2 + l]
    o += 2 + l
npps = conf[o]
o += 1
for _ in range(npps):
    l = struct.unpack(">H", conf[o:o + 2])[0]
    ps += b"\x00\x00\x00\x01" + conf[o + 2:o + 2 + l]
    o += 2 + l

pk = json.loads(subprocess.run([find_ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_packets",
                                "-show_entries", "packet=pos,size", "-of", "json", D],
                               capture_output=True, text=True).stdout)["packets"]
pos, size = int(pk[PIDX]["pos"]), int(pk[PIDX]["size"])
raw = open(S, "rb").read()[pos:pos + size]
print("packet", PIDX, pos, size)


def annexb(buf):
    out = b""
    o = 0
    while o + 4 <= len(buf):
        l = int.from_bytes(buf[o:o + 4], "big")
        out += b"\x00\x00\x00\x01" + buf[o + 4:o + 4 + l]
        o += 4 + l
    return out


def errs(buf):
    data = ps + annexb(buf)
    r = subprocess.run([find_ffmpeg(), "-v", "error", "-f", "h264", "-i", "pipe:0", "-f", "null", "-"],
                       input=data, capture_output=True)
    return len([l for l in r.stderr.decode(errors="replace").splitlines() if l.strip()])


# candidate: raw[:s] plain + raw[s:] XOR; keep NAL length headers valid (they are plain in R)
res = {}
step = int(sys.argv[2]) if len(sys.argv) > 2 else 256
lo = int(sys.argv[3]) if len(sys.argv) > 3 else 0
hi = int(sys.argv[4]) if len(sys.argv) > 4 else size
for s in range(lo, hi + 1, step):
    cand = raw[:s] + raw[s:].translate(T)
    # NAL length bytes must remain plain: restore header fields
    cand = bytearray(cand)
    o = 0
    while o + 4 <= len(raw):
        l = int.from_bytes(raw[o:o + 4], "big")
        cand[o:o + 4] = raw[o:o + 4]
        o += 4 + l
    e = errs(bytes(cand))
    res[s] = e
    print(s, e, flush=True)
