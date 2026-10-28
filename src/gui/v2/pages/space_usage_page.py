"""Exploración de un inventario de espacio; nunca inicia un análisis al abrir."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PyQt6.QtCore import Qt, QAbstractTableModel, QModelIndex, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFontMetrics
from PyQt6.QtWidgets import QApplication, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QSizePolicy, QTableView, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, FlowLayout, FluentIcon, IndeterminateProgressBar, LineEdit, PrimaryPushButton, PushButton, SubtitleLabel
from src.core.space_usage import export_csv, export_extensions_csv
from src.gui.v2.components import GlassCard
from src.gui.v2.space_map import SpaceMap, format_bytes
from src.gui.v2.space_usage_worker import SpaceScanWorker
from src.gui.v2.theme import ElidedPathLabel


logger = logging.getLogger(__name__)

LIST_FOLDER, LIST_FILES, LIST_FOLDERS, LIST_EXTENSIONS = range(4)

STATUS = {"ok": "Disponible", "partial": "Parcial", "denied": "Acceso denegado", "missing": "Desaparecido",
          "error": "Error de lectura", "link": "Enlace omitido", "unsupported": "Tipo no compatible"}


class BreadcrumbButton(PushButton):
    def __init__(self, node):
        super().__init__()
        self.setText(node.name)
        self.full_name = node.name
        self.setMaximumWidth(180)
        self.setMinimumWidth(60)
        self.setToolTip(node.path)
        self.setAccessibleName("Ir a " + node.path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(QFontMetrics(self.font()).elidedText(self.full_name, Qt.TextElideMode.ElideMiddle, max(16, self.width() - 24)))


class SpaceTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None
        self.rows = ()
        self.row_index = {}
        self.extension_rows = ()
        self.parent_size = 0
        self.global_mode = False

    @property
    def extension_mode(self):
        return bool(self.extension_rows)

    def set_rows(self, result, rows, parent_size, global_mode=False):
        self.beginResetModel()
        self.result, self.rows, self.parent_size = result, tuple(rows), parent_size
        # Búsqueda O(1) de la fila de un nodo (antes rows.index()).
        self.row_index = {node_id: row for row, node_id in enumerate(self.rows)}
        self.extension_rows = ()
        self.global_mode = global_mode
        self.endResetModel()

    def set_extension_rows(self, result, rows, total):
        self.beginResetModel()
        self.result, self.rows, self.row_index = result, (), {}
        self.extension_rows, self.parent_size, self.global_mode = tuple(rows), total, True
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.extension_rows) if self.extension_mode else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 5

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if self.extension_mode:
                return ("Extensión", "Tamaño lógico", "En disco", "% análisis", "Archivos")[section]
            return ("Elemento", "Tamaño lógico", "En disco", "% análisis" if self.global_mode else "% carpeta",
                    "Estado")[section]

    def _extension_data(self, index, role):
        ext, count, logical, disk = self.extension_rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return (ext, format_bytes(logical), format_bytes(disk),
                    f"{logical / self.parent_size * 100:.1f} %" if self.parent_size else "—",
                    f"{count:,}".replace(",", "."))[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{ext}: {count} archivos · {logical:,} bytes lógicos · {disk:,} bytes en disco"
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (1, 2, 3, 4):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or self.result is None:
            return None
        if self.extension_mode:
            return self._extension_data(index, role)
        node = self.result.nodes[self.rows[index.row()]]
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return node.name + (" /" if node.kind == "folder" else "")
            if index.column() == 1:
                return format_bytes(node.size)
            if index.column() == 2:
                return format_bytes(node.disk_size) if getattr(self.result, "measured_disk", False) else "—"
            if index.column() == 3:
                return f"{node.size / self.parent_size * 100:.1f} %" if self.parent_size else "—"
            return STATUS.get(node.status, node.status)
        if role == Qt.ItemDataRole.ToolTipRole:
            return (f"{node.path}\n{node.size:,} bytes lógicos · {node.disk_size:,} bytes en disco · "
                    f"{STATUS.get(node.status, node.status)}")
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() in (1, 2, 3):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class SpaceUsagePage(QWidget):
    result_changed = pyqtSignal(object)
    scan_state_changed = pyqtSignal(bool)
    organize_requested = pyqtSignal(str)  # "Organizar esta carpeta" (ruta de carpeta)
    export_finished = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.result = None
        self.current_id = 0
        self.selected_id = None
        self._worker = None
        self._run_id = 0
        self._cancel_requested = False
        self._shutdown_callback = None
        self._rescan_paths = None
        self._columns = 0
        self._export_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="space-export")
        self.export_finished.connect(self._export_done, Qt.ConnectionType.QueuedConnection)
        self.setObjectName("spaceUsagePage")
        self.setMinimumWidth(0)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        controls = GlassCard()
        box = QVBoxLayout(controls)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)
        description = BodyLabel("Analiza una carpeta o unidad sin modificar archivos.")
        description.setWordWrap(True)
        box.addWidget(description)
        row = QHBoxLayout()
        self.path_input = LineEdit()
        self.path_input.setPlaceholderText("Carpeta o unidad que quieres analizar")
        self.path_input.setAccessibleName("Origen del análisis de espacio")
        self.path_input.returnPressed.connect(self.start_scan)
        row.addWidget(self.path_input, 1)
        self.browse_button = PushButton(FluentIcon.FOLDER, "Elegir carpeta o unidad")
        self.browse_button.clicked.connect(self._choose_folder)
        row.addWidget(self.browse_button)
        self.analyze_button = PrimaryPushButton(FluentIcon.SEARCH, "Analizar")
        self.analyze_button.clicked.connect(self.start_scan)
        row.addWidget(self.analyze_button)
        self.cancel_button = PushButton("Cancelar")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scan)
        row.addWidget(self.cancel_button)
        box.addLayout(row)
        self.status_label = BodyLabel("Sin análisis. El resultado permanecerá aquí al cambiar de vista.")
        self.status_label.setWordWrap(True)
        box.addWidget(self.status_label)
        self.progress_bar = IndeterminateProgressBar(self)
        self.progress_bar.stop()
        self.progress_bar.hide()
        box.addWidget(self.progress_bar)
        self.progress_path = ElidedPathLabel()
        self.progress_path.hide()
        box.addWidget(self.progress_path)
        layout.addWidget(controls)

        metrics = QGridLayout()
        self.metric_labels = []
        for index, title in enumerate(("Tamaño lógico · en disco", "Archivos y carpetas", "Lecturas incompletas")):
            card = GlassCard()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 12, 16, 12)
            card_layout.addWidget(BodyLabel(title))
            value = SubtitleLabel("—")
            value.setWordWrap(True)
            self.metric_labels.append(value)
            card_layout.addWidget(value)
            metrics.addWidget(card, 0, index)
        layout.addLayout(metrics)
        self.volume_label = BodyLabel("Tamaño lógico por ruta; incluye archivos ocultos. No se siguen enlaces ni junctions.")
        self.volume_label.setWordWrap(True)
        layout.addWidget(self.volume_label)

        navigation = QHBoxLayout()
        self.up_button = PushButton(FluentIcon.UP, "Subir")
        self.up_button.setEnabled(False)
        self.up_button.clicked.connect(self.go_up)
        navigation.addWidget(self.up_button)
        self.breadcrumbs = QWidget()
        self.breadcrumbs.setMinimumWidth(0)
        self.breadcrumb_layout = QHBoxLayout(self.breadcrumbs)
        self.breadcrumb_layout.setContentsMargins(0, 0, 0, 0)
        self.breadcrumb_layout.setSpacing(4)
        navigation.addWidget(self.breadcrumbs, 1)
        self.list_mode = ComboBox()
        self.list_mode.setMinimumWidth(240)
        self.list_mode.setAccessibleName("Listado de espacio")
        self.list_mode.addItems(("Esta carpeta", "20 archivos más grandes", "20 carpetas más grandes", "Por extensión"))
        self.list_mode.currentIndexChanged.connect(self._refresh_view)
        navigation.addWidget(self.list_mode)
        layout.addLayout(navigation)
        self.filter_input = LineEdit()
        self.filter_input.setAccessibleName("Filtrar nombre o extensión en la carpeta actual")
        self.filter_input.setPlaceholderText("Filtrar nombre o extensión en esta carpeta (texto literal)")
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(180)
        self.filter_timer.timeout.connect(self._refresh_view)
        self.filter_input.textChanged.connect(lambda *_: self.filter_timer.start())
        layout.addWidget(self.filter_input)

        self.body_grid = QGridLayout()
        self.body_grid.setSpacing(14)
        self.map_card = GlassCard()
        map_layout = QVBoxLayout(self.map_card)
        map_layout.setContentsMargins(14, 14, 14, 14)
        map_layout.addWidget(SubtitleLabel("Mapa de esta carpeta"))
        self.map_hint = BodyLabel("Las áreas representan tamaños lógicos. Doble clic o Intro entra sólo en carpetas.")
        self.map_hint.setWordWrap(True)
        map_layout.addWidget(self.map_hint)
        self.space_map = SpaceMap(self.config)
        self.space_map.selected.connect(self._map_selected)
        self.space_map.folder_opened.connect(self.navigate_to)
        map_layout.addWidget(self.space_map, 1)
        self.table_card = GlassCard()
        table_layout = QVBoxLayout(self.table_card)
        table_layout.setContentsMargins(14, 14, 14, 14)
        self.table_title = SubtitleLabel("Elementos · mayor tamaño primero")
        self.table_title.setWordWrap(True)
        table_layout.addWidget(self.table_title)
        self.table = QTableView()
        self.table.setAccessibleName("Elementos y tamaños del análisis")
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(300)
        self.table.setMinimumWidth(0)
        self.table.verticalHeader().hide()
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.model = SpaceTableModel(self)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().currentRowChanged.connect(self._table_selected)
        self.table.doubleClicked.connect(self._activate_row)
        self.table.installEventFilter(self)
        table_layout.addWidget(self.table, 1)
        self.body_grid.addWidget(self.map_card, 0, 0)
        self.body_grid.addWidget(self.table_card, 0, 1)
        layout.addLayout(self.body_grid, 1)
        self.selection_path = ElidedPathLabel("Selecciona un elemento para ver su ubicación.")
        layout.addWidget(self.selection_path)
        # FlowLayout: los botones bajan de línea en ventanas estrechas (sin scroll horizontal).
        self.actions_bar = QWidget()
        self.actions_bar.setMinimumWidth(0)
        actions = FlowLayout(self.actions_bar, needAni=False)
        actions.setContentsMargins(0, 0, 0, 0)
        self.open_button = PushButton(FluentIcon.FOLDER, "Abrir ubicación")
        self.open_button.clicked.connect(self.open_location)
        self.copy_button = PushButton(FluentIcon.COPY, "Copiar ruta")
        self.copy_button.clicked.connect(self.copy_path)
        self.rescan_button = PushButton(FluentIcon.SYNC, "Volver a analizar esta carpeta")
        self.rescan_button.setToolTip("Mide de nuevo sólo la carpeta seleccionada (o la actual) y actualiza los totales")
        self.rescan_button.clicked.connect(self.rescan_folder)
        self.export_button = PushButton(FluentIcon.SAVE, "Exportar CSV")
        self.export_button.setToolTip("Guarda la carpeta actual (o el desglose por extensión) en un CSV")
        self.export_button.clicked.connect(lambda: self.export_csv())
        self.organize_button = PrimaryPushButton(FluentIcon.FOLDER_ADD, "Organizar esta carpeta")
        self.organize_button.setToolTip("Abre Organizar con la carpeta seleccionada (o la actual) como origen")
        self.organize_button.clicked.connect(self.request_organize)
        for button in (self.open_button, self.copy_button, self.rescan_button, self.export_button, self.organize_button):
            actions.addWidget(button)
        layout.addWidget(self.actions_bar)
        self.open_button.setEnabled(False)
        self.copy_button.setEnabled(False)
        for button in (self.rescan_button, self.export_button, self.organize_button):
            button.setEnabled(False)

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Carpeta o raíz de unidad", self.path_input.text())
        if folder:
            self.path_input.setText(folder)

    def start_scan(self):
        if self._worker is not None:
            return False
        path = self.path_input.text().strip()
        if not path:
            self.status_label.setText("Elige una carpeta o unidad antes de analizar.")
            self.path_input.setFocus()
            return False
        return self._start_worker(path)

    def _scan_options(self):
        getter = getattr(self.config, "get", None)
        options = getter("space_usage", {}) if callable(getter) else {}
        options = options if isinstance(options, dict) else {}
        return bool(options.get("size_on_disk", True)), bool(options.get("dedupe_hardlinks", True))

    def _start_worker(self, path, node_id=None):
        self._run_id += 1
        self._cancel_requested = False
        measure_disk, dedupe = self._scan_options()
        worker = SpaceScanWorker(self._run_id, path, self, base_result=self.result if node_id is not None else None,
                                 node_id=node_id, measure_disk=measure_disk, dedupe_hardlinks=dedupe)
        self._worker = worker
        worker.progress.connect(self._progress)
        worker.result_ready.connect(self._completed)
        worker.scan_cancelled.connect(self._cancelled)
        worker.scan_failed.connect(self._failed)
        worker.finished.connect(lambda: self._worker_finished(worker))
        self.analyze_button.setEnabled(False)
        self.path_input.setEnabled(False)
        self.browse_button.setEnabled(False)
        self.rescan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText("Analizando… El resultado anterior seguirá disponible hasta completar este análisis.")
        self.progress_path.set_path(os.path.abspath(path))
        self.progress_path.show()
        self.progress_bar.show()
        self.progress_bar.start()
        self.scan_state_changed.emit(True)
        worker.start()
        return True

    def _progress(self, run_id, files, folders, size, denied, path):
        if run_id != self._run_id or self._cancel_requested:
            return
        self.status_label.setText(f"Analizando: {files} archivos, {folders} carpetas · {format_bytes(size)} · {denied} accesos denegados.")
        self.progress_path.set_path(path)

    def cancel_scan(self):
        if self._worker is not None:
            self._cancel_requested = True
            self._worker.requestInterruption()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelación solicitada. Se conservará el resultado anterior.")

    def _completed(self, run_id, result):
        if run_id != self._run_id or self._cancel_requested or self._shutdown_callback is not None:
            return
        rescan, self._rescan_paths = self._rescan_paths, None
        self.result = result
        self.current_id = 0
        self.selected_id = None
        if rescan:
            # Tras un reanálisis parcial los ids posteriores cambian: se recolocan por ruta.
            current_path, selected_path = rescan
            self.current_id = result.find(current_path) or 0
            self.selected_id = result.find(selected_path) if selected_path else None
        completed = "Completado parcialmente" if result.nodes[0].status == "partial" else "Completado"
        prefix = "Carpeta actualizada · " if rescan else ""
        self.status_label.setText(f"{prefix}{completed} · {result.skipped_links} enlaces omitidos · {result.missing_count} desaparecidos · {result.error_count} errores.")
        root = result.nodes[0]
        measured = getattr(result, "measured_disk", False)
        disk_size = getattr(root, "disk_size", 0)
        self.metric_labels[0].setText(format_bytes(root.size) + (f" · {format_bytes(disk_size)} en disco" if measured else ""))
        self.metric_labels[0].setToolTip(f"{root.size:,} bytes lógicos · {disk_size:,} bytes ocupados en disco")
        self.metric_labels[1].setText(f"{result.file_count} archivos · {result.folder_count} carpetas")
        self.metric_labels[2].setText(f"{result.denied_count} denegados · {result.missing_count + result.error_count} errores")
        volume = "Ocupación de unidad no disponible."
        if result.volume:
            volume = f"Unidad: {format_bytes(result.volume[1])} ocupados · {format_bytes(result.volume[2])} libres."
        hardlinks = getattr(result, "hardlinks_deduped", 0)
        dedupe = f" {hardlinks} hardlinks contados una sola vez en disco." if hardlinks else ""
        self.volume_label.setText("El tamaño lógico se cuenta por ruta; el tamaño en disco incluye clústeres, "
                                  "compresión y hardlinks." + dedupe + " " + volume)
        self.volume_label.setToolTip("No se siguen enlaces ni junctions. La ocupación de la unidad incluye otros datos y reservas del sistema.")
        for button in (self.export_button, self.organize_button):
            button.setEnabled(True)
        self._refresh_view()
        self.result_changed.emit(result)

    def _cancelled(self, run_id):
        self._rescan_paths = None
        if run_id == self._run_id:
            self.status_label.setText("Análisis cancelado. Se conserva el resultado anterior.")

    def _failed(self, run_id, message):
        if run_id == self._run_id and not self._cancel_requested:
            self.status_label.setText(f"No se pudo analizar: {message}. Se conserva el resultado anterior.")

    def _worker_finished(self, worker):
        if worker is not self._worker:
            worker.deleteLater()
            return
        self._worker = None
        self.analyze_button.setEnabled(True)
        self.path_input.setEnabled(True)
        self.browse_button.setEnabled(True)
        self.rescan_button.setEnabled(self.result is not None)
        self.cancel_button.setEnabled(False)
        self.progress_path.hide()
        self.progress_bar.stop()
        self.progress_bar.hide()
        self.scan_state_changed.emit(False)
        worker.deleteLater()
        callback, self._shutdown_callback = self._shutdown_callback, None
        if callback:
            QTimer.singleShot(0, callback)

    def request_shutdown(self, callback):
        if self._worker is None:
            return False
        self._shutdown_callback = callback
        self.cancel_scan()
        return True

    def _refresh_view(self, *_):
        if self.result is None:
            return
        result = self.result
        mode = self.list_mode.currentIndex()
        self.filter_input.setEnabled(mode == 0)
        children = result.children.get(self.current_id, ())
        query = self.filter_input.text().strip().casefold() if mode == 0 else ""
        visible = tuple(index for index in children if query in result.nodes[index].name.casefold()) if query else children
        if mode == LIST_EXTENSIONS:
            rows = ()
            extensions = result.sorted_extensions() if hasattr(result, "sorted_extensions") else []
            self.model.set_extension_rows(result, extensions, result.nodes[0].size)
        else:
            rows = result.top_files if mode == LIST_FILES else result.top_folders if mode == LIST_FOLDERS else visible
            self.model.set_rows(result, rows, result.nodes[self.current_id].size if mode == 0 else result.nodes[0].size, mode != 0)
        shown = [result.nodes[index] for index in visible[:200]]
        visible_size = sum(result.nodes[index].size for index in visible) if query else result.nodes[self.current_id].size
        self.space_map.set_items(shown, max(0, len(visible) - 200), max(0, visible_size - sum(node.size for node in shown)))
        count = self.model.rowCount()
        self.table_title.setText(f"{count} extensiones · mayor tamaño primero" if mode == LIST_EXTENSIONS
                                 else f"{count} elementos · mayor tamaño primero")
        self.map_hint.setText("El mapa muestra esta carpeta; el listado compara todo el análisis. Las carpetas pueden contenerse entre sí." if mode == 2 else "Mapa de esta carpeta; el listado compara todo el análisis." if mode == 1 else "Áreas por tamaño lógico. Los pequeños se agrupan; todos siguen en la tabla.")
        self.up_button.setEnabled(self.current_id != 0)
        self._render_breadcrumbs()
        self.select_node(self.selected_id if self.selected_id in rows else None)

    def _render_breadcrumbs(self):
        while self.breadcrumb_layout.count():
            item = self.breadcrumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        ids = []
        node_id = self.current_id
        while node_id is not None:
            ids.append(node_id)
            node_id = self.result.nodes[node_id].parent_id
        ids.reverse()
        # Raíz + últimos niveles; ruta completa siempre en el tooltip.
        shown = ids if len(ids) <= 4 else [ids[0], *ids[-3:]]
        for node_id in shown:
            node = self.result.nodes[node_id]
            button = BreadcrumbButton(node)
            button.clicked.connect(lambda checked=False, index=node_id: self.navigate_to(index))
            self.breadcrumb_layout.addWidget(button)
        self.breadcrumb_layout.addStretch()

    def navigate_to(self, node_id):
        if self.result is None or self.result.nodes[node_id].kind != "folder":
            return
        self.list_mode.blockSignals(True)
        self.list_mode.setCurrentIndex(0)
        self.list_mode.blockSignals(False)
        self.filter_timer.stop()
        self.filter_input.blockSignals(True)
        self.filter_input.clear()
        self.filter_input.blockSignals(False)
        self.current_id = node_id
        self.selected_id = None
        self._refresh_view()

    def go_up(self):
        if self.result is not None and self.current_id:
            self.navigate_to(self.result.nodes[self.current_id].parent_id)

    def select_node(self, node_id):
        self.selected_id = node_id
        self.space_map.set_selected(node_id)
        selection = self.table.selectionModel()
        selection.blockSignals(True)
        selection.clearSelection()
        row = self.model.row_index.get(node_id)
        if row is not None:
            self.table.selectRow(row)
        selection.blockSignals(False)
        valid = node_id is not None and self.result is not None
        self.open_button.setEnabled(valid)
        self.copy_button.setEnabled(valid)
        self.rescan_button.setEnabled(self.result is not None and self._worker is None)
        self.selection_path.set_path(self.result.nodes[node_id].path if valid else "Selecciona un elemento para ver su ubicación.")

    def _map_selected(self, node_id):
        if self.list_mode.currentIndex() != 0:
            self.list_mode.blockSignals(True)
            self.list_mode.setCurrentIndex(0)
            self.list_mode.blockSignals(False)
            self.filter_input.blockSignals(True)
            self.filter_input.clear()
            self.filter_input.blockSignals(False)
            self.filter_timer.stop()
            self._refresh_view()
        self.select_node(node_id)

    def _table_selected(self, index, previous):
        if index.isValid() and not self.model.extension_mode:
            node_id = self.model.rows[index.row()]
            if self.list_mode.currentIndex() != 0 and self.result.nodes[node_id].parent_id != self.current_id:
                self.current_id = self.result.nodes[node_id].parent_id
                self._refresh_view()
            self.select_node(node_id)

    def _activate_row(self, index):
        if index.isValid() and not self.model.extension_mode:
            self.navigate_to(self.model.rows[index.row()])

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if obj is self.table and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._activate_row(self.table.currentIndex())
                return True
            if event.key() == Qt.Key.Key_Backspace:
                self.go_up()
                return True
        return super().eventFilter(obj, event)

    def _target_folder_id(self):
        """Carpeta seleccionada, o la carpeta actual si la selección es un archivo."""
        if self.result is None:
            return None
        if self.selected_id is not None and self.result.nodes[self.selected_id].kind == "folder":
            return self.selected_id
        return self.current_id

    def rescan_folder(self):
        """Reanálisis incremental de una subcarpeta (o de todo si es la raíz)."""
        if self._worker is not None or self.result is None:
            return False
        node_id = self._target_folder_id()
        if node_id is None:
            return False
        selected = self.result.nodes[self.selected_id].path if self.selected_id is not None else None
        self._rescan_paths = (self.result.nodes[self.current_id].path, selected)
        return self._start_worker(self.result.nodes[node_id].path, node_id)

    def request_organize(self):
        node_id = self._target_folder_id()
        if node_id is not None:
            self.organize_requested.emit(self.result.nodes[node_id].path)

    def export_csv(self, destination=None):
        """Exporta la carpeta actual (o el desglose por extensión) en segundo plano."""
        if self.result is None:
            return False
        extension_mode = self.list_mode.currentIndex() == LIST_EXTENSIONS
        if destination is None:
            name = "extensiones.csv" if extension_mode else f"espacio_{self.result.nodes[self.current_id].name or 'unidad'}.csv"
            destination, _ = QFileDialog.getSaveFileName(self, "Exportar a CSV", str(Path.home() / name), "CSV (*.csv)")
            if not destination:
                return False
        result, node_id = self.result, self.current_id

        def job():
            try:
                rows = export_extensions_csv(result, destination) if extension_mode else export_csv(result, destination, node_id)
                return f"Exportadas {rows} filas a {destination}."
            except OSError as error:
                logger.warning("No se pudo exportar el CSV: %s", error)
                return f"No se pudo exportar: {error.strerror or error}."

        future = self._export_pool.submit(job)
        future.add_done_callback(self._emit_export)
        self.export_button.setEnabled(False)
        return True

    def _emit_export(self, future):
        try:
            self.export_finished.emit(future.result())
        except RuntimeError:  # página destruida durante el cierre
            pass

    def _export_done(self, message):
        self.export_button.setEnabled(self.result is not None)
        self.status_label.setText(message)

    def open_location(self):
        if self.result is not None and self.selected_id is not None:
            node = self.result.nodes[self.selected_id]
            # Abrir sólo una carpeta. Un enlace nunca se abre ni se sigue.
            location = node.path if node.kind == "folder" and node.status in {"ok", "partial"} else str(Path(node.path).parent)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(location)):
                self.status_label.setText("No se pudo abrir la ubicación. Puedes copiar la ruta; el análisis se conserva.")

    def copy_path(self):
        if self.result is not None and self.selected_id is not None:
            QApplication.clipboard().setText(self.result.nodes[self.selected_id].path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "body_grid"):
            return
        columns = 2 if self.width() >= 980 else 1
        if columns != self._columns:
            self._columns = columns
            self.body_grid.removeWidget(self.table_card)
            self.body_grid.addWidget(self.table_card, 0 if columns == 2 else 1, 1 if columns == 2 else 0)
            self.body_grid.setColumnStretch(0, 1)
            self.body_grid.setColumnStretch(1, 1 if columns == 2 else 0)
