"""Tema global y ajustes compactos, sin servicios ni archivos reales."""

import json
from unittest.mock import MagicMock

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme

from src.utils.app_config import AppConfig


@pytest.fixture(scope="module")
def shell_window(tmp_path_factory):
    from src.gui.main_window import FileOrganizerGUI
    from src.gui.v2.app_window import FluentAppWindow

    app = QApplication.instance() or QApplication([])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(FileOrganizerGUI, "_init_disk_manager", lambda self: None)
        patch.setattr(FileOrganizerGUI, "_refresh_disk_viewer_after_theme", lambda *_: None)
        config = AppConfig(str(tmp_path_factory.mktemp("theme-config") / "config.json"))
        config.set_theme_mode("light")
        legacy = FileOrganizerGUI(app_config_ref=config)
        window = FluentAppWindow(legacy)
        window.resize(1280, 800)
        window.show()
        app.processEvents()
        yield window
        if window.isVisible():
            window.close()
        app.processEvents()


@pytest.fixture
def shell(shell_window):
    window = shell_window
    window._cleanup_theme_transition()
    window.config.set_theme_mode("light")
    window._refresh_theme()
    window.resize(1280, 800)
    window.show()
    window._switch_route("home")
    QApplication.processEvents()
    yield window
    window._cleanup_theme_transition()


def test_toggle_persists_once_and_captures_old_theme_before_save(shell, monkeypatch):
    saves = MagicMock(wraps=shell.config.set_theme_mode)
    monkeypatch.setattr(shell.config, "set_theme_mode", saves)
    original_grab = shell.stackedWidget.grab
    snapshot_modes = []

    def capture():
        snapshot_modes.append(shell.config.get_theme_mode())
        return original_grab()

    monkeypatch.setattr(shell.stackedWidget, "grab", capture)
    page = shell._routes["home"]
    page.path_input.setText("Selección de carpeta conservada")
    scrollbar = page.verticalScrollBar()
    scrollbar.setValue(min(80, scrollbar.maximum()))
    position = scrollbar.value()
    assert shell._toggle_theme()
    assert not shell._toggle_theme()
    saves.assert_called_once_with("dark")
    assert snapshot_modes == ["light"]
    assert shell._theme_transition_active
    assert not shell.theme_button.isEnabled()
    assert shell._theme_animation.duration() == 280
    assert shell.stackedWidget.currentWidget() is page
    assert page.path_input.text() == "Selección de carpeta conservada"
    assert scrollbar.value() == position
    saved = json.loads(shell.config.config_file.read_text(encoding="utf-8"))
    assert saved["interface"]["theme_mode"] == "dark"
    QTest.qWait(400)
    assert shell.theme_button.isEnabled()
    assert not shell._theme_transition_active
    assert shell._theme_overlay is None and shell._theme_animation is None
    from src.gui.v2.theme import current_tokens
    dark_color = current_tokens(shell.config.get_accent_color(), "dark").text_primary
    assert dark_color in page.disk_metric.value_label.styleSheet()
    assert shell._toggle_theme()
    QTest.qWait(400)
    light_color = current_tokens(shell.config.get_accent_color(), "light").text_primary
    assert light_color in page.disk_metric.value_label.styleSheet()
    assert dark_color not in page.disk_metric.value_label.styleSheet()


def test_failed_theme_save_keeps_theme_and_does_not_animate(shell, monkeypatch):
    from src.gui.v2 import app_window as module

    monkeypatch.setattr(shell.config, "set_theme_mode", lambda _: False)
    error = MagicMock()
    refresh = MagicMock()
    monkeypatch.setattr(module.InfoBar, "error", error)
    monkeypatch.setattr(shell, "_refresh_theme", refresh)
    assert not shell._toggle_theme()
    error.assert_called_once()
    refresh.assert_not_called()
    assert shell.config.get_theme_mode() == "light"
    assert shell.theme_button.isEnabled()
    assert not shell._theme_transition_active
    assert shell._theme_overlay is None and shell._theme_animation is None


def test_theme_button_is_excluded_from_windows_drag_region(shell):
    button = shell.theme_button
    assert not shell.titleBar.canDrag(button.mapTo(shell.titleBar, button.rect().center()))
    assert shell.titleBar.canDrag(shell.titleBar.titleLabel.pos())
    assert button.width() >= 36 and button.height() >= 36


@pytest.mark.parametrize("effective,expected", [(Theme.DARK, "light"), (Theme.LIGHT, "dark")])
def test_system_mode_toggle_uses_effective_theme(shell, effective, expected):
    shell.config.set_theme_mode("system")
    setTheme(effective)
    assert shell._toggle_theme()
    assert shell.config.get_theme_mode() == expected


@pytest.mark.parametrize("action", ["resize", "close"])
def test_transition_cleans_up_when_window_changes(shell, action):
    assert shell._toggle_theme()
    if action == "resize":
        shell.resize(1180, 750)
    else:
        shell.close()
    QApplication.processEvents()
    assert shell._theme_overlay is None and shell._theme_animation is None
    assert not shell._theme_transition_active
    assert shell.theme_button.isEnabled()


def test_settings_saves_current_global_mode_and_adapts_columns(shell, monkeypatch):
    from src.gui.v2.pages import settings_page as module

    page = shell._routes["settings"]
    shell._switch_route("settings")
    QApplication.processEvents()
    assert not hasattr(page, "theme_mode")
    shell.config.set_theme_mode("dark")
    monkeypatch.setattr(module.InfoBar, "success", MagicMock())
    page.accent.setText("#123456")
    page.apply_appearance()
    assert shell.config.get_theme_mode() == "dark"
    assert shell.config.get_accent_color() == "#123456"
    assert page.settings_panel.maximumWidth() == 1120
    responsive = module.SettingsPage(shell.config)
    responsive.resize(760, 700)
    responsive.show()
    QApplication.processEvents()
    assert responsive.appearance_grid.getItemPosition(responsive.appearance_grid.indexOf(responsive.color_card))[:2] == (1, 0)
    responsive.resize(1280, 800)
    QApplication.processEvents()
    assert responsive.appearance_grid.getItemPosition(responsive.appearance_grid.indexOf(responsive.color_card))[:2] == (0, 1)
    responsive.close()


def test_legacy_font_apply_refreshes_fluent_without_rewriting_theme(shell, monkeypatch):
    from src.gui import config_dialog as module

    shell.config.set_theme_mode("dark")
    shell._refresh_theme()
    refresh = MagicMock(wraps=shell._refresh_theme)
    monkeypatch.setattr(shell.legacy_window, "refresh_fluent_appearance", refresh)
    monkeypatch.setattr(module.QMessageBox, "exec", lambda self: 0)
    dialog = module.ConfigDialog(shell.legacy_window, shell.legacy_window.category_manager,
                                 app_config_ref=shell.config)
    legacy_apply = MagicMock()
    dialog.interface_changes_requested.connect(legacy_apply)
    set_theme = MagicMock(wraps=shell.config.set_theme)
    monkeypatch.setattr(shell.config, "set_theme", set_theme)
    dialog.font_size_combo.setCurrentIndex(2)
    dialog.apply_interface_changes()
    refresh.assert_called_once()
    legacy_apply.assert_not_called()
    set_theme.assert_not_called()
    assert shell.config.get_font_size() == 15
    assert shell.config.get_theme_mode() == "dark"
    assert "Tema oscuro" in shell.theme_button.accessibleName()
    dialog.close()
