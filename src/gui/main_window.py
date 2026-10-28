#!/usr/bin/env python3
"""
Ventana Principal del Organizador de Archivos
Maneja la interfaz principal y la lógica de la aplicación
"""

import os
import sys
import time
import html
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict

from PyQt6.QtWidgets import (
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QWidget,
    QPushButton,
    QLabel,
    QLineEdit,
    QFileDialog,
    QInputDialog,
    QTextEdit,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QProgressBar,
    QGroupBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QSplitter,
    QFrame,
    QDialog,
    QTableView,
    QMenu,
    QSizePolicy,
    QGraphicsOpacityEffect,
)
from PyQt6.QtCore import (
    Qt,
    QThread,
    pyqtSignal,
    QTimer,
    QEasingCurve,
    QPropertyAnimation,
)
from PyQt6.QtGui import QFont, QIcon, QPalette, QColor, QShortcut, QKeySequence, QAction

from src.utils.constants import COLORS, DIALOG_STYLES, UI_CONFIG
from src.utils.themes import ThemeManager
from src.utils.fast_theme_applier import FastThemeApplier
from src.utils.theme_cache import ThemeCache
from src.utils.app_config import AppConfig
from src.utils.version import APP_VERSION
from src.core.category_manager import CategoryManager
from src.core.disk_manager import DiskManager
from src.core.organization_profiles import ProfileManager
from src.core.transaction_manager import TransactionManager
from src.core.workers import AnalysisWorker, OrganizeWorker
from src.core.application_state import app_state, EventType
from src.gui.disk_viewer import DiskViewer
from src.gui.config_dialog import ConfigDialog
from src.gui.duplicates_dashboard import DuplicatesDashboard, CheckboxDelegate
from src.gui.music_duplicates_view import MusicDuplicatesView
from src.gui.table_models import VirtualizedMovementsModel
from src.gui.preview_dialog import PreviewDialog
from src.gui.filter_bar import FilterBar
from src.gui.task_center import TaskCenterDialog, task_registry
from src.gui.operation_summary_dialog import OperationSummaryDialog
from src.gui.v2.theme import apply_control_sizes, bind_path_tooltip, current_tokens, typography_scale, apply_menu_surface


