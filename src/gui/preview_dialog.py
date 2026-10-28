#!/usr/bin/env python3
"""
Dialogo de Preview para el Organizador de Archivos
Muestra una vista previa de los cambios antes de organizar

La vista previa calcula el ``OrganizationPlan`` que después ejecuta el
worker tal cual (``get_plan()``), de modo que ambos no pueden divergir.
"""

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableView,
    QHeaderView,
    QGroupBox,
)
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor
from qfluentwidgets import CheckBox, ComboBox, PrimaryPushButton, PushButton

from src.gui.v2.theme import apply_dialog_surface, current_tokens
from src.core.organization_conflicts import (
    CONFLICT_POLICY_OVERWRITE,
    CONFLICT_POLICY_RENAME,
    CONFLICT_POLICY_SKIP,
)
from src.core.organization_plan import (
    ACTION_OVERWRITE,
    ACTION_RENAME,
    ACTION_SKIP,
    STATUS_NO_CONFLICT,
    build_organization_plan,
)

PREVIEW_HEADERS = ["Tipo", "Nombre", "Destino", "Ruta final", "Estado"]
_ROW_KEYS = ("type", "name", "destination_label", "destination_path", "status")


class PreviewTableModel(QAbstractTableModel):
    """Modelo ligero: las filas se cargan de golpe (sin insertRow por fila)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows = []
        self._warning_color = QColor(current_tokens().warning)

    def set_rows(self, rows):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def set_warning_color(self, color):
        self._warning_color = QColor(color)
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 4),
                self.index(len(self._rows) - 1, 4),
                [Qt.ItemDataRole.ForegroundRole],
            )

    def warning_color(self) -> QColor:
        return QColor(self._warning_color)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(PREVIEW_HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return row[_ROW_KEYS[index.column()]]
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 4:
            if row["status"] != STATUS_NO_CONFLICT:
                return self._warning_color
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return PREVIEW_HEADERS[section]
        return None


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
        category_folder=None,
        category_folder_names=None,
    ):
        super().__init__(parent)
        self.folder_movements = folder_movements
        self.file_movements = file_movements
        self.folder_path = folder_path
        self.organize_by_date = organize_by_date
        self.check_duplicates = check_duplicates
        self.conflict_policy = conflict_policy
        self.category_folder = category_folder
        self.category_folder_names = category_folder_names
        self.plan = None
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
        self.preview_rows = []
        self.conflict_count = 0
        summary = QLabel("")
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

        # Tabla de preview (modelo: se rellena de una vez)
        self.preview_model = PreviewTableModel(self)
        self.preview_table = QTableView()
        self.preview_table.setModel(self.preview_model)
        self.preview_table.verticalHeader().setVisible(False)
        header_view = self.preview_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.preview_table.setColumnWidth(1, 240)
        self.preview_table.setColumnWidth(4, 220)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

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

    def get_plan(self):
        """Plan confirmado: el worker lo ejecuta tal cual."""
        return self.plan

    def _populate_preview(self):
        """Llena la tabla con la vista previa (un único reset del modelo)"""
        self.preview_model.set_rows(self.preview_rows)

    def _refresh_summary(self):
        total_items = len(self.folder_movements) + len(self.file_movements)
        self.conflict_count = sum(
            1 for row in self.preview_rows if row["status"] != STATUS_NO_CONFLICT
        )
        skipped = sum(row["status"] == "Se omitirá por conflicto" for row in self.preview_rows)
        invalid = self.plan.invalid_count if self.plan else 0
        lines = [
            f"Selección: {total_items} elementos · {len(self.folder_movements)} carpetas · {len(self.file_movements)} archivos",
            f"Previstos para mover: {total_items - skipped - invalid} · Omitidos por conflicto: {skipped}",
        ]
        if invalid:
            lines.append(
                f"No se moverán {invalid} elementos: carpetas de categoría, destinos dentro "
                "del propio elemento o elementos que ya no existen"
            )
        lines += [
            f"Destino(s): {len({row['destination_label'] for row in self.preview_rows})} · Conflictos detectados: {self.conflict_count}",
            f"Carpeta origen: {self.folder_path or 'No especificada'}",
            "Se comprobarán duplicados durante la operación y se omitirán las copias detectadas."
            if self.check_duplicates
            else "La detección de duplicados está desactivada.",
        ]
        self.summary_label.setText("\n".join(lines))

    def _refresh_preview(self, *_args):
        self.conflict_policy = self.get_conflict_policy()
        self.preview_rows = self._build_preview_rows()
        has_conflicts = any(
            item.action in (ACTION_RENAME, ACTION_OVERWRITE, ACTION_SKIP)
            for item in self.plan.items
        )
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
        """Calcula el plan (una vez por política) y lo convierte en filas.

        El plan lee cada carpeta de destino una sola vez y tolera archivos que
        desaparecen (se marcan como omitidos en lugar de romper el diálogo).
        """
        self.plan = build_organization_plan(
            self.folder_path,
            self.folder_movements,
            self.file_movements,
            conflict_policy=self.conflict_policy,
            organize_by_date=self.organize_by_date,
            check_duplicates=self.check_duplicates,
            category_folder=self.category_folder,
            category_folder_names=self.category_folder_names,
        )
        return [
            {
                "type": "Carpeta" if item.is_folder else "Archivo",
                "name": f"{item.source.name} ({self._format_size(item.size)})",
                "destination_label": item.category,
                "destination_path": str(item.destination),
                "status": item.status,
            }
            for item in self.plan.items
        ]

    def _apply_theme(self):
        self.setObjectName("fluentPreviewDialog")
        tokens = apply_dialog_surface(self)
        self.preview_model.set_warning_color(tokens.warning)
