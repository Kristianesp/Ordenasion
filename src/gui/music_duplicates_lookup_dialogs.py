#!/usr/bin/env python3
"""Dialogs for lookup diagnostics and cover selection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QVBoxLayout,
)

from src.core.audio_fingerprint import audio_fingerprint_service
from src.core.audio_index import audio_metadata_service
from src.gui.music_duplicates_lookup_presenters import build_lookup_diagnostics_payload
from src.gui.v2.theme import apply_dialog_surface


def show_lookup_diagnostics_dialog(view: Any, file_path: str | Path) -> None:
    result = view._get_lookup_result(file_path)
    if not result:
        return
    dialog = QDialog(view)
    dialog.setObjectName("musicLookupDiagnosticsDialog")
    dialog.setWindowTitle(f"Diagnostico lookup - {Path(str(file_path)).name}")
    dialog.resize(860, 620)
    layout = QVBoxLayout(dialog)
    info = QLabel(
        "Diagnostico completo del lookup online, candidatos, cache y variante seleccionada."
    )
    info.setWordWrap(True)
    layout.addWidget(info)
    payload = QTextEdit()
    payload.setReadOnly(True)
    payload.setPlainText(build_lookup_diagnostics_payload(result))
    layout.addWidget(payload, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)
    apply_dialog_surface(dialog)
    dialog.exec()


def prompt_cover_choice(view: Any, file_path: str | Path) -> bool:
    normalized_path = str(Path(file_path))
    result = view._get_lookup_result(normalized_path)
    if not result:
        return False
    choices = list(result.get("cover_choices") or [])
    if len(choices) <= 1:
        return False
    preview_cache: dict[str, bytes | None] = {}

    dialog = QDialog(view)
    dialog.setObjectName("musicCoverChoiceDialog")
    dialog.setWindowTitle(f"Elegir portada - {Path(normalized_path).name}")
    dialog.resize(860, 520)
    root = QVBoxLayout(dialog)
    info = QLabel(
        "Selecciona la portada online que quieres dejar como activa para esta pista."
    )
    info.setWordWrap(True)
    root.addWidget(info)

    body = QHBoxLayout()
    root.addLayout(body, 1)
    choices_list = QListWidget()
    preview = QLabel("Sin portada")
    preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    preview.setMinimumSize(280, 280)
    preview.setStyleSheet("border: 1px solid rgba(127,127,127,0.35); padding: 8px;")
    details = QTextEdit()
    details.setReadOnly(True)

    left = QVBoxLayout()
    left.addWidget(choices_list, 2)
    left.addWidget(details, 1)
    body.addLayout(left, 2)
    body.addWidget(preview, 1)

    for index, choice in enumerate(choices):
        item = QListWidgetItem(
            f"{index + 1}. {choice.get('label', 'Portada')} | {choice.get('source', 'unknown')}"
        )
        item.setData(Qt.ItemDataRole.UserRole, index)
        choices_list.addItem(item)

    def update_preview() -> None:
        current_item = choices_list.currentItem()
        if current_item is None:
            details.clear()
            view._set_cover_preview(preview, None)
            return
        index = int(current_item.data(Qt.ItemDataRole.UserRole))
        choice = choices[index]
        url = str(choice.get("url") or "").strip()
        details.setPlainText(
            "\n".join(
                [
                    f"Fuente: {choice.get('source', 'unknown')}",
                    f"Label: {choice.get('label', 'Portada')}",
                    f"URL: {url or '-'}",
                ]
            )
        )
        if url not in preview_cache:
            preview_cache[url] = audio_fingerprint_service.get_cover_art_bytes_for_url(
                url
            )
        cover_bytes = preview_cache.get(url)
        view._set_cover_preview_from_bytes(preview, cover_bytes)

    choices_list.currentItemChanged.connect(lambda *_: update_preview())
    choices_list.itemDoubleClicked.connect(lambda *_: dialog.accept())
    if choices_list.count() > 0:
        choices_list.setCurrentRow(0)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    root.addWidget(buttons)
    apply_dialog_surface(dialog)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    current_item = choices_list.currentItem()
    if current_item is None:
        return False
    index = int(current_item.data(Qt.ItemDataRole.UserRole))
    if not (0 <= index < len(choices)):
        return False
    choice = choices[index]
    url = str(choice.get("url") or "").strip()
    if not url:
        return False
    updated = dict(result)
    updated["selected_cover_url"] = url
    updated["cover_url"] = url
    updated["thumb_url"] = url
    selected_cover_bytes = preview_cache.get(url)
    if selected_cover_bytes is None and url:
        selected_cover_bytes = audio_fingerprint_service.get_cover_art_bytes_for_url(
            url
        )
    if selected_cover_bytes:
        updated["cached_cover_art"] = selected_cover_bytes
    else:
        updated.pop("cached_cover_art", None)
    stored = view._store_lookup_result(normalized_path, updated, persist=True)
    embedded = False
    if selected_cover_bytes:
        embedded = audio_metadata_service.update_track_tags(
            Path(normalized_path),
            {},
            cover_art=selected_cover_bytes,
        )
        if embedded:
            view._sync_lookup_result_after_write(
                normalized_path,
                applied=view._lookup_result_is_applied(stored),
            )
    view.refresh_library()
    view._restore_selected_file_paths([normalized_path], normalized_path)
    view._update_library_detail_panel()
    view._show_selected_candidate_preview()
    view.status_update.emit(
        f"🖼 Portada elegida manualmente: {Path(normalized_path).name} | opcion {index + 1}"
        f"{' | guardada en archivo' if embedded else ' | guardada en cache'}"
    )
    return True
