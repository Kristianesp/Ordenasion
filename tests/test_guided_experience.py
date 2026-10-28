"""Regresiones del flujo guiado. Todos los archivos usados son temporales."""

import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QDialog

from src.utils.app_config import AppConfig
from src.gui.v2.theme import current_tokens, contrast_ratio

APP = None


def application():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


def test_appearance_is_validated_and_saved_once(tmp_path, monkeypatch):
    config = AppConfig(str(tmp_path / "config.json"))
    writes = MagicMock(wraps=config.save_config)
    monkeypatch.setattr(config, "save_config", writes)
    assert not config.save_appearance("dark", "compact", 15, "red")
    writes.assert_not_called()
    assert config.save_appearance("dark", "compact", 15, "#FFFF00")
    writes.assert_called_once()
    saved = json.loads(config.config_file.read_text(encoding="utf-8"))
    assert saved["interface"]["accent_color"] == "#FFFF00"
    assert saved["interface"]["theme_mode"] == "dark"


def test_failed_replace_preserves_disk_and_memory(tmp_path, monkeypatch):
    import src.utils.app_config as module
    config = AppConfig(str(tmp_path / "config.json"))
    assert config.save_appearance("light", "comfortable", 13, "#0078D4")
    original = config.config_file.read_bytes()
    monkeypatch.setattr(module.os, "replace", MagicMock(side_effect=PermissionError("denied")))
    assert not config.save_appearance("dark", "compact", 15, "#123456")
    assert config.config_file.read_bytes() == original
    assert config.get_theme_mode() == "light"
    assert not list(tmp_path.glob("*.tmp"))
    assert not config.set("interface.font_size", 15)
    assert config.get_font_size() == 13


@pytest.mark.parametrize("accent", ["#FFFFFF", "#FFFF00", "#000000", "#0078D4"])
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_accent_text_and_selection_meet_contrast(accent, mode):
    application()
    tokens = current_tokens(accent, mode)
    assert contrast_ratio(tokens.accent, tokens.accent_foreground) >= 4.5
    assert contrast_ratio(tokens.accent_text, tokens.surface) >= 4.5


def test_settings_never_reports_success_after_failed_save(tmp_path, monkeypatch):
    from src.gui.v2.pages import settings_page as module
    application()
    config = AppConfig(str(tmp_path / "config.json"))
    page = module.SettingsPage(config)
    success = MagicMock()
    monkeypatch.setattr(module.InfoBar, "success", success)
    monkeypatch.setattr(module.InfoBar, "error", MagicMock())
    theme = MagicMock()
    monkeypatch.setattr(module, "apply_fluent_theme", theme)
    monkeypatch.setattr(config, "save_config", lambda *_: False)
    page.apply_appearance()
    success.assert_not_called()
    theme.assert_not_called()
    assert "No se pudo guardar" in page.validation_label.text()
    page.accent.setText("invalid")
    page.apply_appearance()
    assert "color válido" in page.validation_label.text()


@pytest.mark.parametrize("accepted", [False, True])
def test_review_confirms_selection_exactly_once(tmp_path, monkeypatch, accepted):
    from src.gui import main_window as module
    application()
    selected = [{"file": tmp_path / "selected.txt", "category": "TEXTOS"}]
    preview = MagicMock()
    preview.exec.return_value = QDialog.DialogCode.Accepted if accepted else QDialog.DialogCode.Rejected
    preview.get_conflict_policy.return_value = "skip"
    preview_factory = MagicMock(return_value=preview)
    monkeypatch.setattr(module, "PreviewDialog", preview_factory)
    worker = MagicMock()
    worker_factory = MagicMock(return_value=worker)
    monkeypatch.setattr(module, "OrganizeWorker", worker_factory)
    monkeypatch.setattr(module.task_registry, "start_task", MagicMock())
    facade = SimpleNamespace(
        _get_effective_selected_movements=lambda: ([], selected),
        folder_input=SimpleNamespace(text=lambda: str(tmp_path)),
        organize_by_date_checkbox=SimpleNamespace(isChecked=lambda: False),
        check_duplicates_checkbox=SimpleNamespace(isChecked=lambda: False),
        app_config=AppConfig(str(tmp_path / "config.json")),
        current_organize_task_id=None, _active_workers=[],
        current_analysis_task_id=None,
        _analysis_result_path=os.path.normcase(os.path.realpath(tmp_path)),
        organize_btn=MagicMock(), rollback_btn=MagicMock(), operation_state_changed=MagicMock(),
        log_message=MagicMock(), _handle_task_progress=MagicMock(),
        on_organize_complete=MagicMock(), on_rollback_available=MagicMock(),
        on_operation_summary_ready=MagicMock(), _cleanup_worker=MagicMock(),
    )
    module.FileOrganizerGUI.start_organization(facade)
    if accepted:
        module.FileOrganizerGUI.start_organization(facade)
        preview_factory.assert_called_once()
        worker_factory.assert_called_once()
        assert worker_factory.call_args.args[2] == selected
        assert worker_factory.call_args.kwargs["conflict_policy"] == "skip"
        worker.start.assert_called_once()
    else:
        worker_factory.assert_not_called()
        assert facade.current_organize_task_id is None


