"""Inicio operativo con snapshots reales y accesos compactos."""

from pathlib import Path
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, FluentIcon, LineEdit, PrimaryPushButton, PushButton, ScrollArea, SubtitleLabel
from src.gui.task_center import task_registry
from src.gui.v2.components import ActionBar, GlassCard, MetricCard, PageHeader
from src.gui.v2.dashboard_charts import DiskUsageChart, FolderSizeChart, disk_values
from src.gui.v2.space_map import format_bytes
from src.gui.v2.theme import ElidedPathLabel, current_tokens, typography_scale
from src.utils.app_config import AppConfig


ACTIVE_STATUSES = {"En progreso", "Cancelación solicitada"}


class HomePage(ScrollArea):
    navigate_requested = pyqtSignal(str)
    analyze_requested = pyqtSignal(str)
    result_requested = pyqtSignal()
    undo_requested = pyqtSignal()

    def __init__(self, config: AppConfig, profile_manager, parent=None):
        super().__init__(parent)
        self.setObjectName("homePage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.config = config
        self.profile_manager = profile_manager
        self._controller = None
        self._disks = ()
        self._space_result = None
        self._space_running = False
        self._disk_updated_at = None
        self._disk_error = None
        self._metric_columns = 0
        self._chart_columns = 0
        self.setWidgetResizable(True)
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        self.enableTransparentBackground()
        self.content = QWidget()
        self.content.setObjectName("homeContent")
        self.content.setMinimumWidth(0)
        self.content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setWidget(self.content)
        self._build_ui()
        task_registry.tasks_updated.connect(self.refresh_metrics)
        self.refresh()

    @staticmethod
    def _card(title):
        card = GlassCard()
        card.setMinimumWidth(0)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(9)
        layout.addWidget(SubtitleLabel(title))
        return card, layout

    def _build_ui(self):
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(28, 22, 28, 28)
        outer.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.dashboard_panel = QWidget()
        self.dashboard_panel.setObjectName("homeDashboard")
        self.dashboard_panel.setMaximumWidth(1440)
        self.dashboard_panel.setMinimumWidth(0)
        self.dashboard_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        outer.addWidget(self.dashboard_panel)
        layout = QVBoxLayout(self.dashboard_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(PageHeader("Inicio", "Tu espacio y tu actividad, con los últimos datos disponibles."))

        self.metrics_grid = QGridLayout()
        self.metrics_grid.setSpacing(12)
        self.disk_metric = MetricCard(FluentIcon.SAVE_AS, "Unidad seleccionada", "—", "Ocupación no disponible")
        self.space_metric = MetricCard(FluentIcon.FOLDER, "Carpeta analizada", "—", "Sin análisis de espacio")
        self.task_metric = MetricCard(FluentIcon.SYNC, "Tareas activas", "0", "Sin tareas en curso")
        self.organize_metric = MetricCard(FluentIcon.COMPLETED, "Última organización", "—", "Sin organización en esta sesión")
        self.metric_cards = (self.disk_metric, self.space_metric, self.task_metric, self.organize_metric)
        for card in self.metric_cards:
            card.title_label.setWordWrap(True)
            card.value_label.setWordWrap(True)
            card.value_label.setMinimumWidth(0)
        layout.addLayout(self.metrics_grid)

        quick_card, quick = self._card("Organizar una carpeta")
        self.path_row = ActionBar()
        self.path_input = LineEdit()
        self.path_input.setAccessibleName("Ruta de carpeta para analizar")
        self.path_input.setPlaceholderText("Carpeta que quieres revisar y organizar")
        self.path_input.setClearButtonEnabled(True)
        self.path_input.setMinimumWidth(0)
        self.path_input.returnPressed.connect(self._analyze)
        self.browse_button = PushButton(FluentIcon.FOLDER, "Elegir carpeta")
        self.browse_button.setAccessibleName("Examinar carpetas")
        self.browse_button.clicked.connect(self._choose_folder)
        self.analyze_button = PrimaryPushButton(FluentIcon.SEARCH, "Analizar carpeta")
        self.analyze_button.setAccessibleName("Analizar carpeta ahora")
        self.analyze_button.clicked.connect(self._analyze)
        self.path_row.content_layout.addWidget(self.path_input, 1)
        self.path_row.content_layout.addWidget(self.browse_button)
        self.path_row.content_layout.addWidget(self.analyze_button)
        quick.addWidget(self.path_row)
        self.path_error = BodyLabel("")
        self.path_error.setWordWrap(True)
        self.path_error.hide()
        quick.addWidget(self.path_error)
        recent_row = QHBoxLayout()
        recent_row.addWidget(BodyLabel("Recientes y favoritas"))
        self.recent_paths = ComboBox()
        self.recent_paths.setAccessibleName("Rutas recientes")
        self.recent_paths.setMinimumWidth(0)
        self.recent_paths.setMaximumWidth(480)
        self.recent_paths.currentTextChanged.connect(self._use_recent_path)
        recent_row.addWidget(self.recent_paths, 1)
        recent_row.addStretch()
        quick.addLayout(recent_row)
        layout.addWidget(quick_card)

        self.charts_grid = QGridLayout()
        self.charts_grid.setSpacing(14)
        self.disk_card, disk = self._card("Ocupación de la unidad")
        self.drive_selector = ComboBox()
        self.drive_selector.setAccessibleName("Unidad del resumen de ocupación")
        self.drive_selector.setMinimumWidth(0)
        self.drive_selector.setMaximumWidth(360)
        self.drive_selector.currentIndexChanged.connect(self._update_drive)
        disk.addWidget(self.drive_selector)
        self.usage_chart = DiskUsageChart(self.config)
        disk.addWidget(self.usage_chart)
        self.disk_snapshot_label = BodyLabel("Datos no disponibles")
        self.disk_snapshot_label.setWordWrap(True)
        disk.addWidget(self.disk_snapshot_label)
        self.open_disks_button = PushButton(FluentIcon.SAVE_AS, "Abrir Discos")
        self.open_disks_button.clicked.connect(lambda: self.navigate_requested.emit("disk-health"))
        disk.addWidget(self.open_disks_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.space_card, space = self._card("Qué ocupa espacio")
        self.space_path_label = ElidedPathLabel("Sin análisis de espacio")
        self.space_path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        space.addWidget(self.space_path_label)
        self.folders_chart = FolderSizeChart(self.config)
        space.addWidget(self.folders_chart)
        self.space_snapshot_label = BodyLabel("Tamaño lógico de los hijos de la carpeta analizada.")
        self.space_snapshot_label.setWordWrap(True)
        space.addWidget(self.space_snapshot_label)
        self.open_space_button = PushButton(FluentIcon.SEARCH, "Analizar espacio")
        self.open_space_button.clicked.connect(lambda: self.navigate_requested.emit("space"))
        space.addWidget(self.open_space_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(self.charts_grid)

        self.results_grid = QGridLayout()
        self.results_grid.setSpacing(14)
        self.activity_card, activity = self._card("Actividad reciente")
        self.activity_labels = []
        for _ in range(3):
            label = ElidedPathLabel("")
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            activity.addWidget(label)
            self.activity_labels.append(label)
        self.activity_button = PushButton(FluentIcon.HISTORY, "Ver actividad")
        self.activity_button.clicked.connect(lambda: self.navigate_requested.emit("activity"))
        activity.addWidget(self.activity_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.last_card, last = self._card("Última organización")
        self.last_operation_label = BodyLabel("Todavía no hay un resultado de organización en esta sesión.")
        self.last_operation_label.setWordWrap(True)
        last.addWidget(self.last_operation_label)
        self.result_button = PushButton(FluentIcon.HISTORY, "Ver resultado")
        self.result_button.clicked.connect(self.result_requested.emit)
        self.result_button.setEnabled(False)
        self.undo_button = PushButton(FluentIcon.RETURN, "Deshacer")
        self.undo_button.setAccessibleName("Deshacer última organización")
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.undo_button.setEnabled(False)
        row = ActionBar()
        row.content_layout.addWidget(self.result_button)
        row.content_layout.addWidget(self.undo_button)
        row.content_layout.addStretch()
        last.addWidget(row)
        layout.addLayout(self.results_grid)

        self.shortcuts_grid = QGridLayout()
        self.shortcuts_grid.setSpacing(10)
        self.shortcut_buttons = []
        for route, icon, text in (("organize", FluentIcon.FOLDER, "Organizar"), ("space", FluentIcon.SAVE_AS, "Uso del espacio"),
                                  ("duplicates", FluentIcon.COPY, "Duplicados"), ("music", FluentIcon.MUSIC, "Música")):
            button = PushButton(icon, text)
            button.clicked.connect(lambda checked=False, target=route: self.navigate_requested.emit(target))
            self.shortcut_buttons.append(button)
        layout.addLayout(self.shortcuts_grid)
        self._adapt_layout()
        self.update_dashboard((), None)
        self.refresh_theme()

    def refresh_theme(self):
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        size = max(22, typography_scale(self.config).display + 2)
        for card in self.metric_cards:
            card.value_label.setStyleSheet(f"color: {tokens.text_primary}; background: transparent; font-size: {size}px; font-weight: 600;")
        self.usage_chart.update()
        self.folders_chart.update()

    def _adapt_layout(self):
        width = min(1440, self.viewport().width() - 56)
        metric_columns = 4 if width >= 980 else 2
        chart_columns = 2 if width >= 850 else 1
        if metric_columns != self._metric_columns:
            for card in self.metric_cards:
                self.metrics_grid.removeWidget(card)
            for index, card in enumerate(self.metric_cards):
                self.metrics_grid.addWidget(card, index // metric_columns, index % metric_columns)
            for column in range(4):
                self.metrics_grid.setColumnStretch(column, 1 if column < metric_columns else 0)
            for button in self.shortcut_buttons:
                self.shortcuts_grid.removeWidget(button)
            for index, button in enumerate(self.shortcut_buttons):
                self.shortcuts_grid.addWidget(button, index // metric_columns, index % metric_columns)
            self._metric_columns = metric_columns
        if chart_columns != self._chart_columns:
            for grid, cards in ((self.charts_grid, (self.disk_card, self.space_card)), (self.results_grid, (self.activity_card, self.last_card))):
                for card in cards:
                    grid.removeWidget(card)
                for index, card in enumerate(cards):
                    grid.addWidget(card, index // chart_columns, index % chart_columns)
                grid.setColumnStretch(0, 1)
                grid.setColumnStretch(1, 1 if chart_columns == 2 else 0)
            self._chart_columns = chart_columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "dashboard_panel"):
            self._adapt_layout()

    def refresh(self):
        paths = list(dict.fromkeys(self.config.get_favorite_paths() + self.config.get_recent_paths()))
        self.recent_paths.blockSignals(True)
        self.recent_paths.clear()
        self.recent_paths.addItem("Elige una ruta reciente")
        self.recent_paths.addItems(paths)
        self.recent_paths.setEnabled(bool(paths))
        self.recent_paths.blockSignals(False)
        self.refresh_metrics()

    def refresh_metrics(self):
        tasks = task_registry.get_tasks()
        active = sum(task.get("status") in ACTIVE_STATUSES for _, task in tasks) + int(self._space_running)
        self.task_metric.set_value(str(active), "Procesos en curso" if active else "Sin tareas en curso")
        ordered = sorted(tasks, key=lambda pair: (pair[1].get("status") in ACTIVE_STATUSES, pair[1].get("started_at")), reverse=True)
        texts = []
        if self._space_running:
            texts.append("Uso del espacio · En curso")
        texts.extend(f"{task.get('title', 'Tarea')} · {task.get('status', 'Estado no disponible')}" +
                     (f" · {task['last_message']}" if task.get("last_message") else "") for _, task in ordered[:3])
        if not texts:
            texts = ["Sin tareas registradas en esta sesión."]
        for index, label in enumerate(self.activity_labels):
            label.set_path(texts[index] if index < len(texts) else "")
            label.setVisible(index < len(texts))

    def set_space_scan_active(self, active):
        self._space_running = bool(active)
        self.refresh_metrics()

    def update_dashboard(self, disks, space_result, disk_updated_at=None, disk_error=None, selected_mountpoint=None):
        current = self.drive_selector.currentData()
        self._disks = tuple(disks or ())
        self._space_result = space_result
        self._disk_updated_at, self._disk_error = disk_updated_at, disk_error
        self.drive_selector.blockSignals(True)
        self.drive_selector.clear()
        for disk in self._disks:
            self.drive_selector.addItem(disk.mountpoint, userData=disk.mountpoint)
        if not self._disks:
            self.drive_selector.addItem("Sin unidades disponibles")
        desired = current or selected_mountpoint
        index = next((index for index, disk in enumerate(self._disks) if disk.mountpoint == desired), 0)
        self.drive_selector.setCurrentIndex(index)
        self.drive_selector.setEnabled(bool(self._disks))
        self.drive_selector.blockSignals(False)
        self._update_drive()
        self.folders_chart.set_result(space_result)
        if space_result:
            root = space_result.nodes[0]
            self.space_metric.set_value(format_bytes(root.size), f"{space_result.file_count} archivos · {space_result.folder_count} carpetas")
            self.space_metric.setToolTip(f"{space_result.root_path}\n{root.size:,} bytes lógicos")
            self.space_path_label.set_path(space_result.root_path)
            self.space_snapshot_label.setText("Análisis parcial: hay entradas sin leer." if root.status == "partial" else "Cinco elementos mayores y el resto · tamaño lógico por ruta.")
            self.open_space_button.setText("Ver análisis de espacio")
        else:
            self.space_metric.set_value("—", "Sin análisis de espacio")
            self.space_path_label.set_path("Sin análisis de espacio")
            self.space_snapshot_label.setText("Analiza una carpeta para conocer su distribución.")
            self.open_space_button.setText("Analizar espacio")

    def _update_drive(self, *_):
        index = self.drive_selector.currentIndex()
        disk = self._disks[index] if 0 <= index < len(self._disks) else None
        self.usage_chart.set_disk(disk)
        values = disk_values(disk)
        if values:
            total, used, free = values
            self.disk_metric.set_value(f"{used / total * 100:.1f}%", f"Ocupado · {format_bytes(free)} libres")
            self.disk_metric.setToolTip(self.usage_chart.accessibleDescription())
        else:
            self.disk_metric.set_value("—", "Ocupación no disponible")
            self.disk_metric.setToolTip("No hay un snapshot válido de ocupación.")
        stamp = self._disk_updated_at.strftime("%H:%M:%S") if self._disk_updated_at else None
        text = f"Última actualización en Discos · {stamp}" if stamp else "Datos no disponibles; abre Discos para consultarlos."
        if self._disk_error:
            text = (f"Últimos datos · {stamp}. " if stamp else "") + "No se pudo actualizar; consulta Discos."
        self.disk_snapshot_label.setText(text)
        self.disk_snapshot_label.setToolTip(self._disk_error or text)

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Selecciona una carpeta para analizar", self.path_input.text() or str(Path.home()))
        if folder:
            self.path_input.setText(folder)

    def _use_recent_path(self, path):
        if self.recent_paths.currentIndex() > 0 and path:
            self.path_input.setText(path)

    def _analyze(self):
        path = self.path_input.text().strip()
        if not path or not Path(path).is_dir():
            self.path_error.setText("Elige una carpeta existente para continuar.")
            self.path_error.show()
            self.path_input.setFocus()
            return
        self.path_error.setText("")
        self.path_error.hide()
        self.analyze_requested.emit(path)

    def update_operation(self, controller):
        self._controller = controller
        summary = controller.last_operation_summary
        active = bool(controller.current_organize_task_id)
        self.result_button.setEnabled(bool(summary))
        self.undo_button.setEnabled(bool(controller.last_transaction_id) and not active and not bool(summary and summary.get("undone")))
        if active:
            self.last_operation_label.setText("Organización en curso. Puedes seguir su progreso en Actividad.")
        elif summary:
            status = "Deshecha" if summary.get("undone") else "Resultado disponible"
            self.last_operation_label.setText(f"{status}: {summary.get('folders_moved', 0)} carpetas y "
                f"{summary.get('files_moved', 0)} archivos movidos; {summary.get('skipped_duplicates', 0)} duplicados omitidos; "
                f"{len(summary.get('errors', []))} errores.")
        else:
            self.last_operation_label.setText("Todavía no hay un resultado de organización en esta sesión.")
        if summary:
            self.organize_metric.set_value(str(summary.get("files_moved", 0)), "Archivos movidos · deshecha" if summary.get("undone") else "Archivos movidos")
        else:
            self.organize_metric.set_value("—", "Organización en curso" if active else "Sin organización en esta sesión")
