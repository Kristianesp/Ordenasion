"""Páginas adaptadoras para las herramientas especializadas."""

from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget
from qfluentwidgets import SegmentedWidget

from src.gui.v2.pages.legacy_page import LegacyPage
from src.gui.v2.pages.space_usage_page import SpaceUsagePage
from src.utils.app_config import AppConfig


class DisksPage(LegacyPage):
    def __init__(self, legacy_widget: QWidget, config: AppConfig, parent=None):
        super().__init__(
            "Discos",
            "Supervisa espacio, temperatura y salud SMART de tus unidades.",
            legacy_widget,
            config,
            parent,
        )
        self._move_disk_status_to_header(legacy_widget)
        self.view_selector = SegmentedWidget()
        self.view_selector.setAccessibleName("Vista de Discos")
        self.view_selector.addItem("health", "Unidades y salud", onClick=lambda: self.set_disk_view("health"))
        self.view_selector.addItem("space", "Uso del espacio", onClick=lambda: self.set_disk_view("space"))
        self.add_top_widget(self.view_selector)
        self.space_page = SpaceUsagePage(config, self.content)
        self.content_layout.addWidget(self.space_page, 1)
        self.set_disk_view("health")

    def set_disk_view(self, view):
        self.view_selector.setCurrentItem(view)
        self.legacy_card.setVisible(view == "health")
        self.space_page.setVisible(view == "space")
        status = self.findChild(QWidget, "diskHeaderStatus")
        if status is not None:
            status.setVisible(view == "health")

    def request_shutdown(self, callback):
        return self.space_page.request_shutdown(callback)

    def _move_disk_status_to_header(self, legacy_widget: QWidget) -> None:
        """Integra el estado del disco en la cabecera Fluent."""
        viewer = next(
            (
                child
                for child in (legacy_widget, *legacy_widget.findChildren(QWidget))
                if child.__class__.__name__ == "DiskViewer"
            ),
            None,
        )
        if viewer is None:
            return

        status = QWidget()
        status.setObjectName("diskHeaderStatus")
        status.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)

        system_info = getattr(viewer, "system_info_label", None)
        if system_info is not None:
            system_info.setWordWrap(True)
            system_info.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            status_layout.addWidget(system_info, 1)

        for name in ("safe_mode_label", "safe_mode_checkbox", "refresh_btn"):
            control = getattr(viewer, name, None)
            if control is not None:
                status_layout.addWidget(control)

        self.add_header_widget(status)


class MusicPage(LegacyPage):
    def __init__(self, legacy_widget: QWidget, config: AppConfig, parent=None):
        super().__init__(
            "Música",
            "Organiza tu biblioteca, compara duplicados y mejora metadatos.",
            legacy_widget,
            config,
            parent,
        )


class DuplicatesPage(LegacyPage):
    def __init__(self, legacy_widget: QWidget, config: AppConfig, parent=None):
        super().__init__(
            "Duplicados",
            "Recupera espacio con análisis rápido, híbrido o profundo.",
            legacy_widget,
            config,
            parent,
        )
