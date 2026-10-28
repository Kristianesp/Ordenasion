#!/usr/bin/env python3
"""Dialog helpers for choosing metadata variants."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
)
from src.gui.v2.theme import apply_dialog_surface


VARIANT_TABLE_HEADERS = [
    "Fuente",
    "Confianza",
    "Titulo",
    "Artista",
    "Album",
    "Año",
    "MBID",
]


def configure_variant_table(variants_table: QTableWidget) -> None:
    variants_table.setColumnCount(len(VARIANT_TABLE_HEADERS))
    variants_table.setHorizontalHeaderLabels(VARIANT_TABLE_HEADERS)
    variants_table.setSelectionBehavior(variants_table.SelectionBehavior.SelectRows)
    variants_table.setSelectionMode(variants_table.SelectionMode.SingleSelection)
    variants_table.setAlternatingRowColors(True)
    variant_header = variants_table.horizontalHeader()
    if variant_header is None:
        return
    variant_header.setStretchLastSection(False)
    variant_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    variant_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    variant_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
    variant_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
    variant_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
    variant_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
    variant_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)


def populate_variant_table(
    variants_table: QTableWidget, candidates: list[Dict[str, Any]]
) -> None:
    variants_table.setRowCount(0)
    for index, candidate in enumerate(candidates):
        suggested = candidate.get("suggested_updates", {})
        row = variants_table.rowCount()
        variants_table.insertRow(row)
        values = [
            candidate.get("source", "unknown"),
            str(candidate.get("confidence", 0)),
            suggested.get("title", ""),
            suggested.get("artist", ""),
            suggested.get("album", ""),
            suggested.get("year", ""),
            candidate.get("mbid", ""),
        ]
        for col, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            if col == 0:
                cell.setData(Qt.ItemDataRole.UserRole, index)
            variants_table.setItem(row, col, cell)


def selected_variant_index(variants_table: QTableWidget) -> int | None:
    row = variants_table.currentRow()
    if row < 0:
        return None
    first_cell = variants_table.item(row, 0)
    if first_cell is None:
        return None
    return int(first_cell.data(Qt.ItemDataRole.UserRole))


def build_variant_details_text(
    file_name: str, candidate: Dict[str, Any], result: Dict[str, Any]
) -> str:
    suggested = candidate.get("suggested_updates", {})
    diagnostics = candidate.get("diagnostics", {})
    return "\n".join(
        [
            f"Archivo: {file_name}",
            f"Confianza: {candidate.get('confidence', 0)}",
            f"Fuente: {candidate.get('source', result.get('source', 'unknown'))}",
            f"Titulo: {suggested.get('title', '')}",
            f"Artista: {suggested.get('artist', '')}",
            f"Album: {suggested.get('album', '')}",
            f"Año: {suggested.get('year', '')}",
            f"MBID: {candidate.get('mbid', '')}",
            f"Diagnostico: {candidate.get('reason', result.get('reason', 'ok'))}",
            "Fingerprint: "
            f"{diagnostics.get('fingerprint_strategy', result.get('fingerprint_strategy', 'none'))}",
        ]
    )


def prompt_variant_choice(
    view: Any, file_path: str, position: int, total: int
) -> int | None:
    result = view._get_lookup_result(file_path)
    if not result:
        return None
    candidates = list(result.get("candidates") or [])
    if len(candidates) <= 1:
        return 0

    dialog = QDialog(view)
    dialog.setObjectName("musicVariantChoiceDialog")
    dialog.setWindowTitle(
        f"Elegir variante [{position}/{total}] - {Path(file_path).name}"
    )
    dialog.resize(860, 420)
    layout = QVBoxLayout(dialog)

    info = QLabel(
        "Selecciona la variante a dejar como sugerencia activa. Al aceptar pasa a la siguiente pista."
    )
    info.setWordWrap(True)
    layout.addWidget(info)

    variants_table = QTableWidget(0, len(VARIANT_TABLE_HEADERS))
    configure_variant_table(variants_table)
    details = QTextEdit()
    details.setReadOnly(True)
    layout.addWidget(variants_table, 2)
    layout.addWidget(details, 3)

    populate_variant_table(variants_table, candidates)

    def update_variant_details() -> None:
        candidate_index = selected_variant_index(variants_table)
        if candidate_index is None or not (0 <= candidate_index < len(candidates)):
            details.clear()
            return
        details.setPlainText(
            build_variant_details_text(
                Path(file_path).name, candidates[candidate_index], result
            )
        )

    variants_table.itemSelectionChanged.connect(update_variant_details)
    variants_table.itemDoubleClicked.connect(lambda *_: dialog.accept())

    selected_index = int(result.get("selected_candidate_index", 0) or 0)
    if 0 <= selected_index < variants_table.rowCount():
        variants_table.selectRow(selected_index)
    elif variants_table.rowCount() > 0:
        variants_table.selectRow(0)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    skip_button = buttons.addButton(
        "Omitir",
        QDialogButtonBox.ButtonRole.ActionRole,
    )
    no_match_button = buttons.addButton(
        "No coincide",
        QDialogButtonBox.ButtonRole.ActionRole,
    )
    if skip_button is not None:
        skip_button.pressed.connect(lambda: dialog.done(2))
    if no_match_button is not None:
        no_match_button.pressed.connect(lambda: dialog.done(3))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    apply_dialog_surface(dialog)
    dialog_result = dialog.exec()
    if dialog_result == 2:
        return -1
    if dialog_result == 3:
        return -2
    if dialog_result != QDialog.DialogCode.Accepted:
        return None
    return selected_variant_index(variants_table)
