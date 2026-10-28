"""Visor de Discos con un DiskManager simulado: nada de smartctl real."""

import threading
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.core.disk_manager import DiskInfo, DiskReport
from src.core.health_service import health_level
from src.gui import disk_viewer as package
from src.gui.disk_viewer import health_renderer as renderer
from src.gui.disk_viewer import viewer as viewer_module

GB = 1024 ** 3


APP = None


def app():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


def disk(letter, mount=None, system=False, drive_type="fixed", used=25):
    mount = mount or f"{letter}:\\"
    return DiskInfo(device=mount, mountpoint=mount, filesystem="NTFS", total_size=100 * GB, used_size=used * GB,
                    free_size=(100 - used) * GB, usage_percent=float(used), is_system_drive=system,
                    is_removable=drive_type == "removable", drive_letter=letter, drive_type=drive_type)


class FakeManager:
    def __init__(self, disks):
        self.disks = disks
        self.futures = {}
        self.blocking_calls = []
        self.cached = None
        self.closed = False
        self.elevated = []

    def get_all_disks(self):
        return list(self.disks)

    def get_disk_info(self, path):
        return next((d for d in self.disks if d.mountpoint == path), None)

    def get_cached_report(self, path):
        return self.cached

    def submit_disk_report(self, path, force=False):
        future = Future()
        self.futures.setdefault(path, []).append(future)
        return future

    def prefetch_smart_for_disks(self, paths):
        pass

    def get_disk_io_stats(self, path):
        self.blocking_calls.append(path)

    def get_disk_health_status(self, path):
        self.blocking_calls.append(path)

    def get_safe_mode_status(self):
        return True

    def set_safe_mode(self, enabled):
        pass

    def retry_elevated(self, mountpoints):
        self.elevated.append(mountpoints)
        report = DiskReport(mountpoint=mountpoints[0], disk=self.get_disk_info(mountpoints[0]),
                            smart={"disk_model": "Elevado", "temperature": 33},
                            health={"available": True, "score": 95, "factors": []})
        return {mountpoints[0]: report}

    def shutdown(self):
        self.closed = True


@pytest.fixture
def viewer(monkeypatch):
    app()
    monkeypatch.setattr(viewer_module.os.path, "exists", lambda path: not path.startswith("A:"))
    manager = FakeManager([disk("A"), disk("C", system=True), disk("D", used=70), disk("E", drive_type="removable")])
    widget = package.DiskViewer(disk_manager=manager)
    widget.resize(1300, 900)
    widget.show()
    app().processEvents()
    yield widget
    widget.shutdown()
    widget.close()


