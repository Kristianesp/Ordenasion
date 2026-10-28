#!/usr/bin/env python3
"""
Logger unificado de Ordenasion sobre ``logging`` (sin ``print``).

- Un único logger ``ordenasion`` con salida a stderr (si hay consola) y a
  ``%LOCALAPPDATA%\\Ordenasion\\logs\\ordenasion.log`` (rotativo, UTF-8), para
  poder diagnosticar el ejecutable sin consola.
- Si la consola de Windows no admite un carácter (emojis en cp1252), se
  degrada a ASCII en lugar de lanzar UnicodeEncodeError.
- ``debug`` solo se muestra con ORDENASION_DEBUG=1.

Mantiene la API anterior (info, warn, error, debug, success, critical) y
``SmartCache``.
"""

import logging
import logging.handlers
import os
import sys
import time
from typing import Any, Dict, Optional

LOGGER_NAME = "ordenasion"
LOG_FILE_NAME = "ordenasion.log"


class _SafeStreamHandler(logging.StreamHandler):
    """StreamHandler que nunca falla por la codificación de la consola."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            stream = self.stream
            try:
                stream.write(message + self.terminator)
            except UnicodeEncodeError:
                encoding = getattr(stream, "encoding", None) or "ascii"
                stream.write(message.encode(encoding, errors="ignore").decode(encoding, errors="ignore")
                             + self.terminator)
            self.flush()
        except (OSError, ValueError, AttributeError):
            # Consola cerrada o inexistente: el registro no debe tumbar la app.
            pass


def log_directory():
    """Carpeta de registros dentro de los datos de usuario."""
    from src.utils.paths import user_data_dir

    folder = user_data_dir() / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


_FILE_HANDLER: Optional[logging.Handler] = None


def _file_handler() -> Optional[logging.Handler]:
    """Manejador de archivo único (dos manejadores sobre el mismo archivo
    chocarían al rotar en Windows)."""
    global _FILE_HANDLER
    if _FILE_HANDLER is not None:
        return _FILE_HANDLER
    try:
        handler = logging.handlers.RotatingFileHandler(
            log_directory() / LOG_FILE_NAME, maxBytes=1_000_000, backupCount=3,
            encoding="utf-8", delay=True)
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    _FILE_HANDLER = handler
    return handler


def install_application_logging() -> None:
    """Envía también al archivo los módulos que usan ``logging.getLogger(__name__)``."""
    get_logger()
    handler = _file_handler()
    root = logging.getLogger()
    if handler is not None and handler not in root.handlers:
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not getattr(logger, "_ordenasion_configured", False):
        logger._ordenasion_configured = True
        logger.propagate = False
        if sys.stderr is not None:
            handler = _SafeStreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        file_handler = _file_handler()
        if file_handler is not None:
            logger.addHandler(file_handler)
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.DEBUG if os.environ.get("ORDENASION_DEBUG") == "1" else logging.INFO)
    return logger


def info(msg: str) -> None:
    get_logger().info("ℹ️ %s", msg)


def warn(msg: str) -> None:
    get_logger().warning("⚠️ %s", msg)


def error(msg: str) -> None:
    get_logger().error("❌ %s", msg)


def debug(msg: str) -> None:
    get_logger().debug("[DEBUG] %s", msg)


def success(msg: str) -> None:
    get_logger().info("✅ %s", msg)


def critical(msg: str) -> None:
    get_logger().critical("🔴 %s", msg)


class SmartCache:
    """Cache de sesión con TTL para datos SMART"""

    def __init__(self, ttl_seconds: int = 30):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Obtiene datos del cache si no han expirado"""
        if key not in self._cache:
            return None
        entry = self._cache[key]
        if time.time() - entry['timestamp'] > self._ttl:
            del self._cache[key]
            return None
        return entry['data']

    def set(self, key: str, data: Dict[str, Any]) -> None:
        """Guarda datos en el cache con timestamp"""
        self._cache[key] = {'data': data, 'timestamp': time.time()}

    def clear(self) -> None:
        """Limpia todo el cache"""
        self._cache.clear()

    def size(self) -> int:
        """Retorna el número de entradas en el cache"""
        return len(self._cache)
