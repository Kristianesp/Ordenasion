"""Shell principal Fluent 2.0.

La ventana depende del ``OrganizeController`` (estado, historial, deshacer y
registro) y de la vista de Organizar; las herramientas pesadas (Discos,
Música y Duplicados) se construyen la primera vez que se abren.
"""

import os
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QMenu, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    FluentIconBase,
    FluentWindow,
    IndeterminateProgressRing,
    InfoBar,
    InfoBarPosition,
    NavigationItemPosition,
    isDarkTheme,
    setCustomStyleSheet,
)
from qfluentwidgets.common.style_sheet import styleSheetManager

from src.gui.v2.components import ThemeTitleBarButton
from src.gui.v2.pages.activity_page import ActivityPage
from src.gui.v2.pages.home_page import HomePage
from src.gui.v2.pages.organize_page import OrganizePage
from src.gui.v2.pages.settings_page import SettingsPage
from src.gui.v2.startup_splash import branding_icon
from src.gui.v2.theme import (
    OceanBackdrop,
    apply_control_sizes,
    apply_fluent_palette,
    apply_fluent_theme,
    current_glass,
    current_tokens,
    fluent_window_stylesheet,
    set_themed_stylesheet,
    theme_signature,
    typography_scale,
)
from src.utils.version import APP_NAME, APP_VERSION

# Clases cuya paleta sigue al tema (superficies que pintan su fondo).
_PALETTE_CLASSES = frozenset({
    "NavigationPanel", "StackedWidget", "PopUpAniStackedWidget", "CardWidget",
    "GlassCard", "MetricCard", "FeatureCard", "SurfaceCard",
})
_FIELD_CLASSES = frozenset({"LineEdit", "ComboBox", "SpinBox", "SearchLineEdit", "DoubleSpinBox"})
_BUTTON_CLASSES = frozenset({"PushButton", "PrimaryPushButton"})


def _set_qss(widget: QWidget, qss: str) -> None:
    """setStyleSheet repule todo el subárbol: solo si la hoja cambia."""
    if widget.styleSheet() != qss:
        widget.setStyleSheet(qss)


def _field_qss(class_name: str, tokens, metrics) -> str:
    return (
        f"{class_name} {{ background: {tokens.surface}; color: {tokens.text_primary}; "
        f"border: 1px solid {tokens.stroke}; border-radius: 8px; "
        f"padding: 0 {metrics.padding_x}px; text-align: left; font-size: {metrics.body}px; }} "
        f"{class_name}:focus {{ border-color: {tokens.accent}; }}"
    )


def _button_qss(class_name: str, tokens, metrics) -> str:
    primary = class_name == "PrimaryPushButton"
    background = tokens.accent if primary else tokens.surface_alt
    foreground = tokens.accent_foreground if primary else tokens.text_primary
    accent = QColor(tokens.accent)
    lighten = foreground != "#FFFFFF"
    hover = (accent.lighter(110) if lighten else accent.darker(110)).name() if primary else tokens.surface
    pressed = (accent.lighter(125) if lighten else accent.darker(125)).name() if primary else tokens.surface_alt
    return (
        f"{class_name} {{ background: {background}; color: {foreground}; "
        f"border: 1px solid {tokens.stroke}; border-radius: 8px; "
        f"padding: 0 {metrics.padding_x}px; font-size: {metrics.body}px; }} "
        f'{class_name}[hasIcon="true"] {{ padding: 0 12px 0 36px; }} '
        f"{class_name}:hover {{ background: {hover}; color: {foreground}; border-color: {tokens.accent}; }} "
        f"{class_name}:pressed {{ background: {pressed}; "
        f"color: {foreground}; border-color: {tokens.text_secondary}; }} "
        f"{class_name}:focus {{ border: 2px solid {tokens.text_primary}; }} "
        f"{class_name}:disabled {{ background: {tokens.surface_alt}; "
        f"color: {tokens.text_secondary}; border-color: {tokens.stroke}; }}"
    )


