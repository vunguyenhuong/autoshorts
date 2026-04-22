import os
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal

class AdbUploadThread(QThread):
    progress = pyqtSignal(str)          # Thong bao cap nhat tung buoc
    percent = pyqtSignal(int)           # Thanh tien trinh 0-100
    finished = pyqtSignal(int, int)     # successful, failed
    log_message = pyqtSignal(str)       # Log chi tiet ra man hinh
    
    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks
        self.is_running = True
        
    def stop(self):
        self.is_running = False
        
    def run(self):
        import shutil
        import concurrent.futures
        import threading
        import random

        successful = [0]
        failed = [0]
        total_files_to_push = 0
        pushed_files = [0]
        lock = threading.Lock()

        # Tinh tong so file can push de hien thi % chinh xac
        for task in self.tasks:
            device_count = len(task['devices'])
            total_files_to_push += device_count * task['limit']
            
        if total_files_to_push == 0:
            self.finished.emit(0, 0)
            return

        valid_exts = ('.mp4', '.mov', '.avi', '.mkv', '.wmv')

        # -------------------------------------------------------------------
        # Ham push chung - dung cho ca flat/random va paired
        # -------------------------------------------------------------------
        def push_files_to_device(device, device_files, done_folder_path, move_to_done, t_idx):
            """Push danh sach file toi 1 thiet bi. done_folder_path la noi move sau push."""
            self.log_message.emit(f"📱 Thiết bị [{device}]: Bắt đầu truyền {len(device_files)} video...")
            target_path = '/sdcard/'

            if target_path and target_path != '/':
                try:
                    subprocess.run(
                        ['adb', '-s', device, 'shell', 'mkdir', '-p', target_path],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                except Exception as e:
                    self.log_message.emit(f"⚠️ Lỗi tạo thư mục trên {device}: {e}")

            for count, (local_path, file_name) in enumerate(device_files):
                if not self.is_running:
                    break

                remote_path = f"{target_path.rstrip('/')}/{file_name}"
                self.progress.emit(f"[Tác vụ {t_idx+1}] Đang đẩy {file_name} → {device} ({count+1}/{len(device_files)})")

                try:
                    proc = subprocess.run(
                        ['adb', '-s', device, 'push', local_path, remote_path],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    )
                    if proc.returncode == 0:
                        with lock:
                            successful[0] += 1
                        self.log_message.emit(f"  ✅ [{device}] Đã truyền: {file_name}")
                        # Kich hoat Media Scanner
                        subprocess.run(
                            ['adb', '-s', device, 'shell', 'am', 'broadcast', '-a',
                             'android.intent.action.MEDIA_SCANNER_SCAN_FILE',
                             '-d', f'file://{remote_path}'],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                        # Move vao done neu can
                        if move_to_done and done_folder_path:
                            try:
                                shutil.move(local_path, os.path.join(done_folder_path, file_name))
                            except Exception as e:
                                self.log_message.emit(f"  ⚠️ Lỗi chuyển done ({file_name}): {e}")
                    else:
                        with lock:
                            failed[0] += 1
                        self.log_message.emit(f"  ❌ [{device}] Lỗi: {proc.stderr.strip() or proc.stdout.strip()}")
                except Exception as e:
                    with lock:
                        failed[0] += 1
                    self.log_message.emit(f"  ❌ [{device}] Lỗi ADB: {e}")

                with lock:
                    pushed_files[0] += 1
                    self.percent.emit(int(pushed_files[0] * 100 / max(1, total_files_to_push)))

            self.log_message.emit(f"📱 Thiết bị [{device}]: Hoàn tất.")

        # -------------------------------------------------------------------
        # Vong lap tac vu chinh
        # -------------------------------------------------------------------
        for t_idx, task in enumerate(self.tasks):
            if not self.is_running:
                break

            folder = task['folder']
            devices = task['devices']
            limit_per_device = task['limit']

            # Xac dinh scan_mode (ho tro ca field cu scan_recursive)
            scan_mode = task.get('scan_mode', '')
            if not scan_mode:
                scan_mode = 'random' if task.get('scan_recursive', False) else 'flat'

            mode_labels = {
                'flat':   '📁 Folder gốc',
                'paired': '📂 1 Máy → 1 Folder',
                'random': '🔀 Ngẫu nhiên'
            }
            self.log_message.emit(
                f"▶ Bắt đầu Tác vụ {t_idx + 1}: '{os.path.basename(folder)}' "
                f"- Chế độ: {mode_labels.get(scan_mode, scan_mode)}"
            )

            if not os.path.isdir(folder):
                self.log_message.emit(f"❌ Lỗi: Thư mục không tồn tại: {folder}")
                continue

            # ---------------------------------------------------------------
            # MODE: PAIRED - moi thiet bi <-> 1 subfolder tuong ung (A-Z)
            # ---------------------------------------------------------------
            if scan_mode == 'paired':
                device_jobs = []  # list of (device, files, done_folder)
                for device in [d.strip() for d in devices if d.strip()]:
                    safe_device = device.replace(':', '_').replace('/', '_').replace('\\', '_')
                    subfolder_path = os.path.join(folder, safe_device)
                    
                    if not os.path.isdir(subfolder_path):
                        subfolder_path = os.path.join(folder, device)
                        
                    if not os.path.isdir(subfolder_path):
                        self.log_message.emit(
                            f"⚠️ [{device}]: Không tìm thấy thư mục '{safe_device}' tương ứng trong {folder}"
                        )
                        continue
                    
                    try:
                        vids = sorted([
                            f for f in os.listdir(subfolder_path)
                            if os.path.isfile(os.path.join(subfolder_path, f))
                            and f.lower().endswith(valid_exts)
                        ])
                    except Exception as e:
                        self.log_message.emit(f"❌ Lỗi đọc subfolder '{safe_device}': {e}")
                        vids = []

                    files_for_device = [
                        (os.path.join(subfolder_path, f), f) for f in vids[:limit_per_device]
                    ]
                    done_sub = os.path.join(subfolder_path, 'done')
                    os.makedirs(done_sub, exist_ok=True)
                    self.log_message.emit(
                        f"  📂 Folder '{os.path.basename(subfolder_path)}' → [{device}]: {len(files_for_device)} video"
                    )
                    if files_for_device:
                        device_jobs.append((device, files_for_device, done_sub))

                if not device_jobs:
                    self.log_message.emit("⚠️ Không có tác vụ nào hợp lệ.")
                    continue

                with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(device_jobs))) as executor:
                    futures = [
                        executor.submit(push_files_to_device, d, f, done, True, t_idx)
                        for d, f, done in device_jobs
                    ]
                    concurrent.futures.wait(futures)
                continue  # qua task ke tiep

            # ---------------------------------------------------------------
            # MODE: FLAT hoac RANDOM - xay dung pool chung
            # ---------------------------------------------------------------
            all_files = []  # list of (full_path, file_name)
            try:
                if scan_mode == 'random':
                    for root, dirs, files in os.walk(folder):
                        dirs[:] = [d for d in dirs if d.lower() != 'done']
                        for f in files:
                            if f.lower().endswith(valid_exts):
                                all_files.append((os.path.join(root, f), f))
                    random.shuffle(all_files)
                    self.log_message.emit(f"🔀 Ngẫu nhiên: tìm thấy {len(all_files)} video, đã trộn.")
                else:  # flat
                    all_items = sorted(os.listdir(folder))
                    self.log_message.emit(
                        f"📁 Nội dung folder: {all_items[:10]}{'...' if len(all_items) > 10 else ''}"
                    )
                    for f in all_items:
                        full_path = os.path.join(folder, f)
                        if os.path.isfile(full_path) and f.lower().endswith(valid_exts):
                            all_files.append((full_path, f))
            except Exception as e:
                self.log_message.emit(f"❌ Lỗi khi đọc thư mục {folder}: {e}")
                continue

            total_available = len(all_files)
            self.log_message.emit(f"🔍 Tìm thấy {total_available} video.")

            if total_available == 0:
                self.log_message.emit(f"⚠️ Bỏ qua tác vụ {t_idx + 1} vì không có video.")
                continue

            done_folder = os.path.join(folder, 'done')
            move_done = (scan_mode == 'flat')
            if move_done:
                os.makedirs(done_folder, exist_ok=True)

            # Phan chia file cho tung thiet bi
            device_jobs = []
            file_idx = 0
            for device in devices:
                device = device.strip()
                if not device:
                    continue
                device_files = []
                for _ in range(limit_per_device):
                    if file_idx < total_available:
                        device_files.append(all_files[file_idx])
                        file_idx += 1
                if device_files:
                    device_jobs.append((device, device_files))

            if not device_jobs:
                self.log_message.emit("⚠️ Không có file nào được cấp phát.")
                continue

            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(device_jobs))) as executor:
                futures = [
                    executor.submit(push_files_to_device, d, f, done_folder, move_done, t_idx)
                    for d, f in device_jobs
                ]
                concurrent.futures.wait(futures)

        self.log_message.emit("⏹️ Quá trình ADB Push đã kết thúc.")
        self.progress.emit("Hoàn tất!")
        self.percent.emit(100)
        self.finished.emit(successful[0], failed[0])
