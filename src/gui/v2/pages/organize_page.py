"""Página Organizar nativa (Fluent), sobre el ``OrganizeController``.

El controlador guarda el estado y los workers (analizar → organizar →
deshacer); la página solo pide los datos, confirma con diálogos Fluent y
muestra el resultado:

- carpeta de origen con Examinar, favoritas y recientes (y arrastrar y
  soltar, que instala el shell);
- opciones: carpetas completas, por fecha y, en «Opciones avanzadas»,
  similitud, tamaño mínimo, perfil, duplicados, conflictos y exclusiones;
- progreso con cancelación segura;
- resultados en una tabla virtualizada con casillas, búsqueda, filtro por
  categoría, orden por columna y menú contextual;
- «Revisar y organizar» → vista previa → organización → resumen, y Deshacer.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    IndeterminateProgressBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    ScrollArea,
    SpinBox,
    SubtitleLabel,
    TransparentPushButton,
)

from src.core.organization_conflicts import (
    CONFLICT_POLICY_OVERWRITE,
    CONFLICT_POLICY_RENAME,
    CONFLICT_POLICY_SKIP,
)
from src.gui.filter_bar import FilterBar
from src.gui.preview_dialog import PreviewDialog
from src.gui.table_models import VirtualizedMovementsModel
from src.gui.task_center import task_registry
from src.gui.v2.components import (
    ActionBar, EmptyState, GlassCard, PageHeader, TextPromptDialog, alert, ask, notify, prepare_page_surface,
)
from src.gui.v2.pages import organize_support as support
from src.gui.v2.theme import bind_path_tooltip, current_tokens, typography_scale
from src.utils.app_config import AppConfig
from src.utils.formatting import format_bytes

CONFLICT_CHOICES = (
    ("Mantener ambos (renombrar)", CONFLICT_POLICY_RENAME),
    ("Sobrescribir el existente", CONFLICT_POLICY_OVERWRITE),
    ("Omitir los que entren en conflicto", CONFLICT_POLICY_SKIP),
)
EMPTY_TEXT = "Elige una carpeta y pulsa Analizar para ver qué se puede organizar."


class OrganizePage(ScrollArea):
    """Analiza, revisa y organiza; sin estado propio de los workers."""

    activity_requested = pyqtSignal()
    # La configuración avanzada se aceptó (categorías, audio o exclusiones)
    configuration_changed = pyqtSignal()

    AUTO_ANALYSIS_DELAY_MS = 1000
    REFRESH_DELAY_MS = 150

    def __init__(self, config: AppConfig, controller, category_manager, profile_manager, parent=None):
        super().__init__(parent)
        self.config = config
        self.app_config = config  # los diálogos buscan la configuración en sus padres
        self.controller = controller
        self.category_manager = category_manager
        self.profile_manager = profile_manager
        self.folder_movements: list = []
        self.file_movements: list = []
        # Exclusiones del perfil cargado (se suman a las rutas protegidas)
        self._profile_exclusions: list[str] = []
        self._analysis_folder_path = None
        self._analysis_result_path = None
        self._organization_review_open = False
        self._auto_analysis_timer = QTimer(self)
        self._auto_analysis_timer.setSingleShot(True)
        self._auto_analysis_timer.timeout.connect(self.start_analysis)

        self.setObjectName("organizePage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWidgetResizable(True)
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        self.content = QWidget()
        self.content.setObjectName("organizeContent")
        self.content.setMinimumWidth(0)
        self.content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setWidget(self.content)
        prepare_page_surface(self, self.content)
        self._build_ui()

        controller.analysis_completed.connect(self.on_analysis_complete)
        controller.analysis_cancelled.connect(self.on_analysis_cancelled)
        controller.analysis_failed.connect(self.on_analysis_error)
        controller.organize_finished.connect(self.on_organize_complete)
        controller.rollback_finished.connect(self.on_rollback_finished)
        controller.operation_state_changed.connect(self._sync_action_buttons)
        task_registry.tasks_updated.connect(self._update_progress)

        self.apply_saved_settings()
        self.refresh_profiles()
        active_profile = self.profile_manager.get_active_profile()
        if active_profile:
            self.profile_combo.setCurrentText(active_profile.name)
        self.refresh_saved_paths()
        self._sync_action_buttons()
        self.refresh_theme()

    # ================================================================ UI
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(16)
        self.page_header = PageHeader(
            "Organizar", "Analiza, revisa y organiza tus archivos con control antes de moverlos.")
        layout.addWidget(self.page_header)

        self.config_btn = PushButton(FluentIcon.SETTING, "Configurar")
        self.config_btn.setObjectName("organizeConfigAction")
        self.config_btn.setAccessibleName("Abrir configuración")
        self.config_btn.setToolTip("Categorías, extensiones, exclusiones y música (Ctrl+P)")
        self.config_btn.clicked.connect(lambda: self.open_configuration())
        self.task_center_btn = PushButton(FluentIcon.SYNC, "Tareas")
        self.task_center_btn.setObjectName("organizeTasksAction")
        self.task_center_btn.setAccessibleName("Abrir tareas")
        self.task_center_btn.setToolTip("Tareas en segundo plano, historial y registro")
        self.task_center_btn.clicked.connect(self.open_task_center)
        self.page_header.add_trailing_widget(self.config_btn)
        self.page_header.add_trailing_widget(self.task_center_btn)

        layout.addWidget(self._build_source_card())
        layout.addWidget(self._build_results_card(), 1)

    def _build_source_card(self) -> QWidget:
        card = GlassCard()
        card.setObjectName("organizeSourceCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.source_card = card
        source = QVBoxLayout(card)
        source.setContentsMargins(20, 16, 20, 16)
        source.setSpacing(12)

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.addWidget(SubtitleLabel("Carpeta de origen"))
        hint = CaptionLabel("Elige una carpeta (o arrástrala aquí) y pulsa Analizar. Nada se mueve sin revisarlo.")
        hint.setObjectName("organizeHint")
        hint.setWordWrap(True)
        title_row.addWidget(hint, 1)
        source.addLayout(title_row)

        path_row = ActionBar()
        self.folder_input = LineEdit()
        self.folder_input.setObjectName("organizeFolderInput")
        self.folder_input.setAccessibleName("Ruta de la carpeta que se va a organizar")
        self.folder_input.setPlaceholderText("Escribe o pega la ruta de la carpeta")
        self.folder_input.setClearButtonEnabled(True)
        self.folder_input.setMinimumWidth(180)
        bind_path_tooltip(self.folder_input)
        self.folder_input.textChanged.connect(self.on_folder_path_changed)
        self.folder_input.returnPressed.connect(self.start_analysis)
        path_row.content_layout.addWidget(self.folder_input, 1)
        self.browse_btn = PushButton(FluentIcon.FOLDER, "Examinar")
        self.browse_btn.setAccessibleName("Examinar carpetas")
        self.browse_btn.setToolTip("Selecciona la carpeta que quieres analizar (Ctrl+O)")
        self.browse_btn.clicked.connect(self.browse_folder)
        path_row.content_layout.addWidget(self.browse_btn)
        self.add_favorite_btn = PushButton(FluentIcon.HEART, "Guardar favorito")
        self.add_favorite_btn.clicked.connect(self.add_current_path_to_favorites)
        path_row.content_layout.addWidget(self.add_favorite_btn)
        source.addWidget(path_row)

        recent_row = QHBoxLayout()
        recent_row.setSpacing(8)
        recent_label = BodyLabel("Recientes y favoritas")
        recent_row.addWidget(recent_label)
        self.path_memory_combo = ComboBox()
        self.path_memory_combo.setAccessibleName("Rutas recientes y favoritas")
        self.path_memory_combo.setPlaceholderText("Sin rutas guardadas")
        self.path_memory_combo.setMinimumWidth(220)
        self.path_memory_combo.setMaximumWidth(560)
        self.path_memory_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.path_memory_combo.currentIndexChanged.connect(lambda _index: self.use_selected_saved_path())
        recent_label.setBuddy(self.path_memory_combo)
        recent_row.addWidget(self.path_memory_combo, 1)
        recent_row.addStretch()
        source.addLayout(recent_row)

        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        self.move_folders_checkbox = CheckBox("Mover carpetas completas")
        self.move_folders_checkbox.setChecked(True)
        self.move_folders_checkbox.setToolTip(
            "Las carpetas cuyo contenido es de una sola categoría se mueven enteras")
        options_row.addWidget(self.move_folders_checkbox)
        self.organize_by_date_checkbox = CheckBox("Organizar por fecha")
        self.organize_by_date_checkbox.setToolTip("Crea subcarpetas por año y mes dentro de cada categoría")
        options_row.addWidget(self.organize_by_date_checkbox)
        options_row.addStretch()
        self.advanced_mode_toggle = TransparentPushButton(FluentIcon.DOWN, "Opciones avanzadas")
        self.advanced_mode_toggle.setCheckable(True)
        self.advanced_mode_toggle.setAccessibleName("Mostrar opciones avanzadas")
        self.advanced_mode_toggle.setToolTip("Similitud, tamaño mínimo, perfiles, duplicados, conflictos y exclusiones")
        self.advanced_mode_toggle.toggled.connect(self.on_advanced_mode_toggled)
        options_row.addWidget(self.advanced_mode_toggle)
        self.analyze_btn = PrimaryPushButton(FluentIcon.SEARCH, "Analizar")
        self.analyze_btn.setObjectName("analyze_button")
        self.analyze_btn.setAccessibleName("Analizar la carpeta")
        self.analyze_btn.setToolTip("Analiza el contenido de la carpeta (Ctrl+R o F5)")
        self.analyze_btn.setMinimumWidth(112)
        self.analyze_btn.clicked.connect(self.start_analysis)
        options_row.addWidget(self.analyze_btn)
        source.addLayout(options_row)

        source.addWidget(self._build_advanced_panel())
        source.addWidget(self._build_progress_panel())
        return card

    def _build_advanced_panel(self) -> QWidget:
        self.advanced_controls = QWidget()
        self.advanced_controls.setObjectName("organizeAdvanced")
        grid = QGridLayout(self.advanced_controls)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        grid.addWidget(BodyLabel("Similitud mínima"), 0, 0)
        self.similarity_spinbox = SpinBox()
        self.similarity_spinbox.setAccessibleName("Similitud mínima para mover una carpeta completa")
        self.similarity_spinbox.setRange(0, 100)
        self.similarity_spinbox.setValue(70)
        self.similarity_spinbox.setSuffix(" %")
        self.similarity_spinbox.setMinimumWidth(150)
        self.similarity_spinbox.setToolTip("Porcentaje de archivos de una categoría para mover la carpeta entera")
        grid.addWidget(self.similarity_spinbox, 0, 1)
        grid.addWidget(BodyLabel("Tamaño mínimo"), 0, 2)
        self.min_size_spinbox = SpinBox()
        self.min_size_spinbox.setAccessibleName("Tamaño mínimo de archivo")
        self.min_size_spinbox.setRange(0, 10240)
        self.min_size_spinbox.setSuffix(" MB")
        self.min_size_spinbox.setMinimumWidth(150)
        self.min_size_spinbox.setToolTip("Los archivos más pequeños no se tienen en cuenta")
        grid.addWidget(self.min_size_spinbox, 0, 3, Qt.AlignmentFlag.AlignLeft)

        grid.addWidget(BodyLabel("Perfil"), 1, 0)
        self.profile_combo = ComboBox()
        self.profile_combo.setAccessibleName("Perfil de organización")
        self.profile_combo.setPlaceholderText("Sin perfiles")
        self.profile_combo.setMinimumWidth(260)
        grid.addWidget(self.profile_combo, 1, 1)
        profile_actions = ActionBar()
        self.load_profile_btn = PushButton(FluentIcon.DOWNLOAD, "Cargar")
        self.load_profile_btn.setAccessibleName("Cargar el perfil seleccionado")
        self.load_profile_btn.clicked.connect(self.load_selected_profile)
        profile_actions.content_layout.addWidget(self.load_profile_btn)
        self.save_profile_btn = PushButton(FluentIcon.SAVE, "Guardar perfil")
        self.save_profile_btn.clicked.connect(self.save_current_profile)
        profile_actions.content_layout.addWidget(self.save_profile_btn)
        profile_actions.content_layout.addStretch()
        grid.addWidget(profile_actions, 1, 2, 1, 3)

        grid.addWidget(BodyLabel("Si el destino existe"), 2, 0)
        self.conflict_policy_combo = ComboBox()
        self.conflict_policy_combo.setAccessibleName("Qué hacer si el destino ya existe")
        self.conflict_policy_combo.setMinimumWidth(260)
        for label, policy in CONFLICT_CHOICES:
            self.conflict_policy_combo.addItem(label, userData=policy)
        self.conflict_policy_combo.currentIndexChanged.connect(self._on_conflict_policy_changed)
        grid.addWidget(self.conflict_policy_combo, 2, 1)
        safety = ActionBar()
        self.check_duplicates_checkbox = CheckBox("Buscar duplicados")
        self.check_duplicates_checkbox.setChecked(True)
        self.check_duplicates_checkbox.setToolTip("Omite las copias exactas que ya estén en el destino")
        safety.content_layout.addWidget(self.check_duplicates_checkbox)
        self.manage_exclusions_btn = PushButton(FluentIcon.REMOVE_FROM, "Exclusiones y rutas protegidas")
        self.manage_exclusions_btn.setToolTip("Extensiones y carpetas que nunca se analizan ni se mueven")
        self.manage_exclusions_btn.clicked.connect(self.open_exclusions_configuration)
        safety.content_layout.addWidget(self.manage_exclusions_btn)
        safety.content_layout.addStretch()
        grid.addWidget(safety, 2, 2, 1, 3)
        grid.setColumnStretch(4, 1)
        self.advanced_controls.setVisible(False)
        return self.advanced_controls

    def _build_progress_panel(self) -> QWidget:
        self.progress_panel = QWidget()
        self.progress_panel.setObjectName("organizeProgress")
        row = QHBoxLayout(self.progress_panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        column = QVBoxLayout()
        column.setSpacing(6)
        self.progress_label = BodyLabel("")
        self.progress_label.setObjectName("organizeProgressLabel")
        self.progress_label.setWordWrap(False)
        self.progress_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        column.addWidget(self.progress_label)
        self.progress_bar = IndeterminateProgressBar(start=False)
        self.progress_bar.setAccessibleName("Progreso de la operación")
        column.addWidget(self.progress_bar)
        row.addLayout(column, 1)
        self.cancel_btn = PushButton(FluentIcon.CANCEL, "Cancelar")
        self.cancel_btn.setAccessibleName("Cancelar la operación en curso")
        self.cancel_btn.setToolTip("Se detiene de forma segura; lo ya movido se puede deshacer")
        self.cancel_btn.clicked.connect(self.cancel_operation)
        row.addWidget(self.cancel_btn)
        self.progress_panel.setVisible(False)
        return self.progress_panel

    def _build_results_card(self) -> QWidget:
        card = GlassCard()
        card.setObjectName("organizeResultsCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.results_card = card
        results = QVBoxLayout(card)
        results.setContentsMargins(20, 16, 20, 16)
        results.setSpacing(12)

        # Cabecera: título, resumen por categoría y las acciones (siempre a la vista)
        header = ActionBar()
        header.content_layout.setSpacing(12)
        header.content_layout.addWidget(SubtitleLabel("Resultados"))
        self.stats_label = CaptionLabel("Sin análisis")
        self.stats_label.setObjectName("stats_label")
        self.stats_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        header.content_layout.addWidget(self.stats_label, 1)
        self.rollback_btn = PushButton(FluentIcon.RETURN, "Deshacer")
        self.rollback_btn.setAccessibleName("Deshacer la última organización")
        self.rollback_btn.setToolTip("Revierte la última organización completada")
        self.rollback_btn.clicked.connect(self.rollback_last_operation)
        header.content_layout.addWidget(self.rollback_btn)
        self.organize_btn = PrimaryPushButton(FluentIcon.ACCEPT, "Revisar y organizar")
        self.organize_btn.setObjectName("organize_button")
        self.organize_btn.setToolTip("Revisa y organiza los elementos seleccionados (Ctrl+S)")
        self.organize_btn.setMinimumWidth(176)
        self.organize_btn.clicked.connect(self.start_organization)
        header.content_layout.addWidget(self.organize_btn)
        results.addWidget(header)

        self.filter_bar = FilterBar(sorted(self.category_manager.get_categories().keys()), self.content)
        self.filter_bar.layout().setContentsMargins(0, 0, 0, 0)
        self.filter_bar.filter_changed.connect(self._on_filter_changed)
        self.filter_bar.select_all_requested.connect(self.select_all_items)
        self.filter_bar.deselect_all_requested.connect(self.deselect_all_items)
        self.filter_bar.embed_selection_bar(inline=True)
        self.select_all_btn = self.filter_bar.select_all_btn
        self.deselect_all_btn = self.filter_bar.deselect_all_btn
        self.select_all_btn.setToolTip("Marca todos los elementos (Ctrl+A)")
        self.deselect_all_btn.setToolTip("Desmarca todos los elementos (Ctrl+D)")
        self.filter_bar.search_input.setToolTip("Filtra por nombre (Ctrl+F)")
        self.selection_count_label = self.filter_bar.selection_count_label
        results.addWidget(self.filter_bar)

        self.movements_model = VirtualizedMovementsModel(parent=self)
        self.movements_table = support.MovementsTable(
            self.movements_model, typography_scale(self.config).row_height)
        self.movements_table.customContextMenuRequested.connect(self.show_context_menu)
        self.movements_table.doubleClicked.connect(self.on_table_double_clicked)
        self.movements_table.horizontalHeader().sectionClicked.connect(self.on_header_clicked)
        self.movements_model.dataChanged.connect(self.on_model_data_changed)
        results.addWidget(self.movements_table, 1)

        self.results_empty_state = EmptyState(FluentIcon.FOLDER, EMPTY_TEXT, "Elegir carpeta", primary=False)
        self.results_empty_state.setMinimumHeight(200)
        self.results_empty_state.action_requested.connect(self.browse_folder)
        results.addWidget(self.results_empty_state, 1)
        return card

    def refresh_theme(self, _config=None) -> None:
        """Casillas y selección de la tabla con el acento del tema."""
        accent = self.config.get_accent_color()
        light = current_tokens(accent, "light").accent
        dark = current_tokens(accent, "dark").accent
        self.movements_table.setCheckedColor(light, dark)
        self.progress_bar.setCustomBarColor(light, dark)

    # ===================================================== diálogos / avisos
    def _dialog_parent(self) -> QWidget:
        """Los diálogos se centran sobre la ventana visible."""
        window = self.window()
        return window if window is not None and window.isVisible() else self

    def _ask(self, title: str, content: str, yes_text: str = "Sí", no_text: str = "No") -> bool:
        return ask(self._dialog_parent(), title, content, yes_text, no_text)

    def _alert(self, title: str, content: str) -> None:
        alert(self._dialog_parent(), title, content)

    def _notify(self, level: str, title: str, content: str) -> None:
        notify(self._dialog_parent(), level, title, content)

    def log_message(self, message) -> None:
        """Añade un mensaje al registro (en lotes, vía el controlador)."""
        self.controller.log(message)

    # ====================================================== carpeta de origen
    def on_advanced_mode_toggled(self, checked: bool) -> None:
        """Muestra u oculta las opciones avanzadas y persiste el estado."""
        self.advanced_controls.setVisible(checked)
        self.advanced_mode_toggle.setText("Ocultar opciones avanzadas" if checked else "Opciones avanzadas")
        self.advanced_mode_toggle.setIcon(FluentIcon.UP if checked else FluentIcon.DOWN)
        self.advanced_mode_toggle.setAccessibleName(
            "Ocultar opciones avanzadas" if checked else "Mostrar opciones avanzadas")
        if checked != self.config.get_ui_advanced_mode():
            self.config.set_ui_advanced_mode(checked)

    def apply_saved_settings(self) -> None:
        """Restaura similitud, tamaño mínimo, conflictos y opciones avanzadas."""
        self.similarity_spinbox.setValue(self.config.get_min_similarity())
        self.min_size_spinbox.setValue(self.config.get_min_file_size_mb())
        index = self.conflict_policy_combo.findData(self.config.get_organization_conflict_policy())
        self.conflict_policy_combo.blockSignals(True)
        self.conflict_policy_combo.setCurrentIndex(max(0, index))
        self.conflict_policy_combo.blockSignals(False)
        advanced_mode = self.config.get_ui_advanced_mode()
        self.advanced_mode_toggle.blockSignals(True)
        self.advanced_mode_toggle.setChecked(advanced_mode)
        self.advanced_mode_toggle.blockSignals(False)
        self.on_advanced_mode_toggled(advanced_mode)
        self.update_favorite_button_state()

    def _on_conflict_policy_changed(self, _index: int) -> None:
        policy = self.conflict_policy_combo.currentData()
        if policy and policy != self.config.get_organization_conflict_policy():
            self.config.set_organization_conflict_policy(policy)

    def update_favorite_button_state(self) -> None:
        path = self.folder_input.text().strip()
        is_favorite = bool(path) and path in self.config.get_favorite_paths()
        self.add_favorite_btn.setText("Quitar favorito" if is_favorite else "Guardar favorito")
        self.add_favorite_btn.setEnabled(bool(path))
        self.add_favorite_btn.setToolTip(
            "Quitar ruta actual de favoritos" if is_favorite else "Guardar ruta actual en favoritos")
        self.add_favorite_btn.setAccessibleName(self.add_favorite_btn.toolTip())

    def refresh_saved_paths(self) -> None:
        """Actualiza el selector de favoritas (★) y recientes."""
        current = self.path_memory_combo.currentData()
        self.path_memory_combo.blockSignals(True)
        self.path_memory_combo.clear()
        for path in self.config.get_favorite_paths():
            self.path_memory_combo.addItem(f"★ {path}", userData=path)
        for path in self.config.get_recent_paths():
            if self.path_memory_combo.findData(path) == -1:
                self.path_memory_combo.addItem(path, userData=path)
        index = self.path_memory_combo.findData(current) if current else -1
        # Sin elegir nada por defecto: elegir una ruta la carga en el campo
        self.path_memory_combo.setCurrentIndex(index)
        self.path_memory_combo.setToolTip(current or "Rutas favoritas (★) y recientes")
        has_paths = self.path_memory_combo.count() > 0
        self.path_memory_combo.setPlaceholderText("Elige una ruta guardada" if has_paths else "Sin rutas guardadas")
        self.path_memory_combo.setEnabled(has_paths)
        self.path_memory_combo.blockSignals(False)
        self.update_favorite_button_state()

    def use_selected_saved_path(self) -> None:
        path = self.path_memory_combo.currentData()
        if path:
            self.path_memory_combo.setToolTip(path)
            self.folder_input.setText(path)

    def add_current_path_to_favorites(self) -> None:
        """Añade o quita la ruta actual de favoritos."""
        path = self.folder_input.text().strip()
        if not path:
            return
        if path in self.config.get_favorite_paths():
            self.config.remove_favorite_path(path)
            self.log_message(f"Ruta eliminada de favoritas: {path}")
        else:
            self.config.add_favorite_path(path)
            self.log_message(f"Ruta añadida a favoritas: {path}")
        self.refresh_saved_paths()

    def browse_folder(self) -> None:
        start = self.folder_input.text().strip()
        folder_path = QFileDialog.getExistingDirectory(
            self._dialog_parent(), "Seleccionar carpeta para organizar", start if os.path.isdir(start) else "")
        if folder_path:
            self.folder_input.setText(folder_path)
            self.config.push_recent_path(folder_path)
            self.refresh_saved_paths()

    def set_folder(self, folder_path: str) -> None:
        self.folder_input.setText(folder_path)

    def analyze_folder(self, folder_path: str) -> None:
        """Fija la carpeta y la analiza (Inicio, arrastrar y soltar, Uso del espacio)."""
        self.folder_input.setText(folder_path)
        self.start_analysis()

    def on_folder_path_changed(self, text: str) -> None:
        self.update_favorite_button_state()
        self.update_selection_count()
        path = text.strip()
        if path and os.path.exists(path) and self.config.get_auto_analyze():
            # Pequeño retraso para no analizar mientras se escribe
            self._auto_analysis_timer.start(self.AUTO_ANALYSIS_DELAY_MS)

    # ============================================================ análisis
    def start_analysis(self) -> None:
        """Valida la carpeta y lanza el análisis en el controlador."""
        self._auto_analysis_timer.stop()
        if self.controller.busy:
            return
        folder_path = self.folder_input.text().strip()
        if not folder_path:
            self._notify("warning", "Elige una carpeta", "Selecciona una carpeta para analizar.")
            self.folder_input.setFocus()
            return
        if not os.path.exists(folder_path):
            self._notify("warning", "Carpeta no encontrada", "La carpeta seleccionada no existe.")
            return
        if not os.path.isdir(folder_path):
            self._notify("warning", "No es una carpeta", "El elemento seleccionado no es una carpeta.")
            return

        self._analysis_folder_path = os.path.normcase(os.path.realpath(folder_path))
        self._analysis_result_path = None
        self.folder_movements = []
        self.file_movements = []
        self.movements_model.clear_data()
        if self.similarity_spinbox.value() != self.config.get_min_similarity():
            self.config.set_min_similarity(self.similarity_spinbox.value())
        if self.min_size_spinbox.value() != self.config.get_min_file_size_mb():
            self.config.set_min_file_size_mb(self.min_size_spinbox.value())
        self.config.push_recent_path(folder_path)
        self.refresh_saved_paths()
        self.log_message(f"🔍 Iniciando análisis de: {folder_path}")
        try:
            started = self.controller.start_analysis(
                folder_path,
                self.category_manager.get_categories(),
                self.category_manager.ext_to_categoria,
                self.similarity_spinbox.value(),
                min_file_size_mb=self.min_size_spinbox.value(),
                ignored_extensions=self.config.get_ignored_extensions(),
                ignored_paths=list(self.config.get_ignored_paths()) + list(self._profile_exclusions),
                category_manager=self.category_manager,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            message = f"❌ Error al iniciar el análisis: {exc}"
            self.log_message(message)
            self._alert("Error de análisis", message)
            started = None
        if started:
            self.progress_label.setText(f"Analizando {folder_path}…")
        self._sync_action_buttons()

    def on_analysis_complete(self, folder_movements, file_movements, stats) -> None:
        self.folder_movements = folder_movements
        self.file_movements = file_movements
        self._analysis_result_path = self._analysis_folder_path
        self.populate_results_table()
        total_items = len(folder_movements) + len(file_movements)
        self.log_message(f"✅ Análisis completado: {total_items} elementos encontrados")
        self.filter_bar.update_categories(sorted({mov["category"] for mov in folder_movements + file_movements}))
        if stats:
            self.log_message(
                f"📊 Estadísticas: {stats.get('total_folders', 0)} carpetas, {stats.get('total_files', 0)} archivos")
        self._sync_action_buttons()

    def on_analysis_cancelled(self) -> None:
        """El usuario canceló el análisis: la interfaz queda sin resultados."""
        self._sync_action_buttons()

    def on_analysis_error(self, error_message: str) -> None:
        self._sync_action_buttons()
        self._alert("Error de análisis", error_message)

    def populate_results_table(self) -> None:
        """Llena la tabla virtualizada con los resultados del análisis."""
        rows = support.build_model_rows(self.folder_movements, self.file_movements)
        self.movements_model.clear_data()
        self.movements_model.update_data(rows)
        # resetModel() puede cambiar los anchos: se vuelven a aplicar
        self.movements_table.apply_column_widths()
        self.log_message(f"Tabla de resultados con {len(rows)} elementos")
        self.update_statistics()
        self.update_selection_count()

    # =========================================================== selección
    def select_all_items(self) -> None:
        self.movements_model.check_all()
        self.update_selection_count()

    def deselect_all_items(self) -> None:
        self.movements_model.uncheck_all()
        self.update_selection_count()

    def on_model_data_changed(self, _top_left, _bottom_right, roles) -> None:
        if Qt.ItemDataRole.CheckStateRole in roles:
            self.update_selection_count()

    def on_table_double_clicked(self, index) -> None:
        """Doble clic: expande o contrae un grupo de archivos sueltos."""
        if not index.isValid():
            return
        row_data = self.movements_model.get_row_data(index.row())
        if row_data and row_data.get("is_group", False):
            self.toggle_file_group_expansion(index.row())

    def toggle_file_group_expansion(self, group_row: int) -> None:
        model = self.movements_model
        if group_row >= model.rowCount() or not model.is_group_row(group_row):
            return
        if model.get_row_data(group_row).get("is_expanded", False):
            model.collapse_group(group_row)
        else:
            model.expand_group(group_row)

    def _matches_analysis(self) -> bool:
        path = self.folder_input.text().strip()
        return (bool(path) and os.path.isdir(path)
                and os.path.normcase(os.path.realpath(path)) == self._analysis_result_path)

    def update_selection_count(self) -> None:
        """Resumen de selección y estado de «Revisar y organizar»."""
        if not hasattr(self, "movements_model"):
            return
        model = self.movements_model
        total_count = sum(1 for row in range(model.rowCount())
                          if not (model.get_row_data(row) or {}).get("is_child", False))
        selected_count, selected_size, selected_files = support.selection_totals(model)
        enabled = selected_count > 0 and self._matches_analysis() and not self.controller.busy
        self.organize_btn.setEnabled(enabled)
        self.filter_bar.update_selection_summary(
            selected_count, total_count, format_bytes(selected_size), f"{selected_files:,} archivos")
        self.filter_bar.update_count(model.get_visible_count())
        self._update_results_empty_state(total_count)

    def _update_results_empty_state(self, total_count: int) -> None:
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
            self.results_empty_state.set_text(EMPTY_TEXT)
            self.results_empty_state.set_action("Elegir carpeta")

    def update_statistics(self) -> None:
        """Resumen por categoría (visible) y detalle accesible (tooltip)."""
        summary, detail = support.category_breakdown(
            self.folder_movements, self.file_movements, self.category_manager.get_categories())
        self.stats_label.setText(summary)
        self.stats_label.setToolTip(detail)
        self.stats_label.setAccessibleDescription(detail.replace("<br/>", "\n"))

    def get_selected_movements(self):
        """Carpetas y archivos marcados en la tabla."""
        return support.selected_movements(self.movements_model)

    def _get_effective_selected_movements(self):
        folder_movements, file_movements = self.get_selected_movements()
        if not self.move_folders_checkbox.isChecked():
            folder_movements = []
            self.log_message("ℹ️ Modo: solo archivos sueltos (carpetas ignoradas)")
        else:
            self.log_message("ℹ️ Modo: carpetas completas y archivos sueltos")
        return folder_movements, file_movements

    def _on_filter_changed(self, search_text: str, category: str) -> None:
        self.movements_model.set_filter(search_text, category)
        self.update_selection_count()

    def on_header_clicked(self, logical_index: int) -> None:
        """Ordena por la columna pulsada; un segundo clic invierte el orden."""
        if logical_index not in support.SORTABLE_COLUMNS:
            return
        sort_info = self.movements_model.get_sort_info()
        if sort_info["column"] == logical_index and sort_info["order"] == Qt.SortOrder.AscendingOrder:
            new_order = Qt.SortOrder.DescendingOrder
        else:
            new_order = Qt.SortOrder.AscendingOrder
        self.movements_model.sort(logical_index, new_order)
        self.movements_table.horizontalHeader().setSortIndicator(logical_index, new_order)
        self.movements_table.apply_column_widths()
        self.update_selection_count()

    # ------------------------------------------------------ menú contextual
    def build_context_menu(self, row: int) -> RoundMenu | None:
        """Acciones de una fila: abrir en el Explorador y expandir o contraer."""
        model = self.movements_model
        row_data = model.get_row_data(row) or {}
        menu = RoundMenu(parent=self.movements_table)
        menu.setObjectName("organizeContextMenu")
        if row_data.get("type") == "folder":
            location = str((row_data.get("original_data") or {}).get("folder") or "")
        elif row_data.get("type") == "file_item":
            location = os.path.dirname(row_data.get("original_file") or "")
        else:
            location = self.folder_input.text().strip()
        if location:
            menu.addAction(Action(FluentIcon.FOLDER, "Abrir en el Explorador",
                                  triggered=lambda: self.open_file_location(location)))
        if row_data.get("is_group", False):
            if row_data.get("is_expanded", False):
                menu.addAction(Action(FluentIcon.UP, "Contraer grupo", triggered=lambda: model.collapse_group(row)))
            else:
                menu.addAction(Action(FluentIcon.DOWN, "Expandir grupo", triggered=lambda: model.expand_group(row)))
        if not row_data.get("is_child", False):
            checked = model.data(model.index(row, 0), Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            menu.addSeparator()
            menu.addAction(Action(
                FluentIcon.CLEAR_SELECTION if checked else FluentIcon.CHECKBOX,
                "Desmarcar" if checked else "Marcar",
                triggered=lambda: model.setData(
                    model.index(row, 0), Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
                    Qt.ItemDataRole.CheckStateRole)))
        return menu if menu.actions() else None

    def show_context_menu(self, position) -> None:
        index = self.movements_table.indexAt(position)
        if not index.isValid():
            return
        menu = self.build_context_menu(index.row())
        if menu is not None:
            menu.exec(self.movements_table.viewport().mapToGlobal(position))

    def open_file_location(self, folder_path: str) -> None:
        from src.utils.paths import open_in_file_manager

        if not open_in_file_manager(folder_path):
            self._notify("warning", "No se pudo abrir", f"No se pudo abrir la ubicación:\n{folder_path}")

    # =========================================================== organizar
    def open_selection_preview(self) -> None:
        """Único flujo de revisión y confirmación."""
        self.start_organization()

    def start_organization(self) -> None:
        """Revisa la selección (vista previa) y lanza la organización."""
        if self._organization_review_open or self.controller.busy:
            return
        folder_path = self.folder_input.text().strip()
        if not self._matches_analysis():
            self._notify("warning", "Analiza la carpeta actual",
                         "La selección corresponde a otra carpeta o la ruta ya no está disponible. "
                         "Analiza la carpeta actual antes de revisar.")
            return
        selected_folder_movements, selected_file_movements = self._get_effective_selected_movements()
        if not selected_folder_movements and not selected_file_movements:
            self._notify("warning", "Nada seleccionado", "No hay elementos seleccionados para organizar.")
            return

        # Una única traducción categoría → carpeta para vista previa y worker
        category_folder = getattr(self.category_manager, "get_category_folder", None)
        folder_names_getter = getattr(self.category_manager, "get_category_folder_names", None)
        category_folder_names = folder_names_getter() if callable(folder_names_getter) else None
        organize_by_date = self.organize_by_date_checkbox.isChecked()
        check_duplicates = self.check_duplicates_checkbox.isChecked()

        preview = PreviewDialog(
            selected_folder_movements,
            selected_file_movements,
            folder_path,
            self._dialog_parent(),
            organize_by_date=organize_by_date,
            check_duplicates=check_duplicates,
            conflict_policy=self.config.get_organization_conflict_policy(),
            category_folder=category_folder,
            category_folder_names=category_folder_names,
        )
        self._organization_review_open = True
        try:
            accepted = bool(preview.exec())
        finally:
            self._organization_review_open = False
        if not accepted:
            self.log_message("Organización cancelada en la vista previa")
            return

        # Rutas protegidas del usuario + exclusiones del perfil activo
        protected_paths = list(self.config.get_protected_paths()) + list(self._profile_exclusions)
        started = self.controller.start_organization(
            folder_path,
            selected_folder_movements,
            selected_file_movements,
            organize_by_date=organize_by_date,
            check_duplicates=check_duplicates,
            protected_paths=protected_paths,
            conflict_policy=preview.get_conflict_policy(),
            plan=preview.get_plan(),
            category_folder=category_folder,
        )
        if started:
            self.progress_label.setText("Organizando los elementos seleccionados…")
        self._sync_action_buttons()

    def on_organize_complete(self, success: bool, message: str) -> None:
        """Fin de la organización: resumen y refresco de resultados.

        ``success`` solo es True si todo se completó; el estado real
        (cancelado, completado con errores, error) viene en el resumen.
        """
        summary = self.controller.last_operation_summary or {}
        status = summary.get("status", "completado" if success else "error")
        transaction_id = summary.get("transaction_id")
        moved = summary.get("files_moved", 0) + summary.get("folders_moved", 0)
        self._sync_action_buttons()
        if status in ("completado", "completado con errores", "cancelado"):
            self.log_message(("✅ " if success else "⚠️ ") + message)
            if summary:
                undo = None
                if status != "completado" and transaction_id and moved:
                    # Ofrecer deshacer lo que sí se movió (cancelación o errores)
                    undo = lambda txn=transaction_id: self.rollback_transaction(txn, confirm=False)
                self.show_summary(summary, undo)
            if self.controller.current_rollback_task_id is None:
                self._schedule_post_organization_refresh()
        else:
            self.log_message("❌ " + message)
            self._alert("Error de organización", message)

    def show_summary(self, summary: dict, undo_callback=None) -> None:
        from src.gui.operation_summary_dialog import OperationSummaryDialog

        OperationSummaryDialog(summary, self._dialog_parent(), undo_callback=undo_callback).exec()

    def _schedule_post_organization_refresh(self) -> None:
        """Relanza el análisis para reflejar el estado real tras organizar."""
        folder_path = self.folder_input.text().strip()
        if not folder_path or not os.path.isdir(folder_path):
            self.log_message("⚠️ No se pudo refrescar automáticamente: la ruta actual ya no es válida")
            return
        self.log_message("🔄 Refrescando resultados tras la organización...")
        QTimer.singleShot(self.REFRESH_DELAY_MS, self.start_analysis)

    def cancel_operation(self) -> None:
        """Detiene de forma segura el análisis o la organización en curso."""
        if self.controller.cancel_active():
            self.progress_label.setText("Cancelando… se termina el elemento actual.")
        self._sync_action_buttons()

    # ============================================================ deshacer
    def rollback_last_operation(self) -> None:
        """Revierte la última organización que aún se puede deshacer."""
        if self.controller.current_organize_task_id or self.controller.current_rollback_task_id:
            return
        transaction_id = self.controller.refresh_last_transaction()
        if not transaction_id:
            self._notify("info", "Sin historial", "No hay una organización reciente para deshacer.")
            return
        self.rollback_transaction(transaction_id)

    def rollback_transaction(self, transaction_id: str, confirm: bool = True) -> bool:
        """Pide confirmación y deshace una transacción en segundo plano."""
        if not transaction_id or self.controller.current_organize_task_id or self.controller.current_rollback_task_id:
            return False
        if confirm:
            is_last = transaction_id == self.controller.last_transaction_id
            if not self._ask(
                "Deshacer última organización" if is_last else "Deshacer organización",
                "¿Quieres revertir la última organización completada?"
                if is_last else "¿Quieres revertir esta organización del historial?",
                "Deshacer", "Cancelar",
            ):
                return False
        if not self.controller.start_rollback(transaction_id):
            return False
        self.progress_label.setText("Deshaciendo la organización…")
        self._sync_action_buttons()
        return True

    def on_rollback_finished(self, _transaction_id: str, ok: bool, result: dict) -> None:
        """Muestra el resultado de deshacer y refresca los resultados."""
        self._sync_action_buttons()
        if result.get("already_reverted"):
            self._notify("info", "Ya deshecha", "Esta organización ya se había deshecho; no se ha repetido.")
            return
        if ok:
            extra = ""
            if result.get("renamed"):
                extra = (f" {len(result['renamed'])} elementos se restauraron con otro nombre "
                         "porque su ubicación original estaba ocupada.")
            self._notify("success", "Organización deshecha", "Los cambios se han revertido." + extra)
        else:
            self._alert("Deshacer incompleto",
                        "No se pudieron revertir todos los cambios. Revisa el registro en Actividad.")
        self._schedule_post_organization_refresh()

    # ======================================================= estado / botones
    def _sync_action_buttons(self) -> None:
        """Habilita Analizar, Organizar y Deshacer según el estado del controlador."""
        controller = self.controller
        self.analyze_btn.setEnabled(not controller.busy)
        self.rollback_btn.setEnabled(bool(controller.last_transaction_id)
                                     and not controller.current_organize_task_id
                                     and not controller.current_rollback_task_id)
        self.organize_btn.setText("Organizando…" if controller.current_organize_task_id else "Revisar y organizar")
        self._update_progress()
        self.update_selection_count()

    def _update_progress(self) -> None:
        """Barra indeterminada, último mensaje del worker y Cancelar."""
        task_id = self.controller.active_task_id
        busy = bool(task_id)
        if busy:
            task = task_registry.get_task(task_id) or {}
            message = task.get("last_message")
            if message:
                self.progress_label.setText(message)
            if task.get("status") == "Cancelación solicitada":
                self.progress_label.setText("Cancelando… se termina el elemento actual.")
            self.progress_label.setToolTip(self.progress_label.text())
        self.cancel_btn.setEnabled(self.controller.can_cancel())
        self.cancel_btn.setVisible(not self.controller.current_rollback_task_id)
        if busy != self.progress_panel.isVisible():
            self.progress_panel.setVisible(busy)
            if busy:
                self.progress_bar.start()
            else:
                self.progress_bar.stop()
                self.progress_label.setText("")

    # ============================================================ perfiles
    def refresh_profiles(self) -> None:
        current = self.profile_combo.currentText()
        self.profile_combo.clear()
        self.profile_combo.addItems(self.profile_manager.get_profile_names())
        index = self.profile_combo.findText(current)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)
        has_profiles = self.profile_combo.count() > 0
        self.profile_combo.setEnabled(has_profiles)
        self.load_profile_btn.setEnabled(has_profiles)

    def load_selected_profile(self) -> None:
        """Aplica el perfil seleccionado a la página."""
        profile = self.profile_manager.get_profile(self.profile_combo.currentText().strip())
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
        self._profile_exclusions = [str(path) for path in (profile.exclude_patterns or []) if str(path).strip()]
        self.log_message(f"🧩 Perfil cargado: {profile.name}")
        self._notify("success", "Perfil cargado", profile.name)

    def _prompt_text(self, title: str, label: str, text: str) -> tuple[str, bool]:
        return TextPromptDialog.get_text(self._dialog_parent(), title, label, text)

    def save_current_profile(self) -> None:
        """Guarda el estado actual en un perfil."""
        current_name = self.profile_combo.currentText().strip()
        profile_name, ok = self._prompt_text("Guardar perfil", "Nombre del perfil", current_name or "Nuevo perfil")
        if not ok or not profile_name.strip():
            return
        normalized_name = profile_name.strip()
        profile = self.profile_manager.get_profile(normalized_name)
        if profile is None:
            profile = self.profile_manager.create_profile(normalized_name)
        if profile is None:
            self._alert("No se pudo guardar el perfil", "No se pudo crear el perfil.")
            return
        profile.folder_path = self.folder_input.text().strip()
        profile.move_folders = self.move_folders_checkbox.isChecked()
        profile.similarity_threshold = self.similarity_spinbox.value()
        profile.organize_by_date = self.organize_by_date_checkbox.isChecked()
        profile.exclude_patterns = list(self._profile_exclusions)
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
        self._notify("success", "Perfil guardado", profile.name)

    # ======================================================= configuración
    def open_configuration(self, focus_section: str | None = None) -> bool:
        """Configuración avanzada: categorías, extensiones, exclusiones y música."""
        from src.gui.config_dialog import ConfigDialog

        dialog = ConfigDialog(self._dialog_parent(), self.category_manager, app_config_ref=self.config,
                              focus_section=focus_section)
        if not dialog.exec():
            return False
        self.category_manager = dialog.category_manager
        self.filter_bar.update_categories(sorted(self.category_manager.get_categories().keys()))
        self.configuration_changed.emit()
        self._notify("success", "Configuración actualizada",
                     "Los cambios de categorías se aplicarán en el próximo análisis.")
        return True

    def open_exclusions_configuration(self) -> bool:
        return self.open_configuration("exclusions")

    def open_task_center(self) -> None:
        """Las tareas, el historial y el registro viven en Actividad."""
        self.activity_requested.emit()

    # =============================================================== cierre
    def request_shutdown(self, confirm: bool = True) -> bool:
        """Pide confirmación si hay una organización en curso y detiene los workers."""
        def ask() -> bool:
            return self._ask(
                "Organización en curso",
                "Hay una organización (o un deshacer) en curso.\n\n"
                "¿Detenerla de forma segura y salir? Lo que ya se haya movido "
                "quedará registrado en el historial y se podrá deshacer.",
                "Detener y salir", "Seguir",
            )

        return self.controller.request_shutdown(ask if confirm else None)
