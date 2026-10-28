"""Configuración visual centralizada para la interfaz Fluent."""

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPalette, QPainter, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QToolButton,
    QTextEdit,
    QWidget,
)
from qfluentwidgets import Theme, isDarkTheme, setTheme, setThemeColor, FluentStyleSheet, getStyleSheet

from src.utils.app_config import AppConfig

_FONTS_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"
_BUNDLED_FONTS_REGISTERED = False
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


@dataclass(frozen=True)
class FluentTokens:
    canvas: str
    surface: str
    surface_alt: str
    text_primary: str
    text_secondary: str
    stroke: str
    accent: str
    success: str
    warning: str
    danger: str

    @property
    def accent_foreground(self) -> str:
        return contrasting_foreground(self.accent)

    @property
    def accent_text(self) -> str:
        return self.accent if contrast_ratio(self.accent, self.surface) >= 4.5 else self.text_primary


def contrast_ratio(first: str, second: str) -> float:
    def luminance(value: str) -> float:
        parsed = QColor(value)
        channels = [parsed.redF(), parsed.greenF(), parsed.blueF()]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + 0.05) / (values[0] + 0.05)


def contrasting_foreground(background: str) -> str:
    return "#FFFFFF" if contrast_ratio("#FFFFFF", background) >= 4.5 else "#000000"


LIGHT_TOKENS = FluentTokens(
    canvas="#F3F6FB",
    surface="#FFFFFF",
    surface_alt="#E9EFF7",
    text_primary="#1A2430",
    text_secondary="#40546B",
    stroke="#D5DFEA",
    accent="#0F6CBD",
    success="#0E700E",
    warning="#8A5300",
    danger="#C42B1C",
)

@dataclass(frozen=True)
class TypographyScale:
    display: int
    title: int
    body: int
    small: int
    caption: int
    control_height: int
    row_height: int
    padding_x: int
    page_margin: int
    compact: bool
    family: str


DARK_TOKENS = FluentTokens(
    canvas="#101827",
    surface="#182337",
    surface_alt="#22324A",
    text_primary="#F5F9FF",
    text_secondary="#B9C8D9",
    stroke="#3A4D66",
    accent="#60CDFF",
    success="#6CCB5F",
    warning="#FFD666",
    danger="#FF99A4",
)


@dataclass(frozen=True)
class GlassTokens:
    """Vidrio blanco neutro; la atmósfera azul pertenece al fondo."""

    fill: str
    border: str
    reflection: str
    mesh: tuple[str, str, str]
    radius: int = 16


LIGHT_GLASS = GlassTokens(
    "rgba(255, 255, 255, 184)", "rgba(255, 255, 255, 224)",
    "rgba(255, 255, 255, 242)", ("#A9CBED", "#B3E4E9", "#DAE7F7"),
)
DARK_GLASS = GlassTokens(
    "rgba(255, 255, 255, 16)", "rgba(255, 255, 255, 34)",
    "rgba(255, 255, 255, 62)", ("#193653", "#163A46", "#202C46"),
)


def current_glass(tokens: FluentTokens) -> GlassTokens:
    return DARK_GLASS if tokens.canvas == DARK_TOKENS.canvas else LIGHT_GLASS


def glass_color(value: str) -> QColor:
    """QColor no interpreta la sintaxis rgba de QSS."""
    if value.startswith("rgba("):
        return QColor(*(int(part.strip()) for part in value[5:-1].split(",")))
    return QColor(value)


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


def _to_theme(mode: str) -> Theme:
    normalized = mode.lower()
    if normalized == "light":
        return Theme.LIGHT
    if normalized == "dark":
        return Theme.DARK
    return Theme.AUTO


def current_tokens(
    accent: str | None = None,
    mode: str | None = None,
) -> FluentTokens:
    """Devuelve tokens resueltos para el tema efectivo."""
    normalized_mode = (mode or "").lower()
    use_dark = (
        normalized_mode == "dark"
        or (normalized_mode not in {"light", "dark"} and isDarkTheme())
    )
    base = DARK_TOKENS if use_dark else LIGHT_TOKENS
    if not accent:
        return base
    return FluentTokens(
        canvas=base.canvas,
        surface=base.surface,
        surface_alt=base.surface_alt,
        text_primary=base.text_primary,
        text_secondary=base.text_secondary,
        stroke=base.stroke,
        accent=accent,
        success=base.success,
        warning=base.warning,
        danger=base.danger,
    )


def responsive_ui_scale() -> float:
    """Calcula una escala legible para la resolución del monitor principal."""
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1.0

    geometry = screen.availableGeometry()
    width_scale = geometry.width() / 1440
    height_scale = geometry.height() / 900
    scale = (width_scale + height_scale) / 2
    return max(0.9, min(1.1, scale))


def register_bundled_fonts() -> None:
    """Registra Nunito embebida para que la tipografía no dependa del sistema."""
    global _BUNDLED_FONTS_REGISTERED
    if _BUNDLED_FONTS_REGISTERED:
        return
    if _FONTS_DIR.is_dir():
        for font_file in (*_FONTS_DIR.glob("*.ttf"), *_FONTS_DIR.glob("*.otf")):
            QFontDatabase.addApplicationFont(str(font_file))
    _BUNDLED_FONTS_REGISTERED = True


