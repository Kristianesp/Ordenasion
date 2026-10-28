"""Rejilla adaptable de tarjetas de unidades (FlowLayout, sin recortes)."""

from __future__ import annotations

from typing import List, Tuple

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy,
                             QVBoxLayout, QWidget)
from qfluentwidgets import FlowLayout

from src.gui.disk_viewer.health_renderer import SYSTEM_DRIVE_HELP
from src.gui.v2.theme import apply_control_size, apply_elided_path
from src.utils.formatting import format_bytes

CARD_MIN_WIDTH = 280

TYPE_HELP = {
    "removable": "Unidad extraíble (memoria USB o tarjeta).",
    "network": "Unidad de red: el espacio lo gestiona otro equipo y no tiene datos SMART.",
    "optical": "Unidad óptica: no tiene datos SMART.",
    "ram": "Disco en memoria RAM: se borra al apagar.",
}


class _FlowItemMixin:
    """sizeHint con el ancho asignado por la rejilla: FlowLayout coloca por
    sizeHint y así las tarjetas nunca fuerzan un ancho mínimo mayor que la
    ventana (sin recortes ni scroll horizontal)."""

    target_width = CARD_MIN_WIDTH

    def sizeHint(self):  # noqa: N802 (API Qt)
        return QSize(self.target_width, super().sizeHint().height())

    def minimumSizeHint(self):  # noqa: N802
        return QSize(min(160, self.target_width), super().minimumSizeHint().height())


class _EmptyLabel(_FlowItemMixin, QLabel):
    def sizeHint(self):  # noqa: N802
        return QSize(self.target_width, self.heightForWidth(self.target_width))


class DiskCard(_FlowItemMixin, QFrame):
    clicked = pyqtSignal(int)
    analyze_clicked = pyqtSignal(int)

    def __init__(self, row: int, disk, parent=None):
        super().__init__(parent)
        self.row = row
        self.disk = disk
        self.setObjectName("diskProductCard")
        self.setProperty("diskRow", row)
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        letter = f"{disk.drive_letter}:" if disk.drive_letter else disk.mountpoint
        self.setAccessibleName(f"Unidad {letter}, {disk.usage_percent:.1f} % usado")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        heading = QHBoxLayout()
        heading.setSpacing(8)
        drive_label = QLabel(f"{disk.drive_letter}:" if disk.drive_letter else "Unidad")
        drive_label.setObjectName("diskCardDrive")
        heading.addWidget(drive_label)
        mount_label = QLabel(disk.mountpoint)
        mount_label.setObjectName("diskCardMount")
        mount_label.setMinimumWidth(0)
        apply_elided_path(mount_label, disk.mountpoint)
        heading.addWidget(mount_label, 1)
        drive_type = getattr(disk, "drive_type", "fixed")
        if drive_type != "fixed":
            type_badge = QLabel(getattr(disk, "drive_type_label", drive_type))
            type_badge.setObjectName("diskCardBadge")
            type_badge.setProperty("status", "data")
            type_badge.setToolTip(TYPE_HELP.get(drive_type, ""))
            heading.addWidget(type_badge)
        badge = QLabel("Sistema" if disk.is_system_drive else "Datos")
        badge.setObjectName("diskCardBadge")
        badge.setProperty("status", "system" if disk.is_system_drive else "data")
        badge.setToolTip(SYSTEM_DRIVE_HELP if disk.is_system_drive else
                         "Unidad de datos: no contiene el sistema operativo.")
        self.badge = badge
        heading.addWidget(badge)
        layout.addLayout(heading)

        progress = QProgressBar()
        progress.setObjectName("diskCardProgress")
        progress.setRange(0, 100)
        progress.setValue(round(disk.usage_percent))
        progress.setTextVisible(False)
        progress.setFixedHeight(7)
        progress.setAccessibleName("Ocupación")
        layout.addWidget(progress)

        usage = QLabel(f"{disk.usage_percent:.1f} % usado · {format_bytes(disk.free_size)} libres "
                       f"de {format_bytes(disk.total_size)}")
        usage.setObjectName("diskCardUsage")
        usage.setWordWrap(True)
        self.usage_label = usage
        layout.addWidget(usage)

        details = QLabel(f"{disk.filesystem} · {getattr(disk, 'drive_type_label', 'Disco fijo')}")
        details.setObjectName("diskCardMetric")
        layout.addWidget(details)

        analyze = QPushButton("Analizar")
        analyze.setObjectName("diskCardAnalyze")
        analyze.setToolTip(f"Abre Organizar con {disk.mountpoint} como origen")
        apply_control_size(analyze)
        analyze.clicked.connect(lambda _checked=False: self.analyze_clicked.emit(self.row))
        self.analyze_button = analyze
        layout.addWidget(analyze)

    def set_selected(self, selected: bool) -> None:
        if self.property("selected") == selected:
            return
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit(self.row)
            return
        super().keyPressEvent(event)


class DiskCardGrid(QWidget):
    """Contenedor de tarjetas: columnas según el ancho disponible."""

    card_selected = pyqtSignal(int)
    analyze_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("diskCardsContent")
        self.setMinimumWidth(0)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.flow = FlowLayout(self, needAni=False)
        self.flow.setContentsMargins(0, 0, 0, 0)
        self.flow.setHorizontalSpacing(12)
        self.flow.setVerticalSpacing(12)
        self.cards: List[DiskCard] = []
        self.empty_label = _EmptyLabel("Pulsa Actualizar para buscar unidades disponibles.")
        self.empty_label.setObjectName("diskCardsEmpty")
        self.empty_label.setWordWrap(True)
        self.flow.addWidget(self.empty_label)

    def set_disks(self, disks: List[Tuple[int, object]]) -> None:
        self.flow.takeAllWidgets()
        self.cards = []
        self.empty_label = None
        if not disks:
            self.empty_label = _EmptyLabel("No se encontraron unidades disponibles.")
            self.empty_label.setObjectName("diskCardsEmpty")
            self.empty_label.setWordWrap(True)
            self.flow.addWidget(self.empty_label)
        for row, disk in disks:
            card = DiskCard(row, disk, self)
            card.clicked.connect(self.card_selected.emit)
            card.analyze_clicked.connect(self.analyze_requested.emit)
            self.cards.append(card)
            self.flow.addWidget(card)
        self._resize_cards()
        self.updateGeometry()

    def set_selected_row(self, row: int) -> None:
        for card in self.cards:
            card.set_selected(card.row == row)

    def _resize_cards(self) -> None:
        width = max(1, self.width())
        spacing = self.flow.horizontalSpacing()
        columns = max(1, min(len(self.cards) or 1, (width + spacing) // (CARD_MIN_WIDTH + spacing)))
        # FlowLayout compara con QRect.right() (ancho - 1): se descuenta ese píxel.
        card_width = max(200, (width - 1 - spacing * (columns - 1)) // columns)
        for card in self.cards:
            card.target_width = min(card_width, width)
            card.updateGeometry()
        if self.empty_label is not None:
            self.empty_label.target_width = width
            self.empty_label.updateGeometry()
        self.flow.invalidate()

    @property
    def columns(self) -> int:
        if not self.cards:
            return 0
        top = self.cards[0].y()
        return sum(1 for card in self.cards if card.y() == top)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_cards()
