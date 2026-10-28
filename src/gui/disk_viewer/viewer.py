"""Visor de Discos: lista de unidades, panel de detalle y controlador en hilos."""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime
from typing import Dict, Optional, Tuple

import psutil
from PyQt6.QtCore import QCoreApplication, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
                             QSizePolicy, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from src.core.disk_manager import DiskInfo
from src.gui.disk_viewer.controller import DiskReportController
from src.gui.disk_viewer.detail_panel import DiskDetailPanel
from src.gui.disk_viewer.disk_list import DiskCardGrid
from src.gui.disk_viewer.health_renderer import (render_basic_html, render_content_html, render_health_html,
                                                 smart_metric_texts)
from src.gui.disk_viewer.styles import fluent_palette, legacy_palette, legacy_stylesheet
from src.gui.v2.theme import apply_control_sizes, html_type_scale
from src.utils.app_config import AppConfig
from src.utils.formatting import format_bytes

logger = logging.getLogger(__name__)

CONTENT_TTL = 120.0
STATUS_INTERVAL_MS = 5000


class DiskViewer(QWidget):
    """Widget principal para visualizar y gestionar discos del sistema"""

    disk_selected = pyqtSignal(str)  # Ruta del disco elegido para organizar
    analysis_requested = pyqtSignal(str)
    disks_refreshed = pyqtSignal(object)  # Snapshot existente, sin lecturas adicionales

    def __init__(self, parent=None, disk_manager=None):
        super().__init__(parent)
        self.disk_manager = disk_manager
        self.current_selection: Optional[str] = None
        self.available_disks: tuple = ()
        self.disks_updated_at: Optional[datetime] = None
        self.disks_refresh_error: Optional[str] = None
        self._fallback_config: Optional[AppConfig] = None
        self._shown_disk: Optional[DiskInfo] = None
        self._last_report = None
        self._report_request = 0
        self._content_request = 0
        self._elevated_request: Optional[int] = None
        self._content_cache: Dict[str, Tuple[dict, float]] = {}
        self._closed = False

        self.controller = DiskReportController(self)
        # Siempre en cola: el resultado nunca llega antes de conocer el id de petición.
        queued = Qt.ConnectionType.QueuedConnection
        self.controller.report_ready.connect(self._on_report_ready, queued)
        self.controller.content_ready.connect(self._on_content_ready, queued)
        self.controller.elevated_ready.connect(self._on_elevated_ready, queued)

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(STATUS_INTERVAL_MS)
        self.status_timer.timeout.connect(self.update_system_info)
        psutil.cpu_percent(interval=None)  # Primera lectura de referencia (no bloquea)

        self.init_ui()
        self.setup_connections()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)
        if self.disk_manager:
            self.refresh_disks()
        self.apply_theme_styles(self.get_current_theme_name())

    # ------------------------------------------------------------------ UI
    def init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        header = QFrame()
        header.setObjectName("system_info_group")
        self.unified_header = header
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 8, 14, 8)
        header_layout.setSpacing(12)
        self.system_info_label = QLabel("Pulsa Actualizar para consultar las unidades.")
        self.system_info_label.setObjectName("system_info_label")
        self.system_info_label.setToolTip("Uso actual de procesador y memoria, número de unidades y modo de trabajo.")
        self.system_info_label.setMinimumWidth(0)
        header_layout.addWidget(self.system_info_label, 1)
        self.safe_mode_label = QLabel("Modo seguro")
        self.safe_mode_label.setObjectName("safe_mode_label")
        self.safe_mode_label.setToolTip("Protege las unidades: sólo se analiza y se muestra información")
        header_layout.addWidget(self.safe_mode_label)
        self.safe_mode_checkbox = QCheckBox("Solo lectura")
        self.safe_mode_checkbox.setObjectName("safe_mode_checkbox")
        self.safe_mode_checkbox.setToolTip("Sólo permite análisis y visualización")
        self.safe_mode_checkbox.setChecked(True)
        self.safe_mode_checkbox.toggled.connect(self.on_safe_mode_changed)
        header_layout.addWidget(self.safe_mode_checkbox)
        self.refresh_btn = QPushButton("Actualizar")
        self.refresh_btn.setObjectName("refresh_btn")
        self.refresh_btn.setToolTip("Vuelve a leer las unidades y sus datos SMART")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        header_layout.addWidget(self.refresh_btn)
        main_layout.addWidget(header)

        # Tabla interna (oculta): modelo de selección y compatibilidad.
        self.disks_table = QTableWidget(self)
        self.disks_table.setColumnCount(8)
        self.disks_table.setHorizontalHeaderLabels(
            ["Unidad", "Punto de montaje", "Total", "Usado", "Libre", "% de uso", "Sistema", "Tipo"])
        self.disks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.disks_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.disks_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.disks_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.disks_table.hide()

        self.disk_cards = DiskCardGrid()
        self.disk_cards.card_selected.connect(self.select_row)
        self.disk_cards.analyze_requested.connect(self.on_analyze_and_organize)
        main_layout.addWidget(self.disk_cards)

        self.detail_panel = DiskDetailPanel()
        self.detail_panel.retry_elevated_requested.connect(self.retry_as_admin)
        self.detail_panel.setVisible(False)
        main_layout.addWidget(self.detail_panel, 1)
        for name in ("basic_info_label", "health_status_label", "content_info_label", "usage_progress_bar",
                     "usage_percent_label", "total_size_label", "used_size_label", "free_size_label",
                     "read_count_label", "write_count_label", "read_data_label", "write_data_label",
                     "temperature_label", "power_hours_label", "power_cycles_label"):
            setattr(self, name, getattr(self.detail_panel, name))
        self.space_card_full = self.detail_panel.space_card

        self.log_text = QTextEdit()
        self.log_text.setObjectName("log_text")
        self.log_text.setReadOnly(True)
        self.log_text.document().setMaximumBlockCount(500)
        self.log_text.setMaximumHeight(80)
        main_layout.addWidget(self.log_text)
        apply_control_sizes(self, self._get_runtime_config())

    def setup_connections(self) -> None:
        self.disks_table.itemSelectionChanged.connect(self.on_disk_selection_changed)

    def enable_fluent_mode(self) -> None:
        """Deja que el shell V2 controle la apariencia del visor."""
        self.setProperty("fluentV2", True)
        self.setStyleSheet("")
        self.unified_header.hide()
        self.log_text.hide()
        for child in self.findChildren(QWidget):
            child.setStyleSheet("")
        apply_control_sizes(self, self._get_runtime_config())

    def refresh_fluent_theme(self) -> None:
        """Regenera el HTML con los colores vivos del shell (sin nuevas lecturas)."""
        if not self.property("fluentV2") or not self.current_selection:
            return
        self.update_selected_disk_info(self.current_selection)

    # ------------------------------------------------------------ unidades
    def _on_refresh_clicked(self) -> None:
        invalidate = getattr(self.disk_manager, "invalidate", None)
        if callable(invalidate):
            invalidate()
        self._content_cache.clear()
        self.refresh_disks()

    def refresh_disks(self) -> None:
        """Vuelve a enumerar las unidades (rápido: sin SMART en este hilo)."""
        try:
            self.log_message("Actualizando información de unidades…")
            disks = self.disk_manager.get_all_disks()
            if not disks:
                self.log_message("No se encontraron unidades disponibles")
                self.disks_table.setRowCount(0)
                self._rebuild_disk_cards([])
                self.available_disks = ()
                self.disks_updated_at = datetime.now()
                self.disks_refresh_error = None
                self.disks_refreshed.emit(self.available_disks)
                return
            self.disks_table.blockSignals(True)
            self.disks_table.setRowCount(0)
            valid = []
            for disk in disks:
                if not os.path.exists(disk.mountpoint):
                    continue
                row = self.disks_table.rowCount()  # filas siempre contiguas
                self.disks_table.insertRow(row)
                self._fill_row(row, disk)
                valid.append((row, disk))
            self.disks_table.blockSignals(False)
            self._rebuild_disk_cards(valid)
            self.available_disks = tuple(disk for _, disk in valid)
            self.disks_updated_at = datetime.now()
            self.disks_refresh_error = None
            self.update_system_info()
            self.disks_refreshed.emit(self.available_disks)
        except Exception as exc:  # Mantener el snapshot anterior pase lo que pase
            self.disks_refresh_error = str(exc)
            self.disks_refreshed.emit(self.available_disks)
            self.log_message(f"Error al actualizar unidades: {exc}")
            QMessageBox.critical(self, "Error",
                                 f"Error al actualizar la información de discos:\n{exc}\n\n"
                                 "La aplicación continuará con la información anterior.")
            return

        prefetch = getattr(self.disk_manager, "prefetch_smart_for_disks", None)
        if callable(prefetch):
            prefetch([disk.mountpoint for disk in self.available_disks if getattr(disk, "smart_applicable", True)])
        self.log_message(f"Información actualizada: {len(self.available_disks)} unidades.")
        rows = {disk.mountpoint: index for index, disk in enumerate(self.available_disks)}
        target = rows.get(self.current_selection, 0) if self.available_disks else -1
        if target >= 0:
            self.select_row(target, force=True)

    def _fill_row(self, row: int, disk: DiskInfo) -> None:
        values = (
            f"{disk.drive_letter}:" if disk.drive_letter else disk.mountpoint,
            disk.mountpoint,
            format_bytes(disk.total_size),
            format_bytes(disk.used_size),
            format_bytes(disk.free_size),
            f"{disk.usage_percent:.1f}%",
            "Sí" if disk.is_system_drive else "No",
            getattr(disk, "drive_type_label", ""),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, disk.mountpoint)
            self.disks_table.setItem(row, column, item)

    def _rebuild_disk_cards(self, disks) -> None:
        self.disk_cards.set_disks(list(disks))
        self.disk_cards.set_selected_row(self.disks_table.currentRow())

    def select_row(self, row: int, force: bool = False) -> None:
        if not 0 <= row < self.disks_table.rowCount():
            return
        if row == self.disks_table.currentRow() and not force:
            return
        if row == self.disks_table.currentRow():
            self.on_disk_selection_changed()
        else:
            self.disks_table.selectRow(row)

    def _mountpoint_for_row(self, row: int) -> Optional[str]:
        item = self.disks_table.item(row, 1)
        return item.text() if item else None

    def on_disk_selection_changed(self) -> None:
        row = self.disks_table.currentRow()
        self.disk_cards.set_selected_row(row)
        mountpoint = self._mountpoint_for_row(row) if row >= 0 else None
        if mountpoint:
            self.current_selection = mountpoint
            self.detail_panel.setVisible(True)
            self.update_selected_disk_info(mountpoint)
        else:
            self.current_selection = None
            self.detail_panel.setVisible(False)

    def on_analyze_and_organize(self, row: int) -> None:
        """Selecciona la unidad y pide abrir Organizar con ella."""
        mountpoint = self._mountpoint_for_row(row) if 0 <= row < self.disks_table.rowCount() else None
        if not mountpoint:
            self.log_message("Fila de unidad no válida")
            return
        if not os.path.exists(mountpoint):
            QMessageBox.warning(self, "Unidad no disponible",
                                f"La unidad {mountpoint} no está disponible.\n\nComprueba que esté conectada.")
            return
        self.select_row(row)
        self.disk_selected.emit(mountpoint)

    # ------------------------------------------------------------- detalle
    def _palette(self) -> dict:
        if self.property("fluentV2"):
            return fluent_palette(self._get_runtime_config())
        return legacy_palette(self.get_current_theme_name())

    def update_selected_disk_info(self, mountpoint: str) -> None:
        """Pinta lo que ya se sabe y pide el resto en segundo plano."""
        if self.disk_manager is None or not mountpoint:
            return
        disk = self.disk_manager.get_disk_info(mountpoint)
        palette = self._palette()
        if disk is None or not os.path.exists(mountpoint):
            self.basic_info_label.setText(f"La unidad {mountpoint} no está disponible.")
            self.health_status_label.setText("Estado: no disponible")
            self.content_info_label.setText("Contenido: no disponible")
            return
        self._shown_disk = disk
        self._fill_space(disk)
        get_cached = getattr(self.disk_manager, "get_cached_report", None)
        cached = get_cached(mountpoint) if callable(get_cached) else None
        if cached is not None:
            self._report_request = self.controller.latest_request + 1  # invalida respuestas viejas
            self._render_report(disk, cached)
        else:
            self._last_report = None
            self.basic_info_label.setText(render_basic_html(disk, None, palette, loading=True))
            self.health_status_label.setText(render_health_html(disk, None, palette, loading=True))
            self.detail_panel.set_smart_metrics({key: "…" for key in
                                                 ("read_count", "write_count", "read_data", "write_data",
                                                  "temperature", "power_hours", "power_cycles")})
            self.detail_panel.set_admin_hint(False, False)
            self._report_request = self.controller.request_report(self.disk_manager, mountpoint)
        entry = self._content_cache.get(mountpoint)
        if entry and time.monotonic() - entry[1] < CONTENT_TTL:
            self.content_info_label.setText(render_content_html(entry[0], palette))
        else:
            self.content_info_label.setText(render_content_html(None, palette, loading=True))
            self._content_request = self.controller.request_content(mountpoint)

    def _fill_space(self, disk: DiskInfo) -> None:
        self.usage_progress_bar.setValue(int(round(disk.usage_percent)))
        self.usage_percent_label.setText(f"{disk.usage_percent:.1f} %")
        self.total_size_label.setText(format_bytes(disk.total_size))
        self.used_size_label.setText(format_bytes(disk.used_size))
        self.free_size_label.setText(format_bytes(disk.free_size))

    def _render_report(self, disk: DiskInfo, report) -> None:
        palette = self._palette()
        self._last_report = report
        self.basic_info_label.setText(render_basic_html(disk, report, palette))
        self.health_status_label.setText(render_health_html(disk, report.health, palette, report))
        self.detail_panel.set_smart_metrics(smart_metric_texts(report))
        self.detail_panel.set_admin_hint(bool(getattr(report, "admin_required", False)), sys.platform == "win32")
        for alert in getattr(report, "history_alerts", None) or ():
            self.log_message(f"Alerta SMART ({disk.mountpoint}): {alert}")

    def _on_report_ready(self, request_id: int, mountpoint: str, report) -> None:
        if self._closed or request_id != self._report_request or mountpoint != self.current_selection:
            return
        disk = report.disk or self._shown_disk
        if disk is not None:
            self._render_report(disk, report)

    def _on_content_ready(self, request_id: int, mountpoint: str, summary) -> None:
        if summary:
            self._content_cache[mountpoint] = (summary, time.monotonic())
        if self._closed or request_id != self._content_request or mountpoint != self.current_selection:
            return
        self.content_info_label.setText(render_content_html(summary, self._palette()))

    def retry_as_admin(self) -> None:
        """Relanza sólo smartctl con UAC para la unidad seleccionada."""
        if not self.current_selection:
            return
        self.detail_panel.set_admin_hint(True, True, busy=True)
        self._elevated_request = self.controller.request_elevated(self.disk_manager, [self.current_selection])
        if self._elevated_request is None:
            self.detail_panel.set_admin_hint(True, False)

    def _on_elevated_ready(self, request_id: int, reports) -> None:
        if self._closed or request_id != self._elevated_request:
            return
        report = (reports or {}).get(self.current_selection)
        if report is None:
            self.detail_panel.set_admin_hint(True, sys.platform == "win32")
            self.log_message("No se obtuvieron datos con permisos de administrador.")
            return
        self._render_report(report.disk or self._shown_disk, report)

    # ----------------------------------------------------- estado general
    def update_system_info(self) -> None:
        """Una sola línea: CPU, RAM, unidades y modo (nunca bloquea)."""
        try:
            cpu = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            count = len(self.available_disks)
            self.system_info_label.setText(
                f"CPU {cpu:.0f} % · RAM {memory.percent:.0f} % · {count} {'unidad' if count == 1 else 'unidades'}")
            metrics = self.system_info_label.fontMetrics()
            self.system_info_label.setMinimumWidth(min(360, metrics.horizontalAdvance(self.system_info_label.text()) + 8))
            self.system_info_label.setToolTip(
                f"Procesador: {cpu:.0f} % en uso.\nMemoria: {format_bytes(memory.used)} de "
                f"{format_bytes(memory.total)} ({memory.percent:.0f} %).\nUnidades detectadas: {count}.")
        except (OSError, AttributeError) as exc:
            self.system_info_label.setText("Información del sistema no disponible")
            logger.debug("update_system_info: %s", exc)

    def showEvent(self, event):
        super().showEvent(event)
        if self.disk_manager is not None and not self._closed:
            self.status_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.status_timer.stop()

    def on_safe_mode_changed(self, enabled: bool) -> None:
        if self.disk_manager is not None:
            self.disk_manager.set_safe_mode(enabled)
        self.log_message(f"Modo seguro {'activado' if enabled else 'desactivado'}")
        self.update_system_info()

    # --------------------------------------------------------------- temas
    def apply_theme_styles(self, theme_name: str) -> None:
        """Modo heredado: una hoja de estilos compacta. En Fluent no hace nada."""
        if self.property("fluentV2"):
            return
        scale = html_type_scale(self._get_runtime_config())
        self.setStyleSheet(legacy_stylesheet(legacy_palette(theme_name), scale["small"], scale["body"], scale["title"]))
        if self.current_selection and self._shown_disk is not None and self._last_report is not None:
            self._render_report(self._shown_disk, self._last_report)

    def _get_runtime_config(self) -> AppConfig:
        """Configuración viva del shell; si no hay, una única instancia propia."""
        widget = self.parentWidget()
        while widget is not None:
            config = getattr(widget, "config", None)
            if isinstance(config, AppConfig):
                return config
            widget = widget.parentWidget()
        if self._fallback_config is None:
            self._fallback_config = AppConfig()
        return self._fallback_config

    def get_current_theme_name(self) -> str:
        try:
            return self._get_runtime_config().get_theme()
        except (OSError, ValueError, AttributeError):
            return "🌞 Claro Elegante"

    # ---------------------------------------------------------- utilidades
    def log_message(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")

    def get_selected_disk_path(self) -> Optional[str]:
        return self.current_selection

    def is_safe_mode_enabled(self) -> bool:
        return self.disk_manager.get_safe_mode_status() if self.disk_manager else True

    def shutdown(self) -> None:
        """Cancela consultas, mata smartctl y detiene temporizadores (idempotente)."""
        if self._closed:
            return
        self._closed = True
        self.status_timer.stop()
        self.controller.shutdown()
        manager_shutdown = getattr(self.disk_manager, "shutdown", None)
        if callable(manager_shutdown):
            manager_shutdown()
