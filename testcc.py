"""
CapCut -> MP4 converter (kéo thả nhiều file, chọn thư mục đầu ra)

Cài đặt:
    pip install tkinterdnd2
    + cài FFmpeg (ffmpeg.exe và ffprobe.exe nằm trong PATH
      hoặc để cạnh file capcut_to_mp4.py này)

Chạy:
    python capcut_to_mp4.py
"""
import os
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HERE = Path(__file__).resolve().parent


def find_tool(name):
    exe = name + (".exe" if os.name == "nt" else "")
    # ưu tiên: thư mục ffmpeg cạnh file .py (cả dạng ffmpeg/bin)
    for folder in (HERE / "ffmpeg", HERE / "ffmpeg" / "bin", HERE):
        local = folder / exe
        if local.exists():
            return str(local)
    # tìm sâu hơn trong thư mục ffmpeg (vd: ffmpeg/ffmpeg-7.0-full_build/bin)
    base = HERE / "ffmpeg"
    if base.is_dir():
        for found in base.rglob(exe):
            return str(found)
    return shutil.which(name)


FFMPEG = find_tool("ffmpeg")
FFPROBE = find_tool("ffprobe")


def is_video(path):
    """Dùng ffprobe để kiểm tra file có luồng video đọc được không."""
    r = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, errors="replace", creationflags=NO_WINDOW)
    ok = bool(r.stdout.strip())
    err = (r.stderr or "").strip().splitlines()
    return ok, (err[0] if err else "không có luồng video")


def convert_one(src, dst, reencode=False):
    if not reencode:
        cmd = [FFMPEG, "-y", "-i", str(src), "-c", "copy",
               "-movflags", "+faststart", str(dst)]
    else:
        cmd = [FFMPEG, "-y", "-i", str(src), "-c:v", "libx264", "-crf", "18",
               "-preset", "medium", "-c:a", "aac", "-b:a", "192k",
               "-movflags", "+faststart", str(dst)]
    r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def unique_path(folder, stem):
    out = folder / f"{stem}.mp4"
    i = 1
    while out.exists():
        out = folder / f"{stem}_{i}.mp4"
        i += 1
    return out


