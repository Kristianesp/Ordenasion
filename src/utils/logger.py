#!/usr/bin/env python3
"""
Logger unificado de Ordenasion sobre ``logging`` (sin ``print``).

- Un único logger ``ordenasion`` con salida a stderr; en el ejecutable sin
  consola (stderr es None) los mensajes se descartan sin errores.
- Si la consola de Windows no admite un carácter (emojis en cp1252), se
  degrada a ASCII en lugar de lanzar UnicodeEncodeError.
- ``debug`` solo se muestra con ORDENASION_DEBUG=1.

Mantiene la API anterior (info, warn, error, debug, success, critical) y
``SmartCache``.
"""

import logging
import os
import sys
import time
from typing import Any, Dict, Optional

LOGGER_NAME = "ordenasion"


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


def get_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if not getattr(logger, "_ordenasion_configured", False):
        logger._ordenasion_configured = True
        logger.propagate = False
        if sys.stderr is None:
            logger.addHandler(logging.NullHandler())
        else:
            handler = _SafeStreamHandler(sys.stderr)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
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
