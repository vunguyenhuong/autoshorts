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

        successful = [0]
        failed = [0]
        total_files_to_push = 0
        pushed_files = [0]
        
        lock = threading.Lock()
        
        # Tinh tong so file can push de hien thi % chinh xac
        for task in self.tasks:
            # So luong thiet bi * so luong video moix may
            device_count = len(task['devices'])
            total_files_to_push += device_count * task['limit']
            
        if total_files_to_push == 0:
            self.finished.emit(0, 0)
            return
        
        for t_idx, task in enumerate(self.tasks):
            if not self.is_running:
                break
                
            folder = task['folder']
            devices = task['devices']
            limit_per_device = task['limit']
            target_path = '/sdcard/'  # Đã đổi thành /sdcard/ vì / thường bị lỗi hệ thống read-only
            
            self.log_message.emit(f"▶ Bắt đầu Tác vụ {t_idx + 1}: Thư mục '{os.path.basename(folder)}'")
            
            if not os.path.isdir(folder):
                self.log_message.emit(f"❌ Lỗi: Thư mục không tồn tại: {folder}")
                continue
                
            # Lay tat ca file video va sap xep theo ten
            valid_exts = ('.mp4', '.mov', '.avi', '.mkv', '.wmv')
            all_files = []
            try:
                for f in os.listdir(folder):
                    if f.lower().endswith(valid_exts):
                        all_files.append(f)
            except Exception as e:
                self.log_message.emit(f"❌ Lỗi khi đọc thư mục {folder}: {str(e)}")
                continue
                
            # Sap xep file theo ten A-Z (tu nho den lon)
            all_files.sort()
            
            total_available = len(all_files)
            self.log_message.emit(f"🔍 Tìm thấy {total_available} video trong thư mục.")
            
            if total_available == 0:
                self.log_message.emit(f"⚠️ Bỏ qua tác vụ {t_idx + 1} vì không có video hợp lệ.")
                continue
            
            # Thư mục done
            done_folder = os.path.join(folder, "done")
            os.makedirs(done_folder, exist_ok=True)
            
            # Phân chia file cho từng thiết bị
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
                self.log_message.emit(f"⚠️ Không có file nào được cấp phát cho các thiết bị.")
                continue

            def upload_worker(device, device_files):
                self.log_message.emit(f"📱 Thiết bị [{device}]: Bắt đầu truyền {len(device_files)} video...")
                
                # Tạo mục đích
                if target_path and target_path != '/':
                    try:
                        subprocess.run(
                            ['adb', '-s', device, 'shell', 'mkdir', '-p', target_path],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                    except Exception as e:
                        self.log_message.emit(f"⚠️ Lỗi tạo thư mục trên {device}: {e}")
                
                for count, file_name in enumerate(device_files):
                    if not self.is_running:
                        break
                        
                    local_path = os.path.join(folder, file_name)
                    remote_path = f"{target_path.rstrip('/')}/{file_name}"
                    
                    self.progress.emit(f"[Tác vụ {t_idx+1}] Đang đẩy {file_name} -> {device} ({count+1}/{len(device_files)})")
                    
                    try:
                        cmd = ['adb', '-s', device, 'push', local_path, remote_path]
                        proc = subprocess.run(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                        )
                        
                        if proc.returncode == 0:
                            with lock:
                                successful[0] += 1
                            self.log_message.emit(f"  ✅ [{device}] Đã truyền: {file_name}")
                            # Kích hoạt Media Scanner
                            subprocess.run(
                                ['adb', '-s', device, 'shell', 'am', 'broadcast', '-a', 'android.intent.action.MEDIA_SCANNER_SCAN_FILE', '-d', f'file://{remote_path}'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                            )
                            # Move vao done
                            try:
                                shutil.move(local_path, os.path.join(done_folder, file_name))
                            except Exception as e:
                                self.log_message.emit(f"  ⚠️ Lỗi chuyển thư mục done ({file_name}): {str(e)}")
                        else:
                            with lock:
                                failed[0] += 1
                            err_msg = proc.stderr.strip() if proc.stderr else proc.stdout.strip()
                            self.log_message.emit(f"  ❌ [{device}] Lỗi tải {file_name}: {err_msg}")
                            
                    except Exception as e:
                        with lock:
                            failed[0] += 1
                        self.log_message.emit(f"  ❌ [{device}] Lỗi lệnh ADB: {str(e)}")
                        
                    with lock:
                        pushed_files[0] += 1
                        pct = int(pushed_files[0] * 100 / total_files_to_push)
                        self.percent.emit(pct)
                
                self.log_message.emit(f"📱 Thiết bị [{device}]: Hoàn tất.")

            # Chạy song song tất cả các thiết bị trong Tác vụ này
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(device_jobs))) as executor:
                futures = [executor.submit(upload_worker, d, f) for d, f in device_jobs]
                concurrent.futures.wait(futures)
                
        self.log_message.emit("⏹️ Quá trình ADB Push đã kết thúc.")
        self.progress.emit("Hoàn tất!")
        self.percent.emit(100)
        self.finished.emit(successful[0], failed[0])

