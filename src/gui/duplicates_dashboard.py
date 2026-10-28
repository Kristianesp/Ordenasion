#!/usr/bin/env python3
"""
Dashboard de Gestión de Duplicados para el Organizador de Archivos.

La lógica está repartida en mixins:
- ``duplicates_columns``: anchos, orden y ordenación de columnas.
- ``duplicates_preview``: panel de detalle, vista previa y menú contextual.
- ``duplicates_actions_ui``: retirar, mover, hardlinks, conservar, ignorar y exportar.
"""

import html
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from PyQt6.QtCore import QPoint, QRect, QSettings, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyledItemDelegate,
    QTableView,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.duplicate_actions import choose_keep_index
from src.core.duplicate_finder import PARTIAL_HASH_LABEL, DuplicateScanWorker
from src.core.image_similarity import SimilarImagesWorker
from src.core.transaction_manager import TransactionManager
from src.gui.duplicates_actions_ui import DuplicatesActionsMixin
from src.gui.duplicates_columns import DuplicatesColumnsMixin
from src.gui.duplicates_preview import DuplicatesPreviewMixin
from src.gui.modern_components import TabHeaderWidget
from src.gui.table_models import PaginatedDuplicatesModel
from src.gui.task_center import TaskCenterDialog, task_registry
from src.gui.v2.theme import ElidedPathLabel, apply_control_sizes, apply_menu_surface, typography_scale
from src.utils.constants import DUPLICATE_METHODS
from src.utils.app_config import AppConfig, get_app_config
from src.utils.logger import debug
from src.utils.paths import user_data_file

METHODS = DUPLICATE_METHODS
METHOD_INFO = {
    "fast": "Candidatos por tamaño + nombre + extensión. Se confirman por hash antes de retirar.",
    "hybrid": "Filtro rápido + confirmación por hash de contenido (recomendado).",
    "deep": "Hash de contenido de todos los archivos del mismo tamaño (muestras si >5000 MB).",
    "similar": "Imágenes visualmente parecidas (dHash). No son copias exactas.",
}
SCAN_LABELS = {
    "fast": "Analizar (rápido)",
    "hybrid": "Analizar (híbrido)",
    "deep": "Analizar (profundo)",
    "similar": "Buscar imágenes parecidas",
}


