#!/usr/bin/env python3
"""
Resumen post-organización.
"""

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QTextEdit, QVBoxLayout
from qfluentwidgets import PrimaryPushButton, PushButton, TitleLabel
from src.gui.v2.theme import apply_dialog_surface

# Texto del estado tal y como lo deja OrganizeWorker en summary["status"]
STATUS_TEXT = {
    "completado": "Completada",
    "completado con errores": "Completada con errores",
    "cancelado": "Cancelada (se detuvo antes de terminar)",
    "error": "Error: se intentaron revertir los cambios",
}


def summary_status_text(summary: dict) -> str:
    """Estado legible de un resumen de organización."""
    if summary.get("undone"):
        return "Deshecha"
    status = summary.get("status")
    if status in STATUS_TEXT:
        return STATUS_TEXT[status]
    return "Resultado de la ejecución"


class OperationSummaryDialog(QDialog):
    """Muestra un resumen claro de la última organización.

    Si se pasa ``undo_callback`` y hay cambios que deshacer, se ofrece un
    botón para revertirlos (por ejemplo, tras cancelar a medias).
    """

    def __init__(self, summary: dict, parent=None, undo_callback=None):
        super().__init__(parent)
        self.summary = summary or {}
        self.undo_callback = undo_callback
        self.undo_requested = False
        self.setWindowTitle("Resumen de organización")
        self.setObjectName("operationSummaryDialog")
        self.resize(540, 420)
        self._build_ui()
        apply_dialog_surface(self)

    def summary_lines(self) -> list:
        summary = self.summary
        lines = [
            f"Estado: {summary_status_text(summary)}",
            f"Carpetas movidas: {summary.get('folders_moved', 0)}",
            f"Archivos movidos: {summary.get('files_moved', 0)}",
        ]
        if summary.get("failed"):
            lines.append(f"Elementos con error: {summary.get('failed', 0)}")
        if summary.get("pending"):
            lines.append(f"Sin procesar (cancelado): {summary.get('pending', 0)}")
        lines += [
            f"Espacio reorganizado: {self._format_size(summary.get('bytes_reorganized', 0))}",
            f"Duplicados omitidos: {summary.get('skipped_duplicates', 0)}",
        ]
        if summary.get("skipped_conflicts"):
            lines.append(f"Omitidos por conflicto: {summary.get('skipped_conflicts', 0)}")
        if summary.get("skipped_invalid"):
            lines.append(f"Omitidos (protegidos o no válidos): {summary.get('skipped_invalid', 0)}")
        lines += [
            f"Duración: {summary.get('duration_seconds', 0):.1f}s",
            f"Carpetas creadas: {', '.join(summary.get('created_folders', [])) or 'Ninguna'}",
            "",
            "Avisos:",
            *(summary.get("warnings", []) or ["- Sin avisos"]),
            "",
            "Errores:",
            *(summary.get("errors", []) or ["- Sin errores"]),
        ]
        return lines

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(TitleLabel("Resultado de la última ejecución"))

        content = QTextEdit()
        content.setReadOnly(True)
        content.setPlainText("\n".join(self.summary_lines()))
        layout.addWidget(content, 1)

        buttons = QHBoxLayout()
        moved = self.summary.get("files_moved", 0) + self.summary.get("folders_moved", 0)
        self.undo_btn = None
        if self.undo_callback is not None and moved and not self.summary.get("undone"):
            self.undo_btn = PushButton("Deshacer estos cambios")
            self.undo_btn.setAccessibleName("Deshacer los cambios de esta organización")
            self.undo_btn.clicked.connect(self._request_undo)
            buttons.addWidget(self.undo_btn)
        buttons.addStretch()
        close_btn = PrimaryPushButton("Cerrar")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _request_undo(self):
        self.undo_requested = True
        self.accept()
        if self.undo_callback is not None:
            self.undo_callback()

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes >= 1024**3:
            return f"{size_bytes / (1024**3):.2f} GB"
        if size_bytes >= 1024**2:
            return f"{size_bytes / (1024**2):.2f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.2f} KB"
        return f"{size_bytes} B"