def responsive_font_size(
    config: AppConfig,
    offset: int = 0,
    minimum: int = 10,
) -> int:
    """Resuelve un tamaño de fuente ajustado a configuración y resolución."""
    configured_size = max(9, config.get_font_size())
    return max(minimum, round(configured_size * responsive_ui_scale()) + offset)


def preferred_font_family() -> str:
    """Prefiere Nunito embebida y mantiene una cadena de fallback para Windows."""
    register_bundled_fonts()
    available = set(QFontDatabase.families())
    for family in (
        "Nunito",
        "Nunito Sans",
        "Segoe UI Variable",
        "Segoe UI",
        "Aptos",
        "Arial",
        "Noto Sans",
    ):
        if family in available:
            return family
    fallback = QApplication.font().family()
    return fallback if fallback and fallback != "Sans Serif" else ""


def typography_scale(config: AppConfig) -> TypographyScale:
    """Escala única de tipo y controles derivada de la configuración."""
    compact = config.get_interface_density() == "compact"
    body = responsive_font_size(config)
    extra = 16 if compact else 20
    control_height = body + extra
    return TypographyScale(
        display=body + 8,
        title=max(14, body + 2),
        body=body,
        small=max(11, body - 2),
        caption=max(10, body - 3),
        control_height=control_height,
        row_height=control_height + 4,
        padding_x=8 if compact else 12,
        page_margin=24 if compact else 32,
        compact=compact,
        family=preferred_font_family(),
    )


def html_type_scale(config: AppConfig) -> dict[str, int]:
    """Tamaños de fuente para HTML rico, alineados con la escala de tokens."""
    scale = typography_scale(config)
    return {
        "display": scale.display,
        "title": scale.title,
        "body": scale.body,
        "small": scale.small,
        "caption": scale.caption,
    }


def _config_from_widget(widget: QWidget) -> AppConfig:
    current: QWidget | None = widget
    while current is not None:
        config = getattr(current, "config", None) or getattr(current, "app_config", None)
        if isinstance(config, AppConfig):
            return config
        current = current.parentWidget()
    return AppConfig()


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
    """Aplica tema, acento y tipografía una sola vez a la aplicación."""
    register_bundled_fonts()
    mode = config.get_theme_mode()
    accent = config.get_accent_color()
    setTheme(_to_theme(mode))
    app = QApplication.instance()
    if app is not None:
        # FileOrganizerGUI aplica un QSS global heredado durante su arranque.
        # La V2 debe usar la paleta Fluent y estilos locales, no ese QSS.
        app.setStyleSheet("")
    if QColor(accent).isValid():
        setThemeColor(accent)

    if app is not None:
        metrics = typography_scale(config)
        font = QFont()
        if metrics.family:
            font.setFamily(metrics.family)
        font.setPixelSize(metrics.body)
        app.setFont(font)
        apply_fluent_palette(app, config)
    return current_tokens(accent, mode)


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


