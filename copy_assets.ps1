
$distFolder = "dist"
$fontsSource = "fonts"
$ffmpegSource = "ffmpeg"
$fontsDest = Join-Path $distFolder "fonts"
$ffmpegDest = Join-Path $distFolder "ffmpeg"

Write-Host "Copying assets to dist folder..."

if (Test-Path $fontsSource) {
    Write-Host "   Type 'fonts' found. Copying..."
    Copy-Item -Path $fontsSource -Destination $fontsDest -Recurse -Force
} else {
    Write-Host "   'fonts' folder not found in source!"
}

if (Test-Path $ffmpegSource) {
    Write-Host "   Type 'ffmpeg' found. Copying..."
    Copy-Item -Path $ffmpegSource -Destination $ffmpegDest -Recurse -Force
} else {
    Write-Host "   'ffmpeg' folder not found in source!"
}


# Creates settings folder
$settingsDest = Join-Path $distFolder "settings"
if (-not (Test-Path $settingsDest)) {
    New-Item -ItemType Directory -Force -Path $settingsDest
}

# Copy yt-dlp.exe to settings
$ytdlpSource = "C:\Users\Vu Nguyen Huong\AppData\Local\Programs\Python\Python310\Scripts\yt-dlp.exe"
$ytdlpDest = Join-Path $settingsDest "yt-dlp.exe"

if (Test-Path $ytdlpSource) {
    Write-Host "   Found yt-dlp.exe. Copying to settings..."
    Copy-Item -Path $ytdlpSource -Destination $ytdlpDest -Force
} else {
    Write-Host "   yt-dlp.exe not found at $ytdlpSource"
    # Try looking in current folder
    if (Test-Path "yt-dlp.exe") {
         Copy-Item -Path "yt-dlp.exe" -Destination $ytdlpDest -Force
    }
}

Write-Host "Asset copy complete!"

