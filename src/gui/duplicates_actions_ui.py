#!/usr/bin/env python3
"""Acciones del panel de duplicados: retirar, mover, hardlinks, conservar e ignorar.

Toda operación sobre disco se ejecuta en ``DuplicateActionWorker`` (fuera del
hilo de la interfaz) y cada archivo se verifica contra la copia que se conserva.
Nunca se permite retirar todas las copias de un grupo.
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List

from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from src.core.duplicate_actions import (
    ACTION_DELETE,
    ACTION_HARDLINK,
    ACTION_LABELS,
    ACTION_MOVE,
    KEEP_RULES,
    DuplicateActionWorker,
    build_plan,
    export_plan_csv,
    find_emptied_groups,
)
from src.gui.task_center import task_registry


class DuplicatesActionsMixin:
    """Mixin para ``DuplicatesDashboard``."""

    # ------------------------------------------------------------------ menú
    def build_keep_rules_menu(self, menu):
        rules_menu = menu.addMenu("Regla para conservar")
        self.keep_rule_group = QActionGroup(self)
        self.keep_rule_group.setExclusive(True)
        current = self.app_config.get("duplicates.keep_rule", "newest")
        self.keep_rule_actions = {}
        for rule, label in KEEP_RULES.items():
            action = QAction(label, self, checkable=True)
            action.setChecked(rule == current)
            action.triggered.connect(lambda _checked=False, r=rule: self.set_keep_rule(r))
            self.keep_rule_group.addAction(action)
            rules_menu.addAction(action)
            self.keep_rule_actions[rule] = action
        rules_menu.addSeparator()
        self.add_preferred_folder_action = rules_menu.addAction("Añadir carpeta preferida…")
        self.add_preferred_folder_action.triggered.connect(self.add_preferred_folder)
        self.clear_preferred_folders_action = rules_menu.addAction("Quitar carpetas preferidas")
        self.clear_preferred_folders_action.triggered.connect(self.clear_preferred_folders)
        self.verify_bytes_action = QAction("Verificar byte a byte antes de retirar", self, checkable=True)
        self.verify_bytes_action.setChecked(bool(self.app_config.get("duplicates.verify_bytes_before_delete", False)))
        self.verify_bytes_action.toggled.connect(
            lambda value: self.app_config.set("duplicates.verify_bytes_before_delete", bool(value)))
        menu.addAction(self.verify_bytes_action)

    def set_keep_rule(self, rule: str):
        self.app_config.set("duplicates.keep_rule", rule)
        self.log_message(f"🧭 Regla para conservar: {KEEP_RULES.get(rule, rule)}")
        self.populate_table()

    def add_preferred_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Carpeta cuyas copias se conservan",
                                                  str(self.current_folder or Path.home()))
        if not folder:
            return
        folders = list(self.app_config.get("duplicates.preferred_folders", []) or [])
        if folder not in folders:
            folders.append(folder)
        self.app_config.set("duplicates.preferred_folders", folders)
        self.app_config.set("duplicates.keep_rule", "preferred_folder")
        if "preferred_folder" in getattr(self, "keep_rule_actions", {}):
            self.keep_rule_actions["preferred_folder"].setChecked(True)
        self.log_message(f"📂 Carpeta preferida añadida: {folder}")
        self.populate_table()

    def clear_preferred_folders(self):
        self.app_config.set("duplicates.preferred_folders", [])
        self.populate_table()

    # ------------------------------------------------------------------ selección
    def _marked_paths(self) -> List[str]:
        return self.duplicates_model.get_checked_paths()

    def _groups_from_model(self) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for item in self.duplicates_model._all_rows():
            groups.setdefault(str(item.get("group_key")), []).append(str(item.get("path")))
        return groups

    def _keep_paths_from_model(self) -> Dict[str, str]:
        return {str(item.get("group_key")): str(item.get("path"))
                for item in self.duplicates_model._all_rows() if item.get("is_original")}

    def _sizes_from_model(self) -> Dict[str, int]:
        return {str(item.get("path")): int(item.get("size") or 0)
                for item in self.duplicates_model._all_rows()}

    def _get_selected_file_entries(self):
        """Compatibilidad: archivos marcados (todas las páginas) y su metadata legible."""
        files, info = [], []
        for item in self.duplicates_model.get_checked_entries():
            path = Path(item.get("path", ""))
            files.append(path)
            info.append({"name": path.name, "path": path,
                         "size": f"{item.get('size', 0) / (1024 * 1024):.2f} MB",
                         "location": item.get("location", "")})
        return files, info

    def _block_if_emptying(self, marked: List[str]) -> bool:
        groups = self._groups_from_model()
        emptied = find_emptied_groups(groups, marked, exists=lambda _p: True)
        if not emptied:
            return False
        names = []
        for key in emptied[:5]:
            first = groups[key][0] if groups.get(key) else key
            names.append(f"• {Path(first).name}")
        QMessageBox.warning(
            self,
            "No se pueden retirar todas las copias",
            f"Has marcado todas las copias de {len(emptied)} grupo(s). "
            "Desmarca al menos una copia en cada grupo para conservarla.\n\n" + "\n".join(names),
        )
        self.log_message(f"⛔ Bloqueado: {len(emptied)} grupo(s) quedarían sin ninguna copia")
        return True

    # ------------------------------------------------------------------ acciones
    def delete_selected(self):
        self._run_action(ACTION_DELETE)

    def move_selected(self):
        self._run_action(ACTION_MOVE)

    def replace_with_hardlinks(self):
        self._run_action(ACTION_HARDLINK)

    def delete_single_file(self, row):
        row_data = self.duplicates_model.get_row_data(row)
        if not row_data or not row_data.get("path"):
            return
        self._run_action(ACTION_DELETE, marked=[str(row_data["path"])])

    def on_table_double_clicked(self, index):
        if index.isValid() and index.column() == 6:
            self.delete_single_file(index.row())

    def _build_current_plan(self, action: str, marked: List[str], destination_dir=None):
        return build_plan(
            self._groups_from_model(), marked, action,
            sizes=self._sizes_from_model(),
            keep_paths=self._keep_paths_from_model(),
            destination_dir=destination_dir,
            group_meta=self.group_meta,
            exists=lambda _p: True,
        )

    def _run_action(self, action: str, marked: List[str] = None):
        if getattr(self, "action_worker", None) is not None and self.action_worker.isRunning():
            QMessageBox.information(self, "Duplicados", "Ya hay una operación en curso.")
            return
        marked = list(marked if marked is not None else self._marked_paths())
        if not marked:
            QMessageBox.information(
                self, "Sin selección",
                "No hay archivos marcados.\n\nMarca las copias que quieres retirar; "
                "la copia indicada como «Conservar» se mantiene.",
            )
            return
        if self._block_if_emptying(marked):
            return
        destination_dir = None
        if action == ACTION_MOVE:
            default = Path(self.current_folder or Path.home()) / ".duplicates_quarantine"
            destination_dir = str(default)
        plan = self._build_current_plan(action, marked, destination_dir)
        if action == ACTION_HARDLINK:
            plan = [item for item in plan if not item.similar_only]
        if not plan:
            QMessageBox.information(self, "Duplicados", "No hay acciones aplicables a la selección.")
            return

        similar = [item for item in plan if item.similar_only]
        if similar:
            reply = QMessageBox.warning(
                self, "Imágenes parecidas, no idénticas",
                f"{len(similar)} archivo(s) son imágenes PARECIDAS, no copias exactas. "
                "No se puede verificar que sean iguales.\n\n¿Seguro que quieres continuar con ellas?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        verify_bytes = bool(self.app_config.get("duplicates.verify_bytes_before_delete", False))
        file_list = "\n".join(f"• {Path(item.source).name} — se conserva {Path(item.reference).name}"
                              for item in plan[:10])
        if len(plan) > 10:
            file_list += f"\n… y {len(plan) - 10} más"
        unconfirmed = sum(1 for item in plan if not item.confirmed and not item.similar_only)
        verification = (
            "Antes de cada operación se calcula el hash completo y se compara con la copia que se conserva"
            + (" (y byte a byte)" if verify_bytes else "") + "; si no coinciden, el archivo se omite."
        )
        if unconfirmed:
            verification += f"\n{unconfirmed} archivo(s) son candidatos sin confirmar: se confirmarán ahora."
        details = {
            ACTION_DELETE: "Se retirarán a la papelera (o a .quarantine si no hay papelera).",
            ACTION_MOVE: f"Se moverán a {destination_dir}.",
            ACTION_HARDLINK: "Cada copia se sustituirá por un hardlink a la que se conserva "
                             "(mismo volumen, contenido verificado byte a byte).",
        }[action]
        reply = QMessageBox.question(
            self, f"Confirmar: {ACTION_LABELS[action]}",
            f"{len(plan)} archivo(s). {details}\n\n{file_list}\n\n{verification}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._start_action_worker(plan, verify_bytes)

    def _start_action_worker(self, plan, verify_bytes: bool):
        self.action_worker = DuplicateActionWorker(
            plan, self.transaction_manager, verify_hash=True, verify_bytes=verify_bytes,
        )
        self.action_worker.progress.connect(self._on_action_progress)
        self.action_worker.finished_ok.connect(self._on_action_finished)
        self.action_worker.failed.connect(self._on_action_failed)
        self._set_actions_busy(True)
        self.action_task_id = f"duplicates_action_{int(datetime.now().timestamp())}"
        task_registry.start_task(self.action_task_id, "Acciones sobre duplicados", self.action_worker.stop)
        self.action_worker.start()

    def _set_actions_busy(self, busy: bool):
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
        for widget in (self.delete_btn, self.move_btn, self.scan_btn):
            widget.setEnabled(not busy)
        if not busy:
            self.update_statistics_from_selection()
            self.scan_btn.setEnabled(bool(self.current_folder))

    def _on_action_progress(self, message: str, current: int, total: int):
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(current)
        if getattr(self, "action_task_id", None):
            task_registry.update_task(self.action_task_id, f"{current}/{total} {message}")

    def _on_action_failed(self, message: str):
        self._set_actions_busy(False)
        if getattr(self, "action_task_id", None):
            task_registry.finish_task(self.action_task_id, "Error")
            self.action_task_id = None
        self.log_message(f"❌ Error en la operación: {message}")
        QMessageBox.critical(self, "Error", f"Error durante la operación:\n{message}")

    def _on_action_finished(self, summary: dict):
        self._set_actions_busy(False)
        if getattr(self, "action_task_id", None):
            task_registry.finish_task(self.action_task_id, "Cancelada" if summary.get("cancelled") else "Completada")
            self.action_task_id = None
        done = summary.get("done", [])
        skipped = summary.get("skipped", [])
        failed = summary.get("failed", [])
        self.last_action_plan = summary.get("plan", [])
        for item in done:
            destination = item.get("destination") or ""
            self.log_message(f"✅ {Path(item['source']).name}: {ACTION_LABELS.get(item['action'])}"
                             + (f" → {destination}" if destination else ""))
        for item in skipped:
            self.log_message(f"⚠️ Omitido {Path(item['source']).name}: {item.get('reason')}")
        for item in failed:
            self.log_message(f"❌ Error con {Path(item['source']).name}: {item.get('reason')}")
        removed = [item["source"] for item in done if item.get("action") != ACTION_HARDLINK]
        linked = [item["source"] for item in done if item.get("action") == ACTION_HARDLINK]
        if removed or linked:
            self._forget_paths(removed + linked)
        mb = summary.get("bytes", 0) / (1024 * 1024)
        text = (f"Hechos: {len(done)} ({mb:.1f} MB)\nOmitidos tras verificar: {len(skipped)}\n"
                f"Errores: {len(failed)}")
        if summary.get("cancelled"):
            text += "\n\nOperación cancelada: el resto no se ha tocado."
        if skipped or failed:
            reasons = "\n".join(f"• {Path(i['source']).name}: {i.get('reason')}" for i in (skipped + failed)[:8])
            text += f"\n\nMotivos:\n{reasons}"
        QMessageBox.information(self, "Operación terminada", text)

    def _forget_paths(self, paths: List[str]):
        """Quita rutas de los resultados sin volver a leer el disco."""
        gone = {str(p) for p in paths}
        updated = {}
        for key, files in self.duplicates_data.items():
            remaining = [p for p in files if str(p) not in gone]
            if len(remaining) >= 2:
                updated[key] = remaining
        self.duplicates_data = updated
        self.duplicates_model.remove_paths(gone)
        self.update_pagination_controls()
        self.update_statistics_from_table()
        self._update_empty_state()

    # ------------------------------------------------------------------ plan / exportación
    def export_deletion_plan(self):
        marked = self._marked_paths()
        if not marked:
            QMessageBox.information(self, "Exportar plan", "Marca primero los archivos a retirar.")
            return
        plan = self._build_current_plan(ACTION_DELETE, marked)
        emptied = find_emptied_groups(self._groups_from_model(), marked, exists=lambda _p: True)
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar plan de borrado",
            f"plan_duplicados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", "CSV (*.csv)")
        if not file_path:
            return
        for item in plan:
            item.status = "previsto"
        try:
            export_plan_csv(plan, file_path)
        except OSError as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar: {e}")
            return
        extra = f"\nAtención: {len(emptied)} grupo(s) se quedarían sin copia y no se incluyen." if emptied else ""
        self.log_message(f"📄 Plan exportado ({len(plan)} filas): {file_path}")
        QMessageBox.information(self, "Plan exportado", f"Plan guardado en:\n{file_path}{extra}")

    def export_results(self):
        if not self.duplicates_data:
            QMessageBox.information(self, "Información", "No hay resultados para exportar")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Exportar resultados",
            f"duplicados_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt", "Archivos de texto (*.txt)")
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("REPORTE DE ARCHIVOS DUPLICADOS\n" + "=" * 50 + "\n\n")
                for i, (key, paths) in enumerate(self.duplicates_data.items(), 1):
                    if len(paths) < 2:
                        continue
                    meta = self.group_meta.get(key, {})
                    state = "confirmado" if meta.get("confirmed") else "sin confirmar"
                    f.write(f"GRUPO {i} ({len(paths)} archivos, {state}):\nHash/ID: {key}\n")
                    for path in paths:
                        f.write(f"  • {path}\n")
                    f.write("\n")
            self.log_message(f"📄 Resultados exportados a: {file_path}")
        except OSError as e:
            QMessageBox.critical(self, "Error", f"Error al exportar: {e}")

    # ------------------------------------------------------------------ ignorar / conservar
    def _content_key_for_row(self, row_data) -> str:
        key = str(row_data.get("group_key") or "")
        return self._content_key(key)

    def ignore_selected_group(self):
        index = self.duplicates_table.currentIndex()
        if not index.isValid():
            return
        row_data = self.duplicates_model.get_row_data(index.row())
        if not row_data:
            return
        content_key = self._content_key_for_row(row_data)
        if not content_key:
            QMessageBox.information(
                self, "Ignorar grupo",
                "Este grupo es un candidato sin confirmar (modo Rápido). Para ignorarlo de forma "
                "permanente hace falta su hash de contenido: analiza en modo Híbrido o Profundo.")
            return
        self.ignored_hashes.add(content_key)
        self.app_config.set_ignored_duplicate_hashes(list(self.ignored_hashes))
        self.log_message(f"🙈 Grupo ignorado: {content_key[:24]}")
        self.populate_table()

    def mark_selected_as_preferred_original(self):
        index = self.duplicates_table.currentIndex()
        if not index.isValid():
            return
        row_data = self.duplicates_model.get_row_data(index.row())
        if not row_data or not row_data.get("path"):
            return
        path = str(row_data["path"])
        group_key = str(row_data.get("group_key") or "")
        content_key = self._content_key_for_row(row_data)
        self.session_keep[group_key] = path
        if content_key:
            self.preferred_originals[content_key] = path
            self.app_config.set_preferred_original(content_key, path)
        self.log_message(f"🟢 Se conserva: {Path(path).name}")
        self.populate_table()
