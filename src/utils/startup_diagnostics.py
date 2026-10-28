#!/usr/bin/env python3
"""Diagnóstico del arranque para el ejecutable sin consola.

- Registra cada fase del arranque con su tiempo en ``logs/ordenasion.log``.
- Si la ventana no aparece en ``HANG_SECONDS``, ``faulthandler`` vuelca la pila
  de todos los hilos en ``logs/arranque-bloqueado.txt``: dice exactamente dónde
  se quedó parado, sin adivinar.
- Los fallos graves del intérprete (access violation, etc.) quedan en
  ``logs/fallo-grave.txt`` y las excepciones no capturadas en el log.

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

_state = {"t0": None, "hang": None, "crash": None, "done": False}


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
