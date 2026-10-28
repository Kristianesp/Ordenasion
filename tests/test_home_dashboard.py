"""Dashboard de snapshots: sólo datos sintéticos y archivos temporales."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.core.space_usage import scan_space
from src.gui.task_center import task_registry
from src.gui.v2.dashboard_charts import DiskUsageChart, FolderSizeChart, disk_values
from src.gui.v2.pages.home_page import HomePage
from src.utils.app_config import AppConfig


APP = None


@pytest.fixture
def page(tmp_path, monkeypatch):
    global APP
    APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(task_registry, "_tasks", {})
    widget = HomePage(AppConfig(str(tmp_path / "config.json")), SimpleNamespace())
    widget.resize(1300, 900)
    widget.show()
    APP.processEvents()
    yield widget
    widget.close()


def drive(path="Z:\\", total=1000, used=700, free=300):
    return SimpleNamespace(mountpoint=path, total_size=total, used_size=used, free_size=free)


def result_fixture(tmp_path):
    root = tmp_path / "inventario"
    root.mkdir()
    for index in range(7):
        folder = root / f"Carpeta {index}"
        folder.mkdir()
        nested = folder / "Anidada"
        nested.mkdir()
        (nested / "archivo.bin").write_bytes(b"x" * (index + 1) * 10)
    (root / "archivo directo.bin").write_bytes(b"x" * 150)
    return scan_space(str(root))


def test_empty_dashboard_has_honest_placeholders_and_no_automatic_analysis(page):
    paths = []
    page.analyze_requested.connect(paths.append)
    assert paths == [] and page.path_input.text() == ""
    assert page.disk_metric.value_label.text() == "—"
    assert page.space_metric.detail_label.text() == "Sin análisis de espacio"
    assert page.organize_metric.value_label.text() == "—"
    assert page.task_metric.value_label.text() == "0"
    assert page.usage_chart.values is None and page.folders_chart.bars == ()
    assert not page.result_button.isEnabled() and not page.undo_button.isEnabled()
    destinations = []
    page.navigate_requested.connect(destinations.append)
    page.open_space_button.click()
    page.open_disks_button.click()
    assert destinations == ["space", "disk-health"]


def test_snapshots_total_without_nested_double_count_and_drive_selection(page, tmp_path):
    result = result_fixture(tmp_path)
    stamp = datetime(2026, 9, 27, 12, 30, 15)
    page.update_dashboard([drive(), drive("Y:\\", used=200, free=800)], result, stamp)
    assert page.usage_chart.values == (1000, 700, 300)
    assert "70.0%" in page.disk_metric.value_label.text()
    assert "12:30:15" in page.disk_snapshot_label.text()
    assert sum(value for _, value, _ in page.folders_chart.bars) == result.nodes[0].size
    assert len(page.folders_chart.bars) == 6
    assert page.folders_chart.bars[0][0] == "archivo directo.bin"
    assert all(name != "Anidada" for name, _, _ in page.folders_chart.bars)
    assert page.space_path_label.toolTip() == result.root_path
    page.drive_selector.setCurrentIndex(1)
    page.update_dashboard([drive(), drive("Y:\\", used=200, free=800)], result, stamp, "Fallo simulado")
    assert page.drive_selector.currentData() == "Y:\\"
    assert page.usage_chart.values == (1000, 200, 800)
    assert "No se pudo actualizar" in page.disk_snapshot_label.text()
    assert page.disk_snapshot_label.toolTip() == "Fallo simulado"
    assert page._space_result is result


def test_invalid_disk_and_partial_zero_are_not_presented_as_empty(page, tmp_path):
    assert disk_values(drive(total=0)) is None
    assert disk_values(drive(used=-1)) is None
    assert disk_values(drive(used=900, free=300)) is None
    root = tmp_path / "vacía"
    root.mkdir()
    result = scan_space(str(root))
    result.nodes[0].status = "partial"
    page.update_dashboard([drive(total=0)], result)
    assert page.usage_chart.values is None and page.disk_metric.value_label.text() == "—"
    assert page.folders_chart.partial
    assert "análisis parcial" in page.folders_chart.accessibleDescription()
    assert "Parcial" in page.space_snapshot_label.text() or "parcial" in page.space_snapshot_label.text()


def test_activity_and_operation_actions_follow_real_state(page):
    task_registry.start_task("active", "Mover archivos", cancel_callback=lambda: None)
    task_registry.cancel_task("active")
    task_registry.start_task("ended", "Comprobar carpeta")
    task_registry.finish_task("ended", "Error")
    page.set_space_scan_active(True)
    assert page.task_metric.value_label.text() == "2"
    assert "Cancelación solicitada" in page.activity_labels[1].toolTip()
    controller = SimpleNamespace(last_operation_summary={"files_moved": 12, "folders_moved": 1, "errors": []},
                                 current_organize_task_id=None, last_transaction_id="temporary")
    page.update_operation(controller)
    assert page.organize_metric.value_label.text() == "12"
    assert page.undo_button.isEnabled() and page.result_button.isEnabled()
    results, undos = [], []
    page.result_requested.connect(lambda: results.append(True))
    page.undo_requested.connect(lambda: undos.append(True))
    page.result_button.click()
    page.undo_button.click()
    assert results == undos == [True]
    controller.last_operation_summary["undone"] = True
    page.update_operation(controller)
    assert not page.undo_button.isEnabled() and "deshecha" in page.organize_metric.detail_label.text()
    task_registry.finish_task("active", "Cancelada")
    page.set_space_scan_active(False)
    assert page.task_metric.value_label.text() == "0"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_charts_render_and_responsive_layout_preserves_path_focus(page, tmp_path, theme):
    page.config.set_theme_mode(theme)
    page.refresh_theme()
    result = result_fixture(tmp_path)
    result.root_path = "Z:\\" + "Ruta larga 日本語\\" * 60
    page.update_dashboard([drive()], result, datetime.now())
    page.path_input.setText(str(tmp_path))
    page.path_input.setFocus()
    APP.processEvents()
    assert page._metric_columns == 4 and page._chart_columns == 2
    assert not page.usage_chart.grab().isNull() and not page.folders_chart.grab().isNull()
    assert "bytes" in page.usage_chart.accessibleDescription()
    page.resize(800, 1000)
    APP.processEvents()
    assert page._metric_columns == 2 and page._chart_columns == 1
    assert page.horizontalScrollBar().maximum() == 0
    assert page.path_input.text() == str(tmp_path)
    assert page.drive_selector.currentData() == "Z:\\" and page._space_result is result
    QTest.keyClick(page.path_input, Qt.Key.Key_Tab)
    assert APP.focusWidget() is page.browse_button


def test_disk_viewer_publishes_empty_and_failed_refresh_without_losing_snapshot(monkeypatch):
    from src.gui import disk_viewer as module
    signal = MagicMock()
    manager = SimpleNamespace(get_all_disks=lambda: [])
    facade = SimpleNamespace(disk_manager=manager, available_disks=(drive(),), disks_updated_at=None,
        disks_refresh_error=None, disks_refreshed=SimpleNamespace(emit=signal), log_message=MagicMock(),
        disks_table=MagicMock(), _rebuild_disk_cards=MagicMock())
    module.DiskViewer.refresh_disks(facade)
    assert facade.available_disks == () and facade.disks_updated_at is not None
    signal.assert_called_once_with(())
    previous_stamp = facade.disks_updated_at
    old = (drive(),)
    facade.available_disks = old
    manager.get_all_disks = MagicMock(side_effect=OSError("denegado"))
    monkeypatch.setattr(module.QMessageBox, "critical", MagicMock())
    module.DiskViewer.refresh_disks(facade)
    assert facade.available_disks is old and facade.disks_updated_at is previous_stamp
    assert facade.disks_refresh_error == "denegado"
    assert signal.call_args.args == (old,)


def test_home_shortcuts_select_explicit_disk_view_without_analysis():
    from src.gui.v2.app_window import FluentAppWindow
    disks = SimpleNamespace(set_disk_view=MagicMock())
    facade = SimpleNamespace(_routes={"disks": disks}, switchTo=MagicMock())
    FluentAppWindow._switch_route(facade, "space")
    disks.set_disk_view.assert_called_once_with("space")
    facade.switchTo.assert_called_once_with(disks)
    FluentAppWindow._switch_route(facade, "disk-health")
    assert disks.set_disk_view.call_args.args == ("health",)
