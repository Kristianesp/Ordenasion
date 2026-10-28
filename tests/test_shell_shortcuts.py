"""Atajos del shell, tema Sistema y cableado de cierre/resultados de la V2."""

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.utils.app_config import AppConfig


@pytest.fixture(scope="module")
def shell(tmp_path_factory):
    from src.gui.main_window import FileOrganizerGUI
    from src.gui.v2.app_window import FluentAppWindow

    app = QApplication.instance() or QApplication([])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(FileOrganizerGUI, "_init_disk_manager", lambda self: None)
        config = AppConfig(str(tmp_path_factory.mktemp("shortcuts") / "config.json"))
        config.set_theme_mode("light")
        legacy = FileOrganizerGUI(app_config_ref=config, fluent_mode=True)
        window = FluentAppWindow(legacy)
        window.resize(1280, 720)
        window.show()
        window.activateWindow()
        QTest.qWaitForWindowActive(window, 1000)
        app.processEvents()
        yield window
        window._cleanup_theme_transition()
        window.hide()
        app.processEvents()


def _press(window, key, modifier=Qt.KeyboardModifier.NoModifier):
    window.activateWindow()
    QTest.keyClick(window, key, modifier)
    QApplication.processEvents()


def test_legacy_shortcuts_are_registered_on_the_shell(shell):
    sequences = {sequence for sequence, _ in shell.shortcut_table()}
    for expected in ("Ctrl+O", "F5", "Ctrl+R", "Ctrl+S", "Ctrl+F", "Ctrl+L", "Ctrl+P", "Ctrl+Q", "F1", "Ctrl+1"):
        assert expected in sequences
    assert {"Ctrl+A", "Ctrl+D"} <= set(shell._shortcuts)


def test_f5_navigates_to_organize_and_starts_analysis(shell, monkeypatch):
    start = MagicMock()
    monkeypatch.setattr(shell.legacy_window, "start_analysis", start)
    shell._switch_route("home")
    _press(shell, Qt.Key.Key_F5)
    start.assert_called_once()
    assert shell.stackedWidget.currentWidget() is shell._routes["organize"]


