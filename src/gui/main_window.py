#!/usr/bin/env python3
"""
Vista de Organizar y fábrica de las herramientas heredadas.

``FileOrganizerGUI`` construye la página Organizar (ruta, opciones, tabla de
resultados y acciones) sobre un ``OrganizeController`` sin interfaz, que
guarda el estado y los workers. Las demás herramientas (Discos, Música y
Duplicados) se crean bajo demanda con ``create_*``.

- ``fluent_mode=True`` (lo usa la ventana Fluent): sin pestañas, sin tema
  heredado ni atajos propios; cada página V2 pide su widget cuando se abre.
- ``fluent_mode=False``: ventana autónoma con pestañas (compatibilidad).
"""

import os
from collections import defaultdict
from typing import List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.core.application_state import app_state
from src.core.organization_profiles import ProfileManager
from src.core.transaction_manager import TransactionManager
from src.gui.config_dialog import ConfigDialog
from src.gui.duplicates_dashboard import CheckboxDelegate
from src.gui.filter_bar import FilterBar
from src.gui.operation_summary_dialog import OperationSummaryDialog
from src.gui.organize_controller import OrganizeController
from src.gui.preview_dialog import PreviewDialog
from src.gui.table_models import VirtualizedMovementsModel
from src.gui.task_center import TaskCenterDialog
from qfluentwidgets import ComboBox, FluentIcon

from src.gui.v2.components import EmptyState
from src.gui.v2.theme import (
    apply_control_sizes,
    apply_fluent_theme,
    apply_legacy_surface_style,
    apply_menu_surface,
    bind_path_tooltip,
    typography_scale,
)
from src.utils.app_config import get_app_config, set_app_config
from src.utils.constants import UI_CONFIG
from src.utils.formatting import format_bytes

# Anchos de la tabla de movimientos: casilla, elemento (elástica), destino,
# porcentaje, archivos y tamaño.
MOVEMENT_COLUMN_WIDTHS = {0: 40, 2: 180, 3: 86, 4: 92, 5: 112}


