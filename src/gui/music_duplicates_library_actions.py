#!/usr/bin/env python3
"""Library UI actions and lookup summary helpers for the music tab."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QLabel,
    QCheckBox,
    QMenu,
)

from src.core.audio_fingerprint import audio_fingerprint_service
from src.core.audio_index import audio_metadata_service
from src.gui.music_duplicates_lookup_presenters import (
    build_lookup_preview_text,
    build_lookup_status_text,
)
from src.gui.music_duplicates_lookup_dialogs import (
    prompt_cover_choice,
    show_lookup_diagnostics_dialog,
)
from src.utils.app_config import AppConfig
from src.gui.v2.theme import apply_dialog_surface, apply_menu_surface


def show_selected_candidate_preview(view: Any) -> None:
    selected = view._get_selected_tracks()
    if not selected:
        view.lookup_info_label.setText(
            "Selecciona pistas en la tabla para editar o buscar online."
        )
        view._update_library_detail_panel()
        return
    track = selected[0]
    result = view._get_lookup_result(track.get("file_path", ""), track)
    view.lookup_info_label.setText(build_lookup_preview_text(view, track, result))
    view._update_library_detail_panel()


def update_lookup_status(view: Any, results: list[Dict[str, Any]]) -> None:
    view.lookup_status_label.setText(build_lookup_status_text(view, results))


def show_library_context_menu(view: Any, position) -> None:
    index = view.library_table.indexAt(position)
    if not index.isValid():
        return
    row = index.row()
    path_item = view.library_table.item(row, 0)
    if path_item is None:
        return
    file_path = str(path_item.data(Qt.ItemDataRole.UserRole) or "")
    if not file_path:
        return

    view.library_table.selectRow(row)
    target = Path(file_path)
    menu = QMenu(view)
    apply_menu_surface(menu)

    review_status = audio_metadata_service.get_track_review_status(target)
    complete_label = (
        "Quitar datos completos"
        if review_status == "complete"
        else "Marcar como datos completos"
    )
    complete_action = QAction(complete_label, view)
    complete_action.triggered.connect(
        lambda checked=False, path=target: view._toggle_track_complete(path)
    )
    menu.addAction(complete_action)

    no_match_label = (
        "Quitar no coincide"
        if review_status == "no_match"
        else "Marcar como no coincide"
    )
    no_match_action = QAction(no_match_label, view)
    no_match_action.triggered.connect(
        lambda checked=False, path=target: view._toggle_track_no_match(path)
    )
    menu.addAction(no_match_action)

    clean_action = QAction("Limpiar títulos", view)
    clean_action.triggered.connect(view.clean_selected_titles)
    menu.addAction(clean_action)

    edit_action = QAction("Editar metadatos", view)
    edit_action.triggered.connect(view.edit_selected_metadata)
    menu.addAction(edit_action)

    lookup_result = view._get_lookup_result(target)
    if lookup_result:
        diagnostics_action = QAction("Ver diagnóstico de búsqueda", view)
        diagnostics_action.triggered.connect(
            lambda checked=False, path=target: show_lookup_diagnostics_dialog(
                view, path
            )
        )
        menu.addAction(diagnostics_action)
        if len(lookup_result.get("cover_choices") or []) > 1:
            cover_action = QAction("Elegir portada", view)
            cover_action.triggered.connect(
                lambda checked=False, path=target: prompt_cover_choice(view, path)
            )
            menu.addAction(cover_action)

    menu.exec(view.library_table.mapToGlobal(position))


def edit_library_columns(view: Any) -> None:
    dialog = QDialog(view)
    dialog.setObjectName("musicLibraryColumnsDialog")
    dialog.setWindowTitle("Columnas de biblioteca")
    dialog.resize(320, 460)
    layout = QVBoxLayout(dialog)
    info = QLabel("Activa u oculta columnas de la tabla musical.")
    info.setWordWrap(True)
    layout.addWidget(info)
    checkbox_map: dict[int, QCheckBox] = {}
    for index, label in enumerate(view.LIBRARY_COLUMN_LABELS):
        if index == view.LIBRARY_SELECT_COLUMN:
            label = "Seleccion"
        checkbox = QCheckBox(label)
        checkbox.setChecked(not view.library_table.isColumnHidden(index))
        if index in {view.LIBRARY_SELECT_COLUMN, view.LIBRARY_FILE_COLUMN}:
            checkbox.setEnabled(False)
        checkbox_map[index] = checkbox
        layout.addWidget(checkbox)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    apply_dialog_surface(dialog)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    for index, checkbox in checkbox_map.items():
        hidden = not checkbox.isChecked()
        if index in {view.LIBRARY_SELECT_COLUMN, view.LIBRARY_FILE_COLUMN}:
            hidden = False
        view.library_table.setColumnHidden(index, hidden)
    view._save_visible_columns()


def lookup_results_for_tracks(
    view: Any, tracks: list[Dict[str, Any]], fetch_missing: bool
) -> list[Dict[str, Any]]:
    ordered: list[Dict[str, Any]] = []
    missing: list[Dict[str, Any]] = []
    for track in tracks:
        file_path = str(Path(track.get("file_path", "")))
        cached = view._get_lookup_result(file_path, track)
        if cached is not None:
            ordered.append(cached)
        elif fetch_missing:
            missing.append(track)
    if missing and AppConfig().get_audio_online_metadata_enabled():
        fetched = audio_fingerprint_service.build_batch_suggestions(missing)
        for item in fetched:
            view._store_lookup_result(item.get("file_path", ""), item, persist=True)
        ordered = []
        for track in tracks:
            file_path = str(Path(track.get("file_path", "")))
            cached = view._get_lookup_result(file_path, track)
            if cached is not None:
                ordered.append(cached)
    return ordered