def apply_dialog_surface(dialog: QWidget) -> FluentTokens:
    """Aplica el tema del controlador también a los diálogos fuera del shell."""
    config = _config_from_widget(dialog)
    tokens = current_tokens(config.get_accent_color(), config.get_theme_mode())
    metrics = typography_scale(config)
    if not dialog.objectName():
        dialog.setObjectName("fluentDialog")
    name = dialog.objectName()
    scope = f"QDialog#{name}"
    dialog.setStyleSheet(f"""
        {scope} {{ background: {tokens.canvas}; color: {tokens.text_primary}; }}
        {scope} QLabel, {scope} QCheckBox, {scope} QRadioButton, {scope} QGroupBox {{
            color: {tokens.text_primary}; background: transparent;
            font-size: {metrics.body}px;
        }}
        {scope} QLabel#preview_header {{ font-size: {metrics.title}px; font-weight: 600; }}
        {scope} QGroupBox {{ border: 1px solid {tokens.stroke}; border-radius: 8px; margin-top: 12px; padding: 16px 10px 10px; }}
        {scope} QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
        {scope} QLineEdit, {scope} QComboBox, {scope} QAbstractSpinBox {{
            background: {tokens.surface}; color: {tokens.text_primary};
            border: 1px solid {tokens.stroke}; border-radius: 6px; padding: 5px 8px;
            selection-background-color: {tokens.accent}; selection-color: {tokens.accent_foreground};
        }}
        {scope} QLineEdit:focus, {scope} QComboBox:focus, {scope} QAbstractSpinBox:focus {{ border-color: {tokens.accent}; }}
        {scope} QLineEdit:disabled, {scope} QComboBox:disabled, {scope} QAbstractSpinBox:disabled {{
            background: {tokens.surface_alt}; color: {tokens.text_secondary};
        }}
        {scope} QAbstractItemView, {scope} QTextEdit, {scope} QScrollArea {{
            background: {tokens.surface}; color: {tokens.text_primary};
            alternate-background-color: {tokens.surface_alt};
            border: 1px solid {tokens.stroke};
            selection-background-color: {tokens.accent}; selection-color: {tokens.accent_foreground};
        }}
        {scope} QAbstractItemView::item:disabled, {scope} QCheckBox:disabled, {scope} QRadioButton:disabled {{ color: {tokens.text_secondary}; }}
        {scope} QScrollArea > QWidget > QWidget {{ background: {tokens.surface}; color: {tokens.text_primary}; }}
        {scope} QHeaderView::section {{
            background: {tokens.surface_alt}; color: {tokens.text_primary};
            border: 1px solid {tokens.stroke}; padding: 6px;
        }}
        {scope} QPushButton {{
            background: {tokens.surface_alt}; color: {tokens.text_primary};
            border: 1px solid {tokens.stroke}; border-radius: 6px; padding: 6px 12px;
        }}
        {scope} PrimaryPushButton {{
            background: {tokens.accent}; color: {tokens.accent_foreground}; border-color: {tokens.accent};
        }}
        {scope} QPushButton:hover {{ background: {tokens.surface}; border-color: {tokens.accent}; }}
        {scope} QPushButton:pressed {{ background: {tokens.surface_alt}; border-color: {tokens.text_secondary}; }}
        {scope} QPushButton:focus {{ border: 2px solid {tokens.text_primary}; }}
        {scope} PrimaryPushButton:hover, {scope} PrimaryPushButton:pressed, {scope} PrimaryPushButton:focus {{
            background: {tokens.accent}; color: {tokens.accent_foreground}; border-color: {tokens.text_primary};
        }}
        {scope} QPushButton:disabled {{
            background: {tokens.surface_alt}; color: {tokens.text_secondary}; border-color: {tokens.stroke};
        }}
    """)
    for widget in (dialog, *dialog.findChildren(QWidget)):
        apply_fluent_palette(widget, config)
        if widget.__class__.__name__ == "PrimaryPushButton":
            # El QSS local de QFluent gana al del QDialog: mantener geometría
            # e iconos, pero fijar superficie/foreground coherentes al acento.
            widget.setStyleSheet(getStyleSheet(FluentStyleSheet.BUTTON) + f"""
                PrimaryPushButton {{ background: {tokens.accent}; color: {tokens.accent_foreground};
                    border: 1px solid {tokens.accent}; border-radius: 6px; padding: 6px 12px;
                    font-size: {metrics.body}px; }}
                PrimaryPushButton[hasIcon="true"] {{ padding: 6px 12px 6px 36px; }}
                PrimaryPushButton:hover, PrimaryPushButton:pressed, PrimaryPushButton:focus {{
                    background: {tokens.accent}; color: {tokens.accent_foreground}; border-color: {tokens.text_primary}; }}
                PrimaryPushButton:focus {{ border-width: 2px; }}
                PrimaryPushButton:disabled {{ background: {tokens.surface_alt}; color: {tokens.text_secondary}; border-color: {tokens.stroke}; }}
            """)
    for editor in dialog.findChildren(QTextEdit):
        # Fluent instala QSS local en TextEdit; ese QSS prevalece sobre el
        # estilo del diálogo y puede mantener una superficie del tema anterior.
        editor.setStyleSheet(f"""
            QTextEdit {{ background-color: {tokens.surface}; color: {tokens.text_primary};
                border: 1px solid {tokens.stroke}; font-size: {metrics.body}px;
                selection-background-color: {tokens.accent}; selection-color: {tokens.accent_foreground}; }}
        """)
        viewport = editor.viewport()
        viewport.setStyleSheet(f"background-color: {tokens.surface}; color: {tokens.text_primary};")
        palette = viewport.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(tokens.surface))
        palette.setColor(QPalette.ColorRole.Base, QColor(tokens.surface))
        palette.setColor(QPalette.ColorRole.Text, QColor(tokens.text_primary))
        viewport.setPalette(palette)
        viewport.setAutoFillBackground(True)
    apply_control_sizes(dialog, config)
    return tokens


def apply_menu_surface(menu, config: AppConfig | None = None) -> FluentTokens:
    """Tema propio de QMenu, incluidos popups fuera de la superficie del shell."""
    explicit_config = config
    config = config or _config_from_widget(menu)
    tokens = current_tokens(config.get_accent_color(), config.get_theme_mode())
    metrics = typography_scale(config)
    if not menu.objectName():
        menu.setObjectName("fluentMenu")
    scope = f"QMenu#{menu.objectName()}"
    menu.setStyleSheet(f"""
        {scope} {{ background: {tokens.surface}; color: {tokens.text_primary};
            border: 1px solid {tokens.stroke}; border-radius: 8px; padding: 4px;
            font-size: {metrics.body}px; }}
        {scope}::item {{ background: transparent; color: {tokens.text_primary};
            border-radius: 4px; padding: 7px 28px; margin: 2px; }}
        {scope}::item:selected {{ background: {tokens.accent}; color: {tokens.accent_foreground}; }}
        {scope}::item:disabled {{ color: {tokens.text_secondary}; }}
        {scope}::item:selected:disabled {{ background: {tokens.surface_alt}; color: {tokens.text_secondary}; }}
        {scope}::separator {{ height: 1px; background: {tokens.stroke}; margin: 4px 10px; }}
    """)
    apply_fluent_palette(menu, config)
    # Menús persistentes (Más acciones) se actualizan al abrir después de un
    # cambio de tema; no mantienen una paleta vieja ni consultan datos externos.
    if not getattr(menu, "_fluent_theme_connected", False):
        menu._fluent_theme_connected = True
        menu.aboutToShow.connect(lambda: apply_menu_surface(menu, explicit_config))
    return tokens


