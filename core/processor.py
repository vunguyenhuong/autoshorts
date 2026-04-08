import os
import sys
import math
import random
import subprocess


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
        valid_exts = ['.mp4', '.mov', '.mkv']
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
                        if ((not skip_merge and duration_mode == 'max') or only_under_1min) and dur >= 59:
                            continue
                        
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
                    
                    # Check limit for Under 1 min mode
                    if duration_mode == 'max':
                        if (current_duration + eff_dur) > 59:
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
        duration_mode = settings.get('duration_mode', 'min')
        only_under_1min = settings.get('only_under_1min', False)
        skip_merge = settings.get('skip_merge', False)
        
        video_pool = []
        discarded_videos = []
        
        # Filtering logic for individual videos: Only filter by duration if strictly requested via checkbox
        if only_under_1min:
            if progress_callback:
                progress_callback(f"🛡️ Bật chế độ lọc nghiêm ngặt (chỉ lấy video < 59s) cho Edit lẻ")
            
            for f in files:
                dur = self.get_video_duration_fast(f)
                if dur >= 59:
                    discarded_videos.append(f)
                    if progress_callback:
                        progress_callback(f"⏭️ Loại bỏ video >= 59s: {os.path.basename(f)}")
                else:
                    video_pool.append(f)
            
            # Move discarded others if any
            if discarded_videos:
                self._move_to_unused(source_folder, discarded_videos, progress_callback)
            
            files = video_pool
        
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
            
        def process_single(idx, f_path):
            if check_cancel and check_cancel():
                return
            
            filename = os.path.basename(f_path)
            output_path = os.path.join(output_folder, filename)
            
            if progress_callback:
                progress_callback(f"Processing {idx}/{total_files}: {filename}")
            
            try:
                # Use existing render_batch with single video
                self.render_batch([f_path], output_path, settings, progress_callback)
                if progress_callback:
                    progress_callback(f"✓ Completed: {filename}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                if progress_callback:
                    progress_callback(f"✗ Failed: {filename} - {str(e)}")
                    
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_single, idx, f_path) for idx, f_path in enumerate(files, 1)]
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
        
        if progress_callback and (duration_mode == 'max' or only_under_1min):
            progress_callback(f"🛡️ Bật chế độ lọc nghiêm ngặt (chỉ lấy video < 59s)")

        for f in files:
            dur = self.get_video_duration_fast(f)
            # Filter condition: Merge mode with 'max' duration OR explicit strict filter
            is_too_long = ((not skip_merge and duration_mode == 'max') or only_under_1min) and dur >= 59
            
            if is_too_long:
                discarded_videos.append(f)
                if progress_callback:
                    progress_callback(f"⏭️ Loại bỏ video >= 59s: {os.path.basename(f)}")
            else:
                video_pool.append(f)
        
        if not video_pool:
            if progress_callback: progress_callback("No valid videos found after filtering.")
            # Move discarded to unused anyway
            if discarded_videos:
                self._move_to_unused(source_folder, discarded_videos, progress_callback)
            return

        if progress_callback:
            progress_callback(f"✅ Đã nhận {len(video_pool)} video hợp lệ sau khi lọc")

        while video_pool:
            if check_cancel and check_cancel(): return

            current_batch_files = []
            current_duration = 0.0
            
            # 1. Select clips for this batch
            pool_idx = 0
            while pool_idx < len(video_pool):
                if check_cancel and check_cancel(): return
                
                f_path = video_pool[pool_idx]
                try:
                    # Quick check duration
                    dur = self.get_video_duration_fast(f_path)
                    
                    # Apply speed to get effective duration
                    eff_speed = settings.get('speed', 1.0)
                    eff_dur = dur / eff_speed
                    
                    # Check selection limits
                    if duration_mode == 'max':
                        # Mode: Under 1 minute (hard limit 59s)
                        if (current_duration + eff_dur) > 59:
                            pool_idx += 1
                            continue
                    
                    # Add the video to batch
                    current_batch_files.append(f_path)
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
                    if progress_callback: progress_callback(f"Error reading {os.path.basename(f_path)}: {e}")
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

            # 2. Render this batch
            output_filename = f"output_{batch_idx:03d}.mp4"
            output_path = os.path.join(output_folder, output_filename)
            
            if progress_callback: progress_callback(f"Rendering {output_filename}...")
            
            try:
                self.render_batch(current_batch_files, output_path, settings, progress_callback)
                if progress_callback: progress_callback(f"Finished {output_filename}")
            except Exception as e:
                import traceback
                traceback.print_exc()
                if progress_callback: progress_callback(f"Failed to render {output_filename}: {e}")
            
            batch_idx += 1
        
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
        
        for video_path in video_pool:
            try:
                video_name = os.path.basename(video_path)
                dest_path = os.path.join(unused_folder, video_name)
                # Check if dest exists to avoid error
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                shutil.move(video_path, dest_path)
                if progress_callback:
                    progress_callback(f"  → Moved: {video_name}")
            except Exception as e:
                if progress_callback:
                    progress_callback(f"  ⚠️ Failed to move {os.path.basename(video_path)}: {e}")
        
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
        Auto-detect available GPU encoder on the system
        Supports: NVIDIA (NVENC), AMD (AMF), Intel (QSV), Apple (VideoToolbox)
        Returns: tuple (encoder_name, preset_args, quality_args) or None if no GPU
        """
        try:
            ffmpeg_exe = self.get_ffmpeg_binary()
            cmd = [ffmpeg_exe, '-hide_banner', '-encoders']
            
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
            encoders_output = result.stdout.lower()
            
            # Check in priority order: NVIDIA > AMD > Intel > Apple
            if 'h264_nvenc' in encoders_output:
                return ('h264_nvenc', ['-preset', 'fast'], ['-cq', '18'])
            
            if 'h264_amf' in encoders_output:
                return ('h264_amf', ['-quality', 'speed'], ['-rc', 'vbr_hq', '-qp_i', '18', '-qp_p', '18'])
            
            if 'h264_qsv' in encoders_output:
                return ('h264_qsv', ['-preset', 'veryfast'], ['-global_quality', '18'])
            
            if 'h264_videotoolbox' in encoders_output:
                return ('h264_videotoolbox', ['-realtime', '1', '-profile:v', 'high'], ['-b:v', '5M'])
            
            return None
            
        except Exception as e:
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

    def render_batch(self, file_paths, output_path, settings, progress_callback):
        """
        Renders the batch using a two-pass approach:
        1. Process each video individually (speed, scale, pad)
        2. Concatenate all processed videos
        This is more reliable than complex filter graphs.
        """
        import subprocess
        import tempfile

        speed = float(settings.get('speed', 1.0))
        sx = float(settings.get('scale_x', 1.0))
        sy = float(settings.get('scale_y', 1.0))
        
        if 'scale' in settings and sx == 1.0 and sy == 1.0:
             val = float(settings['scale'])
             if val != 1.0:
                 sx = val
                 sy = val

        off_x = int(settings.get('offset_x', 0))
        off_y = int(settings.get('offset_y', 0))
        
        overlay_color = settings.get('overlay_color', (0, 0, 0))
        overlay_opacity = settings.get('overlay_opacity', 0)
        
        hflip = settings.get('hflip', False)
        random_color = settings.get('random_color', False)
        film_grain = settings.get('film_grain', False)

        ffmpeg_exe = self.get_ffmpeg_binary()
        if progress_callback:
            progress_callback(f"Using FFmpeg binary: {ffmpeg_exe}")
        
        # Canvas dimensions
        CW, CH = 1080, 1920
        
        # Create temp directory for intermediate files
        temp_dir = tempfile.mkdtemp()
        temp_files = [None] * len(file_paths)  # Pre-allocate to maintain order
        
        def process_single_video(i, f_path):
            try:
                # Probe dimensions and audio
                iw, ih = self._probe_dims(f_path)
                has_audio = self._has_audio_stream(f_path)
                
                # Calculate fit dimensions
                scale_w = CW / iw
                scale_h = CH / ih
                fit_scale = min(scale_w, scale_h)
                
                fit_w = int(iw * fit_scale)
                fit_h = int(ih * fit_scale)
                
                # Apply user stretch
                target_w = int(fit_w * sx)
                target_h = int(fit_h * sy)
                
                # Ensure even
                if target_w % 2 != 0: target_w += 1
                if target_h % 2 != 0: target_h += 1
                
                # Calculate padding (overlay position)
                pad_x = int((CW - target_w) / 2 + off_x)
                pad_y = int((CH - target_h) / 2 + off_y)
                
                # Build filter for this video
                vf_filters = [f"setpts=PTS/{speed}"]
                
                if hflip:
                    if i > 0:
                        import random
                        if random.choice([True, False]):
                            vf_filters.append("hflip")
                    
                if random_color:
                    import random
                    br = round(random.uniform(-0.03, 0.03), 3)
                    con = round(random.uniform(0.95, 1.05), 3)
                    sat = round(random.uniform(0.95, 1.10), 3)
                    vf_filters.append(f"eq=brightness={br}:contrast={con}:saturation={sat}")
                
                if film_grain:
                    vf_filters.append("noise=alls=1:allf=t+u")
                
                vf_filters.append(f"scale={target_w}:{target_h}:flags=lanczos")
                vf = ",".join(vf_filters)
                
                # Audio: speed (only if audio exists)
                if speed > 2.0:
                    af = f"atempo=2.0,atempo={speed/2.0}"
                else:
                    af = f"atempo={speed}"
                
                # Output temp file
                temp_file = os.path.join(temp_dir, f"temp_{i:03d}.mp4")
                
                # Build command with filter_complex for overlay
                gpu_info = self.detect_gpu_encoder()
                
                # Check if we have NVIDIA GPU for hardware acceleration
                use_nvidia_hw = gpu_info and gpu_info[0] == 'h264_nvenc'
                
                if use_nvidia_hw:
                    # NVIDIA GPU: Not using -hwaccel auto because CPU filters (scale, overlay, drawbox)
                    # cause severe PCIe transfer bottlenecks when combined with hardware decoding.
                    cmd = [ffmpeg_exe, "-y", "-i", f_path]
                else:
                    # Other GPU or CPU fallback
                    cmd = [ffmpeg_exe, "-y", "-i", f_path]
                
                base_filter = f"color=s={CW}x{CH}:c=black[bg];[0:v]{vf}[scaled];[bg][scaled]overlay={pad_x}:{pad_y}:shortest=1"
                
                # Phủ màu (Color Overlay)
                if overlay_opacity > 0:
                    alpha = overlay_opacity / 100.0
                    overlay_hex = f"0x{overlay_color[0]:02x}{overlay_color[1]:02x}{overlay_color[2]:02x}"
                    base_filter += f"[base];[base]drawbox=x=0:y=0:w={CW}:h={CH}:color={overlay_hex}@{alpha}:t=fill[v]"
                else:
                    base_filter += "[v]"

                # Build filter_complex based on audio availability
                if has_audio:
                    # Video has audio - apply audio filters
                    filter_complex = f"{base_filter};[0:a]{af}[a]"
                    map_args = ["-map", "[v]", "-map", "[a]"]
                else:
                    # Video has no audio - only process video and add silent audio
                    filter_complex = f"{base_filter};anullsrc=channel_layout=stereo:sample_rate=44100[a]"
                    map_args = ["-map", "[v]", "-map", "[a]"]
                
                # Apply filter_complex and map outputs
                cmd += ["-filter_complex", filter_complex]
                cmd += map_args
                
                base_cmd = cmd.copy()
                
                if gpu_info:
                    encoder_name, preset_args, quality_args = gpu_info
                    
                    if use_nvidia_hw:
                        # Optimized NVENC settings with safer presets to avoid argument errors.
                        video_codec = [
                            '-c:v', 'h264_nvenc',
                            '-preset', 'fast',
                            '-tune', 'hq',
                            '-rc', 'vbr',
                            '-cq', '18',
                            '-b:v', '0',
                            '-maxrate', '15M',
                            '-bufsize', '30M',
                            '-profile:v', 'high',
                            '-spatial_aq', '1',
                            '-temporal_aq', '1',
                            '-rc-lookahead', '10'
                        ]
                    else:
                        video_codec = ['-c:v', encoder_name] + preset_args + quality_args
                else:
                    video_codec = ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18']
                
                cmd = base_cmd + video_codec + ['-pix_fmt', 'yuv420p', "-c:a", "aac", temp_file]
                
                # Execute
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                      startupinfo=startupinfo, encoding='utf-8', errors='replace')
                
                if result.returncode != 0:
                    if gpu_info:
                        # NVIDIA limits user GPUs to 3-5 concurrent streams, causing FFmpeg to fail with out of memory.
                        # We fallback to CPU encoding (libx264) for any streams that exceed the GPU limit.
                        cmd_fallback = base_cmd + ['-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p', '-c:a', 'aac', temp_file]
                        result_fb = subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                               startupinfo=startupinfo, encoding='utf-8', errors='replace')
                        if result_fb.returncode != 0:
                            return i, False, f"GPU Error:\n{result.stderr}\n\nCPU Fallback Error:\n{result_fb.stderr}"
                    else:
                        return i, False, result.stderr
                        
                return i, True, temp_file
            except Exception as e:
                return i, False, str(e)
        
        try:
            # PASS 1: Process each video individually (Concurrently)
            import concurrent.futures
            
            # Use workers from settings (default 4)
            max_parallel = settings.get('workers', 4)
            
            if progress_callback:
                progress_callback(f"Starting {len(file_paths)} jobs on pool of {max_parallel} workers")
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
                futures = []
                for i, f_path in enumerate(file_paths):
                    if progress_callback:
                        progress_callback(f"Queueing video {i+1}/{len(file_paths)}...")
                    futures.append(executor.submit(process_single_video, i, f_path))
                
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    i, success, res = future.result()
                    completed += 1
                    
                    if not success:
                        if progress_callback:
                            progress_callback(f"[Error] Failed to process video {i+1}")
                            progress_callback(res[-500:] if len(res) > 500 else res)
                        raise Exception(f"FFmpeg failed on video {i+1}")
                    
                    temp_files[i] = res
                    if progress_callback:
                        progress_callback(f"✓ Video {completed}/{len(file_paths)} encoded successfully.")
            
            # PASS 2: Concatenate all temp files
                

            
            # PASS 2: Concatenate all temp files
            if progress_callback:
                progress_callback("Concatenating videos...")
            
            # Create concat file list
            concat_file = os.path.join(temp_dir, "concat_list.txt")
            with open(concat_file, "w", encoding="utf-8") as f:
                for temp_file in temp_files:
                    # Use forward slashes and escape special chars
                    safe_path = temp_file.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")
            
            # Concatenate
            cmd = [ffmpeg_exe, "-y", "-f", "concat", "-safe", "0", "-i", concat_file]
            cmd += ["-c", "copy", output_path]
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  startupinfo=startupinfo, encoding='utf-8', errors='replace')
            
            if result.returncode != 0:
                if progress_callback:
                    progress_callback("[Error] Failed to concatenate videos")
                    progress_callback(result.stderr[-500:] if len(result.stderr) > 500 else result.stderr)
                raise Exception("FFmpeg concatenation failed")
            
            if progress_callback:
                progress_callback("✓ Rendering complete!")
                
        except Exception as e:
            if progress_callback:
                progress_callback(f"Render Error: {e}")
            raise e
        finally:
            # Cleanup temp files
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
