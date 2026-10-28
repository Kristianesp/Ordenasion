#!/usr/bin/env python3
"""
Dashboard de Gestión de Duplicados para el Organizador de Archivos
Interfaz completa para detectar, visualizar y gestionar archivos duplicados
"""

import os
import html
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QGroupBox,
    QCheckBox,
    QComboBox,
    QLineEdit,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QTextEdit,
    QTabWidget,
    QScrollArea,
    QFrame,
    QSpinBox,
    QDialog,
    QMenu,
    QToolButton,
    QTableView,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionButton,
    QSizePolicy,
    QApplication,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSettings, QRect, QSize, QPoint
from PyQt6.QtGui import QFont, QIcon, QPixmap, QColor, QAction, QPainter

from src.utils.constants import COLORS, UI_CONFIG
from src.utils.app_config import AppConfig
from src.core.duplicate_finder import DuplicateFinder, DuplicateScanWorker
from src.core.hash_manager import HashCalculationWorker
from src.core.transaction_manager import TransactionManager
from src.gui.modern_components import TabHeaderWidget
from src.gui.table_models import VirtualizedDuplicatesModel, PaginatedDuplicatesModel
from src.gui.task_center import TaskCenterDialog, task_registry
from src.gui.v2.theme import ElidedPathLabel, apply_control_sizes, typography_scale, apply_menu_surface