def fluent_window_stylesheet(config: AppConfig) -> str:
    """Estilos locales del shell V2, separados del QSS heredado."""
    tokens = current_tokens(
        config.get_accent_color(),
        config.get_theme_mode(),
    )
    glass = current_glass(tokens)
    metrics = typography_scale(config)
    inner_height = max(1, metrics.control_height - 2)
    base_font_size = metrics.body
    font_family = metrics.family
    font_family_rule = (
        f'font-family: "{font_family}";' if font_family else ""
    )
    return f"""
        QWidget#fluentAppWindow {{
            background: {tokens.canvas};
            background-color: {tokens.canvas};
            color: {tokens.text_primary};
            {font_family_rule}
            font-size: {base_font_size}px;
        }}
        QWidget#fluentAppWindow > QWidget {{
            background-color: transparent;
        }}
        QWidget#fluentAppWindow QScrollArea,
        QWidget#fluentAppWindow StackedWidget,
        QWidget#fluentAppWindow PopUpAniStackedWidget,
        QWidget#fluentAppWindow QWidget > StackedWidget,
        QWidget#fluentAppWindow QWidget#homePage,
        QWidget#fluentAppWindow QWidget#activityPage,
        QWidget#fluentAppWindow QWidget#settingsPage,
        QWidget#fluentAppWindow QWidget#legacyContent {{
            background: transparent;
            background-color: transparent;
            color: {tokens.text_primary};
            border: none;
        }}
        QWidget#fluentAppWindow StackedWidget > QWidget,
        QWidget#fluentAppWindow PopUpAniStackedWidget > QWidget {{
            background: transparent;
            background-color: transparent;
        }}
        QWidget#fluentAppWindow QScrollArea#homePage > QWidget,
        QWidget#fluentAppWindow QScrollArea#settingsPage > QWidget,
        QWidget#fluentAppWindow QScrollArea#activityPage > QWidget {{
            background: transparent;
            background-color: transparent;
        }}
        QWidget#fluentAppWindow QWidget#pageHeader {{
            background: transparent;
            background-color: transparent;
            border: none;
        }}
        QWidget#fluentAppWindow QWidget#pageHeaderTrailing,
        QWidget#fluentAppWindow QWidget#diskHeaderStatus {{
            background: transparent;
            background-color: transparent;
            border: none;
        }}
        QWidget#fluentAppWindow QWidget#diskHeaderStatus QLabel,
        QWidget#fluentAppWindow QWidget#diskHeaderStatus QCheckBox {{
            color: {tokens.text_primary};
        }}
        QWidget#fluentAppWindow QLabel,
        QWidget#fluentAppWindow BodyLabel {{
            color: {tokens.text_primary};
            {font_family_rule}
            font-size: {metrics.body}px;
        }}
        QWidget#fluentAppWindow CaptionLabel {{
            color: {tokens.text_secondary};
            {font_family_rule}
            font-size: {metrics.small}px;
        }}
        QWidget#fluentAppWindow SubtitleLabel {{
            color: {tokens.text_primary};
            {font_family_rule}
            font-size: {metrics.title}px;
            font-weight: 600;
        }}
        QWidget#fluentAppWindow TitleLabel {{
            color: {tokens.text_primary};
            {font_family_rule}
            font-size: {metrics.display}px;
            font-weight: 700;
        }}
        QWidget#fluentAppWindow QWidget#pageHeader BodyLabel,
        QWidget#fluentAppWindow QWidget#pageHeader CaptionLabel {{
            color: {tokens.text_secondary};
        }}
        QWidget#fluentAppWindow GlassCard,
        QWidget#fluentAppWindow MetricCard,
        QWidget#fluentAppWindow FeatureCard,
        QWidget#fluentAppWindow SurfaceCard {{
            background: transparent;
            background-color: transparent;
            border: none;
        }}
        QWidget#fluentAppWindow LineEdit,
        QWidget#fluentAppWindow ComboBox,
        QWidget#fluentAppWindow SpinBox,
        QWidget#fluentAppWindow QLineEdit,
        QWidget#fluentAppWindow QComboBox,
        QWidget#fluentAppWindow QSpinBox {{
            background: {tokens.surface};
            background-color: {tokens.surface};
            color: {tokens.text_primary};
            border: 1px solid {tokens.stroke};
            border-radius: 8px;
            min-height: {inner_height}px;
            max-height: {inner_height}px;
            padding: 0 {metrics.padding_x}px;
            {font_family_rule}
            font-size: {metrics.body}px;
            selection-background-color: {tokens.accent};
            selection-color: {tokens.accent_foreground};
        }}
        QWidget#fluentAppWindow TextEdit {{
            background: {tokens.surface};
            background-color: {tokens.surface};
            color: {tokens.text_primary};
            border: 1px solid {tokens.stroke};
            border-radius: 8px;
            {font_family_rule}
            font-size: {metrics.body}px;
            selection-background-color: {tokens.accent};
            selection-color: {tokens.accent_foreground};
        }}
        QWidget#fluentAppWindow LineEdit:focus,
        QWidget#fluentAppWindow ComboBox:focus,
        QWidget#fluentAppWindow TextEdit:focus,
        QWidget#fluentAppWindow SpinBox:focus,
        QWidget#fluentAppWindow QLineEdit:focus,
        QWidget#fluentAppWindow QComboBox:focus,
        QWidget#fluentAppWindow QSpinBox:focus {{
            border: 1px solid {tokens.accent};
        }}
        QWidget#fluentAppWindow PushButton,
        QWidget#fluentAppWindow PrimaryPushButton,
        QWidget#fluentAppWindow TransparentPushButton,
        QWidget#fluentAppWindow QPushButton,
        QWidget#fluentAppWindow QToolButton {{
            color: {tokens.text_primary};
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
            border: 1px solid {tokens.stroke};
            border-radius: 8px;
            min-height: {inner_height}px;
            max-height: {inner_height}px;
            padding: 0 {metrics.padding_x}px;
            {font_family_rule}
            font-size: {metrics.body}px;
        }}
        QWidget#fluentAppWindow PushButton:hover,
        QWidget#fluentAppWindow QPushButton:hover,
        QWidget#fluentAppWindow QToolButton:hover {{
            background: {tokens.surface};
            background-color: {tokens.surface};
            border-color: {tokens.accent};
        }}
        QWidget#fluentAppWindow PrimaryPushButton {{
            color: {tokens.accent_foreground};
            background: {tokens.accent};
            background-color: {tokens.accent};
            border-color: {tokens.accent};
        }}
        QWidget#fluentAppWindow PrimaryPushButton:hover {{
            background: {tokens.accent};
            background-color: {tokens.accent};
        }}
        QWidget#fluentAppWindow NavigationInterface {{
            background: transparent;
            border: none;
        }}
        QWidget#fluentAppWindow NavigationPanel {{
            background: {glass.fill};
            border-right: 1px solid {glass.border};
        }}
        QWidget#fluentAppWindow NavigationToolButton {{
            color: {tokens.text_secondary};
            border-radius: 8px;
        }}
        QWidget#fluentAppWindow NavigationToolButton:hover {{
            color: {tokens.text_primary};
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
        }}
        QWidget#fluentAppWindow NavigationToolButton:checked {{
            color: {tokens.accent_foreground};
            background: {tokens.accent};
            background-color: {tokens.accent};
        }}
        QWidget#fluentAppWindow QTableView,
        QWidget#fluentAppWindow QTableWidget,
        QWidget#fluentAppWindow QListWidget {{
            background: {tokens.surface};
            background-color: {tokens.surface};
            color: {tokens.text_primary};
            alternate-background-color: {tokens.surface_alt};
            border: 1px solid {tokens.stroke};
            gridline-color: {tokens.stroke};
            selection-background-color: {tokens.accent};
            selection-color: {tokens.accent_foreground};
        }}
        QWidget#fluentAppWindow QHeaderView::section {{
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
            color: {tokens.text_primary};
            border: none;
            border-bottom: 1px solid {tokens.stroke};
            padding: 6px 8px;
        }}
        QWidget#fluentAppWindow QProgressBar {{
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
            border: none;
            border-radius: 4px;
            text-align: center;
            color: {tokens.text_primary};
        }}
        QWidget#fluentAppWindow QProgressBar::chunk {{
            background: {tokens.accent};
            border-radius: 4px;
        }}
        QWidget#fluentAppWindow QPushButton:disabled,
        QWidget#fluentAppWindow PrimaryPushButton:disabled {{
            color: {tokens.text_secondary};
            background: {tokens.surface_alt};
            border: 1px solid {tokens.stroke};
        }}
        QWidget#fluentAppWindow QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 4px 2px;
        }}
        QWidget#fluentAppWindow QScrollBar::handle:vertical {{
            background: {tokens.stroke};
            border-radius: 2px;
            min-height: 32px;
        }}
        QWidget#fluentAppWindow QScrollBar::handle:vertical:hover {{
            background: {tokens.text_secondary};
        }}
        QWidget#fluentAppWindow QScrollBar:horizontal {{
            background: transparent;
            height: 8px;
            margin: 2px 4px;
        }}
        QWidget#fluentAppWindow QScrollBar::handle:horizontal {{
            background: {tokens.stroke};
            border-radius: 2px;
            min-width: 32px;
        }}
        QWidget#fluentAppWindow QScrollBar::handle:horizontal:hover {{
            background: {tokens.text_secondary};
        }}
        QWidget#fluentAppWindow QScrollBar::add-line,
        QWidget#fluentAppWindow QScrollBar::sub-line,
        QWidget#fluentAppWindow QScrollBar::add-page,
        QWidget#fluentAppWindow QScrollBar::sub-page {{
            background: transparent;
            height: 0px;
            width: 0px;
        }}
    """


