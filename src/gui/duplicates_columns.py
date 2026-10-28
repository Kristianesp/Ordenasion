#!/usr/bin/env python3
"""Configuración de columnas de la tabla de duplicados (anchos, orden y ordenación)."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QSizePolicy, QTableView


class DuplicatesColumnsMixin:
    """Mixin para ``DuplicatesDashboard``: requiere ``duplicates_table``,
    ``duplicates_model``, ``settings``, ``preview_panel`` y ``table_splitter``."""

    default_column_widths = {0: 38, 1: 300, 2: 180, 3: 92, 4: 116, 5: 170, 6: 72}

    def setup_table(self):
        """Configura la tabla virtualizada de duplicados."""
        header = self.duplicates_table.horizontalHeader()
        self.duplicates_table.verticalHeader().setVisible(False)
        self.duplicates_table.setSortingEnabled(False)
        self.duplicates_table.setMinimumHeight(320)
        self.duplicates_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 7):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(34)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_clicked)
        self.default_column_widths = dict(type(self).default_column_widths)
        self.apply_column_widths()
        header.sectionResized.connect(self.on_column_resized)
        header.setSectionsMovable(True)
        header.sectionMoved.connect(self.on_column_moved)
        self.duplicates_table.doubleClicked.connect(self.on_table_double_clicked)

    def apply_column_widths(self):
        """Aplica los anchos predefinidos y la configuración visual de la tabla."""
        table = self.duplicates_table
        for column, width in self.default_column_widths.items():
            table.setColumnWidth(column, width)
        table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        table.setDragDropMode(QTableView.DragDropMode.NoDragDrop)
        table.setMouseTracking(True)
        table.setWordWrap(False)
        table.setVerticalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
        table.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setCornerButtonEnabled(False)

    def on_column_resized(self, logical_index, old_size, new_size):
        self.save_column_settings()

    def on_column_moved(self, logical_index, old_visual_index, new_visual_index):
        self.save_column_settings()

    def on_header_clicked(self, logical_index):
        """Ordena por tamaño, fecha, nombre o ubicación sin partir grupos."""
        if logical_index not in (1, 2, 3, 4):
            return
        sort_info = self.duplicates_model.get_sort_info()
        if sort_info["column"] == logical_index:
            new_order = (
                Qt.SortOrder.DescendingOrder
                if sort_info["order"] == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            new_order = Qt.SortOrder.AscendingOrder
        self.duplicates_model.sort(logical_index, new_order)
        self.duplicates_table.horizontalHeader().setSortIndicator(logical_index, new_order)
        self.update_pagination_controls()

    def save_column_settings(self):
        try:
            header = self.duplicates_table.horizontalHeader()
            count = self.duplicates_table.model().columnCount()
            self.settings.setValue("column_widths", {str(i): header.sectionSize(i) for i in range(count)})
            self.settings.setValue("column_order", [header.visualIndex(i) for i in range(count)])
            self.settings.sync()
        except (RuntimeError, AttributeError) as e:
            self.log_message(f"❌ Error guardando estado de columnas: {e}")

    def load_column_settings(self):
        try:
            header = self.duplicates_table.horizontalHeader()
            self.preview_visible = self.settings.value("preview_visible", self.preview_visible, type=bool)
            self.preview_panel.setVisible(self.preview_visible)
            self.table_splitter.setSizes(self._last_preview_sizes if self.preview_visible else [1, 0])
            self.update_preview_button_state()
            count = self.duplicates_table.model().columnCount()
            saved_widths = self.settings.value("column_widths", {}) or {}
            for column_str, width in dict(saved_widths).items():
                try:
                    column_index = int(column_str)
                    if 0 <= column_index < count:
                        self.duplicates_table.setColumnWidth(column_index, int(width))
                except (ValueError, TypeError):
                    continue
            saved_order = self.settings.value("column_order", []) or []
            if saved_order and len(saved_order) == count:
                try:
                    for logical_index, visual_index in enumerate(saved_order):
                        header.moveSection(header.visualIndex(logical_index), int(visual_index))
                except (ValueError, TypeError):
                    pass
        except (RuntimeError, AttributeError, TypeError) as e:
            self.log_message(f"⚠️ Error cargando estado de columnas: {e} - Usando valores por defecto")

    def reset_column_settings(self):
        try:
            for column, width in self.default_column_widths.items():
                self.duplicates_table.setColumnWidth(column, width)
            header = self.duplicates_table.horizontalHeader()
            for i in range(self.duplicates_table.model().columnCount()):
                header.moveSection(header.visualIndex(i), i)
            for key in ("column_widths", "column_order", "preview_visible"):
                self.settings.remove(key)
            self.settings.sync()
            self.preview_visible = True
            self.preview_panel.show()
            self.table_splitter.setSizes([900, 260])
            self.update_preview_button_state()
            self.log_message("🔄 Columnas restauradas a configuración por defecto")
        except (RuntimeError, AttributeError) as e:
            self.log_message(f"❌ Error restaurando columnas: {e}")
