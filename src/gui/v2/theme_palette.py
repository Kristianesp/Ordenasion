"""Aplicación del tema: paleta, tema de qfluentwidgets, alturas de control y
ayudantes de widgets (rutas recortadas, fondo del shell).
"""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPalette, QPainter, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)
from qfluentwidgets import Theme, isDarkTheme

from src.utils.app_config import AppConfig, get_app_config

from src.gui.v2.theme_tokens import (
    FluentTokens, _to_theme, current_glass, current_tokens, register_bundled_fonts, typography_scale,
)


_CONTROL_TYPE_NAMES = frozenset(
    {
        "PushButton",
        "PrimaryPushButton",
        "TransparentPushButton",
        "HyperlinkButton",
        "ToggleButton",
        "LineEdit",
        "SearchLineEdit",
        "ComboBox",
        "EditableComboBox",
        "SpinBox",
        "CompactSpinBox",
        "DoubleSpinBox",
    }
)


_SKIP_CONTROL_TYPE_NAMES = frozenset(
    {
        "NavigationToolButton",
        "NavigationPushButton",
        "MinimizeButton",
        "MaximizeButton",
        "CloseButton",
        "ProgressBar",
        "QProgressBar",
        "QScrollBar",
        "QSlider",
    }
)


class OceanBackdrop(QWidget):
    """Mesh estático suavizado, cacheado por tamaño/tema; no difumina controles."""

    def __init__(self, config: AppConfig, parent: QWidget):
        super().__init__(parent)
        self.config = config
        self._cache_key = None
        self._image = QPixmap()
        self.setObjectName("oceanBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        glass = current_glass(tokens)
        ratio = self.devicePixelRatioF()
        key = (self.size(), ratio, tokens.canvas)
        if key != self._cache_key:
            self._cache_key = key
            self._image = QPixmap(round(self.width() * ratio), round(self.height() * ratio))
            self._image.setDevicePixelRatio(ratio)
            self._image.fill(QColor(tokens.canvas))
            painter = QPainter(self._image)
            width, height = self.width(), self.height()
            for (x, y, radius), color in zip(((0.05, 0.12, 0.8), (0.95, 0.28, 0.78), (0.55, 1.1, 0.65)), glass.mesh):
                gradient = QRadialGradient(width * x, height * y, max(width, height) * radius)
                gradient.setColorAt(0, QColor(color))
                transparent = QColor(color)
                transparent.setAlpha(0)
                gradient.setColorAt(1, transparent)
                painter.fillRect(QRectF(0, 0, width, height), gradient)
            painter.end()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._image)


def _config_from_widget(widget: QWidget) -> AppConfig:
    current: QWidget | None = widget
    while current is not None:
        config = getattr(current, "config", None) or getattr(current, "app_config", None)
        if isinstance(config, AppConfig):
            return config
        current = current.parentWidget()
    return get_app_config()


def apply_control_size(widget: QWidget, config: AppConfig | None = None) -> None:
    """Aplica la altura de control canónica a un botón o campo."""
    class_name = widget.__class__.__name__
    if class_name in _SKIP_CONTROL_TYPE_NAMES:
        return
    is_button = isinstance(widget, QAbstractButton)
    is_field = isinstance(widget, (QLineEdit, QComboBox, QAbstractSpinBox))
    if not is_button and not is_field and class_name not in _CONTROL_TYPE_NAMES:
        return
    if widget.minimumHeight() > 50:
        return
    metrics = typography_scale(config or _config_from_widget(widget))
    height = metrics.control_height
    if isinstance(widget, QToolButton) and not widget.text().strip():
        widget.setFixedHeight(height)
        if widget.minimumWidth() <= 48:
            widget.setFixedWidth(height + 4)
        return
    widget.setMinimumHeight(height)
    # Qt deja el máximo en QWIDGETSIZE_MAX; eso no es un techo real.
    if widget.maximumHeight() >= 16777215 or widget.maximumHeight() <= 48:
        widget.setFixedHeight(height)


def apply_control_sizes(root: QWidget, config: AppConfig | None = None) -> None:
    """Recorre un árbol y unifica la métrica de controles."""
    resolved = config or _config_from_widget(root)
    apply_control_size(root, resolved)
    for child in root.findChildren(QWidget):
        apply_control_size(child, resolved)


