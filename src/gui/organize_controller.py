#!/usr/bin/env python3
"""Controlador de Organizar, sin interfaz.

Concentra el estado y los workers del flujo analizar → organizar → deshacer
para que la interfaz Fluent (y la ventana heredada) dependan de un QObject
pequeño y testeable en lugar de la ventana principal:

- estado: última transacción deshacible, último resumen y tareas en curso;
- workers de análisis, organización y deshacer, con su registro en el
  centro de tareas y una parada segura al cerrar;
- historial persistente de organizaciones;
- registro de la interfaz: mensajes en lotes (cada ~100 ms) con contador
  incremental, que cualquier vista puede mostrar.

Las confirmaciones y los diálogos de resultado son cosa de la vista.
"""

from __future__ import annotations

import html
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from src.core.transaction_manager import TransactionManager
from src.core.workers import AnalysisWorker, OrganizeWorker, RollbackWorker
from src.gui.task_center import task_registry
from src.utils.logger import warn as log_warn

ORGANIZE_TASK_STATUS = {
    "completado": "Completada",
    "completado con errores": "Completada con errores",
    "cancelado": "Cancelada",
}


def _log_color(message: str) -> str:
    if "❌" in message or "Error" in message:
        return "#c62828"
    if "⚠️" in message or "Advertencia" in message:
        return "#ed6c02"
    if "✅" in message:
        return "#2e7d32"
    return "#1976d2"


