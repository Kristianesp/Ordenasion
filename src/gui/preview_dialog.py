#!/usr/bin/env python3
"""
Dialogo de Preview para el Organizador de Archivos
Muestra una vista previa de los cambios antes de organizar
"""

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QGroupBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from qfluentwidgets import CheckBox, ComboBox, PrimaryPushButton, PushButton

from src.utils.app_config import AppConfig
from src.gui.v2.theme import apply_dialog_surface, current_tokens
from src.core.organization_conflicts import (
    CONFLICT_POLICY_OVERWRITE,
    CONFLICT_POLICY_RENAME,
    CONFLICT_POLICY_SKIP,
    build_base_destination,
    resolve_destination,
)


class PreviewDialog(QDialog):
    """Dialogo que muestra vista previa de cambios antes de organizar"""

    def __init__(
        self,
        folder_movements,
        file_movements,
        folder_path,
        parent=None,
        organize_by_date=False,
        check_duplicates=False,
        conflict_policy=CONFLICT_POLICY_RENAME,
    ):
        super().__init__(parent)
        self.folder_movements = folder_movements
        self.file_movements = file_movements
        self.folder_path = folder_path
        self.organize_by_date = organize_by_date
        self.check_duplicates = check_duplicates
        self.conflict_policy = conflict_policy
        self._setup_ui()
    
    def _setup_ui(self):
        self.setWindowTitle("Revisar y organizar")
        self.resize(900, 600)
        self.setMinimumSize(640, 440)
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Header informativo
        header = QLabel("Vista Previa de Cambios")
        header.setObjectName("preview_header")
        layout.addWidget(header)
        
        # Resumen
        total_folders = len(self.folder_movements)
        total_files = len(self.file_movements)
        total_items = total_folders + total_files

        self.preview_rows = []
        self.conflict_count = 0
        categories = {}
        for mov in self.folder_movements:
            categories[mov["category"]] = categories.get(mov["category"], 0) + 1
        for mov in self.file_movements:
            categories[mov["category"]] = categories.get(mov["category"], 0) + 1

        summary = QLabel(
            f"Se organizarán {total_items} elementos · {total_folders} carpetas · {total_files} archivos\n"
            f"Destino(s): {len(categories)} · Conflictos detectados: 0\n"
            f"Carpeta origen: {self.folder_path or 'No especificada'}"
        )
        self.summary_label = summary
        summary.setObjectName("preview_summary")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        # Resolución de conflictos
        self.conflict_box = QGroupBox("Resolución de conflictos")
        conflict_layout = QHBoxLayout(self.conflict_box)
        conflict_layout.setContentsMargins(12, 12, 12, 12)
        conflict_layout.addWidget(QLabel("Si el destino ya existe:"))
        self.conflict_policy_combo = ComboBox()
        for label, policy in (
            ("Mantener ambos (renombrar)", CONFLICT_POLICY_RENAME),
            ("Sobrescribir archivo existente", CONFLICT_POLICY_OVERWRITE),
            ("Omitir elementos en conflicto", CONFLICT_POLICY_SKIP),
        ):
            self.conflict_policy_combo.addItem(label)
            self.conflict_policy_combo.setItemData(
                self.conflict_policy_combo.count() - 1,
                policy,
            )
        index = self.conflict_policy_combo.findData(self.conflict_policy)
        self.conflict_policy_combo.setCurrentIndex(index if index >= 0 else 0)
        self.conflict_policy_combo.currentIndexChanged.connect(
            lambda *_args: self._refresh_preview()
        )
        conflict_layout.addWidget(self.conflict_policy_combo, 1)
        layout.addWidget(self.conflict_box)
        
        # Tabla de preview
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(5)
        self.preview_table.setHorizontalHeaderLabels(["Tipo", "Nombre", "Destino", "Ruta final", "Estado"])
        self.preview_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.preview_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Llenar tabla
        self._refresh_preview()
        layout.addWidget(self.preview_table)
        
        # Checkbox de confirmacion
        self.confirm_checkbox = CheckBox(
            "Confirmo que quiero proceder con la organizacion"
        )
        layout.addWidget(self.confirm_checkbox)
        
        # Botones
        btn_layout = QHBoxLayout()
        
        self.cancel_btn = PushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        
        btn_layout.addStretch()
        
        self.confirm_btn = PrimaryPushButton("Confirmar y organizar")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.confirm_btn)
        
        layout.addLayout(btn_layout)
        
        # Conectar checkbox
        self.confirm_checkbox.stateChanged.connect(self._on_confirm_changed)
        self._apply_theme()

    def get_conflict_policy(self):
        return self.conflict_policy_combo.currentData()
    
    def _populate_preview(self):
        """Llena la tabla con la vista previa"""
        self.preview_table.setRowCount(0)
        for row_index, row_data in enumerate(self.preview_rows):
            self.preview_table.insertRow(row_index)
            self.preview_table.setItem(row_index, 0, QTableWidgetItem(row_data["type"]))
            self.preview_table.setItem(row_index, 1, QTableWidgetItem(row_data["name"]))
            self.preview_table.setItem(row_index, 2, QTableWidgetItem(row_data["destination_label"]))
            self.preview_table.setItem(row_index, 3, QTableWidgetItem(row_data["destination_path"]))
            status_item = QTableWidgetItem(row_data["status"])
            if row_data["status"] != "Sin conflicto":
                status_item.setForeground(QColor(current_tokens().warning))
            self.preview_table.setItem(row_index, 4, status_item)

    def _refresh_summary(self):
        total_items = len(self.folder_movements) + len(self.file_movements)
        conflict_count = sum(1 for row in self.preview_rows if row["status"] != "Sin conflicto")
        skipped = sum(row["status"] == "Se omitirá por conflicto" for row in self.preview_rows)
        self.summary_label.setText(
            f"Selección: {total_items} elementos · {len(self.folder_movements)} carpetas · {len(self.file_movements)} archivos\n"
            f"Previstos para mover: {total_items - skipped} · Omitidos por conflicto: {skipped}\n"
            f"Destino(s): {len({row['destination_label'] for row in self.preview_rows})} · Conflictos detectados: {conflict_count}\n"
            f"Carpeta origen: {self.folder_path or 'No especificada'}\n"
            + ("Se comprobarán duplicados durante la operación y se omitirán las copias detectadas."
               if self.check_duplicates else "La detección de duplicados está desactivada.")
        )

    def _refresh_preview(self, *_args):
        self.conflict_policy = self.get_conflict_policy()
        self.preview_rows = self._build_preview_rows()
        has_conflicts = any(row["status"] != "Sin conflicto" for row in self.preview_rows)
        self.conflict_box.setVisible(has_conflicts)
        self._populate_preview()
        self._refresh_summary()
    
    def _format_size(self, size_bytes):
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def _on_confirm_changed(self, state):
        self.confirm_btn.setEnabled(int(state) == int(Qt.CheckState.Checked.value))

    def _build_preview_rows(self):
        rows = []
        reserved = set()
        for mov in self.folder_movements:
            base_destination = build_base_destination(
                self.folder_path,
                mov["category"],
                mov["folder"].name,
                organize_by_date=False,
            )
            resolved = resolve_destination(
                base_destination,
                conflict_policy=self.conflict_policy,
                is_folder=True,
                reserved=reserved,
            )
            reserved.add(resolved.destination)
            rows.append(
                {
                    "type": "Carpeta",
                    "name": f"{mov['folder'].name} ({self._format_size(mov.get('size', 0))})",
                    "destination_label": mov["category"],
                    "destination_path": str(resolved.destination),
                    "status": resolved.status,
                }
            )
        for mov in self.file_movements:
            base_destination = build_base_destination(
                self.folder_path,
                mov["category"],
                mov["file"].name,
                organize_by_date=self.organize_by_date,
                modified_at=mov["file"].stat().st_mtime,
            )
            resolved = resolve_destination(
                base_destination,
                conflict_policy=self.conflict_policy,
                is_folder=False,
                reserved=reserved,
            )
            if resolved.action != "skip":
                reserved.add(resolved.destination)
            rows.append(
                {
                    "type": "Archivo",
                    "name": f"{mov['file'].name} ({self._format_size(mov.get('size', 0))})",
                    "destination_label": mov["category"],
                    "destination_path": str(resolved.destination),
                    "status": resolved.status,
                }
            )
        return rows

    def _apply_theme(self):
        self.setObjectName("fluentPreviewDialog")
        tokens = apply_dialog_surface(self)
        for row, data in enumerate(self.preview_rows):
            if data["status"] != "Sin conflicto":
                self.preview_table.item(row, 4).setForeground(QColor(tokens.warning))
