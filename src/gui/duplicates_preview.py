#!/usr/bin/env python3
"""Vista previa, panel de detalle y menú contextual de la tabla de duplicados."""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtWidgets import QDialog, QLabel, QMenu, QMessageBox, QPushButton, QScrollArea, QVBoxLayout

from src.gui.v2.theme import apply_menu_surface

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".ico"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"}


def format_file_size(size_bytes) -> str:
    size_bytes = int(size_bytes or 0)
    if size_bytes < 1024:
        return f"{size_bytes} bytes"
    if size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    return f"{size_bytes / (1024 ** 3):.1f} GB"


def open_with_system(path: Path, reveal: bool = False) -> None:
    if sys.platform == "win32":
        if reveal:
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)] if reveal else ["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path.parent if reveal else path)])


class DuplicatesPreviewMixin:
    """Mixin para ``DuplicatesDashboard``."""

    def setup_context_menu(self):
        self.duplicates_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.duplicates_table.customContextMenuRequested.connect(self.show_context_menu)

    def format_file_size(self, size_bytes):
        return format_file_size(size_bytes)

    def show_context_menu(self, position):
        index = self.duplicates_table.indexAt(position)
        if not index.isValid():
            return
        row_data = self.duplicates_model.get_row_data(index.row())
        if not row_data or not row_data.get("path"):
            return
        file_path = Path(row_data["path"])
        menu = QMenu(self)
        apply_menu_surface(menu)
        ext = file_path.suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            action = QAction("Previsualizar imagen", self)
            action.triggered.connect(lambda: self.preview_image(file_path))
            menu.addAction(action)
        if ext in VIDEO_EXTENSIONS:
            action = QAction("Reproducir vídeo", self)
            action.triggered.connect(lambda: self.play_video(file_path))
            menu.addAction(action)
        open_action = QAction("Abrir archivo", self)
        open_action.triggered.connect(lambda: self.open_file(file_path))
        menu.addAction(open_action)
        folder_action = QAction("Abrir ubicación", self)
        folder_action.triggered.connect(lambda: self.open_file_location(file_path))
        menu.addAction(folder_action)
        menu.addSeparator()
        keep_action = QAction("Conservar esta copia", self)
        keep_action.triggered.connect(self.mark_selected_as_preferred_original)
        menu.addAction(keep_action)
        ignore_action = QAction("Ignorar grupo", self)
        ignore_action.triggered.connect(self.ignore_selected_group)
        menu.addAction(ignore_action)
        menu.exec(self.duplicates_table.viewport().mapToGlobal(position))

    def preview_image(self, file_path):
        if not file_path.exists():
            QMessageBox.warning(self, "Error", f"El archivo no existe:\n{file_path}")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Previsualización: {file_path.name}")
        dialog.setModal(True)
        dialog.resize(800, 600)
        layout = QVBoxLayout(dialog)
        try:
            size_text = self.format_file_size(file_path.stat().st_size)
        except OSError:
            size_text = "?"
        layout.addWidget(QLabel(f"{file_path.parent}\n{file_path.name}\n{size_text}"))
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(file_path))
        if pixmap.isNull():
            image_label.setText("No se pudo cargar la imagen")
        else:
            if pixmap.width() > 700 or pixmap.height() > 700:
                pixmap = pixmap.scaled(700, 700, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            image_label.setPixmap(pixmap)
        scroll_area.setWidget(image_label)
        layout.addWidget(scroll_area)
        close_btn = QPushButton("Cerrar")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        dialog.exec()

    def _open_path(self, file_path, reveal=False, label="archivo"):
        if not reveal and not file_path.exists():
            QMessageBox.warning(self, "Error", f"El archivo no existe:\n{file_path}")
            return
        try:
            open_with_system(file_path, reveal=reveal)
        except OSError as e:
            QMessageBox.warning(self, "Error", f"No se pudo abrir el {label}:\n{e}")

    def play_video(self, file_path):
        self._open_path(file_path, label="vídeo")

    def open_file(self, file_path):
        self._open_path(file_path)

    def open_file_location(self, file_path):
        self._open_path(file_path, reveal=True, label="ubicación")

    def update_preview_panel_from_index(self, index):
        if not index.isValid():
            return
        row_data = self.duplicates_model.get_row_data(index.row())
        if not row_data:
            return
        status = "Se conserva" if row_data.get("is_original") else "Copia"
        date = row_data.get("date")
        self.preview_panel.setPlainText("\n".join([
            f"Nombre: {row_data.get('name', 'N/A')}",
            f"Estado: {status}",
            f"Comparación: {row_data.get('match_status', 'Candidato sin confirmar')}",
            f"Ruta: {row_data.get('path', 'N/A')}",
            f"Hash de contenido: {row_data.get('hash') or 'sin calcular'}",
            f"Tamaño: {self.format_file_size(row_data.get('size', 0))}",
            f"Fecha: {datetime.fromtimestamp(date).strftime('%Y-%m-%d %H:%M') if date else 'N/A'}",
            "",
            "Acciones sugeridas:",
            "- «Conservar» fija esta copia como la que se mantiene en el grupo.",
            "- «Ignorar grupo» oculta un conjunto legítimo en futuros análisis.",
            "- Antes de retirar, cada copia se compara con la que se conserva.",
        ]))

    def toggle_preview_panel(self):
        if self.preview_panel.isVisible():
            self._last_preview_sizes = self.table_splitter.sizes()
            self.preview_visible = False
            self.preview_panel.hide()
            self.table_splitter.setSizes([1, 0])
        else:
            self.preview_visible = True
            self.preview_panel.show()
            self.table_splitter.setSizes(self._last_preview_sizes or [900, 260])
        self.settings.setValue("preview_visible", self.preview_visible)
        self.settings.sync()
        self.update_preview_button_state()

    def update_preview_button_state(self):
        if getattr(self, "preview_toggle_btn", None) is None:
            return
        self.preview_toggle_btn.setText("Ocultar panel" if self.preview_visible else "Mostrar panel")
