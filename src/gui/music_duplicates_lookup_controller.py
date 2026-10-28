#!/usr/bin/env python3
"""Lookup worker orchestration for the music tab."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtWidgets import QMessageBox

from src.core.audio_fingerprint import audio_fingerprint_service
from src.gui.music_duplicates_workers import AudioLookupWorker
from src.utils.app_config import AppConfig


def start_lookup_for_tracks(
    view: Any,
    selected: list[Dict[str, Any]],
    selected_paths: list[str],
    *,
    force_refresh: bool = False,
    start_message: str | None = None,
) -> None:
    if view._lookup_worker is not None and view._lookup_worker.isRunning():
        QMessageBox.information(
            view,
            "Metadatos",
            "Ya hay una búsqueda online en curso",
        )
        return
    if not AppConfig().get_audio_online_metadata_enabled():
        QMessageBox.information(
            view,
            "Metadatos",
            "Los metadatos online están desactivados en Configuración.",
        )
        return
    view._lookup_request_token += 1
    request_token = view._lookup_request_token
    view._lookup_active_token = request_token
    view._set_lookup_busy(
        True,
        start_message
        or f"🌐 Iniciando búsqueda online para {len(selected)} pista(s)...",
    )

    view._lookup_worker = AudioLookupWorker(selected, force_refresh=force_refresh)
    view._lookup_worker.progress.connect(
        lambda message, current, total, token=request_token: on_lookup_progress(
            view, token, message, current, total
        )
    )
    view._lookup_worker.result_ready.connect(
        lambda result, token=request_token: on_lookup_result(view, token, result)
    )
    view._lookup_worker.finished_ok.connect(
        lambda token=request_token, paths=selected_paths: on_lookup_finished(
            view, token, paths
        )
    )
    view._lookup_worker.error_occurred.connect(
        lambda error, token=request_token: on_lookup_error(view, token, error)
    )
    view._lookup_worker.cancelled.connect(
        lambda token=request_token, paths=selected_paths: on_lookup_cancelled(view, token, paths)
    )
    view._lookup_worker.start()


def on_lookup_progress(
    view: Any, token: int, message: str, current: int, total: int
) -> None:
    if token != view._lookup_active_token:
        return
    view.lookup_status_label.setText(message)
    view.lookup_progress.setRange(0, total)
    view.lookup_progress.setValue(current)


def on_lookup_result(view: Any, token: int, result: Dict[str, Any]) -> None:
    if token != view._lookup_active_token:
        return
    file_path = str(Path(result.get("file_path", "")))
    if file_path:
        view._store_lookup_result(file_path, result, persist=True)


def on_lookup_finished(view: Any, token: int, selected_paths: list[str]) -> None:
    if token != view._lookup_active_token:
        return
    results = [view._get_lookup_result(path) for path in selected_paths]
    results = [item for item in results if item]
    auto_changed = 0
    auto_messages: list[str] = []
    variant_targets = []
    pending_single_targets = 0
    for path in selected_paths:
        result = view._get_lookup_result(path)
        if not result:
            continue
        auto_index = view._auto_selectable_candidate_index(path, result)
        if auto_index is not None:
            if view._auto_apply_high_confidence_variant(path, result):
                auto_changed += 1
                updated = view._get_lookup_result(path)
                suggested = dict(updated.get("suggested_updates") or {})
                auto_messages.append(
                    f"{Path(path).name} -> {suggested.get('artist', '-') or '-'} / {suggested.get('title', '-') or '-'}"
                )
            else:
                pending_single_targets += 1
        elif len(result.get("candidates") or []) > 1:
            variant_targets.append(path)
        elif result.get("suggested_updates"):
            local_metadata = dict(result.get("local_metadata") or {})
            local_metadata.setdefault("file_path", path)
            candidate = (result.get("candidates") or [None])[0]
            if candidate and audio_fingerprint_service.should_auto_apply_candidate(
                local_metadata, candidate
            ):
                if view._apply_variant_choice(
                    path, int(result.get("selected_candidate_index", 0) or 0)
                ):
                    auto_changed += 1
            else:
                pending_single_targets += 1
    if variant_targets:
        view._choose_variant_sequence(variant_targets)
    view.refresh_library()
    view._restore_selected_file_paths(selected_paths)
    view._update_lookup_status(results)
    view.refresh_missing_metadata()
    view._show_selected_candidate_preview()
    view._set_lookup_busy(
        False,
        f"🌐 Búsqueda online completada: {len(results)} pista(s) | auto={auto_changed} | variantes={len(variant_targets)} | pendientes={pending_single_targets}",
    )
    if auto_messages:
        message = "🤖 Se ha seleccionado automáticamente: " + "; ".join(
            auto_messages[:3]
        )
        if len(auto_messages) > 3:
            message += f"; +{len(auto_messages) - 3} más"
        view.lookup_status_label.setText(message)
        view._show_music_toast(message, duration_ms=2000)
        view.status_update.emit(message)


def on_lookup_error(view: Any, token: int, error: str) -> None:
    if token != view._lookup_active_token:
        return
    view._set_lookup_busy(False, f"❌ Error en búsqueda online: {error}")


def on_lookup_cancelled(view: Any, token: int, selected_paths: list[str]) -> None:
    if token != view._lookup_active_token:
        return
    view.refresh_library()
    view._restore_selected_file_paths(selected_paths)
    view._set_lookup_busy(False, "⏹ Búsqueda online cancelada; los resultados obtenidos se conservan.")
