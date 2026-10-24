"""Render the app icon (.ico, PNGs) and the installer's wizard images from assets/icon.svg.
Run after changing the icon (needs PySide6 and Pillow):

    python packaging/build_assets.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform != "win32":  # the offscreen backend has no fonts on Windows; there a window never opens anyway
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "assets" / "icon.svg"
OUT = ROOT / "assets"
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
INK = "#1D1C1A"
PAPER = "#F6F5F2"


def render(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(str(SVG)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


def to_pil(image: QImage) -> Image.Image:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (image.width(), image.height()), bytes(image.constBits()), "raw", "RGBA", 0, 1)


def wizard_image(width: int, height: int) -> QImage:
    """The tall image on the installer's first and last page: paper, icon and name."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(PAPER))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = width * 0.46
    top = height * 0.26
    painter.drawImage(QRectF((width - side) / 2, top, side, side), render(512))
    font = QFont("Segoe UI")
    font.setPixelSize(round(width * 0.12))
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor(INK))
    painter.drawText(QRectF(0, top + side + width * 0.09, width, width * 0.4),
                     Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "Sims 4\nMod Test")
    painter.end()
    return image


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    images = [to_pil(render(s)) for s in ICO_SIZES]
    images[-1].save(OUT / "icon.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=images[:-1])
    render(1024).save(str(OUT / "icon-1024.png"))
    render(256).save(str(OUT / "icon.png"))
    # Inno Setup picks the variant closest to the display scale (100%, 150%, 200%).
    for scale, (w, h) in {100: (164, 314), 150: (246, 471), 200: (328, 628)}.items():
        to_pil(wizard_image(w, h)).convert("RGB").save(OUT / f"wizard-{scale}.bmp")
    for scale, size in {100: 55, 150: 83, 200: 110}.items():
        small = Image.new("RGB", (size, size), "#FFFFFF")
        icon = to_pil(render(size))
        small.paste(icon, (0, 0), icon)
        small.save(OUT / f"wizard-small-{scale}.bmp")
    del app
    print(f"Wrote icons and installer images to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