def test_preview_accounts_for_conflicts_between_selected_files(tmp_path):
    from src.gui.preview_dialog import PreviewDialog
    application()
    movements = []
    for folder in ("first", "second"):
        source = tmp_path / folder / "same.txt"
        source.parent.mkdir()
        source.write_text(folder, encoding="utf-8")
        movements.append({"file": source, "category": "TEXTOS"})
    dialog = PreviewDialog([], movements, str(tmp_path), check_duplicates=False)
    assert dialog.preview_rows[0]["destination_path"].endswith("same.txt")
    assert dialog.preview_rows[1]["destination_path"].endswith("same (1).txt")
    dialog.conflict_policy_combo.setCurrentIndex(2)
    assert "Omitidos por conflicto: 1" in dialog.summary_label.text()


def test_changed_folder_cannot_review_old_selection(tmp_path, monkeypatch):
    from src.gui import main_window as module
    application()
    other = tmp_path / "other"
    other.mkdir()
    warning = MagicMock()
    monkeypatch.setattr(module.QMessageBox, "warning", warning)
    preview_factory = MagicMock()
    monkeypatch.setattr(module, "PreviewDialog", preview_factory)
    facade = SimpleNamespace(
        current_organize_task_id=None, current_analysis_task_id=None,
        folder_input=SimpleNamespace(text=lambda: str(other)),
        _analysis_result_path=os.path.normcase(os.path.realpath(tmp_path)),
    )
    module.FileOrganizerGUI.start_organization(facade)
    preview_factory.assert_not_called()
    warning.assert_called_once()
    facade.current_analysis_task_id = "running"
    facade._analysis_result_path = os.path.normcase(os.path.realpath(other))
    module.FileOrganizerGUI.start_organization(facade)
    preview_factory.assert_not_called()


def test_home_validates_path_and_undo_state(tmp_path):
    from src.gui.v2.pages.home_page import HomePage
    application()
    page = HomePage(AppConfig(str(tmp_path / "config.json")),
                    SimpleNamespace(get_profile_names=lambda: []))
    received = []
    page.analyze_requested.connect(received.append)
    page._analyze()
    assert received == [] and page.path_error.text()
    page.path_input.setText(str(tmp_path))
    page._analyze()
    assert received == [str(tmp_path)] and not page.path_error.text()
    controller = SimpleNamespace(last_operation_summary={"files_moved": 2},
                                 current_organize_task_id=None, last_transaction_id="tx")
    page.update_operation(controller)
    assert page.undo_button.isEnabled()
    assert "2 archivos movidos" in page.last_operation_label.text()
    controller.current_organize_task_id = "active"
    page.update_operation(controller)
    assert not page.undo_button.isEnabled()


def test_quarantine_retains_content_and_records_actual_destination(tmp_path):
    from src.core.transaction_manager import TransactionManager
    manager = TransactionManager(str(tmp_path / "operations.json"))
    source = tmp_path / "copy.txt"
    source.write_text("temporary content", encoding="utf-8")
    assert manager.safe_delete_file(source, use_trash=False)
    destination = manager.operations[-1]["details"]["destination"]
    assert manager.last_removal_destination == destination
    assert not source.exists()
    from pathlib import Path
    assert Path(destination).read_text(encoding="utf-8") == "temporary content"


