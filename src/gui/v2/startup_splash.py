"""Arranque ligero: sólo Qt y stdlib, antes de cargar los módulos de la app."""

import json
import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPalette, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen


BRANDING_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3])) / "assets" / "branding"
ICON_PATH = BRANDING_DIR / "ordenasion-icon.png"
BACKGROUND_PATH = BRANDING_DIR / "ordenasion-startup-background.png"
# Colores iniciales equivalentes a los tokens Fluent; este módulo evita importar
# QFluent y los controladores antes de que el splash haya sido pintado.
STARTUP_COLORS = {
    "light": ("#F3F6FB", "#FFFFFF", "#1A2430", "#40546B"),
    "dark": ("#101827", "#182337", "#F5F9FF", "#B9C8D9"),
}
_STARTUP_FONT_FAMILY = None


def startup_font_family():
    """La fuente incluida funciona incluso antes de importar QFluent."""
    global _STARTUP_FONT_FAMILY
    if _STARTUP_FONT_FAMILY is None:
        font_id = QFontDatabase.addApplicationFont(str(BRANDING_DIR.parent / "fonts" / "Nunito-Regular.ttf"))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        _STARTUP_FONT_FAMILY = families[0] if families else QApplication.font().family()
    return _STARTUP_FONT_FAMILY


def startup_theme_mode(config_path="app_config.json"):
    """Lee únicamente apariencia; no crea ni modifica configuración."""
    try:
        interface = json.loads(Path(config_path).read_text(encoding="utf-8")).get("interface", {})
        mode = str(interface.get("theme_mode", "system")).lower()
        if mode in {"light", "dark", "system"}:
            return mode
        return "dark" if "oscuro" in str(interface.get("theme", "")).lower() else "light"
    except (OSError, ValueError, AttributeError, TypeError):
        return "system"


def effective_startup_theme(mode):
    if mode in {"light", "dark"}:
        return mode
    app = QApplication.instance()
    return "dark" if app and app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"


def apply_startup_palette(app, mode):
    canvas, surface, text, secondary = STARTUP_COLORS[effective_startup_theme(mode)]
    palette = app.palette()
    for role, color in ((QPalette.ColorRole.Window, canvas), (QPalette.ColorRole.Base, surface),
                        (QPalette.ColorRole.Button, surface), (QPalette.ColorRole.WindowText, text),
                        (QPalette.ColorRole.Text, text), (QPalette.ColorRole.ButtonText, text),
                        (QPalette.ColorRole.PlaceholderText, secondary)):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)


def branding_icon():
    return QIcon(str(ICON_PATH))


class FluentStartupSplash(QSplashScreen):
    """Splash estático, cerrado por la primera pintura de la ventana final."""

    finished = pyqtSignal()

    def __init__(self, theme_mode="system"):
        self.theme_mode = effective_startup_theme(theme_mode)
        self._window = None
        self._paint_pending = False
        super().__init__(self._render(), Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowIcon(branding_icon())
        self.setWindowTitle("Ordenasion")
        self.setAccessibleName("Ordenasion")
        self.setAccessibleDescription("Preparando Ordenasion…")

    def _render(self):
        width, height = 560, 340
        ratio = QApplication.instance().devicePixelRatio()
        image = QPixmap(round(width * ratio), round(height * ratio))
        image.setDevicePixelRatio(ratio)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        canvas, _, text, secondary = STARTUP_COLORS[self.theme_mode]
        clipping = QPainterPath()
        clipping.addRoundedRect(QRectF(0, 0, width, height), 18, 18)
        painter.setClipPath(clipping)
        painter.fillRect(0, 0, width, height, QColor(canvas))
        background = QPixmap(str(BACKGROUND_PATH))
        if not background.isNull():
            background = background.scaled(round(width * ratio), round(height * ratio),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            background.setDevicePixelRatio(ratio)
            painter.drawPixmap(round((width - background.width() / ratio) / 2),
                               round((height - background.height() / ratio) / 2), background)
        overlay = QColor(canvas)
        overlay.setAlpha(225 if self.theme_mode == "light" else 155)
        painter.fillRect(0, 0, width, height, overlay)
        icon = branding_icon().pixmap(round(88 * ratio), round(88 * ratio))
        icon.setDevicePixelRatio(ratio)
        painter.drawPixmap(236, 51, icon)
        painter.setPen(QColor(text))
        title_font = QFont(startup_font_family())
        title_font.setPixelSize(32)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.drawText(QRectF(24, 160, width - 48, 48), Qt.AlignmentFlag.AlignCenter, "Ordenasion")
        message_font = QFont(startup_font_family())
        message_font.setPixelSize(15)
        painter.setFont(message_font)
        painter.setPen(QColor(secondary))
        painter.drawText(QRectF(24, 220, width - 48, 32), Qt.AlignmentFlag.AlignCenter, "Preparando Ordenasion…")
        painter.end()
        return image

    def prepare_window(self, window):
        """Oculta la maximización nativa hasta que Qt haya pintado su contenido."""
        self._window = window
        window.setWindowOpacity(0)
        window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched is self._window:
            if event.type() == QEvent.Type.Paint and not self._paint_pending:
                self._paint_pending = True
                # Siguiente vuelta del event loop: el evento y sus hijos ya se
                # han pintado. No hay temporizador de duración artificial.
                QTimer.singleShot(0, self._reveal_window)
            elif event.type() == QEvent.Type.Close:
                self.close()
        return super().eventFilter(watched, event)

    def _reveal_window(self):
        window = self._window
        if window is not None and window.isVisible():
            window.setWindowOpacity(1)
            window.raise_()
            window.activateWindow()
            self.close()
            self.finished.emit()
        else:
            self._paint_pending = False

    def mousePressEvent(self, event):
        # QSplashScreen oculta por defecto al pulsarlo; aquí debe permanecer
        # hasta que la ventana esté lista o el arranque comunique un error.
        event.accept()

    def closeEvent(self, event):
        if self._window is not None:
            self._window.removeEventFilter(self)
            self._window.setWindowOpacity(1)
            self._window = None
        self._paint_pending = False
        super().closeEvent(event)
