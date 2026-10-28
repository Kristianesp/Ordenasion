#!/usr/bin/env python3
"""
Resumen post-organización.
"""

from PyQt6.QtWidgets import QDialog, QTextEdit, QVBoxLayout
from qfluentwidgets import PrimaryPushButton, TitleLabel
from src.gui.v2.theme import apply_dialog_surface


class OperationSummaryDialog(QDialog):
    """Muestra un resumen claro de la última organización."""

    def __init__(self, summary: dict, parent=None):
        super().__init__(parent)
        self.summary = summary or {}
        self.setWindowTitle("Resumen de organización")
        self.setObjectName("operationSummaryDialog")
        self.resize(540, 420)
        self._build_ui()
        apply_dialog_surface(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(TitleLabel("Resultado de la última ejecución"))

        content = QTextEdit()
        content.setReadOnly(True)
        content.setPlainText(
            "\n".join(
                [
                    f"Carpetas movidas: {self.summary.get('folders_moved', 0)}",
                    "Estado: deshecha" if self.summary.get("undone") else "Estado: resultado de la ejecución",
                    f"Archivos movidos: {self.summary.get('files_moved', 0)}",
                    f"Espacio reorganizado: {self._format_size(self.summary.get('bytes_reorganized', 0))}",
                    f"Duplicados omitidos: {self.summary.get('skipped_duplicates', 0)}",
                    f"Duración: {self.summary.get('duration_seconds', 0):.1f}s",
                    f"Carpetas creadas: {', '.join(self.summary.get('created_folders', [])) or 'Ninguna'}",
                    "",
                    "Avisos:",
                    *(self.summary.get("warnings", []) or ["- Sin avisos"]),
                    "",
                    "Errores:",
                    *(self.summary.get("errors", []) or ["- Sin errores"]),
                ]
            )
        )
        layout.addWidget(content, 1)

        close_btn = PrimaryPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes >= 1024**3:
            return f"{size_bytes / (1024**3):.2f} GB"
        if size_bytes >= 1024**2:
            return f"{size_bytes / (1024**2):.2f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.2f} KB"
        return f"{size_bytes} B"
