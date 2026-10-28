#!/usr/bin/env python3
"""Builders puros de filas para tablas musicales."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple


def build_duplicate_row_values(item: Dict[str, Any], is_best: bool) -> List[str]:
    return [
        "⭐ Conservar" if is_best else "Revisar",
        Path(item.get("file_path", "")).name,
        str(item.get("title") or ""),
        str(item.get("artist") or ""),
        str(item.get("album") or ""),
        str(item.get("duration_text") or ""),
        str(item.get("codec") or ""),
        str(item.get("bitrate_text") or ""),
        str(item.get("quality_score") or ""),
        str(item.get("file_size_text") or ""),
        str(Path(item.get("file_path", "")).parent),
    ]


def build_library_row_values(
    file_path: str,
    track: Dict[str, Any],
    lookup: Dict[str, Any],
    *,
    state_label: str,
    quality_text: str,
    duration_text: str,
    lookup_reason_text: str,
) -> List[str]:
    suggested = lookup.get("suggested_updates", {})
    return [
        Path(file_path).name,
        state_label,
        str(track.get("title") or ""),
        str(track.get("artist") or ""),
        str(track.get("album") or ""),
        str(track.get("album_artist") or ""),
        str(track.get("year") or ""),
        str(track.get("genre") or ""),
        str(track.get("codec") or ""),
        quality_text,
        duration_text,
        str(lookup.get("source", "") or ""),
        str(lookup.get("confidence", 0) or ""),
        lookup_reason_text,
        str(suggested.get("title", "") or ""),
        str(suggested.get("artist", "") or ""),
        str(suggested.get("album", "") or ""),
        str(suggested.get("year", "") or ""),
    ]


def library_row_colors(
    review_status: str,
    *,
    is_applied_variant: bool,
    has_selected_variant: bool,
) -> Tuple[str, str | None]:
    """Colores de fila con tokens semánticos del sistema de diseño.

    Devuelve el color con alfa suave (#AARRGGBB) para no saturar la tabla.
    """
    from src.gui.v2.theme import current_tokens

    def _soft(hex_color: str, alpha: str = "26") -> str:
        return f"#{alpha}{hex_color.lstrip('#').upper()}"

    if review_status == "complete" or is_applied_variant:
        return "resolved", _soft(current_tokens().success)
    if review_status == "no_match":
        return "rejected", _soft(current_tokens().danger)
    if has_selected_variant:
        return "selected_variant", _soft(current_tokens().accent)
    return "pending", None
