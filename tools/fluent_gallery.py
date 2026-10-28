#!/usr/bin/env python3
"""Galería local de componentes Fluent para validar el sistema visual."""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    ScrollArea,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
    TitleLabel,
    setTheme,
    Theme,
)

from src.gui.v2.components import FeatureCard, MetricCard, PageHeader
from src.gui.v2.theme import preferred_font_family


class GalleryPage(ScrollArea):
    """Muestra los componentes que formarán la V2."""

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setObjectName("fluentGallery")
        self.enableTransparentBackground()
        content = QWidget()
        self.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 32)
        layout.setSpacing(18)
        layout.addWidget(
            PageHeader(
                "Galería Fluent",
                "Referencia visual de controles, tarjetas y estados de Ordenasion 2.0.",
                "Acción principal",
                FluentIcon.PLAY,
            )
        )

        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.addWidget(SubtitleLabel("Controles"))
        controls = QHBoxLayout()
        controls.addWidget(PrimaryPushButton(FluentIcon.SEARCH, "Analizar"))
        controls.addWidget(PushButton(FluentIcon.FOLDER, "Examinar"))
        text_input = LineEdit()
        text_input.setText("Texto de ejemplo")
        controls.addWidget(text_input)
        combo = ComboBox()
        combo.addItems(["Sistema", "Claro", "Oscuro"])
        controls.addWidget(combo)
        controls.addWidget(SpinBox())
        controls.addWidget(CheckBox("Recordar"))
        switch = SwitchButton()
        switch.setText("Activo")
        controls.addWidget(switch)
        card_layout.addLayout(controls)
        progress = ProgressBar()
        progress.setValue(62)
        card_layout.addWidget(progress)
        layout.addWidget(card)

        layout.addWidget(SubtitleLabel("Tarjetas de producto"))
        cards = QHBoxLayout()
        cards.addWidget(
            MetricCard(
                FluentIcon.COMPLETED,
                "Protección",
                "Vista previa",
                "Ningún archivo se mueve sin confirmación.",
            )
        )
        cards.addWidget(
            MetricCard(
                FluentIcon.SYNC,
                "Actividad",
                "2 tareas",
                "Los procesos pesados no bloquean la UI.",
            )
        )
        layout.addLayout(cards)
        layout.addWidget(
            FeatureCard(
                FluentIcon.FOLDER,
                "Organización segura",
                "Una tarjeta de acción con icono, descripción y foco claro.",
                "Abrir flujo",
            )
        )
        layout.addWidget(BodyLabel("Esta galería es una herramienta de validación local."))
        layout.addStretch()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--dpi", type=int, choices=(100, 125, 150), default=100)
    args = parser.parse_args()

    os.environ["QT_SCALE_FACTOR"] = str(args.dpi / 100)
    app = QApplication(sys.argv)
    app.setFont(QFont(preferred_font_family(), 10))
    setTheme(Theme.DARK if args.theme == "dark" else Theme.LIGHT)
    window = GalleryPage()
    window.resize(args.width, args.height)
    window.show()

    if args.screenshot:
        QTimer.singleShot(
            250,
            lambda: (
                args.screenshot.parent.mkdir(parents=True, exist_ok=True),
                window.grab().save(str(args.screenshot)),
                app.quit(),
            ),
        )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
