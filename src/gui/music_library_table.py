#!/usr/bin/env python3
"""Tabla de la biblioteca musical basada en ``QAbstractTableModel``.

Sustituye al ``QTableWidget`` (una inserción por fila) por un modelo que se
carga de una vez.  ``LibraryTableView`` conserva la parte de la API de
``QTableWidget`` que usa la vista musical (``item()``, ``rowCount()``,
``setCurrentItem()``, ``scrollToItem()``, señales ``itemChanged``,
``itemSelectionChanged`` e ``itemDoubleClicked``) para no reescribir toda la
lógica que depende de ella.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QTableView


def _sort_key(text: str):
    """Orden natural: '2' < '10' y sin distinguir mayúsculas."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", str(text or ""))]


class LibraryTableModel(QAbstractTableModel):
    """Filas: ``{"file_path", "values": [col1..colN], "color", "checked"}``."""

    check_toggled = pyqtSignal(int)

    def __init__(self, headers: List[str], select_column: int = 0, file_column: int = 1, parent=None):
        super().__init__(parent)
        self._headers = list(headers)
        self._rows: List[Dict[str, Any]] = []
        self.select_column = select_column
        self.file_column = file_column

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._headers)

    def set_headers(self, headers: List[str]) -> None:
        self.beginResetModel()
        self._headers = list(headers)
        self.endResetModel()

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def row_data(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def cell_text(self, row: int, column: int) -> str:
        item = self._rows[row]
        if column == self.select_column:
            return ""
        values = item.get("values") or []
        index = column - 1
        return str(values[index]) if 0 <= index < len(values) else ""

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row, column = index.row(), index.column()
        item = self._rows[row]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            text = self.cell_text(row, column)
            if role == Qt.ItemDataRole.ToolTipRole:
                return item.get("file_path") if column == self.file_column else (text or None)
            return text
        if role == Qt.ItemDataRole.CheckStateRole and column == self.select_column:
            return Qt.CheckState.Checked if item.get("checked") else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.UserRole and column in (self.select_column, self.file_column):
            return item.get("file_path", "")
        if role == Qt.ItemDataRole.BackgroundRole and item.get("color"):
            return QBrush(QColor(item["color"]))
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole or index.column() != self.select_column:
            return False
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, 2, True)
        self._rows[index.row()]["checked"] = checked
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.check_toggled.emit(index.row())
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == self.select_column:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self._headers[section] if 0 <= section < len(self._headers) else ""
        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        if not self._rows or column < 0 or column == self.select_column:
            return  # la columna de selección mantiene el orden del índice
        self.layoutAboutToBeChanged.emit()

        def key(item: Dict[str, Any]):
            values = item.get("values") or []
            return _sort_key(values[column - 1] if column - 1 < len(values) else "")

        old_persistent = self.persistentIndexList()
        old_items = [self._rows[index.row()] if index.isValid() else None for index in old_persistent]
        self._rows.sort(key=key, reverse=order == Qt.SortOrder.DescendingOrder)
        positions = {id(item): row for row, item in enumerate(self._rows)}
        new_persistent = [
            self.index(positions[id(item)], index.column()) if item is not None else QModelIndex()
            for item, index in zip(old_items, old_persistent)
        ]
        self.changePersistentIndexList(old_persistent, new_persistent)
        self.layoutChanged.emit()


class LibraryItem:
    """Vista ligera de una celda, compatible con lo que se usaba de QTableWidgetItem."""

    def __init__(self, table: "LibraryTableView", row: int, column: int):
        self._table = table
        self._row = row
        self._column = column

    def row(self) -> int:
        return self._row

    def column(self) -> int:
        return self._column

    def index(self) -> QModelIndex:
        return self._table.model().index(self._row, self._column)

    def text(self) -> str:
        return self._table.model().cell_text(self._row, self._column)

    def data(self, role: int):
        return self._table.model().data(self.index(), role)

    def checkState(self):
        state = self._table.model().data(self.index(), Qt.ItemDataRole.CheckStateRole)
        return state if state is not None else Qt.CheckState.Unchecked

    def setCheckState(self, state) -> None:
        self._table.model().setData(self.index(), state, Qt.ItemDataRole.CheckStateRole)


class LibraryTableView(QTableView):
    itemChanged = pyqtSignal(object)
    itemSelectionChanged = pyqtSignal()
    itemDoubleClicked = pyqtSignal(object)

    def __init__(self, headers: List[str], select_column: int = 0, file_column: int = 1, parent=None):
        super().__init__(parent)
        self._model = LibraryTableModel(headers, select_column, file_column, self)
        self.setModel(self._model)
        self._model.check_toggled.connect(
            lambda row: self.itemChanged.emit(LibraryItem(self, row, select_column)))
        self.selectionModel().selectionChanged.connect(lambda *_: self.itemSelectionChanged.emit())
        self.doubleClicked.connect(
            lambda index: self.itemDoubleClicked.emit(LibraryItem(self, index.row(), index.column())))
        self.verticalHeader().setVisible(False)

    # --- API compatible con QTableWidget -------------------------------------
    def model(self) -> LibraryTableModel:  # type: ignore[override]
        return self._model

    def rowCount(self) -> int:
        return self._model.rowCount()

    def columnCount(self) -> int:
        return self._model.columnCount()

    def setRowCount(self, count: int) -> None:
        if count == 0:
            self._model.set_rows([])

    def setHorizontalHeaderLabels(self, labels: List[str]) -> None:
        self._model.set_headers(labels)

    def item(self, row: int, column: int) -> Optional[LibraryItem]:
        if 0 <= row < self._model.rowCount() and 0 <= column < self._model.columnCount():
            return LibraryItem(self, row, column)
        return None

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self._model.set_rows(rows)
        if self.isSortingEnabled():
            header = self.horizontalHeader()
            self._model.sort(header.sortIndicatorSection(), header.sortIndicatorOrder())

    def setCurrentItem(self, item: LibraryItem) -> None:
        if item is not None:
            self.setCurrentIndex(item.index())

    def scrollToItem(self, item: LibraryItem, hint=QTableView.ScrollHint.EnsureVisible) -> None:
        if item is not None:
            self.scrollTo(item.index(), hint)

    def visualItemRect(self, item: LibraryItem):
        return self.visualRect(item.index())