class OrganizeController(QObject):
    """Estado y workers de Organizar (sin widgets)."""

    operation_state_changed = pyqtSignal()
    # Registro: lotes de líneas HTML ya formateadas y limpieza completa
    log_appended = pyqtSignal(list)
    log_cleared = pyqtSignal()
    # Resultados de los workers, ya con el estado del controlador actualizado
    analysis_completed = pyqtSignal(list, list, dict)
    analysis_cancelled = pyqtSignal()
    analysis_failed = pyqtSignal(str)
    organize_finished = pyqtSignal(bool, str)
    rollback_finished = pyqtSignal(str, bool, dict)

    LOG_FLUSH_INTERVAL_MS = 100
    MAX_LOG_ENTRIES = 5000

    def __init__(self, transaction_manager: Optional[TransactionManager] = None, parent=None):
        super().__init__(parent)
        # Gestor ÚNICO de transacciones: lo comparten el worker de
        # organización, el deshacer y el historial (recarga el registro).
        self.transaction_manager = transaction_manager or TransactionManager()
        self.last_transaction_id = self.transaction_manager.get_last_undoable_transaction_id()
        self.last_operation_summary: Optional[dict] = None
        self.current_analysis_task_id: Optional[str] = None
        self.current_organize_task_id: Optional[str] = None
        self.current_rollback_task_id: Optional[str] = None
        self.active_workers: list = []
        self._shutdown_done = False
        # Registro en lotes
        self._log_queue: List[str] = []
        self._log_html: List[str] = []
        self._log_plain: List[str] = []
        self._log_entry_count = 0
        self._pending_task_messages: Dict[str, str] = {}
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.setInterval(self.LOG_FLUSH_INTERVAL_MS)
        self._log_flush_timer.timeout.connect(self.flush_log)

    # ------------------------------------------------------------- estado
    @property
    def busy(self) -> bool:
        """Hay un análisis, una organización o un deshacer en curso."""
        return bool(self.current_analysis_task_id or self.current_organize_task_id
                    or self.current_rollback_task_id)

    def can_undo(self) -> bool:
        summary = self.last_operation_summary or {}
        return (bool(self.last_transaction_id) and not self.current_organize_task_id
                and not self.current_rollback_task_id and not summary.get("undone"))

    def get_transaction_history(self, limit: int = 50):
        """Historial persistente de organizaciones (la más reciente primero)."""
        return self.transaction_manager.get_transactions(limit)

    def refresh_last_transaction(self) -> Optional[str]:
        if not self.last_transaction_id:
            self.last_transaction_id = self.transaction_manager.get_last_undoable_transaction_id()
        return self.last_transaction_id

    # ------------------------------------------------------------ registro
    def log(self, message) -> None:
        """Añade un mensaje; se vuelca en lote para no repintar por archivo."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        text = str(message)
        self._log_queue.append(
            f"<span style='color:#888'>[{timestamp}]</span> "
            f"<span style='color:{_log_color(text)}'>{html.escape(text)}</span>"
        )
        self._log_plain.append(f"[{timestamp}] {text}")
        if not self._log_flush_timer.isActive():
            self._log_flush_timer.start()

    def flush_log(self) -> None:
        """Vuelca los mensajes pendientes y el progreso de las tareas."""
        if self._pending_task_messages:
            for task_id, task_message in list(self._pending_task_messages.items()):
                task_registry.update_task(task_id, task_message)
            self._pending_task_messages.clear()
        if not self._log_queue:
            return
        batch, self._log_queue = self._log_queue, []
        self._log_entry_count += len(batch)
        self._log_html.extend(batch)
        overflow = len(self._log_html) - self.MAX_LOG_ENTRIES
        if overflow > 0:
            del self._log_html[:overflow]
        overflow = len(self._log_plain) - self.MAX_LOG_ENTRIES
        if overflow > 0:
            del self._log_plain[:overflow]
        self.log_appended.emit(batch)

    @property
    def log_entry_count(self) -> int:
        return self._log_entry_count

    def log_history(self) -> List[str]:
        """Líneas HTML conservadas (para una vista que se crea más tarde)."""
        return list(self._log_html)

    def log_text(self) -> str:
        return "\n".join(self._log_plain)

    def clear_log(self) -> None:
        self._log_queue = []
        self._log_html = []
        self._log_plain = []
        self._log_entry_count = 0
        self.log_cleared.emit()

    def export_log(self, filepath: str) -> int:
        """Escribe el registro en ``filepath``; devuelve el número de entradas."""
        self.flush_log()
        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write("REGISTRO DE ORDENASION\n")
            handle.write("=" * 50 + "\n")
            handle.write(f"Fecha de exportación: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            handle.write(f"Total de entradas: {self.log_entry_count}\n")
            handle.write("=" * 50 + "\n\n")
            handle.write(self.log_text())
        return self.log_entry_count

    def handle_task_progress(self, task_id: str, message: str) -> None:
        """Progreso de un worker: el centro de tareas se actualiza en lote."""
        self._pending_task_messages[task_id] = message
        self.log(message)

    # ------------------------------------------------------------- workers
    def _track(self, worker) -> None:
        self.active_workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))

    def _cleanup_worker(self, worker) -> None:
        """Libera un worker que ya terminó (nunca uno en marcha)."""
        try:
            if worker in self.active_workers:
                self.active_workers.remove(worker)
            worker.wait()
            worker.deleteLater()
        except RuntimeError as exc:  # El objeto Qt ya se había destruido
            log_warn(f"No se pudo limpiar el worker: {exc}")

    def start_analysis(self, folder_path: str, categories, ext_to_category, similarity: int, *,
                       min_file_size_mb: int = 0, ignored_extensions=None, ignored_paths=None,
                       category_manager=None) -> Optional[str]:
        if self.busy:
            return None
        worker_id = f"analysis_{int(time.time())}"
        worker = AnalysisWorker(
            folder_path, categories, ext_to_category, similarity,
            min_file_size_mb=min_file_size_mb,
            ignored_extensions=list(ignored_extensions or []),
            ignored_paths=list(ignored_paths or []),
            category_manager=category_manager,
        )
        self._track(worker)
        worker.progress_update.connect(lambda message, task_id=worker_id: self.handle_task_progress(task_id, message))
        worker.analysis_complete.connect(self._on_analysis_complete)
        worker.analysis_cancelled.connect(self._on_analysis_cancelled)
        worker.error_occurred.connect(self._on_analysis_error)
        task_registry.start_task(worker_id, "Análisis de organización", worker.stop)
        self.current_analysis_task_id = worker_id
        worker.start()
        self.log(f"✅ Worker de análisis iniciado: {worker_id}")
        return worker_id

    def _finish_analysis(self, status: str) -> None:
        if self.current_analysis_task_id:
            task_registry.finish_task(self.current_analysis_task_id, status)
            self.current_analysis_task_id = None

    def _on_analysis_complete(self, folder_movements, file_movements, stats) -> None:
        self._finish_analysis("Completada")
        self.analysis_completed.emit(folder_movements, file_movements, stats)

    def _on_analysis_cancelled(self) -> None:
        self._finish_analysis("Cancelada")
        self.log("⏹️ Análisis cancelado")
        self.analysis_cancelled.emit()

    def _on_analysis_error(self, message: str) -> None:
        self._finish_analysis("Error")
        self.log(message)
        self.analysis_failed.emit(message)

    def start_organization(self, folder_path: str, folder_movements, file_movements, **worker_options) -> Optional[str]:
        """Lanza la organización ya revisada (el plan viene de la vista previa)."""
        if self.busy:
            return None
        worker_id = f"organize_{int(time.time())}"
        worker = OrganizeWorker(folder_path, folder_movements, file_movements,
                                transaction_manager=self.transaction_manager, **worker_options)
        self._track(worker)
        worker.progress_update.connect(lambda message, task_id=worker_id: self.handle_task_progress(task_id, message))
        worker.organize_complete.connect(self._on_organize_complete)
        worker.rollback_available.connect(self._on_rollback_available)
        worker.summary_ready.connect(self._on_summary_ready)
        task_registry.start_task(worker_id, "Organización de archivos", worker.stop)
        self.current_organize_task_id = worker_id
        self.last_operation_summary = None
        self.operation_state_changed.emit()
        worker.start()
        self.log(f"✅ Worker de organización iniciado: {worker_id}")
        return worker_id

    def _on_rollback_available(self, transaction_id: str) -> None:
        self.last_transaction_id = transaction_id
        self.log(f"↩️ Rollback disponible: {transaction_id}")
        self.operation_state_changed.emit()

    def _on_summary_ready(self, summary: dict) -> None:
        self.last_operation_summary = summary
        self.operation_state_changed.emit()

    def _on_organize_complete(self, success: bool, message: str) -> None:
        self.flush_log()
        summary = self.last_operation_summary or {}
        status = summary.get("status", "completado" if success else "error")
        if self.current_organize_task_id:
            task_registry.finish_task(self.current_organize_task_id, ORGANIZE_TASK_STATUS.get(status, "Error"))
            self.current_organize_task_id = None
        self.organize_finished.emit(success, message)
        self.operation_state_changed.emit()

    def start_rollback(self, transaction_id: str) -> bool:
        """Deshace una transacción del historial en segundo plano."""
        if not transaction_id or self.current_organize_task_id or self.current_rollback_task_id:
            return False
        worker_id = f"rollback_{int(time.time())}"
        worker = RollbackWorker(self.transaction_manager, transaction_id)
        self._track(worker)
        worker.rollback_finished.connect(self._on_rollback_finished)
        task_registry.start_task(worker_id, "Deshacer organización", None)
        self.current_rollback_task_id = worker_id
        self.log(f"↩️ Deshaciendo {transaction_id}...")
        self.operation_state_changed.emit()
        worker.start()
        return True

    def _on_rollback_finished(self, transaction_id: str, ok: bool, result: dict) -> None:
        if self.current_rollback_task_id:
            task_registry.finish_task(self.current_rollback_task_id, "Completada" if ok else "Con errores")
            self.current_rollback_task_id = None
        self.last_transaction_id = self.transaction_manager.get_last_undoable_transaction_id()
        for warning in result.get("warnings", []):
            self.log(f"⚠️ {warning}")
        for error_text in result.get("errors", []):
            self.log(f"❌ {error_text}")
        summary = self.last_operation_summary
        if ok and summary is not None and summary.get("transaction_id") in (None, transaction_id):
            self.last_operation_summary = dict(summary, undone=True)
        if ok and not result.get("already_reverted"):
            self.log(f"✅ Rollback completado: {transaction_id}")
        elif not ok:
            self.log(f"❌ Error al revertir: {transaction_id}")
        self.rollback_finished.emit(transaction_id, ok, result)
        self.operation_state_changed.emit()

    # --------------------------------------------------------------- cierre
    def has_running_organization(self) -> bool:
        """True si hay una organización o un deshacer en curso."""
        return any(
            worker.isRunning()
            for worker in self.active_workers
            if isinstance(worker, (OrganizeWorker, RollbackWorker))
        )

    def request_shutdown(self, confirm: Optional[Callable[[], bool]] = None) -> bool:
        """Prepara el cierre. ``confirm`` decide si se detiene una organización en curso."""
        if self._shutdown_done:
            return True
        if confirm is not None and self.has_running_organization() and not confirm():
            return False
        self.shutdown_workers()
        return True

    def shutdown_workers(self) -> None:
        """Detiene todos los workers y espera a que terminen sus hilos.

        Nunca se destruye un QThread en marcha: stop() deja terminar el
        elemento actual y cerrar la transacción, y se espera sin límite.
        """
        workers = list(self.active_workers)
        for worker in workers:
            stop = getattr(worker, "stop", None)
            if callable(stop):
                try:
                    stop()
                except RuntimeError as exc:
                    log_warn(f"No se pudo detener un worker: {exc}")
        for worker in workers:
            try:
                if worker.isRunning():
                    worker.wait()
            except RuntimeError as exc:
                log_warn(f"No se pudo esperar a un worker: {exc}")
        self._shutdown_done = True
        self.flush_log()
