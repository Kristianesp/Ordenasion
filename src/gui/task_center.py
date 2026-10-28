#!/usr/bin/env python3
"""
Centro sencillo de tareas en segundo plano.
"""

from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class BackgroundTaskRegistry(QObject):
    """Registro compartido de tareas en segundo plano."""

    tasks_updated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._tasks: dict[str, dict] = {}

    def start_task(
        self,
        task_id: str,
        title: str,
        cancel_callback: Optional[Callable[[], None]] = None,
    ):
        self._tasks[task_id] = {
            "title": title,
            "status": "En progreso",
            "started_at": datetime.now(),
            "ended_at": None,
            "last_message": "",
            "cancel_callback": cancel_callback,
        }
        self.tasks_updated.emit()

    def update_task(self, task_id: str, message: str):
        task = self._tasks.get(task_id)
        if not task:
            return
        task["last_message"] = message
        self.tasks_updated.emit()

    def finish_task(self, task_id: str, status: str = "Completada"):
        task = self._tasks.get(task_id)
        if not task:
            return
        task["status"] = status
        task["ended_at"] = datetime.now()
        self.tasks_updated.emit()

    def cancel_task(self, task_id: str):
        task = self._tasks.get(task_id)
        if not task:
            return
        if task["status"] != "En progreso" or not callable(task.get("cancel_callback")):
            return
        callback = task.get("cancel_callback")
        if callback:
            callback()
        task["status"] = "Cancelación solicitada"
        self.tasks_updated.emit()

    def get_tasks(self) -> list[tuple[str, dict]]:
        return list(self._tasks.items())

    def get_task(self, task_id: str) -> Optional[dict]:
        """Obtiene una tarea concreta."""
        task = self._tasks.get(task_id)
        return dict(task) if task else None


task_registry = BackgroundTaskRegistry()


class TaskCenterDialog(QDialog):
    """Diálogo para ver estado, duración y cancelación de tareas."""

    def __init__(self, parent=None, registry: BackgroundTaskRegistry = task_registry):
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle("🧵 Centro de tareas")
        self.resize(640, 420)
        self._build_ui()
        self.registry.tasks_updated.connect(self.refresh)
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Tareas en segundo plano, duración y último estado."))

        body = QHBoxLayout()
        self.task_list = QListWidget()
        self.task_list.currentItemChanged.connect(self._render_details)
        body.addWidget(self.task_list, 1)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        body.addWidget(self.details, 1)
        layout.addLayout(body, 1)

        actions = QHBoxLayout()
        self.cancel_btn = QPushButton("⛔ Cancelar tarea")
        self.cancel_btn.clicked.connect(self.cancel_selected_task)
        actions.addWidget(self.cancel_btn)
        actions.addStretch()
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    def refresh(self):
        current_task_id = None
        if self.task_list.currentItem():
            current_task_id = self.task_list.currentItem().data(256)
        self.task_list.clear()
        for task_id, data in self.registry.get_tasks():
            duration = self._format_duration(data)
            item = QListWidgetItem(f"{data['title']} · {data['status']} · {duration}")
            item.setData(256, task_id)
            self.task_list.addItem(item)
            if current_task_id == task_id:
                self.task_list.setCurrentItem(item)
        if self.task_list.count() and not self.task_list.currentItem():
            self.task_list.setCurrentRow(0)
        elif self.task_list.count() == 0:
            self.details.setPlainText("No hay tareas registradas.")

    def _render_details(self, current, previous):
        if not current:
            self.details.setPlainText("No hay tarea seleccionada.")
            return
        task_id = current.data(256)
        task = self.registry.get_task(task_id)
        if not task:
            self.details.setPlainText("No hay datos disponibles.")
            return
        self.details.setPlainText(
            "\n".join(
                [
                    f"ID: {task_id}",
                    f"Título: {task['title']}",
                    f"Estado: {task['status']}",
                    f"Inicio: {task['started_at']:%Y-%m-%d %H:%M:%S}",
                    f"Fin: {task['ended_at']:%Y-%m-%d %H:%M:%S}" if task["ended_at"] else "Fin: —",
                    f"Duración: {self._format_duration(task)}",
                    "",
                    f"Último mensaje:\n{task['last_message'] or 'Sin mensajes aún.'}",
                ]
            )
        )

    def _format_duration(self, task_data: dict) -> str:
        end = task_data.get("ended_at") or datetime.now()
        seconds = int((end - task_data["started_at"]).total_seconds())
        minutes, seconds = divmod(seconds, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def cancel_selected_task(self):
        item = self.task_list.currentItem()
        if not item:
            return
        task_id = item.data(256)
        self.registry.cancel_task(task_id)
