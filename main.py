"""You-T — desktop video downloader (yt-dlp + PySide6)."""

import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

import runtime
from ui import DARK_QSS, MainWindow

SYSTEM_SCHEMA_DIR = "/usr/share/glib-2.0/schemas"


def _repair_gsettings_env() -> None:
    """Undo snap-injected GSettings env poisoning.

    VS Code's snap wrapper rewrites GSETTINGS_SCHEMA_DIR / XDG_DATA_DIRS to a
    stale schema cache. Qt's GTK3 platform theme then asks GTK for the
    'antialiasing' key, which is missing there, and GLib aborts the whole
    process before the window can open.
    """
    orig_xdg = os.environ.get("XDG_DATA_DIRS_VSCODE_SNAP_ORIG")
    if orig_xdg:
        os.environ["XDG_DATA_DIRS"] = orig_xdg
        os.environ.pop("XDG_DATA_DIRS_VSCODE_SNAP_ORIG", None)

    if "GSETTINGS_SCHEMA_DIR_VSCODE_SNAP_ORIG" in os.environ:
        orig = os.environ.pop("GSETTINGS_SCHEMA_DIR_VSCODE_SNAP_ORIG", "")
        if orig:
            os.environ["GSETTINGS_SCHEMA_DIR"] = orig
        else:
            os.environ.pop("GSETTINGS_SCHEMA_DIR", None)

    # Generic guard: a custom schema dir that shadows system schemas without
    # the keys GTK needs → fall back to the system schema dir.
    schema_dir = os.environ.get("GSETTINGS_SCHEMA_DIR")
    if (
        schema_dir
        and schema_dir.rstrip("/") != SYSTEM_SCHEMA_DIR
        and os.path.isdir(SYSTEM_SCHEMA_DIR)
    ):
        compiled = Path(schema_dir) / "gschemas.compiled"
        try:
            data = compiled.read_bytes() if compiled.is_file() else b""
        except OSError:
            data = b""
        if b"antialiasing" not in data:
            os.environ["GSETTINGS_SCHEMA_DIR"] = SYSTEM_SCHEMA_DIR


def main() -> None:
    _repair_gsettings_env()
    runtime.setup_environment()

    app = QApplication(sys.argv)
    app.setOrganizationName("You-T")
    app.setApplicationName("You-T")
    app.setApplicationDisplayName("You-T")
    app.setApplicationVersion(runtime.app_version())
    app.setDesktopFileName("you-t")

    icon = runtime.icon_path()
    if icon:
        app.setWindowIcon(QIcon(str(icon)))

    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
