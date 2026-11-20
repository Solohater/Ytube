#!/usr/bin/env bash
# Build the Linux app: PyInstaller one-dir bundle + AppImage + tarball.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VERSION="$(tr -d '[:space:]' < VERSION)"
APP="You-T"
ARCH="$(uname -m)"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON="python3"

FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-lgpl.tar.xz"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "error: PyInstaller missing. Run: $PYTHON -m pip install -r requirements-build.txt" >&2
    exit 1
fi

mkdir -p vendor/ffmpeg .cache

if [ ! -x vendor/ffmpeg/ffmpeg ] || [ ! -x vendor/ffmpeg/ffprobe ]; then
    echo "Fetching ffmpeg (LGPL static build)…"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    curl -fL --retry 3 -o "$tmp/ffmpeg.tar.xz" "$FFMPEG_URL"
    tar -xJf "$tmp/ffmpeg.tar.xz" -C "$tmp"
    src="$(find "$tmp" -maxdepth 1 -type d -name 'ffmpeg-*' | head -n 1)"
    install -m 0755 "$src/bin/ffmpeg" "$src/bin/ffprobe" vendor/ffmpeg/
fi

echo "Building $APP $VERSION ($ARCH)…"
rm -rf build dist
YOUT_ONEFILE=0 "$PYTHON" -m PyInstaller --noconfirm --clean You-T.spec

APPDIR="$ROOT/dist/$APP.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" \
         "$APPDIR/usr/share/applications" \
         "$APPDIR/usr/share/icons/hicolor/512x512/apps"

cp -a "dist/$APP" "$APPDIR/usr/bin/$APP"
cp assets/icon-512.png "$APPDIR/you-t.png"
cp assets/icon-512.png "$APPDIR/usr/share/icons/hicolor/512x512/apps/you-t.png"

cat > "$APPDIR/you-t.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=You-T
Comment=Download videos from the web
Exec=You-T
Icon=you-t
Terminal=false
Categories=AudioVideo;Video;
StartupWMClass=You-T
EOF
cp "$APPDIR/you-t.desktop" "$APPDIR/usr/share/applications/you-t.desktop"

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/You-T/You-T" "$@"
EOF
chmod +x "$APPDIR/AppRun"

TOOL=".cache/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    echo "Fetching appimagetool…"
    curl -fL --retry 3 -o "$TOOL" "$APPIMAGETOOL_URL"
    chmod +x "$TOOL"
fi

echo "Packing AppImage…"
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run "$APPDIR" \
    "dist/$APP-$VERSION-$ARCH.AppImage" >/dev/null

tar -C dist -czf "dist/$APP-$VERSION-linux-$ARCH.tar.gz" "$APP"

echo
echo "Done:"
ls -lh "dist/$APP-$VERSION-$ARCH.AppImage" "dist/$APP-$VERSION-linux-$ARCH.tar.gz"