class FileOrganizerGUI(QMainWindow):
    """Ventana principal del organizador de archivos.

    Usa inyección de dependencias opcional para facilitar testing.
    Si no se proporcionan dependencias, se obtienen de app_state.
    """

    operation_state_changed = pyqtSignal()

    def __init__(self, app_state_ref=None, category_manager=None, app_config_ref=None):
        """
        Args:
            app_state_ref: Referencia a ApplicationState (inyeccion opcional)
            category_manager: CategoryManager (inyeccion opcional)
            app_config_ref: AppConfig (inyeccion opcional)
        """
        super().__init__()

        # === DEPENDENCIAS (inyectables para testing) ===
        self._app_state = app_state_ref or app_state
        self.category_manager = category_manager or self._app_state.category_manager
        if self.category_manager is None:
            from src.core.category_manager import CategoryManager

            self.category_manager = CategoryManager()

        self.app_config = app_config_ref or self._app_state.app_config
        if self.app_config is None:
            from src.utils.app_config import AppConfig

            self.app_config = AppConfig()

        self.disk_manager = None  # Se obtendra de app_state cuando se necesite

        # === DATOS LOCALES ===
        self.folder_movements = []
        self.file_movements = []
        self.duplicates_dashboard = None
        self.profile_manager = ProfileManager()
        self.transaction_manager = TransactionManager()
        self.last_transaction_id = None
        self.last_operation_summary = None
        self.current_analysis_task_id = None
        self._analysis_folder_path = None
        self._analysis_result_path = None
        self.current_organize_task_id = None
        self._active_workers = []  # Lista de workers activos para limpieza
        self._tab_fade_anim = None
        # Lazy loading flags para pestanas
        self._disk_viewer_initialized = False
        self._duplicates_initialized = False

        # === INICIALIZACION ===
        self.init_ui()
        self._init_disk_manager()
        self.setup_connections()
        self.setup_shortcuts()
        self.setup_state_observers()
        self.apply_saved_interface_settings()
        active_profile = self.profile_manager.get_active_profile()
        if active_profile and hasattr(self, "profile_combo"):
            self.profile_combo.setCurrentText(active_profile.name)
        self.refresh_saved_paths()

    def _init_disk_manager(self):
        """Inicializa DiskManager usando el estado centralizado"""
        try:
            # Verificar que app_state esté disponible
            if not hasattr(app_state, "get_disk_manager"):
                self.log_message(
                    "⚠️ app_state no tiene get_disk_manager, inicialización pospuesta"
                )
                self.disk_manager = None
                return

            # Obtener DiskManager del estado centralizado
            try:
                self.disk_manager = app_state.get_disk_manager()
            except Exception as e:
                self.log_message(f"⚠️ Error llamando a get_disk_manager: {e}")
                self.disk_manager = None
                return

            if self.disk_manager:
                # Actualizar DiskViewer con la instancia de DiskManager
                if hasattr(self, "disk_viewer") and self.disk_viewer:
                    self.disk_viewer.disk_manager = self.disk_manager
                    # Hacer el primer refresh después de asignar disk_manager
                    try:
                        self.disk_viewer.refresh_disks()
                        self.log_message("✅ DiskViewer actualizado con DiskManager")
                    except Exception as e:
                        self.log_message(f"⚠️ Error refrescando discos: {e}")
            else:
                self.log_message("⚠️ No se pudo inicializar DiskManager")

        except Exception as e:
            self.log_message(f"❌ Error al inicializar DiskManager: {e}")
            import traceback

            self.log_message(traceback.format_exc())
            self.disk_manager = None

    def init_ui(self):
        """Interfaz profesional reestructurada - Tabs con Log dedicado"""
        self.setWindowTitle(UI_CONFIG["WINDOW_TITLE"])
        self.setGeometry(100, 100, 1280, 760)
        self.setMinimumSize(900, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main = QVBoxLayout(central_widget)
        main.setSpacing(0)
        main.setContentsMargins(0, 0, 0, 0)

        # ===== PESTANAS PRINCIPALES =====
        self.main_tabs = QTabWidget()
        self.main_tabs.setObjectName("main_tabs")
        self.main_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.main_tabs.setDocumentMode(True)
        self.main_tabs.currentChanged.connect(self._animate_tab_transition)
        main.addWidget(self.main_tabs)

        # ===== PESTANA 1: ORGANIZAR =====
        organ = QWidget()
        ol = QVBoxLayout(organ)
        ol.setContentsMargins(12, 12, 12, 12)
        ol.setSpacing(8)

        # Header
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
        ol.addLayout(hdr)

        # GroupBox: Carpeta de Origen + Opciones
        source_group = QGroupBox("Carpeta de origen")
        source_layout = QVBoxLayout(source_group)
        source_layout.setContentsMargins(12, 16, 12, 12)
        source_layout.setSpacing(8)

        source_header = QHBoxLayout()
        source_header.setSpacing(8)
        source_summary = QLabel(
            "Modo básico para organizar rápido. Activa el modo avanzado para perfiles, duplicados y exclusiones"
        )
        source_summary.setWordWrap(True)
        source_header.addWidget(source_summary, 1)
        self.advanced_mode_toggle = QPushButton("Opciones avanzadas")
        self.advanced_mode_toggle.setCheckable(True)
        self.advanced_mode_toggle.toggled.connect(self.on_advanced_mode_toggled)
        source_header.addWidget(self.advanced_mode_toggle)
        source_layout.addLayout(source_header)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.path_memory_combo = QComboBox()
        self.path_memory_combo.setMinimumWidth(160)
        self.path_memory_combo.textActivated.connect(
            lambda _text: self.use_selected_saved_path()
        )
        path_row.addWidget(self.path_memory_combo)
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText(
            "Escribe la ruta de la carpeta..."
        )
        self.folder_input.setMinimumWidth(180)
        bind_path_tooltip(self.folder_input)
        self.folder_input.textChanged.connect(self.on_folder_path_changed)
        self.folder_input.textChanged.connect(
            lambda _text: self.update_favorite_button_state()
        )
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

        opts_row = QHBoxLayout()
        opts_row.setSpacing(16)

        self.move_folders_checkbox = QCheckBox("Mover carpetas completas")
        self.move_folders_checkbox.setChecked(True)
        opts_row.addWidget(self.move_folders_checkbox)

        self.organize_by_date_checkbox = QCheckBox("Organizar por fecha")
        opts_row.addWidget(self.organize_by_date_checkbox)

        sim_row = QHBoxLayout()
        sim_row.setSpacing(4)
        sim_label = QLabel("Similitud:")
        sim_row.addWidget(sim_label)
        self.similarity_spinbox = QSpinBox()
        self.similarity_spinbox.setRange(0, 100)
        self.similarity_spinbox.setValue(70)
        self.similarity_spinbox.setSuffix("%")
        self.similarity_spinbox.setMinimumWidth(64)
        sim_row.addWidget(self.similarity_spinbox)

        size_row = QHBoxLayout()
        size_row.setSpacing(4)
        size_row.addWidget(QLabel("Tamaño mín.:"))
        self.min_size_spinbox = QSpinBox()
        self.min_size_spinbox.setRange(0, 10240)
        self.min_size_spinbox.setSuffix(" MB")
        self.min_size_spinbox.setMinimumWidth(86)
        size_row.addWidget(self.min_size_spinbox)

        opts_row.addStretch()

        self.analyze_btn = QPushButton("Analizar")
        self.analyze_btn.setObjectName("analyze_button")
        self.analyze_btn.setMinimumWidth(92)
        self.analyze_btn.clicked.connect(self.start_analysis)
        opts_row.addWidget(self.analyze_btn)

        source_layout.addLayout(opts_row)

        self.advanced_controls = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_controls)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        technical_row = QHBoxLayout()
        technical_row.addLayout(sim_row)
        technical_row.addLayout(size_row)
        technical_row.addStretch()
        advanced_layout.addLayout(technical_row)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(8)
        profile_row.addWidget(QLabel("Perfil:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.addItems(self.profile_manager.get_profile_names())
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

        self.filter_bar = FilterBar(
            sorted(self.category_manager.get_categories().keys()),
            self,
        )
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

        # TABLA PRINCIPAL
        self.movements_table = QTableView()
        self.movements_model = VirtualizedMovementsModel()
        self.movements_table.setModel(self.movements_model)
        self.movements_table.setItemDelegateForColumn(
            0, CheckboxDelegate(self.movements_table)
        )
        self.movements_table.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        )
        self.movements_table.setMinimumHeight(220)
        self.movements_table.verticalHeader().setDefaultSectionSize(
            typography_scale(self.app_config).row_height
        )
        self.movements_table.setAlternatingRowColors(True)
        self.movements_table.setShowGrid(False)
        self.movements_table.setWordWrap(False)
        self.movements_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.movements_table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )
        self.movements_table.customContextMenuRequested.connect(self.show_context_menu)

        h = self.movements_table.horizontalHeader()
        for i, w in enumerate([40, 0, 180, 86, 92, 112]):
            self.movements_table.setColumnWidth(i, w)
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for i in range(2, 6):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        h.setSortIndicatorShown(True)
        h.setSectionsClickable(True)
        h.sectionClicked.connect(self.on_header_clicked)
        ol.addWidget(self.movements_table)

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
        self.organize_btn.setEnabled(False)
        self.organize_btn.clicked.connect(self.start_organization)
        action_bar.addWidget(self.organize_btn, 1)

        self.rollback_btn = QPushButton("Deshacer")
        self.rollback_btn.setEnabled(False)
        self.rollback_btn.clicked.connect(self.rollback_last_operation)
        action_bar.addWidget(self.rollback_btn)
        ol.addLayout(action_bar)

        # Progreso (solo visible durante operaciones)
        progress_layout = QHBoxLayout()
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_label = QLabel("")
        self.progress_label.setMinimumWidth(120)
        progress_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(14)
        progress_layout.addWidget(self.progress_bar)
        self.progress_eta_label = QLabel("")
        progress_layout.addWidget(self.progress_eta_label)
        progress_layout.addStretch()
        ol.addLayout(progress_layout)

        # Resumen de estadísticas del análisis.
        # Estos labels son consumidos por update_statistics(); mantenerlos
        # en la interfaz evita que el flujo de análisis dependa de un bloque
        # visual antiguo que ya no se crea en esta ventana.
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

        # ===== PESTANA 2: DISCOS =====
        discs = QWidget()
        dl = QVBoxLayout(discs)
        dl.setContentsMargins(0, 0, 0, 0)
        self.disk_viewer = DiskViewer(disk_manager=None)
        self.disk_viewer.disk_selected.connect(self.on_disk_selected_for_organize)
        dl.addWidget(self.disk_viewer)

        # ===== PESTANA 2B: MUSICA =====
        music = QWidget()
        ml = QVBoxLayout(music)
        ml.setContentsMargins(0, 0, 0, 0)
        self.music_duplicates_view = MusicDuplicatesView()
        self.music_duplicates_view.status_update.connect(self.log_message)
        ml.addWidget(self.music_duplicates_view)

        # ===== PESTANA 3: DUPLICADOS =====
        dups = QWidget()
        dupl = QVBoxLayout(dups)
        dupl.setContentsMargins(0, 0, 0, 0)
        self.duplicates_dashboard = DuplicatesDashboard()
        self.duplicates_dashboard.tab_header.config_requested.connect(
            self.open_configuration
        )
        self.duplicates_dashboard.tab_header.tasks_requested.connect(
            self.open_task_center
        )
        self.duplicates_dashboard.status_update.connect(self.log_message)
        dupl.addWidget(self.duplicates_dashboard)

        # ===== PESTANA 4: LOG (nueva pestaña dedicada) =====
        log_tab = QWidget()
        log_layout = QVBoxLayout(log_tab)
        log_layout.setContentsMargins(12, 12, 12, 12)
        log_layout.setSpacing(8)

        # Header del log
        log_header = QHBoxLayout()
        log_title = QLabel("📝 Registro de Operaciones")
        log_title.setObjectName("log_title_label")
        log_header.addWidget(log_title)
        log_header.addStretch()

        self.clear_log_btn = QPushButton("Limpiar")
        self.clear_log_btn.clicked.connect(self.clear_log)
        log_header.addWidget(self.clear_log_btn)

        self.export_log_btn = QPushButton("Exportar TXT")
        self.export_log_btn.clicked.connect(self.export_log)
        log_header.addWidget(self.export_log_btn)

        self.scroll_to_bottom_btn = QPushButton("Ir al final")
        self.scroll_to_bottom_btn.clicked.connect(self.scroll_log_to_bottom)
        log_header.addWidget(self.scroll_to_bottom_btn)

        log_layout.addLayout(log_header)

        # Widget de log principal
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("log_text")
        self.log_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        log_layout.addWidget(self.log_text)

        # Info del log
        log_info_layout = QHBoxLayout()
        self.log_info_label = QLabel("📊 Total de entradas: 0")
        log_info_layout.addWidget(self.log_info_label)
        log_info_layout.addStretch()
        log_layout.addLayout(log_info_layout)

        # Agregar pestañas
        self.main_tabs.addTab(organ, "📁 Organizar")
        self.main_tabs.addTab(discs, "💾 Discos")
        self.main_tabs.addTab(music, "🎵 Música")
        self.main_tabs.addTab(dups, "🔍 Duplicados")
        self.main_tabs.addTab(log_tab, "📝 Log")
        self._music_tab_index = self.main_tabs.indexOf(music)

        self.main_tabs.currentChanged.connect(self._on_tab_changed)
        self._apply_audio_tab_visibility()

        apply_control_sizes(self, self.app_config)

        # Referencia para compatibilidad con código existente
        self.log_panel = None  # Ya no existe el panel colapsable

        self.log_message("🚀 Interfaz profesional reestructurada lista")

    def on_advanced_mode_toggled(self, checked: bool):
        """Muestra u oculta las opciones avanzadas y persiste el estado."""
        self.advanced_controls.setVisible(checked)
        self.advanced_mode_toggle.setText(
            "Ocultar opciones avanzadas" if checked else "Opciones avanzadas"
        )
        self.app_config.set_ui_advanced_mode(checked)

    def update_favorite_button_state(self):
        """Actualiza el estado visual del botón de favorito."""
        path = self.folder_input.text().strip()
        is_favorite = path in self.app_config.get_favorite_paths()
        self.add_favorite_btn.setText("Guardar favorito" if not is_favorite else "Quitar favorito")
        self.add_favorite_btn.setToolTip(
            "Guardar ruta actual en favoritos"
            if not is_favorite
            else "Quitar ruta actual de favoritos"
        )

    def create_log_widget(self, layout):
        """Crea el widget de log con funcionalidad de exportar"""
        # Header del log
        header_layout = QHBoxLayout()

        log_title = QLabel("📝 REGISTRO DE OPERACIONES")
        log_title.setToolTip(
            "📝 Historial completo de todas las operaciones realizadas en la aplicación"
        )
        log_title.setObjectName("log_title_label")
        header_layout.addWidget(log_title)

        header_layout.addStretch()

        # Botones de control del log
        self.clear_log_btn = QPushButton("🗑️ Limpiar Log")
        self.clear_log_btn.setToolTip("🗑️ Limpia todo el contenido del log")
        self.clear_log_btn.clicked.connect(self.clear_log)
        header_layout.addWidget(self.clear_log_btn)

        self.export_log_btn = QPushButton("📤 Exportar a TXT")
        self.export_log_btn.setToolTip(
            "📤 Exporta el contenido del log a un archivo de texto"
        )
        self.export_log_btn.clicked.connect(self.export_log)
        header_layout.addWidget(self.export_log_btn)

        layout.addLayout(header_layout)

        # Widget de log principal
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setToolTip(
            "📝 Registro detallado de todas las operaciones realizadas en la aplicación"
        )
        self.log_text.setObjectName("log_text")

        # Configurar el log con scroll automático
        self.log_text.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.log_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        layout.addWidget(self.log_text)

        # Información del log
        info_layout = QHBoxLayout()

        self.log_info_label = QLabel("📊 Total de entradas: 0")
        self.log_info_label.setToolTip("📊 Número total de entradas en el log")
        self.log_info_label.setObjectName("log_info_label")
        info_layout.addWidget(self.log_info_label)

        info_layout.addStretch()

        # Botón para ir al final del log
        self.scroll_to_bottom_btn = QPushButton("⬇️ Ir al Final")
        self.scroll_to_bottom_btn.setToolTip(
            "⬇️ Desplaza el log hasta la entrada más reciente"
        )
        self.scroll_to_bottom_btn.clicked.connect(self.scroll_log_to_bottom)
        info_layout.addWidget(self.scroll_to_bottom_btn)

        layout.addLayout(info_layout)

        # Mensaje inicial
        self.log_message(f"Ordenasion {APP_VERSION} iniciada · registro de operaciones activo")

    def add_categories_info(self, layout):
        """Añade información sobre las categorías disponibles"""
        # Título
        title_label = QLabel("📁 Categorías Disponibles:")
        # El label usará los estilos del tema automáticamente
        layout.addWidget(title_label)

        # Información de categorías
        categories = self.category_manager.get_categories()
        info_text = ""

        for category, extensions in categories.items():
            info_text += f"• <b>{category}</b>: {len(extensions)} extensiones\n"

        info_label = QLabel(info_text)
        # El label usará los estilos del tema automáticamente
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Texto de ayuda
        help_text = QLabel(
            "💡 <b>Consejo:</b> Haz doble clic en las filas de 'archivos sueltos' para expandir y ver archivos individuales."
        )
        # El label usará los estilos del tema automáticamente
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

    def setup_connections(self):
        """Configura las conexiones de señales"""
        # Las conexiones ya se configuraron en init_ui
        pass

    def setup_state_observers(self):
        """✅ NUEVO: Configura observadores del estado centralizado"""
        try:
            # Verificar que app_state esté disponible
            if not hasattr(app_state, "state_changed"):
                self.log_message(
                    "⚠️ app_state no está completamente inicializado, saltando observadores"
                )
                return

            # Conectar señales del estado centralizado
            try:
                app_state.state_changed.connect(self.on_state_changed)
            except Exception as e:
                self.log_message(f"⚠️ Error conectando state_changed: {e}")

            try:
                app_state.theme_changed.connect(self.on_theme_changed)
            except Exception as e:
                self.log_message(f"⚠️ Error conectando theme_changed: {e}")

            try:
                app_state.disk_selected.connect(self.on_disk_selected)
            except Exception as e:
                self.log_message(f"⚠️ Error conectando disk_selected: {e}")

            # Conectar señales del gestor de workers (temporalmente comentado)
            # worker_manager.worker_started.connect(self.on_worker_started)
            # worker_manager.worker_completed.connect(self.on_worker_completed)
            # worker_manager.worker_progress.connect(self.on_worker_progress)
            # worker_manager.worker_error.connect(self.on_worker_error)

            # Conectar señales del gestor de memoria (temporalmente comentado)
            # memory_manager.memory_warning.connect(self.on_memory_warning)
            # memory_manager.cleanup_completed.connect(self.on_memory_cleanup)

            self.log_message("✅ Observadores del estado centralizado configurados")

        except Exception as e:
            self.log_message(f"❌ Error configurando observadores: {e}")

    def on_state_changed(self, event):
        """Maneja cambios del estado de la aplicación"""
        try:
            event_type = event.event_type
            data = event.data

            if event_type == EventType.THEME_CHANGED:
                # El tema ya se maneja en on_theme_changed
                pass
            elif event_type == EventType.DISK_SELECTED:
                # El disco ya se maneja en on_disk_selected
                pass
            elif event_type == EventType.WORKER_STARTED:
                worker_id = data.get("worker_id")
                if worker_id:
                    self.log_message(f"🚀 Worker iniciado: {worker_id}")
            elif event_type == EventType.WORKER_FINISHED:
                worker_id = data.get("worker_id")
                if worker_id:
                    self.log_message(f"✅ Worker completado: {worker_id}")
            elif event_type == EventType.MEMORY_CLEANUP:
                cache_name = data.get("cache_name")
                self.log_message(f"🧹 Limpieza de memoria: {cache_name}")

        except Exception as e:
            self.log_message(f"❌ Error manejando cambio de estado: {e}")

    def on_theme_changed(self, theme_name: str):
        """Maneja cambios de tema"""
        try:
            self.log_message(f"🎨 Tema cambiado a: {theme_name}")
            # El tema se aplica automáticamente por el sistema de temas
        except Exception as e:
            self.log_message(f"❌ Error manejando cambio de tema: {e}")

    def on_disk_selected(self, disk_path: str):
        """Maneja selección de disco"""
        try:
            self.log_message(f"💾 Disco seleccionado: {disk_path}")
            # La lógica de selección de disco ya está implementada
        except Exception as e:
            self.log_message(f"❌ Error manejando selección de disco: {e}")

    def on_worker_started(self, worker_id: str, worker_type: str):
        """Maneja inicio de workers"""
        try:
            self.log_message(f"🚀 Worker iniciado: {worker_type} ({worker_id})")

            # Actualizar UI según el tipo de worker
            if "Analysis" in worker_type:
                self.analyze_btn.setEnabled(False)
                self.progress_bar.setVisible(True)
                self.progress_bar.setRange(0, 0)
            elif "Organize" in worker_type:
                self.organize_btn.setEnabled(False)
                self.organize_btn.setText("Organizando...")

        except Exception as e:
            self.log_message(f"❌ Error manejando inicio de worker: {e}")

    def on_worker_completed(self, worker_id: str, success: bool):
        """Maneja completación de workers"""
        try:
            status = "✅ exitoso" if success else "❌ con errores"
            self.log_message(f"🏁 Worker completado: {worker_id} - {status}")

            # Restaurar UI
            self.analyze_btn.setEnabled(True)
            self.organize_btn.setEnabled(True)
            self.organize_btn.setText("Revisar y organizar")
            self.progress_bar.setVisible(False)

        except Exception as e:
            self.log_message(f"❌ Error manejando completación de worker: {e}")

    def on_worker_progress(self, worker_id: str, progress: float):
        """Maneja progreso de workers"""
        try:
            # Actualizar barra de progreso si es visible
            if self.progress_bar.isVisible():
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(int(progress * 100))

        except Exception as e:
            self.log_message(f"❌ Error manejando progreso de worker: {e}")

    def on_worker_error(self, worker_id: str, error_message: str):
        """Maneja errores de workers"""
        try:
            self.log_message(f"❌ Error en worker {worker_id}: {error_message}")

            # Restaurar UI en caso de error
            self.analyze_btn.setEnabled(True)
            self.organize_btn.setEnabled(True)
            self.organize_btn.setText("Revisar y organizar")
            self.progress_bar.setVisible(False)

        except Exception as e:
            self.log_message(f"❌ Error manejando error de worker: {e}")

    def on_memory_warning(self, warning_type: str, memory_mb: float):
        """Maneja advertencias de memoria"""
        try:
            self.log_message(
                f"⚠️ Advertencia de memoria: {warning_type} ({memory_mb:.1f} MB)"
            )

            # Mostrar advertencia al usuario si es crítica
            if memory_mb > 500:  # Más de 500MB
                QMessageBox.warning(
                    self,
                    "Advertencia de Memoria",
                    f"El uso de memoria es alto: {memory_mb:.1f} MB\n\n"
                    "Se recomienda cerrar otras aplicaciones o reiniciar el programa.",
                )

        except Exception as e:
            self.log_message(f"❌ Error manejando advertencia de memoria: {e}")

    def on_memory_cleanup(self, stats):
        """Maneja limpieza de memoria completada"""
        try:
            self.log_message(
                f"🧹 Limpieza de memoria completada: {stats.cache_size_mb:.1f} MB caché, {stats.active_workers} workers"
            )
        except Exception as e:
            self.log_message(f"❌ Error manejando limpieza de memoria: {e}")

    def setup_shortcuts(self):
        """🚀 MEJORA: Configura los atajos de teclado para operaciones comunes"""
        # Ctrl+O: Abrir carpeta
        QShortcut(QKeySequence("Ctrl+O"), self, self.browse_folder)

        # Ctrl+R o F5: Analizar/Refrescar
        QShortcut(QKeySequence("F5"), self, self.start_analysis)
        QShortcut(QKeySequence("Ctrl+R"), self, self.start_analysis)

        # Ctrl+S: Organizar archivos
        QShortcut(QKeySequence("Ctrl+S"), self, self.start_organization)

        # Ctrl+F: Buscar (cambiar a pestaña de duplicados)
        QShortcut(
            QKeySequence("Ctrl+F"), self, lambda: self.main_tabs.setCurrentIndex(3)
        )

        # Ctrl+A: Seleccionar todo
        QShortcut(QKeySequence("Ctrl+A"), self, self.select_all_items)

        # Ctrl+D: Deseleccionar todo
        QShortcut(QKeySequence("Ctrl+D"), self, self.deselect_all_items)

        # Ctrl+L: Limpiar log
        QShortcut(QKeySequence("Ctrl+L"), self, self.clear_log)

        # Ctrl+,: Abrir configuración (o Ctrl+P como alternativa)
        QShortcut(QKeySequence("Ctrl+P"), self, self.open_configuration)
        QShortcut(QKeySequence("Ctrl+,"), self, self.open_configuration)

        # Ctrl+1, Ctrl+2, Ctrl+3, Ctrl+4, Ctrl+5: Cambiar entre pestañas
        QShortcut(
            QKeySequence("Ctrl+1"), self, lambda: self.main_tabs.setCurrentIndex(0)
        )
        QShortcut(
            QKeySequence("Ctrl+2"), self, lambda: self.main_tabs.setCurrentIndex(1)
        )
        QShortcut(
            QKeySequence("Ctrl+3"), self, lambda: self.main_tabs.setCurrentIndex(2)
        )
        QShortcut(
            QKeySequence("Ctrl+4"), self, lambda: self.main_tabs.setCurrentIndex(3)
        )
        QShortcut(
            QKeySequence("Ctrl+5"), self, lambda: self.main_tabs.setCurrentIndex(4)
        )

        # Ctrl+Q: Salir
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)

        # Actualizar tooltips para mostrar atajos
        self.browse_btn.setToolTip(
            "📂 Selecciona la carpeta que quieres analizar (Ctrl+O)"
        )
        self.analyze_btn.setToolTip(
            "🔍 Analiza el contenido de la carpeta (Ctrl+R o F5)"
        )
        self.organize_btn.setToolTip("📁 Organiza los archivos seleccionados (Ctrl+S)")
        self.select_all_btn.setToolTip(
            "☑️ Marca todos los elementos para ser organizados (Ctrl+A)"
        )
        self.deselect_all_btn.setToolTip("❌ Desmarca todos los elementos (Ctrl+D)")
        self.config_btn.setToolTip(
            "⚙️ Abre la configuración de categorías y extensiones (Ctrl+P)"
        )

        # Mensaje en log sobre atajos disponibles
        self.log_message(
            "⌨️ Atajos de teclado habilitados. Usa Ctrl+O, Ctrl+R, Ctrl+S, Ctrl+F, etc."
        )

    def browse_folder(self):
        """Abre el diálogo para seleccionar una carpeta"""
        folder_path = QFileDialog.getExistingDirectory(
            self, "📂 Seleccionar Carpeta a Organizar"
        )

        if folder_path:
            self.folder_input.setText(folder_path)
            self.app_config.push_recent_path(folder_path)
            self.refresh_saved_paths()

    def on_folder_path_changed(self, text):
        """Maneja el cambio en el campo de ruta de carpeta"""
        if hasattr(self, "movements_model"):
            self.update_selection_count()
        if text.strip() and os.path.exists(text.strip()):
            if self.app_config.get_auto_analyze():
                # Pequeño delay para evitar análisis mientras se escribe
                if not hasattr(self, "_auto_analysis_timer"):
                    self._auto_analysis_timer = QTimer(self)
                    self._auto_analysis_timer.setSingleShot(True)
                    self._auto_analysis_timer.timeout.connect(self.start_analysis)
                self._auto_analysis_timer.start(1000)

    def start_analysis(self):
        """Inicia el análisis de la carpeta usando el gestor de workers"""
        if hasattr(self, "_auto_analysis_timer"):
            self._auto_analysis_timer.stop()
        if self.current_analysis_task_id or self.current_organize_task_id:
            return
        try:
            # Verificar que la ventana esté completamente inicializada
            if not hasattr(self, "analyze_btn") or not self.analyze_btn:
                self.log_message(
                    "⚠️ Ventana no completamente inicializada, análisis cancelado"
                )
                return

            folder_path = self.folder_input.text().strip()

            if not folder_path:
                QMessageBox.warning(
                    self,
                    "Advertencia",
                    "Por favor, selecciona una carpeta para analizar.",
                )
                return

            if not os.path.exists(folder_path):
                QMessageBox.warning(
                    self, "Advertencia", "La carpeta seleccionada no existe."
                )
                return

            if not os.path.isdir(folder_path):
                QMessageBox.warning(
                    self, "Advertencia", "El elemento seleccionado no es una carpeta."
                )
                return

            self._analysis_folder_path = os.path.normcase(os.path.realpath(folder_path))
            self._analysis_result_path = None

            # Limpiar resultados anteriores
            self.folder_movements = []
            self.file_movements = []
            self.preview_btn.setEnabled(False)

            # Log
            self.app_config.set_min_similarity(self.similarity_spinbox.value())
            self.app_config.set_min_file_size_mb(self.min_size_spinbox.value())
            self.app_config.push_recent_path(folder_path)
            self.refresh_saved_paths()
            self.log_message(f"🔍 Iniciando análisis de: {folder_path}")

            # Crear worker usando el gestor centralizado
            worker_id = f"analysis_{int(time.time())}"
            analysis_worker = AnalysisWorker(
                folder_path,
                self.category_manager.get_categories(),
                self.category_manager.ext_to_categoria,
                self.similarity_spinbox.value(),
                min_file_size_mb=self.min_size_spinbox.value(),
                ignored_extensions=self.app_config.get_ignored_extensions(),
                ignored_paths=self.app_config.get_ignored_paths(),
            )

            # Guardar referencia al worker para limpieza
            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            self._active_workers.append(analysis_worker)

            # Conectar señales específicas del worker
            analysis_worker.progress_update.connect(
                lambda message, task_id=worker_id: self._handle_task_progress(
                    task_id, message
                )
            )
            analysis_worker.analysis_complete.connect(self.on_analysis_complete)
            analysis_worker.error_occurred.connect(self.on_analysis_error)

            # Conectar señal de finalización para limpiar el worker
            analysis_worker.finished.connect(
                lambda: self._cleanup_worker(analysis_worker)
            )

            # Iniciar worker
            task_registry.start_task(
                worker_id, "Análisis de organización", analysis_worker.stop
            )
            self.current_analysis_task_id = worker_id
            analysis_worker.start()
            self.log_message(f"✅ Worker de análisis iniciado: {worker_id}")

        except Exception as e:
            error_msg = f"❌ Error al iniciar análisis: {str(e)}"
            self.log_message(error_msg)
            QMessageBox.critical(self, "Error de Análisis", error_msg)

            # Restaurar botones en caso de error
            if hasattr(self, "analyze_btn"):
                self.analyze_btn.setEnabled(True)
            if hasattr(self, "organize_btn"):
                self.organize_btn.setEnabled(True)
            if hasattr(self, "progress_bar"):
                self.progress_bar.setVisible(False)

    def on_analysis_complete(self, folder_movements, file_movements, stats):
        """Maneja la completacion del analisis con auto-seleccion inteligente"""
        self.folder_movements = folder_movements
        self.file_movements = file_movements
        self._analysis_result_path = self._analysis_folder_path

        # Llenar tabla
        self.populate_results_table()

        # AUTO-SELECCION: Si el checkbox esta marcado, seleccionar todo
        if (
            hasattr(self, "auto_select_checkbox")
            and self.auto_select_checkbox.isChecked()
        ):
            self.select_all_items()
            self.log_message("☑️ Auto-seleccion: todos los elementos marcados")

        # Habilitar botones usando la selección real
        self.analyze_btn.setEnabled(True)
        if self.current_analysis_task_id:
            task_registry.finish_task(self.current_analysis_task_id, "Completada")
            self.current_analysis_task_id = None
        self.update_selection_count()

        # Ocultar progreso
        self.progress_bar.setVisible(False)

        # Log
        total_items = len(folder_movements) + len(file_movements)
        self.log_message(f"✅ Analisis completado: {total_items} elementos encontrados")

        if hasattr(self, "filter_bar"):
            self.filter_bar.update_categories(
                sorted({mov["category"] for mov in folder_movements + file_movements})
            )
            self.filter_bar.update_count(self.movements_model.get_visible_count())

        # Mostrar estadisticas
        if stats:
            self.log_message(
                f"📊 Estadisticas: {stats.get('total_folders', 0)} carpetas, {stats.get('total_files', 0)} archivos"
            )

            # Actualizar estadisticas detalladas
            self.update_statistics()

            # Inicializar estadisticas de seleccion (sin elementos seleccionados)
            self.update_selected_statistics()

    def on_analysis_error(self, error_message):
        """Maneja errores durante el análisis"""
        self.log_message(error_message)

        # Habilitar botones
        self.analyze_btn.setEnabled(True)
        self.organize_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)

        # Ocultar progreso
        self.progress_bar.setVisible(False)
        if self.current_analysis_task_id:
            task_registry.finish_task(self.current_analysis_task_id, "Error")
            self.current_analysis_task_id = None

        QMessageBox.critical(self, "Error de Análisis", error_message)

    def populate_results_table(self):
        """🚀 MEJORA: Llena la tabla VIRTUALIZADA con los resultados del análisis"""
        # Limpiar datos anteriores en una sola operación para evitar doble parpadeo
        self.movements_model.clear_data()

        # Preparar datos para el modelo virtualizado
        model_data = []

        # Añadir carpetas
        for mov in self.folder_movements:
            model_data.append(
                {
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
                }
            )

        # Añadir archivos (agrupados por categoría)
        files_by_category = defaultdict(list)
        size_by_category = defaultdict(int)

        for mov in self.file_movements:
            files_by_category[mov["category"]].append(mov)
            size_by_category[mov["category"]] += mov.get("size", 0)

        for category, file_movs in files_by_category.items():
            total_size = size_by_category[category]

            model_data.append(
                {
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
                    "group_files": file_movs,  # Guardar archivos para expansión
                }
            )

        # Actualizar modelo con nuevos datos (virtualización automática)
        self.movements_model.update_data(model_data)

        # ✅ CRÍTICO: Re-aplicar anchos de columna después de actualizar el modelo
        # El resetModel() puede cambiar los anchos, así que los re-aplicamos
        self.movements_table.setColumnWidth(0, 40)  # Checkbox
        self.movements_table.setColumnWidth(2, 180)  # Destino
        self.movements_table.setColumnWidth(3, 86)  # Porcentaje
        self.movements_table.setColumnWidth(4, 92)  # Archivos
        self.movements_table.setColumnWidth(5, 112)  # Tamaño

        # Log de performance
        self.log_message(
            f"✅ Tabla virtualizada poblada con {len(model_data)} elementos (performance óptima)"
        )

        # Actualizar contador de selección y estadísticas
        self.update_selection_count()
        self.update_statistics()

    def select_all_items(self):
        """🚀 MEJORA: Selecciona todos los elementos usando el modelo virtualizado"""
        self.movements_model.check_all()
        self.update_selection_count()
        self.log_message("✅ Todos los elementos seleccionados")

    def deselect_all_items(self):
        """🚀 MEJORA: Deselecciona todos los elementos usando el modelo virtualizado"""
        self.movements_model.uncheck_all()
        self.update_selection_count()
        self.log_message("❌ Todos los elementos deseleccionados")

    def on_model_data_changed(self, top_left, bottom_right, roles):
        """🚀 MEJORA: Maneja cambios en el modelo (checkboxes)"""
        if Qt.ItemDataRole.CheckStateRole in roles:
            self.update_selection_count()

    def on_table_double_clicked(self, index):
        """🚀 MEJORA: Maneja doble clic en la tabla virtualizada"""
        if not index.isValid():
            return

        row = index.row()
        row_data = self.movements_model.get_row_data(row)

        if not row_data:
            return

        # Solo expandir/contraer grupos de archivos
        if row_data.get("is_group", False):
            self.toggle_file_group_expansion(row)

    def toggle_file_group_expansion(self, group_row):
        """Expande o contrae un grupo de archivos sueltos"""
        # Validar que la fila existe y es grupo
        model = self.movements_model
        total_rows = model.rowCount()
        if group_row >= total_rows or not model.is_group_row(group_row):
            return

        # Alternar usando el modelo (sin tocar celdas)
        row_data = model.get_row_data(group_row)
        if row_data.get("is_expanded", False):
            model.collapse_group(group_row)
        else:
            model.expand_group(group_row)

    def expand_file_group(self, group_row, category):
        """Compat: usa el modelo para expandir"""
        self.movements_model.expand_group(group_row)

    def collapse_file_group(self, group_row, category):
        """Compat: usa el modelo para colapsar"""
        self.movements_model.collapse_group(group_row)

    def update_selection_count(self):
        """🚀 MEJORA: Actualiza el contador usando el modelo virtualizado"""
        selected_rows = self.movements_model.get_checked_rows()
        total_count = sum(
            1
            for row in range(self.movements_model.rowCount())
            if not (self.movements_model.get_row_data(row) or {}).get("is_child", False)
        )
        selected_count = len(selected_rows)

        self.selection_count_label.setText(
            f"Elementos: {selected_count}/{total_count} seleccionados"
        )

        # Habilitar/deshabilitar botón de organizar según selección
        path = self.folder_input.text().strip()
        matches_analysis = (bool(path) and os.path.isdir(path)
                            and os.path.normcase(os.path.realpath(path)) == self._analysis_result_path)
        enabled = (selected_count > 0 and matches_analysis
                   and not self.current_organize_task_id and not self.current_analysis_task_id)
        self.organize_btn.setEnabled(enabled)
        self.preview_btn.setEnabled(enabled)

        # Actualizar estadísticas de elementos seleccionados
        self.update_selected_statistics()

        if hasattr(self, "filter_bar"):
            self.filter_bar.update_count(self.movements_model.get_visible_count())

    def update_selected_statistics(self):
        """🚀 MEJORA: Actualiza las estadísticas usando el modelo virtualizado"""
        selected_size = 0
        selected_files = 0

        # Obtener filas seleccionadas del modelo
        selected_rows = self.movements_model.get_checked_rows()

        for row in selected_rows:
            row_data = self.movements_model.get_row_data(row)
            if row_data:
                # Sumar tamaño
                selected_size += row_data.get("size_bytes", 0)

                # Contar archivos
                if row_data.get("type") == "file_group":
                    selected_files += row_data.get(
                        "file_count", len(row_data.get("group_files", []))
                    )
                else:
                    selected_files += row_data.get("file_count", 1)

        # Actualizar las tarjetas de estadísticas
        self.total_size_label.setText(f"{self.format_size(selected_size)}")
        self.total_files_label.setText(f"{selected_files:,} archivos")

        # Log de la actualización (solo si hay cambios significativos)
        if selected_files > 0:
            self.log_message(
                f"📊 Estadísticas actualizadas: {selected_files} elementos seleccionados ({self.format_size(selected_size)})"
            )

    def update_statistics(self):
        """Actualiza las estadísticas mostradas en la barra de estado y el bloque detallado"""
        if not hasattr(self, "folder_movements") or not hasattr(self, "file_movements"):
            return

        # Calcular estadísticas por categoría
        category_stats = defaultdict(lambda: {"count": 0, "size": 0})

        # Contar carpetas por categoría
        for mov in self.folder_movements:
            category = mov["category"]
            category_stats[category]["count"] += 1
            category_stats[category]["size"] += mov.get("size", 0)

        # Contar archivos por categoría
        for mov in self.file_movements:
            category = mov["category"]
            category_stats[category]["count"] += 1
            category_stats[category]["size"] += mov.get("size", 0)

        # Formatear estadísticas para la barra de estado
        stats_text = ""
        for category in [
            "MUSICA",
            "VIDEOS",
            "IMAGENES",
            "DOCUMENTOS",
            "PROGRAMAS",
            "CODIGO",
            "VARIOS",
        ]:
            if category in category_stats:
                count = category_stats[category]["count"]
                if count > 0:
                    percentage = (
                        count / (len(self.folder_movements) + len(self.file_movements))
                    ) * 100
                    stats_text += f"{category}({percentage:.0f}%) • "

        # Limpiar el último "• "
        if stats_text.endswith("• "):
            stats_text = stats_text[:-2]

        if stats_text:
            self.stats_label.setText(f"{stats_text}")
        else:
            self.stats_label.setText(
                "📈 MÚSICA(0%) • VIDEOS(0%) • IMÁG(0%) • VARIOS(0%)"
            )

        # Actualizar estadísticas detalladas
        self.update_detailed_statistics(category_stats)

    def update_detailed_statistics(self, category_stats):
        """Actualiza las estadísticas detalladas del bloque de estadísticas mejorado"""
        # Calcular totales
        total_size = sum(stats["size"] for stats in category_stats.values())
        total_files = sum(stats["count"] for stats in category_stats.values())

        # Actualizar etiquetas de tamaño y archivos con formato mejorado
        self.total_size_label.setText(f"{self.format_size(total_size)}")
        self.total_files_label.setText(f"{total_files:,} archivos")

        # Formatear estadísticas por categoría de manera más organizada
        category_text = ""
        category_count = 0

        # Ordenar categorías por cantidad de archivos
        sorted_categories = sorted(
            category_stats.items(), key=lambda x: x[1]["count"], reverse=True
        )

        for category, stats in sorted_categories:
            if stats["count"] > 0:
                count = stats["count"]
                size = stats["size"]
                category_text += f"<b>{category}:</b> {count:,} archivos ({self.format_size(size)})<br/>"
                category_count += 1

        if category_text:
            # Añadir resumen al inicio
            category_text = (
                f"<div style='margin-bottom: 8px;'><b>📊 {category_count} categorías detectadas:</b></div>"
                + category_text
            )
            self.category_stats_label.setText(category_text)
        else:
            self.category_stats_label.setText(
                "📁 <b>Por categoría:</b> Sin datos detectados"
            )

        # Actualizar información de categorías disponibles con formato mejorado
        categories = self.category_manager.get_categories()
        available_text = ""
        total_extensions = 0

        for category, extensions in categories.items():
            available_text += f"<b>{category}:</b> {len(extensions)} extensiones<br/>"
            total_extensions += len(extensions)

        if available_text:
            # Añadir resumen al inicio
            available_text = (
                f"<div style='margin-bottom: 8px;'><b>⚙️ {len(categories)} categorías configuradas ({total_extensions} extensiones total):</b></div>"
                + available_text
            )
            self.available_categories_label.setText(available_text)
        else:
            self.available_categories_label.setText(
                "⚙️ <b>Categorías disponibles:</b> Sin datos"
            )

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
            self.log_message("ℹ️ Modo: Solo archivos sueltos (carpetas ignoradas)")
        else:
            self.log_message("ℹ️ Modo: Carpetas completas + archivos sueltos")
        return folder_movements, file_movements

    def start_organization(self):
        """🚀 MEJORA: Inicia la organización usando el modelo virtualizado"""
        if (getattr(self, "_organization_review_open", False)
                or self.current_organize_task_id or self.current_analysis_task_id):
            return
        folder_path = self.folder_input.text().strip()
        if (not os.path.isdir(folder_path)
                or os.path.normcase(os.path.realpath(folder_path)) != self._analysis_result_path):
            QMessageBox.warning(self, "Analiza la carpeta actual",
                                "La selección corresponde a otra carpeta o la ruta ya no está disponible. Analiza la carpeta actual antes de revisar.")
            return
        selected_folder_movements, selected_file_movements = self._get_effective_selected_movements()

        if not selected_folder_movements and not selected_file_movements:
            QMessageBox.warning(
                self, "Advertencia", "No hay elementos seleccionados para organizar."
            )
            return

        folder_path = self.folder_input.text().strip()

        # Mostrar Preview antes de organizar
        preview = PreviewDialog(
            selected_folder_movements,
            selected_file_movements,
            folder_path,
            self,
            organize_by_date=self.organize_by_date_checkbox.isChecked(),
            check_duplicates=self.check_duplicates_checkbox.isChecked(),
            conflict_policy=self.app_config.get_organization_conflict_policy(),
        )
        self._organization_review_open = True
        try:
            accepted = preview.exec() == QDialog.DialogCode.Accepted
        finally:
            self._organization_review_open = False
        if not accepted:
            self.log_message("Organizacion cancelada por el usuario (preview)")
            return

        # Crear worker usando el gestor centralizado
        worker_id = f"organize_{int(time.time())}"
        organize_worker = OrganizeWorker(
            folder_path,
            selected_folder_movements,
            selected_file_movements,
            organize_by_date=self.organize_by_date_checkbox.isChecked(),
            check_duplicates=self.check_duplicates_checkbox.isChecked(),
            protected_paths=self.app_config.get_protected_paths(),
            conflict_policy=preview.get_conflict_policy(),
        )

        # Guardar referencia al worker para limpieza
        if not hasattr(self, "_active_workers"):
            self._active_workers = []
        self._active_workers.append(organize_worker)

        # Conectar señales específicas del worker
        organize_worker.progress_update.connect(
            lambda message, task_id=worker_id: self._handle_task_progress(
                task_id, message
            )
        )
        organize_worker.organize_complete.connect(self.on_organize_complete)
        organize_worker.rollback_available.connect(self.on_rollback_available)
        organize_worker.summary_ready.connect(self.on_operation_summary_ready)

        # Conectar señal de finalización para limpiar el worker
        organize_worker.finished.connect(lambda: self._cleanup_worker(organize_worker))

        # Iniciar worker
        task_registry.start_task(
            worker_id, "Organización de archivos", organize_worker.stop
        )
        self.current_organize_task_id = worker_id
        self.last_operation_summary = None
        self.organize_btn.setEnabled(False)
        self.organize_btn.setText("Organizando…")
        self.rollback_btn.setEnabled(False)
        self.operation_state_changed.emit()
        organize_worker.start()
        self.log_message(f"✅ Worker de organización iniciado: {worker_id}")

    def on_organize_complete(self, success, message):
        """Maneja completación de la organización"""
        # Restaurar UI
        self.organize_btn.setEnabled(True)
        self.organize_btn.setText("Revisar y organizar")
        self.progress_bar.setVisible(False)

        if success:
            if self.current_organize_task_id:
                task_registry.finish_task(self.current_organize_task_id, "Completada")
                self.current_organize_task_id = None
            self.log_message("✅ " + message)
            if self.last_operation_summary:
                OperationSummaryDialog(self.last_operation_summary, self).exec()
            self._schedule_post_organization_refresh()
        else:
            if self.current_organize_task_id:
                task_registry.finish_task(self.current_organize_task_id, "Error")
                self.current_organize_task_id = None
            self.log_message("❌ " + message)
            QMessageBox.critical(self, "Error de Organización", message)
        self.rollback_btn.setEnabled(bool(self.last_transaction_id))
        self.operation_state_changed.emit()

    def _schedule_post_organization_refresh(self):
        """Relanza el análisis para reflejar el estado real tras organizar."""
        folder_path = self.folder_input.text().strip() if hasattr(self, "folder_input") else ""
        if not folder_path or not os.path.isdir(folder_path):
            self.log_message(
                "⚠️ No se pudo refrescar automáticamente: la ruta actual ya no es válida"
            )
            return

        self.log_message("🔄 Refrescando resultados tras la organización...")
        QTimer.singleShot(150, self.start_analysis)

    def on_rollback_available(self, transaction_id: str):
        """Guarda la última transacción disponible para deshacer."""
        self.last_transaction_id = transaction_id
        self.rollback_btn.setEnabled(bool(transaction_id))
        self.log_message(f"↩️ Rollback disponible: {transaction_id}")
        self.operation_state_changed.emit()

    def on_operation_summary_ready(self, summary: dict):
        """Guarda resumen de la última operación."""
        self.last_operation_summary = summary
        self.operation_state_changed.emit()

    def rollback_last_operation(self):
        """Revierte la última organización confirmada."""
        if self.current_organize_task_id:
            return
        if not self.last_transaction_id:
            QMessageBox.information(
                self,
                "Sin historial",
                "No hay una transacción reciente para deshacer.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Deshacer última organización",
            "¿Quieres revertir la última organización completada?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.transaction_manager.rollback_transaction(self.last_transaction_id):
            self.log_message(f"✅ Rollback completado: {self.last_transaction_id}")
            QMessageBox.information(
                self,
                "Rollback completado",
                "Los cambios de la última organización se han revertido.",
            )
            self.rollback_btn.setEnabled(False)
            self.last_transaction_id = None
            if self.last_operation_summary is not None:
                self.last_operation_summary = dict(self.last_operation_summary, undone=True)
            self._schedule_post_organization_refresh()
        else:
            self.log_message(f"❌ Error al revertir: {self.last_transaction_id}")
            QMessageBox.warning(
                self,
                "Rollback incompleto",
                "No se pudieron revertir todos los cambios. Revisa el log de operaciones.",
            )
        self.operation_state_changed.emit()

    def refresh_profiles(self):
        """Recarga la lista de perfiles en la interfaz."""
        if not hasattr(self, "profile_combo"):
            return
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

        self.folder_input.setText(profile.folder_path)
        self.move_folders_checkbox.setChecked(profile.move_folders)
        self.similarity_spinbox.setValue(profile.similarity_threshold)
        self.organize_by_date_checkbox.setChecked(profile.organize_by_date)
        self.app_config.set_protected_paths(profile.exclude_patterns)
        self.log_message(f"🧩 Perfil cargado: {profile.name}")

    def save_current_profile(self):
        """Guarda el estado actual en un perfil."""
        current_name = self.profile_combo.currentText().strip()
        suggested_name = current_name or "Nuevo perfil"
        profile_name, ok = QInputDialog.getText(
            self,
            "Guardar perfil",
            "Nombre del perfil:",
            text=suggested_name,
        )
        if not ok or not profile_name.strip():
            return

        normalized_name = profile_name.strip()
        profile = self.profile_manager.get_profile(normalized_name)
        if profile is None:
            profile = self.profile_manager.create_profile(normalized_name)

        if profile is None:
            QMessageBox.warning(self, "Error", "No se pudo crear el perfil.")
            return

        profile.folder_path = self.folder_input.text().strip()
        profile.move_folders = self.move_folders_checkbox.isChecked()
        profile.similarity_threshold = self.similarity_spinbox.value()
        profile.organize_by_date = self.organize_by_date_checkbox.isChecked()
        profile.exclude_patterns = self.app_config.get_protected_paths()
        profile.selected_categories = sorted(
            {
                row_data.get("category")
                for row in self.movements_model.get_checked_rows()
                if (row_data := self.movements_model.get_row_data(row))
            }
        )
        self.profile_manager.update_profile(profile)
        self.profile_manager.set_active_profile(profile.name)
        self.refresh_profiles()
        self.profile_combo.setCurrentText(profile.name)
        self.log_message(f"💾 Perfil guardado: {profile.name}")

    def open_configuration(self, focus_section: str | None = None):
        """Abre la ventana de configuración"""
        dialog = ConfigDialog(
            self,
            self.category_manager,
            app_config_ref=self.app_config,
            focus_section=focus_section,
        )

        # Aplicar tema actual al diálogo
        self.apply_theme_to_dialog_simple(dialog)

        # Conectar señal de cambios de interfaz
        dialog.interface_changes_requested.connect(self.apply_interface_changes)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Actualizar categorías
            self.category_manager = dialog.category_manager
            self._apply_audio_tab_visibility()

            # Actualizar información de categorías
            self.update_categories_info()

            QMessageBox.information(
                self,
                "✅ Configuración Actualizada",
                "✅ Configuración de categorías actualizada.\n\n"
                "🎨 Los cambios de tema y fuente se aplican INMEDIATAMENTE.\n"
                "📁 Los cambios de categorías se aplican en el próximo análisis.",
            )

    def _apply_audio_tab_visibility(self):
        audio_enabled = bool(
            getattr(self.app_config, "get_audio_enabled", lambda: True)()
        )
        if (
            hasattr(self, "music_duplicates_view")
            and self.music_duplicates_view is not None
        ):
            self.music_duplicates_view.setEnabled(audio_enabled)
        if hasattr(self.main_tabs, "setTabVisible"):
            self.main_tabs.setTabVisible(self._music_tab_index, audio_enabled)
        else:
            self.main_tabs.setTabEnabled(self._music_tab_index, audio_enabled)
        if not audio_enabled and self.main_tabs.currentIndex() == self._music_tab_index:
            self.main_tabs.setCurrentIndex(0)

    def apply_saved_interface_settings(self):
        """Aplica la configuración de interfaz guardada UNA SOLA VEZ"""
        try:
            # SOLO UNA APLICACIÓN para evitar conflictos
            theme = self.app_config.get_theme()
            font_size = self.app_config.get_font_size()
            self.similarity_spinbox.setValue(self.app_config.get_min_similarity())
            self.min_size_spinbox.setValue(self.app_config.get_min_file_size_mb())
            advanced_mode = self.app_config.get_ui_advanced_mode()
            self.advanced_mode_toggle.blockSignals(True)
            self.advanced_mode_toggle.setChecked(advanced_mode)
            self.advanced_mode_toggle.blockSignals(False)
            self.on_advanced_mode_toggled(advanced_mode)
            self.update_favorite_button_state()

            # Aplicar tema y fuente JUNTOS en una sola operación
            self.apply_theme_and_font_together(theme, font_size)

            # Checkbox usa estilos básicos del tema

            self.log_message(f"✅ Configuración aplicada: {theme}, {font_size}px")

        except Exception as e:
            self.log_message(f"⚠️ Error aplicando configuración guardada: {str(e)}")

    def _parse_csv_extensions(self) -> List[str]:
        return self.app_config.get_ignored_extensions()

    def _parse_semicolon_paths(self, value: str) -> List[str]:
        return [item.strip() for item in value.split(";") if item.strip()]

    def refresh_saved_paths(self):
        """Actualiza el selector de favoritos y recientes."""
        if not hasattr(self, "path_memory_combo"):
            return
        current = self.path_memory_combo.currentData()
        self.path_memory_combo.clear()
        for path in self.app_config.get_favorite_paths():
            self.path_memory_combo.addItem(f"⭐ {path}", path)
            self.path_memory_combo.setItemData(
                self.path_memory_combo.count() - 1, path, Qt.ItemDataRole.ToolTipRole
            )
        for path in self.app_config.get_recent_paths():
            label = f"🕘 {path}"
            if self.path_memory_combo.findData(path) == -1:
                self.path_memory_combo.addItem(label, path)
                self.path_memory_combo.setItemData(
                    self.path_memory_combo.count() - 1, path, Qt.ItemDataRole.ToolTipRole
                )
        index = self.path_memory_combo.findData(current)
        if index >= 0:
            self.path_memory_combo.setCurrentIndex(index)
        elif self.path_memory_combo.count() > 0:
            self.path_memory_combo.setCurrentIndex(0)
        self.update_favorite_button_state()

    def use_selected_saved_path(self):
        """Carga una ruta guardada en el campo principal."""
        path = self.path_memory_combo.currentData()
        if path:
            self.folder_input.setText(path)

    def add_current_path_to_favorites(self):
        """Añade o quita la ruta actual de favoritos."""
        path = self.folder_input.text().strip()
        if not path:
            return
        if path in self.app_config.get_favorite_paths():
            self.app_config.remove_favorite_path(path)
            self.log_message(f"🗑️ Ruta eliminada de favoritos: {path}")
        else:
            self.app_config.add_favorite_path(path)
            self.log_message(f"⭐ Ruta añadida a favoritos: {path}")
        self.refresh_saved_paths()

    def remove_selected_favorite(self):
        """Elimina la ruta seleccionada de favoritos."""
        path = self.path_memory_combo.currentData()
        if not path:
            return
        self.app_config.remove_favorite_path(path)
        self.refresh_saved_paths()
        self.log_message(f"🗑️ Ruta eliminada de favoritos: {path}")

    def add_ignored_path(self):
        """Añade una carpeta a la lista de exclusiones."""
        self.open_exclusions_configuration()

    def open_exclusions_configuration(self):
        """Abre la configuración enfocada en la sección de exclusiones."""
        self.open_configuration("exclusions")

    def open_task_center(self):
        """Abre el centro de tareas."""
        TaskCenterDialog(self).exec()

    def _animate_tab_transition(self, index: int):
        widget = self.main_tabs.widget(index)
        if widget is None:
            return

        effect = widget.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)

        effect.setOpacity(0.0)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: widget.setGraphicsEffect(None))
        self._tab_fade_anim = animation
        animation.start()

    def _handle_task_progress(self, task_id: str, message: str):
        """Actualiza task center y log."""
        task_registry.update_task(task_id, message)
        self.log_message(message)

    def apply_theme_and_font_together(self, theme_name: str, font_size: int):
        """Aplica tema y fuente JUNTOS usando FastThemeApplier con precarga de caché"""
        try:
            from PyQt6.QtWidgets import QApplication, QDialog

            # Precargar tema en caché para rendimiento futuro
            ThemeCache.preload_theme(theme_name, [10, 12, 14, 16])

            # Usar FastThemeApplier para aplicación ultra-rápida (UN SOLO PASO)
            FastThemeApplier.apply_theme_fast(theme_name, font_size)

            # Obtener paleta y CSS para elementos especiales
            palette = ThemeManager.apply_theme_to_palette(theme_name)
            css_styles = ThemeManager.get_css_styles(theme_name, font_size)

            # Aplicar a la ventana principal
            self.setPalette(palette)
            self.setStyleSheet(css_styles)

            # Aplicar estilos a tarjetas y elementos especiales
            self.apply_stats_cards_styles(theme_name)

            # Actualizar diálogos abiertos
            app = QApplication.instance()
            if app:
                for widget in app.allWidgets():
                    if isinstance(widget, QDialog) and widget.isVisible():
                        if hasattr(widget, "apply_current_theme_to_self"):
                            widget.apply_current_theme_to_self()
                        else:
                            widget.setPalette(palette)
                            widget.setStyleSheet(css_styles)

            # Refrescar componentes especiales
            if hasattr(self, "disk_viewer") and self.disk_viewer:
                try:
                    self.disk_viewer.setStyleSheet("")
                    for child in self.disk_viewer.findChildren(QWidget):
                        try:
                            child.setStyleSheet("")
                        except Exception:
                            pass
                    self.disk_viewer.apply_theme_styles(theme_name)
                    QTimer.singleShot(
                        150, lambda: self._refresh_disk_viewer_after_theme(theme_name)
                    )
                except Exception:
                    pass

            # Refrescar tablas y re-aplicar anchos
            QTimer.singleShot(200, lambda: self._refresh_all_tables_after_theme())
            QTimer.singleShot(250, lambda: self._reapply_table_column_widths())

            self.update()
            self.repaint()
            if app:
                app.processEvents()

        except Exception as e:
            self.log_message(f"⚠️ Error aplicando tema y fuente: {str(e)}")
            import traceback

            self.log_message(f"Traceback: {traceback.format_exc()}")

    def _cleanup_worker(self, worker):
        """Limpia un worker después de que termine"""
        try:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            # Esperar a que el thread termine antes de eliminarlo
            if worker.isRunning():
                worker.wait(1000)  # Esperar máximo 1 segundo
            worker.deleteLater()
        except Exception:
            pass

    def apply_theme_to_all_widgets_simple(
        self, palette, css_styles, update_visual: bool = True
    ):
        """Aplica tema a todos los widgets de forma simple y eficiente"""
        try:
            # Aplicar a todos los widgets hijos
            for widget in self.findChildren(QWidget):
                try:
                    widget.setPalette(palette)
                    # Solo aplicar CSS si no tiene estilos personalizados con !important
                    current_style = widget.styleSheet() or ""
                    if not current_style or "!important" not in current_style:
                        widget.setStyleSheet(css_styles)

                    # Si el widget tiene apply_theme_styles (como DiskViewer), llamarlo también
                    if (
                        hasattr(widget, "apply_theme_styles")
                        and widget is not self.disk_viewer
                    ):
                        try:
                            theme_name = self.app_config.get_theme()
                            widget.apply_theme_styles(theme_name)
                        except:
                            pass

                    # Solo actualizar visualmente si se solicita
                    if update_visual:
                        widget.update()
                except:
                    pass

        except Exception as e:
            pass

    def apply_theme_to_dialog_simple(self, dialog):
        """Aplica el tema actual a un diálogo usando el sistema mejorado"""
        try:
            # Si el diálogo tiene método para aplicar tema, usarlo (es el método más completo)
            if hasattr(dialog, "apply_current_theme_to_self"):
                dialog.apply_current_theme_to_self()
            else:
                # Fallback: aplicar tema básico
                theme = self.app_config.get_theme()
                font_size = self.app_config.get_font_size()
                palette = ThemeManager.apply_theme_to_palette(theme)
                css_styles = ThemeManager.get_css_styles(theme, font_size)

                dialog.setPalette(palette)
                dialog.setStyleSheet(css_styles)

                # Aplicar a todos los widgets hijos del diálogo
                for widget in dialog.findChildren(QWidget):
                    try:
                        widget.setPalette(palette)
                        widget.setStyleSheet(css_styles)
                    except:
                        pass

                dialog.update()
                dialog.repaint()

        except Exception as e:
            self.log_message(f"⚠️ Error aplicando tema al diálogo: {str(e)}")
            # Fallback al método anterior
            try:
                theme = self.app_config.get_theme()
                font_size = self.app_config.get_font_size()
                self._apply_theme_to_dialog_fallback(dialog, theme, font_size)
            except:
                pass

    def _apply_theme_to_dialog_fallback(self, dialog, theme, font_size):
        """Método de respaldo para aplicar tema a diálogos"""
        try:
            # Aplicar paleta y estilos
            palette = ThemeManager.apply_theme_to_palette(theme)
            css_styles = ThemeManager.get_css_styles(theme, font_size)

            # Aplicar al diálogo
            dialog.setPalette(palette)
            dialog.setStyleSheet(css_styles)

            # Aplicar a todos los widgets hijos del diálogo de forma recursiva
            def apply_to_all_widgets(widget):
                try:
                    widget.setPalette(palette)
                    # Solo aplicar estilos si no tiene estilos personalizados ya definidos
                    if not widget.styleSheet():
                        widget.setStyleSheet(css_styles)
                    elif "QInputDialog" in str(type(widget)):
                        # Forzar estilos para QInputDialog que pueden tener estilos por defecto
                        widget.setStyleSheet(css_styles)

                    # Aplicar recursivamente a todos los hijos
                    for child in widget.children():
                        if hasattr(child, "setPalette"):
                            apply_to_all_widgets(child)
                except Exception:
                    pass

            # Aplicar a todos los widgets hijos del diálogo
            for child in dialog.findChildren(QWidget):
                apply_to_all_widgets(child)

            # Forzar actualización completa
            dialog.update()
            dialog.repaint()
            dialog.show()  # Forzar repintado

        except Exception as e:
            self.log_message(f"⚠️ Error en método de respaldo: {str(e)}")

    def apply_interface_changes(self, font_size: int, theme: str):
        """Aplica cambios de interfaz desde el diálogo de configuración"""
        try:
            # Guardar configuración PRIMERO
            self.app_config.set_font_size(font_size)
            self.app_config.set_theme(theme)

            # Aplicar tema y fuente JUNTOS
            self.apply_theme_and_font_together(theme, font_size)

            # Actualizar diálogos abiertos si existen (especialmente ConfigDialog)
            self.refresh_open_dialogs()

            # Asegurar que el ConfigDialog se actualice inmediatamente si está abierto
            from PyQt6.QtWidgets import QApplication

            app = QApplication.instance()
            if app:
                for widget in app.allWidgets():
                    if isinstance(widget, ConfigDialog) and widget.isVisible():
                        # Actualizar INMEDIATAMENTE sin delay
                        widget.apply_current_theme_to_self()

            self.log_message(
                f"✅ Configuración de interfaz aplicada: {font_size}px, {theme}"
            )

        except Exception as e:
            self.log_message(f"❌ Error aplicando cambios de interfaz: {str(e)}")

    def _refresh_disk_viewer_after_theme(self, theme_name: str):
        """Refresca el DiskViewer después de aplicar el tema"""
        try:
            if hasattr(self, "disk_viewer") and self.disk_viewer:
                # Refrescar la tabla de discos para aplicar nuevos colores
                self.disk_viewer.refresh_disks()

                # Actualizar información del disco seleccionado si hay uno
                selected_disk = self.disk_viewer.get_selected_disk_path()
                if selected_disk:
                    self.disk_viewer.update_selected_disk_info(selected_disk)

                # Forzar actualización visual
                self.disk_viewer.update()
                self.disk_viewer.repaint()
        except Exception as e:
            self.log_message(
                f"⚠️ Error refrescando DiskViewer después del tema: {str(e)}"
            )

    def _refresh_all_tables_after_theme(self):
        """Refresca todas las tablas y widgets después de aplicar el tema"""
        try:
            from PyQt6.QtWidgets import QTableWidget, QTableView

            # Refrescar tabla de movimientos si existe
            if hasattr(self, "movements_table") and self.movements_table:
                self.movements_table.update()
                self.movements_table.repaint()

            # Refrescar tabla de duplicados si existe
            if hasattr(self, "duplicates_dashboard") and self.duplicates_dashboard:
                try:
                    # El tema ya se aplicó en el paso 3, solo refrescar la tabla
                    if (
                        hasattr(self.duplicates_dashboard, "duplicates_table")
                        and self.duplicates_dashboard.duplicates_table
                    ):
                        self.duplicates_dashboard.duplicates_table.update()
                        self.duplicates_dashboard.duplicates_table.repaint()
                    # Aplicar estilos al botón de escaneo si existe
                    if hasattr(self.duplicates_dashboard, "apply_scan_button_style"):
                        self.duplicates_dashboard.apply_scan_button_style()
                except Exception as e:
                    self.log_message(
                        f"⚠️ Error refrescando DuplicatesDashboard: {str(e)}"
                    )

            # Refrescar todas las tablas encontradas
            for widget in self.findChildren(QTableWidget):
                try:
                    widget.update()
                    widget.repaint()
                except:
                    pass
            for widget in self.findChildren(QTableView):
                try:
                    widget.update()
                    widget.repaint()
                except:
                    pass

            # Forzar actualización de la ventana principal
            self.update()
            self.repaint()
        except Exception as e:
            self.log_message(f"⚠️ Error refrescando tablas después del tema: {str(e)}")

    def _reapply_table_column_widths(self):
        """✅ Re-aplica los anchos de columna de TODAS las tablas después de cambiar el tema/fuente"""
        try:
            # 1. Tabla principal de movimientos
            if hasattr(self, "movements_table") and self.movements_table:
                self.movements_table.setColumnWidth(0, 40)  # Checkbox
                self.movements_table.setColumnWidth(2, 180)  # Destino
                self.movements_table.setColumnWidth(3, 86)  # Porcentaje
                self.movements_table.setColumnWidth(4, 92)  # Archivos
                self.movements_table.setColumnWidth(5, 112)  # Tamaño
                self.log_message("📏 Anchos de tabla principal re-aplicados")

            # 2. Tabla de duplicados
            if hasattr(self, "duplicates_dashboard") and self.duplicates_dashboard:
                if hasattr(self.duplicates_dashboard, "apply_column_widths"):
                    self.duplicates_dashboard.apply_column_widths()
                    self.log_message("📏 Anchos de tabla de duplicados re-aplicados")

            # 3. Tabla de discos (en DiskViewer)
            if hasattr(self, "disk_viewer") and self.disk_viewer:
                if hasattr(self.disk_viewer, "disks_table"):
                    # Anchos predefinidos de la tabla de discos
                    self.disk_viewer.disks_table.setColumnWidth(0, 80)  # Unidad
                    self.disk_viewer.disks_table.setColumnWidth(5, 80)  # % Uso
                    self.disk_viewer.disks_table.setColumnWidth(6, 100)  # Sistema
                    self.disk_viewer.disks_table.setColumnWidth(7, 130)  # Botón
                    self.log_message("📏 Anchos de tabla de discos re-aplicados")

            self.log_message(
                "✅ Todos los anchos de columna re-aplicados después del cambio"
            )
        except Exception as e:
            self.log_message(f"⚠️ Error re-aplicando anchos de columna: {str(e)}")

    def refresh_open_dialogs(self):
        """Actualiza todos los diálogos abiertos con el tema actual"""
        try:
            # Buscar todos los diálogos hijos de la ventana principal
            from PyQt6.QtWidgets import QDialog

            for child in self.findChildren(QDialog):
                if child.isVisible() and child.parent() == self:
                    self.apply_theme_to_dialog_simple(child)

            self.log_message("🔄 Diálogos abiertos actualizados con nuevo tema")
        except Exception as e:
            self.log_message(f"⚠️ Error actualizando diálogos: {str(e)}")

    # Función eliminada - ahora se aplica junto con el tema

    def apply_stats_cards_styles(self, theme_name: str):
        values = [getattr(self, name, None) for name in
                  ("total_size_label", "total_files_label", "selection_count_label")]
        if any(value is not None and value.window().objectName() == "fluentAppWindow" for value in values):
            tokens = current_tokens(self.app_config.get_accent_color(), self.app_config.get_theme_mode())
            for value in values:
                if value is not None:
                    value.setStyleSheet(f"color: {tokens.text_primary}; background: transparent; border: none;")
            return
        """Aplica estilos dinámicos a las tarjetas de estadísticas y separadores"""
        try:
            colors = ThemeManager.get_theme_colors(theme_name)

            # Aplicar estilos a separadores
            for separator in self.findChildren(QFrame):
                if separator.objectName() in ["separator1", "separator2"]:
                    separator.setStyleSheet(f"QFrame {{ color: {colors['border']}; }}")

            # Aplicar estilos a tarjetas de estadísticas
            card_style = f"""
                QFrame {{
                    background-color: {colors["surface"]};
                    border: 1px solid {colors["border"]};
                    border-radius: 8px;
                    padding: 12px;
                    margin: 4px;
                }}
                QFrame:hover {{
                    border: 2px solid {colors["accent"]};
                }}
            """
            for card in self.findChildren(QFrame):
                if card.objectName() == "stats_card":
                    card.setStyleSheet(card_style)

            # Aplicar estilos a headers de tarjetas
            type_metrics = typography_scale(self.app_config)
            header_style = f"""
                QLabel {{
                    color: {colors["accent"]};
                    font-weight: bold;
                    font-size: {type_metrics.small}px;
                    text-align: center;
                    margin-bottom: 8px;
                }}
            """
            for header in self.findChildren(QLabel):
                if header.objectName() == "stats_card_header":
                    header.setStyleSheet(header_style)

            # Aplicar estilos a labels de valores
            value_style = f"""
                QLabel {{
                    color: {colors["text_primary"]};
                    font-weight: bold;
                    font-size: {type_metrics.body}px;
                    text-align: center;
                    padding: 8px;
                    background-color: {colors["surface"]};
                    border-radius: 4px;
                    border: 1px solid {colors["border"]};
                }}
            """
            value_labels = [
                "total_size_label",
                "total_files_label",
                "category_stats_label",
                "available_categories_label",
            ]
            for label in self.findChildren(QLabel):
                if label.objectName() in value_labels:
                    label.setStyleSheet(value_style)
        except Exception as e:
            self.log_message(f"⚠️ Error aplicando estilos a tarjetas: {str(e)}")

    def apply_theme(self, theme_name: str):
        """Aplica un tema específico (usa apply_theme_and_font_together internamente)"""
        try:
            # Obtener el tamaño de fuente actual
            current_font_size = self.app_config.get_font_size()

            # Usar el método unificado
            self.apply_theme_and_font_together(theme_name, current_font_size)

            self.log_message(f"✅ Tema aplicado: {theme_name}")

        except Exception as e:
            self.log_message(f"⚠️ Error aplicando tema: {str(e)}")

    # Función eliminada - simplificada

    # Función eliminada - simplificada

    # Funciones complejas eliminadas - simplificadas en apply_theme_to_all_widgets_simple

    def update_categories_info(self):
        """Actualiza la información de categorías mostrada"""
        # Buscar y actualizar el widget de información de categorías
        for child in self.findChildren(QGroupBox):
            if "Información" in child.title():
                # Limpiar layout existente
                for i in reversed(range(child.layout().count())):
                    child.layout().itemAt(i).widget().setParent(None)

                # Añadir nueva información
                self.add_categories_info(child.layout())
                break

    def log_message(self, message):
        """Añade un mensaje al log"""
        from datetime import datetime

        timestamp = datetime.now().strftime("%H:%M:%S")
        level_color = "#1976d2"
        if "❌" in message or "Error" in message:
            level_color = "#c62828"
        elif "⚠️" in message or "Advertencia" in message:
            level_color = "#ed6c02"
        elif "✅" in message:
            level_color = "#2e7d32"
        safe_message = html.escape(message)
        self.log_text.append(
            f"<span style='color:#888'>[{timestamp}]</span> "
            f"<span style='color:{level_color}'>{safe_message}</span>"
        )

        # Auto-scroll al final
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # Actualizar contador de entradas
        self.update_log_info()

    def clear_log(self):
        """Limpia todo el contenido del log"""
        reply = QMessageBox.question(
            self,
            "Limpiar Log",
            "¿Estás seguro de que quieres limpiar todo el contenido del log?\n\n"
            "Esta acción no se puede deshacer.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.log_text.clear()
            self.log_message("🗑️ Log limpiado por el usuario")
            self.update_log_info()

    def export_log(self):
        """Exporta el contenido del log a un archivo de texto"""
        from datetime import datetime

        # Generar nombre de archivo con timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"log_organizador_{timestamp}.txt"

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "📤 Exportar Log",
            default_filename,
            "Archivos de texto (*.txt);;Todos los archivos (*)",
        )

        if filepath:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write("📝 LOG DEL ORGANIZADOR DE ARCHIVOS\n")
                    f.write("=" * 50 + "\n")
                    f.write(
                        f"Fecha de exportación: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    )
                    f.write(f"Total de entradas: {self.get_log_entry_count()}\n")
                    f.write("=" * 50 + "\n\n")
                    f.write(self.log_text.toPlainText())

                QMessageBox.information(
                    self,
                    "✅ Exportación Exitosa",
                    f"Log exportado exitosamente a:\n{filepath}\n\n"
                    f"Total de entradas exportadas: {self.get_log_entry_count()}",
                )

                self.log_message(f"📤 Log exportado a: {filepath}")

            except Exception as e:
                QMessageBox.critical(
                    self,
                    "❌ Error de Exportación",
                    f"No se pudo exportar el log:\n{str(e)}",
                )
                self.log_message(f"❌ Error al exportar log: {str(e)}")

    def scroll_log_to_bottom(self):
        """Desplaza el log hasta la entrada más reciente"""
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.log_message("⬇️ Desplazado al final del log")

    def update_log_info(self):
        """Actualiza la información del log"""
        entry_count = self.get_log_entry_count()
        self.log_info_label.setText(f"📊 Total de entradas: {entry_count}")

    def get_log_entry_count(self):
        """Obtiene el número total de entradas en el log"""
        text = self.log_text.toPlainText()
        if not text.strip():
            return 0

        # Contar líneas que empiezan con timestamp [HH:MM:SS]
        lines = text.split("\n")
        count = 0
        for line in lines:
            if line.strip() and line.strip().startswith("[") and "]" in line:
                count += 1

        return count

    def on_disk_selected_for_organize(self, disk_path):
        """Maneja la selección de un disco para organizar archivos"""
        try:
            # Cambiar a la pestaña de organizar
            self.main_tabs.setCurrentIndex(0)

            # Establecer la ruta del disco seleccionado
            self.folder_input.setText(disk_path)

            # Log del cambio
            self.log_message(f"💾 Disco seleccionado para organización: {disk_path}")

            # Verificar que la ventana esté completamente inicializada antes de analizar
            if hasattr(self, "analyze_btn") and self.analyze_btn:
                # Auto-iniciar análisis del disco con delay más largo
                QTimer.singleShot(2000, self.start_analysis)
            else:
                self.log_message(
                    "⚠️ Ventana no completamente inicializada, análisis manual requerido"
                )

        except Exception as e:
            self.log_message(f"❌ Error al seleccionar disco: {str(e)}")
            QMessageBox.critical(
                self, "Error", f"Error al seleccionar disco:\n{str(e)}"
            )

    def format_size(self, size_bytes):
        """Formatea el tamaño en bytes a una representación legible"""
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1

        return f"{size_bytes:.1f} {size_names[i]}"

    # ✅ NUEVO: Métodos para gestión de columnas y menú contextual

    def show_context_menu(self, position):
        """Muestra menú contextual para la tabla de movimientos"""
        try:
            # Obtener la fila donde se hizo clic
            index = self.movements_table.indexAt(position)
            if not index.isValid():
                return

            row = index.row()

            # Obtener información del elemento
            model = self.movements_table.model()
            element_data = model.data(model.index(row, 1), Qt.ItemDataRole.DisplayRole)
            destination_data = model.data(
                model.index(row, 2), Qt.ItemDataRole.DisplayRole
            )

            if not element_data:
                return

            # Crear menú contextual
            menu = QMenu(self)
            apply_menu_surface(menu)

            # Acción para abrir ubicación del archivo
            if hasattr(self, "folder_path") and self.folder_path:
                open_location_action = QAction("📁 Abrir ubicación", self)
                open_location_action.triggered.connect(
                    lambda: self.open_file_location(self.folder_path)
                )
                menu.addAction(open_location_action)

            # Acción para expandir/contraer grupo (si es aplicable)
            row_data = model.get_row_data(row)
            if row_data and row_data.get("is_group", False):
                if row_data.get("is_expanded", False):
                    collapse_action = QAction("📁 Contraer grupo", self)
                    collapse_action.triggered.connect(lambda: model.collapse_group(row))
                else:
                    expand_action = QAction("📂 Expandir grupo", self)
                    expand_action.triggered.connect(lambda: model.expand_group(row))
                menu.addAction(
                    expand_action
                    if not row_data.get("is_expanded", False)
                    else collapse_action
                )

            # Mostrar menú
            menu.exec(self.movements_table.mapToGlobal(position))

        except Exception as e:
            self.log_message(f"❌ Error en menú contextual: {str(e)}")

    def open_file_location(self, folder_path):
        """Abre la ubicación del archivo en el explorador"""
        try:
            import subprocess
            import sys

            if sys.platform == "win32":
                # Windows - abrir explorer
                subprocess.Popen(f'explorer "{folder_path}"')
            elif sys.platform == "darwin":
                # macOS
                subprocess.Popen(["open", str(folder_path)])
            else:
                # Linux
                subprocess.Popen(["xdg-open", str(folder_path)])

        except Exception as e:
            QMessageBox.warning(
                self, "Error", f"No se pudo abrir la ubicación:\n{str(e)}"
            )

    def on_header_clicked(self, logical_index):
        """Maneja el clic en el encabezado de una columna para ordenar"""
        # Solo permitir ordenamiento en columnas de tamaño y porcentaje
        if logical_index in [3, 5]:  # Porcentaje (3) y Tamaño (5)
            # Obtener información de ordenamiento actual
            sort_info = (
                self.movements_model.get_sort_info()
                if hasattr(self.movements_model, "get_sort_info")
                else {"column": -1, "order": Qt.SortOrder.AscendingOrder}
            )

            # Determinar nuevo orden
            if sort_info["column"] == logical_index:
                # Misma columna, cambiar orden
                new_order = (
                    Qt.SortOrder.DescendingOrder
                    if sort_info["order"] == Qt.SortOrder.AscendingOrder
                    else Qt.SortOrder.AscendingOrder
                )
            else:
                # Nueva columna, empezar con ascendente
                new_order = Qt.SortOrder.AscendingOrder

            # Aplicar ordenamiento si el modelo lo soporta
            if hasattr(self.movements_model, "sort"):
                self.movements_model.sort(logical_index, new_order)

            # Actualizar indicador visual
            header = self.movements_table.horizontalHeader()
            header.setSortIndicator(logical_index, new_order)

            self.log_message(
                f"📊 Ordenando por columna {logical_index} ({'descendente' if new_order == Qt.SortOrder.DescendingOrder else 'ascendente'})"
            )

    def closeEvent(self, event):
        """Maneja el cierre de la ventana con limpieza completa"""
        try:
            self.log_message("🔄 Cerrando aplicación...")

            # Limpiar todos los workers activos
            if hasattr(self, "_active_workers"):
                for worker in self._active_workers[:]:  # Copia de la lista
                    try:
                        if worker.isRunning():
                            worker.quit()
                            worker.wait(2000)  # Esperar máximo 2 segundos
                        worker.deleteLater()
                    except:
                        pass
                self._active_workers.clear()

            # Limpiar estado centralizado (si está disponible)
            try:
                if hasattr(app_state, "cleanup"):
                    app_state.cleanup()
            except Exception as cleanup_error:
                self.log_message(
                    f"⚠️ Error durante cleanup de app_state: {cleanup_error}"
                )

            self.log_message("✅ Aplicación cerrada correctamente")

        except Exception as e:
            self.log_message(f"❌ Error durante el cierre: {e}")
            import traceback

            self.log_message(traceback.format_exc())

        # Aceptar el evento de cierre
        event.accept()

    # ===== MEJORAS UX: Drag & Drop =====

    def _on_log_toggled(self, checked: bool):
        """Legacy: el log ahora está en una pestaña dedicada"""
        pass

    def _on_folder_dropped(self, folder_path: str):
        """Maneja una carpeta soltada en la zona de Drag & Drop"""
        self.folder_input.setText(folder_path)
        self.log_message(f"📂 Carpeta arrastrada: {folder_path}")
        # Auto-analizar
        QTimer.singleShot(500, self.start_analysis)

    def _toggle_drop_zone(self, checked: bool):
        """Muestra/oculta la zona de Drag & Drop"""
        if hasattr(self, "drop_zone"):
            self.drop_zone.setVisible(checked)
            if checked:
                self.log_message("🖱️ Zona Drag & Drop activada")
            else:
                self.log_message("🖱️ Zona Drag & Drop desactivada")

    # ===== LAZY LOADING PESTANAS (ASINCRONO) =====

    def _on_tab_changed(self, index: int):
        """Maneja el cambio de pestana con carga diferida ASINCRONA para no bloquear UI"""
        # Tab 1: Gestion de Discos - Carga asincrona
        if index == 1 and not self._disk_viewer_initialized:
            # Mostrar indicador de carga inmediatamente
            self.log_message("💾 Cargando DiskViewer...")
            # Cargar en segundo plano para no bloquear
            QTimer.singleShot(100, self._load_disk_viewer_async)

        # Tab 2: Duplicados - Carga asincrona
        elif index == 2 and not self._duplicates_initialized:
            QTimer.singleShot(100, self._load_duplicates_async)

    def _load_disk_viewer_async(self):
        """Carga DiskViewer de forma asincrona para no bloquear UI"""
        if self.disk_viewer:
            # Usar QTimer para cargar en el siguiente ciclo del event loop
            # Esto permite que la UI se actualice primero
            self.disk_viewer.refresh_disks()
            self._disk_viewer_initialized = True
            self.log_message("✅ DiskViewer cargado")

    def _load_duplicates_async(self):
        """Carga DuplicadosDashboard de forma asincrona"""
        if self.duplicates_dashboard:
            self.duplicates_dashboard.apply_scan_button_style()
            self._duplicates_initialized = True
            self.log_message("✅ DuplicadosDashboard cargado")

    # ===== MEJORAS UX: Busqueda y Filtro =====

    def _on_filter_changed(self, search_text: str, category: str):
        """Maneja cambios en el filtro de busqueda"""
        if hasattr(self, "movements_model"):
            self.movements_model.set_filter(search_text, category)
            # Actualizar contador
            visible = self.movements_model.get_visible_count()
            if hasattr(self, "filter_bar"):
                self.filter_bar.update_count(visible)
            self.log_message(
                f"🔍 Filtro: '{search_text}' | Categoria: '{category}' → {visible} resultados"
            )

    # ===== MODO COMPACTO/EXPANDIDO =====

    def _toggle_sidebar(self):
        """Muestra/oculta el sidebar izquierdo"""
        if self.sidebar.isVisible():
            self.sidebar.hide()
            self.sidebar_toggle_btn.setText("▶")
            self.log_message("◀ Sidebar oculto")
        else:
            self.sidebar.show()
            self.sidebar_toggle_btn.setText("◀")
            self.log_message("▶ Sidebar visible")

    def _toggle_compact_mode(self, checked: bool):
        """Alterna entre modo compacto y expandido"""
        self._is_compact_mode = checked
        if checked:
            self.compact_mode_btn.setText("📐 Modo Expandido")
            self._apply_compact_mode()
            self.log_message("📐 Modo compacto activado")
        else:
            self.compact_mode_btn.setText("📐 Modo Compacto")
            self._apply_expanded_mode()
            self.log_message("📐 Modo expandido activado")

    def _apply_compact_mode(self):
        """Aplica modo compacto"""
        metrics = typography_scale(self.app_config)
        # Reducir tamaño de fuentes
        self.setStyleSheet(
            self.styleSheet()
            + f"""
            QLabel, QPushButton, QCheckBox, QSpinBox {{ font-size: {metrics.small}px; }}
            QTableView {{ font-size: {metrics.small}px; }}
            QTableView::item {{ padding: 2px; }}
        """
        )
        # Reducir altura de filas
        if hasattr(self, "movements_table"):
            self.movements_table.verticalHeader().setDefaultSectionSize(metrics.row_height)
        # Ocultar elementos secundarios
        if hasattr(self, "stats_group"):
            self.stats_group.setVisible(False)

    def _apply_expanded_mode(self):
        """Aplica modo expandido"""
        # Restaurar estilos
        self.setStyleSheet("")
        # Restaurar altura de filas
        if hasattr(self, "movements_table"):
            self.movements_table.verticalHeader().setDefaultSectionSize(
                typography_scale(self.app_config).row_height
            )
        # Mostrar elementos secundarios
        if hasattr(self, "stats_group"):
            self.stats_group.setVisible(True)

    # ===== PROGRESO MEJORADO =====

    def update_progress(self, current: int, total: int, message: str = ""):
        """Actualiza la barra de progreso con contador y ETA"""
        if total == 0:
            return

        # Actualizar barra
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        self.progress_bar.setVisible(True)

        # Actualizar label
        if message:
            self.progress_label.setText(f"{message} ({current}/{total})")
        else:
            self.progress_label.setText(f"Procesando: {current}/{total}")

        # Calcular ETA
        if hasattr(self, "_progress_start_time") and current > 0:
            elapsed = time.time() - self._progress_start_time
            items_per_sec = current / elapsed
            remaining = total - current
            eta_seconds = remaining / items_per_sec if items_per_sec > 0 else 0

            if eta_seconds > 60:
                eta_str = f"{int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
            else:
                eta_str = f"{int(eta_seconds)}s"

            self.progress_eta_label.setText(f"⏱️ ETA: {eta_str}")
        else:
            self.progress_eta_label.setText("⏱️ Calculando...")

    def start_progress(self, total: int):
        """Inicia el seguimiento de progreso"""
        self._progress_start_time = time.time()
        self.update_progress(0, total)

    def finish_progress(self, message: str = "Completado"):
        """Finaliza el seguimiento de progreso"""
        self.progress_bar.setVisible(False)
        self.progress_label.setText(message)
        self.progress_eta_label.setText("")
        if hasattr(self, "_progress_start_time"):
            elapsed = time.time() - self._progress_start_time
            self.log_message(f"✅ {message} en {elapsed:.1f}s")
