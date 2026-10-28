#!/usr/bin/env python3
"""Logica de la pestaña de duplicados musicales."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor, QBrush
from PyQt6.QtWidgets import QMenu, QListWidgetItem, QTableWidgetItem

from src.core.audio_index import audio_metadata_service
from src.gui.music_duplicates_presenters import (
    build_duplicate_hint,
    build_duplicate_preview_block,
)
from src.gui.music_duplicates_table_builders import build_duplicate_row_values
from src.gui.v2.theme import current_tokens, apply_menu_surface


def refresh_results(view: Any) -> None:
    view.groups_list.clear()
    view.duplicates_table.setRowCount(0)
    view.detail.clear()
    total_groups = len(view.results)
    total_files = sum(len(v) for v in view.results.values())
    view.summary_label.setText(
        f"Grupos: {total_groups} | Pistas candidatas: {total_files}"
    )

    for identity_key, items in view.results.items():
        best = items[0]
        label = f"{Path(best['file_path']).name} ({len(items)})"
        list_item = QListWidgetItem(label)
        list_item.setData(Qt.ItemDataRole.UserRole, identity_key)
        view.groups_list.addItem(list_item)

    if view.groups_list.count() > 0:
        view.groups_list.setCurrentRow(0)
    else:
        view.duplicate_group_info.setText(
            "No hay grupos de duplicados musicales en la carpeta analizada."
        )


def show_group_detail(view: Any, current: Any, previous: Any) -> None:
    del previous
    if not current:
        view.duplicates_table.setRowCount(0)
        view.detail.clear()
        view.best_duplicate_hint.setText(
            "La mejor copia sugerida se resaltara al analizar duplicados."
        )
        return
    identity_key = current.data(Qt.ItemDataRole.UserRole)
    group = view.results.get(identity_key, [])
    view.duplicate_group_info.setText(
        f"Candidatos musicales: {len(group)} copias. La similitud musical no confirma archivos idénticos; compara antes de retirar."
    )
    view.duplicates_table.setRowCount(0)
    view.duplicates_table.setSortingEnabled(False)
    removable_bytes = sum(int(item.get("file_size") or 0) for item in group[1:])
    tokens = current_tokens()
    for item_index, item in enumerate(group):
        row = view.duplicates_table.rowCount()
        view.duplicates_table.insertRow(row)
        is_best = item_index == 0
        display_item = dict(item)
        display_item["duration_text"] = view._format_duration(item.get("duration"))
        display_item["bitrate_text"] = view._format_bitrate(item.get("bitrate"))
        display_item["file_size_text"] = view._format_file_size(item.get("file_size"))
        values = build_duplicate_row_values(display_item, is_best)
        for col, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            if col in (0, 1):
                cell.setData(
                    Qt.ItemDataRole.UserRole, str(Path(item.get("file_path", "")))
                )
            if is_best:
                cell.setBackground(QBrush(QColor(tokens.surface_alt)))
                cell.setForeground(QBrush(QColor(tokens.text_primary)))
            elif col == 0:
                cell.setBackground(QBrush(QColor(tokens.surface)))
                cell.setForeground(QBrush(QColor(tokens.text_primary)))
            view.duplicates_table.setItem(row, col, cell)
    view.duplicates_table.setSortingEnabled(True)
    if group:
        best = group[0]
        view.best_duplicate_hint.setText(build_duplicate_hint(best, removable_bytes))
    if view.duplicates_table.rowCount() > 0:
        view.duplicates_table.selectRow(0)
    update_duplicate_preview(view)


def selected_duplicate_paths(view: Any) -> List[str]:
    paths: list[str] = []
    rows = sorted({index.row() for index in view.duplicates_table.selectedIndexes()})
    for row in rows:
        item = view.duplicates_table.item(row, 0)
        if not item:
            continue
        file_path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if file_path:
            paths.append(file_path)
    return paths


def update_duplicate_preview(view: Any) -> None:
    selected_paths = selected_duplicate_paths(view)
    view.delete_duplicate_btn.setEnabled(bool(selected_paths))
    if not selected_paths:
        view.detail.clear()
        return
    current_group_item = view.groups_list.currentItem()
    current_group = []
    if current_group_item is not None:
        current_group = list(
            view.results.get(current_group_item.data(Qt.ItemDataRole.UserRole), [])
        )
    best_path = (
        str(Path(current_group[0].get("file_path", ""))) if current_group else ""
    )
    lines = []
    for file_path in selected_paths[:3]:
        path = Path(file_path)
        metadata = audio_metadata_service.get_metadata(path) or {}
        recommendation = "Conservar" if str(path) == best_path else "Revisar/eliminar"
        lines.append(build_duplicate_preview_block(path, metadata, recommendation))
    if len(selected_paths) > 3:
        lines.append(f"...y {len(selected_paths) - 3} pista(s) mas seleccionadas")
    if best_path:
        lines.append(f"\nMejor copia sugerida actual: {Path(best_path).name}")
    view.detail.setPlainText("\n\n".join(lines))


def select_best_duplicate(view: Any) -> None:
    if view.duplicates_table.rowCount() <= 0:
        return
    for row in range(view.duplicates_table.rowCount()):
        item = view.duplicates_table.item(row, 0)
        if item and str(item.text()).startswith("⭐"):
            view.duplicates_table.selectRow(row)
            view.duplicates_table.scrollToItem(item)
            return
    view.duplicates_table.selectRow(0)
    view.duplicates_table.scrollToItem(view.duplicates_table.item(0, 0))


def mark_selected_duplicate_as_keep(view: Any) -> None:
    current_group_item = view.groups_list.currentItem()
    if current_group_item is None:
        return
    identity_key = current_group_item.data(Qt.ItemDataRole.UserRole)
    group = list(view.results.get(identity_key, []))
    selected_paths = selected_duplicate_paths(view)
    if not group or not selected_paths:
        return
    target_path = str(Path(selected_paths[0]))
    selected_item = None
    remaining: list[Dict[str, Any]] = []
    for item in group:
        normalized = str(Path(item.get("file_path", "")))
        if normalized == target_path and selected_item is None:
            selected_item = item
        else:
            remaining.append(item)
    if selected_item is None:
        return
    view.results[str(identity_key)] = [selected_item] + remaining
    show_group_detail(view, current_group_item, None)
    for row in range(view.duplicates_table.rowCount()):
        row_item = view.duplicates_table.item(row, 0)
        if (
            row_item
            and str(row_item.data(Qt.ItemDataRole.UserRole) or "") == target_path
        ):
            view.duplicates_table.selectRow(row)
            view.duplicates_table.scrollToItem(row_item)
            break
    view.status_update.emit(f"⭐ Marcada como conservar: {Path(target_path).name}")


def show_duplicates_context_menu(view: Any, position) -> None:
    index = view.duplicates_table.indexAt(position)
    if not index.isValid():
        return
    view.duplicates_table.selectRow(index.row())
    menu = QMenu(view)
    apply_menu_surface(menu)
    select_best_action = QAction("Ir a mejor copia", view)
    select_best_action.triggered.connect(view._select_best_duplicate)
    menu.addAction(select_best_action)
    keep_action = QAction("Marcar como conservar", view)
    keep_action.triggered.connect(view._mark_selected_duplicate_as_keep)
    menu.addAction(keep_action)
    play_action = QAction("Reproducir", view)
    play_action.triggered.connect(view.play_selected_duplicate)
    menu.addAction(play_action)
    open_action = QAction("Abrir carpeta", view)
    open_action.triggered.connect(view.open_selected_duplicate_folder)
    menu.addAction(open_action)
    delete_action = QAction("Enviar a papelera", view)
    delete_action.triggered.connect(view.delete_selected_duplicates)
    menu.addAction(delete_action)
    viewport = view.duplicates_table.viewport() or view.duplicates_table
    menu.exec(viewport.mapToGlobal(position))
