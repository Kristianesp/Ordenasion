#!/usr/bin/env python3
"""Diagnóstico del arranque para el ejecutable sin consola.

- Registra cada fase del arranque con su tiempo en ``logs/ordenasion.log``.
- Si la ventana no aparece en ``HANG_SECONDS``, ``faulthandler`` vuelca la pila
  de todos los hilos en ``logs/arranque-bloqueado.txt``: dice exactamente dónde
  se quedó parado, sin adivinar.
- Los fallos graves del intérprete (access violation, etc.) quedan en
  ``logs/fallo-grave.txt`` y las excepciones no capturadas en el log.
- Una excepción no capturada muestra un aviso (la app sigue abierta) y, si la
  sesión anterior terminó de golpe, al arrancar se ofrece abrir el informe.

No importa Qt: se puede llamar antes de crear la QApplication.
"""

import faulthandler
import os
import platform
import sys
import time
from typing import Optional

from src.utils.logger import get_logger, install_application_logging, log_directory
from src.utils.version import APP_VERSION

HANG_SECONDS = 20
HANG_FILE = "arranque-bloqueado.txt"
CRASH_FILE = "fallo-grave.txt"
# Existe mientras la app está abierta: si sigue ahí al arrancar, la sesión
# anterior terminó de golpe. (El contenido de fallo-grave.txt no basta: en
# Windows faulthandler también anota excepciones COM que no son fallos.)
SESSION_MARKER = "sesion-en-curso"

_state = {"t0": None, "hang": None, "crash": None, "done": False,
          "previous_crash": None, "error_shown": False}


def _elapsed() -> float:
    t0 = _state["t0"]
    return time.perf_counter() - t0 if t0 is not None else 0.0


def begin() -> None:
    """Primera llamada de main(): log, volcado de fallos graves y vigilante de bloqueo."""
    if _state["t0"] is not None:
        return
    _state["t0"] = time.perf_counter()
    install_application_logging()
    logger = get_logger()
    logger.info("=== Arranque de Ordenasion %s · %s · Python %s · %s ===",
                APP_VERSION, "ejecutable" if getattr(sys, "frozen", False) else "código",
                platform.python_version(), platform.platform())
    try:
        folder = log_directory()
        marker = folder / SESSION_MARKER
        if marker.exists():
            crash = folder / CRASH_FILE
            _state["previous_crash"] = {
                "details": crash.read_text(encoding="utf-8", errors="replace")[-4000:] if crash.exists() else "",
            }
            logger.warning("La sesión anterior de Ordenasion terminó de forma inesperada")
        marker.write_text(APP_VERSION, encoding="utf-8")
        _keep_previous(folder / CRASH_FILE)
        _keep_previous(folder / HANG_FILE)
        _state["crash"] = open(folder / CRASH_FILE, "w", encoding="utf-8")
        faulthandler.enable(file=_state["crash"], all_threads=True)
        _state["hang"] = open(folder / HANG_FILE, "w", encoding="utf-8")
        faulthandler.dump_traceback_later(HANG_SECONDS, repeat=False, file=_state["hang"], exit=False)
    except (OSError, RuntimeError) as exc:
        logger.warning("Arranque: no se pudo preparar el diagnóstico (%s)", exc)

    previous_hook = sys.excepthook

    def log_uncaught(exc_type, exc, tb):
        get_logger().critical("Excepción no capturada", exc_info=(exc_type, exc, tb))
        previous_hook(exc_type, exc, tb)
        _show_error_later(exc_type, exc)

    sys.excepthook = log_uncaught


def _keep_previous(path) -> None:
    """Un volcado con contenido no se pisa al volver a abrir la app."""
    try:
        if path.exists() and path.stat().st_size > 0:
            os.replace(path, path.with_name(path.stem + "-anterior" + path.suffix))
    except OSError:
        pass


def milestone(name: str) -> None:
    get_logger().info("Arranque: %s (%.2f s)", name, _elapsed())


def finish(revealed_by_fallback: bool = False) -> None:
    """La ventana ya es visible: cancela el vigilante y borra el volcado vacío."""
    if _state["done"]:
        return
    _state["done"] = True
    faulthandler.cancel_dump_traceback_later()
    how = "por el plan B (sin primera pintura)" if revealed_by_fallback else "tras la primera pintura"
    get_logger().info("Arranque: ventana visible %s en %.2f s", how, _elapsed())
    _discard(_state.pop("hang", None), HANG_FILE)
    _state["hang"] = None
    if _state["previous_crash"] is not None:
        _call_on_gui_thread(_show_previous_crash, delay_ms=600)


def _call_on_gui_thread(callback, delay_ms: int = 0) -> None:
    """Ejecuta ``callback`` en el hilo de la interfaz (si hay QApplication)."""
    try:
        from PyQt6.QtCore import QThread, QTimer
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None or QThread.currentThread() is not app.thread():
        return  # desde otro hilo basta con el registro
    QTimer.singleShot(delay_ms, callback)


def _show_error_later(exc_type, exc) -> None:
    """Avisa (una vez por sesión) en lugar de fallar en silencio."""
    if _state["error_shown"] or os.environ.get("ORDENASION_SMOKE") == "1" or os.environ.get("ORDENASION_E2E") == "1":
        return
    _state["error_shown"] = True
    text = f"{exc_type.__name__}: {exc}"
    _call_on_gui_thread(lambda: _report_dialog(
        "Ordenasion encontró un error",
        "Se produjo un error inesperado. La aplicación sigue abierta, pero la última acción "
        "puede no haberse completado.",
        text))


def _show_previous_crash() -> None:
    details = (_state["previous_crash"] or {}).get("details", "").strip()
    _report_dialog(
        "Ordenasion se cerró inesperadamente",
        "La última vez Ordenasion se cerró de forma inesperada. Se ha guardado un informe "
        "en la carpeta de registros; envíalo para poder corregir el fallo.",
        details[-1500:] if details else "")


def _report_dialog(title: str, message: str, details: str) -> None:
    from PyQt6.QtWidgets import QApplication, QMessageBox

    box = QMessageBox(QApplication.activeWindow())
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message + f"\n\nRegistros: {log_directory()}")
    if details:
        box.setDetailedText(details)
    open_button = box.addButton("Abrir carpeta de registros", QMessageBox.ButtonRole.ActionRole)
    box.addButton("Cerrar", QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is open_button:
        from src.utils.paths import open_in_file_manager

        open_in_file_manager(log_directory())


def _discard(handle, name: str) -> None:
    if handle is None:
        return
    try:
        handle.close()
        path = log_directory() / name
        if path.exists() and path.stat().st_size == 0:
            path.unlink()
    except OSError:
        pass


def shutdown() -> None:
    """Al salir: si no hubo fallo grave, quita el archivo vacío."""
    faulthandler.cancel_dump_traceback_later()
    try:
        (log_directory() / SESSION_MARKER).unlink(missing_ok=True)
    except OSError:
        pass
    crash: Optional[object] = _state.get("crash")
    if crash is not None:
        try:
            faulthandler.disable()
        except RuntimeError:
            pass
        _discard(crash, CRASH_FILE)
        _state["crash"] = None
    _discard(_state.get("hang"), HANG_FILE)
    _state["hang"] = None
