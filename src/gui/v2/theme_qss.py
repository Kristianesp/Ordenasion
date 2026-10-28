"""Hojas de estilo: shell V2, puente para los controles Qt heredados,
diálogos y menús. Se cachean por firma visual (acento, claro/oscuro, tipo).
"""

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QTextEdit, QWidget
from qfluentwidgets import FluentStyleSheet, getStyleSheet

from src.gui.v2.theme_tokens import (
    FluentTokens, contrasting_foreground, current_glass, current_tokens, theme_signature, typography_scale,
)
from src.gui.v2.theme_palette import _config_from_widget, apply_control_sizes, apply_fluent_palette
from src.utils.app_config import AppConfig

# Hojas de estilo ya generadas, por firma visual (acento, claro/oscuro,
# densidad, tamaño, escala y familia): cambiar de tema no las recompone.
_QSS_CACHE: dict[tuple, str] = {}


def cached_stylesheet(name: str, config: AppConfig, builder) -> str:
    key = (name, *theme_signature(config))
    qss = _QSS_CACHE.get(key)
    if qss is None:
        qss = _QSS_CACHE[key] = builder(config)
    return qss


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
    """Estilos locales del shell V2, separados del QSS heredado (cacheado)."""
    return cached_stylesheet("window", config, _build_fluent_window_stylesheet)


def _build_fluent_window_stylesheet(config: AppConfig) -> str:
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
        QWidget#fluentAppWindow SegmentedItem {{
            /* Hereda la regla de PushButton; su relleno (6 px) o su relleno
               y margen (3 + 3 px) suman 12 px a la altura del contenido. */
            min-height: {max(1, metrics.control_height - 12)}px;
            max-height: {max(1, metrics.control_height - 12)}px;
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
    """QSS acotado para controles Qt heredados dentro de páginas V2 (cacheado)."""
    return cached_stylesheet("legacy", config, _build_legacy_surface_stylesheet)


def _build_legacy_surface_stylesheet(config: AppConfig) -> str:
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
    qss = legacy_surface_stylesheet(config)
    if widget.styleSheet() != qss:
        widget.setStyleSheet(qss)
    apply_fluent_palette(widget, config)
    widget.setAutoFillBackground(False)
    signature = theme_signature(config)
    # Las alturas de control solo dependen de tipo y densidad, no del tema.
    if getattr(widget, "_control_size_signature", None) != signature[2:]:
        widget._control_size_signature = signature[2:]
        apply_control_sizes(widget, config)
