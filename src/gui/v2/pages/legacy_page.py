"""Adaptador visual para reutilizar páginas existentes durante la migración."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QVBoxLayout, QSizePolicy, QWidget
from qfluentwidgets import ScrollArea

from src.gui.v2.components import PageHeader, SurfaceCard
from src.gui.v2.theme import apply_legacy_surface_style
from src.utils.app_config import AppConfig


class LegacyPage(ScrollArea):
    """Envuelve una página existente con el shell visual Fluent."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        legacy_widget: QWidget,
        config: AppConfig,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName(f"legacy_{title.lower().replace(' ', '_')}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWidgetResizable(True)
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        self.enableTransparentBackground()
        self.legacy_widget = legacy_widget

        content = QWidget()
        content.setObjectName("legacyContent")
        content.setMinimumWidth(0)
        content.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self.content = content
        self.setWidget(content)
        layout = QVBoxLayout(content)
        self.content_layout = layout
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(18)
        self.page_header = PageHeader(title, subtitle)
        layout.addWidget(self.page_header)

        apply_legacy_surface_style(self.legacy_widget, config)
        self.legacy_card = SurfaceCard("legacyToolCard", content)
        self.legacy_card.content_layout.addWidget(self.legacy_widget, 1)
        layout.addWidget(self.legacy_card, 1)
        self.legacy_widget.setVisible(True)
        self.legacy_widget.show()

    def add_top_widget(self, widget: QWidget) -> None:
        """Añade un control V2 encima del contenido heredado."""
        self.content_layout.insertWidget(1, widget)

    def add_header_widget(self, widget: QWidget) -> None:
        """Añade un widget compacto a la derecha de la cabecera."""
        self.page_header.add_trailing_widget(widget)

    def refresh_theme(self, config: AppConfig) -> None:
        """Actualiza la capa heredada cuando cambia el tema."""
        apply_legacy_surface_style(self.legacy_widget, config)
