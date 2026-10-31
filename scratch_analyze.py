import subprocess, sys, json, os
sys.path.insert(0, r"f:\Code\AutoShorts")
from core.capcut_preprocessor import find_ffmpeg, find_ffprobe

SRC = sys.argv[1]
KEY = int(sys.argv[2], 0)
TBL = bytes(i ^ KEY for i in range(256))
DEC = r"f:\Code\AutoShorts\scratch_dec.mp4"

with open(SRC, "rb") as fi, open(DEC, "wb") as fo:
    while True:
        c = fi.read(1 << 22)
        if not c:
            break
        fo.write(c.translate(TBL))

r = subprocess.run([find_ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_packets",
                    "-show_entries", "packet=pos,size,flags", "-of", "json", DEC],
                   capture_output=True, text=True)
pk = json.loads(r.stdout)["packets"]
print("packets:", len(pk))
raw = open(SRC, "rb")
for p in pk[:6]:
    pos, size = int(p["pos"]), int(p["size"])
    raw.seek(pos)
    b = raw.read(size)
    print(f"\npos={pos} size={size} flags={p['flags']}")
    print(" raw first 24 :", b[:24].hex(" "))
    print(" xor first 24 :", b[:24].translate(TBL).hex(" "))
    # find how many leading bytes make sense as xor-decoded NAL length
    import struct
    print(" nal len raw  :", struct.unpack(">I", b[:4])[0], " nal len xor:", struct.unpack(">I", b[:4].translate(TBL))[0])
    # check where raw bytes look like valid 4-byte length chain
    def chain(buf):
        o = 0; n = 0
        while o + 4 <= len(buf):
            l = struct.unpack(">I", buf[o:o+4])[0]
            if l == 0 or o + 4 + l > len(buf): break
            o += 4 + l; n += 1
        return n, o
    print(" chain raw:", chain(b), " chain xor:", chain(b.translate(TBL)), "of", size)
