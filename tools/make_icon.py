#!/usr/bin/env python3
"""Render assets/icon.svg into PNGs and a multi-size Windows .ico.

Run with the project venv:  ./venv/bin/python tools/make_icon.py
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SVG = ASSETS / "icon.svg"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def render(renderer: QSvgRenderer, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def write_ico(path: Path, images: list[QImage]) -> None:
    """Pack PNG-encoded frames into an ICO (PNG-in-ICO, Vista+)."""
    payloads: list[bytes] = []
    for image in images:
        tmp = path.with_suffix(f".{image.width()}.tmp.png")
        image.save(str(tmp), "PNG")
        payloads.append(tmp.read_bytes())
        tmp.unlink()

    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = bytearray()
    for image, payload in zip(images, payloads):
        dim = 0 if image.width() >= 256 else image.width()
        entries += struct.pack(
            "<BBBBHHII", dim, dim, 0, 0, 1, 32, len(payload), offset
        )
        offset += len(payload)
    path.write_bytes(header + bytes(entries) + b"".join(payloads))


def main() -> int:
    if not SVG.is_file():
        print(f"missing {SVG}", file=sys.stderr)
        return 1

    app = QGuiApplication(sys.argv)  # noqa: F841 (needed by Qt internals)
    renderer = QSvgRenderer(QByteArray(SVG.read_bytes()))
    if not renderer.isValid():
        print(f"invalid SVG: {SVG}", file=sys.stderr)
        return 1

    rendered: dict[int, QImage] = {}
    for size in SIZES:
        image = render(renderer, size)
        rendered[size] = image
        image.save(str(ASSETS / f"icon-{size}.png"), "PNG")
    rendered[512].save(str(ASSETS / "icon.png"), "PNG")

    ico_frames = [rendered[s] for s in (16, 24, 32, 48, 64, 128, 256)]
    write_ico(ASSETS / "icon.ico", ico_frames)
    print(f"wrote {len(SIZES)} PNGs and assets/icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
