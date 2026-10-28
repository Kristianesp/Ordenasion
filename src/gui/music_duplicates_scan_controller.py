#!/usr/bin/env python3
"""Scan worker orchestration for the music duplicates view."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtWidgets import QMessageBox

from src.gui.music_duplicates_workers import AudioLibraryWorker


def set_scan_busy(view: Any, busy: bool, message: str) -> None:
    view._scan_busy = busy
    view.scan_progress.setVisible(busy)
    browse_btn = view.browse_btn
    recursive_cb = view.recursive_cb
    if busy:
        view.scan_progress.setRange(0, 0)
        view.scan_progress.setValue(0)
    else:
        view.scan_progress.setRange(0, 1)
        view.scan_progress.setValue(0)
        view._scan_worker = None
    view.scan_status_label.setText(message)
    cancel_btn = getattr(view, "cancel_scan_btn", None)
    if cancel_btn is not None:
        cancel_btn.setVisible(busy)
    controls = [
        view.scan_btn,
        view.online_lookup_btn,
        view.edit_meta_btn,
        view.apply_all_btn,
        view.refresh_missing_btn,
        view.enrich_btn,
        view.library_filter_combo,
        view.library_search_input,
        view.library_columns_btn,
        view.library_reset_view_btn,
    ]
    for widget in controls:
        if widget is not None:
            widget.setEnabled(not busy and not view._lookup_busy)
    if browse_btn is not None:
        browse_btn.setEnabled(not busy and not view._lookup_busy)
    recursive_cb.setEnabled(not busy and not view._lookup_busy)
    view.path_input.setEnabled(not busy and not view._lookup_busy)


def _start_scan_worker(
    view: Any,
    folder: str,
    *,
    include_duplicates: bool,
    start_message: str,
) -> None:
    set_scan_busy(view, True, start_message)
    view._scan_worker = AudioLibraryWorker(
        folder,
        recursive=view.recursive_cb.isChecked(),
        include_duplicates=include_duplicates,
    )
    view._scan_worker.progress.connect(view._on_scan_progress)
    view._scan_worker.finished_ok.connect(view._on_scan_finished)
    view._scan_worker.error_occurred.connect(view._on_scan_error)
    view._scan_worker.cancelled.connect(lambda: on_scan_cancelled(view))
    view._scan_worker.start()


def scan_library(view: Any) -> None:
    folder = view.path_input.text().strip()
    if not folder:
        QMessageBox.warning(view, "Error", "Selecciona una carpeta primero")
        return
    if not Path(folder).exists():
        QMessageBox.warning(view, "Error", "La carpeta no existe")
        return
    if view._scan_worker is not None and view._scan_worker.isRunning():
        QMessageBox.information(
            view,
            "Música",
            "Ya hay un escaneo musical en curso",
        )
        return

    view.status_update.emit(f"🎵 Analizando música en: {folder}")
    view.current_folder = folder
    view._persist_music_state()
    _start_scan_worker(
        view,
        folder,
        include_duplicates=True,
        start_message=f"🎵 Iniciando análisis musical en: {folder}",
    )


def on_scan_progress(view: Any, message: str) -> None:
    view.scan_status_label.setText(message)


def on_scan_finished(view: Any, payload: Dict[str, Any]) -> None:
    indexed = int(payload.get("indexed", 0) or 0)
    view.current_folder = str(payload.get("folder") or view.current_folder or "")
    view.path_input.setText(view.current_folder)
    view._persist_music_state()
    if payload.get("include_duplicates"):
        view.results = dict(payload.get("duplicates") or {})
    view._refresh_results()
    view.refresh_missing_metadata()
    view.refresh_library()
    duplicate_groups = len(view.results)
    set_scan_busy(
        view,
        False,
        f"🎵 Biblioteca actualizada: indexadas {indexed} pista(s) | grupos duplicados={duplicate_groups}",
    )


def on_scan_cancelled(view: Any) -> None:
    set_scan_busy(view, False, "⏹ Análisis musical cancelado. No se ha modificado ningún archivo.")


def on_scan_error(view: Any, error: str) -> None:
    set_scan_busy(view, False, f"❌ Error en análisis musical: {error}")


def refresh_from_current_folder(view: Any) -> None:
    if not view.current_folder:
        return
    if view._scan_worker is not None and view._scan_worker.isRunning():
        return
    _start_scan_worker(
        view,
        view.current_folder,
        include_duplicates=False,
        start_message=f"🎵 Reindexando biblioteca: {view.current_folder}",
    )
