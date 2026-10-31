
import PyInstaller.__main__
import os
import shutil

# Clean previous builds
if os.path.exists('build'):
    shutil.rmtree('build')
if os.path.exists('dist'):
    shutil.rmtree('dist')

# Define build arguments
args = [
    'main.py',
    '--name=AutoTiktok',
    '--onefile',
    '--windowed',
    '--icon=icons/icon.ico',
    '--add-data=icons;icons',  # Include icons folder
    '--collect-all=selenium',  # Collect all selenium submodules, data, and binaries
    '--collect-all=yt_dlp',    # Collect yt_dlp package
    '--collect-all=trio',      # Collect all trio submodules, data, and binaries
    '--collect-all=trio_websocket', # Collect all trio-websocket submodules, data, and binaries
    '--collect-all=faster_whisper', # Collect faster_whisper assets (silero_vad_v6.onnx, etc.)
    '--collect-all=ctranslate2',    # Collect ctranslate2 binaries and models
    '--collect-all=onnxruntime',    # Collect onnxruntime binaries
    '--clean',
    '--noconfirm',
    # Exclude unnecessary heavy modules if not used
    '--exclude-module=tkinter',
    '--exclude-module=PySide6',
    '--exclude-module=shiboken6',
]

print("Starting build process...")
PyInstaller.__main__.run(args)
print("Build complete! Check 'dist' folder.")