def test_ctrl_shortcuts_trigger_legacy_actions(shell, monkeypatch):
    browse, organize = MagicMock(), MagicMock()
    monkeypatch.setattr(shell.legacy_window, "browse_folder", browse)
    monkeypatch.setattr(shell.legacy_window, "start_organization", organize)
    _press(shell, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    _press(shell, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    browse.assert_called_once()
    organize.assert_called_once()
    _press(shell, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
    assert shell.stackedWidget.currentWidget() is shell._routes["disks"]


def test_ctrl_f_focuses_organize_search(shell):
    shell._switch_route("organize")
    QApplication.processEvents()
    _press(shell, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert shell.legacy_window.filter_bar.search_input.hasFocus()


def test_f1_shows_shortcuts_help(shell, monkeypatch):
    from src.gui.v2 import components

    shown = []
    monkeypatch.setattr(components.ShortcutsDialog, "exec", lambda self: shown.append(self.rows) or 0)
    _press(shell, Qt.Key.Key_F1)
    assert shown and ("F1", "Mostrar esta ayuda") in shown[0]


def test_system_theme_selectable_and_follows_os(shell, monkeypatch):
    settings = shell._routes["settings"]
    assert [settings.theme_selector.itemData(i) for i in range(settings.theme_selector.count())] == ["light", "dark", "system"]
    settings.theme_selector.setCurrentIndex(settings.theme_selector.findData("system"))
    assert shell.config.get_theme_mode() == "system"
    shell._cleanup_theme_transition()
    refresh = MagicMock()
    monkeypatch.setattr(shell, "_refresh_theme", refresh)
    shell._on_system_color_scheme_changed(Qt.ColorScheme.Dark)
    refresh.assert_called_once()
    shell.config.set_theme_mode("light")
    shell._on_system_color_scheme_changed(Qt.ColorScheme.Dark)
    refresh.assert_called_once()


def test_theme_menu_offers_three_modes(shell):
    menu = shell._show_theme_menu()
    assert [action.text() for action in menu.actions()] == ["Claro", "Oscuro", "Sistema"]
    menu.actions()[1].trigger()
    assert shell.config.get_theme_mode() == "dark"
    shell._cleanup_theme_transition()
    shell.set_theme_mode("light")
    shell._cleanup_theme_transition()


def test_tool_settings_are_saved(shell, monkeypatch):
    from src.gui.v2.pages import settings_page as module

    monkeypatch.setattr(module.InfoBar, "success", MagicMock())
    page = shell._routes["settings"]
    page.keep_rule.setCurrentIndex(page.keep_rule.findData("oldest"))
    page.dup_method.setCurrentIndex(page.dup_method.findData("deep"))
    page.preferred_folders.addItem("C:/Fotos")
    page.verify_bytes.setChecked(True)
    page.similar_threshold.setValue(7)
    page.duration_tolerance.setValue(3.5)
    page.local_chromaprint.setChecked(False)
    page.smart_ttl.setValue(300)
    page.smart_history.setChecked(False)
    page.size_on_disk.setChecked(False)
    page.dedupe_hardlinks.setChecked(False)
    assert page.save_tool_settings()
    reloaded = AppConfig(str(shell.config.config_file))
    assert reloaded.get("duplicates.keep_rule") == "oldest"
    assert reloaded.get("duplicates.default_method") == "deep"
    assert reloaded.get("duplicates.preferred_folders") == ["C:/Fotos"]
    assert reloaded.get("duplicates.verify_bytes_before_delete") is True
    assert reloaded.get("duplicates.similar_images_threshold") == 7
    assert reloaded.get("audio.duplicate_duration_tolerance") == 3.5
    assert reloaded.get("audio.local_chromaprint") is False
    assert reloaded.get("disks.smart_cache_ttl") == 300
    assert reloaded.get("disks.smart_history") is False
    assert reloaded.get("space_usage.size_on_disk") is False
    assert reloaded.get("space_usage.dedupe_hardlinks") is False


def test_last_result_offers_undo(shell, monkeypatch):
    from src.gui import operation_summary_dialog as module

    captured = {}

    def fake_init(self, summary, parent=None, undo_callback=None):
        captured["undo"] = undo_callback
        QApplication.instance()  # sin interfaz real

    monkeypatch.setattr(module.OperationSummaryDialog, "__init__", fake_init)
    monkeypatch.setattr(module.OperationSummaryDialog, "exec", lambda self: 0)
    rollback = MagicMock(return_value=True)
    monkeypatch.setattr(shell.legacy_window, "rollback_transaction", rollback)
    monkeypatch.setattr(shell.legacy_window, "last_operation_summary",
                        {"transaction_id": "txn-1", "files_moved": 2, "folders_moved": 0})
    shell._show_last_result()
    captured["undo"]()
    rollback.assert_called_once_with("txn-1", confirm=False)


def test_space_organize_request_starts_analysis(shell, monkeypatch):
    start = MagicMock()
    monkeypatch.setattr(shell.legacy_window, "start_analysis", start)
    shell.page("disks").space_page.organize_requested.emit("/tmp")
    start.assert_called_once()
    assert shell.legacy_window.folder_input.text() == "/tmp"


def test_close_asks_legacy_shutdown_first(shell, monkeypatch):
    monkeypatch.setattr(shell.legacy_window, "request_shutdown", lambda confirm=True: False)
    shutdown = MagicMock()
    monkeypatch.setattr(shell.legacy_window.disk_viewer, "shutdown", shutdown)
    shell.close()
    assert shell.isVisible()
    shutdown.assert_not_called()


def test_heavy_pages_are_built_on_first_navigation(tmp_path):
    from src.gui.main_window import FileOrganizerGUI
    from src.gui.v2.app_window import FluentAppWindow, LazyPage

    app = QApplication.instance()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(FileOrganizerGUI, "_init_disk_manager", lambda self: None)
        config = AppConfig(str(tmp_path / "config.json"))
        legacy = FileOrganizerGUI(app_config_ref=config, fluent_mode=True)
        assert legacy.main_tabs is None
        assert legacy.disk_viewer is None and legacy.music_duplicates_view is None
        assert legacy.duplicates_dashboard is None
        window = FluentAppWindow(legacy)
        window.resize(1280, 720)
        window.show()
        app.processEvents()
        for route in ("disks", "music", "duplicates"):
            assert isinstance(window._routes[route], LazyPage)
            assert window.built_page(route) is None
        # Navegación por clic: el marcador primero y la página en la siguiente vuelta
        window.switchTo(window._routes["music"])
        assert window.built_page("music") is None
        QTest.qWait(50)
        assert window.built_page("music") is not None
        assert legacy.music_duplicates_view is not None
        # Navegación programática: construcción inmediata
        window._switch_route("space")
        assert window.built_page("disks").space_page.isVisible()
        assert legacy.disk_viewer is not None
        assert window.built_page("duplicates") is None
        window.close()
        app.processEvents()
