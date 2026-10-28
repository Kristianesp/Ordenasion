#!/usr/bin/env python3
"""
Panel visual para gestionar reglas personalizadas de categorización.

Controles Fluent y tokens V2: la lista de reglas, su detalle y un único
formulario (nombre, patrón, categoría y prioridad) para crear o editar.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    LineEdit,
    ListWidget,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SpinBox,
    SubtitleLabel,
    TitleLabel,
)
from PyQt6.QtWidgets import QListWidgetItem

from src.core.category_manager import CategoryManager, CategoryRule
from src.gui.v2.components import ask


class RuleFormDialog(MessageBoxBase):
    """Formulario Fluent de una regla: nombre, patrón, categoría y prioridad."""

    def __init__(self, categories, existing: CategoryRule | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("ruleFormDialog")
        self.viewLayout.addWidget(SubtitleLabel("Editar regla" if existing else "Nueva regla"))
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.name_input = LineEdit()
        self.name_input.setAccessibleName("Nombre de la regla")
        self.name_input.setText(existing.name if existing else "")
        form.addRow(BodyLabel("Nombre"), self.name_input)
        self.pattern_input = LineEdit()
        self.pattern_input.setAccessibleName("Patrón de la regla")
        self.pattern_input.setPlaceholderText("Texto o regex: usa 'regex:' para patrones regulares")
        self.pattern_input.setText(existing.pattern if existing else "")
        form.addRow(BodyLabel("Patrón"), self.pattern_input)
        self.category_combo = ComboBox()
        self.category_combo.setAccessibleName("Categoría destino")
        self.category_combo.addItems(list(categories))
        if existing and existing.category in categories:
            self.category_combo.setCurrentText(existing.category)
        form.addRow(BodyLabel("Categoría"), self.category_combo)
        self.priority_spin = SpinBox()
        self.priority_spin.setAccessibleName("Prioridad")
        self.priority_spin.setRange(0, 100)
        self.priority_spin.setValue(existing.priority if existing else 50)
        form.addRow(BodyLabel("Prioridad"), self.priority_spin)
        self.viewLayout.addLayout(form)
        hint = CaptionLabel("Más prioridad = se aplica antes que la categorización por extensión.")
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)
        self.yesButton.setText("Guardar")
        self.cancelButton.setText("Cancelar")
        self.widget.setMinimumWidth(460)

    def validate(self) -> bool:
        return bool(self.name_input.text().strip() and self.pattern_input.text().strip()
                    and self.category_combo.currentText())

    def values(self) -> dict:
        return {
            "name": self.name_input.text().strip(),
            "pattern": self.pattern_input.text().strip(),
            "category": self.category_combo.currentText(),
            "priority": self.priority_spin.value(),
        }


class RulePanel(QDialog):
    """Diálogo CRUD sencillo para reglas personalizadas."""

    def __init__(self, parent=None, category_manager: CategoryManager | None = None):
        super().__init__(parent)
        self.category_manager = category_manager or CategoryManager()
        self.setObjectName("rulePanelDialog")
        self.setWindowTitle("Reglas personalizadas")
        self.setMinimumSize(700, 480)
        self._build_ui()
        self.refresh_rules()
        from src.gui.v2.theme import apply_dialog_surface

        apply_dialog_surface(self)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(TitleLabel("Reglas personalizadas"))
        info = BodyLabel(
            "Define reglas por nombre o regex. Se aplican antes de la categorización por extensión."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        content = QHBoxLayout()
        content.setSpacing(16)
        layout.addLayout(content, 1)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(SubtitleLabel("Reglas configuradas"))
        self.rules_list = ListWidget()
        self.rules_list.setAccessibleName("Reglas configuradas")
        self.rules_list.currentItemChanged.connect(self._on_rule_selected)
        left.addWidget(self.rules_list, 1)
        content.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(SubtitleLabel("Detalle"))
        detail = QWidget()
        detail.setObjectName("ruleDetail")
        self.detail_layout = QFormLayout(detail)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setHorizontalSpacing(12)
        self.detail_layout.setVerticalSpacing(8)
        self.detail_name = BodyLabel("—")
        self.detail_pattern = BodyLabel("—")
        self.detail_category = BodyLabel("—")
        self.detail_priority = BodyLabel("—")
        self.detail_status = BodyLabel("—")
        self.detail_pattern.setWordWrap(True)
        for label, widget in [
            ("Nombre", self.detail_name),
            ("Patrón", self.detail_pattern),
            ("Categoría", self.detail_category),
            ("Prioridad", self.detail_priority),
            ("Estado", self.detail_status),
        ]:
            self.detail_layout.addRow(CaptionLabel(label), widget)
        right.addWidget(detail)
        right.addStretch()
        content.addLayout(right, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.add_btn = PushButton(FluentIcon.ADD, "Añadir")
        self.edit_btn = PushButton(FluentIcon.EDIT, "Editar")
        self.toggle_btn = PushButton(FluentIcon.PAUSE, "Activar/Desactivar")
        self.delete_btn = PushButton(FluentIcon.DELETE, "Eliminar")
        self.close_btn = PrimaryPushButton("Cerrar")
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
            status = "Activa" if rule.enabled else "En pausa"
            item = QListWidgetItem(f"{rule.name} → {rule.category} · prioridad {rule.priority} · {status}")
            item.setData(Qt.ItemDataRole.UserRole, rule.name)
            self.rules_list.addItem(item)
        has_rules = self.rules_list.count() > 0
        for button in (self.edit_btn, self.toggle_btn, self.delete_btn):
            button.setEnabled(has_rules)
        if has_rules:
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
        """Formulario único; None si se cancela."""
        categories = sorted(self.category_manager.get_categories().keys())
        dialog = RuleFormDialog(categories, existing, self)
        if not dialog.exec():
            return None
        return dialog.values()

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
        if ask(self, "Eliminar regla", f"¿Eliminar la regla '{rule.name}'?", "Eliminar", "Cancelar"):
            self.category_manager.remove_custom_rule(rule.name)
            self.refresh_rules()
