"""Página Organizar durante la migración a Fluent."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget
from qfluentwidgets import PushButton, TransparentPushButton

from src.gui.v2.pages.legacy_page import LegacyPage
from src.gui.v2.theme import apply_control_size
from src.utils.app_config import AppConfig


class OrganizePage(LegacyPage):
    """Mantiene el flujo actual de análisis y organización."""
    activity_requested = pyqtSignal()

    def __init__(
        self,
        legacy_widget: QWidget,
        config: AppConfig,
        controller=None,
        parent=None,
    ):
        super().__init__(
            "Organizar",
            "Analiza, revisa y organiza tus archivos con control antes de moverlos.",
            legacy_widget,
            config,
            parent,
        )
        self.config = config
        if controller is not None:
            self._move_legacy_actions_to_header(controller)

    def _move_legacy_actions_to_header(self, controller) -> None:
        """Coloca las acciones globales en la cabecera, fuera del flujo de trabajo."""
        legacy_config_button = getattr(controller, "config_btn", None)
        legacy_tasks_button = getattr(controller, "task_center_btn", None)
        if legacy_config_button is not None:
            legacy_config_button.hide()
        if legacy_tasks_button is not None:
            legacy_tasks_button.hide()

        config_button = TransparentPushButton()
        config_button.setText("Configurar")
        config_button.setObjectName("organizeConfigAction")
        config_button.setAccessibleName("Abrir configuración")
        config_button.setMinimumWidth(96)
        apply_control_size(config_button, self.config)
        config_button.clicked.connect(controller.open_configuration)

        tasks_button = PushButton()
        tasks_button.setText("Tareas")
        tasks_button.setObjectName("organizeTasksAction")
        tasks_button.setAccessibleName("Abrir tareas")
        tasks_button.setMinimumWidth(82)
        apply_control_size(tasks_button, self.config)
        tasks_button.clicked.connect(self.activity_requested.emit)

        self.add_header_widget(config_button)
        self.add_header_widget(tasks_button)
