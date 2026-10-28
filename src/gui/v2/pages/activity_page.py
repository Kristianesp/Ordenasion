"""Actividad y registro unificados para la interfaz Fluent."""

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    ListWidget,
    MessageBox,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    TextEdit,
    TransparentToolButton,
)

from src.gui.task_center import task_registry
from src.utils.logger import warn
from src.utils.paths import open_in_file_manager
from src.gui.v2.components import EmptyState, GlassCard, PageHeader, prepare_page_surface


class ActivityPage(ScrollArea):
    """Combina tareas en segundo plano, historial y registro operativo.

    Depende solo del ``OrganizeController`` (estado, historial, deshacer y
    registro); las confirmaciones y el deshacer con diálogo los resuelve
    ``undo_handler`` si se proporciona.
    """

    def __init__(self, controller, undo_handler=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._undo_handler = undo_handler
        self.setObjectName("activityPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWidgetResizable(True)
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        self.content = QWidget()
        self.content.setObjectName("activityContent")
        self.setWidget(self.content)
        prepare_page_surface(self, self.content)
        self._build_ui()
        task_registry.tasks_updated.connect(self.refresh)
        controller.operation_state_changed.connect(self._on_operation_state_changed)
        log_appended = getattr(controller, "log_appended", None)
        if log_appended is not None:
            log_appended.connect(self._append_log_lines)
            controller.log_cleared.connect(self.log_widget.clear)
            self._append_log_lines(controller.log_history())
        self.refresh()
        self._refresh_history()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(28, 24, 28, 28)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(
            PageHeader(
                "Actividad",
                "Sigue procesos, mensajes y operaciones sin perder contexto.",
            )
        )

        body = QVBoxLayout()
        body.setSpacing(14)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)

        tasks_card = GlassCard()
        self.tasks_card = tasks_card
        tasks_layout = QVBoxLayout(tasks_card)
        tasks_layout.setContentsMargins(16, 16, 16, 16)
        tasks_layout.addWidget(SubtitleLabel("Tareas en segundo plano"))
        tasks_layout.addWidget(
            BodyLabel("Los análisis y operaciones siguen activos mientras exploras la app.")
        )
        self.task_list = ListWidget()
        self.empty_state = EmptyState(
            FluentIcon.SYNC, "No hay procesos activos. El resultado de cada análisis u organización aparecerá aquí.")
        self.empty_label = self.empty_state.text_label
        tasks_layout.addWidget(self.empty_state)
        self.task_list.setAccessibleName("Tareas en segundo plano")
        self.task_list.currentItemChanged.connect(self._render_task)
        tasks_layout.addWidget(self.task_list, 1)
        self.task_detail = TextEdit()
        self.task_detail.setAccessibleName("Detalle de tarea seleccionada")
        self.task_detail.setReadOnly(True)
        self.task_detail.setMinimumHeight(80)
        tasks_layout.addWidget(self.task_detail)
        actions = QHBoxLayout()
        self.cancel_button = PushButton(FluentIcon.CANCEL, "Cancelar seleccionada")
        self.cancel_button.setAccessibleName("Cancelar tarea seleccionada")
        self.cancel_button.clicked.connect(self.cancel_selected_task)
        actions.addWidget(self.cancel_button)
        self.result_button = PushButton(FluentIcon.HISTORY, "Ver último resultado")
        self.result_button.clicked.connect(self._show_result)
        actions.addWidget(self.result_button)
        self.undo_button = PushButton(FluentIcon.RETURN, "Deshacer última organización")
        self.undo_button.clicked.connect(self._undo_last)
        actions.addWidget(self.undo_button)
        actions.addStretch()
        tasks_layout.addLayout(actions)
        body.addWidget(tasks_card, 1)

        history_card = GlassCard()
        self.history_card = history_card
        history_layout = QVBoxLayout(history_card)
        history_layout.setContentsMargins(16, 16, 16, 16)
        history_layout.setSpacing(8)
        history_layout.addWidget(SubtitleLabel("Historial de organizaciones"))
        history_layout.addWidget(
            BodyLabel("Se conserva entre sesiones. Puedes deshacer cualquier organización que no se haya revertido.")
        )
        self.history_empty_state = EmptyState(FluentIcon.HISTORY, "Todavía no hay organizaciones registradas.")
        self.history_empty_label = self.history_empty_state.text_label
        history_layout.addWidget(self.history_empty_state)
        self.history_rows = QVBoxLayout()
        self.history_rows.setSpacing(6)
        history_layout.addLayout(self.history_rows)
        self.history_entries = []
        body.addWidget(history_card)

        log_card = GlassCard()
        self.log_card = log_card
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 16, 16, 16)
        log_header = QHBoxLayout()
        log_header.addWidget(SubtitleLabel("Registro técnico"))
        self.log_count_label = CaptionLabel("")
        log_header.addWidget(self.log_count_label)
        log_header.addStretch()
        clear_button = PushButton(FluentIcon.DELETE, "Limpiar")
        clear_button.clicked.connect(self.clear_log)
        log_header.addWidget(clear_button)
        export_button = PushButton(FluentIcon.DOWNLOAD, "Exportar")
        export_button.clicked.connect(self.export_log)
        log_header.addWidget(export_button)
        end_button = PushButton(FluentIcon.DOWN, "Ir al final")
        end_button.clicked.connect(self.scroll_log_to_bottom)
        log_header.addWidget(end_button)
        log_layout.addLayout(log_header)
        self.log_widget = TextEdit()
        self.log_widget.setObjectName("log_text")
        self.log_widget.setAccessibleName("Registro técnico")
        self.log_widget.setReadOnly(True)
        self.log_widget.setMinimumHeight(260)
        self.log_widget.document().setMaximumBlockCount(5000)
        log_layout.addWidget(self.log_widget, 1)
        self.log_toggle = PushButton("Mostrar registro técnico")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        body.addWidget(self.log_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        log_card.setVisible(False)
        body.addWidget(log_card, 1)

        layout.addLayout(body, 1)

    # ------------------------------------------------------------- tareas
    def refresh(self) -> None:
        self.result_button.setEnabled(bool(self.controller.last_operation_summary))
        self.undo_button.setEnabled(bool(self.controller.last_transaction_id)
                                    and not self.controller.current_organize_task_id
                                    and not getattr(self.controller, "current_rollback_task_id", None))
        current_id = None
        if self.task_list.currentItem():
            current_id = self.task_list.currentItem().data(Qt.ItemDataRole.UserRole)

        self.task_list.clear()
        tasks = sorted(task_registry.get_tasks(),
                       key=lambda entry: (entry[1]["status"] in {"En progreso", "Cancelación solicitada"}, entry[1]["started_at"]),
                       reverse=True)
        self.empty_state.setVisible(not tasks)
        self.task_list.setVisible(bool(tasks))
        self.task_detail.setVisible(bool(tasks))
        self.cancel_button.setVisible(bool(tasks))
        for task_id, task in tasks:
            duration = self._format_duration(task)
            self.task_list.addItem(f"{task['title']} · {task['status']} · {duration}")
            current = self.task_list.item(self.task_list.count() - 1)
            current.setData(Qt.ItemDataRole.UserRole, task_id)
            if task_id == current_id:
                self.task_list.setCurrentItem(current)

        if self.task_list.count() and self.task_list.currentItem() is None:
            self.task_list.setCurrentRow(0)
        elif not self.task_list.count():
            self.task_detail.setPlainText("No hay tareas registradas.")
            self.cancel_button.setEnabled(False)

    def _on_operation_state_changed(self) -> None:
        self.refresh()
        self._refresh_history()

    # ----------------------------------------------------------- historial
    HISTORY_LIMIT = 15
    _STATUS_LABELS = {
        "completado": "Completada",
        "completado con errores": "Con errores",
        "cancelado": "Cancelada",
        "error": "Error",
        "interrumpido": "Interrumpida",
        "en curso": "En curso",
    }

    def _history_entries(self) -> list:
        getter = getattr(self.controller, "get_transaction_history", None)
        if not callable(getter):
            return []
        try:
            return list(getter(self.HISTORY_LIMIT))
        except (OSError, ValueError, RuntimeError) as exc:
            warn(f"No se pudo leer el historial de organizaciones: {exc}")
            return []

    @classmethod
    def describe_transaction(cls, entry: dict) -> str:
        """Texto de una fila del historial."""
        try:
            moment = datetime.fromisoformat(entry.get("timestamp", ""))
            when = f"{moment:%Y-%m-%d %H:%M}"
        except (TypeError, ValueError):
            when = "Fecha desconocida"
        status = cls._STATUS_LABELS.get(entry.get("status"), entry.get("status") or "—")
        undo_state = entry.get("undo_state")
        if undo_state == "deshecha":
            status += " · deshecha"
        elif undo_state == "parcial":
            status += " · deshecha en parte"
        moves = entry.get("moves", 0)
        folder = entry.get("source_folder") or entry.get("description", "")
        return f"{when} · {status} · {moves} elementos movidos · {folder}"

    def _refresh_history(self) -> None:
        entries = self._history_entries()
        while self.history_rows.count():
            item = self.history_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.history_entries = []
        self.history_empty_state.setVisible(not entries)
        busy = bool(getattr(self.controller, "current_organize_task_id", None)
                    or getattr(self.controller, "current_rollback_task_id", None))
        can_rollback = callable(getattr(self.controller, "rollback_transaction", None)) or self._undo_handler
        for entry in entries:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            label = CaptionLabel(self.describe_transaction(entry))
            label.setWordWrap(True)
            label.setToolTip(entry.get("description", ""))
            row_layout.addWidget(label, 1)
            folder = entry.get("source_folder")
            if folder:
                open_button = TransparentToolButton(FluentIcon.FOLDER)
                open_button.setToolTip("Abrir en el Explorador")
                open_button.setAccessibleName(f"Abrir {folder} en el Explorador")
                open_button.setEnabled(Path(folder).exists())
                open_button.clicked.connect(lambda _checked=False, path=folder: open_in_file_manager(path))
                row_layout.addWidget(open_button)
            undo = PushButton(FluentIcon.RETURN, "Deshacer")
            undo.setAccessibleName(f"Deshacer organización del {entry.get('timestamp', '')}")
            undo.setEnabled(bool(entry.get("can_undo")) and not busy and bool(can_rollback))
            transaction_id = entry.get("id")
            undo.clicked.connect(lambda _checked=False, txn=transaction_id: self._undo(txn))
            row_layout.addWidget(undo)
            self.history_rows.addWidget(row)
            self.history_entries.append((transaction_id, undo, label))

    def _undo(self, transaction_id: str) -> None:
        if self._undo_handler is not None:
            self._undo_handler(transaction_id)
        else:
            self.controller.rollback_transaction(transaction_id)

    def _undo_last(self) -> None:
        transaction_id = self.controller.last_transaction_id
        if transaction_id:
            self._undo(transaction_id)

    def _render_task(self, current, _previous) -> None:
        if current is None:
            self.task_detail.clear()
            self.cancel_button.setEnabled(False)
            return
        task_id = current.data(Qt.ItemDataRole.UserRole)
        task = task_registry.get_task(task_id)
        if not task:
            self.task_detail.setPlainText("No hay datos disponibles.")
            return
        self.cancel_button.setEnabled(task["status"] == "En progreso"
                                      and callable(task.get("cancel_callback")))
        ended = task["ended_at"]
        self.task_detail.setPlainText(
            "\n".join(
                (
                    f"Estado: {task['status']}",
                    f"Inicio: {task['started_at']:%Y-%m-%d %H:%M:%S}",
                    f"Fin: {ended:%Y-%m-%d %H:%M:%S}" if ended else "Fin: —",
                    f"Último mensaje: {task['last_message'] or 'Sin mensajes aún.'}",
                )
            )
        )

    def cancel_selected_task(self) -> None:
        item = self.task_list.currentItem()
        if item and self.cancel_button.isEnabled():
            task_registry.cancel_task(item.data(Qt.ItemDataRole.UserRole))

    # ------------------------------------------------------------ registro
    def _append_log_lines(self, lines) -> None:
        if not lines:
            return
        self.log_widget.setUpdatesEnabled(False)
        try:
            for line in lines:
                self.log_widget.append(line)
        finally:
            self.log_widget.setUpdatesEnabled(True)
        self.scroll_log_to_bottom()
        self.log_count_label.setText(f"{getattr(self.controller, 'log_entry_count', 0)} entradas")

    def scroll_log_to_bottom(self) -> None:
        scrollbar = self.log_widget.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _confirm(self, title: str, content: str) -> bool:
        box = MessageBox(title, content, self.window())
        box.yesButton.setText("Limpiar")
        box.cancelButton.setText("Cancelar")
        return bool(box.exec())

    def clear_log(self) -> None:
        if not self._confirm("Limpiar registro", "¿Quieres limpiar todo el registro técnico? No se puede deshacer."):
            return
        self.controller.clear_log()
        self.log_count_label.setText("0 entradas")

    def export_log(self, filepath: str | None = None) -> bool:
        if filepath is None:
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Exportar registro", f"registro_ordenasion_{datetime.now():%Y%m%d_%H%M%S}.txt",
                "Archivos de texto (*.txt);;Todos los archivos (*)")
        if not filepath:
            return False
        try:
            count = self.controller.export_log(filepath)
        except OSError as exc:
            InfoBar.error("No se pudo exportar", str(exc), position=InfoBarPosition.TOP_RIGHT, parent=self)
            return False
        InfoBar.success("Registro exportado", f"{count} entradas en {filepath}",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)
        return True

    def _toggle_log(self, visible: bool) -> None:
        self.log_card.setVisible(visible)
        self.log_toggle.setText("Ocultar registro técnico" if visible else "Mostrar registro técnico")
        if visible:
            self.scroll_log_to_bottom()

    def _show_result(self) -> None:
        from src.gui.operation_summary_dialog import OperationSummaryDialog
        summary = self.controller.last_operation_summary
        if not summary:
            return
        undo = None
        transaction_id = summary.get("transaction_id")
        if transaction_id and not summary.get("undone"):
            undo = lambda: self._undo_without_confirm(transaction_id)
        OperationSummaryDialog(summary, self, undo_callback=undo).exec()

    def _undo_without_confirm(self, transaction_id: str) -> None:
        start = getattr(self.controller, "start_rollback", None)
        if callable(start):
            start(transaction_id)
        else:
            self._undo(transaction_id)

    @staticmethod
    def _format_duration(task: dict) -> str:
        end = task.get("ended_at") or datetime.now()
        seconds = int((end - task["started_at"]).total_seconds())
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"
