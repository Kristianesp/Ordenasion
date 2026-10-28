"""Arranque bajo Qt offscreen, sin servicios ni configuración real."""

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontMetrics, QImage, QPalette
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QWidget
import main_fluent
from src.gui.v2 import startup_splash as module


APP = None


@pytest.fixture
def app():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


def test_entrypoint_import_is_lightweight_and_read_only(tmp_path):
    repo = Path(main_fluent.__file__).resolve().parent
    script = f"import sys;sys.path.insert(0,{str(repo)!r});import main_fluent;assert 'src.gui.main_window' not in sys.modules;assert 'qfluentwidgets' not in sys.modules"
    completed = subprocess.run([sys.executable, "-B", "-c", script], cwd=tmp_path, capture_output=True, text=True,
                               env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("interface,expected", [({}, "system"), ({"theme_mode": "dark"}, "dark"),
    ({"theme_mode": "light"}, "light"), ({"theme_mode": "invalid", "theme": "Oscuro"}, "dark")])
def test_theme_read_is_consistent_and_does_not_write(tmp_path, interface, expected):
    path = tmp_path / "config.json"
    content = json.dumps({"interface": interface}).encode()
    path.write_bytes(content)
    assert module.startup_theme_mode(path) == expected
    assert path.read_bytes() == content
    absent = tmp_path / "absent.json"
    assert module.startup_theme_mode(absent) == "system" and not absent.exists()


def test_assets_have_alpha_and_valid_ico_and_bundled_text_glyphs(app):
    image = QImage(str(module.ICON_PATH))
    assert not image.isNull() and image.hasAlphaChannel()
    assert image.pixelColor(0, 0).alpha() == 0
    icon = QImage(str(module.ICON_PATH.with_suffix(".ico")))
    assert not icon.isNull() and icon.hasAlphaChannel()
    assert (icon.width(), icon.height()) == (256, 256)
    assert not QImage(str(module.BACKGROUND_PATH)).isNull()
    assert not module.branding_icon().isNull()
    font = QFont(module.startup_font_family())
    metrics = QFontMetrics(font)
    assert all(metrics.inFont(character) for character in "OrdenasionPreparando…")


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_saved_theme_palette_and_splash_render(app, mode):
    from src.gui.v2.theme import current_tokens
    module.apply_startup_palette(app, mode)
    tokens = current_tokens(mode=mode)
    assert app.palette().color(QPalette.ColorRole.Window).name() == tokens.canvas.lower()
    splash = module.FluentStartupSplash(mode)
    splash.show()
    app.processEvents()
    assert splash.theme_mode == mode
    assert splash.size().width() == 560 and splash.size().height() == 340
    assert not splash.grab().isNull()
    assert "%" not in splash.accessibleDescription()
    QTest.mouseClick(splash, Qt.MouseButton.LeftButton)
    assert splash.isVisible()  # no se puede ocultar antes de completar el arranque
    splash.close()


def test_first_paint_reveals_final_window_and_closes_splash(app):
    splash = module.FluentStartupSplash("dark")
    window = QWidget()
    window.resize(640, 400)
    finished = QSignalSpy(splash.finished)
    splash.show()
    splash.prepare_window(window)
    assert not finished and splash.isVisible()
    window.show()
    for _ in range(20):
        app.processEvents()
        if finished:
            break
    assert len(finished) == 1 and not splash.isVisible()
    assert window.isVisible() and window.windowOpacity() == 1
    assert splash._window is None and not splash._paint_pending
    window.close()


def test_early_window_close_also_cleans_up(app):
    splash = module.FluentStartupSplash("light")
    window = QWidget()
    splash.show()
    splash.prepare_window(window)
    window.close()
    app.processEvents()
    assert not splash.isVisible() and splash._window is None
    assert window.windowOpacity() == 1


def test_startup_shows_splash_before_factory_and_failure_closes_it(app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen = []
    original = module.FluentStartupSplash

    def splash_factory(mode):
        splash = original(mode)
        seen.append(splash)
        return splash

    def fail():
        assert seen[0].isVisible()
        raise RuntimeError("Error de arranque temporal")

    monkeypatch.setattr(main_fluent, "FluentStartupSplash", splash_factory)
    monkeypatch.setattr(main_fluent, "create_window", fail)
    error = MagicMock()
    monkeypatch.setattr(main_fluent.QMessageBox, "critical", error)
    assert main_fluent.start_window(app) is None
    error.assert_called_once()
    assert not seen[0].isVisible()
    assert not (tmp_path / "app_config.json").exists()


def test_successful_startup_uses_saved_theme_and_application_icon(app, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "app_config.json"
    path.write_text(json.dumps({"interface": {"theme_mode": "dark"}}), encoding="utf-8")
    content = path.read_bytes()
    window = QWidget()
    window.show_maximized_safe = window.show
    monkeypatch.setattr(main_fluent, "create_window", lambda: window)
    assert main_fluent.start_window(app) is window
    for _ in range(20):
        app.processEvents()
        if not window._startup_splash.isVisible():
            break
    assert window._startup_splash.theme_mode == "dark"
    assert not window.windowIcon().isNull() and not app.windowIcon().isNull()
    assert not window._startup_splash.isVisible()
    assert window.windowOpacity() == 1 and path.read_bytes() == content
    window.close()