class LazyPage(QWidget):
    """Hueco de navegación que construye su página la primera vez que se abre."""

    built = pyqtSignal(object)

    def __init__(self, title: str, factory, parent=None):
        super().__init__(parent)
        self._factory = factory
        self.page = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._layout = layout
        self.placeholder = QWidget()
        placeholder_layout = QVBoxLayout(self.placeholder)
        placeholder_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ring = IndeterminateProgressRing()
        ring.setFixedSize(40, 40)
        placeholder_layout.addWidget(ring, alignment=Qt.AlignmentFlag.AlignHCenter)
        placeholder_layout.addWidget(BodyLabel(f"Cargando {title}…"), alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.placeholder)

    @property
    def is_built(self) -> bool:
        return self.page is not None

    def ensure_page(self):
        if self.page is None:
            page = self._factory()
            self.page = page
            self.placeholder.hide()
            self.placeholder.deleteLater()
            self._layout.addWidget(page)
            page.show()
            self.built.emit(page)
        return self.page


def resolve_page(page):
    """Página real de una ruta (construyéndola si era perezosa)."""
    return page.ensure_page() if isinstance(page, LazyPage) else page


class FluentAppWindow(FluentWindow):
    """Ventana V2 con navegación lateral y páginas propias."""

    def __init__(self, legacy_window, parent=None):
        super().__init__(parent)
        self.legacy_window = legacy_window
        self.controller = legacy_window.controller
        self.config = legacy_window.app_config
        self._routes: dict[str, QWidget] = {}
        self._legacy_pages: dict[str, QWidget] = {}
        self._theme_transition_active = False
        self._theme_animation = None
        self._theme_overlay = None
        self._styled_signature = {}
        self._disk_snapshot = ((), None, None)
        self._closing = False

        self.setObjectName("fluentAppWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMicaEffectEnabled(False)
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(branding_icon())
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self.navigationInterface.setMinimumExpandWidth(1200)
        self.navigationInterface.setExpandWidth(200)
        apply_fluent_theme(self.config)

        self._build_navigation()
        self._backdrop = OceanBackdrop(self.config, self)
        self._backdrop.setGeometry(self.rect())
        self._backdrop.lower()
        self._backdrop.show()
        self.theme_button = ThemeTitleBarButton(FluentIcon.QUIET_HOURS, self.titleBar)
        self.theme_button.setObjectName("globalThemeButton")
        self.theme_button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.theme_button.setIconSize(QSize(20, 20))
        self.theme_button.clicked.connect(self._toggle_theme)
        self.theme_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.theme_button.customContextMenuRequested.connect(self._show_theme_menu)
        self.titleBar.buttonLayout.insertWidget(0, self.theme_button)
        self.titleBar.setFixedHeight(36)
        self._apply_shell_styles()
        self._connect_controller()
        self._setup_shortcuts()
        hints = QGuiApplication.styleHints()
        scheme_changed = getattr(hints, "colorSchemeChanged", None)
        if scheme_changed is not None:  # Qt >= 6.5
            scheme_changed.connect(self._on_system_color_scheme_changed)
        self.stackedWidget.currentChanged.connect(self._on_current_page_changed)
        # El modal reutilizado solicita un refresco Fluent al guardar fuente.
        self.legacy_window.refresh_fluent_appearance = self._refresh_theme

        self.legacy_window.hide()
        QTimer.singleShot(0, self._adapt_navigation)
        # Inicio muestra la ocupación sin construir la página Discos.
        QTimer.singleShot(0, self._load_disk_snapshot)

    # ------------------------------------------------------------ páginas
    def _prepare_legacy_widget(self, widget: QWidget) -> QWidget:
        """Deja que el shell controle una herramienta heredada."""
        for child in (widget, *widget.findChildren(QWidget)):
            fluent_hook = getattr(child, "enable_fluent_mode", None)
            if callable(fluent_hook):
                fluent_hook()
            if child.objectName() == "main_title_label" or child.__class__.__name__ == "TabHeaderWidget":
                child.hide()
        return widget

    def _create_disks_page(self):
        from src.gui.v2.pages.feature_pages import DisksPage

        viewer = self._prepare_legacy_widget(self.legacy_window.create_disk_viewer())
        page = DisksPage(viewer, self.config)
        viewer.disk_selected.connect(lambda _path: self._switch_route("organize"))
        viewer.disks_refreshed.connect(lambda _disks: self._refresh_home_dashboard())
        home = self._routes["home"]
        space = page.space_page
        space.result_changed.connect(lambda _result: self._refresh_home_dashboard())
        space.scan_state_changed.connect(home.set_space_scan_active)
        space.organize_requested.connect(self._analyze_from_home)
        self._legacy_pages["disks"] = page
        return page

    def _create_music_page(self):
        from src.gui.v2.pages.feature_pages import MusicPage

        page = MusicPage(self._prepare_legacy_widget(self.legacy_window.create_music_view()), self.config)
        self._legacy_pages["music"] = page
        return page

    def _create_duplicates_page(self):
        from src.gui.v2.pages.feature_pages import DuplicatesPage

        page = DuplicatesPage(self._prepare_legacy_widget(self.legacy_window.create_duplicates_dashboard()),
                              self.config)
        self._legacy_pages["duplicates"] = page
        return page

    def _build_navigation(self) -> None:
        home = HomePage(self.config, self.legacy_window.profile_manager)
        self._add_route("home", home, FluentIcon.HOME, "Inicio")
        home.navigate_requested.connect(self._switch_route)
        home.analyze_requested.connect(self._analyze_from_home)
        home.result_requested.connect(self._show_last_result)
        home.undo_requested.connect(self.legacy_window.rollback_last_operation)
        self.controller.operation_state_changed.connect(lambda: home.update_operation(self.controller))
        home.update_operation(self.controller)

        organize = OrganizePage(self.legacy_window.organize_widget, self.config, self.legacy_window)
        organize.activity_requested.connect(lambda: self._switch_route("activity"))
        self._legacy_pages["organize"] = organize
        self._add_route("organize", organize, FluentIcon.FOLDER, "Organizar")

        for route, factory, icon, title in (
            ("disks", self._create_disks_page, FluentIcon.SAVE_AS, "Discos"),
            ("music", self._create_music_page, FluentIcon.MUSIC, "Música"),
            ("duplicates", self._create_duplicates_page, FluentIcon.COPY, "Duplicados"),
        ):
            lazy = LazyPage(title, factory)
            lazy.built.connect(self._on_lazy_page_built)
            self._add_route(route, lazy, icon, title)

        activity = ActivityPage(self.controller, undo_handler=self.legacy_window.rollback_transaction)
        self._add_route("activity", activity, FluentIcon.SYNC, "Actividad")

        settings = SettingsPage(self.config)
        settings.advanced_settings_requested.connect(self.legacy_window.open_configuration)
        settings.theme_changed.connect(self._refresh_theme)
        settings.theme_mode_selected.connect(self.set_theme_mode)
        self._add_route("settings", settings, FluentIcon.SETTING, "Configuración", NavigationItemPosition.BOTTOM)

        self.switchTo(self._routes["home"])

    def _add_route(self, route: str, page: QWidget, icon, title: str,
                   position: NavigationItemPosition = NavigationItemPosition.TOP) -> None:
        page.setObjectName(route)
        self._routes[route] = page
        self.addSubInterface(page, icon, title, position)

    def page(self, route: str):
        """Página real de ``route`` (la construye si era perezosa)."""
        return resolve_page(self._routes[route])

    def built_page(self, route: str):
        """Página de ``route`` si ya existe; None si aún no se ha abierto."""
        page = self._routes.get(route)
        if isinstance(page, LazyPage):
            return page.page
        return page

    def _built_pages(self):
        for route in self._routes:
            page = self.built_page(route)
            if page is not None:
                yield route, page

    def _current_page(self):
        widget = self.stackedWidget.currentWidget()
        if isinstance(widget, LazyPage):
            return widget.page
        return widget

    def _on_current_page_changed(self, index: int) -> None:
        widget = self.stackedWidget.widget(index)
        if isinstance(widget, LazyPage) and not widget.is_built:
            # Clic en la navegación: se ve el marcador y la página llega en
            # la siguiente vuelta del bucle de eventos.
            QTimer.singleShot(0, widget.ensure_page)
            return
        page = self._current_page()
        if page is not None and getattr(page, "_theme_dirty", False):
            self._refresh_legacy_page(page)

    def _on_lazy_page_built(self, page) -> None:
        self._style_page(page, force=True)
        # El min-height del QSS de qfluentwidgets (p. ej. SegmentedItem) se
        # aplica al pulir la página recién mostrada: las alturas, después.
        QTimer.singleShot(0, lambda: apply_control_sizes(page, self.config))
        if self.built_page("disks") is page:
            self._refresh_home_dashboard()

    # ---------------------------------------------------------- Inicio
    def _connect_controller(self) -> None:
        self._refresh_home_dashboard()

    def _load_disk_snapshot(self) -> None:
        """Lee las unidades (rápido, sin SMART) para Inicio si Discos no existe aún."""
        if self.built_page("disks") is not None or self._closing:
            return
        manager = getattr(self.legacy_window, "disk_manager", None)
        if manager is None:
            return
        try:
            disks = tuple(manager.get_all_disks() or ())
            self._disk_snapshot = (disks, datetime.now(), None)
        except Exception as exc:  # Inicio nunca debe romperse por un disco
            self._disk_snapshot = (self._disk_snapshot[0], self._disk_snapshot[1], str(exc))
        self._refresh_home_dashboard()

    def _refresh_home_dashboard(self) -> None:
        disks_page = self.built_page("disks")
        if disks_page is not None:
            viewer = self.legacy_window.disk_viewer
            disks = viewer.available_disks
            manager = viewer.disk_manager
            if not disks and viewer.disks_updated_at is None and manager is not None:
                disks = getattr(manager, "_disks_cache", None) or ()
            self._routes["home"].update_dashboard(
                disks, disks_page.space_page.result,
                viewer.disks_updated_at, viewer.disks_refresh_error, viewer.current_selection,
            )
            return
        disks, updated_at, error = self._disk_snapshot
        self._routes["home"].update_dashboard(disks, None, updated_at, error, None)

    # ------------------------------------------------------------ estilos
    def _apply_shell_styles(self) -> None:
        """Estilo completo: marco del shell y todas las páginas construidas."""
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        self._style_chrome(tokens)
        for _route, page in self._built_pages():
            self._style_page(page)
        self._backdrop.update()
        self._routes["home"].refresh_theme()
        self._update_theme_button()

    def _style_chrome(self, tokens) -> None:
        """Ventana, navegación y barra de título (pocos widgets)."""
        glass = current_glass(tokens)
        _set_qss(self, fluent_window_stylesheet(self.config))
        for target in (self, self.navigationInterface):
            target.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            apply_fluent_palette(target, self.config)
        self.navigationInterface.setAutoFillBackground(False)
        _set_qss(self.navigationInterface, f"""
            NavigationInterface {{ background: transparent; border: none; }}
            NavigationPanel {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {glass.reflection}, stop:0.002 {glass.fill}, stop:1 {glass.fill});
                border-right: 1px solid {glass.border};
                color: {tokens.text_primary};
            }}
            NavigationToolButton {{
                color: {tokens.text_secondary};
                background-color: transparent;
                border-radius: 8px;
            }}
            NavigationToolButton:hover {{
                color: {tokens.text_primary};
                background-color: {tokens.surface};
            }}
            NavigationToolButton:checked {{
                color: {tokens.accent_foreground};
                background-color: {tokens.accent};
            }}
            """)
        for child in self.navigationInterface.findChildren(QWidget):
            class_name = child.__class__.__name__
            if class_name == "NavigationPanel":
                apply_fluent_palette(child, self.config)
                child.setAutoFillBackground(False)
                _set_qss(child, f"NavigationPanel {{ background-color: {glass.fill}; color: {tokens.text_primary}; }}")
            elif class_name == "ScrollArea":
                _set_qss(child, "background: transparent; border: none;")
                child.setAutoFillBackground(False)
                _set_qss(child.viewport(), "background: transparent;")
                child.viewport().setAutoFillBackground(False)
        for child in self.titleBar.findChildren(QWidget):
            class_name = child.__class__.__name__
            if class_name in {"MinimizeButton", "MaximizeButton", "CloseButton"}:
                _set_qss(
                    child,
                    f"{class_name} {{ background-color: transparent; color: {tokens.text_primary}; }}"
                    f"{class_name}:hover {{ background-color: {tokens.surface}; }}")
            elif child.objectName() == "titleLabel":
                _set_qss(child, f"QLabel {{ color: {tokens.text_primary}; }}")
        self.titleBar.setObjectName("fluentTitleBar")
        self.titleBar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        _set_qss(
            self.titleBar,
            f"QWidget#fluentTitleBar {{ background-color: transparent; color: {tokens.text_primary}; }}")
        stacked = self.stackedWidget
        stacked.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        apply_fluent_palette(stacked, self.config)
        stacked.setAutoFillBackground(False)

    def _style_page(self, page: QWidget, force: bool = False) -> None:
        """Una sola pasada por el árbol de la página.

        Los controles Fluent reciben su QSS como estilo personalizado claro y
        oscuro (setCustomStyleSheet): qfluentwidgets lo conserva al cambiar
        de tema, así que solo se regenera si cambian el acento, el tamaño o
        la densidad. La paleta sí sigue al tema.
        """
        signature = theme_signature(self.config)
        controls_signature = (signature[0], *signature[2:])
        restyle_controls = force or self._styled_signature.get(id(page)) != controls_signature
        self._styled_signature[id(page)] = controls_signature
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        light = current_tokens(self.config.get_accent_color(), "light")
        dark = current_tokens(self.config.get_accent_color(), "dark")
        metrics = typography_scale(self.config)
        qss_cache: dict[str, tuple[str, str]] = {}

        # Superficie de la página: fondo transparente sobre el mesh
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if page.styleSheet():
            _set_qss(page, "")
        apply_fluent_palette(page, self.config)
        page.setAutoFillBackground(False)
        viewport = getattr(page, "viewport", lambda: None)()
        content = getattr(page, "widget", lambda: None)()
        if viewport is not None:
            viewport.setAutoFillBackground(False)
            _set_qss(viewport, "QWidget#qt_scrollarea_viewport { background-color: transparent; }")
        if content is not None:
            apply_fluent_palette(content, self.config)
            content.setAutoFillBackground(False)
            # Sin color: el texto lo resuelve el QSS de la ventana y así la
            # hoja no cambia con el tema (cada setStyleSheet repule el subárbol).
            _set_qss(content, f"QWidget#{content.objectName()} {{ background-color: transparent; }}")

        for widget in page.findChildren(QWidget):
            class_name = widget.__class__.__name__
            if class_name in _PALETTE_CLASSES:
                widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                apply_fluent_palette(widget, self.config)
                widget.setAutoFillBackground(False)
            elif class_name in _FIELD_CLASSES or class_name in _BUTTON_CLASSES:
                if restyle_controls:
                    self._style_control(widget, class_name, light, dark, metrics, qss_cache)
                elif widget not in styleSheetManager.widgets:
                    if class_name not in qss_cache:
                        qss_cache[class_name] = self._control_qss(class_name, light, dark, metrics)
                    _set_qss(widget, qss_cache[class_name][1 if isDarkTheme() else 0])
            elif widget.objectName() == "pageHeader":
                set_themed_stylesheet(widget.title_label, lambda t: (
                    f"color: {t.text_primary}; background: transparent; "
                    f"font-size: {metrics.display}px; font-weight: 700;"), self.config)
                set_themed_stylesheet(widget.subtitle_label, lambda t: (
                    f"color: {t.text_secondary}; background: transparent; font-size: {metrics.body}px;"), self.config)
            elif widget.objectName() == "diskHeaderStatus":
                for control in widget.findChildren(QWidget):
                    apply_fluent_palette(control, self.config)
                    control.setAutoFillBackground(False)
                    if control.__class__.__name__ in {"QLabel", "QCheckBox"}:
                        _set_qss(control, f"color: {tokens.text_primary}; background-color: transparent;")
            elif widget.objectName() in {"total_size_label", "total_files_label", "selection_count_label"}:
                _set_qss(widget, f"color: {tokens.text_primary}; background-color: transparent; border: none;")
        if restyle_controls:
            apply_control_sizes(page, self.config)
        if page in self._legacy_pages.values():
            self._refresh_legacy_page(page)

    @staticmethod
    def _control_qss(class_name, light, dark, metrics) -> tuple[str, str]:
        builder = _button_qss if class_name in _BUTTON_CLASSES else _field_qss
        return builder(class_name, light, metrics), builder(class_name, dark, metrics)

    def _style_control(self, control, class_name, light, dark, metrics, cache) -> None:
        if class_name not in cache:
            cache[class_name] = self._control_qss(class_name, light, dark, metrics)
        light_qss, dark_qss = cache[class_name]
        if class_name == "PrimaryPushButton":
            icon = getattr(control, "_ocean_primary_icon", getattr(control, "_icon", None))
            if isinstance(icon, FluentIconBase):
                control._ocean_primary_icon = icon
                control.setIcon(icon.icon(color=light.accent_foreground))
        if control in styleSheetManager.widgets:
            setCustomStyleSheet(control, light_qss, dark_qss)
        else:
            _set_qss(control, dark_qss if isDarkTheme() else light_qss)

    def _refresh_legacy_page(self, page) -> None:
        """La hoja heredada solo se aplica a la página visible; las demás al abrirse."""
        if page is not self._current_page() and self.isVisible():
            page._theme_dirty = True
            return
        page._theme_dirty = False
        page.refresh_theme(self.config)
        refresh_fluent_theme = getattr(getattr(page, "legacy_widget", None), "refresh_fluent_theme", None)
        if callable(refresh_fluent_theme):
            refresh_fluent_theme()

    def _update_theme_button(self) -> None:
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        dark = isDarkTheme()
        destination = "claro" if dark else "oscuro"
        state = "oscuro" if dark else "claro"
        if self.config.get_theme_mode() == "system":
            state += " (sistema)"
        icon = FluentIcon.BRIGHTNESS if dark else FluentIcon.QUIET_HOURS
        self.theme_button.setIcon(icon.icon(color=tokens.text_primary))
        self.theme_button.setToolTip(
            f"Tema {state}. Cambiar a {destination} (clic derecho: Claro, Oscuro o Sistema)")
        self.theme_button.setAccessibleName(f"Tema {state}. Cambiar a tema {destination}")
        self.theme_button.setFixedSize(36, 36)
        self.theme_button.setNormalColor(QColor(tokens.text_primary))
        self.theme_button.setHoverColor(QColor(tokens.text_primary))
        self.theme_button.setPressedColor(QColor(tokens.text_primary))
        self.theme_button.setHoverBackgroundColor(QColor(tokens.surface_alt))
        self.theme_button.setPressedBackgroundColor(QColor(tokens.surface))

    # --------------------------------------------------------------- tema
    THEME_MODE_LABELS = (("light", "Claro"), ("dark", "Oscuro"), ("system", "Sistema"))

    def _show_theme_menu(self, position=None) -> QMenu:
        """Menú del botón de tema (clic derecho): Claro, Oscuro o Sistema."""
        from src.gui.v2.theme import apply_menu_surface
        menu = QMenu(self)
        menu.setObjectName("themeModeMenu")
        group = QActionGroup(menu)
        current = self.config.get_theme_mode()
        for mode, label in self.THEME_MODE_LABELS:
            action = QAction(label, menu, checkable=True)
            action.setChecked(mode == current)
            action.triggered.connect(lambda _checked=False, target=mode: self.set_theme_mode(target))
            group.addAction(action)
            menu.addAction(action)
        apply_menu_surface(menu, self.config)
        self._theme_menu = menu
        if position is not None:
            menu.popup(self.theme_button.mapToGlobal(position))
        return menu

    def set_theme_mode(self, mode: str) -> bool:
        """Elige Claro, Oscuro o Sistema (desde Configuración o el menú del botón)."""
        if mode == self.config.get_theme_mode():
            return False
        return self._change_theme_mode(mode)

    def _on_system_color_scheme_changed(self, *_args) -> None:
        """Con el modo Sistema, sigue al sistema operativo en caliente."""
        if self.config.get_theme_mode() != "system" or self._theme_transition_active:
            return
        self._refresh_theme()

    def _toggle_theme(self) -> bool:
        return self._change_theme_mode("light" if isDarkTheme() else "dark")

    def _change_theme_mode(self, target: str) -> bool:
        if self._theme_transition_active:
            return False
        snapshot = self.stackedWidget.grab()
        if not self.config.set_theme_mode(target):
            InfoBar.error("No se pudo guardar el tema", "El tema anterior sigue activo. Revisa los permisos y vuelve a intentarlo.",
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return False
        self._theme_transition_active = True
        self.theme_button.setEnabled(False)
        overlay = QLabel(self)
        overlay.setObjectName("themeTransitionOverlay")
        overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        overlay.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        overlay.setPixmap(snapshot)
        overlay.setGeometry(self.stackedWidget.geometry())
        self._theme_overlay = overlay
        effect = QGraphicsOpacityEffect(overlay)
        effect.setOpacity(1)
        overlay.setGraphicsEffect(effect)
        scroll_positions = [(page.verticalScrollBar(), page.verticalScrollBar().value())
                            for _route, page in self._built_pages() if hasattr(page, "verticalScrollBar")]
        self._refresh_theme()
        for scrollbar, value in scroll_positions:
            scrollbar.setValue(value)
        overlay.show()
        overlay.raise_()
        self.titleBar.raise_()
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(280)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(self._cleanup_theme_transition)
        self._theme_animation = animation
        animation.start()
        return True

    def _cleanup_theme_transition(self) -> None:
        animation, self._theme_animation = self._theme_animation, None
        overlay, self._theme_overlay = self._theme_overlay, None
        if animation is not None:
            animation.stop()
            animation.deleteLater()
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()
        self._theme_transition_active = False
        if hasattr(self, "theme_button"):
            self.theme_button.setEnabled(True)

    def _refresh_theme(self) -> None:
        apply_fluent_theme(self.config)
        self._apply_shell_styles()
        settings = self._routes.get("settings")
        if settings is not None:
            settings.sync_theme_selector()

    # ------------------------------------------------------------ atajos
    NAVIGATION_SHORTCUTS: tuple[tuple[str, str, str], ...] = (
        ("Ctrl+1", "home", "Ir a Inicio"),
        ("Ctrl+2", "organize", "Ir a Organizar"),
        ("Ctrl+3", "disks", "Ir a Discos"),
        ("Ctrl+4", "music", "Ir a Música"),
        ("Ctrl+5", "duplicates", "Ir a Duplicados"),
        ("Ctrl+6", "activity", "Ir a Actividad"),
        ("Ctrl+7", "settings", "Ir a Configuración"),
    )

    def shortcut_table(self) -> list[tuple[str, str]]:
        """(secuencia, descripción) de todos los atajos, para la ayuda (F1)."""
        return [(seq, text) for seq, text, _ in self._action_shortcuts()] + [
            ("Ctrl+A / Ctrl+D", "Marcar o desmarcar todo en Organizar"),
        ] + [(seq, text) for seq, _, text in self.NAVIGATION_SHORTCUTS]

    def _action_shortcuts(self):
        legacy = self.legacy_window
        return (
            ("Ctrl+O", "Elegir carpeta para organizar", lambda: self._on_organize(legacy.browse_folder)),
            ("F5", "Analizar la carpeta actual", lambda: self._on_organize(legacy.start_analysis)),
            ("Ctrl+R", "Analizar la carpeta actual", lambda: self._on_organize(legacy.start_analysis)),
            ("Ctrl+S", "Revisar y organizar la selección", lambda: self._on_organize(legacy.start_organization)),
            ("Ctrl+F", "Buscar en los resultados", self._focus_search),
            ("Ctrl+L", "Limpiar el registro", lambda: self._routes["activity"].clear_log()),
            ("Ctrl+P", "Configuración avanzada", legacy.open_configuration),
            ("Ctrl+,", "Configuración", lambda: self._switch_route("settings")),
            ("F1", "Mostrar esta ayuda", self.show_shortcuts_help),
            ("Ctrl+Q", "Salir", self.close),
        )

    def _setup_shortcuts(self) -> None:
        # Los atajos viven en el shell (la ventana heredada está oculta).
        self._shortcuts: dict[str, QShortcut] = {}
        for sequence, _text, callback in self._action_shortcuts():
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts[sequence] = shortcut
        for sequence, route, _text in self.NAVIGATION_SHORTCUTS:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(lambda destination=route: self._switch_route(destination))
            self._shortcuts[sequence] = shortcut
        # Marcar/desmarcar solo dentro de Organizar: Ctrl+A sigue
        # seleccionando texto en los campos (ShortcutOverride del QLineEdit).
        organize = self._routes["organize"]
        for sequence, callback in (("Ctrl+A", self.legacy_window.select_all_items),
                                   ("Ctrl+D", self.legacy_window.deselect_all_items)):
            shortcut = QShortcut(QKeySequence(sequence), organize)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts[sequence] = shortcut

    def _on_organize(self, action) -> None:
        self._switch_route("organize")
        action()

    def _focus_search(self) -> None:
        if self.stackedWidget.currentWidget() is self._routes.get("organize"):
            search = self.legacy_window.filter_bar.search_input
            search.setFocus(Qt.FocusReason.ShortcutFocusReason)
            search.selectAll()
            return
        self._switch_route("duplicates")

    def show_shortcuts_help(self) -> None:
        from src.gui.v2.components import ShortcutsDialog
        dialog = ShortcutsDialog(self.shortcut_table(), self)
        self._shortcuts_dialog = dialog
        dialog.exec()
        self._shortcuts_dialog = None

    # -------------------------------------------------------- navegación
    def _adapt_navigation(self) -> None:
        if self.width() >= 1200:
            self.navigationInterface.expand(useAni=False)
        else:
            self.navigationInterface.panel.collapse()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_theme_transition_active", False):
            self._cleanup_theme_transition()
        if hasattr(self, "_backdrop"):
            self._backdrop.setGeometry(self.rect())
        if hasattr(self, "_routes"):
            QTimer.singleShot(0, self._adapt_navigation)

    def show_maximized_safe(self) -> None:
        """Maximiza en Windows y evita el crash de Qt offscreen en smoke tests."""
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            screen = QApplication.primaryScreen()
            if screen is not None:
                self.setGeometry(screen.availableGeometry())
            self.show()
            return
        self.showMaximized()

    def _switch_route(self, route: str) -> None:
        if route in ("space", "disk-health"):
            disks = resolve_page(self._routes["disks"])
            disks.set_disk_view("space" if route == "space" else "health")
            route = "disks"
        page = self._routes.get(route)
        if page is None:
            return
        if route == "home":
            page.refresh()
            page.update_operation(self.controller)
            self._refresh_home_dashboard()
        resolve_page(page)
        self.switchTo(page)

    def _show_last_result(self) -> None:
        from src.gui.operation_summary_dialog import OperationSummaryDialog
        summary = self.controller.last_operation_summary
        if not summary:
            return
        transaction_id = summary.get("transaction_id")
        undo = None
        if transaction_id and not summary.get("undone"):
            undo = lambda: self.legacy_window.rollback_transaction(transaction_id, confirm=False)
        OperationSummaryDialog(summary, self, undo_callback=undo).exec()

    def _analyze_from_home(self, path: str) -> None:
        self._switch_route("organize")
        self.legacy_window.analyze_folder(path)

    # -------------------------------------------------------------- cierre
    def closeEvent(self, event) -> None:
        disks = self.built_page("disks")
        if disks is not None and disks.request_shutdown(self.close):
            event.ignore()
            return
        if not self.legacy_window.request_shutdown():
            event.ignore()
            return
        self._closing = True
        self._cleanup_theme_transition()
        if self.legacy_window.disk_viewer is not None:
            self.legacy_window.disk_viewer.shutdown()
        self.legacy_window.close()
        super().closeEvent(event)
