import os
import sys
import math
import random
import subprocess
import time
import threading

# Global semaphore to limit concurrent NVENC sessions (GTX 1080 8GB supports 3-5 concurrent streams)
_nvenc_semaphore = threading.Semaphore(3)

# Thread-safe counter for date-based naming across concurrent renders
_date_naming_lock = threading.Lock()
_date_naming_counters = {}  # key: (output_folder, date_str) -> next counter


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

    def _validate_video_file(self, file_path):
        """Quick check that a file is a valid video (has video stream and non-zero size)."""
        try:
            if os.path.getsize(file_path) < 1024:  # Less than 1KB = probably corrupt
                return False
            return self._has_video_stream(file_path)
        except Exception:
            return False

    def _generate_date_filename(self, output_folder):
        """
        Generate a unique filename in ddmmyyNN format.
        Thread-safe: uses a global lock + counter to prevent collisions
        across concurrent render threads.
        Example: 19052601.mp4, 19052602.mp4, ...
        """
        from datetime import datetime
        date_str = datetime.now().strftime("%d%m%y")
        
        with _date_naming_lock:
            key = (os.path.normpath(output_folder), date_str)
            
            if key not in _date_naming_counters:
                # Scan existing files to find the highest existing counter
                existing_max = 0
                try:
                    import re
                    pattern = re.compile(rf'^{re.escape(date_str)}(\d{{2}})\.mp4$', re.IGNORECASE)
                    for fname in os.listdir(output_folder):
                        m = pattern.match(fname)
                        if m:
                            num = int(m.group(1))
                            if num > existing_max:
                                existing_max = num
                except Exception:
                    pass
                _date_naming_counters[key] = existing_max + 1
            
            counter = _date_naming_counters[key]
            _date_naming_counters[key] = counter + 1
        
        filename = f"{date_str}{counter:02d}.mp4"
        return filename

    def scan_folder(self, folder, sort_by_views=True, random_order=True):
        """Scan folder for .mp4 files only, skip fragments and partial downloads"""
        import re
        # Only accept .mp4 files — skip .f137, .f140, .part, .ytdl, .mkv, .webm etc.
        fragment_re = re.compile(r'\.f\d+', re.IGNORECASE)  # Matches .f137, .f140, etc.
        
        files = []
        for f in os.listdir(folder):
            f_lower = f.lower()
            # Must end with .mp4
            if not f_lower.endswith('.mp4'):
                continue
            # Skip fragment/partial files (e.g. "video.f137.mp4", "video.mp4.part")
            if fragment_re.search(f):
                continue
            if '.part' in f_lower or '.ytdl' in f_lower or '.temp' in f_lower:
                continue
            full_path = os.path.join(folder, f)
            if os.path.isfile(full_path):
                files.append(full_path)
        
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
            trim_mode = settings.get('trim_mode', 'none')
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
                        
                        # Apply user trim settings to estimation
                        if trim_mode == 'head_tail':
                            trim_head = float(settings.get('trim_head', 0.0))
                            trim_tail = float(settings.get('trim_tail', 0.0))
                            dur = max(1.0, dur - trim_head - trim_tail)
                        elif trim_mode == 'range':
                            trim_from = float(settings.get('trim_from', 0.0))
                            trim_to = float(settings.get('trim_to', 0.0))
                            if trim_to > trim_from:
                                dur = trim_to - trim_from
                            else:
                                dur = max(1.0, dur - trim_from)
                        elif trim_mode == 'skip_segment':
                            skip_from = float(settings.get('skip_from', 0.0))
                            skip_to = float(settings.get('skip_to', 0.0))
                            if skip_to > skip_from >= 0:
                                skip_to = min(skip_to, dur)
                                dur = max(1.0, skip_from + (dur - skip_to))
                        
                        eff_dur = dur / speed
                        video_pool.append(eff_dur)
                except:
                    pass
            
            valid_files_count = len(video_pool)
            if skip_merge:
                return valid_files_count, valid_files_count

            # 2a. Free mode: merge exactly min_videos videos per clip (no duration limit)
            if duration_mode == 'free':
                if min_videos < 1:
                    return 0, valid_files_count
                est_count = valid_files_count // min_videos
                return est_count, valid_files_count

            # 2b. Standard: Simulated greedy batching by duration
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
        if not os.path.exists(source_folder):
            if progress_callback: progress_callback(f"⚠️ Folder nguồn không tồn tại: {source_folder}")
            return
        
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        
        files = self.scan_folder(source_folder, sort_by_views=False)  # No need to sort
        if not files:
            if progress_callback: progress_callback("No videos found in source folder.")
            return

        # Filtering logic for individual videos
        only_under_1min = settings.get('only_under_1min', False)
        trim_long_videos = settings.get('trim_long_videos', False)
        max_input_duration = float(settings.get('max_input_duration', 0) or 0)
        speed = float(settings.get('speed', 1.0))
        # trim_dur là thời lượng input (trước khi áp speed).
        # Để output đúng = max_input_duration giây, cần trim input = max_input_duration * speed.
        max_trim_input = max_input_duration * speed if max_input_duration > 0 else 0
        
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
                    item = {"path": f, "dur": trim_dur, "trim_dur": trim_dur, "original_dur": dur}
                    item = self._apply_trim_settings(item, dur, settings)
                    # Apply max_trim_input on top if set and stricter
                    if max_trim_input > 0 and item.get('trim_dur', trim_dur) > max_trim_input:
                        item['trim_dur'] = max_trim_input
                        item['dur'] = max_trim_input
                    video_pool.append(item)
                    if progress_callback:
                        progress_callback(f"✂️ Cắt ngẫu nhiên đuôi video dài {dur:.1f}s giữ lại {trim_dur:.1f}s: {os.path.basename(f)}")
                else:
                    item = {"path": f, "dur": dur}
                    item = self._apply_trim_settings(item, dur, settings)
                    # Apply max_trim_input if set and video is longer
                    if max_trim_input > 0 and dur > max_trim_input:
                        item['trim_dur'] = max_trim_input
                        item['dur'] = max_trim_input
                        if progress_callback:
                            progress_callback(f"✂️ Cắt video {dur:.1f}s → {max_input_duration:.0f}s output (max đầu vào): {os.path.basename(f)}")
                    video_pool.append(item)
            
            # Move discarded others if any
            if discarded_videos:
                self._move_to_unused(source_folder, discarded_videos, progress_callback)
            
            files = video_pool
        else:
            files = []
            for f in self.scan_folder(source_folder, sort_by_views=False):
                dur = self.get_video_duration_fast(f)
                item = {"path": f, "dur": dur}
                item = self._apply_trim_settings(item, dur, settings)
                # Apply max_trim_input if set and video is longer
                if max_trim_input > 0 and dur > max_trim_input:
                    item['trim_dur'] = max_trim_input
                    item['dur'] = max_trim_input
                    if progress_callback:
                        progress_callback(f"✂️ Cắt video {dur:.1f}s → {max_input_duration:.0f}s output (max đầu vào): {os.path.basename(f)}")
                files.append(item)
        
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
            
            # Generate filename based on naming mode
            date_naming = settings.get('date_naming', False)
            if date_naming:
                filename = self._generate_date_filename(output_folder)
            else:
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
        
        if not os.path.exists(source_folder):
            if progress_callback: progress_callback(f"⚠️ Folder nguồn không tồn tại: {source_folder}")
            return
        
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
                discarded_videos.append({"path": f, "dur": dur})
                if progress_callback:
                    progress_callback(f"⏭️ Loại bỏ video >= 60s: {os.path.basename(f)}")
            else:
                trim_long_videos = settings.get('trim_long_videos', False)
                # In 'free' mode: never auto-trim long videos. Keep original duration.
                if dur >= 60 and duration_mode != 'free' and (trim_long_videos or not skip_merge):
                    trim_dur = random.uniform(30.0, 55.0)
                    item = {"path": f, "dur": trim_dur, "trim_dur": trim_dur, "original_dur": dur}
                    item = self._apply_trim_settings(item, dur, settings)
                    video_pool.append(item)
                    if progress_callback:
                        progress_callback(f"✂️ Cắt ngẫu nhiên đuôi video dài {dur:.1f}s giữ lại {trim_dur:.1f}s: {os.path.basename(f)}")
                else:
                    item = {"path": f, "dur": dur}
                    item = self._apply_trim_settings(item, dur, settings)
                    video_pool.append(item)
        
        if not video_pool:
            if progress_callback: progress_callback("No valid videos found after filtering.")
            # Move discarded to unused anyway
            if discarded_videos:
                self._move_to_unused(source_folder, discarded_videos, progress_callback)
            return

        if progress_callback:
            progress_callback(f"✅ Đã nhận {len(video_pool)} video hợp lệ sau khi lọc")

        batches_to_render = []

        # ── FREE MODE: merge exactly min_videos videos per clip ─────────────────
        if duration_mode == 'free':
            if min_videos < 1:
                if progress_callback:
                    progress_callback("⚠️ Số video gộp phải >= 1, bỏ qua.")
                return

            if progress_callback:
                progress_callback(
                    f"🔗 Gộp thường (không cắt): mỗi clip ghép đúng {min_videos} video."
                )

            # Split pool into fixed-size batches of min_videos
            i = 0
            while i + min_videos <= len(video_pool):
                if check_cancel and check_cancel(): return
                batch = video_pool[i:i + min_videos]
                batches_to_render.append((batch_idx, batch))
                batch_idx += 1
                i += min_videos

            # Remaining videos (< min_videos) go to discarded
            remainder = video_pool[i:]
            if remainder:
                discarded_videos.extend(remainder)
                if progress_callback:
                    progress_callback(
                        f"📦 {len(remainder)} video thừa (không đủ {min_videos}) → unused_videos."
                    )

        # ── STANDARD MODE: greedy batching by target duration ────────────────────
        else:
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
            
        # Collect paths used in rendering so we don't move them prematurely
        rendered_paths = set()
        for _, batch_files in batches_to_render:
            for f_item in batch_files:
                p = f_item['path'] if isinstance(f_item, dict) else f_item
                rendered_paths.add(os.path.normpath(p))

        def render_single_batch(b_idx, batch_files):
            if check_cancel and check_cancel(): return
            
            first_item = batch_files[0]
            first_path = first_item['path'] if isinstance(first_item, dict) else first_item
            
            # Generate filename based on naming mode
            date_naming = settings.get('date_naming', False)
            if date_naming:
                output_filename = self._generate_date_filename(output_folder)
            else:
                base_name = os.path.splitext(os.path.basename(first_path))[0]
                prefix = settings.get('output_prefix', '')
                if prefix:
                    output_filename = f"{prefix} - {base_name}.mp4"
                else:
                    output_filename = f"{base_name}.mp4"
                
            output_path = os.path.join(output_folder, output_filename)
            
            # Prevent accidental overwrites (for non-date mode, date mode handles it internally)
            if not date_naming:
                counter = 1
                base_name_for_dedup = os.path.splitext(output_filename)[0]
                while os.path.exists(output_path):
                    output_filename = f"{base_name_for_dedup}_{counter}.mp4"
                    output_path = os.path.join(output_folder, output_filename)
                    counter += 1
            
            if progress_callback: progress_callback(f"Rendering Batch {b_idx}: {output_filename}...")
            
            try:
                # Validate all input files before rendering
                valid_files = []
                for f_item in batch_files:
                    f_path = f_item['path'] if isinstance(f_item, dict) else f_item
                    if self._validate_video_file(f_path):
                        valid_files.append(f_item)
                    elif progress_callback:
                        progress_callback(f"⚠️ Bỏ qua file lỗi/corrupt: {os.path.basename(f_path)}")
                
                if not valid_files:
                    if progress_callback: progress_callback(f"⚠️ Batch {b_idx}: Không có file hợp lệ, bỏ qua.")
                    return
                
                self.render_batch(valid_files, output_path, settings, progress_callback)
                if progress_callback: progress_callback(f"✅ Finished {output_filename}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                if progress_callback: progress_callback(f"❌ Failed to render {output_filename}: {e}")
                # Clean up partial output file
                try:
                    if os.path.exists(output_path):
                        os.remove(output_path)
                except Exception:
                    pass

        if batches_to_render:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(render_single_batch, b_idx, b_files) for b_idx, b_files in batches_to_render]
                concurrent.futures.wait(futures)
        
        # Move all unused videos AFTER all rendering is complete (avoids file locking)
        video_pool.extend(discarded_videos)
        if video_pool:
            self._move_to_unused(source_folder, video_pool, progress_callback)

    def _apply_trim_settings(self, f_item, dur, settings):
        """
        Apply trim settings to a video item dict.
        Returns updated f_item with trim_start and/or trim_dur fields.

        trim_mode: 'none' | 'head_tail' | 'range'
        - head_tail: trim_head (s from start), trim_tail (s from end)
        - range:     trim_from (start second), trim_to (end second, 0=until end)
        """
        trim_mode = settings.get('trim_mode', 'none')
        if trim_mode == 'none' or dur <= 0:
            return f_item

        item = dict(f_item) if isinstance(f_item, dict) else {'path': f_item, 'dur': dur}

        if trim_mode == 'head_tail':
            trim_head = float(settings.get('trim_head', 0.0))
            trim_tail = float(settings.get('trim_tail', 0.0))
            trim_start = max(0.0, trim_head)
            effective_dur = dur - trim_head - trim_tail
            if effective_dur <= 0:
                # If trim removes everything, keep at least 1 second
                effective_dur = max(1.0, dur - trim_head)
            item['trim_start'] = trim_start
            item['trim_dur'] = effective_dur
            item['dur'] = effective_dur

        elif trim_mode == 'range':
            trim_from = float(settings.get('trim_from', 0.0))
            trim_to = float(settings.get('trim_to', 0.0))
            trim_start = max(0.0, trim_from)
            if trim_to > trim_start:
                effective_dur = trim_to - trim_start
            else:
                # trim_to == 0 or invalid → keep until end
                effective_dur = max(1.0, dur - trim_start)
            item['trim_start'] = trim_start
            item['trim_dur'] = effective_dur
            item['dur'] = effective_dur

        elif trim_mode == 'skip_segment':
            skip_from = float(settings.get('skip_from', 0.0))
            skip_to = float(settings.get('skip_to', 0.0))
            # Validate: skip_to must be > skip_from and <= dur
            if skip_to <= skip_from or skip_from < 0:
                return item  # Invalid range → do nothing
            skip_to = min(skip_to, dur)
            # Effective duration = part before skip + part after skip
            part1_dur = skip_from          # 0 → skip_from
            part2_dur = dur - skip_to      # skip_to → end
            effective_dur = max(1.0, part1_dur + part2_dur)
            item['skip_from'] = skip_from
            item['skip_to'] = skip_to
            item['dur'] = effective_dur
            # Mark as skip mode so renderer knows to use 2-segment concat
            item['trim_mode'] = 'skip_segment'

        return item

    def _move_to_unused(self, source_folder, video_pool, progress_callback):
        """Helper to move videos to unused category with retry for locked files"""
        import shutil
        unused_count = len(video_pool)
        if progress_callback:
            progress_callback(f"📦 Moving {unused_count} unused video(s) to 'unused_videos' folder...")
        
        unused_folder = os.path.join(source_folder, "unused_videos")
        if not os.path.exists(unused_folder):
            os.makedirs(unused_folder)
        
        moved = 0
        for f_item in video_pool:
            try:
                video_path = f_item['path'] if isinstance(f_item, dict) else f_item
                if not os.path.exists(video_path):
                    continue  # Already moved or deleted
                video_name = os.path.basename(video_path)
                dest_path = os.path.join(unused_folder, video_name)
                # Check if dest exists to avoid error
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                # Retry move up to 3 times (file may still be locked by ffmpeg)
                for attempt in range(3):
                    try:
                        shutil.move(video_path, dest_path)
                        moved += 1
                        if progress_callback:
                            progress_callback(f"  → Moved: {video_name}")
                        break
                    except PermissionError:
                        if attempt < 2:
                            time.sleep(1)  # Wait for file lock to release
                        else:
                            raise
            except Exception as e:
                err_path = f_item['path'] if isinstance(f_item, dict) else f_item
                if progress_callback:
                    progress_callback(f"  ⚠️ Failed to move {os.path.basename(err_path)}: {e}")
        
        if progress_callback:
            progress_callback(f"✅ Đã di chuyển {moved}/{unused_count} video thừa vào: {unused_folder}")

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
                probe_cmd = [ffmpeg_exe, '-y', '-hide_banner', '-f', 'lavfi', '-i', 'color=s=64x64:d=0.04', '-c:v', 'h264_nvenc', '-f', 'null', '-']
                probe_res = subprocess.run(
                    probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, startupinfo=startupinfo, encoding='utf-8', errors='replace'
                )
                if probe_res.returncode == 0:
                    self._gpu_cache = {
                        'encoder':      'h264_nvenc',
                        'preset_args':  ['-preset', 'p4', '-tune', 'hq'],
                        'quality_args': ['-rc', 'vbr', '-cq', '23', '-b:v', '0'],
                        'hwaccel_args': [],
                        'decoder_arg':  [],
                        'is_nvidia':    True
                    }
                    return self._gpu_cache
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

    def _expand_skip_segments(self, file_paths):
        """
        Expand any f_item with trim_mode='skip_segment' into two consecutive f_items:
          - Part 1: trim_start=0, trim_dur=skip_from  (keeps 0→skip_from)
          - Part 2: trim_start=skip_to, no trim_dur   (keeps skip_to→end)
        This allows the normal render pipeline to handle skip_segment transparently.
        """
        expanded = []
        for f_item in file_paths:
            if not isinstance(f_item, dict):
                expanded.append(f_item)
                continue
            if f_item.get('trim_mode') != 'skip_segment':
                expanded.append(f_item)
                continue

            skip_from = f_item.get('skip_from', 0.0)
            skip_to = f_item.get('skip_to', 0.0)
            f_path = f_item['path']

            # Part 1: from beginning to skip_from
            if skip_from > 0:
                part1 = dict(f_item)
                part1.pop('trim_mode', None)
                part1.pop('skip_from', None)
                part1.pop('skip_to', None)
                part1['trim_start'] = 0.0
                part1['trim_dur'] = skip_from
                part1['dur'] = skip_from
                expanded.append(part1)

            # Part 2: from skip_to to end
            part2 = dict(f_item)
            part2.pop('trim_mode', None)
            part2.pop('skip_from', None)
            part2.pop('skip_to', None)
            part2['trim_start'] = skip_to
            # No trim_dur → keep until end
            if 'trim_dur' in part2:
                del part2['trim_dur']
            if skip_to > 0:
                part2['dur'] = max(1.0, f_item.get('dur', 30.0) - skip_from + 1.0)
            expanded.append(part2)

        return expanded

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
            
            # Expand any skip_segment items into 2 sub-inputs (part1 + part2)
            file_paths = self._expand_skip_segments(file_paths)

            # Check which files have audio
            need_silent_audio = any(not self._has_audio_stream(f['path'] if isinstance(f, dict) else f) for f in file_paths)
            
            # Build the FFmpeg command
            cmd = [ffmpeg_exe, "-y"]
            cmd_cpu = [ffmpeg_exe, "-y"]
            
            # Add inputs to commands
            for i, f_item in enumerate(file_paths):
                f_path = f_item['path'] if isinstance(f_item, dict) else f_item
                trim_dur = f_item.get('trim_dur', None) if isinstance(f_item, dict) else None
                trim_start = f_item.get('trim_start', None) if isinstance(f_item, dict) else None
                
                # Add probesize and analyzeduration for robust decoding
                for c in [cmd, cmd_cpu]:
                    c.extend(["-probesize", "50M", "-analyzeduration", "100M"])
                    if trim_start and trim_start > 0:
                        c.extend(["-ss", str(trim_start)])
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
            
            enc_name = gpu_info.get('encoder', 'h264_nvenc') if gpu_info else 'h264_nvenc'
            preset_args = gpu_info.get('preset_args', ['-preset', 'p4', '-tune', 'hq']) if gpu_info else ['-preset', 'p4', '-tune', 'hq']
            quality_args = gpu_info.get('quality_args', ['-rc', 'vbr', '-cq', '23', '-b:v', '0']) if gpu_info else ['-rc', 'vbr', '-cq', '23', '-b:v', '0']

            # Complete the GPU command
            cmd.extend([
                "-filter_complex", filter_complex_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", enc_name,
                *preset_args,
                *quality_args,
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                output_path
            ])
            
            # Complete the CPU fallback command
            cmd_cpu.extend([
                "-filter_complex", filter_complex_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                output_path
            ])
            
            if progress_callback:
                progress_callback(f"🚀 [GPU] Đang tiến hành gộp và scale video 1080x1920 (Stretch & Perfect Crop) bằng {enc_name}...")
            
            # Use NVENC semaphore to prevent exceeding GPU session limit
            gpu_acquired = _nvenc_semaphore.acquire(timeout=600)  # Wait up to 10 min for a slot
            try:
                if not gpu_acquired:
                    if progress_callback:
                        progress_callback("⚠️ GPU đang bận (quá nhiều phiên NVENC), chuyển sang CPU...")
                    raise RuntimeError("NVENC semaphore timeout")
                
                res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, timeout=600)
            except subprocess.TimeoutExpired:
                if progress_callback:
                    progress_callback("⚠️ FFmpeg GPU timeout sau 10 phút, chuyển sang CPU...")
                res = type('obj', (object,), {'returncode': -1, 'stderr': 'Timeout'})()  # Fake failed result
            finally:
                if gpu_acquired:
                    _nvenc_semaphore.release()
            
            if res.returncode != 0:
                if progress_callback:
                    progress_callback("⚠️ GPU NVENC failed, falling back to CPU (libx264) direct render...")
                try:
                    res_cpu = subprocess.run(cmd_cpu, capture_output=True, text=True, startupinfo=startupinfo, timeout=900)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("FFmpeg CPU cũng bị timeout sau 15 phút. Video có thể bị lỗi.")
                if res_cpu.returncode != 0:
                    raise RuntimeError(f"Direct Concat failed on both GPU and CPU. CPU Error: {res_cpu.stderr[-500:]}")
            
            if progress_callback:
                progress_callback("✅ Gộp và xử lý video hoàn tất thành công!")
            return True
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"❌ GPU Render Error: {e}")
            raise e

    def render_batch(self, file_paths, output_path, settings, progress_callback):
        """
        Renders the batch using FFmpeg directly.
        Tries GPU (NVENC) first, falls back to CPU (libx264) — all via FFmpeg.
        """
        use_gpu_setting = settings.get('use_gpu', True)
        
        if use_gpu_setting:
            try:
                if progress_callback:
                    progress_callback(f"🚀 Using GPU FFmpeg Engine (High Performance)")
                return self.render_batch_gpu_ffmpeg(file_paths, output_path, settings, progress_callback)
            except Exception as e:
                if progress_callback:
                    progress_callback(f"⚠️ GPU Pipeline failed: {e}. Falling back to CPU FFmpeg...")
        
        # CPU-only FFmpeg fallback (no MoviePy)
        if progress_callback:
            progress_callback(f"🖥️ Using CPU FFmpeg Engine (libx264)")
        return self.render_batch_cpu_ffmpeg(file_paths, output_path, settings, progress_callback)

    def render_batch_cpu_ffmpeg(self, file_paths, output_path, settings, progress_callback):
        """
        Pure FFmpeg CPU rendering pipeline (libx264). Same logic as GPU pipeline
        but without NVENC encoder.
        """
        import random as py_random
        
        ffmpeg_exe = self.get_ffmpeg_binary()
        
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
        
        CW, CH = 1080, 1920
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        try:
            if progress_callback:
                progress_callback("🎬 [CPU] Đang khởi tạo bộ trộn video (Single-pass CPU Merger)...")
            
            # Expand any skip_segment items into 2 sub-inputs (part1 + part2)
            file_paths = self._expand_skip_segments(file_paths)

            # Check which files have audio
            need_silent_audio = any(not self._has_audio_stream(f['path'] if isinstance(f, dict) else f) for f in file_paths)
            
            # Build the FFmpeg command
            cmd = [ffmpeg_exe, "-y"]
            
            # Add inputs
            for i, f_item in enumerate(file_paths):
                f_path = f_item['path'] if isinstance(f_item, dict) else f_item
                trim_dur = f_item.get('trim_dur', None) if isinstance(f_item, dict) else None
                trim_start = f_item.get('trim_start', None) if isinstance(f_item, dict) else None
                
                cmd.extend(["-probesize", "50M", "-analyzeduration", "100M"])
                if trim_start and trim_start > 0:
                    cmd.extend(["-ss", str(trim_start)])
                if trim_dur:
                    cmd.extend(["-t", str(trim_dur)])
                cmd.extend(["-i", f_path])
            
            # Add silent dummy audio source if needed
            if need_silent_audio:
                cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
            
            filter_complex_parts = []
            
            # Construct filters for each input video
            for i, f_item in enumerate(file_paths):
                f_path = f_item['path'] if isinstance(f_item, dict) else f_item
                
                # Determine audio source
                has_audio = self._has_audio_stream(f_path)
                if has_audio:
                    audio_src = f"{i}:a"
                else:
                    audio_src = f"{len(file_paths)}:a"
                
                # Video filters
                v_filters = []
                
                # 1. Crop and stretch/scale to 1080x1920
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
            
            # Complete the CPU command
            cmd.extend([
                "-filter_complex", filter_complex_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                output_path
            ])
            
            if progress_callback:
                progress_callback("🖥️ [CPU] Đang tiến hành gộp và scale video 1080x1920 bằng libx264...")
            
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, timeout=900)
            except subprocess.TimeoutExpired:
                raise RuntimeError("FFmpeg CPU bị timeout sau 15 phút. Video có thể bị lỗi.")
            
            if res.returncode != 0:
                raise RuntimeError(f"CPU render failed: {res.stderr[-500:]}")
            
            if progress_callback:
                progress_callback("✅ Gộp và xử lý video hoàn tất thành công!")
            return True
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"❌ CPU Render Error: {e}")
            raise e