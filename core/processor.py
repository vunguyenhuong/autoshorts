import os
import sys
import math
import random
import subprocess
import time


class ShortsProcessor:
    def __init__(self):
        self.download_history = None
        self._duration_cache = {} # path -> (mtime, duration)
        self._load_download_history()
    
    def _load_download_history(self):
        """Load download history to access view counts"""
        try:
            from core.downloader import DownloadHistory
            self.download_history = DownloadHistory()
        except:
            self.download_history = None

    def get_video_view_count(self, video_path):
        """Extract view count from download history based on video ID in filename"""
        if not self.download_history:
            return 0
        
        try:
            import re
            # Extract video ID from filename pattern: "Title [VIDEO_ID].ext"
            filename = os.path.basename(video_path)
            match = re.search(r'\[([a-zA-Z0-9_-]+)\]', filename)
            if match:
                video_id = match.group(1)
                # Search through all channels for this video ID
                for channel_key, channel_data in self.download_history.history.items():
                    if isinstance(channel_data, dict):
                        view_counts = channel_data.get('view_counts', {})
                        for video_url, view_count in view_counts.items():
                            if video_id in video_url:
                                return view_count
        except:
            pass
        return 0

    def scan_folder(self, folder, sort_by_views=True, random_order=True):
        """Scan folder and optionally sort by view count or randomize"""
        valid_exts = ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4a']
        files = [
            os.path.join(folder, f) for f in os.listdir(folder) 
            if os.path.splitext(f)[1].lower() in valid_exts
        ]
        
        if sort_by_views:
            # Sort by view count (highest first)
            files_with_views = [(f, self.get_video_view_count(f)) for f in files]
            files_with_views.sort(key=lambda x: x[1], reverse=True)
            files = [f for f, _ in files_with_views]
        elif random_order:
            # Randomize video order (old behavior)
            random.shuffle(files)
        else:
            # Stable alphabetical order (useful for estimation)
            files.sort()
        
        return files

    def get_video_duration_fast(self, file_path):
        """Fast duration extraction with caching implementation"""
        # 0. Check cache
        try:
            mtime = os.path.getmtime(file_path)
            if file_path in self._duration_cache:
                cached_mtime, cached_dur = self._duration_cache[file_path]
                if cached_mtime == mtime:
                    return cached_dur
        except:
            pass

        import subprocess
        import re
        
        ffmpeg_exe = self.get_ffmpeg_binary()
        
        # Try to find ffprobe
        ffprobe_exe = None
        if "ffmpeg.exe" in ffmpeg_exe:
            cand = ffmpeg_exe.replace('ffmpeg.exe', 'ffprobe.exe')
            if os.path.exists(cand): ffprobe_exe = cand
        elif "ffmpeg" in ffmpeg_exe and os.sep in ffmpeg_exe: # path/to/ffmpeg
            cand = ffmpeg_exe.replace('ffmpeg', 'ffprobe')
            if os.path.exists(cand): ffprobe_exe = cand
            
        # 1. Try ffprobe if found or system path
        if not ffprobe_exe:
            # Check system ffprobe
            try:
                subprocess.run(['ffprobe', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ffprobe_exe = 'ffprobe'
            except:
                pass

        if ffprobe_exe:
            try:
                cmd = [ffprobe_exe, '-v', 'error', '-show_entries', 'format=duration', 
                       '-of', 'default=noprint_wrappers=1:nokey=1', file_path]
                
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
                
                if result.returncode == 0 and result.stdout.strip():
                    dur = float(result.stdout.strip())
                    return self._cache_duration(file_path, dur)
            except Exception as e:
                pass
        
        # 2. Fallback to ffmpeg -i parsing
        try:
            cmd = [ffmpeg_exe, '-i', file_path]
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            # ffmpeg writes info to stderr
            result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, encoding='utf-8', errors='replace')
            
            # Look for "Duration: 00:00:05.50,"
            output = result.stderr
            matcher = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}\.\d+)", output)
            if matcher:
                h = int(matcher.group(1))
                m = int(matcher.group(2))
                s = float(matcher.group(3))
                dur = h*3600 + m*60 + s
                return self._cache_duration(file_path, dur)
        except Exception as e:
            print(f"Error getting duration for {file_path}: {e}")
            pass

        # 3. Cache result before returning
        try:
            self._duration_cache[file_path] = (os.path.getmtime(file_path), 0.0)
        except:
            pass
        return 0.0

    def _cache_duration(self, file_path, duration):
        """Internal helper to save duration to cache"""
        try:
            self._duration_cache[file_path] = (os.path.getmtime(file_path), duration)
        except:
            pass
        return duration

    def estimate_compilations(self, source_folder, settings):
        """
        Estimate how many compilation videos will be created by simulating the batching logic.
        """
        try:
            sort_by_views = settings.get('sort_by_views', True)
            # Use stable order (no random shuffle) for estimation to prevent jitter
            files = self.scan_folder(source_folder, sort_by_views=sort_by_views, random_order=False)
            if not files:
                return 0, 0
            
            speed = settings.get('speed', 1.0)
            target_duration = settings.get('target_duration', 55)
            min_videos = settings.get('min_videos', 1)
            duration_mode = settings.get('duration_mode', 'min')
            only_under_1min = settings.get('only_under_1min', False)
            skip_merge = settings.get('skip_merge', False)

            # 1. First pass: Filter and get effective durations
            video_pool = []
            for f_path in files:
                try:
                    dur = self.get_video_duration_fast(f_path)
                    if dur > 0:
                        # Pre-filter large videos if strict mode or Under 1 min mode is on
                        if only_under_1min and dur >= 60:
                            continue
                            
                        trim_long_videos = settings.get('trim_long_videos', False)
                        # In 'free' mode, keep video as-is (no trimming forced).
                        # Only trim if explicitly requested or in 'max'/'min' modes (not skip_merge).
                        if dur >= 60 and duration_mode != 'free' and (trim_long_videos or not skip_merge):
                            dur = 45.0  # Estimation average for trimmed videos
                        
                        eff_dur = dur / speed
                        video_pool.append(eff_dur)
                except:
                    pass
            
            valid_files_count = len(video_pool)
            if skip_merge:
                return valid_files_count, valid_files_count

            # 2. Second pass: Simulated greedy batching
            est_count = 0
            # Work on a copy of the pool
            pool = video_pool.copy()
            
            while pool:
                current_batch_count = 0
                current_duration = 0.0
                
                # Try to fill a batch
                idx = 0
                batch_indices = []
                while idx < len(pool):
                    eff_dur = pool[idx]
                    
                    # Check limit for Under 1 min mode only
                    if duration_mode == 'max':
                        if (current_duration + eff_dur) > 59.9:
                            idx += 1
                            continue
                    
                    # Add to simulated batch
                    current_duration += eff_dur
                    current_batch_count += 1
                    batch_indices.append(idx)
                    
                    # If batch is "complete"
                    if current_duration >= target_duration and current_batch_count >= min_videos:
                        break
                    idx += 1
                
                # Validate batch (using same logic as process_compilations)
                min_required = min(30, target_duration * 0.4)
                if current_batch_count >= min_videos and current_duration >= min_required:
                    # Success batch
                    est_count += 1
                    # Remove used indices from pool (in reverse order)
                    for i in reversed(batch_indices):
                        pool.pop(i)
                else:
                    # Failed batch - discard the first video in the pool and try again
                    pool.pop(0)

            return est_count, valid_files_count
        except Exception as e:
            print(f"Estimation error: {e}")
            return 0, 0 

    def process_individual_videos(self, source_folder, output_folder, settings, progress_callback=None, check_cancel=None):
        """
        Process each video individually without merging.
        Applies speed, scale, and position effects to each video.
        """
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        
        files = self.scan_folder(source_folder, sort_by_views=False)  # No need to sort
        if not files:
            if progress_callback: progress_callback("No videos found in source folder.")
            return

        # Filtering logic for individual videos
        only_under_1min = settings.get('only_under_1min', False)
        trim_long_videos = settings.get('trim_long_videos', False)
        
        video_pool = []
        discarded_videos = []
        
        # Filtering logic for individual videos
        if only_under_1min or trim_long_videos:
            if progress_callback and only_under_1min:
                progress_callback(f"🛡️ Bật chế độ lọc nghiêm ngặt (chỉ lấy video < 60s) cho Edit lẻ")
            
            for f in files:
                dur = self.get_video_duration_fast(f)
                if only_under_1min and dur >= 60:
                    discarded_videos.append(f)
                    if progress_callback:
                        progress_callback(f"⏭️ Loại bỏ video >= 60s: {os.path.basename(f)}")
                elif trim_long_videos and dur >= 60:
                    trim_dur = random.uniform(30.0, 55.0)
                    video_pool.append({"path": f, "dur": trim_dur, "trim_dur": trim_dur, "original_dur": dur})
                    if progress_callback:
                        progress_callback(f"✂️ Cắt ngẫu nhiên đuôi video dài {dur:.1f}s giữ lại {trim_dur:.1f}s: {os.path.basename(f)}")
                else:
                    video_pool.append({"path": f, "dur": dur})
            
            # Move discarded others if any
            if discarded_videos:
                self._move_to_unused(source_folder, discarded_videos, progress_callback)
            
            files = video_pool
        else:
            files = [{"path": f, "dur": self.get_video_duration_fast(f)} for f in files]
        
        if not files:
            if progress_callback: progress_callback("No valid videos found after filtering.")
            return
        
        total_files = len(files)
        if progress_callback:
            progress_callback(f"Found {total_files} videos to process individually")
        import concurrent.futures
        
        # Determine number of concurrent workers
        max_workers = settings.get('workers', settings.get('max_concurrent_videos', 4))
        
        if progress_callback:
            progress_callback(f"🚀 Chạy đa luồng: Xuất {max_workers} video cùng lúc")
            
        def process_single(idx, f_item):
            if check_cancel and check_cancel():
                return
            
            f_path = f_item['path'] if isinstance(f_item, dict) else f_item
            filename = os.path.basename(f_path)
            
            prefix = settings.get('output_prefix', '')
            if prefix:
                filename = f"{prefix} - {filename}"
                
            output_path = os.path.join(output_folder, filename)
            
            if progress_callback:
                progress_callback(f"Processing {idx}/{total_files}: {filename}")
            
            try:
                # Use existing render_batch with single video
                self.render_batch([f_item], output_path, settings, progress_callback)
                if progress_callback:
                    progress_callback(f"✓ Completed: {filename}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                if progress_callback:
                    progress_callback(f"✗ Failed: {filename} - {str(e)}")
                    
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_single, idx, f_item) for idx, f_item in enumerate(files, 1)]
            concurrent.futures.wait(futures)
        
        if progress_callback:
            progress_callback(f"✓ All {total_files} videos processed successfully!")


    def process_compilations(self, source_folder, output_folder, settings, progress_callback=None, check_cancel=None):
        """
        Main runner.
        settings: {
            'speed': float,
            'scale': float, # 1.05 for 105%
            'offset_x': int,
            'offset_y': int,
            'skip_merge': bool  # If True, process videos individually
        }
        """
        # Check if skip merge is enabled
        if settings.get('skip_merge', False):
            return self.process_individual_videos(source_folder, output_folder, settings, progress_callback, check_cancel)
        
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)

        # Get sort preference from settings
        sort_by_views = settings.get('sort_by_views', True)  # Default to sort by views
        files = self.scan_folder(source_folder, sort_by_views=sort_by_views)
        
        if not files:
            if progress_callback: progress_callback("No videos found in source folder.")
            return
        
        if progress_callback:
            sort_method = "sorted by view count (highest first)" if sort_by_views else "randomly shuffled"
            progress_callback(f"📊 Videos {sort_method}")
        
        # Get target duration from settings (default to 55 seconds)
        target_duration = settings.get('target_duration', 55)
        min_videos = settings.get('min_videos', 2)
        if progress_callback:
            progress_callback(f"🎯 Target compilation length: {target_duration} seconds (min {min_videos} videos)")

        batch_idx = 1
        
        # PRE-FILTERING: Filter video pool based on duration if strict mode is on
        video_pool = []
        discarded_videos = []
        
        duration_mode = settings.get('duration_mode', 'min')
        only_under_1min = settings.get('only_under_1min', False)
        skip_merge = settings.get('skip_merge', False) # Should be false here
        
        if progress_callback and only_under_1min:
            progress_callback(f"🛡️ Bật chế độ lọc nghiêm ngặt (chỉ lấy video < 60s)")

        for f in files:
            dur = self.get_video_duration_fast(f)
            
            if only_under_1min and dur >= 60:
                discarded_videos.append(f)
                if progress_callback:
                    progress_callback(f"⏭️ Loại bỏ video >= 60s: {os.path.basename(f)}")
            else:
                trim_long_videos = settings.get('trim_long_videos', False)
                # In 'free' mode: never auto-trim long videos. Keep original duration.
                if dur >= 60 and duration_mode != 'free' and (trim_long_videos or not skip_merge):
                    trim_dur = random.uniform(30.0, 55.0)
                    video_pool.append({"path": f, "dur": trim_dur, "trim_dur": trim_dur, "original_dur": dur})
                    if progress_callback:
                        progress_callback(f"✂️ Cắt ngẫu nhiên đuôi video dài {dur:.1f}s giữ lại {trim_dur:.1f}s: {os.path.basename(f)}")
                else:
                    video_pool.append({"path": f, "dur": dur})
        
        if not video_pool:
            if progress_callback: progress_callback("No valid videos found after filtering.")
            # Move discarded to unused anyway
            if discarded_videos:
                self._move_to_unused(source_folder, discarded_videos, progress_callback)
            return

        if progress_callback:
            progress_callback(f"✅ Đã nhận {len(video_pool)} video hợp lệ sau khi lọc")

        batches_to_render = []
        while video_pool:
            if check_cancel and check_cancel(): return

            current_batch_files = []
            current_duration = 0.0
            
            # 1. Select clips for this batch
            pool_idx = 0
            while pool_idx < len(video_pool):
                if check_cancel and check_cancel(): return
                
                f_item = video_pool[pool_idx]
                try:
                    f_path = f_item['path'] if isinstance(f_item, dict) else f_item
                    dur = f_item['dur'] if isinstance(f_item, dict) else self.get_video_duration_fast(f_path)
                    
                    # Apply speed to get effective duration
                    eff_speed = settings.get('speed', 1.0)
                    eff_dur = dur / eff_speed
                    
                    # Check selection limits
                    if duration_mode == 'max':
                        # Mode: Under 1 minute (hard limit 59.9s)
                        if (current_duration + eff_dur) > 59.9:
                            pool_idx += 1
                            continue
                    # In 'free' mode: no upper cap, just fill until target_duration is hit
                    
                    # Add the video to batch
                    current_batch_files.append(f_item)
                    current_duration += eff_dur
                    video_pool.pop(pool_idx)
                    
                    if progress_callback: 
                        progress_callback(f"Adding to Video {batch_idx}: {os.path.basename(f_path)} (Total: {current_duration:.1f}s)")
                    
                    # Stop if reached target
                    if current_duration >= target_duration and len(current_batch_files) >= min_videos:
                        if progress_callback:
                            progress_callback(f"Batch {batch_idx} complete at {current_duration:.1f}s")
                        break
                        
                except Exception as e:
                    err_path = f_item['path'] if isinstance(f_item, dict) else f_item
                    if progress_callback: progress_callback(f"Error reading {os.path.basename(err_path)}: {e}")
                    video_pool.pop(pool_idx) # Skip bad file

            # Check if we actually added any videos to this batch
            if not current_batch_files:
                # No combinations found - we're done
                if progress_callback: 
                    progress_callback(f"No more valid combinations found.")
                break
            
            # Check if batch meets minimum requirement
            # Accept batches that are at least 30 seconds OR 40% of target (whichever is lower)
            min_required = min(30, target_duration * 0.4)
            
            if current_duration < min_required or len(current_batch_files) < min_videos:
                if progress_callback: 
                    reason = f"only {current_duration:.1f}s (need {min_required:.0f}s)"
                    if len(current_batch_files) < min_videos:
                        reason = f"only {len(current_batch_files)} videos (requires {min_videos})"
                    progress_callback(f"Last batch failed: {reason}. Skipping first video.")
                # Discard first video and return others to pool
                first_failed = current_batch_files.pop(0)
                discarded_videos.append(first_failed)
                video_pool.extend(current_batch_files)
                continue

            batches_to_render.append((batch_idx, current_batch_files))
            batch_idx += 1
            
        # 2. Render all batches in parallel
        import concurrent.futures
        max_workers = settings.get('workers', settings.get('max_concurrent_videos', 4))
        
        if progress_callback and batches_to_render:
            progress_callback(f"🚀 Chạy đa luồng: Xuất {max_workers} luồng merge cùng lúc (Tổng {len(batches_to_render)} video)")
            
        def render_single_batch(b_idx, batch_files):
            if check_cancel and check_cancel(): return
            
            first_item = batch_files[0]
            first_path = first_item['path'] if isinstance(first_item, dict) else first_item
            base_name = os.path.splitext(os.path.basename(first_path))[0]
            
            prefix = settings.get('output_prefix', '')
            if prefix:
                output_filename = f"{prefix} - {base_name}.mp4"
            else:
                output_filename = f"{base_name}.mp4"
                
            output_path = os.path.join(output_folder, output_filename)
            
            # Prevent accidental overwrites
            counter = 1
            while os.path.exists(output_path):
                output_filename = f"{base_name}_{counter}.mp4"
                output_path = os.path.join(output_folder, output_filename)
                counter += 1
            
            if progress_callback: progress_callback(f"Rendering Batch {b_idx}: {output_filename}...")
            
            try:
                self.render_batch(batch_files, output_path, settings, progress_callback)
                if progress_callback: progress_callback(f"Finished {output_filename}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                if progress_callback: progress_callback(f"Failed to render {output_filename}: {e}")

        if batches_to_render:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(render_single_batch, b_idx, b_files) for b_idx, b_files in batches_to_render]
                concurrent.futures.wait(futures)
        
        # Move all unused videos
        video_pool.extend(discarded_videos)
        if video_pool:
            self._move_to_unused(source_folder, video_pool, progress_callback)

    def _move_to_unused(self, source_folder, video_pool, progress_callback):
        """Helper to move videos to unused category"""
        import shutil
        unused_count = len(video_pool)
        if progress_callback:
            progress_callback(f"📦 Moving {unused_count} unused video(s) to 'unused_videos' folder...")
        
        unused_folder = os.path.join(source_folder, "unused_videos")
        if not os.path.exists(unused_folder):
            os.makedirs(unused_folder)
        
        for f_item in video_pool:
            try:
                video_path = f_item['path'] if isinstance(f_item, dict) else f_item
                video_name = os.path.basename(video_path)
                dest_path = os.path.join(unused_folder, video_name)
                # Check if dest exists to avoid error
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                shutil.move(video_path, dest_path)
                if progress_callback:
                    progress_callback(f"  → Moved: {video_name}")
            except Exception as e:
                err_path = f_item['path'] if isinstance(f_item, dict) else f_item
                if progress_callback:
                    progress_callback(f"  ⚠️ Failed to move {os.path.basename(err_path)}: {e}")
        
        if progress_callback:
            progress_callback(f"✅ Moved {unused_count} unused video(s) to: {unused_folder}")

    def get_ffmpeg_binary(self):
        """
        Returns the path to the ffmpeg executable.
        Prioritizes local 'ffmpeg/ffmpeg.exe' if it exists.
        Falls back to imageio_ffmpeg.
        """
        if getattr(sys, 'frozen', False):
            # If frozen (exe), look relative to exe location
            base_path = os.path.dirname(sys.executable)
        else:
            # If script, look relative to script location
            base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
        # Check standard locations
        candidates = [
            os.path.join(base_path, 'ffmpeg', 'bin', 'ffmpeg.exe'),
            os.path.join(base_path, 'ffmpeg', 'ffmpeg.exe'),
            os.path.join(base_path, 'ffmpeg.exe'),
        ]
        
        for path in candidates:
            if os.path.exists(path):
                return path
            
        # Fallback to system path or default
        return "ffmpeg.exe"

    def detect_gpu_encoder(self):
        """
        Auto-detect available GPU encoder on the system.
        Returns dict: {'encoder', 'preset_args', 'quality_args', 'hwaccel_args'} or None.
        """
        if hasattr(self, '_gpu_cache') and self._gpu_cache != 'uncached':
            return self._gpu_cache
        try:
            ffmpeg_exe = self.get_ffmpeg_binary()
            cmd = [ffmpeg_exe, '-hide_banner', '-encoders']
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, startupinfo=startupinfo,
                encoding='utf-8', errors='replace'
            )
            enc = result.stdout.lower()
            if 'h264_nvenc' in enc:
                # Pattern đơn giản hóa, dùng scale_cuda và overlay_cuda
                self._gpu_cache = {
                    'encoder':      'h264_nvenc',
                    'preset_args':  ['-preset', 'p4', '-tune', 'hq'],
                    'quality_args': ['-cq', '23', '-b:v', '0'],
                    'hwaccel_args': ['-hwaccel', 'd3d11va', '-hwaccel_output_format', 'd3d11'],
                    'decoder_arg':  [],
                    'is_nvidia':    True
                }
            elif 'h264_amf' in enc:
                self._gpu_cache = {
                    'encoder':      'h264_amf',
                    'preset_args':  ['-quality', 'speed'],
                    'quality_args': ['-rc', 'vbr_hq', '-qp_i', '23', '-qp_p', '23'],
                    'hwaccel_args': [],
                    'decoder_arg':  [],
                    'is_nvidia':    False
                }
            elif 'h264_qsv' in enc:
                self._gpu_cache = {
                    'encoder':      'h264_qsv',
                    'preset_args':  ['-preset', 'fast'],
                    'quality_args': ['-global_quality', '23'],
                    'hwaccel_args': ['-hwaccel', 'qsv'],
                    'decoder_arg':  [],
                    'is_nvidia':    False
                }
            else:
                self._gpu_cache = None
            return self._gpu_cache
        except Exception:
            self._gpu_cache = None
            return None

    def check_gpu_availability(self):
        """
        Checks if 'h264_nvenc' encoder is available in the selected ffmpeg.
        """
        import subprocess
        ffmpeg_exe = self.get_ffmpeg_binary()
        try:
            cmd = [ffmpeg_exe, "-hide_banner", "-encoders"]
            # startupinfo to hide console window on Windows
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            result = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True,
                startupinfo=startupinfo,
                encoding='utf-8', 
                errors='replace'
            )
            return "h264_nvenc" in result.stdout
        except:
            return False

    def _has_audio_stream(self, file_path):
        """
        Check if video file has an audio stream.
        Returns True if audio exists, False otherwise.
        """
        import subprocess
        ffmpeg_exe = self.get_ffmpeg_binary()
        try:
            cmd = [ffmpeg_exe, "-hide_banner", "-i", file_path]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                startupinfo=startupinfo,
                encoding='utf-8', 
                errors='replace'
            )
            # Check if there's an Audio stream in the output
            return 'Audio:' in result.stderr
        except Exception:
            return False  # Assume no audio on error

    def _has_video_stream(self, file_path):
        """
        Check if video file has a video stream.
        Returns True if video exists, False otherwise.
        """
        import subprocess
        ffmpeg_exe = self.get_ffmpeg_binary()
        try:
            cmd = [ffmpeg_exe, "-hide_banner", "-i", file_path]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                startupinfo=startupinfo,
                encoding='utf-8', 
                errors='replace'
            )
            return 'Video:' in result.stderr
        except Exception:
            return False

    def _probe_dims(self, file_path):
        """
        Probes video dimensions using ffmpeg (since ffprobe might not be aliased).
        Returns (width, height).
        """
        import re
        import subprocess
        ffmpeg_exe = self.get_ffmpeg_binary()
        try:
            # We use ffmpeg -i file.ext to get info. Fast and reliable.
            cmd = [ffmpeg_exe, "-hide_banner", "-i", file_path]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                startupinfo=startupinfo,
                encoding='utf-8', 
                errors='replace'
            )
            # Search for "Video: ..., 1920x1080"
            match = re.search(r'Video:.*, (\d+)x(\d+)', result.stderr)
            if match:
                return int(match.group(1)), int(match.group(2))
        except Exception:
            pass
        return 1080, 1920 # Fallback

    def render_batch_gpu_ffmpeg(self, file_paths, output_path, settings, progress_callback):
        """
        New GPU-accelerated rendering pipeline using FFmpeg directly in a single-pass command.
        """
        import random as py_random
        
        ffmpeg_exe = self.get_ffmpeg_binary()
        temp_dir = os.path.dirname(output_path)
        
        gpu_info = self.detect_gpu_encoder()
        
        speed = float(settings.get('speed', 1.0))
        sx = float(settings.get('scale_x', 1.0))
        sy = float(settings.get('scale_y', 1.0))
        if 'scale' in settings and sx == 1.0 and sy == 1.0:
             val = float(settings['scale'])
             if val != 1.0:
                 sx, sy = val, val

        off_x = int(settings.get('offset_x', 0))
        off_y = int(settings.get('offset_y', 0))
        overlay_color = settings.get('overlay_color', (0, 0, 0))
        overlay_opacity = settings.get('overlay_opacity', 0)
        hflip_enabled = settings.get('hflip', False)
        random_color = settings.get('random_color', False)
        film_grain = settings.get('film_grain', False)
        
        bg_hex = "0x{:02x}{:02x}{:02x}".format(*overlay_color) if overlay_opacity > 0 else "0xf0f0f0"
        
        CW, CH = 1080, 1920 # 1080x1920 as requested by the user
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        try:
            if progress_callback:
                progress_callback("🎬 [GPU] Đang khởi tạo bộ trộn video đơn kỳ (Single-pass GPU Merger)...")
            
            # Check which files have audio
            need_silent_audio = any(not self._has_audio_stream(f['path'] if isinstance(f, dict) else f) for f in file_paths)
            
            # Build the FFmpeg command
            cmd = [ffmpeg_exe, "-y"]
            cmd_cpu = [ffmpeg_exe, "-y"]
            
            # Add inputs to commands
            for i, f_item in enumerate(file_paths):
                f_path = f_item['path'] if isinstance(f_item, dict) else f_item
                trim_dur = f_item.get('trim_dur', None) if isinstance(f_item, dict) else None
                
                # Add probesize and analyzeduration for robust decoding
                for c in [cmd, cmd_cpu]:
                    c.extend(["-probesize", "50M", "-analyzeduration", "100M"])
                    if trim_dur:
                        c.extend(["-t", str(trim_dur)])
                    c.extend(["-i", f_path])
            
            # Add silent dummy audio source if needed
            if need_silent_audio:
                for c in [cmd, cmd_cpu]:
                    c.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
            
            filter_complex_parts = []
            
            # Construct filters for each input video
            for i, f_item in enumerate(file_paths):
                f_path = f_item['path'] if isinstance(f_item, dict) else f_item
                
                # Determine audio source
                has_audio = self._has_audio_stream(f_path)
                if has_audio:
                    audio_src = f"{i}:a"
                else:
                    audio_src = f"{len(file_paths)}:a" # Silent source at the end
                
                # Video filters
                v_filters = []
                
                # 1. Crop and stretch/scale to 1080x1920 (Stretch Perfect Crop)
                crop_scale = f"crop=iw/(1.22*{sx}):ih/(1.11*{sy}):(iw-ow)/2+{off_x}:(ih-oh)/2+{off_y},scale={CW}:{CH},setsar=1"
                v_filters.append(crop_scale)
                
                # 2. PTS / Speed
                if speed != 1.0:
                    v_filters.append(f"setpts={1/speed}*PTS")
                
                # 3. Horizontal flip
                if hflip_enabled and i > 0:
                    if py_random.choice([True, False]):
                        v_filters.append("hflip")
                
                # 4. Random color
                if random_color:
                    b = py_random.uniform(-0.03, 0.03)
                    c = py_random.uniform(0.97, 1.03)
                    v_filters.append(f"eq=brightness={b}:contrast={c}")
                
                # 5. Film grain
                if film_grain:
                    v_filters.append("noise=alls=4:allf=t+u")
                
                # 6. Color overlay
                if overlay_opacity > 0:
                    alpha = overlay_opacity / 100.0
                    overlay_hex = "0x{:02x}{:02x}{:02x}".format(*overlay_color)
                    v_filters.append(f"drawbox=x=0:y=0:w={CW}:h={CH}:color={overlay_hex}@{alpha}:t=fill")
                
                # 7. FPS and format normalization
                v_filters.append("fps=30")
                v_filters.append("format=yuv420p")
                
                v_filter_chain = ",".join(v_filters)
                filter_complex_parts.append(f"[{i}:v]{v_filter_chain}[v{i}]")
                
                # Audio filters
                a_filters = []
                if speed != 1.0:
                    a_filters.append(f"atempo={speed}")
                a_filters.append("aformat=sample_rates=44100:channel_layouts=stereo")
                
                a_filter_chain = ",".join(a_filters)
                filter_complex_parts.append(f"[{audio_src}]{a_filter_chain}[a{i}]")
            
            # Concatenate all inputs
            concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(len(file_paths)))
            concat_filter = f"{concat_inputs}concat=n={len(file_paths)}:v=1:a=1[v][a]"
            filter_complex_parts.append(concat_filter)
            
            filter_complex_str = ";".join(filter_complex_parts)
            
            # Complete the GPU command
            cmd.extend([
                "-filter_complex", filter_complex_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "h264_nvenc", "-preset", "p6",
                "-c:a", "aac", "-b:a", "192k",
                output_path
            ])
            
            # Complete the CPU fallback command
            cmd_cpu.extend([
                "-filter_complex", filter_complex_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                output_path
            ])
            
            if progress_callback:
                progress_callback("🚀 [GPU] Đang tiến hành gộp và scale video 1080x1920 (Stretch & Perfect Crop) bằng NVIDIA NVENC...")
            
            res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo)
            
            if res.returncode != 0:
                if progress_callback:
                    progress_callback("⚠️ GPU NVENC failed, falling back to CPU (libx264) direct render...")
                res_cpu = subprocess.run(cmd_cpu, capture_output=True, text=True, startupinfo=startupinfo)
                if res_cpu.returncode != 0:
                    raise RuntimeError(f"Direct Concat failed on both GPU and CPU. CPU Error: {res_cpu.stderr}")
            
            if progress_callback:
                progress_callback("✅ Gộp và xử lý video hoàn tất thành công!")
            return True
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"❌ GPU Render Error: {e}")
            raise e

    def render_batch(self, file_paths, output_path, settings, progress_callback):
        """
        Renders the batch. 
        Uses GPU-accelerated FFmpeg pipeline if enabled, otherwise falls back to MoviePy.
        """
        use_gpu_setting = settings.get('use_gpu', True)
        
        # If GPU is requested and we are on Windows, use the new high-performance pipeline
        if use_gpu_setting and os.name == 'nt':
            try:
                if progress_callback:
                    progress_callback(f"🚀 Using GPU FFmpeg Engine (High Performance)")
                return self.render_batch_gpu_ffmpeg(file_paths, output_path, settings, progress_callback)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"⚠️ GPU Pipeline failed: {e}. Falling back to MoviePy...")
        
        # Original MoviePy Fallback
        from moviepy import VideoFileClip, ColorClip, CompositeVideoClip, concatenate_videoclips, vfx
        from proglog import ProgressBarLogger
        import tempfile

        class GuiLogger(ProgressBarLogger):
            def __init__(self, ui_callback):
                super().__init__()
                self.ui_callback = ui_callback
                self.last_pct = -1

            def bars_callback(self, bar, attr, value, old_value=None):
                if bar == 'frame_index' and attr == 'index':
                    total = self.bars[bar].get('total')
                    if total:
                        pct = int((value / total) * 100)
                        if pct != self.last_pct and pct % 5 == 0:
                            self.last_pct = pct
                            if self.ui_callback:
                                self.ui_callback(f"  ⏳ Encoding: {pct}%")

            def callback(self, **kw):
                # Optionally pass MoviePy's log messages to the UI
                if 'message' in kw and self.ui_callback:
                    self.ui_callback(kw['message'])

        speed = float(settings.get('speed', 1.0))
        sx = float(settings.get('scale_x', 1.0))
        sy = float(settings.get('scale_y', 1.0))
        if 'scale' in settings and sx == 1.0 and sy == 1.0:
             val = float(settings['scale'])
             if val != 1.0:
                 sx, sy = val, val

        off_x = int(settings.get('offset_x', 0))
        off_y = int(settings.get('offset_y', 0))
        overlay_color = settings.get('overlay_color', (0, 0, 0))
        overlay_opacity = settings.get('overlay_opacity', 0)
        hflip = settings.get('hflip', False)
        
        # Dimensions
        CW, CH = 1080, 1920

        if progress_callback:
            progress_callback(f"🚀 Using MoviePy Engine (Python Native Video Editing)")

        try:
            processed_clips = []
            
            for i, f_item in enumerate(file_paths):
                if progress_callback:
                    progress_callback(f"Processing video {i+1}/{len(file_paths)}...")
                    
                if isinstance(f_item, dict):
                    f_path = f_item['path']
                    trim_dur = f_item.get('trim_dur', None)
                else:
                    f_path = f_item
                    trim_dur = None
                
                clip = VideoFileClip(f_path)
                if trim_dur:
                    clip = clip.subclipped(0, trim_dur)
                    
                # Mirror FX
                if hflip and i > 0:
                    import random
                    if random.choice([True, False]):
                        clip = clip.with_effects([vfx.MirrorX()])
                        
                # Speed FX
                if speed != 1.0:
                    clip = clip.with_speed_scaled(speed)
                    
                # Scaling logic
                iw, ih = clip.size
                scale_x_ratio = CW / iw
                scale_y_ratio = CH / ih
                cover_scale = max(scale_x_ratio, scale_y_ratio)
                
                fit_width = int(iw * cover_scale)
                fit_height = int(ih * cover_scale)
                scaled_width = int(fit_width * sx)
                scaled_height = int(fit_height * sy)
                
                clip = clip.resized(new_size=(scaled_width, scaled_height))
                
                # Centering and Offset
                overlay_x = (CW - scaled_width) // 2 + off_x
                overlay_y = (CH - scaled_height) // 2 + off_y
                
                # Background
                bg_color = overlay_color if overlay_opacity > 0 else (240, 240, 240)
                bg_clip = ColorClip(size=(CW, CH), color=bg_color, duration=clip.duration)
                
                # Composite
                final_clip = CompositeVideoClip([bg_clip, clip.with_position((overlay_x, overlay_y))])
                processed_clips.append(final_clip)

            if progress_callback:
                progress_callback("Merging all clips into final timeline...")
                
            final_video = concatenate_videoclips(processed_clips, method="compose")
            
            # Export Setting
            use_gpu_setting = settings.get('use_gpu', True)
            
            moviepy_logger = GuiLogger(progress_callback)
            
            if use_gpu_setting:
                if progress_callback:
                    progress_callback("  🎮 Exporting using MoviePy NVENC Encoder...")
                ffmpeg_params = ['-cq', '23', '-b:v', '0']
                final_video.write_videofile(
                    output_path, 
                    codec="h264_nvenc", 
                    fps=30, 
                    preset="p1", 
                    ffmpeg_params=ffmpeg_params, 
                    threads=4, 
                    logger=moviepy_logger
                )
            else:
                if progress_callback:
                    progress_callback("  🖥️ Exporting using MoviePy CPU Encoder...")
                final_video.write_videofile(
                    output_path, 
                    codec="libx264", 
                    fps=30, 
                    preset="fast", 
                    threads=4, 
                    logger=moviepy_logger
                )
                
            # Memory Cleanup
            final_video.close()
            for c in processed_clips:
                c.close()
                
            if progress_callback:
                progress_callback("✓ Rendering complete!")
                
        except Exception as e:
            if progress_callback:
                progress_callback(f"[MoviePy Error] Render failed: {str(e)}")
            raise e