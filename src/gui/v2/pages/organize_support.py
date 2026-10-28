"""Piezas de la página Organizar: tabla de resultados y cálculos.

Sin estado de la página: filas del modelo a partir del análisis, resumen por
categoría y la tabla Fluent con casillas. Los diálogos Fluent (pregunta,
aviso y petición de texto) viven en ``src.gui.v2.components``.
"""

from __future__ import annotations

from collections import defaultdict

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QSizePolicy
from qfluentwidgets import TableItemDelegate, TableView

from src.utils.formatting import format_bytes

# Anchos de la tabla: casilla, elemento (elástica), destino, %, archivos y tamaño.
MOVEMENT_COLUMN_WIDTHS = {0: 48, 2: 180, 3: 86, 4: 92, 5: 112}
SORTABLE_COLUMNS = frozenset({1, 2, 3, 4, 5})


def build_model_rows(folder_movements, file_movements) -> list[dict]:
    """Filas del modelo: una por carpeta y un grupo por categoría de archivos sueltos."""
    rows = []
    for movement in folder_movements:
        name = movement["folder"].name
        rows.append({
            "type": "folder",
            "element": name,
            "category": movement["category"],
            "percentage": movement.get("percentage", 0),
            "file_count": movement.get("total_files", 0),
            "size_bytes": movement.get("size", 0),
            "size_formatted": format_bytes(movement.get("size", 0)),
            "tooltip": f"Carpeta: {name}\nArchivos: {movement.get('total_files', 0)}",
            "is_group": False,
            "is_expanded": False,
            "original_data": movement,
        })
    files_by_category: dict[str, list] = defaultdict(list)
    for movement in file_movements:
        files_by_category[movement["category"]].append(movement)
    for category, movements in files_by_category.items():
        total_size = sum(movement.get("size", 0) for movement in movements)
        rows.append({
            "type": "file_group",
            "element": f"{len(movements)} archivo suelto" if len(movements) == 1
                       else f"{len(movements)} archivos sueltos",
            "category": category,
            "percentage": 0,
            "file_count": len(movements),
            "size_bytes": total_size,
            "size_formatted": format_bytes(total_size),
            "tooltip": f"Grupo de {len(movements)} archivos sueltos\nCategoría: {category}\n"
                       "Doble clic para ver los archivos",
            "is_group": True,
            "is_expanded": False,
            "group_files": movements,
        })
    return rows


def category_breakdown(folder_movements, file_movements, categories=None) -> tuple[str, str]:
    """(resumen corto, detalle HTML) por categoría del último análisis."""
    stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "size": 0})
    movements = list(folder_movements) + list(file_movements)
    for movement in movements:
        stats[movement["category"]]["count"] += 1
        stats[movement["category"]]["size"] += movement.get("size", 0)
    ordered = sorted(stats.items(), key=lambda item: -item[1]["count"])
    total = len(movements)
    summary = " · ".join(f"{category} ({values['count'] / total * 100:.0f} %)"
                         for category, values in ordered if total and values["count"])
    lines = [f"<b>{category}:</b> {values['count']:,} elementos ({format_bytes(values['size'])})"
             for category, values in ordered if values["count"]]
    if categories:
        lines.append("<br/><b>Categorías disponibles</b>")
        lines += [f"{name}: {len(extensions)} extensiones" for name, extensions in categories.items()]
    return summary or "Sin análisis", "<br/>".join(lines) if lines else "Sin datos"


def selection_totals(model) -> tuple[int, int, int]:
    """(elementos, bytes, archivos) de las filas marcadas del modelo."""
    count = size = files = 0
    for row in model.get_checked_rows():
        row_data = model.get_row_data(row)
        if not row_data:
            continue
        count += 1
        size += row_data.get("size_bytes", 0)
        if row_data.get("type") == "file_group":
            files += row_data.get("file_count", len(row_data.get("group_files", [])))
        else:
            files += row_data.get("file_count", 1)
    return count, size, files


def selected_movements(model) -> tuple[list, list]:
    """Carpetas y archivos de las filas marcadas, tal y como los dio el análisis."""
    folders, files = [], []
    for row in model.get_checked_rows():
        row_data = model.get_row_data(row) or {}
        if row_data.get("type") == "folder" and row_data.get("original_data"):
            folders.append(row_data["original_data"])
        elif row_data.get("type") == "file_group":
            files.extend(row_data.get("group_files", []))
    return folders, files


class MovementsDelegate(TableItemDelegate):
    """Delegado Fluent con casilla: clic o Espacio en la primera columna la alterna."""

    def editorEvent(self, event, model, option, index):
        if index.column() != 0 or not (model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable):
            return super().editorEvent(event, model, option, index)
        kind = event.type()
        toggle = False
        if kind == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            toggle = option.rect.contains(event.position().toPoint())
        elif kind == QEvent.Type.MouseButtonDblClick:
            return True  # el doble clic no vuelve a alternar la casilla
        elif kind == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Select):
            toggle = True
        if not toggle:
            return False
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        model.setData(index, Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
                      Qt.ItemDataRole.CheckStateRole)
        return True


class MovementsTable(TableView):
    """Tabla Fluent de resultados (modelo virtualizado, casillas y orden)."""

    def __init__(self, model, row_height: int, parent=None):
        super().__init__(parent)
        self.setObjectName("organizeResultsTable")
        self.setAccessibleName("Resultados del análisis")
        self.setModel(model)
        self.setItemDelegate(MovementsDelegate(self))
        self.setBorderVisible(True)
        self.setBorderRadius(8)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(200)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(max(36, row_height))
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        header.setSectionsClickable(True)
        self.apply_column_widths()

    def apply_column_widths(self) -> None:
        for column, width in MOVEMENT_COLUMN_WIDTHS.items():
            self.setColumnWidth(column, width)