class ElidedPathLabel(QLabel):
    """Muestra una ruta en una línea, recortada al centro, con tooltip completo."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = text
        self.setWordWrap(False)
        self.setToolTip(text)
        self._update_elision()

    def set_path(self, text: str, tooltip: str | None = None) -> None:
        self._full_text = text
        self.setToolTip(tooltip or text)
        self._update_elision()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._update_elision()

    def _update_elision(self) -> None:
        metrics = QFontMetrics(self.font())
        width = max(16, self.width())
        self.setText(
            metrics.elidedText(
                self._full_text,
                Qt.TextElideMode.ElideMiddle,
                width,
            )
        )


def bind_path_tooltip(field: QLineEdit) -> None:
    """El campo muestra la ruta; el tooltip siempre lleva el valor completo."""

    def _sync(text: str) -> None:
        field.setToolTip(text)

    field.textChanged.connect(_sync)
    field.setToolTip(field.text())


def apply_elided_path(label: QLabel, text: str, tooltip: str | None = None) -> None:
    """Aplica recorte central y tooltip a una etiqueta de ruta existente."""
    if isinstance(label, ElidedPathLabel):
        label.set_path(text, tooltip)
        return
    label.setWordWrap(False)
    label.setToolTip(tooltip or text)
    metrics = QFontMetrics(label.font())
    width = max(16, label.width())
    label.setText(
        metrics.elidedText(text, Qt.TextElideMode.ElideMiddle, width)
    )


def apply_fluent_theme(config: AppConfig) -> FluentTokens:
    """Aplica tema, acento y tipografía a la aplicación, solo si cambian.

    qfluentwidgets re-aplica el QSS de todos sus widgets en setTheme y en
    setThemeColor; se hace una única pasada, y diferida (``lazy``) para los
    que no están visibles: se actualizan al pintarse. Los estilos propios de
    los controles van como QSS personalizado (setCustomStyleSheet), así que
    esa pasada no los pierde.
    """
    from qfluentwidgets import qconfig
    from qfluentwidgets.common.style_sheet import updateStyleSheet

    register_bundled_fonts()
    mode = config.get_theme_mode()
    accent = config.get_accent_color()
    theme = _to_theme(mode)
    app = QApplication.instance()
    if app is not None and app.styleSheet():
        # Un QSS global (p. ej. de una ventana heredada) taparía la paleta Fluent.
        app.setStyleSheet("")
    previous_dark = isDarkTheme()
    previous_color = QColor(qconfig.get(qconfig.themeColor))
    color_changed = QColor(accent).isValid() and previous_color != QColor(accent)
    if color_changed:
        qconfig.set(qconfig.themeColor, QColor(accent), save=False)
    # setTheme resuelve AUTO; comparar después decide si hay que repintar.
    qconfig.set(qconfig.themeMode, theme, False)
    if theme == Theme.AUTO:
        qconfig.theme = Theme.AUTO  # vuelve a detectar el esquema del sistema
    if color_changed or isDarkTheme() != previous_dark or not getattr(apply_fluent_theme, "_applied", False):
        lazy = getattr(apply_fluent_theme, "_applied", False)
        try:
            updateStyleSheet(lazy=lazy)
        except RuntimeError:
            # qfluentwidgets recorre un WeakKeyDictionary: si el recolector
            # libera widgets (diálogos cerrados) a mitad, se reintenta una vez.
            import gc

            gc.collect()
            updateStyleSheet(lazy=lazy)
        qconfig.themeChangedFinished.emit()
    apply_fluent_theme._applied = True

    if app is not None:
        metrics = typography_scale(config)
        font = QFont()
        if metrics.family:
            font.setFamily(metrics.family)
        font.setPixelSize(metrics.body)
        if app.font() != font:
            app.setFont(font)
        apply_fluent_palette(app, config)
    return current_tokens(accent, mode)


def set_themed_stylesheet(widget: QWidget, build, config: AppConfig) -> None:
    """QSS que depende del tema: ``build(tokens) -> str``.

    Si qfluentwidgets gestiona el widget, se registra como estilo
    personalizado claro y oscuro: su cambio de tema (también el diferido de
    los widgets ocultos) lo conserva en lugar de sobrescribirlo.
    """
    from qfluentwidgets import setCustomStyleSheet
    from qfluentwidgets.common.style_sheet import styleSheetManager

    accent = config.get_accent_color()
    if widget in styleSheetManager.widgets:
        light = build(current_tokens(accent, "light"))
        dark = build(current_tokens(accent, "dark"))
        if (widget.property("lightCustomQss"), widget.property("darkCustomQss")) != (light, dark):
            setCustomStyleSheet(widget, light, dark)
    else:
        qss = build(current_tokens(accent, config.get_theme_mode()))
        if widget.styleSheet() != qss:
            widget.setStyleSheet(qss)


def apply_fluent_palette(widget: QWidget | QApplication, config: AppConfig) -> None:
    """Fija la paleta de superficies para evitar fondos Acrylic neutros."""
    tokens = current_tokens(
        config.get_accent_color(),
        config.get_theme_mode(),
    )
    palette = widget.palette()
    for role, color in (
        (QPalette.ColorRole.Window, tokens.canvas),
        (QPalette.ColorRole.Base, tokens.surface),
        (QPalette.ColorRole.AlternateBase, tokens.surface_alt),
        (QPalette.ColorRole.Button, tokens.surface_alt),
        (QPalette.ColorRole.ButtonText, tokens.text_primary),
        (QPalette.ColorRole.Text, tokens.text_primary),
        (QPalette.ColorRole.WindowText, tokens.text_primary),
        (QPalette.ColorRole.Highlight, tokens.accent),
        (QPalette.ColorRole.HighlightedText, tokens.accent_foreground),
        (QPalette.ColorRole.PlaceholderText, tokens.text_secondary),
    ):
        palette.setColor(role, QColor(color))
    widget.setPalette(palette)
    if isinstance(widget, QWidget):
        widget.setAutoFillBackground(True)
