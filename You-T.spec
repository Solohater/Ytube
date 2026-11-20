# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for You-T.

Linux/macOS default: one-dir build (fast startup, used for AppImage).
Windows: set YOUT_ONEFILE=1 for a portable single .exe.
"""

import importlib.util
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)
ONEFILE = os.environ.get("YOUT_ONEFILE") == "1"
IS_WINDOWS = os.name == "nt"

datas = [
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "VERSION"), "."),
]
binaries = []
hiddenimports = []

for package in ("yt_dlp", "secretstorage"):
    if importlib.util.find_spec(package) is None:
        continue
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

vendor = ROOT / "vendor" / "ffmpeg"
for name in ("ffmpeg.exe", "ffprobe.exe") if IS_WINDOWS else ("ffmpeg", "ffprobe"):
    candidate = vendor / name
    if candidate.is_file():
        binaries.append((str(candidate), "bin"))

exe_kwargs = {
    "name": "You-T",
    "debug": False,
    "bootloader_ignore_signals": False,
    "strip": False,
    "upx": True,
    "upx_exclude": [],
    "runtime_tmpdir": None,
    "console": False,
    "disable_windowed_traceback": False,
    "argv_emulation": False,
    "target_arch": None,
    "codesign_identity": None,
    "entitlements_file": None,
}

if IS_WINDOWS:
    exe_kwargs["icon"] = str(ROOT / "assets" / "icon.ico")
    version_file = ROOT / "tools" / "version_info.txt"
    if version_file.is_file():
        exe_kwargs["version"] = str(version_file)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        **exe_kwargs,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **exe_kwargs,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="You-T",
    )
