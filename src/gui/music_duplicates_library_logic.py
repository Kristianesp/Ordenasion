#!/usr/bin/env python3
"""Lógica de biblioteca musical para la vista de duplicados."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PyQt6.QtCore import Qt, QItemSelectionModel

from src.core.audio_index import audio_metadata_service
from src.gui.music_duplicates_table_builders import (
    build_library_row_values,
    library_row_colors,
)


def get_selected_file_paths(view: Any) -> List[str]:
    checked_paths: list[str] = []
    for row in range(view.library_table.rowCount()):
        item = view.library_table.item(row, view.LIBRARY_SELECT_COLUMN)
        if not item or item.checkState() != Qt.CheckState.Checked:
            continue
        file_path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if file_path:
            checked_paths.append(file_path)
    if checked_paths:
        return sorted({str(Path(path)) for path in checked_paths})

    paths: list[str] = []
    rows = sorted({index.row() for index in view.library_table.selectedIndexes()})
    for row in rows:
        item = view.library_table.item(row, view.LIBRARY_SELECT_COLUMN)
        if not item:
            continue
        file_path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if file_path:
            paths.append(file_path)
    return sorted({str(Path(path)) for path in paths})


def get_selected_tracks(view: Any) -> List[Dict[str, Any]]:
    target_paths = get_selected_file_paths(view)
    if not target_paths:
        return []
    target_set = {str(Path(path)) for path in target_paths}
    return [
        track
        for track in view.library_rows
        if str(track.get("file_path", "")) in target_set
    ]


def restore_selected_file_paths(
    view: Any, file_paths: list[str], focus_path: str | None = None
) -> None:
    targets = {str(Path(path)) for path in file_paths if str(path).strip()}
    if not targets:
        return
    selection_model = view.library_table.selectionModel()
    if selection_model is None:
        return
    selection_model.clearSelection()
    model = view.library_table.model()
    if model is None:
        return
    focus_target = str(Path(focus_path)) if focus_path else None
    focus_item = None
    for row in range(view.library_table.rowCount()):
        item = view.library_table.item(row, view.LIBRARY_SELECT_COLUMN)
        if not item:
            continue
        current_path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if current_path not in targets:
            continue
        selection_model.select(
            model.index(row, view.LIBRARY_SELECT_COLUMN),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )
        if focus_target and current_path == focus_target:
            focus_item = view.library_table.item(row, view.LIBRARY_FILE_COLUMN) or item
    if focus_item is None:
        for row in range(view.library_table.rowCount()):
            item = view.library_table.item(row, view.LIBRARY_SELECT_COLUMN)
            if item and str(item.data(Qt.ItemDataRole.UserRole) or "") in targets:
                focus_item = (
                    view.library_table.item(row, view.LIBRARY_FILE_COLUMN) or item
                )
                break
    if focus_item is not None:
        view.library_table.setCurrentItem(focus_item)
        view.library_table.scrollToItem(focus_item)


def refresh_library(view: Any) -> None:
    """Recarga la biblioteca completa (sin límite) en el modelo de la tabla."""
    tracks = audio_metadata_service.list_tracks(limit=None)
    view.library_all_rows = tracks
    available_paths = {str(track.get("file_path") or "") for track in tracks}
    view._checked_library_paths.intersection_update(available_paths)
    filtered_tracks: list[Dict[str, Any]] = []
    rows: list[Dict[str, Any]] = []
    for track in tracks:
        file_path = str(track.get("file_path", ""))
        lookup = view._get_lookup_result(file_path, track)
        state_label = view._track_state_label(track, lookup)
        if not view._match_library_filter(track, lookup, state_label):
            continue
        track_copy = dict(track)
        track_copy["ui_state_label"] = state_label
        filtered_tracks.append(track_copy)
        diagnostics = lookup.get("diagnostics", {})
        diagnostic_reason = lookup.get("reason", "")
        acoustid_reason = diagnostics.get("acoustid_reason", "")
        if diagnostic_reason in ("", "ok", "no_candidates") and acoustid_reason not in (
            "",
            "ok",
            "no_candidates",
            "not_used",
        ):
            diagnostic_reason = acoustid_reason
        values = build_library_row_values(
            file_path,
            track,
            lookup,
            state_label=state_label,
            quality_text=view._format_quality(track),
            duration_text=view._format_duration(track.get("duration")),
            lookup_reason_text=view._format_lookup_reason(diagnostic_reason),
        )
        review_status = str(track.get("review_status") or "")
        is_applied_variant = view._lookup_result_is_applied(lookup) or (
            review_status == "applied"
        )
        has_selected_variant = (
            view._lookup_selected_candidate_index(lookup) is not None
            and bool(lookup.get("suggested_updates"))
            and review_status not in {"complete", "no_match", "applied"}
            and not is_applied_variant
        )
        _, row_color = library_row_colors(
            review_status,
            is_applied_variant=is_applied_variant,
            has_selected_variant=has_selected_variant,
        )
        rows.append(
            {
                "file_path": file_path,
                "values": [str(value) for value in values],
                "color": row_color,
                "checked": file_path in view._checked_library_paths,
            }
        )
    view.library_rows = filtered_tracks
    view._refreshing_library_table = True
    try:
        view.library_table.set_rows(rows)
    finally:
        view._refreshing_library_table = False
    count_label = getattr(view, "library_count_label", None)
    if count_label is not None:
        total = len(tracks)
        shown = len(rows)
        count_label.setText(
            f"{shown} de {total} pistas" if shown != total else f"{total} pistas"
        )
    view._restore_column_widths()
    view._update_library_detail_panel()
