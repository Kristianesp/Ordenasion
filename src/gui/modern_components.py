#!/usr/bin/env python3
"""Componentes heredados que aún usan las herramientas embebidas.

Solo queda ``TabHeaderWidget`` (cabecera de Duplicados en la ventana
autónoma; la V2 la oculta y usa su propia cabecera de página). Los botones,
campos y tarjetas "Modern*" se retiraron: la interfaz usa qfluentwidgets y
los componentes de ``src.gui.v2.components``.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from ..utils.constants import UI_CONFIG


class TabHeaderWidget(QWidget):
    config_requested = pyqtSignal()
    tasks_requested = pyqtSignal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("tab_header_title")
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        layout.addWidget(self.title_label, 1)

        self.config_btn = QPushButton("Configurar")
        self.config_btn.setObjectName("tab_header_config_btn")
        self.config_btn.setFixedHeight(UI_CONFIG["BUTTON_HEIGHT"])
        self.config_btn.setMinimumWidth(80)
        self.config_btn.clicked.connect(self.config_requested.emit)
        layout.addWidget(self.config_btn)

        self.tasks_btn = QPushButton("Tareas")
        self.tasks_btn.setObjectName("tab_header_tasks_btn")
        self.tasks_btn.setFixedHeight(UI_CONFIG["BUTTON_HEIGHT"])
        self.tasks_btn.setMinimumWidth(80)
        self.tasks_btn.clicked.connect(self.tasks_requested.emit)
        layout.addWidget(self.tasks_btn)
