#!/usr/bin/env python3
"""Presentation helpers for lookup state and diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.gui.music_duplicates_presenters import summarize_lookup_candidates


def build_lookup_preview_text(
    view: Any, track: Dict[str, Any], result: Dict[str, Any]
) -> str:
    if not result:
        return (
            f"Seleccionado: {Path(track.get('file_path', '')).name} | "
            f"Local: {track.get('artist') or track.get('album_artist') or '-'} - {track.get('title') or '-'} | "
            "Sin búsqueda online todavía"
        )
    suggested = dict(result.get("suggested_updates") or {})
    alternatives = summarize_lookup_candidates(result)
    selected_variant_text = ""
    selected_index = view._lookup_selected_candidate_index(result)
    if selected_index is not None and result.get("suggested_updates"):
        state_word = (
            "Aplicada" if view._lookup_result_is_applied(result) else "Variante elegida"
        )
        selected_variant_text = f" | {state_word}: {selected_index + 1}"
    cache_hint = ""
    cache_status = str(result.get("cache_status") or "").strip().lower()
    cache_updated_at = str(result.get("cache_updated_at") or "").strip()
    if cache_status == "fresh":
        cache_hint = " | Cache: fresca"
    elif result and (cache_status == "cached" or cache_updated_at):
        cache_hint = " | Cache: reutilizada"
    return (
        f"Seleccionado: {Path(track.get('file_path', '')).name} | "
        f"Local: {track.get('artist') or track.get('album_artist') or '-'} - {track.get('title') or '-'} | "
        f"Sugerido: {suggested.get('artist', '-') or '-'} - {suggested.get('title', '-') or '-'} | "
        f"Album: {suggested.get('album', '-') or '-'} | "
        f"Fuente: {result.get('source', 'unknown')} | "
        f"Confianza: {result.get('confidence', 0)} | "
        f"Alternativas: {result.get('candidate_count', 0)}"
        f"{selected_variant_text}{cache_hint} | Top: {alternatives}"
    )


def build_lookup_status_text(view: Any, results: list[Dict[str, Any]]) -> str:
    if not results:
        return "Búsqueda online: sin candidatos válidos"
    first = results[0]
    diagnostics = dict(first.get("diagnostics") or {})
    source = first.get("source", "unknown")
    fingerprint = diagnostics.get(
        "fingerprint_strategy", first.get("fingerprint_strategy", "none")
    )
    primary_reason = first.get("reason", diagnostics.get("acoustid_reason", "ok"))
    reason = view._format_lookup_reason(primary_reason)
    acoustid_reason = diagnostics.get("acoustid_reason", "")
    acoustid_hint = ""
    if acoustid_reason not in ("", "ok", "no_candidates", "not_used"):
        acoustid_hint = f" | acoustid={view._format_lookup_reason(acoustid_reason)}"
    candidate_count = sum(int(item.get("candidate_count", 0)) for item in results)
    source_counts = diagnostics.get("candidate_counts", {})
    source_hint = ""
    if source_counts:
        source_hint = (
            f" | A/M/D={source_counts.get('acoustid', 0)}/"
            f"{source_counts.get('musicbrainz', 0)}/"
            f"{source_counts.get('discogs', 0)}"
        )
    return (
        f"Búsqueda online: fuente={source} | fingerprint={fingerprint} | "
        f"diagnóstico={reason} | pistas={len(results)} | candidatos={candidate_count}"
        f"{source_hint}{acoustid_hint}"
    )


def build_lookup_diagnostics_payload(result: Dict[str, Any]) -> str:
    payload = {
        "file_path": result.get("file_path", ""),
        "source": result.get("source", "unknown"),
        "confidence": result.get("confidence", 0),
        "reason": result.get("reason", ""),
        "candidate_count": result.get(
            "candidate_count", len(result.get("candidates") or [])
        ),
        "cache_status": result.get("cache_status", ""),
        "cache_updated_at": result.get("cache_updated_at", ""),
        "selected_candidate_index": result.get("selected_candidate_index"),
        "applied_candidate_index": result.get("applied_candidate_index"),
        "applied_at": result.get("applied_at", ""),
        "suggested_updates": result.get("suggested_updates", {}),
        "diagnostics": result.get("diagnostics", {}),
        "cover_choices": result.get("cover_choices", []),
        "candidates": result.get("candidates", []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