class FileOrganizerGUI(QMainWindow):
    """Vista de Organizar (y, fuera de Fluent, ventana con pestañas).

    Usa inyección de dependencias opcional para facilitar testing.
    """

    def __init__(self, app_state_ref=None, category_manager=None, app_config_ref=None,
                 fluent_mode: bool = False, controller: OrganizeController | None = None):
        super().__init__()
        self.fluent_mode = bool(fluent_mode)

        # === DEPENDENCIAS (inyectables para testing) ===
        self._app_state = app_state_ref or app_state
        self.category_manager = category_manager or self._app_state.category_manager
        if self.category_manager is None:
            from src.core.category_manager import CategoryManager

            self.category_manager = CategoryManager()

        self.app_config = app_config_ref or self._app_state.app_config or get_app_config()
        # Una única configuración en todo el proceso: las vistas y servicios
        # que no la reciben inyectada usan esta (get_app_config()).
        set_app_config(self.app_config)

        self.controller = controller or OrganizeController(TransactionManager(), self)
        self.controller.analysis_completed.connect(self.on_analysis_complete)
        self.controller.analysis_cancelled.connect(self.on_analysis_cancelled)
        self.controller.analysis_failed.connect(self.on_analysis_error)
        self.controller.organize_finished.connect(self.on_organize_complete)
        self.controller.rollback_finished.connect(self.on_rollback_finished)
        self.controller.operation_state_changed.connect(self._sync_action_buttons)
        self.controller.log_appended.connect(self._append_log_lines)
        self.controller.log_cleared.connect(self._on_log_cleared)

        self.disk_manager = None  # Se obtiene de app_state en _init_disk_manager
        self.disk_viewer = None
        self.music_duplicates_view = None
        self.duplicates_dashboard = None
        self.main_tabs = None
        self.log_text = None
        self.log_info_label = None

        # === DATOS LOCALES ===
        self.folder_movements = []
        self.file_movements = []
        self.profile_manager = ProfileManager()
        # Exclusiones del perfil cargado (independientes de las rutas protegidas)
        self._profile_exclusions: List[str] = []
        self._analysis_folder_path = None
        self._analysis_result_path = None
        self._organization_review_open = False

        # === INICIALIZACIÓN ===
        self.init_ui()
        self._init_disk_manager()
        if not self.fluent_mode:
            self.setup_shortcuts()
        self.apply_saved_interface_settings()
        active_profile = self.profile_manager.get_active_profile()
        if active_profile:
            self.profile_combo.setCurrentText(active_profile.name)
        self.refresh_saved_paths()
        self.update_selection_count()
        # Última red de seguridad: nunca destruir un QThread en marcha al salir
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._shutdown_workers)

    # ------------------------------------------------- estado (controlador)
    # La vista y la V2 leen el estado del controlador; estas propiedades
    # mantienen la API anterior de la ventana.
    @property
    def operation_state_changed(self):
        return self.controller.operation_state_changed

    @property
    def transaction_manager(self):
        return self.controller.transaction_manager

    @property
    def last_transaction_id(self):
        return self.controller.last_transaction_id

    @last_transaction_id.setter
    def last_transaction_id(self, value):
        self.controller.last_transaction_id = value

    @property
    def last_operation_summary(self):
        return self.controller.last_operation_summary

    @last_operation_summary.setter
    def last_operation_summary(self, value):
        self.controller.last_operation_summary = value

    @property
    def current_analysis_task_id(self):
        return self.controller.current_analysis_task_id

    @property
    def current_organize_task_id(self):
        return self.controller.current_organize_task_id

    @property
    def current_rollback_task_id(self):
        return self.controller.current_rollback_task_id

    def get_transaction_history(self, limit: int = 50):
        return self.controller.get_transaction_history(limit)

    # ------------------------------------------------------------ discos
    def _init_disk_manager(self):
        """Obtiene el DiskManager compartido (sin enumerar unidades)."""
        try:
            self.disk_manager = self._app_state.get_disk_manager()
        except Exception as exc:  # El resto de la aplicación debe seguir
            self.log_message(f"⚠️ No se pudo inicializar el gestor de discos: {exc}")
            self.disk_manager = None
            return
        if self.disk_manager is None:
            self.log_message("⚠️ No se pudo inicializar el gestor de discos")
        elif self.disk_viewer is not None:
            self.disk_viewer.disk_manager = self.disk_manager
            self.disk_viewer.refresh_disks()

    # ------------------------------------------------------- herramientas
    def create_disk_viewer(self):
        """Visor de Discos (se crea una vez, al abrir su página)."""
        if self.disk_viewer is None:
            from src.gui.disk_viewer import DiskViewer

            self.disk_viewer = DiskViewer(disk_manager=None, app_config=self.app_config)
            self.disk_viewer.disk_selected.connect(self.on_disk_selected_for_organize)
            if self.disk_manager is not None:
                self.disk_viewer.disk_manager = self.disk_manager
                self.disk_viewer.refresh_disks()
        return self.disk_viewer

    def create_music_view(self):
        """Vista de Música (se crea una vez, al abrir su página)."""
        if self.music_duplicates_view is None:
            from src.gui.music_duplicates_view import MusicDuplicatesView

            self.music_duplicates_view = MusicDuplicatesView(app_config=self.app_config)
            self.music_duplicates_view.status_update.connect(self.log_message)
            self.music_duplicates_view.setEnabled(bool(self.app_config.get_audio_enabled()))
        return self.music_duplicates_view

    def create_duplicates_dashboard(self):
        """Panel de Duplicados (se crea una vez, al abrir su página)."""
        if self.duplicates_dashboard is None:
            from src.gui.duplicates_dashboard import DuplicatesDashboard

            self.duplicates_dashboard = DuplicatesDashboard()
            self.duplicates_dashboard.tab_header.config_requested.connect(self.open_configuration)
            self.duplicates_dashboard.tab_header.tasks_requested.connect(self.open_task_center)
            self.duplicates_dashboard.status_update.connect(self.log_message)
        return self.duplicates_dashboard

    # ---------------------------------------------------------------- UI
    def init_ui(self):
        self.setWindowTitle(UI_CONFIG["WINDOW_TITLE"])
        self.setGeometry(100, 100, 1280, 760)
        self.setMinimumSize(900, 600)
        self.organize_widget = self._build_organize_tab()
        if self.fluent_mode:
            # La página Organizar de la V2 adopta organize_widget.
            self.setCentralWidget(QWidget())
            apply_control_sizes(self.organize_widget, self.app_config)
            return

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main = QVBoxLayout(central_widget)
        main.setContentsMargins(0, 0, 0, 0)
        self.main_tabs = QTabWidget()
        self.main_tabs.setObjectName("main_tabs")
        self.main_tabs.setDocumentMode(True)
        main.addWidget(self.main_tabs)
        self.main_tabs.addTab(self.organize_widget, "Organizar")
        self.main_tabs.addTab(self.create_disk_viewer(), "Discos")
        self._music_tab_index = self.main_tabs.addTab(self.create_music_view(), "Música")
        self.main_tabs.addTab(self.create_duplicates_dashboard(), "Duplicados")
        self.main_tabs.addTab(self._build_log_tab(), "Registro")
        self._apply_audio_tab_visibility()
        apply_control_sizes(self, self.app_config)

    def _build_organize_tab(self) -> QWidget:
        organ = QWidget()
        organ.setObjectName("organizeView")
        ol = QVBoxLayout(organ)
        ol.setContentsMargins(12, 12, 12, 12)
        ol.setSpacing(8)

        # Cabecera (en Fluent la sustituye la cabecera de la página)
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 4)
        hdr.setSpacing(8)
        tl = QLabel("Organizador de archivos")
        tl.setObjectName("main_title_label")
        tl.setWordWrap(True)
        tl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        hdr.addWidget(tl, 1)
        self.config_btn = QPushButton("Configurar")
        self.config_btn.setMinimumWidth(96)
        self.config_btn.clicked.connect(self.open_configuration)
        hdr.addWidget(self.config_btn)
        self.task_center_btn = QPushButton("Tareas")
        self.task_center_btn.setMinimumWidth(82)
        self.task_center_btn.clicked.connect(self.open_task_center)
        hdr.addWidget(self.task_center_btn)
        if self.fluent_mode:
            for widget in (tl, self.config_btn, self.task_center_btn):
                widget.hide()
        ol.addLayout(hdr)

        # Carpeta de origen + opciones
        source_group = QWidget()
        source_group.setObjectName("organizeSource")
        source_layout = QVBoxLayout(source_group)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(8)

        source_header = QHBoxLayout()
        source_header.setSpacing(8)
        source_title = QLabel("Carpeta de origen")
        source_title.setObjectName("organizeSectionTitle")
        source_header.addWidget(source_title)
        source_summary = QLabel("Elige una carpeta y pulsa Analizar. Las opciones avanzadas añaden perfiles, duplicados y exclusiones.")
        source_summary.setObjectName("organizeHint")
        source_summary.setWordWrap(True)
        source_header.addWidget(source_summary, 1)
        self.advanced_mode_toggle = QPushButton("Opciones avanzadas")
        self.advanced_mode_toggle.setCheckable(True)
        self.advanced_mode_toggle.toggled.connect(self.on_advanced_mode_toggled)
        source_header.addWidget(self.advanced_mode_toggle)
        source_layout.addLayout(source_header)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("Escribe o pega la ruta de la carpeta")
        self.folder_input.setMinimumWidth(180)
        bind_path_tooltip(self.folder_input)
        self.folder_input.textChanged.connect(self.on_folder_path_changed)
        self.folder_input.textChanged.connect(lambda _text: self.update_favorite_button_state())
        path_row.addWidget(self.folder_input, 1)
        self.browse_btn = QPushButton("Examinar")
        self.browse_btn.setMinimumWidth(96)
        self.browse_btn.clicked.connect(self.browse_folder)
        path_row.addWidget(self.browse_btn)
        self.add_favorite_btn = QPushButton("Favorito")
        self.add_favorite_btn.setMinimumWidth(84)
        self.add_favorite_btn.clicked.connect(self.add_current_path_to_favorites)
        path_row.addWidget(self.add_favorite_btn)
        source_layout.addLayout(path_row)

        recent_row = QHBoxLayout()
        recent_row.setSpacing(8)
        recent_label = QLabel("Recientes y favoritas:")
        recent_row.addWidget(recent_label)
        self.path_memory_combo = ComboBox()
        self.path_memory_combo.setAccessibleName("Rutas recientes y favoritas")
        self.path_memory_combo.setPlaceholderText("Sin rutas guardadas")
        self.path_memory_combo.setMinimumWidth(220)
        self.path_memory_combo.currentIndexChanged.connect(lambda _index: self.use_selected_saved_path())
        recent_label.setBuddy(self.path_memory_combo)
        recent_row.addWidget(self.path_memory_combo, 1)
        source_layout.addLayout(recent_row)

        opts_row = QHBoxLayout()
        opts_row.setSpacing(16)
        self.move_folders_checkbox = QCheckBox("Mover carpetas completas")
        self.move_folders_checkbox.setChecked(True)
        opts_row.addWidget(self.move_folders_checkbox)
        self.organize_by_date_checkbox = QCheckBox("Organizar por fecha")
        opts_row.addWidget(self.organize_by_date_checkbox)
        opts_row.addStretch()
        self.analyze_btn = QPushButton("Analizar")
        self.analyze_btn.setObjectName("analyze_button")
        self.analyze_btn.setProperty("primary", True)
        self.analyze_btn.setMinimumWidth(92)
        self.analyze_btn.clicked.connect(self.start_analysis)
        opts_row.addWidget(self.analyze_btn)
        source_layout.addLayout(opts_row)

        self.advanced_controls = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_controls)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        technical_row = QHBoxLayout()
        technical_row.addWidget(QLabel("Similitud:"))
        self.similarity_spinbox = QSpinBox()
        self.similarity_spinbox.setRange(0, 100)
        self.similarity_spinbox.setValue(70)
        self.similarity_spinbox.setSuffix("%")
        self.similarity_spinbox.setMinimumWidth(64)
        technical_row.addWidget(self.similarity_spinbox)
        technical_row.addSpacing(16)
        technical_row.addWidget(QLabel("Tamaño mínimo:"))
        self.min_size_spinbox = QSpinBox()
        self.min_size_spinbox.setRange(0, 10240)
        self.min_size_spinbox.setSuffix(" MB")
        self.min_size_spinbox.setMinimumWidth(86)
        technical_row.addWidget(self.min_size_spinbox)
        technical_row.addStretch()
        advanced_layout.addLayout(technical_row)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        profile_label = QLabel("Perfil:")
        profile_row.addWidget(profile_label)
        self.profile_combo = ComboBox()
        self.profile_combo.setAccessibleName("Perfil de organización")
        self.profile_combo.setPlaceholderText("Sin perfiles")
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.addItems(self.profile_manager.get_profile_names())
        profile_label.setBuddy(self.profile_combo)
        profile_row.addWidget(self.profile_combo)
        self.load_profile_btn = QPushButton("Cargar")
        self.load_profile_btn.clicked.connect(self.load_selected_profile)
        profile_row.addWidget(self.load_profile_btn)
        self.save_profile_btn = QPushButton("Guardar perfil")
        self.save_profile_btn.clicked.connect(self.save_current_profile)
        profile_row.addWidget(self.save_profile_btn)
        profile_row.addStretch()
        advanced_layout.addLayout(profile_row)

        advanced_row = QHBoxLayout()
        advanced_row.setSpacing(8)
        self.check_duplicates_checkbox = QCheckBox("Buscar duplicados")
        self.check_duplicates_checkbox.setChecked(True)
        advanced_row.addWidget(self.check_duplicates_checkbox)
        self.manage_exclusions_btn = QPushButton("Gestionar exclusiones")
        self.manage_exclusions_btn.clicked.connect(self.open_exclusions_configuration)
        advanced_row.addWidget(self.manage_exclusions_btn)
        advanced_row.addStretch()
        advanced_layout.addLayout(advanced_row)
        self.advanced_controls.setVisible(False)
        source_layout.addWidget(self.advanced_controls)
        ol.addWidget(source_group)

        self.filter_bar = FilterBar(sorted(self.category_manager.get_categories().keys()), self)
        self.filter_bar.filter_changed.connect(self._on_filter_changed)
        self.filter_bar.select_all_requested.connect(self.select_all_items)
        self.filter_bar.deselect_all_requested.connect(self.deselect_all_items)
        self.filter_bar.embed_selection_bar()
        self.select_all_btn = self.filter_bar.select_all_btn
        self.deselect_all_btn = self.filter_bar.deselect_all_btn
        self.selection_count_label = self.filter_bar.selection_count_label
        self.total_size_label = self.filter_bar.total_size_label
        self.total_files_label = self.filter_bar.total_files_label
        ol.addWidget(self.filter_bar)

        # Tabla principal (virtualizada)
        self.movements_table = QTableView()
        self.movements_model = VirtualizedMovementsModel()
        self.movements_table.setModel(self.movements_model)
        self.movements_table.setItemDelegateForColumn(0, CheckboxDelegate(self.movements_table))
        self.movements_table.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding))
        self.movements_table.setMinimumHeight(220)
        self.movements_table.verticalHeader().setDefaultSectionSize(typography_scale(self.app_config).row_height)
        self.movements_table.setAlternatingRowColors(True)
        self.movements_table.setShowGrid(False)
        self.movements_table.setWordWrap(False)
        self.movements_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.movements_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.movements_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.movements_table.customContextMenuRequested.connect(self.show_context_menu)
        header = self.movements_table.horizontalHeader()
        self._apply_movement_column_widths()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in range(2, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_clicked)
        ol.addWidget(self.movements_table, 1)
        self.results_empty_state = EmptyState(
            FluentIcon.FOLDER, "Elige una carpeta y pulsa Analizar para ver qué se puede organizar.",
            "Elegir carpeta", primary=False)
        self.results_empty_state.setMinimumHeight(220)
        self.results_empty_state.action_requested.connect(self.browse_folder)
        ol.addWidget(self.results_empty_state, 1)
        self.movements_model.dataChanged.connect(self.on_model_data_changed)
        self.movements_table.doubleClicked.connect(self.on_table_double_clicked)

        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)
        self.preview_btn = QPushButton("Vista previa")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self.open_selection_preview)
        self.preview_btn.hide()
        self.organize_btn = QPushButton("Revisar y organizar")
        self.organize_btn.setObjectName("organize_button")
        self.organize_btn.setProperty("primary", True)
        self.organize_btn.setEnabled(False)
        self.organize_btn.clicked.connect(self.start_organization)
        action_bar.addWidget(self.organize_btn, 1)
        self.rollback_btn = QPushButton("Deshacer")
        self.rollback_btn.setEnabled(bool(self.controller.last_transaction_id))
        self.rollback_btn.clicked.connect(self.rollback_last_operation)
        action_bar.addWidget(self.rollback_btn)
        ol.addLayout(action_bar)

        # Progreso (solo visible durante operaciones)
        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_label = QLabel("")
        progress_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(14)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addStretch()
        ol.addLayout(progress_layout)

        # Resumen del análisis (consumido por update_statistics)
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel("Sin análisis")
        self.stats_label.setObjectName("stats_label")
        stats_layout.addWidget(self.stats_label, 1)
        self.category_stats_label = QLabel()
        self.category_stats_label.setObjectName("category_stats_label")
        self.category_stats_label.setVisible(False)
        stats_layout.addWidget(self.category_stats_label)
        self.available_categories_label = QLabel()
        self.available_categories_label.setObjectName("available_categories_label")
        self.available_categories_label.setVisible(False)
        stats_layout.addWidget(self.available_categories_label)
        ol.addLayout(stats_layout)

        self.browse_btn.setToolTip("Selecciona la carpeta que quieres analizar (Ctrl+O)")
        self.analyze_btn.setToolTip("Analiza el contenido de la carpeta (Ctrl+R o F5)")
        self.organize_btn.setToolTip("Revisa y organiza los elementos seleccionados (Ctrl+S)")
        self.select_all_btn.setToolTip("Marca todos los elementos (Ctrl+A)")
        self.deselect_all_btn.setToolTip("Desmarca todos los elementos (Ctrl+D)")
        self.config_btn.setToolTip("Abre la configuración de categorías y extensiones (Ctrl+P)")
        return organ

    def _build_log_tab(self) -> QWidget:
        """Pestaña de registro de la ventana autónoma (en Fluent, Actividad)."""
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("Registro de operaciones"))
        log_header.addStretch()
        for text, slot in (("Limpiar", self.clear_log), ("Exportar TXT", self.export_log),
                           ("Ir al final", self.scroll_log_to_bottom)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            log_header.addWidget(button)
        log_layout.addLayout(log_header)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("log_text")
        for line in self.controller.log_history():
            self.log_text.append(line)
        log_layout.addWidget(self.log_text)
        self.log_info_label = QLabel("")
        log_layout.addWidget(self.log_info_label)
        self.update_log_info()
        return log_tab

    def _apply_movement_column_widths(self):
        for column, width in MOVEMENT_COLUMN_WIDTHS.items():
            self.movements_table.setColumnWidth(column, width)

    def on_advanced_mode_toggled(self, checked: bool):
        """Muestra u oculta las opciones avanzadas y persiste el estado."""
        self.advanced_controls.setVisible(checked)
        self.advanced_mode_toggle.setText("Ocultar opciones avanzadas" if checked else "Opciones avanzadas")
        if checked != self.app_config.get_ui_advanced_mode():
            self.app_config.set_ui_advanced_mode(checked)

    def update_favorite_button_state(self):
        """Actualiza el texto del botón de favorito."""
        path = self.folder_input.text().strip()
        is_favorite = path in self.app_config.get_favorite_paths()
        self.add_favorite_btn.setText("Quitar favorito" if is_favorite else "Guardar favorito")
        self.add_favorite_btn.setToolTip(
            "Quitar ruta actual de favoritos" if is_favorite else "Guardar ruta actual en favoritos")

    def setup_shortcuts(self):
        """Atajos de la ventana autónoma (en Fluent los registra el shell)."""
        for sequence, slot in (
            ("Ctrl+O", self.browse_folder), ("F5", self.start_analysis), ("Ctrl+R", self.start_analysis),
            ("Ctrl+S", self.start_organization), ("Ctrl+A", self.select_all_items),
            ("Ctrl+D", self.deselect_all_items), ("Ctrl+L", self.clear_log),
            ("Ctrl+P", self.open_configuration), ("Ctrl+,", self.open_configuration), ("Ctrl+Q", self.close),
        ):
            QShortcut(QKeySequence(sequence), self, slot)
        for index in range(5):
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self,
                      lambda target=index: self.main_tabs.setCurrentIndex(target))

    # ---------------------------------------------------------- análisis
    def browse_folder(self):
        """Abre el diálogo para seleccionar una carpeta"""
        folder_path = QFileDialog.getExistingDirectory(self._dialog_parent(), "Seleccionar carpeta para organizar")
        if folder_path:
            self.folder_input.setText(folder_path)
            self.app_config.push_recent_path(folder_path)
            self.refresh_saved_paths()

    def analyze_folder(self, folder_path: str):
        """Fija la carpeta y la analiza (Inicio, arrastrar y soltar, Uso del espacio)."""
        self.folder_input.setText(folder_path)
        self.start_analysis()

    def on_folder_path_changed(self, text):
        """Maneja el cambio en el campo de ruta de carpeta"""
        self.update_selection_count()
        if text.strip() and os.path.exists(text.strip()) and self.app_config.get_auto_analyze():
            # Pequeño retraso para no analizar mientras se escribe
            if not hasattr(self, "_auto_analysis_timer"):
                self._auto_analysis_timer = QTimer(self)
                self._auto_analysis_timer.setSingleShot(True)
                self._auto_analysis_timer.timeout.connect(self.start_analysis)
            self._auto_analysis_timer.start(1000)

    def start_analysis(self):
        """Valida la carpeta y lanza el análisis en el controlador."""
        if hasattr(self, "_auto_analysis_timer"):
            self._auto_analysis_timer.stop()
        if self.controller.busy:
            return
        folder_path = self.folder_input.text().strip()
        parent = self._dialog_parent()
        if not folder_path:
            QMessageBox.warning(parent, "Elige una carpeta", "Selecciona una carpeta para analizar.")
            return
        if not os.path.exists(folder_path):
            QMessageBox.warning(parent, "Carpeta no encontrada", "La carpeta seleccionada no existe.")
            return
        if not os.path.isdir(folder_path):
            QMessageBox.warning(parent, "No es una carpeta", "El elemento seleccionado no es una carpeta.")
            return

        self._analysis_folder_path = os.path.normcase(os.path.realpath(folder_path))
        self._analysis_result_path = None
        self.folder_movements = []
        self.file_movements = []
        self.preview_btn.setEnabled(False)
        if self.similarity_spinbox.value() != self.app_config.get_min_similarity():
            self.app_config.set_min_similarity(self.similarity_spinbox.value())
        if self.min_size_spinbox.value() != self.app_config.get_min_file_size_mb():
            self.app_config.set_min_file_size_mb(self.min_size_spinbox.value())
        self.app_config.push_recent_path(folder_path)
        self.refresh_saved_paths()
        self.log_message(f"🔍 Iniciando análisis de: {folder_path}")
        try:
            started = self.controller.start_analysis(
                folder_path,
                self.category_manager.get_categories(),
                self.category_manager.ext_to_categoria,
                self.similarity_spinbox.value(),
                min_file_size_mb=self.min_size_spinbox.value(),
                ignored_extensions=self.app_config.get_ignored_extensions(),
                ignored_paths=list(self.app_config.get_ignored_paths()) + list(self._profile_exclusions),
                category_manager=self.category_manager,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            message = f"❌ Error al iniciar el análisis: {exc}"
            self.log_message(message)
            QMessageBox.critical(parent, "Error de análisis", message)
            started = None
        if not started:
            self.progress_bar.setVisible(False)
        self._sync_action_buttons()

    def on_analysis_complete(self, folder_movements, file_movements, stats):
        """Muestra los resultados del análisis."""
        self.folder_movements = folder_movements
        self.file_movements = file_movements
        self._analysis_result_path = self._analysis_folder_path
        self.populate_results_table()
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.update_selection_count()
        total_items = len(folder_movements) + len(file_movements)
        self.log_message(f"✅ Análisis completado: {total_items} elementos encontrados")
        self.filter_bar.update_categories(
            sorted({mov["category"] for mov in folder_movements + file_movements}))
        self.filter_bar.update_count(self.movements_model.get_visible_count())
        if stats:
            self.log_message(
                f"📊 Estadísticas: {stats.get('total_folders', 0)} carpetas, {stats.get('total_files', 0)} archivos")
            self.update_statistics()
            self.update_selected_statistics()

    def on_analysis_cancelled(self):
        """El usuario canceló el análisis: se restaura la interfaz sin resultados."""
        self.analyze_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.update_selection_count()

    def on_analysis_error(self, error_message):
        """Maneja errores durante el análisis"""
        self.analyze_btn.setEnabled(True)
        self.organize_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        QMessageBox.critical(self._dialog_parent(), "Error de análisis", error_message)

    def populate_results_table(self):
        """Llena la tabla virtualizada con los resultados del análisis"""
        self.movements_model.clear_data()
        model_data = []
        for mov in self.folder_movements:
            model_data.append({
                "type": "folder",
                "element": f"📁 {mov['folder'].name}",
                "category": mov["category"],
                "percentage": mov.get("percentage", 0),
                "file_count": mov.get("total_files", 0),
                "size_bytes": mov.get("size", 0),
                "size_formatted": self.format_size(mov.get("size", 0)),
                "tooltip": f"Carpeta: {mov['folder'].name}\nArchivos: {mov.get('total_files', 0)}",
                "is_group": False,
                "is_expanded": False,
                "original_data": mov,
            })
        files_by_category = defaultdict(list)
        size_by_category = defaultdict(int)
        for mov in self.file_movements:
            files_by_category[mov["category"]].append(mov)
            size_by_category[mov["category"]] += mov.get("size", 0)
        for category, file_movs in files_by_category.items():
            total_size = size_by_category[category]
            model_data.append({
                "type": "file_group",
                "element": f"📄 {len(file_movs)} archivos sueltos",
                "category": category,
                "percentage": 0,
                "file_count": len(file_movs),
                "size_bytes": total_size,
                "size_formatted": self.format_size(total_size),
                "tooltip": f"Grupo de {len(file_movs)} archivos sueltos\nCategoría: {category}",
                "is_group": True,
                "is_expanded": False,
                "group_files": file_movs,
            })
        self.movements_model.update_data(model_data)
        # resetModel() puede cambiar los anchos: se vuelven a aplicar
        self._apply_movement_column_widths()
        self.log_message(f"Tabla de resultados con {len(model_data)} elementos")
        self.update_selection_count()
        self.update_statistics()

    def select_all_items(self):
        self.movements_model.check_all()
        self.update_selection_count()

    def deselect_all_items(self):
        self.movements_model.uncheck_all()
        self.update_selection_count()

    def on_model_data_changed(self, top_left, bottom_right, roles):
        if Qt.ItemDataRole.CheckStateRole in roles:
            self.update_selection_count()

    def on_table_double_clicked(self, index):
        """Doble clic: expande o contrae un grupo de archivos sueltos."""
        if not index.isValid():
            return
        row_data = self.movements_model.get_row_data(index.row())
        if row_data and row_data.get("is_group", False):
            self.toggle_file_group_expansion(index.row())

    def toggle_file_group_expansion(self, group_row):
        model = self.movements_model
        if group_row >= model.rowCount() or not model.is_group_row(group_row):
            return
        if model.get_row_data(group_row).get("is_expanded", False):
            model.collapse_group(group_row)
        else:
            model.expand_group(group_row)

    def _sync_action_buttons(self):
        """Habilita Analizar, Organizar y Deshacer según el estado del controlador."""
        if not hasattr(self, "organize_btn"):
            return
        controller = self.controller
        self.analyze_btn.setEnabled(not controller.busy)
        self.rollback_btn.setEnabled(bool(controller.last_transaction_id)
                                     and not controller.current_organize_task_id
                                     and not controller.current_rollback_task_id)
        self.organize_btn.setText("Organizando…" if controller.current_organize_task_id else "Revisar y organizar")
        self.update_selection_count()

    def update_selection_count(self):
        """Actualiza el resumen de selección y el botón Organizar."""
        if not hasattr(self, "movements_model"):
            return
        selected_rows = self.movements_model.get_checked_rows()
        total_count = sum(
            1 for row in range(self.movements_model.rowCount())
            if not (self.movements_model.get_row_data(row) or {}).get("is_child", False)
        )
        selected_count = len(selected_rows)
        path = self.folder_input.text().strip()
        matches_analysis = (bool(path) and os.path.isdir(path)
                            and os.path.normcase(os.path.realpath(path)) == self._analysis_result_path)
        enabled = selected_count > 0 and matches_analysis and not self.controller.busy
        self.organize_btn.setEnabled(enabled)
        self.preview_btn.setEnabled(enabled)
        self.update_selected_statistics()
        self.filter_bar.update_selection_summary(
            selected_count, total_count, self.total_size_label.text(), self.total_files_label.text())
        self.filter_bar.update_count(self.movements_model.get_visible_count())
        self._update_results_empty_state(total_count)

    def _update_results_empty_state(self, total_count: int):
        """Tabla o estado vacío: nunca una tabla vacía sin explicación."""
        # Con filtro activo la tabla puede quedar vacía: eso no es "sin resultados"
        has_rows = total_count > 0 or bool(self.folder_movements or self.file_movements)
        self.movements_table.setVisible(has_rows)
        self.filter_bar.setVisible(has_rows)
        self.results_empty_state.setVisible(not has_rows)
        self.stats_label.setVisible(has_rows)
        if has_rows:
            return
        if self.controller.current_analysis_task_id:
            self.results_empty_state.set_text("Analizando la carpeta…")
            self.results_empty_state.set_action("")
        elif self._analysis_result_path:
            self.results_empty_state.set_text("No hay nada que organizar en esta carpeta.")
            self.results_empty_state.set_action("Elegir otra carpeta")
        else:
            self.results_empty_state.set_text("Elige una carpeta y pulsa Analizar para ver qué se puede organizar.")
            self.results_empty_state.set_action("Elegir carpeta")

    def update_selected_statistics(self):
        """Tamaño y número de archivos de los elementos seleccionados."""
        selected_size = 0
        selected_files = 0
        for row in self.movements_model.get_checked_rows():
            row_data = self.movements_model.get_row_data(row)
            if row_data:
                selected_size += row_data.get("size_bytes", 0)
                if row_data.get("type") == "file_group":
                    selected_files += row_data.get("file_count", len(row_data.get("group_files", [])))
                else:
                    selected_files += row_data.get("file_count", 1)
        self.total_size_label.setText(self.format_size(selected_size))
        self.total_files_label.setText(f"{selected_files:,} archivos")

    def update_statistics(self):
        """Resumen por categoría del último análisis."""
        category_stats = defaultdict(lambda: {"count": 0, "size": 0})
        for mov in self.folder_movements + self.file_movements:
            category_stats[mov["category"]]["count"] += 1
            category_stats[mov["category"]]["size"] += mov.get("size", 0)
        total = len(self.folder_movements) + len(self.file_movements)
        parts = [f"{category} ({stats['count'] / total * 100:.0f} %)"
                 for category, stats in sorted(category_stats.items(), key=lambda item: -item[1]["count"])
                 if total and stats["count"]]
        self.stats_label.setText(" · ".join(parts) if parts else "Sin análisis")
        self.update_detailed_statistics(category_stats)

    def update_detailed_statistics(self, category_stats):
        """Detalle por categoría (etiquetas ocultas, usadas como resumen accesible)."""
        lines = [f"<b>{category}:</b> {stats['count']:,} elementos ({self.format_size(stats['size'])})"
                 for category, stats in sorted(category_stats.items(), key=lambda item: -item[1]["count"])
                 if stats["count"]]
        self.category_stats_label.setText("<br/>".join(lines) if lines else "Sin datos")
        categories = self.category_manager.get_categories()
        self.available_categories_label.setText(
            "<br/>".join(f"<b>{name}:</b> {len(extensions)} extensiones" for name, extensions in categories.items()))

    def get_selected_movements(self):
        """Obtiene carpetas y archivos seleccionados desde el modelo."""
        selected_folder_movements = []
        selected_file_movements = []
        for row in self.movements_model.get_checked_rows():
            row_data = self.movements_model.get_row_data(row)
            if not row_data:
                continue
            row_type = row_data.get("type", "")
            if row_type == "folder":
                original_data = row_data.get("original_data")
                if original_data:
                    selected_folder_movements.append(original_data)
            elif row_type == "file_group":
                selected_file_movements.extend(row_data.get("group_files", []))
        return selected_folder_movements, selected_file_movements

    def open_selection_preview(self):
        """Conserva el acceso existente al único flujo de revisión y confirmación."""
        self.start_organization()

    def _get_effective_selected_movements(self):
        folder_movements, file_movements = self.get_selected_movements()
        if not self.move_folders_checkbox.isChecked():
            folder_movements = []
            self.log_message("ℹ️ Modo: solo archivos sueltos (carpetas ignoradas)")
        else:
            self.log_message("ℹ️ Modo: carpetas completas y archivos sueltos")
        return folder_movements, file_movements

    # -------------------------------------------------------- organizar
    def start_organization(self):
        """Revisa la selección (vista previa) y lanza la organización."""
        if getattr(self, "_organization_review_open", False) or self.controller.busy:
            return
        folder_path = self.folder_input.text().strip()
        if (not os.path.isdir(folder_path)
                or os.path.normcase(os.path.realpath(folder_path)) != self._analysis_result_path):
            QMessageBox.warning(self._dialog_parent(), "Analiza la carpeta actual",
                                "La selección corresponde a otra carpeta o la ruta ya no está disponible. "
                                "Analiza la carpeta actual antes de revisar.")
            return
        selected_folder_movements, selected_file_movements = self._get_effective_selected_movements()
        if not selected_folder_movements and not selected_file_movements:
            QMessageBox.warning(self._dialog_parent(), "Nada seleccionado",
                                "No hay elementos seleccionados para organizar.")
            return

        # Una única traducción categoría → carpeta para vista previa y worker
        category_manager = getattr(self, "category_manager", None)
        category_folder = getattr(category_manager, "get_category_folder", None)
        folder_names_getter = getattr(category_manager, "get_category_folder_names", None)
        category_folder_names = folder_names_getter() if callable(folder_names_getter) else None

        preview = PreviewDialog(
            selected_folder_movements,
            selected_file_movements,
            folder_path,
            self._dialog_parent(),
            organize_by_date=self.organize_by_date_checkbox.isChecked(),
            check_duplicates=self.check_duplicates_checkbox.isChecked(),
            conflict_policy=self.app_config.get_organization_conflict_policy(),
            category_folder=category_folder,
            category_folder_names=category_folder_names,
        )
        self._organization_review_open = True
        try:
            accepted = preview.exec() == QDialog.DialogCode.Accepted
        finally:
            self._organization_review_open = False
        if not accepted:
            self.log_message("Organización cancelada en la vista previa")
            return

        # Rutas protegidas del usuario + exclusiones del perfil activo
        protected_paths = list(self.app_config.get_protected_paths()) + list(
            getattr(self, "_profile_exclusions", []))
        started = self.controller.start_organization(
            folder_path,
            selected_folder_movements,
            selected_file_movements,
            organize_by_date=self.organize_by_date_checkbox.isChecked(),
            check_duplicates=self.check_duplicates_checkbox.isChecked(),
            protected_paths=protected_paths,
            conflict_policy=preview.get_conflict_policy(),
            plan=preview.get_plan() if hasattr(preview, "get_plan") else None,
            category_folder=category_folder,
        )
        if started:
            self.organize_btn.setEnabled(False)
            self.organize_btn.setText("Organizando…")
            self.rollback_btn.setEnabled(False)

    def on_organize_complete(self, success, message):
        """Fin de la organización: resumen y refresco de resultados.

        ``success`` solo es True si todo se completó; el estado real
        (cancelado, completado con errores, error) viene en el resumen.
        """
        self.organize_btn.setText("Revisar y organizar")
        self.progress_bar.setVisible(False)
        summary = self.controller.last_operation_summary or {}
        status = summary.get("status", "completado" if success else "error")
        transaction_id = summary.get("transaction_id")
        moved = summary.get("files_moved", 0) + summary.get("folders_moved", 0)
        if status in ("completado", "completado con errores", "cancelado"):
            self.log_message(("✅ " if success else "⚠️ ") + message)
            if summary:
                undo = None
                if status != "completado" and transaction_id and moved:
                    # Ofrecer deshacer lo que sí se movió (cancelación o errores)
                    undo = lambda txn=transaction_id: self.rollback_transaction(txn, confirm=False)
                OperationSummaryDialog(summary, self._dialog_parent(), undo_callback=undo).exec()
            if self.controller.current_rollback_task_id is None:
                self._schedule_post_organization_refresh()
        else:
            self.log_message("❌ " + message)
            QMessageBox.critical(self._dialog_parent(), "Error de organización", message)
        self._sync_action_buttons()

    def _dialog_parent(self):
        """En Fluent, los diálogos se centran sobre la ventana visible."""
        widget = getattr(self, "organize_widget", None)
        window = widget.window() if widget is not None else None
        return window if window is not None and window.isVisible() else self

    def _schedule_post_organization_refresh(self):
        """Relanza el análisis para reflejar el estado real tras organizar."""
        folder_path = self.folder_input.text().strip() if hasattr(self, "folder_input") else ""
        if not folder_path or not os.path.isdir(folder_path):
            self.log_message("⚠️ No se pudo refrescar automáticamente: la ruta actual ya no es válida")
            return
        self.log_message("🔄 Refrescando resultados tras la organización...")
        QTimer.singleShot(150, self.start_analysis)

    # ---------------------------------------------------------- deshacer
    def rollback_last_operation(self):
        """Revierte la última organización que aún se puede deshacer."""
        if self.controller.current_organize_task_id or self.controller.current_rollback_task_id:
            return
        transaction_id = self.controller.refresh_last_transaction()
        if not transaction_id:
            QMessageBox.information(self._dialog_parent(), "Sin historial",
                                    "No hay una transacción reciente para deshacer.")
            return
        self.rollback_transaction(transaction_id)

    def rollback_transaction(self, transaction_id: str, confirm: bool = True) -> bool:
        """Pide confirmación y deshace una transacción en segundo plano.

        Returns:
            True si se inició el proceso de deshacer.
        """
        if not transaction_id or self.controller.current_organize_task_id or self.controller.current_rollback_task_id:
            return False
        if confirm:
            is_last = transaction_id == self.controller.last_transaction_id
            reply = QMessageBox.question(
                self._dialog_parent(),
                "Deshacer última organización" if is_last else "Deshacer organización",
                "¿Quieres revertir la última organización completada?"
                if is_last else "¿Quieres revertir esta organización del historial?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return False
        if not self.controller.start_rollback(transaction_id):
            return False
        self.rollback_btn.setEnabled(False)
        self.organize_btn.setEnabled(False)
        return True

    def on_rollback_finished(self, transaction_id: str, ok: bool, result: dict):
        """Muestra el resultado de deshacer y refresca los resultados."""
        parent = self._dialog_parent()
        if result.get("already_reverted"):
            QMessageBox.information(parent, "Ya deshecha",
                                    "Esta organización ya se había deshecho; no se ha repetido.")
        elif ok:
            extra = ""
            if result.get("renamed"):
                extra = (f"\n\n{len(result['renamed'])} elementos se restauraron con otro nombre "
                         "porque su ubicación original estaba ocupada.")
            QMessageBox.information(parent, "Organización deshecha",
                                    "Los cambios de la organización se han revertido." + extra)
            self._schedule_post_organization_refresh()
        else:
            QMessageBox.warning(parent, "Deshacer incompleto",
                                "No se pudieron revertir todos los cambios. Revisa el registro en Actividad.")
            self._schedule_post_organization_refresh()
        self._sync_action_buttons()

    # ----------------------------------------------------------- perfiles
    def refresh_profiles(self):
        """Recarga la lista de perfiles en la interfaz."""
        current = self.profile_combo.currentText()
        self.profile_combo.clear()
        self.profile_combo.addItems(self.profile_manager.get_profile_names())
        index = self.profile_combo.findText(current)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)

    def load_selected_profile(self):
        """Aplica el perfil seleccionado a la UI."""
        profile_name = self.profile_combo.currentText().strip()
        profile = self.profile_manager.get_profile(profile_name)
        if not profile:
            return
        # Un perfil sin carpeta no borra la ruta que ya escribió el usuario
        if (profile.folder_path or "").strip():
            self.folder_input.setText(profile.folder_path)
        self.move_folders_checkbox.setChecked(profile.move_folders)
        self.similarity_spinbox.setValue(profile.similarity_threshold)
        self.organize_by_date_checkbox.setChecked(profile.organize_by_date)
        # Las exclusiones del perfil se suman a las rutas protegidas del
        # usuario solo mientras el perfil está activo; nunca las sustituyen.
        self._profile_exclusions = [
            str(path) for path in (profile.exclude_patterns or []) if str(path).strip()
        ]
        self.log_message(f"🧩 Perfil cargado: {profile.name}")

    def save_current_profile(self):
        """Guarda el estado actual en un perfil."""
        current_name = self.profile_combo.currentText().strip()
        profile_name, ok = QInputDialog.getText(
            self._dialog_parent(), "Guardar perfil", "Nombre del perfil:", text=current_name or "Nuevo perfil")
        if not ok or not profile_name.strip():
            return
        normalized_name = profile_name.strip()
        profile = self.profile_manager.get_profile(normalized_name)
        if profile is None:
            profile = self.profile_manager.create_profile(normalized_name)
        if profile is None:
            QMessageBox.warning(self._dialog_parent(), "Error", "No se pudo crear el perfil.")
            return
        profile.folder_path = self.folder_input.text().strip()
        profile.move_folders = self.move_folders_checkbox.isChecked()
        profile.similarity_threshold = self.similarity_spinbox.value()
        profile.organize_by_date = self.organize_by_date_checkbox.isChecked()
        profile.exclude_patterns = list(getattr(self, "_profile_exclusions", []))
        profile.selected_categories = sorted({
            row_data.get("category")
            for row in self.movements_model.get_checked_rows()
            if (row_data := self.movements_model.get_row_data(row))
        })
        self.profile_manager.update_profile(profile)
        self.profile_manager.set_active_profile(profile.name)
        self.refresh_profiles()
        self.profile_combo.setCurrentText(profile.name)
        self.log_message(f"💾 Perfil guardado: {profile.name}")

    # ------------------------------------------------------ configuración
    def open_configuration(self, focus_section: str | None = None):
        """Abre la configuración de categorías, exclusiones y audio."""
        dialog = ConfigDialog(self, self.category_manager, app_config_ref=self.app_config,
                              focus_section=focus_section)
        dialog.interface_changes_requested.connect(self.apply_interface_changes)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.category_manager = dialog.category_manager
            self._apply_audio_tab_visibility()
            QMessageBox.information(
                self._dialog_parent(),
                "Configuración actualizada",
                "Los cambios de categorías se aplicarán en el próximo análisis.",
            )

    def _apply_audio_tab_visibility(self):
        audio_enabled = bool(self.app_config.get_audio_enabled())
        if self.music_duplicates_view is not None:
            self.music_duplicates_view.setEnabled(audio_enabled)
        if self.main_tabs is not None:
            self.main_tabs.setTabVisible(self._music_tab_index, audio_enabled)
            if not audio_enabled and self.main_tabs.currentIndex() == self._music_tab_index:
                self.main_tabs.setCurrentIndex(0)

    def apply_saved_interface_settings(self):
        """Restaura las opciones guardadas; en Fluent el tema lo aplica el shell."""
        self.similarity_spinbox.setValue(self.app_config.get_min_similarity())
        self.min_size_spinbox.setValue(self.app_config.get_min_file_size_mb())
        advanced_mode = self.app_config.get_ui_advanced_mode()
        self.advanced_mode_toggle.blockSignals(True)
        self.advanced_mode_toggle.setChecked(advanced_mode)
        self.advanced_mode_toggle.blockSignals(False)
        self.on_advanced_mode_toggled(advanced_mode)
        self.update_favorite_button_state()
        if not self.fluent_mode:
            # Ventana autónoma: el mismo tema de tokens que la V2.
            apply_fluent_theme(self.app_config)
            apply_legacy_surface_style(self.centralWidget(), self.app_config)

    def apply_interface_changes(self, font_size: int, theme: str):
        """Cambios de fuente desde el diálogo de configuración (ventana autónoma)."""
        if font_size != self.app_config.get_font_size():
            self.app_config.set_font_size(font_size)
        apply_fluent_theme(self.app_config)
        if self.centralWidget() is not None:
            apply_legacy_surface_style(self.centralWidget(), self.app_config)

    def refresh_saved_paths(self):
        """Actualiza el selector de favoritas y recientes."""
        current = self.path_memory_combo.currentData()
        self.path_memory_combo.blockSignals(True)
        self.path_memory_combo.clear()
        for path in self.app_config.get_favorite_paths():
            self.path_memory_combo.addItem(f"★ {path}", userData=path)
        for path in self.app_config.get_recent_paths():
            if self.path_memory_combo.findData(path) == -1:
                self.path_memory_combo.addItem(path, userData=path)
        index = self.path_memory_combo.findData(current) if current else -1
        # Sin elegir nada por defecto: elegir una ruta la carga en el campo
        self.path_memory_combo.setCurrentIndex(index)
        self.path_memory_combo.setToolTip(current or "Rutas favoritas (★) y recientes")
        self.path_memory_combo.setEnabled(self.path_memory_combo.count() > 0)
        self.path_memory_combo.blockSignals(False)
        self.update_favorite_button_state()

    def use_selected_saved_path(self):
        """Carga una ruta guardada en el campo principal."""
        path = self.path_memory_combo.currentData()
        if path:
            self.path_memory_combo.setToolTip(path)
            self.folder_input.setText(path)

    def add_current_path_to_favorites(self):
        """Añade o quita la ruta actual de favoritos."""
        path = self.folder_input.text().strip()
        if not path:
            return
        if path in self.app_config.get_favorite_paths():
            self.app_config.remove_favorite_path(path)
            self.log_message(f"Ruta eliminada de favoritas: {path}")
        else:
            self.app_config.add_favorite_path(path)
            self.log_message(f"Ruta añadida a favoritas: {path}")
        self.refresh_saved_paths()

    def open_exclusions_configuration(self):
        """Abre la configuración enfocada en la sección de exclusiones."""
        self.open_configuration("exclusions")

    def open_task_center(self):
        TaskCenterDialog(self._dialog_parent()).exec()

    # ------------------------------------------------------------ registro
    def log_message(self, message):
        """Añade un mensaje al registro (en lotes, vía el controlador)."""
        self.controller.log(message)

    def _flush_log(self):
        self.controller.flush_log()

    def _handle_task_progress(self, task_id: str, message: str):
        self.controller.handle_task_progress(task_id, message)

    def _append_log_lines(self, lines):
        if self.log_text is None:
            return
        self.log_text.setUpdatesEnabled(False)
        try:
            for line in lines:
                self.log_text.append(line)
        finally:
            self.log_text.setUpdatesEnabled(True)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.update_log_info()

    def _on_log_cleared(self):
        if self.log_text is not None:
            self.log_text.clear()
            self.update_log_info()

    def clear_log(self):
        """Limpia el registro tras confirmarlo."""
        reply = QMessageBox.question(
            self._dialog_parent(), "Limpiar registro",
            "¿Quieres limpiar todo el registro? Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.controller.clear_log()

    def export_log(self):
        """Exporta el registro a un archivo de texto."""
        from datetime import datetime

        parent = self._dialog_parent()
        filepath, _ = QFileDialog.getSaveFileName(
            parent, "Exportar registro", f"registro_ordenasion_{datetime.now():%Y%m%d_%H%M%S}.txt",
            "Archivos de texto (*.txt);;Todos los archivos (*)")
        if not filepath:
            return
        try:
            count = self.controller.export_log(filepath)
        except OSError as exc:
            QMessageBox.critical(parent, "No se pudo exportar", f"No se pudo exportar el registro:\n{exc}")
            return
        QMessageBox.information(parent, "Registro exportado", f"{count} entradas exportadas a:\n{filepath}")

    def scroll_log_to_bottom(self):
        if self.log_text is not None:
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def update_log_info(self):
        if self.log_info_label is not None:
            self.log_info_label.setText(f"Total de entradas: {self.get_log_entry_count()}")

    def get_log_entry_count(self):
        return self.controller.log_entry_count

    # ------------------------------------------------------------ discos
    def on_disk_selected_for_organize(self, disk_path):
        """Analiza la unidad elegida en Discos."""
        if self.main_tabs is not None:
            self.main_tabs.setCurrentIndex(0)
        self.folder_input.setText(disk_path)
        self.log_message(f"💾 Unidad seleccionada para organizar: {disk_path}")
        QTimer.singleShot(2000, self.start_analysis)

    def format_size(self, size_bytes):
        """Formatea el tamaño en bytes a una representación legible"""
        return format_bytes(size_bytes)

    def show_context_menu(self, position):
        """Menú contextual de la tabla de movimientos."""
        index = self.movements_table.indexAt(position)
        if not index.isValid():
            return
        row = index.row()
        model = self.movements_model
        row_data = model.get_row_data(row) or {}
        menu = QMenu(self.movements_table)
        apply_menu_surface(menu, self.app_config)
        source = (row_data.get("original_data") or {}).get("folder") if row_data.get("type") == "folder" else None
        location = str(source) if source else self.folder_input.text().strip()
        if location:
            open_action = QAction("Abrir en el Explorador", menu)
            open_action.triggered.connect(lambda: self.open_file_location(location))
            menu.addAction(open_action)
        if row_data.get("is_group", False):
            if row_data.get("is_expanded", False):
                action = QAction("Contraer grupo", menu)
                action.triggered.connect(lambda: model.collapse_group(row))
            else:
                action = QAction("Expandir grupo", menu)
                action.triggered.connect(lambda: model.expand_group(row))
            menu.addAction(action)
        if menu.actions():
            menu.exec(self.movements_table.viewport().mapToGlobal(position))

    def open_file_location(self, folder_path):
        """Abre la ubicación en el explorador del sistema."""
        from src.utils.paths import open_in_file_manager

        if not open_in_file_manager(folder_path):
            QMessageBox.warning(self._dialog_parent(), "No se pudo abrir",
                                f"No se pudo abrir la ubicación:\n{folder_path}")

    def on_header_clicked(self, logical_index):
        """Ordena por porcentaje (3) o tamaño (5)."""
        if logical_index not in (3, 5):
            return
        sort_info = (self.movements_model.get_sort_info() if hasattr(self.movements_model, "get_sort_info")
                     else {"column": -1, "order": Qt.SortOrder.AscendingOrder})
        if sort_info["column"] == logical_index and sort_info["order"] == Qt.SortOrder.AscendingOrder:
            new_order = Qt.SortOrder.DescendingOrder
        else:
            new_order = Qt.SortOrder.AscendingOrder
        if hasattr(self.movements_model, "sort"):
            self.movements_model.sort(logical_index, new_order)
        self.movements_table.horizontalHeader().setSortIndicator(logical_index, new_order)

    def _on_filter_changed(self, search_text: str, category: str):
        """Filtra la tabla por texto y categoría."""
        self.movements_model.set_filter(search_text, category)
        self.filter_bar.update_count(self.movements_model.get_visible_count())

    # -------------------------------------------------------------- cierre
    def has_running_organization(self) -> bool:
        return self.controller.has_running_organization()

    def request_shutdown(self, confirm: bool = True) -> bool:
        """Prepara el cierre: pide confirmación, detiene y espera a los workers.

        Devuelve False si el usuario decide no cerrar. La ventana V2 lo llama
        desde su closeEvent antes de cerrar.
        """
        def ask() -> bool:
            reply = QMessageBox.question(
                self._dialog_parent(),
                "Organización en curso",
                "Hay una organización (o un deshacer) en curso.\n\n"
                "¿Detenerla de forma segura y salir? Lo que ya se haya movido "
                "quedará registrado en el historial y se podrá deshacer.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            return reply == QMessageBox.StandardButton.Yes

        return self.controller.request_shutdown(ask if confirm else None)

    def _shutdown_workers(self):
        self.controller.shutdown_workers()

    def closeEvent(self, event):
        """Cierre ordenado: nunca se destruye un hilo en marcha."""
        if not self.request_shutdown():
            event.ignore()
            return
        if self.disk_viewer is not None:
            self.disk_viewer.shutdown()
        cleanup = getattr(self._app_state, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except (RuntimeError, OSError) as exc:
                self.log_message(f"⚠️ Error durante la limpieza del estado: {exc}")
        self.controller.flush_log()
        event.accept()