class CheckboxDelegate(QStyledItemDelegate):
    """Delegado para checkboxes centrados con los colores del tema actual."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_table = parent

    def paint(self, painter, option, index):
        if not index.isValid():
            return
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        painter.save()
        try:
            self.paint_custom_checkbox(painter, self.get_checkbox_rect(option.rect), checked,
                                       self.get_theme_colors())
        finally:
            painter.restore()

    def get_theme_colors(self):
        """Colores del sistema de diseño actual (sin leer la configuración en cada pintado)."""
        try:
            from src.gui.v2.theme import current_tokens

            tokens = current_tokens()
            return {
                "primary": tokens.accent,
                "border": tokens.stroke,
                "success": tokens.success,
                "text_primary": tokens.text_primary,
                "background": tokens.canvas,
                "surface": tokens.surface_alt,
            }
        except (ImportError, AttributeError) as exc:
            debug(f"CheckboxDelegate: tokens no disponibles ({exc})")
            return {"primary": "#0078D4", "border": "#8a8a8a", "success": "#2e7d32",
                    "text_primary": "#202020", "background": "#ffffff", "surface": "#f3f3f3"}

    def paint_custom_checkbox(self, painter, rect, checked, colors):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(rect, QColor(colors["background"]))
        pen = painter.pen()
        pen.setWidth(2)
        if checked:
            painter.fillRect(rect, QColor(colors["success"]))
            pen.setColor(QColor(colors["success"]))
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            pen.setWidth(3)
            pen.setColor(QColor("white"))
            painter.setPen(pen)
            cx = rect.x() + rect.width() // 2
            cy = rect.y() + rect.height() // 2
            size = min(rect.width(), rect.height()) // 3
            painter.drawPolyline([
                QPoint(cx - size // 2, cy),
                QPoint(cx - size // 4, cy + size // 2),
                QPoint(cx + size // 2, cy - size // 2),
            ])
        else:
            pen.setColor(QColor(colors["primary"]))
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def get_checkbox_rect(self, cell_rect):
        checkbox_size = 20
        x = cell_rect.x() + (cell_rect.width() - checkbox_size) // 2
        y = cell_rect.y() + (cell_rect.height() - checkbox_size) // 2
        return QRect(x, y, checkbox_size, checkbox_size)

    def editorEvent(self, event, model, option, index):
        if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if self.get_checkbox_rect(option.rect).contains(event.pos()):
                current_state = index.data(Qt.ItemDataRole.CheckStateRole)
                new_state = (Qt.CheckState.Unchecked if current_state == Qt.CheckState.Checked
                             else Qt.CheckState.Checked)
                model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
                return True
        return False

    def sizeHint(self, option, index):
        return QSize(60, 40)


def _format_bytes(size: int) -> str:
    if size >= 1024 ** 3:
        return f"{size / (1024 ** 3):.1f} GB"
    if size >= 1024 ** 2:
        return f"{size / (1024 ** 2):.1f} MB"
    return f"{size / 1024:.1f} KB"


class DuplicatesDashboard(DuplicatesColumnsMixin, DuplicatesPreviewMixin, DuplicatesActionsMixin, QWidget):
    """Dashboard principal para gestión de duplicados"""

    status_update = pyqtSignal(str)
    analysis_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.duplicates_data: Dict[str, List[Path]] = {}
        self.group_meta: Dict[str, Dict[str, Any]] = {}
        self.file_info: Dict[str, Dict[str, Any]] = {}
        self.session_keep: Dict[str, str] = {}
        self.duplicate_finder = None
        self.scan_worker = None
        self.action_worker = None
        self.action_task_id = None
        self.last_action_plan = []
        self.current_folder = None
        self._scan_done = False
        self.transaction_manager = TransactionManager(str(user_data_file("duplicate_operations_log.json")))
        self.app_config = get_app_config()
        self.ignored_hashes = set(self.app_config.get_ignored_duplicate_hashes())
        self.preferred_originals = self.app_config.get_preferred_originals()
        default_method = str(self.app_config.get("duplicates.default_method", "hybrid") or "hybrid")
        self.current_method = default_method if default_method in dict(METHODS) else "hybrid"
        self._result_method = self.current_method
        self.scan_task_id = None
        self.preview_toggle_btn = None
        self.scan_btn = None

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._execute_search)
        self.search_delay_ms = 300

        self.settings = QSettings("FileOrganizer", "DuplicatesDashboard")
        self.preview_visible = self.settings.value("preview_visible", True, type=bool)
        self._last_preview_sizes = [900, 260]

        self.init_ui()
        apply_control_sizes(self, self.app_config)
        self.setup_connections()
        self.setup_context_menu()
        self.setup_table()
        self.load_column_settings()
        self._update_empty_state()

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.tab_header = TabHeaderWidget("🔍 Detector de duplicados")
        main_layout.addWidget(self.tab_header)

        controls_frame = QFrame()
        controls_frame.setObjectName("duplicates_controls_frame")
        controls_layout = QGridLayout(controls_frame)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setHorizontalSpacing(10)
        controls_layout.setVerticalSpacing(8)

        controls_layout.addWidget(QLabel("Método"), 0, 0)
        self.method_combo = QComboBox()
        for key, label in METHODS:
            self.method_combo.addItem(label, key)
        self.method_combo.setCurrentIndex([k for k, _ in METHODS].index(self.current_method))
        self.method_combo.setMinimumWidth(200)
        self.method_combo.setToolTip(
            "Método de detección:\n"
            "• Rápido: tamaño + nombre + extensión (candidatos; se confirman por hash antes de retirar)\n"
            "• Híbrido: filtro rápido + confirmación por hash (recomendado)\n"
            "• Profundo: hash de contenido de todos los archivos del mismo tamaño\n"
            "• Imágenes parecidas: comparación visual (no son copias exactas)"
        )
        controls_layout.addWidget(self.method_combo, 0, 1)

        self.select_folder_btn = QPushButton("📂 Elegir carpeta…")
        self.select_folder_btn.setMinimumWidth(140)
        self.select_folder_btn.setToolTip("Selecciona la carpeta o disco donde buscar duplicados")
        controls_layout.addWidget(self.select_folder_btn, 0, 2)

        self.current_folder_label = ElidedPathLabel("Ninguna carpeta seleccionada")
        self.current_folder_label.setObjectName("duplicates_path_label")
        self.current_folder_label.setWordWrap(False)
        self.current_folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.current_folder_label.setMinimumWidth(220)
        self.current_folder_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        controls_layout.addWidget(self.current_folder_label, 0, 3, 1, 5)

        controls_layout.addWidget(QLabel("Mínimo"), 1, 0)
        self.min_size_spin = QSpinBox()
        self.min_size_spin.setRange(0, 10000)
        self.min_size_spin.setValue(1)
        self.min_size_spin.setSuffix(" MB")
        self.min_size_spin.setMinimumWidth(90)
        self.min_size_spin.setToolTip("Tamaño mínimo de los archivos que se muestran (en MB)")
        controls_layout.addWidget(self.min_size_spin, 1, 1)

        controls_layout.addWidget(QLabel("Extensión"), 1, 2)
        self.ext_filter_combo = QComboBox()
        self.ext_filter_combo.addItem("Todas", None)
        for ext in (".jpg", ".png", ".gif", ".mp4", ".avi", ".mp3", ".pdf", ".txt", ".docx"):
            self.ext_filter_combo.addItem(ext, ext)
        self.ext_filter_combo.setMinimumWidth(108)
        self.ext_filter_combo.setToolTip("Filtra por tipo de archivo")
        controls_layout.addWidget(self.ext_filter_combo, 1, 3)

        self.recursive_cb = QCheckBox("Subcarpetas")
        self.recursive_cb.setChecked(True)
        self.recursive_cb.setToolTip("Buscar también en todas las subcarpetas")
        controls_layout.addWidget(self.recursive_cb, 1, 4)

        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(0, 30)
        self.threshold_spin.setValue(int(self.app_config.get("duplicates.similar_images_threshold", 10) or 10))
        self.threshold_spin.setPrefix("Umbral ")
        self.threshold_spin.setToolTip("Distancia máxima (bits distintos de 64) entre imágenes parecidas")
        controls_layout.addWidget(self.threshold_spin, 1, 5)

        # Compatibilidad con código antiguo (opciones sin efecto en la búsqueda)
        self.show_details_cb = QCheckBox("Detalles")
        self.show_details_cb.setVisible(False)
        self.group_by_hash_cb = QCheckBox("Agrupar")
        self.group_by_hash_cb.setVisible(False)

        self.method_info = QLabel("")
        self.method_info.setObjectName("duplicates_method_info")
        self.method_info.setWordWrap(True)
        controls_layout.addWidget(self.method_info, 1, 6, 1, 2)
        controls_layout.setColumnStretch(3, 1)
        main_layout.addWidget(controls_frame)

        self.result_status_label = QLabel("")
        self.result_status_label.setWordWrap(True)
        main_layout.addWidget(self.result_status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(12)
        main_layout.addWidget(self.progress_bar)

        self.actions_frame = QFrame()
        self.actions_frame.setObjectName("duplicates_action_frame")
        actions_layout = QHBoxLayout(self.actions_frame)
        actions_layout.setContentsMargins(10, 8, 10, 8)
        actions_layout.setSpacing(6)

        self.select_all_btn = QPushButton("Marcar copias")
        self.select_all_btn.setProperty("styleClass", "ghost")
        self.select_all_btn.setToolTip("Marca todas las copias de todas las páginas (no las que se conservan)")
        actions_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Limpiar selección")
        self.deselect_all_btn.setProperty("styleClass", "ghost")
        actions_layout.addWidget(self.deselect_all_btn)

        actions_layout.addWidget(QLabel("Filtrar"))
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Buscar por nombre o extensión...")
        self.filter_input.setMinimumWidth(180)
        self.filter_input.setMaximumWidth(260)
        self.filter_input.textChanged.connect(self.on_filter_changed)
        actions_layout.addWidget(self.filter_input)
        self.filter_count_label = QLabel("")
        actions_layout.addWidget(self.filter_count_label)
        actions_layout.addStretch()

        self.delete_btn = QPushButton("Retirar selección")
        self.delete_btn.setEnabled(False)
        self.delete_btn.setProperty("styleClass", "danger")
        self.delete_btn.setToolTip(
            "Retira a la papelera (o a .quarantine) las copias marcadas tras verificar su contenido. "
            "Nunca se retiran todas las copias de un grupo.")
        actions_layout.addWidget(self.delete_btn)

        self.move_btn = QPushButton("Mover")
        self.move_btn.setEnabled(False)
        self.move_btn.setProperty("styleClass", "ghost")
        self.move_btn.setToolTip("Mueve las copias marcadas a .duplicates_quarantine")
        actions_layout.addWidget(self.move_btn)

        self.preview_toggle_btn = QPushButton()
        self.preview_toggle_btn.setObjectName("duplicates_preview_toggle")
        self.preview_toggle_btn.setProperty("styleClass", "ghost")
        actions_layout.addWidget(self.preview_toggle_btn)

        self.more_actions_btn = QToolButton()
        self.more_actions_btn.setObjectName("duplicates_more_button")
        self.more_actions_btn.setText("Más acciones")
        self.more_actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        more_menu = QMenu(self)
        apply_menu_surface(more_menu)
        self.hardlink_action = more_menu.addAction("🔗 Sustituir copias por hardlinks")
        self.export_plan_action = more_menu.addAction("📄 Exportar plan de borrado (CSV)")
        self.export_action = more_menu.addAction("💾 Exportar resultados")
        more_menu.addSeparator()
        self.ignore_group_action = more_menu.addAction("🙈 Ignorar grupo")
        self.keep_selected_action = more_menu.addAction("🟢 Conservar")
        self.build_keep_rules_menu(more_menu)
        more_menu.addSeparator()
        self.reset_columns_action = more_menu.addAction("📏 Restablecer columnas")
        self.task_center_action = more_menu.addAction("🧵 Tareas")
        self.more_actions_btn.setMenu(more_menu)
        actions_layout.addWidget(self.more_actions_btn)
        main_layout.addWidget(self.actions_frame)

        self.summary_frame = QFrame()
        self.summary_frame.setObjectName("duplicates_summary_frame")
        summary_layout = QHBoxLayout(self.summary_frame)
        summary_layout.setContentsMargins(10, 6, 10, 6)
        summary_layout.setSpacing(6)
        self.stats_labels = {}
        for key, title in (("grupos", "Grupos"), ("duplicados", "Copias"), ("seleccionados", "Marcadas"),
                           ("espacio", "Recuperable"), ("espacio_seleccionado", "Marcado"),
                           ("tiempo", "Tiempo")):
            chip, value_label = self._create_stat_chip(key, title)
            self.stats_labels[key] = value_label
            summary_layout.addWidget(chip)
        summary_layout.addStretch()
        main_layout.addWidget(self.summary_frame)

        results_frame = QFrame()
        results_frame.setObjectName("duplicates_results_frame")
        results_layout = QVBoxLayout(results_frame)
        results_layout.setContentsMargins(8, 8, 8, 8)
        results_layout.setSpacing(6)

        self.empty_state_label = QLabel()
        self.empty_state_label.setObjectName("duplicates_empty_state")
        self.empty_state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        self.empty_state_label.setMinimumHeight(160)
        results_layout.addWidget(self.empty_state_label, 1)

        self.duplicates_table = QTableView()
        self.duplicates_model = PaginatedDuplicatesModel(page_size=1000)
        self.duplicates_table.setModel(self.duplicates_model)
        self.duplicates_table.setItemDelegateForColumn(0, CheckboxDelegate(self.duplicates_table))

        self.table_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table_splitter.addWidget(self.duplicates_table)
        self.table_splitter.setChildrenCollapsible(False)
        self.table_splitter.setHandleWidth(6)
        self.preview_panel = QTextEdit()
        self.preview_panel.setObjectName("duplicates_preview_panel")
        self.preview_panel.setReadOnly(True)
        self.preview_panel.setMinimumWidth(200)
        self.preview_panel.setMaximumWidth(340)
        self.preview_panel.setPlaceholderText("Selecciona un archivo para ver detalles y decidir cuál conservar.")
        self.table_splitter.addWidget(self.preview_panel)
        self.table_splitter.setStretchFactor(0, 5)
        self.table_splitter.setStretchFactor(1, 1)
        self.table_splitter.setSizes(self._last_preview_sizes)
        self.preview_panel.setVisible(self.preview_visible)
        results_layout.addWidget(self.table_splitter, 1)

        scan_row = QHBoxLayout()
        self.scan_btn = QPushButton("Analizar")
        self.scan_btn.setObjectName("scan_button")
        self.scan_btn.setEnabled(False)
        self.scan_btn.setMinimumWidth(132)
        self.scan_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.scan_btn.setToolTip("Inicia la búsqueda de duplicados (elige antes una carpeta)")
        scan_row.addWidget(self.scan_btn, 1)
        self.cancel_scan_btn = QPushButton("Cancelar")
        self.cancel_scan_btn.setProperty("styleClass", "ghost")
        self.cancel_scan_btn.setVisible(False)
        scan_row.addWidget(self.cancel_scan_btn)
        results_layout.addLayout(scan_row)
        self.on_method_changed()

        self.pagination_widget = QWidget()
        pagination_layout = QHBoxLayout(self.pagination_widget)
        pagination_layout.setContentsMargins(0, 0, 0, 0)
        pagination_layout.setSpacing(6)
        self.prev_page_btn = QPushButton("Anterior")
        self.prev_page_btn.setProperty("styleClass", "ghost")
        self.prev_page_btn.setMinimumWidth(typography_scale(self.app_config).control_height)
        self.prev_page_btn.clicked.connect(self.go_to_previous_page)
        self.prev_page_btn.setEnabled(False)
        pagination_layout.addWidget(self.prev_page_btn)
        self.page_info_label = QLabel("")
        self.page_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pagination_layout.addWidget(self.page_info_label)
        self.next_page_btn = QPushButton("Siguiente")
        self.next_page_btn.setProperty("styleClass", "ghost")
        self.next_page_btn.setMinimumWidth(typography_scale(self.app_config).control_height)
        self.next_page_btn.clicked.connect(self.go_to_next_page)
        self.next_page_btn.setEnabled(False)
        pagination_layout.addWidget(self.next_page_btn)
        results_layout.addWidget(self.pagination_widget)
        main_layout.addWidget(results_frame, 1)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_height = typography_scale(self.app_config).control_height
        self.log_text.setMinimumHeight(log_height)
        self.log_text.setMaximumHeight(log_height * 2)
        self.log_text.setObjectName("log_text")
        main_layout.addWidget(self.log_text)
        self.update_preview_button_state()

    def _create_stat_chip(self, key: str, title: str):
        chip = QFrame()
        chip.setProperty("styleClass", "stat-chip")
        chip.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
        chip.setToolTip(title)
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setProperty("styleClass", "stat-title")
        value_label = QLabel("—")
        value_label.setProperty("styleClass", "stat-value")
        value_label.setObjectName(f"stat_value_{key}")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addStretch()
        return chip, value_label

    def _update_empty_state(self):
        """Estado vacío en lugar de contadores a cero y tabla sin explicación."""
        has_rows = bool(self.duplicates_model._all_rows())
        scanning = bool(self.scan_task_id)
        self.empty_state_label.setVisible(not has_rows)
        self.table_splitter.setVisible(has_rows)
        self.pagination_widget.setVisible(has_rows and self.duplicates_model.get_page_info()["total_pages"] > 1)
        self.summary_frame.setVisible(has_rows)
        self.actions_frame.setVisible(has_rows)
        if has_rows:
            return
        if scanning:
            text = "🔎 Analizando… los resultados aparecerán aquí."
        elif not self.current_folder:
            text = ("📂 Elige una carpeta con «Elegir carpeta…» y pulsa «Analizar».\n\n"
                    "El modo Híbrido confirma por contenido antes de mostrar un grupo.")
        elif self.duplicates_data:
            text = "Ningún resultado pasa los filtros actuales (tamaño mínimo, extensión o texto)."
        elif self._scan_done:
            text = "✅ No se encontraron duplicados en la carpeta analizada."
        else:
            text = "Pulsa «Analizar» para buscar duplicados en la carpeta elegida."
        self.empty_state_label.setText(text)

    def _format_folder_display(self, scope_type: str, folder: str) -> str:
        normalized = os.path.normpath(folder)
        parts = [part for part in normalized.split(os.sep) if part]
        if len(parts) <= 3:
            return f"{scope_type}: {normalized}"
        return f"{scope_type}: …{os.sep}{os.sep.join(parts[-3:])}"

    def setup_connections(self):
        self.select_folder_btn.clicked.connect(self.select_folder)
        self.scan_btn.clicked.connect(self.start_scan)
        self.cancel_scan_btn.clicked.connect(self.cancel_scan)
        self.select_all_btn.clicked.connect(self.select_all_duplicates)
        self.deselect_all_btn.clicked.connect(self.deselect_all_duplicates)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.move_btn.clicked.connect(self.move_selected)
        self.preview_toggle_btn.clicked.connect(self.toggle_preview_panel)
        self.export_action.triggered.connect(self.export_results)
        self.export_plan_action.triggered.connect(self.export_deletion_plan)
        self.hardlink_action.triggered.connect(self.replace_with_hardlinks)
        self.ignore_group_action.triggered.connect(self.ignore_selected_group)
        self.keep_selected_action.triggered.connect(self.mark_selected_as_preferred_original)
        self.task_center_action.triggered.connect(self.open_task_center)
        self.reset_columns_action.triggered.connect(self.reset_column_settings)
        self.min_size_spin.valueChanged.connect(self._debounced_filter)
        self.ext_filter_combo.currentTextChanged.connect(self._debounced_filter)
        self.recursive_cb.stateChanged.connect(self.on_recursive_changed)
        self.method_combo.currentIndexChanged.connect(self.on_method_changed)
        self.threshold_spin.valueChanged.connect(
            lambda v: self.app_config.set("duplicates.similar_images_threshold", int(v)))
        self.duplicates_model.dataChanged.connect(self.on_selection_changed)
        self.duplicates_table.clicked.connect(self.update_preview_panel_from_index)

    def on_selection_changed(self, top_left, bottom_right, roles):
        if Qt.ItemDataRole.CheckStateRole in roles:
            self.update_statistics_from_selection()

    def on_method_changed(self):
        self.current_method = self.method_combo.currentData() or "hybrid"
        self.method_info.setText(METHOD_INFO[self.current_method])
        self.scan_btn.setText(SCAN_LABELS[self.current_method])
        self.threshold_spin.setVisible(self.current_method == "similar")
        if self.current_method in ("fast", "hybrid", "deep"):
            if self.app_config.get("duplicates.default_method") != self.current_method:
                self.app_config.set("duplicates.default_method", self.current_method)
        self.update_preview_button_state()

    def on_recursive_changed(self):
        if self.recursive_cb.isChecked():
            self.log_message("🔄 Búsqueda recursiva activada: incluye subcarpetas")
        else:
            self.log_message("📁 Búsqueda recursiva desactivada: solo la carpeta actual")

    def select_folder(self):
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Seleccionar ámbito de búsqueda")
        msg_box.setText("¿Qué quieres analizar?")
        msg_box.setInformativeText(
            "📂 CARPETA: analiza solo una carpeta (recomendado)\n"
            "💿 DISCO: analiza toda una unidad (puede ser muy lento)")
        msg_box.setIcon(QMessageBox.Icon.Question)
        carpeta_btn = msg_box.addButton("📂 Carpeta", QMessageBox.ButtonRole.YesRole)
        disco_btn = msg_box.addButton("💿 Disco completo", QMessageBox.ButtonRole.NoRole)
        cancel_btn = msg_box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(carpeta_btn)
        msg_box.exec()
        clicked_button = msg_box.clickedButton()
        if clicked_button is None or clicked_button == cancel_btn:
            return
        if clicked_button == carpeta_btn:
            folder = QFileDialog.getExistingDirectory(
                self, "Seleccionar carpeta para analizar", str(Path.home()), QFileDialog.Option.ShowDirsOnly)
            scope_type = "CARPETA"
        else:
            folder = QFileDialog.getExistingDirectory(
                self, "Seleccionar disco completo (puede ser muy lento)", "", QFileDialog.Option.ShowDirsOnly)
            scope_type = "DISCO"
        if folder:
            self.set_folder(folder, scope_type)
            if clicked_button == disco_btn:
                QMessageBox.warning(
                    self, "Análisis de disco completo",
                    f"Has seleccionado analizar TODO el disco: {folder}\n\n"
                    "• Puede tardar mucho según el tamaño\n"
                    "• Se omiten carpetas del sistema, ocultas y de cuarentena\n"
                    "• Puedes cancelar en cualquier momento")

    def set_folder(self, folder: str, scope_type: str = "CARPETA"):
        self.current_folder = folder
        self.current_folder_label.set_path(self._format_folder_display(scope_type, folder), folder)
        self.scan_btn.setEnabled(True)
        self.apply_scan_button_style()
        self.log_message(f"✅ {scope_type} seleccionada: {folder}")
        self._update_empty_state()

    # ------------------------------------------------------------------ análisis
    def start_scan(self):
        if not self.current_folder:
            QMessageBox.warning(self, "Error", "Primero selecciona una carpeta o disco")
            return
        if self.scan_worker is not None and self.scan_worker.isRunning():
            return
        self.method_combo.setEnabled(False)
        self._result_method = self.current_method
        self.delete_btn.setEnabled(False)
        self.move_btn.setEnabled(False)
        self.duplicates_data = {}
        self.group_meta = {}
        self.file_info = {}
        self.session_keep = {}
        self._scan_done = False
        self.duplicates_model.clear_data()
        self.clear_statistics()
        self.scan_btn.setEnabled(False)
        self.cancel_scan_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self._scan_started = datetime.now()
        self.result_status_label.setText("Analizando… La selección estará disponible al terminar.")
        recursive_enabled = self.recursive_cb.isChecked()
        if self.current_method == "similar":
            self.scan_worker = SimilarImagesWorker(
                str(self.current_folder), recursive=recursive_enabled, threshold=self.threshold_spin.value())
        else:
            self.scan_worker = DuplicateScanWorker(
                str(self.current_folder), method=self.current_method, recursive=recursive_enabled,
                min_size=self.min_size_spin.value() * 1024 * 1024)
        self.duplicate_finder = getattr(self.scan_worker, "duplicate_finder", None)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.error_occurred.connect(self.on_scan_error)
        self.scan_worker.scan_progress.connect(self._handle_scan_progress)
        self.scan_worker.scan_complete.connect(self.on_duplicates_found)
        self.scan_worker.scan_cancelled.connect(self.on_scan_cancelled)
        self.log_message(f"🚀 Iniciando análisis ({dict(METHODS)[self.current_method]}) en: {self.current_folder}")
        self.scan_task_id = f"duplicates_scan_{int(datetime.now().timestamp())}"
        task_registry.start_task(self.scan_task_id, "Escaneo de duplicados", self.scan_worker.stop)
        self._update_empty_state()
        self.scan_worker.start()

    def cancel_scan(self):
        if self.scan_worker is not None and self.scan_worker.isRunning():
            self.scan_worker.stop()
            self.log_message("⏹ Cancelando análisis…")

    def on_scan_cancelled(self):
        self._scan_cancelled = True
        self.result_status_label.setText("Análisis cancelado. No se ha modificado ningún archivo.")

    def _content_key(self, group_key: str) -> str:
        """Clave de contenido estable (hash) para ignorar/conservar; '' si no la hay."""
        meta = self.group_meta.get(group_key) or {}
        if meta.get("method") == "similar":
            return group_key
        if meta.get("content_hash"):
            return str(meta["content_hash"])
        if group_key.startswith(PARTIAL_HASH_LABEL + ":"):
            return group_key
        if meta.get("confirmed"):
            return group_key
        return ""

    def on_duplicates_found(self, duplicates_data, statistics):
        self.duplicates_data = {k: [Path(p) for p in v] for k, v in duplicates_data.items()}
        statistics = statistics or {}
        self.group_meta = dict(statistics.get("group_meta") or {})
        self.file_info = dict(statistics.get("file_info") or {})
        method = statistics.get("method", self._result_method)
        if method == "fast":
            self.result_status_label.setText(
                "Candidatos por nombre, extensión y tamaño: el contenido NO está confirmado. "
                "Antes de retirar se confirma cada archivo por hash.")
        elif method == "similar":
            self.result_status_label.setText(
                "Imágenes parecidas (no idénticas). Revisa cada grupo antes de retirar nada.")
        else:
            partial = statistics.get("partial_groups", 0)
            extra = (f" {partial} grupo(s) de más de 5000 MB se compararon por muestras y se "
                     "verificarán completos antes de retirar.") if partial else ""
            self.result_status_label.setText("Coincidencias confirmadas por hash de contenido." + extra)
        errors = statistics.get("errors") or []
        for path, reason in list(errors)[:20]:
            self.log_message(f"⚠️ {path}: {reason}")
        if len(errors) > 20:
            self.log_message(f"⚠️ … y {len(errors) - 20} errores más")
        if statistics.get("hardlinks_skipped"):
            self.log_message(f"🔗 {statistics['hardlinks_skipped']} hardlink(s) omitidos: no ocupan espacio extra")
        self.log_message(f"🔍 Encontrados {len(self.duplicates_data)} grupos")
        self.populate_table()
        started = getattr(self, "_scan_started", None)
        if started:
            seconds = (datetime.now() - started).total_seconds()
            self.stats_labels["tiempo"].setText(f"{seconds:.1f} s" if seconds >= 1 else "< 1 s")

    def on_scan_finished(self):
        self.scan_btn.setEnabled(True)
        self.method_combo.setEnabled(True)
        self.cancel_scan_btn.setVisible(False)
        self._scan_done = True
        if not self.duplicates_data and not getattr(self, "_scan_cancelled", False):
            self.result_status_label.setText("Análisis terminado: no se encontraron coincidencias.")
        self._scan_cancelled = False
        self.apply_scan_button_style()
        self.progress_bar.setVisible(False)
        if self.scan_task_id:
            task_registry.finish_task(self.scan_task_id, "Completada")
            self.scan_task_id = None
        self._update_empty_state()
        self.update_statistics_from_selection()
        self.log_message("✅ Escaneo terminado")
        self.analysis_finished.emit()

    def on_scan_error(self, error_message):
        self.scan_btn.setEnabled(True)
        self.method_combo.setEnabled(True)
        self.cancel_scan_btn.setVisible(False)
        self.result_status_label.setText("No se pudo completar el análisis. Revisa la carpeta y vuelve a intentarlo.")
        self.apply_scan_button_style()
        self.progress_bar.setVisible(False)
        if self.scan_task_id:
            task_registry.finish_task(self.scan_task_id, "Error")
            self.scan_task_id = None
        self.log_message(f"❌ Error en escaneo: {error_message}")
        QMessageBox.critical(self, "Error", f"Error durante el escaneo:\n{error_message}")

    # ------------------------------------------------------------------ estadísticas
    def clear_statistics(self):
        for label in self.stats_labels.values():
            label.setText("—")

    def update_statistics_from_table(self):
        rows = self.duplicates_model._all_rows()
        groups: Dict[str, List[int]] = {}
        for row in rows:
            groups.setdefault(str(row.get("group_key")), []).append(int(row.get("size") or 0))
        recoverable = sum(sum(sizes) - max(sizes) for sizes in groups.values() if sizes)
        self.stats_labels["grupos"].setText(str(len(groups)))
        self.stats_labels["duplicados"].setText(str(sum(1 for r in rows if not r.get("is_original"))))
        self.stats_labels["espacio"].setText(_format_bytes(recoverable))
        self.update_statistics_from_selection()

    def update_statistics_from_selection(self):
        entries = self.duplicates_model.get_checked_entries()
        busy = bool(self.scan_task_id) or (self.action_worker is not None and self.action_worker.isRunning())
        self.delete_btn.setEnabled(bool(entries) and not busy)
        self.move_btn.setEnabled(bool(entries) and not busy)
        self.stats_labels["seleccionados"].setText(str(len(entries)))
        self.stats_labels["espacio_seleccionado"].setText(
            _format_bytes(sum(int(e.get("size") or 0) for e in entries)))

    # ------------------------------------------------------------------ tabla
    def _match_status(self, group_key: str) -> str:
        meta = self.group_meta.get(group_key) or {}
        method = meta.get("method", self._result_method)
        if method == "similar":
            return "Imagen parecida (no idéntica)"
        if meta.get("partial") or group_key.startswith(PARTIAL_HASH_LABEL + ":"):
            return "Muestras (>5000 MB): se verificará al retirar"
        if meta.get("confirmed"):
            return "Contenido idéntico (hash)"
        return "Candidato sin confirmar"

    def populate_table(self):
        text = self.filter_input.text().strip() if hasattr(self, "filter_input") else ""
        if text:
            self.apply_quick_filter(text)
        else:
            self.populate_table_with_filtered_data(self.duplicates_data)

    def populate_table_with_filtered_data(self, data_to_use):
        """Construye las filas desde los datos del análisis (sin stat() en la interfaz)."""
        min_size_bytes = self.min_size_spin.value() * 1024 * 1024
        selected_ext = self.ext_filter_combo.currentData()
        rule = str(self.app_config.get("duplicates.keep_rule", "newest") or "newest")
        preferred_folders = list(self.app_config.get("duplicates.preferred_folders", []) or [])
        model_data = []
        filtered_out = 0
        for group_key, file_paths in (data_to_use or {}).items():
            content_key = self._content_key(group_key)
            if content_key and content_key in self.ignored_hashes:
                continue
            meta = self.group_meta.get(group_key) or {}
            status = self._match_status(group_key)
            files_info = []
            for file_path in file_paths:
                path_str = str(file_path)
                info = self.file_info.get(path_str) or {}
                size = int(info.get("size", meta.get("size", 0)) or 0)
                if size < min_size_bytes or (selected_ext and Path(path_str).suffix.lower() != selected_ext):
                    filtered_out += 1
                    continue
                files_info.append({
                    "path": path_str,
                    "name": Path(path_str).name,
                    "location": str(Path(path_str).parent),
                    "size": size,
                    "date": float(info.get("date", 0) or 0),
                    "hash": content_key if content_key and not group_key.startswith("similar:") else "",
                    "group_key": group_key,
                    "match_status": status,
                    "is_original": False,
                })
            if len(files_info) < 2:
                continue
            preferred_path = self.session_keep.get(group_key) or (
                self.preferred_originals.get(content_key) if content_key else None)
            keep_index = choose_keep_index(files_info, rule, preferred_folders, preferred_path)
            files_info[keep_index]["is_original"] = True
            files_info.insert(0, files_info.pop(keep_index))
            model_data.extend(files_info)
        self.duplicates_model.load_full_data(model_data)
        self.update_pagination_controls()
        self.apply_column_widths()
        self.update_statistics_from_table()
        self._update_empty_state()
        self.filter_count_label.setText(f"({filtered_out} ocultos por filtros)" if filtered_out else "")

    def go_to_next_page(self):
        if self.duplicates_model.next_page():
            self.update_pagination_controls()
            self.apply_column_widths()

    def go_to_previous_page(self):
        if self.duplicates_model.previous_page():
            self.update_pagination_controls()
            self.apply_column_widths()

    def update_pagination_controls(self):
        page_info = self.duplicates_model.get_page_info()
        self.page_info_label.setText(
            f"Página {page_info['current_page']} de {page_info['total_pages']} "
            f"({page_info['showing_from']}-{page_info['showing_to']} de {page_info['total_items']}) · "
            "los grupos no se parten entre páginas")
        self.prev_page_btn.setEnabled(page_info["current_page"] > 1)
        self.next_page_btn.setEnabled(page_info["current_page"] < page_info["total_pages"])
        self.pagination_widget.setVisible(bool(page_info["total_items"]) and page_info["total_pages"] > 1)

    def _debounced_filter(self):
        self.search_timer.start(self.search_delay_ms)

    def _execute_search(self):
        self.apply_filters()

    def on_filter_changed(self):
        if self.duplicates_data:
            self.populate_table()

    def apply_quick_filter(self, filter_text):
        """Filtro por nombre o extensión en memoria (sin acceder al disco)."""
        if not filter_text:
            self.populate_table_with_filtered_data(self.duplicates_data)
            return
        needle = filter_text.lower()
        filtered = {key: paths for key, paths in self.duplicates_data.items()
                    if any(needle in Path(p).name.lower() for p in paths)}
        # Se muestra el grupo completo para no ocultar la copia que se conserva
        self.populate_table_with_filtered_data(filtered)
        self.filter_count_label.setText(f"({sum(len(v) for v in filtered.values())} archivos)")
        self.duplicates_table.viewport().update()

    def apply_filters(self):
        if self.duplicates_data:
            self.populate_table()

    def refresh_view(self):
        self.apply_filters()

    def select_all_duplicates(self):
        self.duplicates_model.check_all_duplicates()
        self.log_message("✅ Copias marcadas (las que se conservan quedan sin marcar)")
        self.update_statistics_from_selection()

    def deselect_all_duplicates(self):
        self.duplicates_model.uncheck_all()
        self.update_statistics_from_selection()

    # ------------------------------------------------------------------ varios
    def open_task_center(self):
        TaskCenterDialog(self).exec()

    def _handle_scan_progress(self, message: str):
        self.log_message(message)
        if self.scan_task_id:
            task_registry.update_task(self.scan_task_id, message)

    def log_message(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_color = "#1976d2"
        if "❌" in message or "Error" in message:
            level_color = "#c62828"
        elif "⚠️" in message or "⛔" in message:
            level_color = "#ed6c02"
        elif "✅" in message:
            level_color = "#2e7d32"
        self.log_text.append(
            f"<span style='color:#888'>[{timestamp}]</span> "
            f"<span style='color:{level_color}'>{html.escape(message)}</span>")
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
        self.status_update.emit(message)

    def apply_scan_button_style(self):
        self.scan_btn.update()
        self.scan_btn.repaint()
