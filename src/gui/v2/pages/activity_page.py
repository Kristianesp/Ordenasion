"""Actividad y registro unificados para la interfaz Fluent."""

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    ListWidget,
    PushButton,
    SubtitleLabel,
    TextEdit,
)

from src.gui.task_center import task_registry
from src.gui.v2.components import GlassCard, PageHeader


class ActivityPage(QWidget):
    """Combina tareas en segundo plano y el registro operativo."""

    def __init__(self, controller, log_widget, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.log_widget = log_widget
        self.setObjectName("activityPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()
        task_registry.tasks_updated.connect(self.refresh)
        controller.operation_state_changed.connect(self.refresh)
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
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
        self.empty_label = BodyLabel("No hay procesos activos. El resultado de cada organización aparecerá aquí.")
        self.empty_label.setWordWrap(True)
        tasks_layout.addWidget(self.empty_label)
        self.task_list.setAccessibleName("Tareas en segundo plano")
        self.task_list.currentItemChanged.connect(self._render_task)
        tasks_layout.addWidget(self.task_list, 1)
        self.task_detail = TextEdit()
        self.task_detail.setAccessibleName("Detalle de tarea seleccionada")
        self.task_detail.setReadOnly(True)
        self.task_detail.setMinimumHeight(80)
        tasks_layout.addWidget(self.task_detail)
        self.cancel_button = PushButton(FluentIcon.CANCEL, "Cancelar seleccionada")
        self.cancel_button.setAccessibleName("Cancelar tarea seleccionada")
        self.cancel_button.clicked.connect(self.cancel_selected_task)
        tasks_layout.addWidget(self.cancel_button)
        self.result_button = PushButton(FluentIcon.HISTORY, "Ver último resultado")
        self.result_button.clicked.connect(self._show_result)
        tasks_layout.addWidget(self.result_button)
        self.undo_button = PushButton(FluentIcon.RETURN, "Deshacer última organización")
        self.undo_button.clicked.connect(self.controller.rollback_last_operation)
        tasks_layout.addWidget(self.undo_button)
        body.addWidget(tasks_card, 1)

        log_card = GlassCard()
        self.log_card = log_card
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(16, 16, 16, 16)
        log_header = QHBoxLayout()
        log_header.addWidget(SubtitleLabel("Registro técnico"))
        log_header.addStretch()
        clear_button = PushButton(FluentIcon.DELETE, "Limpiar")
        clear_button.clicked.connect(self.controller.clear_log)
        log_header.addWidget(clear_button)
        export_button = PushButton(FluentIcon.DOWNLOAD, "Exportar")
        export_button.clicked.connect(self.controller.export_log)
        log_header.addWidget(export_button)
        log_layout.addLayout(log_header)

        self.log_widget.setParent(log_card)
        log_layout.addWidget(self.log_widget, 1)
        bottom = QHBoxLayout()
        bottom.addStretch()
        end_button = PushButton(FluentIcon.DOWN, "Ir al final")
        end_button.clicked.connect(self.controller.scroll_log_to_bottom)
        bottom.addWidget(end_button)
        log_layout.addLayout(bottom)
        self.log_toggle = PushButton("Mostrar registro técnico")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_log)
        body.addWidget(self.log_toggle)
        log_card.setVisible(False)
        body.addWidget(log_card, 1)

        layout.addLayout(body, 1)

    def refresh(self) -> None:
        self.result_button.setEnabled(bool(self.controller.last_operation_summary))
        self.undo_button.setEnabled(bool(self.controller.last_transaction_id)
                                    and not self.controller.current_organize_task_id)
        current_id = None
        if self.task_list.currentItem():
            current_id = self.task_list.currentItem().data(Qt.ItemDataRole.UserRole)

        self.task_list.clear()
        tasks = sorted(task_registry.get_tasks(),
                       key=lambda entry: (entry[1]["status"] in {"En progreso", "Cancelación solicitada"}, entry[1]["started_at"]),
                       reverse=True)
        self.empty_label.setVisible(not tasks)
        self.task_list.setVisible(bool(tasks))
        self.task_detail.setVisible(bool(tasks))
        self.tasks_card.setMaximumHeight(16777215 if tasks else 220)
        for task_id, task in tasks:
            duration = self._format_duration(task)
            item = self.task_list.addItem(
                f"{task['title']} · {task['status']} · {duration}"
            )
            current = self.task_list.item(self.task_list.count() - 1)
            current.setData(Qt.ItemDataRole.UserRole, task_id)
            if task_id == current_id:
                self.task_list.setCurrentItem(current)

        if self.task_list.count() and self.task_list.currentItem() is None:
            self.task_list.setCurrentRow(0)
        elif not self.task_list.count():
            self.task_detail.setPlainText("No hay tareas registradas.")
            self.cancel_button.setEnabled(False)

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

    def _toggle_log(self, visible: bool) -> None:
        self.log_card.setVisible(visible)
        self.log_toggle.setText("Ocultar registro técnico" if visible else "Mostrar registro técnico")

    def _show_result(self) -> None:
        from src.gui.operation_summary_dialog import OperationSummaryDialog
        if self.controller.last_operation_summary:
            OperationSummaryDialog(self.controller.last_operation_summary, self).exec()

    @staticmethod
    def _format_duration(task: dict) -> str:
        end = task.get("ended_at") or datetime.now()
        seconds = int((end - task["started_at"]).total_seconds())
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"
