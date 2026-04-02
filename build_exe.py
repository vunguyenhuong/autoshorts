
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
    '--clean',
    '--noconfirm',
    # Exclude unnecessary heavy modules if not used
    '--exclude-module=tkinter',
    '--exclude-module=PySide6',
    '--exclude-module=shiboken6',
]

print("🚀 Starting build process...")
PyInstaller.__main__.run(args)
print("✅ Build complete! Check 'dist' folder.")
