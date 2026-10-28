"""Diálogos abiertos desde Organizar: controles Fluent, tokens V2 y alturas del shell."""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget
from qfluentwidgets import PushButton

from src.utils.app_config import AppConfig

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def parent(tmp_path):
    widget = QWidget()
    widget.app_config = AppConfig(str(tmp_path / "config.json"))
    yield widget
    widget.close()


def _category_manager(tmp_path):
    from src.core.category_manager import CategoryManager

    return CategoryManager(str(tmp_path / "categories.json"))


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_dialog_buttons_match_shell_height_and_labels_do_not_paint(parent, tmp_path, mode):
    from src.gui.config_dialog import ConfigDialog
    from src.gui.operation_summary_dialog import OperationSummaryDialog
    from src.gui.preview_dialog import PreviewDialog
    from src.gui.rule_panel import RulePanel
    from src.gui.task_center import TaskCenterDialog
    from src.gui.v2.theme import typography_scale

    parent.app_config.set_theme_mode(mode)
    height = typography_scale(parent.app_config).control_height
    manager = _category_manager(tmp_path)
    for dialog in (PreviewDialog([], [], str(tmp_path), parent),
                   OperationSummaryDialog({"files_moved": 1}, parent, undo_callback=lambda: None),
                   TaskCenterDialog(parent), RulePanel(parent, manager),
                   ConfigDialog(parent, manager, app_config_ref=parent.app_config)):
        dialog.show()
        APP.processEvents()
        buttons = [button for button in dialog.findChildren(PushButton) if button.isVisible()]
        assert buttons, type(dialog).__name__
        assert {button.height() for button in buttons} == {height}, type(dialog).__name__
        # Solo el diálogo rellena su fondo: sin franjas detrás de etiquetas
        painted = [child for child in dialog.findChildren(QWidget)
                   if child.autoFillBackground() and child.objectName() != "qt_scrollarea_viewport"]
        assert painted == [], (type(dialog).__name__, [type(child).__name__ for child in painted])
        dialog.close()


def test_config_dialog_uses_tabs_and_fluent_confirmations(parent, tmp_path, monkeypatch):
    from src.gui import config_dialog as module

    manager = _category_manager(tmp_path)
    dialog = module.ConfigDialog(parent, manager, app_config_ref=parent.app_config, focus_section="exclusions")
    tabs = dialog.findChild(QTabWidget)
    assert [tabs.tabText(index) for index in range(tabs.count())] == ["General", "Catálogo", "Exclusiones"]
    assert dialog.save_btn.text() == "Guardar y cerrar" and dialog.cancel_btn.text() == "Cancelar"
    # Crear una categoría pide el nombre con el diálogo Fluent y avisa sin bloquear
    monkeypatch.setattr(module.TextPromptDialog, "get_text", classmethod(lambda cls, *a, **k: ("viajes", True)))
    info = MagicMock()
    monkeypatch.setattr(dialog, "_info", info)
    dialog.add_category()
    assert "VIAJES" in manager.get_categories()
    info.assert_called_once()
    # Eliminarla pide confirmación (Fluent): si se rechaza, sigue ahí
    item = next(dialog.categories_list.item(i) for i in range(dialog.categories_list.count())
                if dialog.categories_list.item(i).text() == "VIAJES")
    dialog.categories_list.setCurrentItem(item)
    monkeypatch.setattr(module, "ask", MagicMock(return_value=False))
    dialog.remove_category()
    assert "VIAJES" in manager.get_categories()
    monkeypatch.setattr(module, "ask", MagicMock(return_value=True))
    dialog.remove_category()
    assert "VIAJES" not in manager.get_categories()
    dialog.close()


def test_rule_panel_single_form_creates_and_edits_rules(parent, tmp_path, monkeypatch):
    from src.gui import rule_panel as module

    manager = _category_manager(tmp_path)
    panel = module.RulePanel(parent, manager)
    assert not panel.edit_btn.isEnabled() and not panel.delete_btn.isEnabled()
    form = module.RuleFormDialog(sorted(manager.get_categories()), None, panel)
    assert not form.validate()
    form.name_input.setText("Facturas")
    form.pattern_input.setText("factura")
    form.category_combo.setCurrentText("DOCUMENTOS")
    form.priority_spin.setValue(80)
    assert form.validate()
    values = form.values()
    assert values == {"name": "Facturas", "pattern": "factura", "category": "DOCUMENTOS", "priority": 80}
    monkeypatch.setattr(panel, "_prompt_rule_data", lambda existing=None: values)
    panel.add_rule()
    assert [rule.name for rule in manager.get_custom_rules()] == ["Facturas"]
    assert panel.rules_list.count() == 1 and panel.edit_btn.isEnabled()
    assert panel.detail_priority.text() == "80"
    monkeypatch.setattr(module, "ask", MagicMock(return_value=True))
    panel.delete_rule()
    assert manager.get_custom_rules() == []
    panel.close()


def test_task_center_cancels_only_cancellable_tasks(parent):
    from src.gui.task_center import BackgroundTaskRegistry, TaskCenterDialog

    registry = BackgroundTaskRegistry()
    cancel = MagicMock()
    registry.start_task("a", "Análisis", cancel)
    registry.start_task("b", "Deshacer", None)
    dialog = TaskCenterDialog(parent, registry)
    dialog.task_list.setCurrentRow(1)
    assert not dialog.cancel_btn.isEnabled()
    dialog.task_list.setCurrentRow(0)
    assert dialog.cancel_btn.isEnabled()
    dialog.cancel_selected_task()
    cancel.assert_called_once()
    dialog.close()


def test_preview_shows_paths_relative_to_source(parent, tmp_path):
    from PyQt6.QtCore import Qt
    from src.gui.preview_dialog import PreviewDialog

    source = tmp_path / "informe.pdf"
    source.write_bytes(b"pdf")
    dialog = PreviewDialog([], [{"file": source, "category": "DOCUMENTOS", "size": 3}], str(tmp_path), parent)
    model = dialog.preview_model
    shown = model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole)
    assert shown.replace("\\", "/") == "DOCUMENTOS/informe.pdf"
    assert model.data(model.index(0, 3), Qt.ItemDataRole.ToolTipRole) == dialog.preview_rows[0]["destination_path"]
    assert not dialog.conflict_box.isVisibleTo(dialog)
    assert not dialog.confirm_btn.isEnabled()
    dialog.confirm_checkbox.setChecked(True)
    assert dialog.confirm_btn.isEnabled()
    dialog.close()
