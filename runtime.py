"""Runtime helpers for source runs and frozen (PyInstaller) builds."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

APP_NAME = "You-T"
FFMPEG_EXE = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """Directory holding bundled resources (assets, VERSION, bin/)."""
    if is_frozen():
        # onefile: temp extraction dir; onedir (PyInstaller >= 6): _internal
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def bundled_bin_dir() -> Path:
    return resource_dir() / "bin"


def ffmpeg_location() -> Optional[str]:
    """Directory containing ffmpeg, preferring the bundled copy."""
    candidate = bundled_bin_dir() / FFMPEG_EXE
    if candidate.is_file():
        return str(candidate.parent)

    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    return None


def setup_environment() -> None:
    """Put the bundled ffmpeg/ffprobe on PATH for yt-dlp and subprocesses."""
    bin_dir = bundled_bin_dir()
    if not bin_dir.is_dir():
        return
    current = os.environ.get("PATH", "")
    if str(bin_dir) not in current.split(os.pathsep):
        os.environ["PATH"] = str(bin_dir) + (os.pathsep + current if current else "")


def app_version(default: str = "dev") -> str:
    for candidate in (
        resource_dir() / "VERSION",
        Path(__file__).resolve().parent / "VERSION",
    ):
        try:
            value = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return default


def icon_path() -> Optional[Path]:
    assets = resource_dir() / "assets"
    for name in ("icon.png", "icon-512.png", "icon-256.png"):
        candidate = assets / name
        if candidate.is_file():
            return candidate
    return None