def test_cancellation_is_only_requested_until_worker_finishes():
    from src.gui.task_center import BackgroundTaskRegistry
    registry = BackgroundTaskRegistry()
    cancel = MagicMock()
    registry.start_task("one", "Temporary analysis", cancel)
    registry.cancel_task("one")
    registry.cancel_task("one")
    cancel.assert_called_once()
    assert registry.get_task("one")["status"] == "Cancelación solicitada"
    assert registry.get_task("one")["ended_at"] is None
    registry.finish_task("one", "Cancelada")
    assert registry.get_task("one")["ended_at"] is not None


def test_selected_file_organization_conflict_and_undo_restore_bytes(tmp_path, monkeypatch):
    from src.core.transaction_manager import TransactionManager
    from src.core.workers import OrganizeWorker
    application()
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "selected.txt"
    source.write_bytes(b"selected content")
    untouched = tmp_path / "unselected.txt"
    untouched.write_bytes(b"not selected")
    existing = tmp_path / "TEXTOS" / "selected.txt"
    existing.parent.mkdir()
    existing.write_bytes(b"existing destination")
    worker = OrganizeWorker(str(tmp_path), [], [{"file": source, "category": "TEXTOS", "size": source.stat().st_size}],
                            check_duplicates=False, conflict_policy="rename")
    worker.transaction_manager = TransactionManager(str(tmp_path / "operations.json"))
    worker.run()
    renamed = existing.parent / "selected (1).txt"
    assert renamed.read_bytes() == b"selected content"
    assert not source.exists()
    assert untouched.read_bytes() == b"not selected"
    assert existing.read_bytes() == b"existing destination"
    assert worker.summary["files_moved"] == 1
    assert worker.transaction_manager.rollback_transaction(worker.current_transaction_id)
    assert source.read_bytes() == b"selected content"
    assert not renamed.exists()
    assert existing.read_bytes() == b"existing destination"
    assert untouched.read_bytes() == b"not selected"


def test_dialogs_inherit_controller_dark_theme(tmp_path):
    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QWidget
    from src.gui.preview_dialog import PreviewDialog
    from src.gui.operation_summary_dialog import OperationSummaryDialog
    application()
    parent = QWidget()
    parent.app_config = AppConfig(str(tmp_path / "config.json"))
    assert parent.app_config.save_appearance("dark", "comfortable", 13, "#FFFF00")
    for dialog in (PreviewDialog([], [], str(tmp_path), parent),
                   OperationSummaryDialog({"files_moved": 1}, parent)):
        assert dialog.palette().color(QPalette.ColorRole.Window).name() == "#101827"
        assert dialog.palette().color(QPalette.ColorRole.WindowText).name() == "#f5f9ff"
        assert dialog.palette().color(QPalette.ColorRole.HighlightedText).name() == "#000000"


def test_summary_editor_renders_dark_surface_and_readable_text(tmp_path):
    from PyQt6.QtGui import QPalette
    from PyQt6.QtWidgets import QMainWindow, QTextEdit
    from PyQt6.QtTest import QTest
    from src.gui.operation_summary_dialog import OperationSummaryDialog
    from src.gui.v2.theme import apply_fluent_theme, fluent_window_stylesheet
    app = application()
    parent = QMainWindow()
    parent.setObjectName("fluentAppWindow")
    parent.app_config = AppConfig(str(tmp_path / "config.json"))
    assert parent.app_config.save_appearance("dark", "comfortable", 13, "#0078D4")
    apply_fluent_theme(parent.app_config)
    parent.setStyleSheet(fluent_window_stylesheet(parent.app_config))
    dialog = OperationSummaryDialog({"files_moved": 2}, parent)
    dialog.show()
    app.processEvents()
    QTest.qWait(650)
    editor = dialog.findChild(QTextEdit)
    viewport = editor.viewport()
    rendered = viewport.grab().toImage()
    assert rendered.pixelColor(rendered.width() - 8, rendered.height() - 8).name() == "#182337"
    assert contrast_ratio(viewport.palette().color(QPalette.ColorRole.Text).name(),
                          viewport.palette().color(QPalette.ColorRole.Base).name()) >= 4.5
    bright_text_pixels = sum(
        rendered.pixelColor(x, y).lightness() > 200
        for y in range(min(180, rendered.height())) for x in range(rendered.width())
    )
    assert bright_text_pixels > 100
    dialog.close()
