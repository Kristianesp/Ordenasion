"""Panel de detalle de la unidad seleccionada: información, salud, contenido
y métricas de espacio/SMART. Sólo muestra datos ya calculados."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

from src.gui.v2.theme import apply_control_size

SMART_METRICS = (
    ("Lecturas", "read_count_label", "read_count"),
    ("Escrituras", "write_count_label", "write_count"),
    ("Datos leídos", "read_data_label", "read_data"),
    ("Datos escritos", "write_data_label", "write_data"),
    ("Temperatura", "temperature_label", "temperature"),
    ("Horas encendido", "power_hours_label", "power_hours"),
    ("Ciclos", "power_cycles_label", "power_cycles"),
)


def _metric_card(title: str, value: str, object_name: str) -> tuple[QFrame, QLabel]:
    card = QFrame()
    card.setObjectName(object_name)
    card.setMinimumWidth(0)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(9, 7, 9, 7)
    layout.setSpacing(3)
    header = QLabel(title)
    header.setObjectName("smartMetricLabel" if object_name == "smartMetricCard" else "spaceCardLabel")
    header.setAlignment(Qt.AlignmentFlag.AlignCenter)
    header.setWordWrap(True)
    layout.addWidget(header)
    value_label = QLabel(value)
    value_label.setObjectName("smartMetricValue" if object_name == "smartMetricCard" else "spaceCardValue")
    value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    value_label.setWordWrap(True)
    layout.addWidget(value_label)
    return card, value_label


class _InfoCard(QFrame):
    def __init__(self, title: str, placeholder: str, parent=None):
        super().__init__(parent)
        self.setObjectName("analysis_card_large")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.header = QLabel(title)
        self.header.setObjectName("card_header")
        layout.addWidget(self.header)
        self.frame = QFrame()
        self.frame.setObjectName("analysis_inner_frame")
        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(12, 10, 12, 10)
        self.label = QLabel(placeholder)
        self.label.setObjectName("analysis_content_label")
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setMinimumWidth(0)
        inner.addWidget(self.label)
        inner.addStretch()
        layout.addWidget(self.frame, 1)


class DiskDetailPanel(QWidget):
    """Tres tarjetas adaptables + aviso de administrador + métricas."""

    retry_elevated_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("diskDetailPanel")
        self._columns = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.admin_banner = QFrame()
        self.admin_banner.setObjectName("diskAdminBanner")
        banner_layout = QHBoxLayout(self.admin_banner)
        banner_layout.setContentsMargins(12, 8, 12, 8)
        self.admin_label = QLabel()
        self.admin_label.setWordWrap(True)
        banner_layout.addWidget(self.admin_label, 1)
        self.admin_button = QPushButton("Reintentar como administrador")
        self.admin_button.setObjectName("diskAdminRetry")
        self.admin_button.setToolTip("Muestra el aviso de Windows (UAC) y ejecuta sólo smartctl con permisos "
                                     "elevados; Ordenasion sigue sin privilegios.")
        apply_control_size(self.admin_button)
        self.admin_button.clicked.connect(self.retry_elevated_requested.emit)
        banner_layout.addWidget(self.admin_button)
        self.admin_banner.hide()
        layout.addWidget(self.admin_banner)

        self.cards_grid = QGridLayout()
        self.cards_grid.setHorizontalSpacing(14)
        self.cards_grid.setVerticalSpacing(14)
        self.basic_card = _InfoCard("Información básica", "Selecciona una unidad para ver su información.")
        self.health_card = _InfoCard("Estado y salud", "Estado: no seleccionado")
        self.content_card = _InfoCard("Contenido", "Contenido: no seleccionado")
        self.cards = (self.basic_card, self.health_card, self.content_card)
        layout.addLayout(self.cards_grid)
        self.space_card = self._build_space_card()
        layout.addWidget(self.space_card)
        self._arrange(3)

    # Etiquetas con los nombres históricos del visor
    @property
    def basic_info_label(self) -> QLabel:
        return self.basic_card.label

    @property
    def health_status_label(self) -> QLabel:
        return self.health_card.label

    @property
    def content_info_label(self) -> QLabel:
        return self.content_card.label

    def _build_space_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("space_card_full")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(8)
        usage_card = QFrame()
        usage_card.setObjectName("spaceUsageCard")
        usage_layout = QVBoxLayout(usage_card)
        usage_layout.setContentsMargins(10, 8, 10, 8)
        heading = QHBoxLayout()
        self.progress_label = QLabel("Uso del disco")
        self.progress_label.setObjectName("spaceCardLabel")
        heading.addWidget(self.progress_label)
        self.usage_percent_label = QLabel("—")
        self.usage_percent_label.setObjectName("spaceCardPercent")
        self.usage_percent_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        heading.addWidget(self.usage_percent_label)
        usage_layout.addLayout(heading)
        self.usage_progress_bar = QProgressBar()
        self.usage_progress_bar.setObjectName("usage_progress_bar")
        self.usage_progress_bar.setRange(0, 100)
        self.usage_progress_bar.setTextVisible(False)
        self.usage_progress_bar.setFixedHeight(8)
        self.usage_progress_bar.setToolTip("Porcentaje de espacio utilizado (usado / total)")
        usage_layout.addWidget(self.usage_progress_bar)
        top.addWidget(usage_card, 2)
        for title, attribute in (("Total", "total_size_label"), ("Usado", "used_size_label"), ("Libre", "free_size_label")):
            metric, value = _metric_card(title, "—", "spaceMetricCard")
            setattr(self, attribute, value)
            top.addWidget(metric, 1)
        outer.addLayout(top)
        self.smart_grid = QGridLayout()
        self.smart_grid.setSpacing(8)
        self._smart_cards = []
        for title, attribute, _key in SMART_METRICS:
            metric, value = _metric_card(title, "—", "smartMetricCard")
            setattr(self, attribute, value)
            self._smart_cards.append(metric)
        outer.addLayout(self.smart_grid)
        self._arrange_smart(7)
        return card

    def set_smart_metrics(self, texts: dict) -> None:
        for _title, attribute, key in SMART_METRICS:
            getattr(self, attribute).setText(texts.get(key, "—"))

    def set_admin_hint(self, visible: bool, can_elevate: bool, busy: bool = False) -> None:
        self.admin_banner.setVisible(visible)
        if not visible:
            return
        if busy:
            self.admin_label.setText("Esperando a la confirmación de Windows y a smartctl…")
        elif can_elevate:
            self.admin_label.setText("Leer SMART requiere permisos de administrador. Puedes reintentar elevando "
                                     "sólo smartctl; no hace falta reiniciar Ordenasion.")
        else:
            self.admin_label.setText("Leer SMART requiere permisos de administrador (ejecuta la aplicación con "
                                     "privilegios elevados).")
        self.admin_button.setVisible(can_elevate)
        self.admin_button.setEnabled(not busy)

    def _arrange(self, columns: int) -> None:
        if columns == self._columns:
            return
        for card in self.cards:
            self.cards_grid.removeWidget(card)
        for index, card in enumerate(self.cards):
            self.cards_grid.addWidget(card, index // columns, index % columns)
        for column in range(3):
            self.cards_grid.setColumnStretch(column, 1 if column < columns else 0)
        self._columns = columns

    def _arrange_smart(self, columns: int) -> None:
        for card in self._smart_cards:
            self.smart_grid.removeWidget(card)
        for index, card in enumerate(self._smart_cards):
            self.smart_grid.addWidget(card, index // columns, index % columns)
        for column in range(7):
            self.smart_grid.setColumnStretch(column, 1 if column < columns else 0)

    @property
    def columns(self) -> int:
        return self._columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = self.width()
        columns = 3 if width >= 1100 else 2 if width >= 760 else 1
        if columns != self._columns:
            self._arrange(columns)
            self._arrange_smart(7 if width >= 900 else 4 if width >= 560 else 2)
