"""Componentes compartidos de la interfaz Fluent 2.0."""

from PyQt6.QtCore import Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPainter, QLinearGradient, QPen
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    IconWidget,
    PrimaryPushButton,
    SubtitleLabel,
    TitleLabel,
    TransparentToolButton,
)

from src.gui.v2.theme import _config_from_widget, current_tokens, current_glass, glass_color
from qfluentwidgets.window.fluent_window import FluentTitleBarButton


class ThemeTitleBarButton(FluentTitleBarButton):
    """Botón SVG reconocido por el hit-test de la barra de título Windows."""

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hasFocus():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(self.normalColor, 2))
            painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 6, 6)


class GlassCard(CardWidget):
    """Superficie Fluent de vidrio, sin blur ni sombras sobre el texto."""

    def paintEvent(self, event):
        config = _config_from_widget(self)
        tokens = current_tokens(config.get_accent_color(), config.get_theme_mode())
        glass = current_glass(tokens)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = glass_color(glass.fill)
        if self.isClickEnabled() and self.isHover:
            fill.setAlpha(min(255, fill.alpha() + 12))
        painter.setBrush(fill)
        painter.setPen(QPen(glass_color(glass.border), 1))
        painter.drawRoundedRect(rect, glass.radius, glass.radius)
        # Una línea superior neutra marca el reflejo, sin halos exteriores.
        reflection = QLinearGradient(0, 0, self.width(), 0)
        reflection.setColorAt(0, glass_color(glass.border))
        reflection.setColorAt(0.45, glass_color(glass.reflection))
        reflection.setColorAt(1, glass_color(glass.border))
        painter.setPen(QPen(reflection, 1))
        painter.drawLine(glass.radius, 1, max(glass.radius, self.width() - glass.radius), 1)


class PageHeader(QWidget):
    """Cabecera consistente para todas las páginas."""

    primary_clicked = pyqtSignal()
    secondary_clicked = pyqtSignal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        primary_text: str = "",
        primary_icon=None,
        secondary_icon=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(12)
        self.setMinimumWidth(0)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        self.title_label = TitleLabel(title)
        self.subtitle_label = BodyLabel(subtitle)
        self.subtitle_label.setWordWrap(True)
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        layout.addLayout(text_layout, 1)

        self.trailing_container = QWidget()
        self.trailing_container.setObjectName("pageHeaderTrailing")
        self.trailing_layout = QHBoxLayout(self.trailing_container)
        self.trailing_layout.setContentsMargins(0, 0, 0, 0)
        self.trailing_layout.setSpacing(8)
        self.trailing_container.setVisible(False)
        layout.addWidget(self.trailing_container)

        self.secondary_button = TransparentToolButton()
        if secondary_icon is not None:
            self.secondary_button.setIcon(secondary_icon)
        self.secondary_button.setAccessibleName("Acción secundaria")
        self.secondary_button.setVisible(secondary_icon is not None)
        self.secondary_button.clicked.connect(self.secondary_clicked.emit)
        layout.addWidget(self.secondary_button)

        self.primary_button = PrimaryPushButton()
        if primary_icon is not None:
            self.primary_button.setIcon(primary_icon)
        self.primary_button.setText(primary_text)
        self.primary_button.setAccessibleName(primary_text or "Acción principal")
        self.primary_button.setVisible(bool(primary_text))
        self.primary_button.clicked.connect(self.primary_clicked.emit)
        layout.addWidget(self.primary_button)

    def add_trailing_widget(self, widget: QWidget) -> None:
        """Añade información contextual a la derecha de la cabecera."""
        self.trailing_layout.addWidget(widget)
        self.trailing_container.setVisible(True)


class ActionBar(QWidget):
    """Fila de acciones con espaciado y márgenes consistentes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("actionBar")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.setMinimumWidth(0)
        self.content_layout = QHBoxLayout(self)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)


class SurfaceCard(GlassCard):
    """Superficie reutilizable para contenido de herramientas."""

    def __init__(self, object_name: str = "surfaceCard", parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumWidth(0)
        self.content_layout = QVBoxLayout(self)
        self.content_layout.setContentsMargins(18, 18, 18, 18)
        self.content_layout.setSpacing(14)


class MetricCard(GlassCard):
    """Tarjeta compacta para una métrica o estado relevante."""

    def __init__(self, icon, title: str, value: str, detail: str, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(106)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.icon_widget = IconWidget(icon)
        self.icon_widget.setFixedSize(24, 24)
        header.addWidget(self.icon_widget)
        self.title_label = BodyLabel(title)
        header.addWidget(self.title_label)
        header.addStretch()
        layout.addLayout(header)

        self.value_label = SubtitleLabel(value)
        layout.addWidget(self.value_label)
        self.detail_label = CaptionLabel(detail)
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

    def set_value(self, value: str, detail: str | None = None) -> None:
        self.value_label.setText(value)
        if detail is not None:
            self.detail_label.setText(detail)


class FeatureCard(GlassCard):
    """Tarjeta navegable que explica una fortaleza de la aplicación."""

    activated = pyqtSignal()

    def __init__(self, icon, title: str, description: str, action: str, parent=None):
        super().__init__(parent)
        self.setClickEnabled(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(118)
        self.setMinimumWidth(0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 16, 16, 16)
        layout.setSpacing(14)

        icon_widget = IconWidget(icon)
        icon_widget.setFixedSize(30, 30)
        layout.addWidget(icon_widget, alignment=Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)
        title_label = SubtitleLabel(title)
        description_label = BodyLabel(description)
        description_label.setWordWrap(True)
        action_label = CaptionLabel(action)
        text_layout.addWidget(title_label)
        text_layout.addWidget(description_label)
        text_layout.addStretch()
        text_layout.addWidget(action_label)
        layout.addLayout(text_layout, 1)

        self.clicked.connect(self.activated.emit)
