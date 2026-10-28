"""Shell principal Fluent 2.0 construido sobre la lógica existente."""

import os
from src.utils.version import APP_NAME, APP_VERSION

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QLabel, QWidget
from qfluentwidgets import FluentIcon, FluentIconBase, FluentWindow, NavigationItemPosition, FluentStyleSheet, getStyleSheet, isDarkTheme, InfoBar, InfoBarPosition

from src.gui.v2.pages.activity_page import ActivityPage
from src.gui.v2.components import ThemeTitleBarButton
from src.gui.v2.startup_splash import branding_icon
from src.gui.v2.pages.feature_pages import (
    DisksPage,
    DuplicatesPage,
    MusicPage,
)
from src.gui.v2.pages.home_page import HomePage
from src.gui.v2.pages.legacy_page import LegacyPage
from src.gui.v2.pages.organize_page import OrganizePage
from src.gui.v2.pages.settings_page import SettingsPage
from src.gui.v2.theme import (
    apply_control_sizes,
    apply_fluent_palette,
    apply_fluent_theme,
    current_tokens,
    current_glass,
    OceanBackdrop,
    typography_scale,
    fluent_window_stylesheet,
)


class FluentAppWindow(FluentWindow):
    """Ventana V2 con navegación lateral y páginas migradas progresivamente."""

    def __init__(self, legacy_window, parent=None):
        super().__init__(parent)
        self.legacy_window = legacy_window
        self.config = legacy_window.app_config
        self._routes: dict[str, QWidget] = {}
        self._legacy_pages: dict[str, LegacyPage] = {}
        self._theme_transition_active = False
        self._theme_animation = None
        self._theme_overlay = None

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

        self._detach_legacy_pages()
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
        self.titleBar.buttonLayout.insertWidget(0, self.theme_button)
        self.titleBar.setFixedHeight(36)
        self._apply_shell_styles()
        self._connect_controller()
        self._setup_shortcuts()
        # El modal reutilizado solicita un refresco Fluent al guardar fuente;
        # evita que el controlador antiguo reinstale su paleta global.
        self.legacy_window.refresh_fluent_appearance = self._refresh_theme

        self.legacy_window.hide()
        QTimer.singleShot(0, self._adapt_navigation)

    def _detach_legacy_pages(self) -> None:
        """Extrae las pestañas actuales para reutilizarlas como contenido V2."""
        tabs = self.legacy_window.main_tabs
        tabs.blockSignals(True)
        self._legacy_widgets: dict[str, QWidget] = {}
        routes = ("organize", "disks", "music", "duplicates")
        for route in routes:
            if tabs.count() == 0:
                break
            widget = tabs.widget(0)
            tabs.removeTab(0)
            # Al quitar una pestaña, Qt puede convertirla temporalmente en
            # ventana independiente. Mantenerla oculta evita los pantallazos
            # durante el arranque; LegacyPage la mostrará al reparentarla.
            widget.hide()
            widget.setParent(None)
            descendants = (widget, *widget.findChildren(QWidget))
            for child in descendants:
                fluent_hook = getattr(child, "enable_fluent_mode", None)
                if callable(fluent_hook):
                    fluent_hook()
                if child.objectName() == "main_title_label":
                    child.hide()
                elif child.__class__.__name__ == "TabHeaderWidget":
                    child.hide()
            self._legacy_widgets[route] = widget
        tabs.blockSignals(False)

    def _build_navigation(self) -> None:
        home = HomePage(self.config, self.legacy_window.profile_manager)
        self._add_route("home", home, FluentIcon.HOME, "Inicio")
        home.navigate_requested.connect(self._switch_route)
        home.analyze_requested.connect(self._analyze_from_home)
        home.result_requested.connect(self._show_last_result)
        home.undo_requested.connect(self.legacy_window.rollback_last_operation)
        self.legacy_window.operation_state_changed.connect(
            lambda: home.update_operation(self.legacy_window)
        )
        home.update_operation(self.legacy_window)

        organize = OrganizePage(
            self._legacy_widgets["organize"],
            self.config,
            self.legacy_window,
        )
        organize.activity_requested.connect(lambda: self._switch_route("activity"))
        disks = DisksPage(self._legacy_widgets["disks"], self.config)
        music = MusicPage(self._legacy_widgets["music"], self.config)
        duplicates = DuplicatesPage(
            self._legacy_widgets["duplicates"],
            self.config,
        )
        for route, page, icon, title in (
            ("organize", organize, FluentIcon.FOLDER, "Organizar"),
            ("disks", disks, FluentIcon.SAVE_AS, "Discos"),
            ("music", music, FluentIcon.MUSIC, "Música"),
            ("duplicates", duplicates, FluentIcon.COPY, "Duplicados"),
        ):
            self._legacy_pages[route] = page
            self._add_route(route, page, icon, title)

        activity = ActivityPage(
            self.legacy_window,
            self.legacy_window.log_text,
        )
        self._add_route("activity", activity, FluentIcon.SYNC, "Actividad")

        settings = SettingsPage(self.config)
        settings.advanced_settings_requested.connect(
            self.legacy_window.open_configuration
        )
        settings.theme_changed.connect(self._refresh_theme)
        self._add_route(
            "settings",
            settings,
            FluentIcon.SETTING,
            "Configuración",
            NavigationItemPosition.BOTTOM,
        )

        self.switchTo(self._routes["home"])

    def _add_route(
        self,
        route: str,
        page: QWidget,
        icon,
        title: str,
        position: NavigationItemPosition = NavigationItemPosition.TOP,
    ) -> None:
        page.setObjectName(route)
        self._routes[route] = page
        self.addSubInterface(page, icon, title, position)

    def _connect_controller(self) -> None:
        self.legacy_window.disk_viewer.disk_selected.connect(
            lambda _path: self._switch_route("organize")
        )
        home = self._routes["home"]
        space = self._routes["disks"].space_page
        space.result_changed.connect(lambda _result: self._refresh_home_dashboard())
        space.scan_state_changed.connect(home.set_space_scan_active)
        self.legacy_window.disk_viewer.disks_refreshed.connect(lambda _disks: self._refresh_home_dashboard())
        self._refresh_home_dashboard()

    def _refresh_home_dashboard(self) -> None:
        viewer = self.legacy_window.disk_viewer
        manager = viewer.disk_manager
        disks = viewer.available_disks
        if not disks and viewer.disks_updated_at is None and manager is not None:
            disks = getattr(manager, "_disks_cache", None) or ()
        self._routes["home"].update_dashboard(
            disks, self._routes["disks"].space_page.result,
            viewer.disks_updated_at, viewer.disks_refresh_error, viewer.current_selection,
        )

    def _apply_shell_styles(self) -> None:
        tokens = current_tokens(
            self.config.get_accent_color(),
            self.config.get_theme_mode(),
        )
        glass = current_glass(tokens)
        palette_targets = [self, self.navigationInterface]
        for page in self._routes.values():
            # ScrollArea instala un QSS transparente propio; el shell debe
            # controlar la superficie para que el tema no termine en blanco.
            page.setStyleSheet("")
            palette_targets.append(page)
            viewport = getattr(page, "viewport", lambda: None)()
            content = getattr(page, "widget", lambda: None)()
            if viewport is not None:
                palette_targets.append(viewport)
                viewport.setAutoFillBackground(False)
                viewport.setStyleSheet(
                    f"QWidget#qt_scrollarea_viewport {{"
                    " background-color: transparent; }}"
                )
            if content is not None:
                palette_targets.append(content)
                content.setStyleSheet(
                    f"QWidget#{content.objectName()} {{"
                    " background-color: transparent;"
                    f" color: {tokens.text_primary}; }}"
                )
        palette_targets.extend(
            child
            for child in self.findChildren(QWidget)
            if child.__class__.__name__
            in {
                "NavigationPanel",
                "StackedWidget",
                "PopUpAniStackedWidget",
                "CardWidget",
                "GlassCard",
                "MetricCard",
                "FeatureCard",
                "SurfaceCard",
            }
        )
        for target in palette_targets:
            target.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            apply_fluent_palette(target, self.config)
        self.setStyleSheet(fluent_window_stylesheet(self.config))
        navigation_stylesheet = f"""
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
            """
        self.navigationInterface.setStyleSheet(navigation_stylesheet)
        for child in self.navigationInterface.findChildren(QWidget):
            if child.__class__.__name__ in {"NavigationPanel", "ScrollArea"}:
                apply_fluent_palette(child, self.config)
                child.setStyleSheet(
                    f"{child.__class__.__name__} {{"
                    f" background-color: {glass.fill};"
                    f" color: {tokens.text_primary}; }}"
                )
        for child in self.findChildren(QWidget):
            class_name = child.__class__.__name__
            if class_name in {"FluentWidgetTitleBar", "FluentTitleBar"}:
                object_name = (
                    "fluentTitleBar"
                    if class_name == "FluentWidgetTitleBar"
                    else "fluentTitleBarContainer"
                )
                child.setObjectName(object_name)
                child.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                apply_fluent_palette(child, self.config)
                child.setStyleSheet(
                    f"QWidget#{object_name} {{"
                    " background-color: transparent;"
                    f" color: {tokens.text_primary}; }}"
                )
            elif class_name in {
                "MinimizeButton",
                "MaximizeButton",
                "CloseButton",
            }:
                child.setStyleSheet(
                    f"{class_name} {{"
                    f" background-color: transparent;"
                    f" color: {tokens.text_primary}; }}"
                    f"{class_name}:hover {{"
                    f" background-color: {tokens.surface}; }}"
                )
            elif child.objectName() == "titleLabel":
                child.setStyleSheet(
                    f"QLabel {{ color: {tokens.text_primary}; }}"
                )
        # Aplicar la paleta después del QSS: Qt puede reconstruir la paleta
        # efectiva al instalar una hoja de estilos global.
        for target in palette_targets:
            apply_fluent_palette(target, self.config)

        # Las páginas dejan ver un único fondo; las tablas/inputs mantienen su
        # paleta opaca. Evitar AutoFill en ancestros que taparía el mesh.
        for target in palette_targets:
            if target is not self:
                target.setAutoFillBackground(False)
        for child in self.navigationInterface.findChildren(QWidget):
            if child.__class__.__name__ == "ScrollArea":
                child.setStyleSheet("background: transparent; border: none;")
                child.setAutoFillBackground(False)
                child.viewport().setStyleSheet("background: transparent;")
                child.viewport().setAutoFillBackground(False)
        self._backdrop.update()

        apply_control_sizes(self, self.config)
        metrics = typography_scale(self.config)
        for header in self.findChildren(QWidget, "pageHeader"):
            header.title_label.setStyleSheet(
                f"color: {tokens.text_primary}; background: transparent; "
                f"font-size: {metrics.display}px; font-weight: 700;"
            )
            header.subtitle_label.setStyleSheet(
                f"color: {tokens.text_secondary}; background: transparent; "
                f"font-size: {metrics.body}px;"
            )
        # QFluent usa QSS local en sus campos y botones. Darles superficie
        # sólida explícita evita una segunda capa de vidrio de baja legibilidad.
        for control in self.findChildren(QWidget):
            class_name = control.__class__.__name__
            if class_name in {"LineEdit", "ComboBox", "SpinBox", "SearchLineEdit"}:
                if not hasattr(control, "_ocean_geometry_qss"):
                    control._ocean_geometry_qss = control.styleSheet()
                control.setStyleSheet(
                    control._ocean_geometry_qss +
                    f"{class_name} {{ background: {tokens.surface}; color: {tokens.text_primary}; "
                    f"border: 1px solid {tokens.stroke}; border-radius: 8px; "
                    f"padding: 0 {metrics.padding_x}px; text-align: left; font-size: {metrics.body}px; }} "
                    f"{class_name}:focus {{ border-color: {tokens.accent}; }}"
                )
            elif class_name in {"PushButton", "PrimaryPushButton"}:
                primary = class_name == "PrimaryPushButton"
                background = tokens.accent if primary else tokens.surface_alt
                foreground = tokens.accent_foreground if primary else tokens.text_primary
                accent = QColor(tokens.accent)
                hover = (accent.darker(110) if foreground == "#FFFFFF" else accent.lighter(110)).name() if primary else tokens.surface
                pressed = (accent.darker(125) if foreground == "#FFFFFF" else accent.lighter(125)).name() if primary else tokens.surface_alt
                if primary:
                    icon = getattr(control, "_ocean_primary_icon", control._icon)
                    if isinstance(icon, FluentIconBase):
                        control._ocean_primary_icon = icon
                        control.setIcon(icon.icon(color=foreground))
                control.setStyleSheet(
                    getStyleSheet(FluentStyleSheet.BUTTON) +
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

        # Estos controles se reparentaron fuera del panel heredado y aún pueden
        # tener QSS local del tema anterior, que prevalece sobre el del shell.
        header_status = self.findChild(QWidget, "diskHeaderStatus")
        if header_status is not None:
            for control in header_status.findChildren(QWidget):
                apply_fluent_palette(control, self.config)
                control.setAutoFillBackground(False)
                if control.__class__.__name__ in {"QLabel", "QCheckBox"}:
                    control.setStyleSheet(
                        f"color: {tokens.text_primary}; background-color: transparent;"
                    )
        for name in ("total_size_label", "total_files_label", "selection_count_label"):
            control = getattr(self.legacy_window, name, None)
            if control is not None:
                control.setStyleSheet(
                    f"color: {tokens.text_primary}; background-color: transparent; border: none;"
                )
                apply_fluent_palette(control, self.config)
                control.setAutoFillBackground(False)

        disk_viewer = getattr(self.legacy_window, "disk_viewer", None)
        refresh_fluent_theme = getattr(disk_viewer, "refresh_fluent_theme", None)
        if callable(refresh_fluent_theme):
            refresh_fluent_theme()
        self._routes["home"].refresh_theme()
        self._update_theme_button()

    def _update_theme_button(self) -> None:
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        dark = isDarkTheme()
        destination = "claro" if dark else "oscuro"
        state = "oscuro" if dark else "claro"
        icon = FluentIcon.BRIGHTNESS if dark else FluentIcon.QUIET_HOURS
        self.theme_button.setIcon(icon.icon(color=tokens.text_primary))
        self.theme_button.setToolTip(f"Tema {state}. Cambiar a {destination}")
        self.theme_button.setAccessibleName(f"Tema {state}. Cambiar a tema {destination}")
        self.theme_button.setFixedSize(36, 36)
        self.theme_button.setNormalColor(QColor(tokens.text_primary))
        self.theme_button.setHoverColor(QColor(tokens.text_primary))
        self.theme_button.setPressedColor(QColor(tokens.text_primary))
        self.theme_button.setHoverBackgroundColor(QColor(tokens.surface_alt))
        self.theme_button.setPressedBackgroundColor(QColor(tokens.surface))

    def _toggle_theme(self) -> bool:
        if self._theme_transition_active:
            return False
        target = "light" if isDarkTheme() else "dark"
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
                            for page in self._routes.values() if hasattr(page, "verticalScrollBar")]
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

    def _setup_shortcuts(self) -> None:
        shortcuts: tuple[tuple[str, str], ...] = (
            ("Ctrl+1", "home"),
            ("Ctrl+2", "organize"),
            ("Ctrl+3", "disks"),
            ("Ctrl+4", "music"),
            ("Ctrl+5", "duplicates"),
            ("Ctrl+6", "activity"),
            ("Ctrl+7", "settings"),
        )
        for sequence, route in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(
                lambda destination=route: self._switch_route(destination)
            )

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
        if route == "space":
            self._routes["disks"].set_disk_view("space")
            route = "disks"
        elif route == "disk-health":
            self._routes["disks"].set_disk_view("health")
            route = "disks"
        page = self._routes.get(route)
        if page is not None:
            if route == "home":
                page.refresh()
                page.update_operation(self.legacy_window)
                self._refresh_home_dashboard()
            self.switchTo(page)

    def _show_last_result(self) -> None:
        from src.gui.operation_summary_dialog import OperationSummaryDialog
        if self.legacy_window.last_operation_summary:
            OperationSummaryDialog(self.legacy_window.last_operation_summary, self).exec()

    def _analyze_from_home(self, path: str) -> None:
        self._switch_route("organize")
        self.legacy_window.folder_input.setText(path)
        self.legacy_window.start_analysis()

    def _refresh_theme(self) -> None:
        apply_fluent_theme(self.config)
        self._apply_shell_styles()
        for page in self._legacy_pages.values():
            page.refresh_theme(self.config)
        self.legacy_window.log_message("Tema Fluent actualizado")

    def closeEvent(self, event) -> None:
        disks = self._routes.get("disks")
        if disks is not None and disks.request_shutdown(self.close):
            event.ignore()
            return
        self._cleanup_theme_transition()
        self.legacy_window.close()
        super().closeEvent(event)