def wait_for(condition, timeout=2000):
    for _ in range(timeout // 10):
        if condition():
            return True
        QTest.qWait(10)
    return condition()


def test_rows_are_contiguous_and_cards_map_to_the_right_disk(viewer):
    # A: no existe → se salta sin dejar huecos (insertRow(rowCount()))
    assert viewer.disks_table.rowCount() == 3
    assert [viewer.disks_table.item(r, 1).text() for r in range(3)] == ["C:\\", "D:\\", "E:\\"]
    assert [card.row for card in viewer.disk_cards.cards] == [0, 1, 2]
    viewer.disk_cards.cards[1].clicked.emit(1)
    assert viewer.current_selection == "D:\\"
    emitted = []
    viewer.disk_selected.connect(emitted.append)
    viewer.disk_cards.cards[2].analyze_button.click()
    assert emitted == ["E:\\"] and viewer.current_selection == "E:\\"
    system_card = viewer.disk_cards.cards[0]
    assert "Windows" in system_card.badge.toolTip()


def test_selection_never_runs_smartctl_on_gui_thread_and_ignores_stale(viewer):
    manager = viewer.disk_manager
    assert viewer.current_selection == "C:\\"
    assert manager.blocking_calls == []
    assert "Leyendo datos SMART" in viewer.health_status_label.text()
    assert viewer.temperature_label.text() == "…"
    stale = manager.futures["C:\\"][-1]
    viewer.select_row(1)
    current = manager.futures["D:\\"][-1]
    fresh = DiskReport(mountpoint="D:\\", disk=manager.disks[2], physical_disk=1,
                       smart={"disk_model": "WD Red", "temperature": 41, "power_on_hours": 48,
                              "critical_attributes": {197: {"name": "Current_Pending_Sector", "raw": 3}}},
                       health={"available": True, "score": 45, "level": health_level(45),
                               "factors": [{"severity": "critical", "text": "Sectores pendientes (3)"}],
                               "alerts": ["Los sectores pendientes (197) han aumentado: 0 → 3"]})
    # El resultado llega desde otro hilo, como en el executor real.
    threading.Thread(target=current.set_result, args=(fresh,)).start()
    assert wait_for(lambda: "WD Red" in viewer.basic_info_label.text())
    html = viewer.health_status_label.text()
    assert "Advertencia" in html and "45/100" in html and "Sectores pendientes" in html and "197" in html
    assert viewer.temperature_label.text() == "41 °C" and viewer.power_hours_label.text().startswith("48 h")
    stale.set_result(DiskReport(mountpoint="C:\\", disk=manager.disks[1], smart={"disk_model": "Viejo"}))
    QTest.qWait(30)
    assert "Viejo" not in viewer.basic_info_label.text()
    assert manager.blocking_calls == []


def test_content_summary_runs_in_background(viewer, monkeypatch):
    calls = []

    def summary(path, max_items=10000):
        calls.append(threading.current_thread().name)
        return {"total_files": 3, "total_dirs": 1, "total_size": 30, "file_types": {".txt": 3}}

    monkeypatch.setattr("src.gui.disk_viewer.controller.summarize_top_level", summary)
    viewer._content_cache.clear()
    viewer.select_row(1)
    assert wait_for(lambda: "Extensiones" in viewer.content_info_label.text())
    assert calls and calls[0] != threading.current_thread().name


def test_cpu_percent_is_non_blocking(viewer, monkeypatch):
    seen = []
    monkeypatch.setattr(viewer_module.psutil, "cpu_percent", lambda interval=None: seen.append(interval) or 7.0)
    viewer.update_system_info()
    assert seen == [None]
    text = viewer.system_info_label.text()
    assert text.startswith("CPU 7 %") and "3 unidades" in text and "\n" not in text and "Memoria" in viewer.system_info_label.toolTip()


def test_admin_banner_and_elevated_retry(viewer, monkeypatch):
    monkeypatch.setattr(viewer_module.sys, "platform", "win32")
    manager = viewer.disk_manager
    viewer.select_row(1)
    report = DiskReport(mountpoint="D:\\", disk=manager.disks[2], error="admin_required",
                        health={"available": False, "score": None, "factors": [], "admin_required": True,
                                "status": "Se necesitan permisos de administrador para leer SMART"})
    manager.futures["D:\\"][-1].set_result(report)
    assert wait_for(lambda: viewer.detail_panel.admin_banner.isVisible())
    assert viewer.detail_panel.admin_button.isVisible()
    assert "administrador" in viewer.health_status_label.text()
    viewer.detail_panel.admin_button.click()
    assert wait_for(lambda: "Elevado" in viewer.basic_info_label.text())
    assert manager.elevated == [["D:\\"]] and not viewer.detail_panel.admin_banner.isVisible()


def test_cards_flow_without_clipping(viewer):
    grid = viewer.disk_cards
    viewer.resize(1300, 900)
    app().processEvents()
    QTest.qWait(20)
    assert grid.columns >= 3
    viewer.resize(420, 900)
    app().processEvents()
    QTest.qWait(20)
    assert grid.columns == 1
    assert all(card.geometry().right() <= grid.width() for card in grid.cards)
    assert grid.minimumSizeHint().width() <= 420


def test_shutdown_stops_controller_and_manager(viewer):
    viewer.shutdown()
    assert viewer.disk_manager.closed and viewer.controller._closed
    viewer.shutdown()


def test_fluent_hooks_still_exist(viewer):
    for name in ("enable_fluent_mode", "refresh_fluent_theme", "apply_theme_styles", "refresh_disks",
                 "update_selected_disk_info", "get_selected_disk_path", "system_info_label",
                 "safe_mode_label", "safe_mode_checkbox", "refresh_btn", "disks_table", "log_text"):
        assert hasattr(viewer, name)
    viewer.enable_fluent_mode()
    viewer.refresh_fluent_theme()
    assert type(viewer).__name__ == "DiskViewer"


def test_renderer_is_pure_and_honest():
    d = disk("C", system=True)
    unavailable = renderer.render_health_html(d, {"available": False, "score": None, "status": "x"},
                                              report=SimpleNamespace(error="admin_required"))
    assert "sin datos" in unavailable and "administrador" in unavailable and "CRÍTICO" not in unavailable
    assert "0/100" not in renderer.render_health_html(d, {"status": "Error", "score": None})
    good = renderer.render_health_html(d, {"available": True, "score": 92, "factors": ["texto plano"]},
                                       palette={"success": "#00ff00"})
    assert "Excelente" in good and "#00ff00" in good and "texto plano" in good
    for emoji in ("🟢", "🔴", "📊", "💾"):
        assert emoji not in good
    assert "Windows" in renderer.render_basic_html(d)
    nvme = renderer.render_critical_attributes({"critical_attributes": {"media_errors": 2, "percentage_used": 9}})
    assert "Errores de medio" in nvme and "Vida usada" in nvme
    assert renderer.rgba("#102030", 0.5) == "rgba(16, 32, 48, 0.50)"
    texts = renderer.smart_metric_texts(SimpleNamespace(smart={"read_count": None, "temperature": 30}))
    assert texts["read_count"] == "—" and texts["temperature"] == "30 °C"
