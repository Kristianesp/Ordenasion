#!/usr/bin/env python3
"""Helpers puros de presentacion para la vista musical."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from PyQt6.QtGui import QColor

from src.gui.music_duplicates_formatters import (
    format_bitrate,
    format_duration,
    format_file_size,
    format_quality,
)
from src.gui.v2.theme import current_tokens


def lookup_cache_badge(lookup: Dict[str, Any]) -> Tuple[str, str]:
    status = str(lookup.get("cache_status") or "").strip().lower()
    cache_updated_at = str(lookup.get("cache_updated_at") or "").strip()
    if status == "fresh":
        return (
            "cache fresca",
            _badge_style(current_tokens().success),
        )
    if lookup and (status == "cached" or cache_updated_at):
        return (
            "cache reutilizada",
            _badge_style(current_tokens().accent),
        )
    return "", ""


def _badge_style(color: str) -> str:
    return (
        f"background: {_rgba_css(color, 0.14)}; "
        f"color: {color}; padding: 4px 8px; border-radius: 4px;"
    )


def _rgba_css(color: str, alpha: float) -> str:
    parsed = QColor(color)
    if not parsed.isValid():
        return color
    return (
        f"rgba({parsed.red()}, {parsed.green()}, {parsed.blue()}, "
        f"{max(0.0, min(1.0, alpha)):.2f})"
    )


def summarize_lookup_candidates(result: Dict[str, Any], limit: int = 3) -> str:
    parts = []
    for candidate in (result.get("candidates") or [])[:limit]:
        suggested = candidate.get("suggested_updates", {})
        parts.append(
            f"{candidate.get('source', 'unknown')}:{candidate.get('confidence', 0)} {suggested.get('artist', '')} - {suggested.get('title', '')} ({suggested.get('album', '')})"
        )
    return " | ".join(parts) if parts else "sin alternativas"


def build_duplicate_hint(best: Dict[str, Any], removable_bytes: int) -> str:
    return (
        "⭐ Mejor copia sugerida: "
        f"{Path(best.get('file_path', '')).name} | "
        f"{best.get('codec', 'unknown')} | "
        f"score={best.get('quality_score', 0)} | "
        f"{format_quality(best)} | "
        f"Ahorro potencial si eliminas el resto: {format_file_size(removable_bytes)}"
    )


def build_duplicate_preview_block(
    file_path: Path, metadata: Dict[str, Any], recommendation: str
) -> str:
    return "\n".join(
        [
            f"Recomendacion: {recommendation}",
            f"Archivo: {file_path.name}",
            f"Ruta: {file_path}",
            f"Titulo: {metadata.get('title') or file_path.stem}",
            f"Artista: {metadata.get('artist') or metadata.get('album_artist') or '-'}",
            f"Album: {metadata.get('album') or '-'}",
            f"Calidad: {format_quality(metadata)}",
            f"Duracion: {format_duration(metadata.get('duration'))}",
            f"Codec: {metadata.get('codec') or '-'}",
            f"Bitrate: {format_bitrate(metadata.get('bitrate'))}",
        ]
    )


def build_library_detail_text(
    file_path: Path,
    current: Dict[str, Any],
    lookup: Dict[str, Any],
    *,
    state_label: str,
    quality_text: str,
    lookup_reason_text: str,
    is_applied: bool,
    selected_variant_index: int | None,
) -> str:
    suggested = dict(lookup.get("suggested_updates") or {})
    diagnostics = dict(lookup.get("diagnostics") or {})
    lines = [
        f"Estado actual: {state_label}",
        f"Archivo: {file_path.name}",
        f"Ruta: {file_path}",
        "",
        "Metadatos locales",
        f"- Titulo: {current.get('title') or '-'}",
        f"- Artista: {current.get('artist') or current.get('album_artist') or '-'}",
        f"- Album: {current.get('album') or '-'}",
        f"- Año: {current.get('year') or '-'}",
        f"- Genero: {current.get('genre') or '-'}",
        f"- Calidad tecnica: {quality_text}",
    ]
    if selected_variant_index is not None and lookup.get("suggested_updates"):
        lines.append(f"- Variante elegida: {selected_variant_index + 1}")
    if is_applied:
        applied_at = str(lookup.get("applied_at") or "").strip()
        lines.append(
            f"- Aplicada al archivo: si{f' | {applied_at}' if applied_at else ''}"
        )
    if lookup:
        lines.extend(
            [
                "",
                "Sugerencia online",
                f"- Fuente: {lookup.get('source', '-') or '-'}",
                f"- Confianza: {lookup.get('confidence', 0)}",
                f"- Diagnostico: {lookup_reason_text or diagnostics.get('acoustid_reason', '-') or '-'}",
                f"- Titulo sugerido: {suggested.get('title', '-') or '-'}",
                f"- Artista sugerido: {suggested.get('artist', '-') or '-'}",
                f"- Album sugerido: {suggested.get('album', '-') or '-'}",
                f"- Año sugerido: {suggested.get('year', '-') or '-'}",
                f"- Genero sugerido: {suggested.get('genre', '-') or '-'}",
                f"- Alternativas detectadas: {lookup.get('candidate_count', len(lookup.get('candidates') or []))}",
            ]
        )
        cache_updated_at = str(lookup.get("cache_updated_at") or "").strip()
        if cache_updated_at:
            lines.append(f"- Cache actualizada: {cache_updated_at}")
    else:
        lines.extend(
            [
                "",
                "Sugerencia online",
                "- Sin lookup cargado todavia para esta pista.",
            ]
        )
    return "\n".join(lines)
