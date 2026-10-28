"""Tokens de diseño: colores, vidrio, tipografía y firma visual del tema.

Sin widgets ni QSS: lo comparten la paleta, las hojas de estilo y el HTML.
"""

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontDatabase
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import Theme, isDarkTheme

from src.utils.app_config import AppConfig


_FONTS_DIR = Path(__file__).resolve().parents[3] / "assets" / "fonts"
_BUNDLED_FONTS_REGISTERED = False
_PREFERRED_FAMILY: str | None = None


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


def system_prefers_dark() -> bool | None:
    """Esquema de color del sistema según Qt (None si Qt no lo sabe)."""
    from PyQt6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        return None
    hints = QGuiApplication.styleHints()
    color_scheme = getattr(hints, "colorScheme", None)
    if color_scheme is None:  # Qt < 6.5
        return None
    scheme = color_scheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return None


def _to_theme(mode: str) -> Theme:
    normalized = mode.lower()
    if normalized == "light":
        return Theme.LIGHT
    if normalized == "dark":
        return Theme.DARK
    # Sistema: Qt conoce el esquema vivo (también tras un cambio en caliente);
    # si no lo sabe, qfluentwidgets lo detecta con darkdetect.
    prefers_dark = system_prefers_dark()
    if prefers_dark is None:
        return Theme.AUTO
    return Theme.DARK if prefers_dark else Theme.LIGHT


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
    """Prefiere Nunito embebida y mantiene una cadena de fallback para Windows.

    Se resuelve una vez: QFontDatabase.families() es caro y la escala de
    tipografía se consulta por cada control.
    """
    global _PREFERRED_FAMILY
    if _PREFERRED_FAMILY is None:
        _PREFERRED_FAMILY = _resolve_font_family()
    return _PREFERRED_FAMILY


def _resolve_font_family() -> str:
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


def theme_signature(config: AppConfig) -> tuple:
    """Firma de todo lo que cambia el aspecto: sirve de clave de caché."""
    metrics = typography_scale(config)
    return (config.get_accent_color().upper(), current_tokens(None, config.get_theme_mode()).canvas,
            metrics.body, metrics.compact, metrics.family)
