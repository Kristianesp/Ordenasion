#!/usr/bin/env python3
"""
Panel visual para gestionar reglas personalizadas de categorización.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.core.category_manager import CategoryManager, CategoryRule


class RulePanel(QDialog):
    """Diálogo CRUD sencillo para reglas personalizadas."""

    def __init__(self, parent=None, category_manager: CategoryManager | None = None):
        super().__init__(parent)
        self.category_manager = category_manager or CategoryManager()
        self.setWindowTitle("Reglas personalizadas")
        self.setMinimumSize(680, 480)
        self._build_ui()
        self.refresh_rules()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        info = QLabel(
            "Define reglas por nombre o regex. Se aplican antes de la categorización por extensión."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        content = QHBoxLayout()
        layout.addLayout(content, 1)

        left_box = QGroupBox("Reglas configuradas")
        left_layout = QVBoxLayout(left_box)
        self.rules_list = QListWidget()
        self.rules_list.currentItemChanged.connect(self._on_rule_selected)
        left_layout.addWidget(self.rules_list)
        content.addWidget(left_box, 1)

        right_box = QGroupBox("Detalle")
        self.detail_layout = QFormLayout(right_box)
        self.detail_name = QLabel("—")
        self.detail_pattern = QLabel("—")
        self.detail_category = QLabel("—")
        self.detail_priority = QLabel("—")
        self.detail_status = QLabel("—")
        self.detail_pattern.setWordWrap(True)
        for label, widget in [
            ("Nombre", self.detail_name),
            ("Patrón", self.detail_pattern),
            ("Categoría", self.detail_category),
            ("Prioridad", self.detail_priority),
            ("Estado", self.detail_status),
        ]:
            self.detail_layout.addRow(label + ":", widget)
        content.addWidget(right_box, 1)

        buttons = QHBoxLayout()
        self.add_btn = QPushButton("Añadir")
        self.edit_btn = QPushButton("Editar")
        self.toggle_btn = QPushButton("Activar/Desactivar")
        self.delete_btn = QPushButton("Eliminar")
        self.close_btn = QPushButton("Cerrar")
        self.add_btn.clicked.connect(self.add_rule)
        self.edit_btn.clicked.connect(self.edit_rule)
        self.toggle_btn.clicked.connect(self.toggle_rule)
        self.delete_btn.clicked.connect(self.delete_rule)
        self.close_btn.clicked.connect(self.accept)
        for btn in [self.add_btn, self.edit_btn, self.toggle_btn, self.delete_btn]:
            buttons.addWidget(btn)
        buttons.addStretch()
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    def refresh_rules(self):
        self.rules_list.clear()
        for rule in sorted(
            self.category_manager.get_custom_rules(),
            key=lambda item: item.priority,
            reverse=True,
        ):
            status = "✅" if rule.enabled else "⏸️"
            item = QListWidgetItem(f"{status} {rule.name} → {rule.category} ({rule.priority})")
            item.setData(Qt.ItemDataRole.UserRole, rule.name)
            self.rules_list.addItem(item)
        if self.rules_list.count():
            self.rules_list.setCurrentRow(0)
        else:
            self._set_rule_details(None)

    def _get_selected_rule(self) -> CategoryRule | None:
        item = self.rules_list.currentItem()
        if not item:
            return None
        rule_name = item.data(Qt.ItemDataRole.UserRole)
        for rule in self.category_manager.get_custom_rules():
            if rule.name == rule_name:
                return rule
        return None

    def _set_rule_details(self, rule: CategoryRule | None):
        self.detail_name.setText(rule.name if rule else "—")
        self.detail_pattern.setText(rule.pattern if rule else "—")
        self.detail_category.setText(rule.category if rule else "—")
        self.detail_priority.setText(str(rule.priority) if rule else "—")
        self.detail_status.setText("Activa" if rule and rule.enabled else "Inactiva" if rule else "—")

    def _on_rule_selected(self, current, previous):
        self._set_rule_details(self._get_selected_rule())

    def _prompt_rule_data(self, existing: CategoryRule | None = None):
        name, ok = QInputDialog.getText(
            self,
            "Nombre de la regla",
            "Nombre:",
            text=existing.name if existing else "",
        )
        if not ok or not name.strip():
            return None

        pattern, ok = QInputDialog.getText(
            self,
            "Patrón",
            "Texto o regex: usa 'regex:' para patrones regulares",
            text=existing.pattern if existing else "",
        )
        if not ok or not pattern.strip():
            return None

        categories = sorted(self.category_manager.get_categories().keys())
        current_index = 0
        if existing and existing.category in categories:
            current_index = categories.index(existing.category)
        category, ok = QInputDialog.getItem(
            self,
            "Categoría destino",
            "Categoría:",
            categories,
            current=current_index,
            editable=False,
        )
        if not ok or not category:
            return None

        priority_dialog = QDialog(self)
        priority_dialog.setWindowTitle("Prioridad")
        priority_layout = QVBoxLayout(priority_dialog)
        priority_layout.addWidget(QLabel("Prioridad (más alto = se aplica antes):"))
        priority_spin = QSpinBox()
        priority_spin.setRange(0, 100)
        priority_spin.setValue(existing.priority if existing else 50)
        priority_layout.addWidget(priority_spin)
        button_row = QHBoxLayout()
        save_btn = QPushButton("Guardar")
        cancel_btn = QPushButton("Cancelar")
        save_btn.clicked.connect(priority_dialog.accept)
        cancel_btn.clicked.connect(priority_dialog.reject)
        button_row.addWidget(save_btn)
        button_row.addWidget(cancel_btn)
        priority_layout.addLayout(button_row)
        if priority_dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        return {
            "name": name.strip(),
            "pattern": pattern.strip(),
            "category": category,
            "priority": priority_spin.value(),
        }

    def add_rule(self):
        data = self._prompt_rule_data()
        if not data:
            return
        self.category_manager.add_custom_rule(**data)
        self.refresh_rules()

    def edit_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            return
        data = self._prompt_rule_data(rule)
        if not data:
            return
        self.category_manager.update_custom_rule(rule.name, **data)
        self.refresh_rules()

    def toggle_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            return
        self.category_manager.toggle_custom_rule(rule.name)
        self.refresh_rules()

    def delete_rule(self):
        rule = self._get_selected_rule()
        if not rule:
            return
        reply = QMessageBox.question(
            self,
            "Eliminar regla",
            f"¿Eliminar la regla '{rule.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.category_manager.remove_custom_rule(rule.name)
            self.refresh_rules()
