"""Formateo de tamaños compartido por toda la interfaz (una única fuente)."""


def format_bytes(value) -> str:
    """Bytes legibles en unidades binarias: ``512 B``, ``1.5 KB``, ``2.0 GB``."""
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    negative = value < 0
    value = abs(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            text = f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
            return f"-{text}" if negative else text
        value /= 1024
    return "—"  # pragma: no cover
