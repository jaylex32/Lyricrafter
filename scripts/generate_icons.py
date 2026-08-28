from __future__ import annotations

from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app" / "assets" / "lyricrafter.svg"
OUTPUT = ROOT / "packaging" / "icons"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)


def render(size: int) -> Path:
    renderer = QSvgRenderer(QByteArray(SOURCE.read_bytes()))
    if not renderer.isValid():
        raise RuntimeError(f"Unable to render {SOURCE}")
    image = QImage(QSize(size, size), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    path = OUTPUT / f"lyricrafter-{size}.png"
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"Unable to save {path}")
    return path


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    paths = [render(size) for size in SIZES]
    master = Image.open(paths[-2]).convert("RGBA")
    master.save(
        OUTPUT / "lyricrafter.ico",
        format="ICO",
        sizes=[(size, size) for size in SIZES if size <= 256],
    )
    try:
        master.save(OUTPUT / "lyricrafter.icns", format="ICNS")
    except (KeyError, OSError):
        pass
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
