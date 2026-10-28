"""Controlador en hilos para el visor de Discos.

Nada de smartctl, WMI ni recorridos de carpetas en el hilo de la interfaz:
las consultas van al executor del DiskManager (un Future en vuelo por disco)
o a un executor propio, y los resultados vuelven por señales Qt (conexión en
cola) etiquetados con un identificador de petición. La vista descarta los que
no corresponden a la última petición.
"""

from __future__ import annotations

import logging
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from src.core.disk_manager import DiskReport, summarize_top_level

logger = logging.getLogger(__name__)


class DiskReportController(QObject):
    report_ready = pyqtSignal(int, str, object)    # request_id, mountpoint, DiskReport
    content_ready = pyqtSignal(int, str, object)   # request_id, mountpoint, dict | None
    elevated_ready = pyqtSignal(int, object)       # request_id, {mountpoint: DiskReport}

    def __init__(self, parent=None):
        super().__init__(parent)
        self._request_id = 0
        self._closed = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="disk-viewer")

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    @property
    def latest_request(self) -> int:
        return self._request_id

    def _emit(self, signal_name: str, *args) -> None:
        if self._closed:
            return
        try:
            getattr(self, signal_name).emit(*args)
        except RuntimeError:  # QObject destruido mientras el hilo terminaba
            self._closed = True

    def request_report(self, manager, mountpoint: str, force: bool = False) -> int:
        """Pide el informe SMART/salud de ``mountpoint``. Devuelve el id de petición."""
        request_id = self._next_id()
        if manager is None or self._closed:
            return request_id
        try:
            future: Future = manager.submit_disk_report(mountpoint, force=force)
        except RuntimeError as exc:  # executor ya cerrado
            logger.debug("No se pudo programar la consulta SMART: %s", exc)
            return request_id

        def done(finished: Future, rid=request_id, path=mountpoint):
            try:
                report = finished.result()
            except CancelledError:
                return
            except Exception as exc:  # El worker nunca debe tumbar la interfaz
                logger.warning("Fallo obteniendo el informe de %s: %s", path, exc)
                report = DiskReport(mountpoint=path, disk=None, error="error",
                                    health={"available": False, "score": None, "factors": [],
                                            "status": "Error al leer SMART"})
            self._emit("report_ready", rid, path, report)

        future.add_done_callback(done)
        return request_id

    def request_content(self, mountpoint: str) -> int:
        request_id = self._next_id()
        if self._closed:
            return request_id
        future = self._pool.submit(summarize_top_level, mountpoint)

        def done(finished: Future, rid=request_id, path=mountpoint):
            try:
                summary = finished.result()
            except CancelledError:
                return
            except OSError:
                summary = None
            self._emit("content_ready", rid, path, summary)

        future.add_done_callback(done)
        return request_id

    def request_elevated(self, manager, mountpoints: List[str]) -> Optional[int]:
        """Reintento con smartctl elevado (UAC) en segundo plano."""
        if manager is None or self._closed or not hasattr(manager, "retry_elevated"):
            return None
        request_id = self._next_id()
        future = self._pool.submit(manager.retry_elevated, list(mountpoints))

        def done(finished: Future, rid=request_id):
            try:
                reports = finished.result()
            except CancelledError:
                return
            except Exception as exc:
                logger.warning("La consulta elevada falló: %s", exc)
                reports = {}
            self._emit("elevated_ready", rid, reports)

        future.add_done_callback(done)
        return request_id

    def shutdown(self) -> None:
        self._closed = True
        self._pool.shutdown(wait=False, cancel_futures=True)
