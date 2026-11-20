#!/usr/bin/env bash
# Register You-T with the desktop: app-menu entry + icon (needed on Wayland).
# Usage: ./install.sh [path/to/You-T-*.AppImage]
#        ./install.sh --uninstall
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/opt/you-t"
DESKTOP_DIR="$PREFIX/share/applications"
ICON_ROOT="$PREFIX/share/icons/hicolor"
DESKTOP_FILE="$DESKTOP_DIR/you-t.desktop"
SIZES=(16 24 32 48 64 128 256 512)

refresh_caches() {
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -f -t "$ICON_ROOT" >/dev/null 2>&1 || true
    fi
}

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$DESKTOP_FILE"
    rm -rf "$APP_DIR"
    for size in "${SIZES[@]}"; do
        rm -f "$ICON_ROOT/${size}x${size}/apps/you-t.png"
    done
    refresh_caches
    echo "You-T removed from the app menu."
    exit 0
fi

if [ -n "${1:-}" ]; then
    APPIMAGE="$1"
else
    APPIMAGE="$(find "$ROOT/dist" -maxdepth 1 -name 'You-T-*-x86_64.AppImage' -printf '%T@ %p\n' 2>/dev/null \
        | sort -nr | head -n 1 | cut -d' ' -f2-)"
fi

if [ -z "${APPIMAGE:-}" ] || [ ! -f "$APPIMAGE" ]; then
    echo "error: no AppImage found. Build one first (./build.sh) or pass its path." >&2
    exit 1
fi

mkdir -p "$APP_DIR" "$DESKTOP_DIR" "$ICON_ROOT"
install -m 0755 "$APPIMAGE" "$APP_DIR/You-T.AppImage"

# AppImages need libfuse2, which is not installed by default on recent
# Ubuntu. Launch through a wrapper that extracts and runs instead, so the
# app-menu entry works everywhere.
cat > "$APP_DIR/you-t" <<EOF
#!/usr/bin/env bash
export APPIMAGE_EXTRACT_AND_RUN=1
exec "$APP_DIR/You-T.AppImage" "\$@"
EOF
chmod 0755 "$APP_DIR/you-t"

for size in "${SIZES[@]}"; do
    [ -f "$ROOT/assets/icon-$size.png" ] || continue
    install -Dm 0644 "$ROOT/assets/icon-$size.png" \
        "$ICON_ROOT/${size}x${size}/apps/you-t.png"
done

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=You-T
Comment=Download videos from the web
Exec=$APP_DIR/you-t
TryExec=$APP_DIR/you-t
Icon=you-t
Terminal=false
Categories=AudioVideo;Video;
StartupWMClass=You-T
StartupNotify=true
X-GNOME-UsesNotifications=true
EOF

refresh_caches
echo "Installed. You-T should now appear in your app menu with its icon."
echo "Run it from there, or: $APP_DIR/you-t"