def legacy_surface_stylesheet(config: AppConfig) -> str:
    """QSS acotado para controles Qt heredados dentro de páginas V2."""
    tokens = current_tokens(
        config.get_accent_color(),
        config.get_theme_mode(),
    )
    metrics = typography_scale(config)
    control_height = metrics.control_height
    inner_height = max(1, control_height - 2)
    row_height = metrics.row_height
    base_font_size = metrics.body
    small_font_size = metrics.small
    card_title_size = metrics.title
    font_family = metrics.family
    font_family_rule = (
        f'font-family: "{font_family}";' if font_family else ""
    )
    return f"""
        QWidget#legacySurface {{
            background: transparent;
            color: {tokens.text_primary};
            {font_family_rule}
            font-size: {base_font_size}px;
        }}
        QWidget#legacySurface QLabel {{
            background: transparent;
            color: {tokens.text_primary};
        }}
        QWidget#legacySurface QFrame#system_info_group,
        QWidget#legacySurface QFrame#duplicates_controls_frame,
        QWidget#legacySurface QFrame#duplicates_action_frame,
        QWidget#legacySurface QFrame#duplicates_summary_frame,
        QWidget#legacySurface QFrame#duplicates_results_frame,
        QWidget#legacySurface QFrame#space_card_full,
        QWidget#legacySurface QFrame#analysis_card_large,
        QWidget#legacySurface QFrame#analysis_inner_frame {{
            background: {tokens.surface};
            background-color: {tokens.surface};
            border: 1px solid {tokens.stroke};
            border-radius: 12px;
        }}
        QWidget#legacySurface QFrame#analysis_inner_frame {{
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
        }}
        QWidget#legacySurface QFrame#system_info_group {{
            min-height: 52px;
            padding: 2px;
        }}
        QWidget#legacySurface QScrollArea {{
            background: transparent;
            border: none;
        }}
        QWidget#legacySurface QWidget#diskCardsContent {{
            background: transparent;
            border: none;
        }}
        QWidget#legacySurface QFrame#diskProductCard {{
            background: {tokens.surface};
            background-color: {tokens.surface};
            border: 1px solid {tokens.stroke};
            border-radius: 12px;
        }}
        QWidget#legacySurface QFrame#diskProductCard[selected="true"] {{
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
            border: 1px solid {tokens.accent};
        }}
        QWidget#legacySurface QLabel#diskCardDrive {{
            color: {tokens.text_primary};
            font-size: {card_title_size}px;
            font-weight: 700;
        }}
        QWidget#legacySurface QLabel#diskCardMount {{
            color: {tokens.text_secondary};
        }}
        QWidget#legacySurface QLabel#diskCardBadge {{
            padding: 3px 8px;
            border-radius: 8px;
            color: {tokens.success};
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
        }}
        QWidget#legacySurface QLabel#diskCardBadge[status="system"] {{
            color: {tokens.danger};
        }}
        QWidget#legacySurface QLabel#diskCardUsage {{
            color: {tokens.text_secondary};
            font-weight: 600;
        }}
        QWidget#legacySurface QLabel#diskCardMetric {{
            color: {tokens.text_secondary};
            font-size: {small_font_size}px;
        }}
        QWidget#legacySurface QProgressBar#diskCardProgress {{
            min-height: 7px;
            max-height: 7px;
            border: none;
            border-radius: 4px;
            background: {tokens.stroke};
        }}
        QWidget#legacySurface QProgressBar#diskCardProgress::chunk {{
            border-radius: 4px;
            background: {tokens.accent};
        }}
        QWidget#legacySurface QPushButton#diskCardAnalyze {{
            min-height: {inner_height}px;
            max-height: {inner_height}px;
            color: {tokens.accent_foreground};
            background: {tokens.accent};
            border: 1px solid {tokens.accent};
            border-radius: 8px;
            font-weight: 600;
        }}
        QWidget#legacySurface QScrollArea#analysis_scroll_area {{
            background: transparent;
            background-color: transparent;
            border: 1px solid {tokens.stroke};
            border-radius: 12px;
        }}
        QWidget#legacySurface QFrame#analysis_card_large {{
            background: transparent;
            background-color: transparent;
            border: none;
        }}
        QWidget#legacySurface QFrame#analysis_inner_frame {{
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
            border: 1px solid {tokens.stroke};
            border-radius: 10px;
        }}
        QWidget#legacySurface QLabel#card_header {{
            background: transparent;
            color: {tokens.text_primary};
            font-size: {card_title_size}px;
            font-weight: 700;
            padding: 6px 8px;
        }}
        QWidget#legacySurface QLabel#analysis_content_label {{
            background: transparent;
            color: {tokens.text_primary};
            font-size: {base_font_size}px;
        }}
        QWidget#legacySurface QGroupBox#analysis_group {{
            background: {tokens.surface};
            background-color: {tokens.surface};
            border: none;
        }}
        QWidget#legacySurface QGroupBox {{
            background: {tokens.surface};
            border: 1px solid {tokens.stroke};
            border-radius: 12px;
            margin-top: 16px;
            padding: 16px 12px 12px 12px;
            font-weight: 600;
        }}
        QWidget#legacySurface QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: {tokens.text_primary};
        }}
        QWidget#legacySurface QLineEdit,
        QWidget#legacySurface QComboBox,
        QWidget#legacySurface QSpinBox,
        QWidget#legacySurface QDateEdit {{
            min-height: {inner_height}px;
            max-height: {inner_height}px;
            background: {tokens.surface};
            color: {tokens.text_primary};
            border: 1px solid {tokens.stroke};
            border-radius: 8px;
            padding: 0 {metrics.padding_x}px;
            font-size: {base_font_size}px;
        }}
        QWidget#legacySurface QLineEdit:focus,
        QWidget#legacySurface QComboBox:focus,
        QWidget#legacySurface QSpinBox:focus,
        QWidget#legacySurface QDateEdit:focus {{
            border: 1px solid {tokens.accent};
        }}
        QWidget#legacySurface QPushButton,
        QWidget#legacySurface QToolButton {{
            min-height: {inner_height}px;
            max-height: {inner_height}px;
            background: {tokens.surface_alt};
            color: {tokens.text_primary};
            border: 1px solid {tokens.stroke};
            border-radius: 8px;
            padding: 0 {metrics.padding_x}px;
            font-size: {base_font_size}px;
        }}
        QWidget#legacySurface QPushButton:hover,
        QWidget#legacySurface QToolButton:hover {{
            background: {tokens.surface};
            border-color: {tokens.accent};
        }}
        QWidget#legacySurface QPushButton:pressed,
        QWidget#legacySurface QToolButton:pressed {{
            background: {tokens.surface_alt};
        }}
        QWidget#legacySurface QPushButton#organize_button,
        QWidget#legacySurface QPushButton#analyze_button,
        QWidget#legacySurface QPushButton#scan_button,
        QWidget#legacySurface QPushButton#music_scan_button {{
            color: {tokens.accent_foreground};
            background: {tokens.accent};
            border-color: {tokens.accent};
            font-weight: 600;
        }}
        QWidget#legacySurface QPushButton[styleClass="danger"] {{
            color: {contrasting_foreground(tokens.danger)};
            background: {tokens.danger};
            border-color: {tokens.danger};
        }}
        QWidget#legacySurface QPushButton[styleClass="ghost"] {{
            background: transparent;
            border-color: transparent;
        }}
        QWidget#legacySurface QCheckBox,
        QWidget#legacySurface QRadioButton {{
            spacing: 8px;
            padding: 5px 2px;
            color: {tokens.text_primary};
        }}
        QWidget#legacySurface QCheckBox:hover,
        QWidget#legacySurface QRadioButton:hover {{
            color: {tokens.accent_text};
        }}
        QWidget#legacySurface QTabWidget::pane {{
            background: {tokens.surface};
            border: 1px solid {tokens.stroke};
            border-radius: 12px;
            top: -1px;
        }}
        QWidget#legacySurface QTabBar::tab {{
            min-height: {control_height}px;
            padding: 0 16px;
            color: {tokens.text_secondary};
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
        }}
        QWidget#legacySurface QTabBar::tab:hover {{
            color: {tokens.text_primary};
            background: {tokens.surface_alt};
        }}
        QWidget#legacySurface QTabBar::tab:selected {{
            color: {tokens.accent_text};
            border-bottom: 2px solid {tokens.accent};
        }}
        QWidget#legacySurface QTableView,
        QWidget#legacySurface QTableWidget,
        QWidget#legacySurface QListWidget,
        QWidget#legacySurface QTextEdit {{
            background: {tokens.surface};
            alternate-background-color: {tokens.surface_alt};
            color: {tokens.text_primary};
            border: 1px solid {tokens.stroke};
            border-radius: 12px;
            gridline-color: transparent;
            selection-background-color: {tokens.accent};
            selection-color: {tokens.accent_foreground};
        }}
        QWidget#legacySurface QHeaderView::section {{
            min-height: {row_height}px;
            background: {tokens.surface_alt};
            color: {tokens.text_primary};
            border: none;
            border-bottom: 1px solid {tokens.stroke};
            padding: 0 10px;
            font-weight: 600;
        }}
        QWidget#legacySurface QTableCornerButton::section {{
            background: {tokens.surface_alt};
            border: none;
        }}
        QWidget#legacySurface QSplitter::handle {{
            background: {tokens.stroke};
            border-radius: 3px;
        }}
        QWidget#legacySurface QSlider::groove:horizontal {{
            height: 5px;
            background: {tokens.stroke};
            border-radius: 3px;
        }}
        QWidget#legacySurface QSlider::handle:horizontal {{
            width: 14px;
            margin: -5px 0;
            background: {tokens.accent};
            border-radius: 7px;
        }}
        QWidget#legacySurface QFrame[styleClass="stat-chip"] {{
            background: {tokens.surface_alt};
            border: 1px solid {tokens.stroke};
            border-radius: 10px;
        }}
        QWidget#legacySurface QLabel[styleClass="stat-title"] {{
            color: {tokens.text_secondary};
        }}
        QWidget#legacySurface QLabel[styleClass="stat-value"] {{
            color: {tokens.accent_text};
            font-weight: 700;
        }}
        QWidget#legacySurface QLabel#system_info_title,
        QWidget#legacySurface QLabel#card_header,
        QWidget#legacySurface QLabel#main_title_label {{
            color: {tokens.text_primary};
            font-weight: 700;
        }}
        QWidget#legacySurface QProgressBar {{
            min-height: 5px;
            max-height: 5px;
            border: none;
            border-radius: 3px;
            background: {tokens.stroke};
        }}
        QWidget#legacySurface QProgressBar::chunk {{
            border-radius: 3px;
            background: {tokens.accent};
        }}
        QWidget#legacySurface QFrame#spaceUsageCard,
        QWidget#legacySurface QFrame#spaceMetricCard,
        QWidget#legacySurface QFrame#smartMetricCard {{
            background: {tokens.surface_alt};
            background-color: {tokens.surface_alt};
            border: 1px solid {tokens.stroke};
            border-radius: 9px;
        }}
        QWidget#legacySurface QLabel#spaceCardLabel,
        QWidget#legacySurface QLabel#smartMetricLabel {{
            color: {tokens.text_secondary};
            font-size: {small_font_size}px;
            font-weight: 600;
        }}
        QWidget#legacySurface QLabel#spaceCardValue,
        QWidget#legacySurface QLabel#smartMetricValue {{
            color: {tokens.text_primary};
            font-size: {base_font_size}px;
            font-weight: 700;
        }}
        QWidget#legacySurface QLabel#spaceCardPercent {{
            color: {tokens.accent_text};
            font-size: {base_font_size}px;
            font-weight: 700;
        }}
        QWidget#legacySurface QProgressBar#usage_progress_bar {{
            min-height: 8px;
            max-height: 8px;
            border: none;
            border-radius: 4px;
            background: {tokens.stroke};
        }}
        QWidget#legacySurface QProgressBar#usage_progress_bar::chunk {{
            border-radius: 4px;
            background: {tokens.accent};
        }}
        QWidget#legacySurface QPushButton:disabled,
        QWidget#legacySurface QPushButton#organize_button:disabled,
        QWidget#legacySurface QPushButton#analyze_button:disabled,
        QWidget#legacySurface QPushButton#scan_button:disabled,
        QWidget#legacySurface QPushButton#music_scan_button:disabled,
        QWidget#legacySurface QToolButton:disabled {{
            color: {tokens.text_secondary};
            background: {tokens.surface_alt};
            border-color: {tokens.stroke};
        }}
        QWidget#legacySurface QLineEdit:disabled,
        QWidget#legacySurface QComboBox:disabled,
        QWidget#legacySurface QSpinBox:disabled {{
            color: {tokens.text_secondary};
            background: {tokens.surface_alt};
        }}
        QWidget#legacySurface QScrollBar:vertical {{
            background: transparent;
            width: 8px;
            margin: 4px 2px;
        }}
        QWidget#legacySurface QScrollBar::handle:vertical {{
            background: {tokens.stroke};
            border-radius: 2px;
            min-height: 32px;
        }}
        QWidget#legacySurface QScrollBar::handle:vertical:hover {{
            background: {tokens.text_secondary};
        }}
        QWidget#legacySurface QScrollBar:horizontal {{
            background: transparent;
            height: 8px;
            margin: 2px 4px;
        }}
        QWidget#legacySurface QScrollBar::handle:horizontal {{
            background: {tokens.stroke};
            border-radius: 2px;
            min-width: 32px;
        }}
        QWidget#legacySurface QScrollBar::handle:horizontal:hover {{
            background: {tokens.text_secondary};
        }}
        QWidget#legacySurface QScrollBar::add-line,
        QWidget#legacySurface QScrollBar::sub-line,
        QWidget#legacySurface QScrollBar::add-page,
        QWidget#legacySurface QScrollBar::sub-page {{
            background: transparent;
            height: 0px;
            width: 0px;
        }}
    """


def apply_legacy_surface_style(widget: QWidget, config: AppConfig) -> None:
    widget.setObjectName("legacySurface")
    widget.setStyleSheet(legacy_surface_stylesheet(config))
    apply_fluent_palette(widget, config)
    widget.setAutoFillBackground(False)
    apply_control_sizes(widget, config)
