"""Sólo fixtures temporales; ningún escaneo de unidades ni apertura real."""

import os
import random
import stat
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from src.core import space_usage as engine
from src.gui.v2.space_usage_worker import SpaceScanWorker
from src.gui.v2.space_map import SpaceMap, squarified
from src.gui.v2.pages.space_usage_page import SpaceUsagePage
from src.utils.app_config import AppConfig

APP = None


def application():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


def inventory(tmp_path):
    (tmp_path / "Música_日本語").mkdir()
    (tmp_path / "Música_日本語" / "pista.mp3").write_bytes(b"a" * 100)
    (tmp_path / ".oculto").write_bytes(b"b" * 30)
    (tmp_path / "vacía").mkdir()
    return engine.scan_space(str(tmp_path))


def test_engine_totals_hidden_unicode_empty_and_indices(tmp_path):
    result = inventory(tmp_path)
    assert result.nodes[0].size == 130
    assert result.file_count == 2 and result.folder_count == 2
    assert sum(result.nodes[index].size for index in result.children[0]) == 130
    assert result.nodes[result.top_files[0]].name == "pista.mp3"
    assert result.nodes[result.top_folders[0]].size == 100
    assert result.children[next(node.id for node in result.nodes if node.name == "vacía")] == ()


def test_engine_root_denied_and_nested_errors_continue(tmp_path, monkeypatch):
    for name in ("denied", "deleted", "broken"):
        (tmp_path / name).mkdir()
    (tmp_path / "good.txt").write_bytes(b"123")
    original = engine.os.scandir

    def scandir(path):
        name = os.path.basename(path)
        errors = {"denied": PermissionError(), "deleted": FileNotFoundError(), "broken": OSError("unavailable")}
        if name in errors:
            raise errors[name]
        return original(path)

    monkeypatch.setattr(engine.os, "scandir", scandir)
    result = engine.scan_space(str(tmp_path))
    assert result.nodes[0].size == 3 and result.nodes[0].status == "partial"
    assert (result.denied_count, result.missing_count, result.error_count) == (1, 1, 1)
    application()
    page = SpaceUsagePage(AppConfig(str(tmp_path / "config.json")))
    page._completed(0, result)
    assert page.status_label.text().startswith("Completado parcialmente")
    page.close()
    monkeypatch.setattr(engine.os, "scandir", lambda _: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(engine.SpaceScanError):
        engine.scan_space(str(tmp_path))


def test_engine_links_cloud_placeholders_and_cancellation(tmp_path):
    (tmp_path / "file.txt").write_bytes(b"1234")
    assert not engine._is_link(SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400, st_reparse_tag=0x9000001A))
    assert engine._is_link(SimpleNamespace(st_mode=stat.S_IFDIR, st_reparse_tag=0xA0000003))
    assert engine._is_link(SimpleNamespace(st_mode=stat.S_IFREG, st_reparse_tag=0xA000000C))
    with pytest.raises(engine.SpaceScanCancelled):
        engine.scan_space(str(tmp_path), cancelled=lambda: True)
    try:
        os.symlink(tmp_path / "file.txt", tmp_path / "link.txt")
    except OSError:
        return  # Windows sin permiso de symlink: tags de junction/symlink arriba.
    result = engine.scan_space(str(tmp_path))
    assert result.skipped_links == 1 and result.nodes[0].size == 4


def test_engine_long_path_and_progress_throttle(tmp_path, monkeypatch):
    current = tmp_path
    for _ in range(7):
        current = current / ("á" * 35)
        current.mkdir()
    (current / "fin.txt").write_bytes(b"abcdef")
    ticks = iter(index * 0.05 for index in range(10000))
    monkeypatch.setattr(engine.time, "monotonic", lambda: next(ticks))
    progress = []
    result = engine.scan_space(str(tmp_path), progress=lambda *args: progress.append(args))
    assert result.nodes[0].size == 6
    assert len(result.nodes[-1].path) > 260
    assert progress and all(len(values) == 5 for values in progress)
    assert len(progress) < 12


def test_worker_large_progress_and_unexpected_failure(tmp_path, monkeypatch):
    from src.gui.v2 import space_usage_worker as module
    application()
    worker = SpaceScanWorker(7, str(tmp_path))
    progress = []
    errors = []
    worker.progress.connect(lambda *args: progress.append(args))
    worker.scan_failed.connect(lambda *args: errors.append(args))
    worker.progress.emit(7, 1, 0, 5 * 1024**3, 0, str(tmp_path))
    assert progress[0][3] == 5 * 1024**3
    monkeypatch.setattr(module, "scan_space", MagicMock(side_effect=RuntimeError("test error")))
    worker.run()
    assert errors == [(7, "test error")]