class App:
    def __init__(self, root):
        self.root = root
        self.files = []
        self.running = False
        self.out_var = tk.StringVar(value=str(Path.home() / "Videos" / "CapCut_MP4"))
        self.mode_var = tk.StringVar(value="auto")

        root.title("CapCut → MP4")
        root.geometry("720x560")
        root.minsize(600, 460)

        # --- vùng kéo thả / danh sách ---
        top = ttk.Frame(root, padding=10)
        top.pack(fill="both", expand=True)

        hint = ("Kéo thả file hoặc thư mục vào đây" if HAS_DND
                else "Chưa cài tkinterdnd2 (pip install tkinterdnd2) – dùng nút Thêm file")
        self.drop = tk.Label(top, text=hint, relief="groove", bd=2, height=3,
                             bg="#f2f5fa", fg="#355", font=("Segoe UI", 11))
        self.drop.pack(fill="x")

        mid = ttk.Frame(top)
        mid.pack(fill="both", expand=True, pady=8)
        self.listbox = tk.Listbox(mid, selectmode="extended")
        sb = ttk.Scrollbar(mid, command=self.listbox.yview)
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        btns = ttk.Frame(top)
        btns.pack(fill="x")
        ttk.Button(btns, text="Thêm file...", command=self.add_dialog).pack(side="left")
        ttk.Button(btns, text="Thêm thư mục...", command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(btns, text="Xóa đã chọn", command=self.remove_selected).pack(side="left")
        ttk.Button(btns, text="Xóa hết", command=self.clear).pack(side="left", padx=4)
        self.count_lbl = ttk.Label(btns, text="0 file")
        self.count_lbl.pack(side="right")

        # --- thư mục đầu ra ---
        out = ttk.Frame(top)
        out.pack(fill="x", pady=(10, 0))
        ttk.Label(out, text="Thư mục đầu ra:").pack(side="left")
        ttk.Entry(out, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(out, text="Chọn...", command=self.pick_out).pack(side="left")

        # --- chế độ ---
        mode = ttk.Frame(top)
        mode.pack(fill="x", pady=6)
        ttk.Label(mode, text="Chế độ:").pack(side="left")
        ttk.Radiobutton(mode, text="Tự động (copy nhanh, lỗi thì mã hóa lại)",
                        variable=self.mode_var, value="auto").pack(side="left", padx=6)
        ttk.Radiobutton(mode, text="Luôn mã hóa lại H.264",
                        variable=self.mode_var, value="reencode").pack(side="left")

        # --- chạy ---
        self.progress = ttk.Progressbar(top, mode="determinate")
        self.progress.pack(fill="x", pady=(6, 4))
        self.start_btn = ttk.Button(top, text="Chuyển sang MP4", command=self.start)
        self.start_btn.pack(fill="x")
        self.log = tk.Text(top, height=6, state="disabled", bg="#fafafa")
        self.log.pack(fill="x", pady=(8, 0))

        if HAS_DND:
            for w in (self.drop, self.listbox):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)

        if not (FFMPEG and FFPROBE):
            messagebox.showwarning(
                "Thiếu FFmpeg",
                "Không tìm thấy ffmpeg/ffprobe.\nCài FFmpeg và thêm vào PATH, "
                "hoặc đặt ffmpeg.exe + ffprobe.exe cạnh file này.")

    # ---------- quản lý danh sách ----------
    def add_paths(self, paths):
        added = 0
        for p in paths:
            p = Path(p)
            items = [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
            for f in items:
                if f.is_file() and f not in self.files:
                    self.files.append(f)
                    self.listbox.insert("end", str(f))
                    added += 1
        self.update_count()
        return added

    def on_drop(self, event):
        self.add_paths(self.root.tk.splitlist(event.data))

    def add_dialog(self):
        paths = filedialog.askopenfilenames(title="Chọn file (mọi loại, kể cả không có đuôi)")
        if paths:
            self.add_paths(paths)

    def add_folder(self):
        d = filedialog.askdirectory(title="Chọn thư mục chứa file CapCut")
        if d:
            self.add_paths([d])

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            self.listbox.delete(i)
            del self.files[i]
        self.update_count()

    def clear(self):
        self.listbox.delete(0, "end")
        self.files.clear()
        self.update_count()

    def update_count(self):
        self.count_lbl.config(text=f"{len(self.files)} file")

    def pick_out(self):
        d = filedialog.askdirectory(title="Chọn thư mục đầu ra")
        if d:
            self.out_var.set(d)

    def write_log(self, msg):
        def _w():
            self.log.config(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.config(state="disabled")
        self.root.after(0, _w)

    # ---------- xử lý ----------
    def start(self):
        if self.running:
            return
        if not (FFMPEG and FFPROBE):
            messagebox.showerror("Lỗi", "Chưa có FFmpeg.")
            return
        if not self.files:
            messagebox.showinfo("Trống", "Hãy kéo thả hoặc thêm file trước.")
            return
        out_dir = Path(self.out_var.get().strip())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Lỗi", f"Không tạo được thư mục đầu ra:\n{e}")
            return
        self.running = True
        self.start_btn.config(state="disabled")
        self.progress.config(value=0, maximum=len(self.files))
        threading.Thread(target=self.worker, args=(list(self.files), out_dir),
                         daemon=True).start()

    def worker(self, files, out_dir):
        ok = skipped = failed = 0
        force = self.mode_var.get() == "reencode"
        for n, f in enumerate(files, 1):
            self.write_log(f"[{n}/{len(files)}] {f.name}")
            try:
                ok_video, reason = is_video(f)
                if not ok_video:
                    self.write_log("   ↳ Bỏ qua: không đọc được video (có thể bị mã hóa)")
                    self.write_log(f"      Lý do từ ffprobe: {reason}")
                    skipped += 1
                else:
                    dst = unique_path(out_dir, f.stem)
                    success = convert_one(f, dst, reencode=force)
                    if not success and not force:
                        self.write_log("   ↳ Copy lỗi, đang mã hóa lại...")
                        success = convert_one(f, dst, reencode=True)
                    if success:
                        self.write_log(f"   ↳ OK → {dst.name}")
                        ok += 1
                    else:
                        self.write_log("   ↳ Thất bại")
                        failed += 1
                        if dst.exists():
                            dst.unlink()
            except Exception as e:
                self.write_log(f"   ↳ Lỗi: {e}")
                failed += 1
            self.root.after(0, lambda v=n: self.progress.config(value=v))
        self.write_log(f"Xong: {ok} thành công, {skipped} bỏ qua, {failed} lỗi.")
        self.root.after(0, lambda: self.finish(out_dir, ok))

    def finish(self, out_dir, ok):
        self.running = False
        self.start_btn.config(state="normal")
        if ok and messagebox.askyesno("Hoàn tất", f"Đã chuyển {ok} video.\nMở thư mục đầu ra?"):
            try:
                if sys.platform == "win32":
                    os.startfile(out_dir)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(out_dir)])
                else:
                    subprocess.Popen(["xdg-open", str(out_dir)])
            except Exception:
                pass


if __name__ == "__main__":
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    App(root)
    root.mainloop()