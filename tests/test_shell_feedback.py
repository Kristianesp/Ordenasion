"""Avisos de tareas, arrastrar y soltar carpetas y última página visitada."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import QApplication

from src.gui.task_center import BackgroundTaskRegistry
from src.utils.app_config import AppConfig

# La QApplication debe sobrevivir entre tests (qconfig de qfluentwidgets).
APP = QApplication.instance() or QApplication([])


def _build(config):
    from src.gui.v2.app_window import FluentAppWindow

    window = FluentAppWindow(config)
    window.resize(1280, 720)
    window.show()
    QApplication.processEvents()
    return window


@pytest.fixture
def shell(tmp_path):
    from src.gui.v2.app_window import FluentAppWindow

    app = APP
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(FluentAppWindow, "_init_disk_manager", lambda self: None)
        window = _build(AppConfig(str(tmp_path / "config.json")))
        yield window
        window.close()
        app.processEvents()


def _drop(widget, folder):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(folder))])
    # Qt solo entrega el Drop al widget que aceptó el DragEnter
    enter = QDragEnterEvent(QPointF(10, 10).toPoint(), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, enter)
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)
    return event


def test_badge_counts_active_tasks_and_infobar_on_finish(shell, monkeypatch):
    from src.gui.v2 import task_feedback as module

    registry = BackgroundTaskRegistry()
    feedback = module.TaskFeedback(shell, registry)
    registry.start_task("a", "Análisis de organización")
    registry.start_task("b", "Duplicados")
    assert feedback.badge is not None and feedback.badge.text() == "2"
    assert not feedback.badge.isHidden()
    success = MagicMock()
    monkeypatch.setattr(module.InfoBar, "success", success)
    error = MagicMock()
    monkeypatch.setattr(module.InfoBar, "error", error)
    monkeypatch.setattr(shell, "isActiveWindow", lambda: True)
    registry._tasks["a"]["started_at"] = datetime.now() - timedelta(seconds=5)
    registry.finish_task("a", "Completada")
    success.assert_called_once()
    assert feedback.badge.text() == "1"
    registry.finish_task("b", "Error")
    error.assert_called_once()
    assert feedback.badge.isHidden()


def test_long_task_in_background_notifies_from_tray(shell, monkeypatch):
    from src.gui.v2 import task_feedback as module

    registry = BackgroundTaskRegistry()
    feedback = module.TaskFeedback(shell, registry)
    tray = MagicMock()
    monkeypatch.setattr(feedback, "_tray", tray)
    monkeypatch.setattr(shell, "isActiveWindow", lambda: False)
    registry.start_task("long", "Organización de archivos")
    registry._tasks["long"]["started_at"] = datetime.now() - timedelta(minutes=2)
    registry.finish_task("long", "Completada")
    tray.assert_called_once()
    assert tray.call_args.args[:2] == ("Organización de archivos", "Completada")
    # Una tarea instantánea que sale bien no molesta
    registry.start_task("short", "Análisis")
    registry.finish_task("short", "Completada")
    tray.assert_called_once()


def test_taskbar_progress_is_a_noop_outside_windows():
    from src.gui.v2.task_feedback import WindowsTaskbarProgress

    progress = WindowsTaskbarProgress()
    if not progress.available:
        progress.set_state(123, WindowsTaskbarProgress.TBPF_INDETERMINATE)  # no lanza


def test_dropping_a_folder_on_home_or_organize_starts_analysis(shell, tmp_path, monkeypatch):
    analyze = MagicMock()
    monkeypatch.setattr(shell.organize_page, "analyze_folder", analyze)
    folder = tmp_path / "Descargas"
    folder.mkdir()
    event = _drop(shell._routes["home"].viewport(), folder)
    assert event.isAccepted()
    analyze.assert_called_once_with(str(folder))
    assert shell.stackedWidget.currentWidget() is shell._routes["organize"]
    _drop(shell._routes["organize"].viewport(), folder)
    assert analyze.call_count == 2
    # Un archivo suelto no se acepta
    loose = tmp_path / "nota.txt"
    loose.write_text("x", encoding="utf-8")
    _drop(shell._routes["home"].viewport(), loose)
    assert analyze.call_count == 2


def test_dropping_a_folder_on_space_usage_scans_it(shell, tmp_path, monkeypatch):
    space = shell.page("disks").space_page
    start = MagicMock(return_value=True)
    monkeypatch.setattr(space, "start_scan", start)
    _drop(space, tmp_path)
    start.assert_called_once()
    assert space.path_input.text() == str(tmp_path)


def test_last_visited_page_is_restored(tmp_path):
    from src.gui.v2.app_window import FluentAppWindow

    app = APP
    config_path = str(tmp_path / "config.json")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(FluentAppWindow, "_init_disk_manager", lambda self: None)
        first = _build(AppConfig(config_path))
        first._switch_route("activity")
        first.close()
        app.processEvents()
        assert AppConfig(config_path).get("interface.last_page") == "activity"
        second = _build(AppConfig(config_path))
        assert second.stackedWidget.currentWidget() is second._routes["activity"]
        second.close()
        app.processEvents()


def test_badge_stays_hidden_after_theme_change(shell):
    from src.gui.task_center import task_registry

    task_registry.start_task("badge", "Prueba")
    task_registry.finish_task("badge", "Completada")
    badge = shell.task_feedback.badge
    assert badge is not None and badge.isHidden()
    shell.set_theme_mode("dark" if shell.config.get_theme_mode() != "dark" else "light")
    shell._cleanup_theme_transition()
    QApplication.processEvents()
    assert badge.isHidden()


def test_home_disk_snapshot_never_blocks_the_window(shell):
    """Una unidad lenta (red desconectada, lector) no debe congelar el arranque."""
    import time
    from src.core.disk_manager import DiskInfo

    disk = DiskInfo(device="C:\\", mountpoint="C:\\", filesystem="NTFS", total_size=100, used_size=40,
                    free_size=60, usage_percent=40.0, is_system_drive=True, is_removable=False,
                    drive_letter="C", drive_type="fixed", opts="rw,fixed")

    class SlowManager:
        def get_all_disks(self):
            time.sleep(1.0)
            return [disk]

    shell._ensure_disk_manager = lambda: SlowManager()
    started = time.perf_counter()
    shell._load_disk_snapshot()
    assert time.perf_counter() - started < 0.5  # la interfaz sigue libre
    deadline = time.perf_counter() + 5
    while not shell._disk_snapshot[0] and time.perf_counter() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert shell._disk_snapshot[0] == (disk,) and shell._disk_snapshot[2] is None