def test_squarified_extreme_sizes_stay_inside_without_overlap():
    random.seed(9)
    areas = [random.random() ** 6 for _ in range(50)]
    bounds = QRectF(0, 0, 800, 300)
    rectangles = squarified(areas, bounds)
    assert len(rectangles) == len(areas)
    assert sum(rect.width() * rect.height() for rect in rectangles) == pytest.approx(240000, abs=0.001)
    for index, rect in enumerate(rectangles):
        assert rect.width() >= 0 and rect.height() >= 0
        assert rect.left() >= -1e-6 and rect.top() >= -1e-6
        assert rect.right() <= 800 + 1e-6 and rect.bottom() <= 300 + 1e-6
        for other in rectangles[index + 1:]:
            overlap = rect.intersected(other)
            assert overlap.width() * overlap.height() <= 1e-6


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_page_navigation_filter_selection_map_and_no_file_open(tmp_path, monkeypatch, mode):
    from src.gui.v2.pages import space_usage_page as module
    application()
    source = tmp_path / "source"
    source.mkdir()
    result = inventory(source)
    config = AppConfig(str(tmp_path / "config.json"))
    config.set_theme_mode(mode)
    page = SpaceUsagePage(config)
    page.resize(1100, 950)
    page.show()
    application().processEvents()
    assert page.result is None and page._worker is None
    page._completed(0, result)
    assert page.model.rowCount() == 3
    folder = next(node.id for node in result.nodes if node.name == "Música_日本語")
    file = next(node.id for node in result.nodes if node.name == "pista.mp3")
    page.space_map.selected.emit(folder)
    assert page.selected_id == folder
    assert page.model.rows[page.table.currentIndex().row()] == folder
    page.space_map.folder_opened.emit(folder)
    assert page.current_id == folder and page.model.rows == (file,)
    open_url = MagicMock()
    monkeypatch.setattr(module.QDesktopServices, "openUrl", open_url)
    page._activate_row(page.model.index(0, 0))
    assert page.current_id == folder
    open_url.assert_not_called()
    page.select_node(file)
    page.open_location()
    assert os.path.normcase(os.path.normpath(open_url.call_args.args[0].toLocalFile())) == os.path.normcase(os.path.normpath(result.nodes[folder].path))
    page.copy_path()
    assert QApplication.clipboard().text() == result.nodes[file].path
    QTest.keyClick(page.table, Qt.Key.Key_Backspace)
    assert page.current_id == 0
    page.filter_input.setText(".OCULTO")
    page._refresh_view()
    assert page.model.rowCount() == 1
    page.list_mode.setCurrentIndex(1)
    assert len(page.model.rows) == 2 and not page.filter_input.isEnabled()
    page._completed(99, engine.scan_space(str(source)))
    assert page.result is result  # resultado antiguo se ignora
    page.list_mode.setCurrentIndex(2)
    page.navigate_to(folder)
    assert page.list_mode.currentIndex() == 0 and not page.filter_input.text()
    page.select_node(file)
    page.filter_input.setText("no coincidencia")
    page._refresh_view()
    assert page.selected_id is None and not page.open_button.isEnabled()
    page.go_up()
    page.list_mode.setCurrentIndex(1)
    page.space_map.selected.emit(folder)
    assert page.list_mode.currentIndex() == 0 and page.selected_id == folder
    open_url.return_value = False
    page.open_location()
    assert "No se pudo abrir" in page.status_label.text() and page.result is result
    page.resize(800, 1100)
    application().processEvents()
    assert page._columns == 1, (page.width(), page.minimumSizeHint().width())
    page.close()


def test_worker_cancel_restart_and_cooperative_shutdown(tmp_path, monkeypatch):
    import threading
    from src.gui.v2 import space_usage_worker as module
    application()
    config = AppConfig(str(tmp_path / "config.json"))
    page = SpaceUsagePage(config)
    page.path_input.setText(str(tmp_path))
    entered = threading.Event()

    def slow_scan(root, cancelled, progress):
        entered.set()
        while not cancelled():
            threading.Event().wait(0.01)
        raise engine.SpaceScanCancelled()

    monkeypatch.setattr(module, "scan_space", slow_scan)
    old = engine.scan_space(str(tmp_path))
    page._completed(0, old)
    assert page.progress_bar.isHidden()
    assert page.start_scan() and not page.start_scan()
    assert not page.progress_bar.isHidden()
    assert entered.wait(1)
    finished = MagicMock()
    assert page.request_shutdown(finished)
    for _ in range(100):
        QTest.qWait(10)
        if page._worker is None:
            break
    assert page._worker is None
    assert page.progress_bar.isHidden()
    assert page.result is old and page.analyze_button.isEnabled()
    finished.assert_called_once()
    monkeypatch.setattr(module, "scan_space", engine.scan_space)
    assert page.start_scan()
    for _ in range(100):
        QTest.qWait(10)
        if page._worker is None:
            break
    assert page._worker is None and page.result is not old


def test_map_aggregates_tiny_blocks_and_keyboard_opens_only_folders(tmp_path):
    application()
    config = AppConfig(str(tmp_path / "config.json"))
    widget = SpaceMap(config)
    widget.resize(400, 300)
    nodes = [engine.SpaceNode(1, 0, "Grande", "Grande", "folder", 100000), engine.SpaceNode(2, 0, "Archivo", "Archivo", "file", 30000)]
    nodes.extend(engine.SpaceNode(index, 0, str(index), str(index), "file", 1) for index in range(3, 51))
    widget.set_items(nodes)
    assert len(widget.blocks) == 3
    assert widget.blocks[-1][1][4] == "aggregate"
    assert widget.blocks[-1][1][2] == 48
    selected, entered = [], []
    widget.selected.connect(selected.append)
    widget.folder_opened.connect(entered.append)
    QTest.keyClick(widget, Qt.Key.Key_Right)
    assert selected == [1]
    QTest.keyClick(widget, Qt.Key.Key_Return)
    assert entered == [1]
    QTest.keyClick(widget, Qt.Key.Key_Right)
    QTest.keyClick(widget, Qt.Key.Key_Return)
    assert entered == [1]
