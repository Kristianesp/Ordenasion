#!/usr/bin/env python3
"""Metadata editor dialog for the music duplicates view."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTextEdit,
    QVBoxLayout,
)

from src.core.audio_fingerprint import audio_fingerprint_service
from src.core.audio_index import audio_metadata_service
from src.utils.app_config import AppConfig
from src.gui.v2.theme import apply_dialog_surface
from src.gui.music_duplicates_lookup_dialogs import (
    prompt_cover_choice,
    show_lookup_diagnostics_dialog,
)
from src.gui.music_duplicates_lookup_logic import (
    invalidate_lookup_cache_if_manual_updates_conflict,
)
from src.gui.music_duplicates_variant_dialog import (
    build_variant_details_text,
    configure_variant_table,
    populate_variant_table,
    selected_variant_index,
)


def edit_track_metadata(view: Any, target: Path) -> None:
    current = audio_metadata_service.get_metadata(target) or {}
    initial_lookup = view._get_lookup_result(target, current)
    dialog = QDialog(view)
    dialog.setObjectName("musicMetadataEditorDialog")
    dialog.setWindowTitle(f"Editar metadatos - {target.name}")
    dialog.resize(980, 760)
    dialog.setMinimumSize(920, 700)
    root_layout = QVBoxLayout(dialog)
    header = QLabel(f"Editar metadatos - {target.name}")
    root_layout.addWidget(header)
    content_layout = QHBoxLayout()
    root_layout.addLayout(content_layout, 2)

    left_layout = QVBoxLayout()
    content_layout.addLayout(left_layout, 3)
    form = QFormLayout()
    left_layout.addLayout(form)

    right_layout = QVBoxLayout()
    content_layout.addLayout(right_layout, 1)
    cover_label = QLabel("Sin portada")
    cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cover_label.setMinimumSize(200, 200)
    cover_label.setStyleSheet("border: 1px solid rgba(127,127,127,0.35); padding: 6px;")
    right_layout.addWidget(cover_label)
    view._set_cover_preview(cover_label, target)
    right_layout.addStretch()

    file_info = QLabel(
        f"Archivo: {target.name}\nRuta: {target}\nCodec: {current.get('codec') or '-'} | Duracion: {view._format_duration(current.get('duration'))} | Calidad: {view._format_quality(current)}"
    )
    file_info.setWordWrap(True)
    form.addRow(file_info)

    suggestion_info: QLabel = QLabel()
    suggestion_info.setWordWrap(True)
    form.addRow(suggestion_info)

    title_edit = QLineEdit(current.get("title") or target.stem)
    artist_edit = QLineEdit(current.get("artist") or "")
    album_edit = QLineEdit(current.get("album") or "")
    album_artist_edit = QLineEdit(current.get("album_artist") or "")
    year_edit = QLineEdit(current.get("year") or "")
    genre_edit = QLineEdit(current.get("genre") or "")
    highlighted_edits = [
        title_edit,
        artist_edit,
        album_edit,
        album_artist_edit,
        year_edit,
        genre_edit,
    ]
    form.addRow("Titulo", title_edit)
    form.addRow("Artista", artist_edit)
    form.addRow("Album", album_edit)
    form.addRow("Album artist", album_artist_edit)
    form.addRow("Año", year_edit)
    form.addRow("Genero", genre_edit)

    lookup_actions = QHBoxLayout()
    dialog_lookup_btn = QPushButton("Buscar online")
    use_variant_btn = QPushButton("Usar variante")
    use_variant_btn.setEnabled(False)
    choose_cover_btn = QPushButton("Portadas")
    choose_cover_btn.setEnabled(False)
    diagnostics_btn = QPushButton("Diagnóstico")
    no_match_btn = QPushButton("No coincide")
    skip_variant_btn = QPushButton("Omitir esta")
    skip_variant_btn.setVisible(False)
    lookup_actions.addWidget(dialog_lookup_btn)
    lookup_actions.addWidget(use_variant_btn)
    lookup_actions.addWidget(choose_cover_btn)
    lookup_actions.addWidget(diagnostics_btn)
    lookup_actions.addWidget(no_match_btn)
    lookup_actions.addWidget(skip_variant_btn)
    lookup_actions.addStretch()
    left_layout.addLayout(lookup_actions)

    dialog_lookup_status = QLabel(
        "Pulsa Buscar online para cargar variantes en esta misma ventana."
    )
    dialog_lookup_status.setWordWrap(True)
    left_layout.addWidget(dialog_lookup_status)

    variants_box = QGroupBox("Variantes online")
    variants_layout = QVBoxLayout(variants_box)
    variants_table = QTableWidget(0, 7)
    configure_variant_table(variants_table)
    variants_layout.addWidget(variants_table, 2)
    variant_details = QTextEdit()
    variant_details.setReadOnly(True)
    variants_layout.addWidget(variant_details, 1)
    root_layout.addWidget(variants_box, 3)

    def current_lookup_payload() -> Dict[str, Any]:
        return {
            **current,
            "file_path": str(target),
            "title": title_edit.text().strip(),
            "artist": artist_edit.text().strip(),
            "album": album_edit.text().strip(),
            "album_artist": album_artist_edit.text().strip(),
            "year": year_edit.text().strip(),
            "genre": genre_edit.text().strip(),
        }

    def current_lookup_result() -> Dict[str, Any]:
        return view._get_lookup_result(target, current_lookup_payload())

    def refresh_dialog_suggestion(result: Dict[str, Any] | None = None) -> None:
        active_result = result or current_lookup_result()
        fresh_suggested = dict(active_result.get("suggested_updates") or {})
        if fresh_suggested:
            suggestion_info.setText(
                "Sugerido online: "
                f"{fresh_suggested.get('artist', '-') or '-'} - {fresh_suggested.get('title', '-') or '-'} | "
                f"Album: {fresh_suggested.get('album', '-') or '-'} | Año: {fresh_suggested.get('year', '-') or '-'}"
            )
            suggestion_info.show()
        else:
            suggestion_info.setText("Sin sugerencia online seleccionada.")
            suggestion_info.show()

    def update_dialog_cover(result: Dict[str, Any] | None = None) -> None:
        active_result = result or current_lookup_result()
        cover_bytes = view._fetch_cover_preview_bytes(target, active_result)
        if cover_bytes:
            view._set_cover_preview_from_bytes(cover_label, cover_bytes)
        else:
            view._set_cover_preview(cover_label, target)

    def update_dialog_variant_details() -> None:
        result = current_lookup_result()
        candidates = list(result.get("candidates") or [])
        chosen_index = selected_variant_index(variants_table)
        if chosen_index is None or not (0 <= chosen_index < len(candidates)):
            variant_details.setPlainText(
                "Haz una busqueda online y selecciona una variante para ver su detalle."
            )
            use_variant_btn.setEnabled(False)
            return
        use_variant_btn.setEnabled(True)
        variant_details.setPlainText(
            build_variant_details_text(target.name, candidates[chosen_index], result)
        )

    def populate_dialog_variants(result: Dict[str, Any]) -> None:
        candidates = list(result.get("candidates") or [])
        populate_variant_table(variants_table, candidates)
        choose_cover_btn.setEnabled(len(result.get("cover_choices") or []) > 1)
        if not candidates:
            dialog_lookup_status.setText(
                "Sin candidatos online para esta pista. Puedes seguir editando manualmente."
            )
            variants_box.setVisible(False)
            variant_details.setPlainText("Sin variantes disponibles.")
            use_variant_btn.setEnabled(False)
            refresh_dialog_suggestion(result)
            update_dialog_cover(result)
            return

        variants_box.setVisible(True)
        dialog_lookup_status.setText(
            f"{len(candidates)} variante(s) encontradas. Doble clic o usa 'Usar variante' para cargar una en el formulario."
        )
        selected_index = int(result.get("selected_candidate_index", 0) or 0)
        if 0 <= selected_index < variants_table.rowCount():
            variants_table.selectRow(selected_index)
        elif variants_table.rowCount() > 0:
            variants_table.selectRow(0)
        refresh_dialog_suggestion(result)
        update_dialog_cover(result)
        update_dialog_variant_details()

    def apply_selected_variant_to_form() -> None:
        chosen_index = selected_variant_index(variants_table)
        if chosen_index is None:
            return
        updated_result = view._select_variant_in_lookup_cache(str(target), chosen_index)
        if not updated_result:
            return
        selected_updates = dict(updated_result.get("suggested_updates") or {})
        title_edit.setText(selected_updates.get("title", title_edit.text()).strip())
        artist_edit.setText(selected_updates.get("artist", artist_edit.text()).strip())
        album_edit.setText(selected_updates.get("album", album_edit.text()).strip())
        if selected_updates.get("artist") and not album_artist_edit.text().strip():
            album_artist_edit.setText(str(selected_updates.get("artist") or "").strip())
        if selected_updates.get("year"):
            year_edit.setText(str(selected_updates.get("year") or "").strip())
        if selected_updates.get("genre"):
            genre_edit.setText(str(selected_updates.get("genre") or "").strip())
        view._variant_field_styles(highlighted_edits, True)
        refresh_dialog_suggestion(updated_result)
        update_dialog_cover(updated_result)
        dialog_lookup_status.setText(
            f"Variante cargada en el formulario: {chosen_index + 1}/{len(updated_result.get('candidates') or [])}"
        )
        view.status_update.emit(
            f"🎯 Variante elegida en editor: {target.name} | opcion {chosen_index + 1}"
        )
        view.refresh_library()
        view._restore_selected_file_paths([str(target)], str(target))
        view._update_library_detail_panel()
        update_dialog_variant_details()

    def lookup_from_dialog() -> None:
        if not AppConfig().get_audio_online_metadata_enabled():
            dialog_lookup_status.setText(
                "La busqueda online esta desactivada en Configuracion."
            )
            return
        result = audio_fingerprint_service.get_or_lookup_online_metadata(
            target,
            current_lookup_payload(),
            force_refresh=True,
        )
        view._store_lookup_result(target, result, persist=True)
        view._variant_field_styles(highlighted_edits, False)
        populate_dialog_variants(result)
        view.refresh_library()
        view._restore_selected_file_paths([str(target)], str(target))
        view._update_library_detail_panel()
        view.lookup_status_label.setText(
            f"Busqueda online manual para editor: {target.name} | fuente={result.get('source', 'unknown')} | confianza={result.get('confidence', 0)}"
        )

    def mark_dialog_no_match() -> None:
        if view._set_track_no_match(target):
            view.refresh_library()
            view._restore_selected_file_paths([str(target)], str(target))
            view.refresh_missing_metadata()
            view._update_library_detail_panel()
            dialog.done(3)

    def choose_cover_from_dialog() -> None:
        view._select_row_by_file_path(str(target))
        if prompt_cover_choice(view, target):
            updated = current_lookup_result()
            update_dialog_cover(updated)
            populate_dialog_variants(updated)

    def show_diagnostics_from_dialog() -> None:
        view._select_row_by_file_path(str(target))
        show_lookup_diagnostics_dialog(view, target)

    dialog_lookup_btn.clicked.connect(lookup_from_dialog)
    use_variant_btn.clicked.connect(apply_selected_variant_to_form)
    choose_cover_btn.clicked.connect(choose_cover_from_dialog)
    diagnostics_btn.clicked.connect(show_diagnostics_from_dialog)
    no_match_btn.clicked.connect(mark_dialog_no_match)
    variants_table.itemSelectionChanged.connect(update_dialog_variant_details)
    variants_table.itemDoubleClicked.connect(
        lambda *_: apply_selected_variant_to_form()
    )
    skip_variant_btn.clicked.connect(lambda: dialog.done(2))

    if initial_lookup.get("candidates"):
        populate_dialog_variants(initial_lookup)
    else:
        variants_box.setVisible(False)
        variant_details.setPlainText(
            "Haz una busqueda online para ver variantes aqui mismo."
        )
        refresh_dialog_suggestion(initial_lookup)
        update_dialog_cover(initial_lookup)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    root_layout.addWidget(buttons)
    apply_dialog_surface(dialog)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        if dialog.result() == 2:
            return
        if dialog.result() == 3:
            view.status_update.emit(f"🚫 Marcada como no coincide: {target.name}")
            return
        return
    updates = {
        "title": audio_metadata_service.clean_track_title(title_edit.text()),
        "artist": artist_edit.text().strip(),
        "album": album_edit.text().strip(),
        "album_artist": album_artist_edit.text().strip(),
        "year": year_edit.text().strip(),
        "genre": genre_edit.text().strip(),
    }
    active_result = current_lookup_result()
    cover_art = view._fetch_cover_preview_bytes(target, active_result)
    if audio_metadata_service.update_track_tags(target, updates, cover_art=cover_art):
        invalidate_lookup_cache_if_manual_updates_conflict(view, target, updates)
        view._clear_no_match_status(target)
        view._sync_lookup_result_after_write(
            target,
            applied=view._selected_variant_matches_updates(active_result, updates),
        )
        view.status_update.emit("✏️ Metadatos editados: 1")
        view.refresh_library()
        view._restore_selected_file_paths([str(target)], str(target))
        view.refresh_missing_metadata()
        view._update_library_detail_panel()