class CheckboxDelegate(QStyledItemDelegate):
    """Delegado personalizado para checkboxes centrados y funcionales con colores del tema"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_table = parent

    def paint(self, painter, option, index):
        """Pinta el checkbox centrado en la celda con colores del tema actual"""
        if not index.isValid():
            return

        # Obtener el estado del checkbox
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked

        # Obtener colores del tema actual
        theme_colors = self.get_theme_colors()

        # Calcular rectángulo del checkbox
        checkbox_rect = self.get_checkbox_rect(option.rect)

        # Guardar el estado del painter
        painter.save()

        try:
            # Pintar el checkbox personalizado
            self.paint_custom_checkbox(painter, checkbox_rect, checked, theme_colors)
        finally:
            # Restaurar el estado del painter
            painter.restore()

    def get_theme_colors(self):
        """Obtiene los colores del tema actual"""
        try:
            from src.utils.themes import ThemeManager
            from src.utils.app_config import AppConfig

            # Obtener el tema actual desde la configuración
            app_config = AppConfig()
            current_theme = app_config.get_theme()
            return ThemeManager.get_theme_colors(current_theme)
        except:
            # Fallback con tokens del sistema de diseño
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

    def paint_custom_checkbox(self, painter, rect, checked, colors):
        """Pinta un checkbox personalizado con colores del tema - ROBUSTO"""
        # Configurar el painter
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Limpiar el área del checkbox
        painter.fillRect(rect, QColor(colors["background"]))

        if checked:
            # Checkbox marcado - FONDO VERDE SÓLIDO
            painter.fillRect(rect, QColor(colors["success"]))

            # Borde verde
            pen = painter.pen()
            pen.setWidth(2)
            pen.setColor(QColor(colors["success"]))
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

            # Checkmark blanco más visible y robusto
            pen.setWidth(3)  # Más grueso para mejor visibilidad
            pen.setColor(QColor("white"))
            painter.setPen(pen)

            # Dibujar checkmark más grande y visible
            center_x = rect.x() + rect.width() // 2
            center_y = rect.y() + rect.height() // 2
            size = min(rect.width(), rect.height()) // 3

            # Puntos del checkmark (V) más robustos
            check_points = [
                QPoint(center_x - size // 2, center_y),
                QPoint(center_x - size // 4, center_y + size // 2),
                QPoint(center_x + size // 2, center_y - size // 2),
            ]
            painter.drawPolyline(check_points)

            # Dibujar un segundo checkmark para mayor visibilidad
            check_points2 = [
                QPoint(center_x - size // 2 + 1, center_y + 1),
                QPoint(center_x - size // 4 + 1, center_y + size // 2 + 1),
                QPoint(center_x + size // 2 + 1, center_y - size // 2 + 1),
            ]
            painter.drawPolyline(check_points2)
        else:
            # Checkbox desmarcado - FONDO BLANCO CON BORDE VISIBLE
            painter.fillRect(rect, QColor(colors["background"]))

            # Borde más grueso y visible
            pen = painter.pen()
            pen.setWidth(2)
            pen.setColor(QColor(colors["primary"]))
            painter.setPen(pen)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

    def get_checkbox_rect(self, cell_rect):
        """Calcula el rectángulo centrado para el checkbox"""
        checkbox_size = 20  # Tamaño del checkbox más grande
        x = cell_rect.x() + (cell_rect.width() - checkbox_size) // 2
        y = cell_rect.y() + (cell_rect.height() - checkbox_size) // 2
        return QRect(x, y, checkbox_size, checkbox_size)

    def editorEvent(self, event, model, option, index):
        """Maneja eventos del mouse para el checkbox"""
        if event.type() == event.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                checkbox_rect = self.get_checkbox_rect(option.rect)
                if checkbox_rect.contains(event.pos()):
                    # Alternar estado del checkbox
                    current_state = index.data(Qt.ItemDataRole.CheckStateRole)
                    new_state = (
                        Qt.CheckState.Unchecked
                        if current_state == Qt.CheckState.Checked
                        else Qt.CheckState.Checked
                    )
                    model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
                    return True
        return False

    def sizeHint(self, option, index):
        """Retorna el tamaño sugerido para la celda"""
        return QSize(60, 40)


class DuplicatesDashboard(QWidget):
    """Dashboard principal para gestión de duplicados"""

    # Señales para comunicación con ventana principal
    status_update = pyqtSignal(str)
    analysis_finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.duplicates_data = {}  # Datos de duplicados {hash: [paths]}
        self.duplicate_finder = None
        self.current_method = "fast"  # Por defecto método rápido
        self.current_folder = None
        self.transaction_manager = TransactionManager("duplicate_operations_log.json")
        self.app_config = AppConfig()
        self.ignored_hashes = set(self.app_config.get_ignored_duplicate_hashes())
        self.preferred_originals = self.app_config.get_preferred_originals()
        self.scan_task_id = None
        self.preview_visible = True
        self.preview_toggle_btn = None
        self.scan_btn = None
        # 🚀 MEJORA: Variables eliminadas - ya no se usa procesamiento por lotes
        # La paginación reemplaza el sistema de lotes asíncrono

        # 🚀 MEJORA: Debouncing para búsquedas
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._execute_search)
        self.search_delay_ms = 300  # Esperar 300ms después de la última tecla
        self.pending_search_query = ""

        # ✅ NUEVO: Configuración persistente de columnas
        self.settings = QSettings("FileOrganizer", "DuplicatesDashboard")
        self.preview_visible = self.settings.value("preview_visible", True, type=bool)
        self._last_preview_sizes = [900, 260]

        self.init_ui()
        apply_control_sizes(self, self.app_config)
        self.setup_connections()
        self.setup_context_menu()

        # Configurar tabla inicial
        self.setup_table()
        # ✅ NUEVO: Cargar estado de columnas guardado
        self.load_column_settings()

    def init_ui(self):
        """Inicializa la interfaz con prioridad total a la tabla."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.tab_header = TabHeaderWidget("🔍 Detector de Duplicados")
        main_layout.addWidget(self.tab_header)

        controls_frame = QFrame()
        controls_frame.setObjectName("duplicates_controls_frame")
        controls_layout = QGridLayout(controls_frame)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setHorizontalSpacing(10)
        controls_layout.setVerticalSpacing(8)

        controls_layout.addWidget(QLabel("Método"), 0, 0)
        self.method_combo = QComboBox()
        self.method_combo.addItems(["Rapido", "Hibrido", "Profundo"])
        self.method_combo.setCurrentIndex(0)
        self.method_combo.setMinimumWidth(156)
        self.method_combo.setToolTip(
            "Selecciona el método de detección de duplicados:\n• ULTRA-RÁPIDO: Compara tamaño + nombre + extensión\n• HÍBRIDO: Filtro rápido + confirmación MD5\n• PROFUNDO: MD5 completo de todo el archivo"
        )
        controls_layout.addWidget(self.method_combo, 0, 1)

        self.select_folder_btn = QPushButton("Carpeta")
        self.select_folder_btn.setMinimumWidth(112)
        self.select_folder_btn.setToolTip(
            "Selecciona la carpeta donde buscar archivos duplicados"
        )
        self.select_folder_btn.setProperty("styleClass", "ghost")
        controls_layout.addWidget(self.select_folder_btn, 0, 2)

        self.current_folder_label = ElidedPathLabel("Ninguna ruta seleccionada")
        self.current_folder_label.setObjectName("duplicates_path_label")
        self.current_folder_label.setWordWrap(False)
        self.current_folder_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.current_folder_label.setMinimumWidth(220)
        self.current_folder_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self.current_folder_label.setToolTip(
            "Muestra la ruta de la carpeta seleccionada para buscar duplicados"
        )
        controls_layout.addWidget(self.current_folder_label, 0, 3, 1, 5)

        controls_layout.addWidget(QLabel("Mínimo"), 1, 0)
        self.min_size_spin = QSpinBox()
        self.min_size_spin.setRange(0, 10000)
        self.min_size_spin.setValue(1)
        self.min_size_spin.setSuffix(" MB")
        self.min_size_spin.setMinimumWidth(90)
        self.min_size_spin.setToolTip(
            "Tamaño mínimo de archivos a analizar (en MB)\nArchivos más pequeños serán ignorados"
        )
        controls_layout.addWidget(self.min_size_spin, 1, 1)

        controls_layout.addWidget(QLabel("Extensión"), 1, 2)
        self.ext_filter_combo = QComboBox()
        self.ext_filter_combo.addItem("Todas", None)
        extensions = [
            ".jpg",
            ".png",
            ".gif",
            ".mp4",
            ".avi",
            ".mp3",
            ".pdf",
            ".txt",
            ".docx",
        ]
        for ext in extensions:
            self.ext_filter_combo.addItem(ext, ext)
        self.ext_filter_combo.setMinimumWidth(108)
        self.ext_filter_combo.setToolTip(
            "Filtra por tipo de archivo específico\nSelecciona 'Todas' para analizar todos los tipos"
        )
        controls_layout.addWidget(self.ext_filter_combo, 1, 3)

        self.recursive_cb = QCheckBox("Subcarpetas")
        self.recursive_cb.setChecked(True)
        self.recursive_cb.setToolTip(
            "Buscar archivos duplicados en todas las subcarpetas\nDesactivar para buscar solo en la carpeta principal"
        )
        controls_layout.addWidget(self.recursive_cb, 1, 4)

        self.show_details_cb = QCheckBox("Detalles")
        self.show_details_cb.setToolTip(
            "Mostrar información detallada de cada archivo duplicado\nIncluye ruta completa, tamaño y fecha de modificación"
        )
        self.group_by_hash_cb = QCheckBox("Agrupar")
        self.group_by_hash_cb.setToolTip(
            "Agrupar archivos duplicados por su hash MD5\nFacilita la identificación de grupos de duplicados"
        )
        controls_layout.addWidget(self.show_details_cb, 1, 5)
        controls_layout.addWidget(self.group_by_hash_cb, 1, 6)

        self.method_info = QLabel("Ultra: tamano + nombre + extension")
        self.method_info.setObjectName("duplicates_method_info")
        self.method_info.setToolTip(
            "Descripción del método de búsqueda seleccionado\nCambia automáticamente según la opción elegida"
        )
        controls_layout.addWidget(self.method_info, 1, 7)
        controls_layout.setColumnStretch(3, 1)

        main_layout.addWidget(controls_frame)
        self.result_status_label = QLabel("Sin análisis. El método rápido encuentra candidatos; revisa las copias antes de retirarlas.")
        self.result_status_label.setWordWrap(True)
        main_layout.addWidget(self.result_status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(12)
        self.progress_bar.setToolTip("Muestra el progreso de la búsqueda de duplicados")
        main_layout.addWidget(self.progress_bar)

        actions_frame = QFrame()
        actions_frame.setObjectName("duplicates_action_frame")
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setContentsMargins(10, 8, 10, 8)
        actions_layout.setSpacing(6)

        self.select_all_btn = QPushButton("Seleccionar todo")
        self.select_all_btn.setProperty("styleClass", "ghost")
        self.select_all_btn.setToolTip(
            "Selecciona solo los archivos duplicados (rojos)"
        )
        actions_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Limpiar selección")
        self.deselect_all_btn.setProperty("styleClass", "ghost")
        self.deselect_all_btn.setToolTip("Deselecciona todos los archivos de la tabla")
        actions_layout.addWidget(self.deselect_all_btn)

        filter_label = QLabel("Filtrar")
        filter_label.setToolTip(
            "Buscar por nombre de archivo o extensión (ej: verde, .rar)"
        )
        actions_layout.addWidget(filter_label)

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Buscar por nombre o extensión...")
        self.filter_input.setToolTip(
            "Escribe para filtrar en tiempo real por nombre de archivo o extensión"
        )
        self.filter_input.setMinimumWidth(180)
        self.filter_input.setMaximumWidth(260)
        self.filter_input.textChanged.connect(self.on_filter_changed)
        actions_layout.addWidget(self.filter_input)

        self.filter_count_label = QLabel("")
        self.filter_count_label.setToolTip("Número de resultados filtrados")
        actions_layout.addWidget(self.filter_count_label)

        actions_layout.addStretch()

        self.delete_btn = QPushButton("Retirar selección")
        self.delete_btn.setEnabled(False)
        self.delete_btn.setProperty("styleClass", "danger")
        self.delete_btn.setToolTip(
            "Retira a la papelera; si no hay soporte, usa .quarantine junto a cada archivo. Conserva los archivos sin marcar."
        )
        actions_layout.addWidget(self.delete_btn)

        self.move_btn = QPushButton("Mover")
        self.move_btn.setEnabled(False)
        self.move_btn.setProperty("styleClass", "ghost")
        self.move_btn.setToolTip("Mueve los archivos seleccionados a otra carpeta")
        actions_layout.addWidget(self.move_btn)

        self.preview_toggle_btn = QPushButton()
        self.preview_toggle_btn.setObjectName("duplicates_preview_toggle")
        self.preview_toggle_btn.setProperty("styleClass", "ghost")
        self.preview_toggle_btn.setToolTip(
            "Muestra u oculta el panel lateral de detalle"
        )
        actions_layout.addWidget(self.preview_toggle_btn)

        self.more_actions_btn = QToolButton()
        self.more_actions_btn.setObjectName("duplicates_more_button")
        self.more_actions_btn.setText("Más acciones")
        self.more_actions_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.more_actions_btn.setToolTip("Acciones secundarias")
        more_menu = QMenu(self)
        apply_menu_surface(more_menu)
        self.export_action = more_menu.addAction("💾 Exportar")
        self.ignore_group_action = more_menu.addAction("🙈 Ignorar grupo")
        self.keep_selected_action = more_menu.addAction("🟢 Conservar")
        self.reset_columns_action = more_menu.addAction("📏 Restablecer columnas")
        self.task_center_action = more_menu.addAction("🧵 Tareas")
        self.more_actions_btn.setMenu(more_menu)
        actions_layout.addWidget(self.more_actions_btn)

        main_layout.addWidget(actions_frame)

        summary_frame = QFrame()
        summary_frame.setObjectName("duplicates_summary_frame")
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(10, 6, 10, 6)
        summary_layout.setSpacing(6)

        self.stats_labels = {}
        stats_info = [
            ("grupos", "Grupos"),
            ("duplicados", "Duplicados"),
            ("seleccionados", "Seleccionados"),
            ("espacio", "Espacio"),
            ("espacio_seleccionado", "Marcado"),
            ("tiempo", "Tiempo"),
        ]
        for key, title in stats_info:
            chip, value_label = self._create_stat_chip(key, title)
            self.stats_labels[key] = value_label
            summary_layout.addWidget(chip)

        summary_layout.addStretch()
        main_layout.addWidget(summary_frame)

        results_frame = QFrame()
        results_frame.setObjectName("duplicates_results_frame")
        results_layout = QVBoxLayout(results_frame)
        results_layout.setContentsMargins(8, 8, 8, 8)
        results_layout.setSpacing(6)

        self.duplicates_table = QTableView()
        self.duplicates_model = PaginatedDuplicatesModel(
            page_size=1000
        )  # 1000 elementos por página
        self.duplicates_table.setModel(self.duplicates_model)

        # Aplicar delegado personalizado para checkboxes
        checkbox_delegate = CheckboxDelegate(self.duplicates_table)
        self.duplicates_table.setItemDelegateForColumn(0, checkbox_delegate)

        self.table_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table_splitter.addWidget(self.duplicates_table)
        self.table_splitter.setChildrenCollapsible(False)
        self.table_splitter.setHandleWidth(6)

        self.preview_panel = QTextEdit()
        self.preview_panel.setObjectName("duplicates_preview_panel")
        self.preview_panel.setReadOnly(True)
        self.preview_panel.setMinimumWidth(200)
        self.preview_panel.setMaximumWidth(340)
        self.preview_panel.setPlaceholderText(
            "Selecciona un archivo para ver detalles y decidir cuál conservar."
        )
        self.table_splitter.addWidget(self.preview_panel)
        self.table_splitter.setStretchFactor(0, 5)
        self.table_splitter.setStretchFactor(1, 1)
        self.table_splitter.setSizes(self._last_preview_sizes)
        self.preview_panel.setVisible(self.preview_visible)
        results_layout.addWidget(self.table_splitter, 1)

        self.scan_btn = QPushButton("Analizar")
        self.scan_btn.setObjectName("scan_button")
        self.scan_btn.setEnabled(False)
        self.scan_btn.setMinimumWidth(132)
        self.scan_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.scan_btn.setToolTip(
            "Inicia la búsqueda de archivos duplicados\nRequiere seleccionar una carpeta primero"
        )
        results_layout.addWidget(self.scan_btn)
        # Inicializar estado del método y texto del botón ahora que scan_btn existe
        self.on_method_changed()

        pagination_layout = QHBoxLayout()
        pagination_layout.setSpacing(6)

        self.prev_page_btn = QPushButton("Anterior")
        self.prev_page_btn.setProperty("styleClass", "ghost")
        self.prev_page_btn.setMinimumWidth(typography_scale(self.app_config).control_height)
        self.prev_page_btn.clicked.connect(self.go_to_previous_page)
        self.prev_page_btn.setEnabled(False)
        self.prev_page_btn.setToolTip("Ir a la página anterior de resultados")
        pagination_layout.addWidget(self.prev_page_btn)

        self.page_info_label = QLabel("Página 1 de 1 (0-0 de 0)")
        self.page_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_info_label.setToolTip(
            "Información de paginación: página actual, total de páginas y rango de elementos"
        )
        pagination_layout.addWidget(self.page_info_label)

        self.next_page_btn = QPushButton("Siguiente")
        self.next_page_btn.setProperty("styleClass", "ghost")
        self.next_page_btn.setMinimumWidth(typography_scale(self.app_config).control_height)
        self.next_page_btn.clicked.connect(self.go_to_next_page)
        self.next_page_btn.setEnabled(False)
        self.next_page_btn.setToolTip("Ir a la página siguiente de resultados")
        pagination_layout.addWidget(self.next_page_btn)

        results_layout.addLayout(pagination_layout)

        main_layout.addWidget(results_frame, 1)

        log_layout = QHBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setToolTip(
            "📝 Historial de operaciones, errores y mensajes informativos del sistema"
        )
        self.log_text.setReadOnly(True)
        log_height = typography_scale(self.app_config).control_height
        self.log_text.setMinimumHeight(log_height)
        self.log_text.setMaximumHeight(log_height * 2)
        self.log_text.setObjectName("log_text")
        log_layout.addWidget(self.log_text)

        main_layout.addLayout(log_layout)
        self.update_preview_button_state()

    def _create_stat_chip(self, key: str, title: str):
        """Crea una capsule compacta para una estadistica."""
        chip = QFrame()
        chip.setProperty("styleClass", "stat-chip")
        chip.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed
        )
        chip.setToolTip(title)

        layout = QHBoxLayout(chip)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setProperty("styleClass", "stat-title")
        value_label = QLabel("0")
        value_label.setProperty("styleClass", "stat-value")
        value_label.setObjectName(f"stat_value_{key}")

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addStretch()
        return chip, value_label

    def _format_folder_display(self, scope_type: str, folder: str) -> str:
        """Recorta la ruta visible para mantener la toolbar en una sola fila."""
        normalized = os.path.normpath(folder)
        parts = [part for part in normalized.split(os.sep) if part]
        if len(parts) <= 3:
            return f"{scope_type}: {normalized}"
        short_path = os.sep.join(parts[-3:])
        prefix = "..." if not normalized.startswith(short_path) else ""
        return f"{scope_type}: {prefix}{os.sep}{short_path}"

    def setup_table(self):
        """🚀 MEJORA: Configura la tabla VIRTUALIZADA de duplicados"""
        # El modelo ya tiene los headers configurados, solo configuramos la vista
        header = self.duplicates_table.horizontalHeader()
        self.duplicates_table.verticalHeader().setVisible(False)
        self.duplicates_table.setSortingEnabled(False)
        self.duplicates_table.setMinimumHeight(320)
        self.duplicates_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        # Permitir redimensionamiento manual de TODAS las columnas
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)  # Checkbox
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Nombre
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)  # Ubicación
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)  # Tamaño
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)  # Fecha
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)  # Hash
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)  # Acciones
        header.setMinimumSectionSize(34)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )

        # Habilitar ordenamiento por columnas
        header.setSortIndicatorShown(True)
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_clicked)

        # ✅ Establecer anchos predefinidos según especificaciones
        self.default_column_widths = {
            0: 38,
            1: 300,
            2: 180,
            3: 92,
            4: 116,
            5: 140,
            6: 92,
        }

        # Aplicar anchos por defecto inicial
        self.apply_column_widths()

        # Conectar señales
        header.sectionResized.connect(self.on_column_resized)
        header.setSectionsMovable(True)
        header.sectionMoved.connect(self.on_column_moved)

    def apply_column_widths(self):
        """✅ Aplica los anchos de columna predefinidos - Se llama después de cargar datos"""
        for column, width in self.default_column_widths.items():
            self.duplicates_table.setColumnWidth(column, width)

        # Habilitar selección por filas y checkboxes
        self.duplicates_table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )
        self.duplicates_table.setSelectionMode(
            QTableView.SelectionMode.ExtendedSelection
        )  # Permitir selección múltiple

        # Configuración para checkboxes - permitir clic simple
        self.duplicates_table.setEditTriggers(
            QTableView.EditTrigger.NoEditTriggers
        )  # Sin edit triggers automáticos
        self.duplicates_table.setDragDropMode(
            QTableView.DragDropMode.NoDragDrop
        )  # Sin drag & drop

        # Habilitar clics en checkboxes
        self.duplicates_table.setMouseTracking(True)

        # Configuración específica para checkboxes
        self.duplicates_table.setWordWrap(False)  # Evitar wrap de texto
        self.duplicates_table.setVerticalScrollMode(
            QTableView.ScrollMode.ScrollPerPixel
        )
        self.duplicates_table.setHorizontalScrollMode(
            QTableView.ScrollMode.ScrollPerPixel
        )

        # Configuración visual
        self.duplicates_table.setAlternatingRowColors(True)
        self.duplicates_table.setShowGrid(False)
        self.duplicates_table.setCornerButtonEnabled(False)
        self.duplicates_table.setSelectionBehavior(
            QTableView.SelectionBehavior.SelectRows
        )
        self.duplicates_table.setSelectionMode(
            QTableView.SelectionMode.ExtendedSelection
        )

        # Conectar doble clic en la tabla para manejar botón de eliminar
        self.duplicates_table.doubleClicked.connect(self.on_table_double_clicked)

    def setup_connections(self):
        """Configura las conexiones de señales"""
        self.select_folder_btn.clicked.connect(self.select_folder)
        self.scan_btn.clicked.connect(self.start_scan)
        self.select_all_btn.clicked.connect(self.select_all_duplicates)
        self.deselect_all_btn.clicked.connect(self.deselect_all_duplicates)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.move_btn.clicked.connect(self.move_selected)
        self.preview_toggle_btn.clicked.connect(self.toggle_preview_panel)
        self.export_action.triggered.connect(self.export_results)
        self.ignore_group_action.triggered.connect(self.ignore_selected_group)
        self.keep_selected_action.triggered.connect(
            self.mark_selected_as_preferred_original
        )
        self.task_center_action.triggered.connect(self.open_task_center)
        self.reset_columns_action.triggered.connect(self.reset_column_settings)

        # Conectar filtros
        # 🚀 MEJORA: Usar debouncing en filtros de texto para evitar búsquedas innecesarias
        self.min_size_spin.valueChanged.connect(self._debounced_filter)
        self.ext_filter_combo.currentTextChanged.connect(self._debounced_filter)
        self.recursive_cb.stateChanged.connect(self.on_recursive_changed)  # ✅ NUEVO

        # Conectar selector de método
        self.method_combo.currentIndexChanged.connect(self.on_method_changed)

        # Conectar cambios de selección para actualizar estadísticas
        self.duplicates_model.dataChanged.connect(self.on_selection_changed)
        self.duplicates_table.clicked.connect(self.update_preview_panel_from_index)

    def on_selection_changed(self, top_left, bottom_right, roles):
        """Maneja cambios en la selección de checkboxes"""
        # Solo actualizar si cambió el estado de checkboxes
        if Qt.ItemDataRole.CheckStateRole in roles:
            self.update_statistics_from_selection()

    def setup_context_menu(self):
        """Configura menú contextual para previsualización de imágenes"""
        self.duplicates_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.duplicates_table.customContextMenuRequested.connect(self.show_context_menu)

    def on_method_changed(self):
        """Maneja el cambio de método de detección"""
        method_index = self.method_combo.currentIndex()

        if method_index == 0:  # Ultra-rápido
            self.current_method = "fast"
            self.method_info.setText("Candidato: tamano + nombre + extension")
            self.scan_btn.setText("Analizar rapido")

        elif method_index == 1:  # Híbrido
            self.current_method = "hybrid"
            self.method_info.setText("Filtro rápido + comparación por hash")
            self.scan_btn.setText("Analizar hibrido")

        else:  # Profundo
            self.current_method = "deep"
            self.method_info.setText("Hash: contenido o muestras (>5000 MB)")
            self.scan_btn.setText("Analizar profundo")

        self.update_preview_button_state()

    def on_recursive_changed(self):
        """Maneja el cambio en la opción de búsqueda recursiva"""
        recursive_enabled = self.recursive_cb.isChecked()
        if recursive_enabled:
            self.log_message("🔄 Búsqueda recursiva ACTIVADA - Incluirá subcarpetas")
        else:
            self.log_message("📁 Búsqueda recursiva DESACTIVADA - Solo carpeta actual")

    def select_folder(self):
        """Selecciona carpeta o disco para analizar"""
        # Crear diálogo personalizado con botones descriptivos
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("🎯 Seleccionar Ámbito de Búsqueda")
        msg_box.setText("¿Qué quieres analizar?")
        msg_box.setInformativeText(
            "📂 CARPETA: Analiza solo una carpeta específica (recomendado)\n"
            "💿 DISCO: Analiza todo un disco/unidad (puede ser muy lento)"
        )
        msg_box.setIcon(QMessageBox.Icon.Question)

        # Botones personalizados con texto descriptivo
        carpeta_btn = msg_box.addButton("📂 Carpeta", QMessageBox.ButtonRole.YesRole)
        disco_btn = msg_box.addButton(
            "💿 Disco Completo", QMessageBox.ButtonRole.NoRole
        )
        msg_box.addButton("❌ Cancelar", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(carpeta_btn)

        msg_box.exec()
        clicked_button = msg_box.clickedButton()

        # Si canceló, salir
        if clicked_button.text() == "❌ Cancelar":
            return

        if clicked_button == carpeta_btn:
            # Seleccionar carpeta específica
            folder = QFileDialog.getExistingDirectory(
                self,
                "📂 Seleccionar carpeta específica para analizar",
                str(Path.home()),
                QFileDialog.Option.ShowDirsOnly,
            )
            scope_type = "CARPETA"
        else:
            # Seleccionar disco completo
            folder = QFileDialog.getExistingDirectory(
                self,
                "💿 Seleccionar disco completo (ej: C:) - ADVERTENCIA: Puede ser muy lento",
                "",
                QFileDialog.Option.ShowDirsOnly,
            )
            scope_type = "DISCO"

        if folder:
            self.current_folder = folder
            folder_display = self._format_folder_display(scope_type, folder)
            self.current_folder_label.set_path(folder_display, folder)
            self.scan_btn.setEnabled(True)
            self.apply_scan_button_style()  # ✅ NUEVO: Reaplicar estilo azul
            self.log_message(f"✅ {scope_type} seleccionada: {folder}")

            # Advertencia para discos completos
            if scope_type == "DISCO":
                QMessageBox.warning(
                    self,
                    "⚠️ Advertencia - Análisis de Disco Completo",
                    f"Has seleccionado analizar TODO el disco: {folder}\n\n"
                    f"⚠️ ADVERTENCIAS:\n"
                    f"• Puede tardar horas dependiendo del tamaño\n"
                    f"• Usa mucha CPU y disco durante el proceso\n"
                    f"• Se recomienda usar método ULTRA-RÁPIDO\n\n"
                    f"💡 CONSEJO: Considera analizar carpetas específicas en lugar de discos completos",
                )

    def start_scan(self):
        """Inicia el escaneo de duplicados"""
        if not self.current_folder:
            QMessageBox.warning(self, "Error", "Primero selecciona una carpeta o disco")
            return

        self.method_combo.setEnabled(False)
        self.result_status_label.setText("Analizando… La selección estará disponible al terminar.")
        self._result_method = self.current_method
        self.delete_btn.setEnabled(False)
        self.move_btn.setEnabled(False)

        # Limpiar resultados anteriores
        self.duplicates_data = {}
        # NO limpiar la tabla aquí - se limpiará en load_duplicates_data para evitar doble parpadeo
        self.clear_statistics()

        # Configurar interfaz para escaneo
        self.scan_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminado

        method_name = {
            "fast": "ULTRA-RÁPIDO",
            "hybrid": "HÍBRIDO",
            "deep": "PROFUNDO",
        }.get(self.current_method, "DESCONOCIDO")

        self.log_message(
            f"🚀 Iniciando escaneo {method_name} en: {self.current_folder}"
        )

        # Crear worker con método y configuración recursiva seleccionados
        recursive_enabled = self.recursive_cb.isChecked()
        self.scan_worker = DuplicateScanWorker(
            str(self.current_folder),
            method=self.current_method,
            recursive=recursive_enabled,  # ✅ NUEVO: Pasar opción recursiva
        )
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.error_occurred.connect(
            self.on_scan_error
        )  # ✅ Nombre correcto
        self.scan_worker.scan_progress.connect(self._handle_scan_progress)
        self.scan_worker.duplicates_found.connect(self.on_duplicates_found)

        # Log información de configuración
        recursive_text = (
            "RECURSIVA (incluye subcarpetas)"
            if recursive_enabled
            else "NO RECURSIVA (solo carpeta actual)"
        )
        self.log_message(f"🔄 Búsqueda {recursive_text}")

        self.scan_task_id = f"duplicates_scan_{int(datetime.now().timestamp())}"
        task_registry.start_task(
            self.scan_task_id, "Escaneo de duplicados", self.scan_worker.stop
        )
        self.scan_worker.start()

    def on_duplicates_found(self, duplicates_data, statistics):
        """Maneja duplicados encontrados en tiempo real - FIRMA CORRECTA"""
        self.duplicates_data = duplicates_data
        method = getattr(self, "_result_method", "fast")
        if method == "fast":
            self.result_status_label.setText("Candidatos por nombre, extensión y tamaño. El contenido todavía no está confirmado.")
        else:
            self.result_status_label.setText("Coincidencias por hash. Los archivos de más de 5000 MB se comparan mediante muestras y siguen siendo candidatos.")
        self.log_message(f"🔍 Encontrados {len(duplicates_data)} grupos de duplicados")

        # Actualizar estadísticas usando las CLAVES CORRECTAS del worker
        if statistics:
            # ✅ CLAVES CORRECTAS del get_statistics_fast()
            self.stats_labels["grupos"].setText(
                str(statistics.get("total_duplicate_groups", 0))
            )
            self.stats_labels["duplicados"].setText(
                str(statistics.get("total_duplicate_files", 0))
            )

            # Formatear espacio guardado
            space_mb = statistics.get("space_saved_mb", 0)
            if space_mb >= 1024:
                space_str = f"{space_mb / 1024:.1f} GB"
            else:
                space_str = f"{space_mb:.1f} MB"
            self.stats_labels["espacio"].setText(space_str)

            # Tiempo (por ahora placeholder)
            self.stats_labels["tiempo"].setText("< 1s")
        else:
            # Fallback si no hay estadísticas
            total_groups = len(
                [group for group in duplicates_data.values() if len(group) > 1]
            )
            total_duplicates = sum(
                len(paths) - 1 for paths in duplicates_data.values() if len(paths) > 1
            )
            self.stats_labels["grupos"].setText(str(total_groups))
            self.stats_labels["duplicados"].setText(str(total_duplicates))
            self.stats_labels["espacio"].setText("0 MB")
            self.stats_labels["tiempo"].setText("< 1s")

        # Poblar tabla
        self.populate_table()

    def on_scan_finished(self):
        """Maneja finalización del escaneo"""
        self.scan_btn.setEnabled(True)
        self.method_combo.setEnabled(True)
        if not self.duplicates_data:
            self.result_status_label.setText("Análisis terminado: no se encontraron coincidencias.")
        self.apply_scan_button_style()  # ✅ NUEVO: Reaplicar estilo azul
        self.progress_bar.setVisible(False)
        if self.scan_task_id:
            task_registry.finish_task(self.scan_task_id, "Completada")
            self.scan_task_id = None
        self.log_message("✅ Escaneo completado")

    def on_scan_error(self, error_message):
        """Maneja errores del escaneo"""
        self.scan_btn.setEnabled(True)
        self.method_combo.setEnabled(True)
        self.result_status_label.setText("No se pudo completar el análisis. Revisa la carpeta y vuelve a intentarlo.")
        self.apply_scan_button_style()  # ✅ NUEVO: Reaplicar estilo azul
        self.progress_bar.setVisible(False)
        if self.scan_task_id:
            task_registry.finish_task(self.scan_task_id, "Error")
            self.scan_task_id = None
        self.log_message(f"❌ Error en escaneo: {error_message}")
        QMessageBox.critical(
            self, "Error", f"Error durante el escaneo:\n{error_message}"
        )

    def clear_statistics(self):
        """Limpia las estadísticas"""
        for label in self.stats_labels.values():
            label.setText("0")

    def update_statistics_from_table(self):
        """Actualiza las estadísticas basándose en los datos actuales de la tabla"""
        try:
            if not hasattr(self, "duplicates_model") or not self.duplicates_model:
                return

            # Obtener datos del modelo actual (puede estar filtrado)
            model_data = (
                self.duplicates_model._data
                if hasattr(self.duplicates_model, "_data")
                else []
            )

            # Calcular estadísticas de la tabla actual
            total_groups = 0
            total_duplicates = 0
            total_selected = 0
            total_space = 0
            selected_space = 0

            # Procesar datos del modelo
            for row_data in model_data:
                if row_data:
                    # Contar grupos (cada fila es un archivo, agrupamos por hash)
                    hash_value = row_data.get("hash", "")
                    if hash_value:
                        # Solo contar una vez por grupo
                        if not hasattr(self, "_processed_hashes"):
                            self._processed_hashes = set()
                        if hash_value not in self._processed_hashes:
                            self._processed_hashes.add(hash_value)
                            total_groups += 1

                    # Contar duplicados (archivos que no son originales)
                    if not row_data.get("is_original", False):
                        total_duplicates += 1

                    # Contar seleccionados
                    if row_data.get("is_checked", False):
                        total_selected += 1
                        # Sumar espacio de seleccionados
                        file_size = row_data.get("size", 0)
                        selected_space += file_size

                    # Sumar espacio total
                    file_size = row_data.get("size", 0)
                    total_space += file_size

            # Limpiar hashes procesados para la próxima actualización
            if hasattr(self, "_processed_hashes"):
                delattr(self, "_processed_hashes")

            # Actualizar labels
            self.stats_labels["grupos"].setText(str(total_groups))
            self.stats_labels["duplicados"].setText(str(total_duplicates))
            self.stats_labels["seleccionados"].setText(str(total_selected))

            # Formatear espacio total
            if total_space >= 1024**3:
                space_str = f"{total_space / (1024**3):.1f} GB"
            elif total_space >= 1024**2:
                space_str = f"{total_space / (1024**2):.1f} MB"
            else:
                space_str = f"{total_space / 1024:.1f} KB"
            self.stats_labels["espacio"].setText(space_str)

            # Formatear espacio seleccionado
            if selected_space >= 1024**3:
                selected_space_str = f"{selected_space / (1024**3):.1f} GB"
            elif selected_space >= 1024**2:
                selected_space_str = f"{selected_space / (1024**2):.1f} MB"
            else:
                selected_space_str = f"{selected_space / 1024:.1f} KB"
            self.stats_labels["espacio_seleccionado"].setText(selected_space_str)

        except Exception as e:
            self.log_message(f"❌ Error actualizando estadísticas: {str(e)}")

    def update_statistics_from_selection(self):
        """Actualiza solo las estadísticas de selección cuando cambia la selección"""
        try:
            if not hasattr(self, "duplicates_model") or not self.duplicates_model:
                return

            # Obtener filas seleccionadas
            selected_rows = self.duplicates_model.get_checked_rows()
            total_selected = len(selected_rows)
            self.delete_btn.setEnabled(total_selected > 0 and not self.scan_task_id)
            self.move_btn.setEnabled(total_selected > 0 and not self.scan_task_id)
            selected_space = 0

            # Calcular espacio de seleccionados
            for row in selected_rows:
                row_data = self.duplicates_model.get_row_data(row)
                if row_data:
                    file_size = row_data.get("size", 0)
                    selected_space += file_size

            # Actualizar solo las estadísticas de selección
            self.stats_labels["seleccionados"].setText(str(total_selected))

            # Formatear espacio seleccionado
            if selected_space >= 1024**3:
                selected_space_str = f"{selected_space / (1024**3):.1f} GB"
            elif selected_space >= 1024**2:
                selected_space_str = f"{selected_space / (1024**2):.1f} MB"
            else:
                selected_space_str = f"{selected_space / 1024:.1f} KB"
            self.stats_labels["espacio_seleccionado"].setText(selected_space_str)

        except Exception as e:
            self.log_message(
                f"❌ Error actualizando estadísticas de selección: {str(e)}"
            )

    def populate_table(self):
        """🚀 MEJORA: Llena la tabla VIRTUALIZADA Y PAGINADA con los resultados"""
        self.populate_table_with_filtered_data(self.duplicates_data)

    def populate_table_with_filtered_data(self, data_to_use):
        """🚀 MEJORA: Llena la tabla VIRTUALIZADA Y PAGINADA con datos específicos"""
        self.log_message("📊 Iniciando población con virtualización + paginación...")

        try:
            if not data_to_use:
                self.log_message("⚠️ No hay datos de duplicados para mostrar")
                # Limpiar tabla completamente
                self.duplicates_model.clear_data()
                self.update_pagination_controls()
                return

            # Limpiar datos anteriores en una sola operación para evitar doble parpadeo
            self.duplicates_model.clear_data()

            # Obtener configuración de filtros
            min_size_mb = self.min_size_spin.value()
            min_size_bytes = min_size_mb * 1024 * 1024
            selected_ext = self.ext_filter_combo.currentData()

            self.log_message(
                f"🎛️ Aplicando filtros: Mín {min_size_mb}MB, Ext: {selected_ext or 'Todas'}"
            )

            # Preparar datos para el modelo
            model_data = []
            filtered_out_files = 0

            for hash_value, file_paths in data_to_use.items():
                if hash_value in self.ignored_hashes:
                    continue
                if len(file_paths) > 1:
                    files_info = []

                    for file_path in file_paths:
                        try:
                            if not file_path.exists():
                                continue

                            stat_info = file_path.stat()

                            # Aplicar filtros
                            if stat_info.st_size < min_size_bytes:
                                filtered_out_files += 1
                                continue

                            if (
                                selected_ext
                                and not file_path.suffix.lower() == selected_ext
                            ):
                                filtered_out_files += 1
                                continue

                            files_info.append(
                                {
                                    "path": str(file_path),
                                    "name": file_path.name,
                                    "location": str(file_path.parent),
                                    "size": stat_info.st_size,
                                    "date": stat_info.st_mtime,
                                    "hash": hash_value,
                                    "match_status": (
                                        "Candidato: contenido sin confirmar"
                                        if getattr(self, "_result_method", "fast") == "fast"
                                        else "Candidato: comparación por muestras"
                                        if stat_info.st_size > 5000 * 1024 * 1024
                                        else "Coincidencia por hash de contenido"
                                    ),
                                    "is_original": False,  # Se marcará después
                                }
                            )
                        except (OSError, AttributeError):
                            continue

                    # Solo procesar grupos con duplicados
                    if len(files_info) <= 1:
                        continue

                    preferred_path = self.preferred_originals.get(hash_value)
                    files_info.sort(key=lambda x: x["date"], reverse=True)
                    for file_info in files_info:
                        file_info["is_original"] = False
                    preferred_match = next(
                        (
                            file_info
                            for file_info in files_info
                            if file_info["path"] == preferred_path
                        ),
                        None,
                    )
                    if preferred_match:
                        preferred_match["is_original"] = True
                    else:
                        files_info[0]["is_original"] = True

                    # Agregar todos los archivos del grupo
                    model_data.extend(files_info)

            total_files = len(model_data)
            self.log_message(
                f"✅ Preparados {total_files} archivos para visualización PAGINADA"
            )
            self.log_message(f"🎯 Archivos filtrados: {filtered_out_files}")

            if total_files == 0:
                self.log_message("⚠️ No se encontraron archivos que pasen los filtros")
                # Limpiar tabla completamente
                self.duplicates_model.clear_data()
                self.update_pagination_controls()
                return

            # Cargar datos en el modelo PAGINADO (solo muestra 1000 a la vez)
            self.duplicates_model.load_full_data(model_data)
            self.update_pagination_controls()

            # ✅ CRÍTICO: Aplicar anchos de columna DESPUÉS de cargar datos
            self.apply_column_widths()
            self.log_message(
                f"🚀 Tabla virtualizada lista - Mostrando página 1 de {self.duplicates_model.get_page_info()['total_pages']}"
            )
            self.preview_panel.setPlainText(
                "Selecciona un archivo para ver detalles del grupo."
            )

        except Exception as e:
            self.log_message(f"❌ Error en populate_table: {str(e)}")
            import traceback

            self.log_message(f"🔍 Traceback: {traceback.format_exc()}")

    def go_to_next_page(self):
        """🚀 MEJORA: Avanza a la siguiente página"""
        if self.duplicates_model.next_page():
            self.update_pagination_controls()
            # ✅ Aplicar anchos después de cambiar de página
            self.apply_column_widths()
            self.log_message(
                f"📄 Página {self.duplicates_model.get_page_info()['current_page']} cargada"
            )

    def go_to_previous_page(self):
        """🚀 MEJORA: Retrocede a la página anterior"""
        if self.duplicates_model.previous_page():
            self.update_pagination_controls()
            # ✅ Aplicar anchos después de cambiar de página
            self.apply_column_widths()
            self.log_message(
                f"📄 Página {self.duplicates_model.get_page_info()['current_page']} cargada"
            )

    def update_pagination_controls(self):
        """🚀 MEJORA: Actualiza los controles de paginación"""
        page_info = self.duplicates_model.get_page_info()

        # Actualizar label
        self.page_info_label.setText(
            f"Página {page_info['current_page']} de {page_info['total_pages']} "
            f"({page_info['showing_from']}-{page_info['showing_to']} de {page_info['total_items']})"
        )

        # Habilitar/deshabilitar botones
        self.prev_page_btn.setEnabled(page_info["current_page"] > 1)
        self.next_page_btn.setEnabled(
            page_info["current_page"] < page_info["total_pages"]
        )

    def _debounced_filter(self):
        """🚀 MEJORA: Inicia un temporizador para debouncing de búsquedas"""
        # Reiniciar el timer cada vez que cambia algo
        self.search_timer.start(self.search_delay_ms)

    def _execute_search(self):
        """🚀 MEJORA: Ejecuta la búsqueda real después del debouncing"""
        self.apply_filters()

    def on_filter_changed(self):
        """Maneja el cambio en el filtro de búsqueda rápida"""
        filter_text = self.filter_input.text().strip()

        if not self.duplicates_data:
            return

        # Aplicar filtro en tiempo real
        self.apply_quick_filter(filter_text)

    def apply_quick_filter(self, filter_text):
        """Aplica filtro rápido por nombre o extensión - VERSIÓN SIMPLE Y RÁPIDA"""
        if not filter_text:
            # Sin filtro, mostrar todos
            filtered_data = self.duplicates_data
        else:
            # Filtrar por nombre o extensión - SIMPLE Y RÁPIDO
            filtered_data = {}
            filter_lower = filter_text.lower()

            for hash_value, file_paths in self.duplicates_data.items():
                if len(file_paths) > 1:  # Solo grupos de duplicados
                    filtered_paths = []
                    for file_path in file_paths:
                        # Verificar que el archivo existe
                        if not file_path.exists():
                            continue

                        # Extraer nombre del archivo de la ruta
                        filename = os.path.basename(file_path).lower()

                        # Filtro simple: contiene el texto (coincidencia parcial)
                        if filter_lower in filename:
                            filtered_paths.append(file_path)

                    # Solo incluir grupos que tengan al menos un archivo
                    if filtered_paths:
                        filtered_data[hash_value] = filtered_paths

        # Actualizar contador
        total_files = sum(len(paths) for paths in filtered_data.values())
        self.filter_count_label.setText(f"({total_files} archivos)")

        # Actualizar tabla con datos filtrados
        self.populate_table_with_filtered_data(filtered_data)

        # Actualizar estadísticas basándose en los datos filtrados
        self.update_statistics_from_table()

        # Forzar actualización de la vista
        self.duplicates_table.viewport().update()

    def apply_filters(self):
        """Aplica filtros a la vista de duplicados - AHORA INTEGRADO EN populate_table"""
        if not self.duplicates_data:
            self.log_message("⚠️ No hay datos para filtrar")
            return

        self.log_message("🎛️ Reaplicando filtros...")

        # Los filtros ahora se aplican DENTRO de populate_table
        # antes de crear las filas, no después
        self.populate_table()

    def refresh_view(self):
        """Actualiza la vista con filtros aplicados"""
        self.apply_filters()

    def select_all_duplicates(self):
        """🚀 MEJORA: Selecciona SOLO los duplicados usando el modelo"""
        self.duplicates_model.check_all_duplicates()
        self.log_message("✅ Duplicados seleccionados (originales sin marcar)")
        # Actualizar estadísticas de selección
        self.update_statistics_from_selection()

    def deselect_all_duplicates(self):
        """🚀 MEJORA: Deselecciona TODOS los archivos usando el modelo"""
        self.duplicates_model.uncheck_all()
        self.log_message("❌ Todos los archivos deseleccionados")
        # Actualizar estadísticas de selección
        self.update_statistics_from_selection()

    def delete_selected(self):
        """🚀 MEJORA: Elimina los archivos seleccionados usando el modelo"""
        selected_files, selected_info = self._get_selected_file_entries()

        self.log_message(f"✅ Encontrados {len(selected_files)} archivos seleccionados")

        if not selected_files:
            QMessageBox.information(
                self,
                "Sin Selección",
                f"❌ No hay archivos seleccionados para eliminar.\n\n"
                f"💡 Marca los checkboxes de los archivos que quieres eliminar:\n"
                f"   🟢 VERDES = Originales (más recientes)\n"
                f"   🔴 ROJOS = Duplicados (más antiguos)\n\n"
                f"Puedes eliminar cualquiera de los dos tipos.",
            )
            return
        selected_set = set(selected_files)
        affected = [paths for paths in self.duplicates_data.values()
                    if any(path in selected_set for path in paths)]
        retained = [path for paths in affected for path in paths
                    if path not in selected_set and path.exists()]
        empty_groups = sum(not any(path not in selected_set and path.exists() for path in paths)
                           for paths in affected)
        retained_text = "\n".join(f"• {path}" for path in retained[:10]) or "Ninguna copia."
        if empty_groups:
            retained_text += f"\nAtención: {empty_groups} grupos quedarán sin ninguna copia en su carpeta."

        # Mostrar lista detallada de archivos a eliminar
        file_list = "\n".join(
            [
                f"• {info['name']} ({info['size']}) - {info['location']}"
                for info in selected_info[:10]
            ]
        )  # Máximo 10 para no saturar
        if len(selected_info) > 10:
            file_list += f"\n... y {len(selected_info) - 10} archivos más"

        # Confirmar eliminación con detalles
        reply = QMessageBox.question(
            self,
            "Confirmar retirada de archivos",
            f"Se retirarán {len(selected_files)} archivos a la papelera. Si no hay soporte, se moverán a .quarantine junto a cada archivo.\n\n"
            f"📂 Archivos a eliminar:\n{file_list}\n\n"
            f"Copias que se conservan sin marcar:\n{retained_text}\n\n"
            "Revisa los candidatos: una coincidencia por nombre o muestras no confirma contenido idéntico.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.log_message(
                f"🗑️ Iniciando eliminación de {len(selected_files)} archivos duplicados..."
            )

            # IMPLEMENTAR ELIMINACIÓN REAL
            deleted_count = 0
            error_count = 0

            for file_path in selected_files:
                try:
                    if self.transaction_manager.safe_delete_file(
                        file_path, use_trash=True
                    ):
                        deleted_count += 1
                        self.log_message(f"✅ {file_path.name} retirado a: {self.transaction_manager.last_removal_destination}")
                    else:
                        error_count += 1
                        reason = (
                            self.transaction_manager.last_error
                            or "motivo no disponible"
                        )
                        self.log_message(
                            f"❌ No se pudo eliminar: {file_path.name} ({reason})"
                        )

                except Exception as e:
                    error_count += 1
                    self.log_message(f"❌ Error eliminando {file_path.name}: {str(e)}")

            # Mostrar resultado
            if deleted_count > 0:
                QMessageBox.information(
                    self,
                    "✅ Eliminación Completada",
                    f"✅ Procesados correctamente: {deleted_count} archivos\n"
                    f"❌ Errores: {error_count} archivos\n\n"
                    f"💡 Actualiza la vista para ver los cambios.",
                )

                # Refrescar vista automáticamente
                self.log_message("🔄 Refrescando vista...")
                self.populate_table()

                # Actualizar filtro si está activo
                if hasattr(self, "filter_input") and self.filter_input.text().strip():
                    self.log_message("🔄 Actualizando filtro después de eliminación...")
                    self.apply_quick_filter(self.filter_input.text().strip())
            else:
                QMessageBox.warning(
                    self,
                    "⚠️ Error en Eliminación",
                    f"❌ No se pudo eliminar ningún archivo\n"
                    f"Errores: {error_count}\n\n"
                    f"Verifica los permisos de los archivos.",
                )

    def move_selected(self):
        """Mueve los archivos duplicados seleccionados"""
        selected_files, _ = self._get_selected_file_entries()
        if not selected_files or not self.current_folder:
            QMessageBox.information(
                self, "Información", "Selecciona archivos duplicados antes de moverlos."
            )
            return

        quarantine_dir = Path(self.current_folder) / ".duplicates_quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)

        moved_count = 0
        for file_path in selected_files:
            destination = quarantine_dir / file_path.name
            counter = 1
            while destination.exists():
                destination = (
                    quarantine_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                )
                counter += 1
            if self.transaction_manager.safe_move_file(file_path, destination):
                moved_count += 1
                self.log_message(f"📁 Movido a cuarentena: {file_path.name}")

        if moved_count:
            QMessageBox.information(
                self,
                "Cuarentena completada",
                f"Se movieron {moved_count} archivos a {quarantine_dir}.",
            )
            self.populate_table()

    def _get_selected_file_entries(self):
        """Obtiene archivos seleccionados y su metadata legible."""
        selected_files = []
        selected_info = []

        self.log_message("🔍 Verificando archivos seleccionados...")
        for row in self.duplicates_model.get_checked_rows():
            row_data = self.duplicates_model.get_row_data(row)
            if not row_data:
                continue
            try:
                file_path = Path(row_data.get("path", ""))
                if file_path.exists() and file_path.is_file():
                    selected_files.append(file_path)
                    size_mb = row_data.get("size", 0) / (1024 * 1024)
                    selected_info.append(
                        {
                            "name": file_path.name,
                            "path": file_path,
                            "size": f"{size_mb:.2f} MB",
                            "location": row_data.get("location", ""),
                        }
                    )
                else:
                    self.log_message(f"⚠️ Archivo no encontrado: {file_path}")
            except Exception as e:
                self.log_message(f"❌ Error procesando fila {row}: {str(e)}")

        return selected_files, selected_info

    def show_context_menu(self, position):
        """Muestra menú contextual para previsualizar imágenes"""
        try:
            # Obtener la fila donde se hizo clic (QTableView)
            index = self.duplicates_table.indexAt(position)
            if not index.isValid():
                return

            row = index.row()

            # Obtener información del archivo usando el modelo
            model = self.duplicates_table.model()
            name_data = model.data(model.index(row, 1), Qt.ItemDataRole.DisplayRole)
            location_data = model.data(model.index(row, 2), Qt.ItemDataRole.DisplayRole)

            if not name_data or not location_data:
                return

            # Extraer nombre sin emojis
            file_name_raw = str(name_data)
            if file_name_raw.startswith("🟢 ") or file_name_raw.startswith("🔴 "):
                file_name = file_name_raw[2:]
            else:
                file_name = file_name_raw

            # Construir ruta completa
            location_path = str(location_data)
            file_path = Path(location_path) / file_name

            # Crear menú contextual
            menu = QMenu(self)
            apply_menu_surface(menu)

            # Verificar tipo de archivo y agregar acciones apropiadas
            file_ext = file_path.suffix.lower()

            # Acciones para imágenes
            image_extensions = {
                ".jpg",
                ".jpeg",
                ".png",
                ".gif",
                ".bmp",
                ".webp",
                ".tiff",
                ".ico",
            }
            if file_ext in image_extensions:
                preview_action = QAction("🖼️ Previsualizar imagen", self)
                preview_action.triggered.connect(lambda: self.preview_image(file_path))
                menu.addAction(preview_action)

            # Acciones para video
            video_extensions = {
                ".mp4",
                ".avi",
                ".mkv",
                ".mov",
                ".wmv",
                ".flv",
                ".webm",
                ".m4v",
            }
            if file_ext in video_extensions:
                play_video_action = QAction("🎬 Reproducir video", self)
                play_video_action.triggered.connect(lambda: self.play_video(file_path))
                menu.addAction(play_video_action)

            # Acción para abrir archivo (siempre disponible)
            open_file_action = QAction("📄 Abrir archivo", self)
            open_file_action.triggered.connect(lambda: self.open_file(file_path))
            menu.addAction(open_file_action)

            # Acción para abrir ubicación (siempre disponible)
            open_folder_action = QAction("📁 Abrir ubicación", self)
            open_folder_action.triggered.connect(
                lambda: self.open_file_location(file_path)
            )
            menu.addAction(open_folder_action)

            # Mostrar menú
            menu.exec(self.duplicates_table.mapToGlobal(position))

        except Exception as e:
            self.log_message(f"❌ Error en menú contextual: {str(e)}")

    def preview_image(self, file_path):
        """Muestra previsualización de imagen en ventana emergente"""
        try:
            if not file_path.exists():
                QMessageBox.warning(
                    self, "Error", f"El archivo no existe:\n{file_path}"
                )
                return

            # Crear ventana de previsualización
            preview_window = QDialog(self)
            preview_window.setWindowTitle(f"🖼️ Previsualización: {file_path.name}")
            preview_window.setModal(True)
            preview_window.resize(800, 600)

            layout = QVBoxLayout(preview_window)

            # Información del archivo
            info_label = QLabel(
                f"📂 {file_path.parent}\n📄 {file_path.name}\n💾 {self.format_file_size(file_path.stat().st_size)}"
            )
            layout.addWidget(info_label)

            # ScrollArea para la imagen
            scroll_area = QScrollArea()
            scroll_area.setWidgetResizable(True)
            scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Label para mostrar la imagen
            image_label = QLabel()
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # Cargar y mostrar imagen
            pixmap = QPixmap(str(file_path))
            if pixmap.isNull():
                image_label.setText("❌ No se pudo cargar la imagen")
            else:
                # Escalar imagen si es muy grande
                max_size = 700
                if pixmap.width() > max_size or pixmap.height() > max_size:
                    pixmap = pixmap.scaled(
                        max_size,
                        max_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )

                image_label.setPixmap(pixmap)

            scroll_area.setWidget(image_label)
            layout.addWidget(scroll_area)

            # Botón cerrar
            close_btn = QPushButton("✖️ Cerrar")
            close_btn.clicked.connect(preview_window.close)
            layout.addWidget(close_btn)

            # Mostrar ventana
            preview_window.exec()

        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Error mostrando previsualización:\n{str(e)}"
            )
            self.log_message(f"❌ Error en preview_image: {str(e)}")

    def play_video(self, file_path):
        """Reproduce archivo de video"""
        try:
            import subprocess
            import sys

            if not file_path.exists():
                QMessageBox.warning(
                    self, "Error", f"El archivo no existe:\n{file_path}"
                )
                return

            # Abrir con reproductor por defecto
            if sys.platform == "win32":
                os.startfile(str(file_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(file_path)])
            else:
                subprocess.Popen(["xdg-open", str(file_path)])

            self.log_message(f"🎬 Reproduciendo video: {file_path.name}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error reproduciendo video:\n{str(e)}")
            self.log_message(f"❌ Error en play_video: {str(e)}")

    def open_file(self, file_path):
        """Abre archivo con aplicación por defecto"""
        try:
            import subprocess
            import sys

            if not file_path.exists():
                QMessageBox.warning(
                    self, "Error", f"El archivo no existe:\n{file_path}"
                )
                return

            # Abrir con aplicación por defecto
            if sys.platform == "win32":
                os.startfile(str(file_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(file_path)])
            else:
                subprocess.Popen(["xdg-open", str(file_path)])

            self.log_message(f"📄 Abriendo archivo: {file_path.name}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error abriendo archivo:\n{str(e)}")
            self.log_message(f"❌ Error en open_file: {str(e)}")

    def open_file_location(self, file_path):
        """Abre la ubicación del archivo en el explorador"""
        try:
            import subprocess
            import sys

            if sys.platform == "win32":
                # Windows - abrir explorer y seleccionar archivo
                subprocess.Popen(f'explorer /select,"{file_path}"')
            elif sys.platform == "darwin":
                # macOS
                subprocess.Popen(["open", "-R", str(file_path)])
            else:
                # Linux
                subprocess.Popen(["xdg-open", str(file_path.parent)])

        except Exception as e:
            QMessageBox.warning(
                self, "Error", f"No se pudo abrir la ubicación:\n{str(e)}"
            )

    def on_table_double_clicked(self, index):
        """Maneja doble clic en la tabla, especialmente en la columna de acciones"""
        try:
            row = index.row()
            col = index.column()

            # Solo manejar doble clic en la columna de acciones (columna 6)
            if col == 6:
                self.delete_single_file(row)

        except Exception as e:
            self.log_message(f"❌ Error en on_table_double_clicked: {str(e)}")

    def delete_single_file(self, row):
        """Elimina un archivo individual"""
        try:
            row_data = self.duplicates_model.get_row_data(row)
            if not row_data or not row_data.get("path"):
                return
            file_path = Path(row_data["path"])
            file_name = file_path.name
            location_path = str(file_path.parent)

            # Confirmar eliminación
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Confirmar Eliminación")
            msg_box.setText("¿Retirar este archivo a la papelera? Si no hay soporte, se moverá a .quarantine junto a su carpeta. Las demás copias se conservan.")
            msg_box.setInformativeText(f"📄 {file_name}\n📂 {location_path}")
            msg_box.setIcon(QMessageBox.Icon.Question)

            # Botones personalizados
            delete_btn = msg_box.addButton(
                "Retirar archivo", QMessageBox.ButtonRole.AcceptRole
            )
            cancel_btn = msg_box.addButton(
                "❌ Cancelar", QMessageBox.ButtonRole.RejectRole
            )
            msg_box.setDefaultButton(cancel_btn)

            msg_box.exec()
            clicked_button = msg_box.clickedButton()

            if clicked_button == cancel_btn:
                return

            if clicked_button == delete_btn:
                # Eliminar archivo
                if file_path.exists():
                    if self.transaction_manager.safe_delete_file(
                        file_path, use_trash=True
                    ):
                        self.log_message(f"{file_name} retirado a: {self.transaction_manager.last_removal_destination}")
                    else:
                        QMessageBox.warning(
                            self,
                            "Error",
                            f"No se pudo eliminar {file_name}:\n{self.transaction_manager.last_error or 'motivo no disponible'}",
                        )
                        return

                    # Refrescar la tabla
                    self.log_message("🔄 Refrescando vista...")
                    self.populate_table()

                    # Actualizar filtro si está activo
                    if (
                        hasattr(self, "filter_input")
                        and self.filter_input.text().strip()
                    ):
                        self.log_message(
                            "🔄 Actualizando filtro después de eliminación..."
                        )
                        self.apply_quick_filter(self.filter_input.text().strip())
                else:
                    QMessageBox.warning(
                        self, "Error", f"El archivo no existe:\n{file_path}"
                    )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error eliminando archivo:\n{str(e)}")
            self.log_message(f"❌ Error en delete_single_file: {str(e)}")

    def format_file_size(self, size_bytes):
        """Formatea el tamaño del archivo de manera legible"""
        if size_bytes < 1024:
            return f"{size_bytes} bytes"
        elif size_bytes < 1024**2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024**3:
            return f"{size_bytes / (1024**2):.1f} MB"
        else:
            return f"{size_bytes / (1024**3):.1f} GB"

    def export_results(self):
        """Exporta los resultados a un archivo"""
        if not self.duplicates_data:
            QMessageBox.information(
                self, "Información", "No hay resultados para exportar"
            )
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar Resultados",
            f"duplicados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Archivos de texto (*.txt)",
        )

        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("REPORTE DE ARCHIVOS DUPLICADOS\n")
                    f.write("=" * 50 + "\n\n")

                    for i, (hash_val, paths) in enumerate(
                        self.duplicates_data.items(), 1
                    ):
                        if len(paths) > 1:
                            f.write(f"GRUPO {i} ({len(paths)} archivos):\n")
                            f.write(f"Hash/ID: {hash_val}\n")
                            for path in paths:
                                f.write(f"  • {path}\n")
                            f.write("\n")

                self.log_message(f"📄 Resultados exportados a: {file_path}")
                QMessageBox.information(
                    self,
                    "Éxito",
                    f"Resultados exportados correctamente a:\n{file_path}",
                )
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Error al exportar: {str(e)}")

    def update_preview_panel_from_index(self, index):
        """Actualiza el panel lateral de preview/detalle."""
        if not index.isValid():
            return
        row_data = self.duplicates_model.get_row_data(index.row())
        if not row_data:
            return
        status = (
            "Original preferido"
            if row_data.get("is_original")
            else "Duplicado candidato"
        )
        self.preview_panel.setPlainText(
            "\n".join(
                [
                    f"Nombre: {row_data.get('name', 'N/A')}",
                    f"Estado: {status}",
                    f"Comparación: {row_data.get('match_status', 'Candidato: contenido sin confirmar')}",
                    f"Ruta: {row_data.get('path', 'N/A')}",
                    f"Grupo hash: {row_data.get('hash', 'N/A')}",
                    f"Tamaño: {self.format_file_size(row_data.get('size', 0))}",
                    f"Fecha: {datetime.fromtimestamp(row_data.get('date', 0)).strftime('%Y-%m-%d %H:%M') if row_data.get('date') else 'N/A'}",
                    "",
                    "Acciones sugeridas:",
                    "- Marca como original preferido si este archivo debe conservarse.",
                    "- Ignora el grupo si es un conjunto legítimo que no quieres revisar.",
                    "- Usa cuarentena para revisar fuera de la carpeta principal.",
                ]
            )
        )

    def toggle_preview_panel(self):
        """Muestra u oculta el panel lateral de vista previa."""
        if self.preview_panel.isVisible():
            self._last_preview_sizes = self.table_splitter.sizes()
            self.preview_visible = False
            self.preview_panel.hide()
            self.table_splitter.setSizes([1, 0])
        else:
            self.preview_visible = True
            self.preview_panel.show()
            restored_sizes = self._last_preview_sizes or [900, 260]
            self.table_splitter.setSizes(restored_sizes)
        self.settings.setValue("preview_visible", self.preview_visible)
        self.settings.sync()
        self.update_preview_button_state()

    def update_preview_button_state(self):
        """Actualiza el texto del boton de preview."""
        if not hasattr(self, "preview_toggle_btn") or self.preview_toggle_btn is None:
            return
        self.preview_toggle_btn.setText(
            "Ocultar panel" if self.preview_visible else "Mostrar panel"
        )

    def ignore_selected_group(self):
        """Ignora el grupo hash del archivo seleccionado."""
        index = self.duplicates_table.currentIndex()
        if not index.isValid():
            return
        row_data = self.duplicates_model.get_row_data(index.row())
        if not row_data:
            return
        hash_value = row_data.get("hash")
        if not hash_value:
            return
        self.ignored_hashes.add(hash_value)
        self.app_config.set_ignored_duplicate_hashes(list(self.ignored_hashes))
        self.log_message(f"🙈 Grupo ignorado: {hash_value}")
        self.populate_table()

    def mark_selected_as_preferred_original(self):
        """Marca el archivo actual como original preferido del grupo."""
        index = self.duplicates_table.currentIndex()
        if not index.isValid():
            return
        row_data = self.duplicates_model.get_row_data(index.row())
        if not row_data:
            return
        hash_value = row_data.get("hash")
        path = row_data.get("path")
        if not hash_value or not path:
            return
        self.preferred_originals[hash_value] = path
        self.app_config.set_preferred_original(hash_value, path)
        self.log_message(
            f"🟢 Original preferido actualizado para {hash_value}: {Path(path).name}"
        )
        self.populate_table()

    def open_task_center(self):
        """Abre el centro de tareas."""
        TaskCenterDialog(self).exec()

    def _handle_scan_progress(self, message: str):
        """Sincroniza el progreso del escaneo con el centro de tareas."""
        self.log_message(message)
        if self.scan_task_id:
            task_registry.update_task(self.scan_task_id, message)

    def log_message(self, message: str):
        """Añade un mensaje al log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        level_color = "#1976d2"
        if "❌" in message or "Error" in message:
            level_color = "#c62828"
        elif "⚠️" in message:
            level_color = "#ed6c02"
        elif "✅" in message:
            level_color = "#2e7d32"
        self.log_text.append(
            f"<span style='color:#888'>[{timestamp}]</span> "
            f"<span style='color:{level_color}'>{html.escape(message)}</span>"
        )

        # Hacer scroll automático al final
        cursor = self.log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)

        # Emitir señal de estado
        self.status_update.emit(message)

    def on_column_resized(self, logical_index, old_size, new_size):
        """Se ejecuta cuando el usuario redimensiona una columna"""
        self.log_message(
            f"📏 Columna {logical_index} redimensionada: {old_size}px → {new_size}px"
        )
        self.save_column_settings()

    def on_column_moved(self, logical_index, old_visual_index, new_visual_index):
        """Se ejecuta cuando el usuario reordena columnas"""
        self.log_message(
            f"🔄 Columna movida desde posición {old_visual_index} → {new_visual_index}"
        )
        self.save_column_settings()

    def on_header_clicked(self, logical_index):
        """Maneja el clic en el encabezado de una columna para ordenar"""
        # Solo permitir ordenamiento en columnas de tamaño y fecha
        if logical_index in [3, 4]:  # Tamaño (3) y Fecha (4)
            # Obtener información de ordenamiento actual
            sort_info = self.duplicates_model.get_sort_info()

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

            # Aplicar ordenamiento
            self.duplicates_model.sort(logical_index, new_order)

            # Actualizar indicador visual
            header = self.duplicates_table.horizontalHeader()
            header.setSortIndicator(logical_index, new_order)

            # Actualizar paginación
            self.update_pagination_controls()

            self.log_message(
                f"📊 Ordenando por columna {logical_index} ({'descendente' if new_order == Qt.SortOrder.DescendingOrder else 'ascendente'})"
            )

    def save_column_settings(self):
        """Guarda el estado actual de las columnas"""
        try:
            header = self.duplicates_table.horizontalHeader()

            # Guardar anchos de columnas
            column_widths = {}
            for i in range(self.duplicates_table.model().columnCount()):
                column_widths[str(i)] = header.sectionSize(i)

            # Guardar orden visual de columnas
            column_order = []
            for i in range(self.duplicates_table.model().columnCount()):
                column_order.append(header.visualIndex(i))

            # Guardar en configuración persistente
            self.settings.setValue("column_widths", column_widths)
            self.settings.setValue("column_order", column_order)
            self.settings.sync()  # Forzar guardado inmediato

            self.log_message("💾 Estado de columnas guardado automáticamente")

        except Exception as e:
            self.log_message(f"❌ Error guardando estado de columnas: {str(e)}")

    def load_column_settings(self):
        """Carga el estado guardado de las columnas"""
        try:
            header = self.duplicates_table.horizontalHeader()
            self.preview_visible = self.settings.value(
                "preview_visible", self.preview_visible, type=bool
            )
            self.preview_panel.setVisible(self.preview_visible)
            if self.preview_visible:
                self.table_splitter.setSizes(self._last_preview_sizes)
            else:
                self.table_splitter.setSizes([1, 0])
            self.update_preview_button_state()

            # Cargar anchos de columnas
            saved_widths = self.settings.value("column_widths", {})
            if saved_widths:
                for column_str, width in saved_widths.items():
                    try:
                        column_index = int(column_str)
                        if (
                            0
                            <= column_index
                            < self.duplicates_table.model().columnCount()
                        ):
                            self.duplicates_table.setColumnWidth(
                                column_index, int(width)
                            )
                    except (ValueError, TypeError):
                        continue

            # Cargar orden de columnas
            saved_order = self.settings.value("column_order", [])
            if (
                saved_order
                and len(saved_order) == self.duplicates_table.model().columnCount()
            ):
                try:
                    for logical_index, visual_index in enumerate(saved_order):
                        header.moveSection(
                            header.visualIndex(logical_index), int(visual_index)
                        )
                except (ValueError, TypeError):
                    pass

            if saved_widths or saved_order:
                self.log_message(
                    "📋 Estado de columnas restaurado desde configuración anterior"
                )
            else:
                self.log_message("📋 Usando configuración de columnas por defecto")

        except Exception as e:
            self.log_message(
                f"⚠️ Error cargando estado de columnas: {str(e)} - Usando valores por defecto"
            )

    def reset_column_settings(self):
        """Restaura las columnas a su configuración por defecto"""
        try:
            # Aplicar anchos por defecto
            for column, width in self.default_column_widths.items():
                self.duplicates_table.setColumnWidth(column, width)

            # Restaurar orden original
            header = self.duplicates_table.horizontalHeader()
            for i in range(self.duplicates_table.model().columnCount()):
                header.moveSection(header.visualIndex(i), i)

            # Limpiar configuración guardada
            self.settings.remove("column_widths")
            self.settings.remove("column_order")
            self.settings.remove("preview_visible")
            self.settings.sync()
            self.preview_visible = True
            self.preview_panel.show()
            self.table_splitter.setSizes([900, 260])
            self.update_preview_button_state()

            self.log_message("🔄 Columnas restauradas a configuración por defecto")

        except Exception as e:
            self.log_message(f"❌ Error restaurando columnas: {str(e)}")

    def apply_scan_button_style(self):
        """Mantiene refresco visual sin volver a introducir estilos inline."""
        self.scan_btn.update()
        self.scan_btn.repaint()
