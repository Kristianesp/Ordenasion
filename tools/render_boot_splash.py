"""Genera packaging/splash.png: la imagen que el ejecutable muestra mientras se descomprime.

Uso: python tools/render_boot_splash.py
Reutiliza el diseño del splash de Qt (tema oscuro) sobre fondo opaco: la ventana
de carga de PyInstaller no garantiza transparencias.
"""

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "1")


def main() -> Path:
    from PyQt6.QtGui import QColor, QPainter, QPixmap
    from PyQt6.QtWidgets import QApplication
    from src.gui.v2.startup_splash import STARTUP_COLORS, FluentStartupSplash

    app = QApplication.instance() or QApplication([])
    splash = FluentStartupSplash("dark")
    image = splash.pixmap()
    opaque = QPixmap(image.size())
    opaque.fill(QColor(STARTUP_COLORS["dark"][0]))
    painter = QPainter(opaque)
    painter.drawPixmap(0, 0, image)
    painter.end()
    target = ROOT / "packaging" / "splash.png"
    assert opaque.save(str(target), "PNG")
    splash.deleteLater()
    app.processEvents()
    return target


if __name__ == "__main__":
    print(main())
