# Build the Windows portable app (single You-T.exe) and zip it.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Version = (Get-Content VERSION -Raw).Trim()
$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$FfmpegUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip"

& $Python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller missing. Run: $Python -m pip install -r requirements-build.txt"
}

New-Item -ItemType Directory -Force -Path "vendor/ffmpeg", ".cache" | Out-Null

if (-not (Test-Path "vendor/ffmpeg/ffmpeg.exe")) {
    Write-Host "Fetching ffmpeg (LGPL static build)..."
    $zip = ".cache/ffmpeg-win64-lgpl.zip"
    Invoke-WebRequest -Uri $FfmpegUrl -OutFile $zip
    $tmp = ".cache/ffmpeg"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    Copy-Item (Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName "vendor/ffmpeg/ffmpeg.exe" -Force
    Copy-Item (Get-ChildItem $tmp -Recurse -Filter ffprobe.exe | Select-Object -First 1).FullName "vendor/ffmpeg/ffprobe.exe" -Force
    Remove-Item -Recurse -Force $tmp
}

Write-Host "Building You-T $Version (win64)..."
Remove-Item -Recurse -Force "build", "dist" -ErrorAction SilentlyContinue
$env:YOUT_ONEFILE = "1"
& $Python -m PyInstaller --noconfirm --clean You-T.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$out = "dist/You-T-$Version-win64.zip"
Compress-Archive -Path "dist/You-T.exe" -DestinationPath $out -Force

Write-Host ""
Write-Host "Done:"
Get-ChildItem "dist/You-T.exe", $out | Format-Table Name, Length
