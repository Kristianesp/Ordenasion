"""Colores y estilos del visor de Discos.

En el shell Fluent (V2) el QSS lo aporta ``legacy_surface_stylesheet`` por
objectName; aquí sólo se construye la paleta para el HTML. En el modo
heredado se genera una hoja compacta a partir de los colores del tema.
"""

from __future__ import annotations

import logging
from typing import Dict

from src.gui.v2.theme import current_tokens
from src.utils.app_config import AppConfig, get_app_config

logger = logging.getLogger(__name__)


def fluent_palette(config: AppConfig) -> Dict[str, str]:
    """Paleta del HTML a partir de los tokens vivos del shell (sólo lectura)."""
    tokens = current_tokens(config.get_accent_color(), config.get_theme_mode())
    return {
        "primary": tokens.accent,
        "secondary": tokens.text_secondary,
        "accent": tokens.accent,
        "background": tokens.canvas,
        "surface": tokens.surface_alt,
        "surface_variant": tokens.surface,
        "text_primary": tokens.text_primary,
        "text_secondary": tokens.text_secondary,
        "border": tokens.stroke,
        "success": tokens.success,
        "warning": tokens.warning,
        "error": tokens.danger,
        "info": tokens.accent,
    }


def legacy_palette(theme_name: str) -> Dict[str, str]:
    """Colores del sistema de temas heredado, con valores por defecto seguros."""
    try:
        from src.utils.themes import ThemeManager

        colors = dict(ThemeManager.get_theme_colors(theme_name))
    except (ImportError, KeyError, AttributeError) as exc:
        logger.debug("Tema heredado no disponible (%s); se usan tokens Fluent", exc)
        colors = {}
    fallback = fluent_palette(get_app_config())
    for key, value in fallback.items():
        colors.setdefault(key, value)
    return colors


def legacy_stylesheet(colors: Dict[str, str], small_px: int, body_px: int, title_px: int) -> str:
    """Hoja única para el modo heredado (sustituye ~600 líneas de estilos sueltos)."""
    return f"""
        QFrame#system_info_group, QFrame#space_card_full, QFrame#analysis_inner_frame,
        QFrame#diskProductCard, QFrame#spaceUsageCard, QFrame#spaceMetricCard,
        QFrame#smartMetricCard, QFrame#diskAdminBanner {{
            background-color: {colors['surface']};
            border: 1px solid {colors['border']};
            border-radius: 10px;
        }}
        QFrame#diskProductCard[selected="true"] {{ border: 1px solid {colors['primary']}; }}
        QLabel {{ color: {colors['text_primary']}; background: transparent; font-size: {body_px}px; }}
        QLabel#system_info_label, QLabel#diskCardMount, QLabel#diskCardMetric,
        QLabel#spaceCardLabel, QLabel#smartMetricLabel {{
            color: {colors.get('text_secondary', colors['text_primary'])}; font-size: {small_px}px;
        }}
        QLabel#card_header, QLabel#diskCardDrive {{ font-size: {title_px}px; font-weight: bold; }}
        QLabel#diskCardBadge {{ padding: 2px 8px; border-radius: 8px; color: {colors['success']}; }}
        QLabel#diskCardBadge[status="system"] {{ color: {colors['error']}; }}
        QPushButton#refresh_btn, QPushButton#diskCardAnalyze, QPushButton#diskAdminRetry {{
            background-color: {colors['primary']}; color: white; border: none;
            border-radius: 6px; padding: 4px 12px; font-weight: bold;
        }}
        QProgressBar {{
            border: 1px solid {colors['border']}; border-radius: 4px;
            background-color: {colors['surface']}; max-height: 8px;
        }}
        QProgressBar::chunk {{ background-color: {colors['primary']}; border-radius: 4px; }}
    """


def usage_role(usage_percent: float) -> str:
    """Rol de color para un porcentaje de ocupación."""
    if usage_percent > 90:
        return "error"
    if usage_percent > 80:
        return "warning"
    return "success"
