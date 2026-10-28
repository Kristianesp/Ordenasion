"""DiskManager con psutil, smartctl, ctypes y PowerShell simulados."""

import threading
import time
from collections import namedtuple
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.core import disk_manager as dm
from src.core.smart_history import SmartHistory
from src.utils.app_config import AppConfig
from src.utils.smartctl_wrapper import SmartQuery

GB = 1024 ** 3
Partition = namedtuple("Partition", "device mountpoint fstype opts")
Usage = namedtuple("Usage", "total used free percent")


class FakeSmart:
    def __init__(self, data=None, error=None, delay=0.0):
        self.data, self.error, self.delay = data, error, delay
        self.calls = []
        self.closed = False

    def is_available(self):
        return not self.closed

    def scan_all_disks(self):
        return [{"device": "/dev/sda", "type": "ata", "physical_index": 0},
                {"device": "/dev/sdb", "type": "sat", "physical_index": 1}]

    def query(self, device, timeout=10, device_type=None, max_retries=1):
        self.calls.append((device, device_type))
        if self.delay:
            time.sleep(self.delay)
        return SmartQuery(device=device, data=dict(self.data) if self.data else None, error=self.error)

    def shutdown(self):
        self.closed = True


def make_manager(tmp_path, smart=None, history=False):
    config = AppConfig(str(tmp_path / "config.json"))
    hist = SmartHistory(tmp_path / "history.db") if history else None
    manager = dm.DiskManager(config, smartctl=smart or FakeSmart(), history=hist)
    if not history:
        manager.history = None
    return manager


@pytest.fixture
def windows_volumes(monkeypatch):
    parts = [Partition("C:\\", "C:\\", "NTFS", "rw,fixed"), Partition("D:\\", "D:\\", "NTFS", "rw,fixed"),
             Partition("E:\\", "E:\\", "exFAT", "rw,removable"), Partition("Z:\\", "Z:\\", "NTFS", "rw,remote"),
             Partition("F:\\", "F:\\", "CDFS", "ro,cdrom")]
    monkeypatch.setattr(dm.psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr(dm.psutil, "disk_usage", lambda mp: Usage(100 * GB, 25 * GB, 70 * GB, 26.3))
    monkeypatch.setattr(dm.os.path, "exists", lambda p: True)
    return parts


def test_drive_types_system_drive_and_consistent_percent(tmp_path, monkeypatch, windows_volumes):
    monkeypatch.setenv("SystemDrive", "D:")
    monkeypatch.setattr(dm, "win_drive_type", lambda root: None)  # sin Windows: opts de psutil
    manager = make_manager(tmp_path)
    disks = {disk.drive_letter: disk for disk in manager.get_all_disks()}
    assert disks["D"].is_system_drive and not disks["C"].is_system_drive
    assert disks["E"].drive_type == "removable" and disks["E"].is_removable
    assert disks["Z"].drive_type == "network" and not disks["Z"].smart_applicable
    assert disks["F"].drive_type == "optical" and disks["F"].drive_type_label == "Unidad óptica"
    # Porcentaje = usado / total, igual que el donut de Inicio (no el de psutil)
    assert disks["C"].usage_percent == 25.0


def test_get_drive_type_w_is_preferred(tmp_path, monkeypatch, windows_volumes):
    monkeypatch.setattr(dm, "win_drive_type", lambda root: {"C:\\": "fixed", "E:\\": "fixed"}.get(root, "ram"))
    disks = {disk.drive_letter: disk for disk in make_manager(tmp_path).get_all_disks()}
    assert disks["E"].drive_type == "fixed" and disks["D"].drive_type == "ram"


def test_get_disk_info_uses_snapshot_and_most_specific_mount(tmp_path, monkeypatch):
    parts = [Partition("/dev/a", "/", "ext4", "rw"), Partition("/dev/b", "/mnt/datos", "ext4", "rw")]
    calls = []
    monkeypatch.setattr(dm.psutil, "disk_partitions", lambda all=False: calls.append(1) or parts)
    monkeypatch.setattr(dm.psutil, "disk_usage", lambda mp: Usage(10 * GB, 1 * GB, 9 * GB, 10.0))
    manager = make_manager(tmp_path)
    assert manager.get_disk_info("/mnt/datos/fotos").mountpoint == "/mnt/datos"
    assert manager.get_disk_info("/home/user").mountpoint == "/"
    assert manager.get_disk_info("/mnt/datosX").mountpoint == "/"
    assert len(calls) == 1  # no vuelve a enumerar en cada llamada
    assert manager.get_disk_info("/").is_system_drive and not manager.get_disk_info("/mnt/datos").is_system_drive


def test_physical_mapping_chain_without_size_heuristics(tmp_path, monkeypatch):
    manager = make_manager(tmp_path)
    monkeypatch.setattr(dm, "win_device_number", lambda mp: {"C:\\": 0, "D:\\": 0}.get(mp))
    powershell = MagicMock(return_value={"E": 1})
    monkeypatch.setattr(dm, "powershell_partition_map", powershell)
    manager._wmi_map = {"F:": "PHYSICALDRIVE2"}
    # Varias letras en el mismo disco físico
    assert manager.resolve_physical_disk("C:\\") == 0 and manager.resolve_physical_disk("D:\\") == 0
    assert manager.resolve_physical_disk("E:\\") == 1
    assert manager.resolve_physical_disk("F:\\") == 2
    assert manager.resolve_physical_disk("G:\\") is None
    powershell.assert_called_once()  # el mapa de PowerShell se cachea
    # Caché negativa con TTL
    monkeypatch.setattr(dm, "win_device_number", lambda mp: 5)
    assert manager.resolve_physical_disk("G:\\") is None
    key = dm._normalize("G:\\")
    manager._drive_map[key] = (None, time.monotonic() - dm.NEGATIVE_MAP_TTL - 1)
    assert manager.resolve_physical_disk("G:\\") == 5
    assert manager._smart_target(1) == ("/dev/sdb", "sat")
    assert manager._smart_target(7) == ("/dev/pd7", None)


def test_partition_json_parsing():
    assert dm.parse_partition_json('{"DriveLetter":"C","DiskNumber":0}') == {"C": 0}
    assert dm.parse_partition_json('[{"DriveLetter":"D","DiskNumber":1},{"DriveLetter":69,"DiskNumber":2},'
                                   '{"DriveLetter":"","DiskNumber":3}]') == {"D": 1, "E": 2}
    assert dm.parse_partition_json("basura") == {}


def test_win_device_number_ioctl_with_mocked_ctypes(monkeypatch):
    import ctypes
    monkeypatch.setattr(dm.sys, "platform", "win32")

    class Kernel32:
        def __init__(self):
            self.CreateFileW = MagicMock(return_value=42)
            self.closed = []

        def DeviceIoControl(self, handle, code, inbuf, insize, outbuf, outsize, returned, overlapped):
            assert handle == 42 and code == dm.IOCTL_STORAGE_GET_DEVICE_NUMBER
            outbuf._obj.DeviceNumber = 3
            return 1

        def CloseHandle(self, handle):
            self.closed.append(handle)

    kernel = Kernel32()
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: kernel, raising=False)
    assert dm.win_device_number("D:\\") == 3
    assert kernel.CreateFileW.call_args.args[0] == "\\\\.\\D:" and kernel.closed == [42]


def test_report_inflight_dedupe_ttl_and_shared_physical_query(tmp_path, monkeypatch, windows_volumes):
    smart = FakeSmart({"disk_model": "M", "temperature": 30, "smart_status": True}, delay=0.2)
    manager = make_manager(tmp_path, smart)
    monkeypatch.setattr(dm, "win_drive_type", lambda root: None)
    monkeypatch.setattr(dm, "win_device_number", lambda mp: 0)
    first = manager.submit_disk_report("C:\\")
    second = manager.submit_disk_report("C:\\")
    assert first is second
    other_letter = manager.submit_disk_report("D:\\")
    assert first.result(5).smart["temperature"] == 30 and other_letter.result(5).smart
    assert len(smart.calls) == 1  # mismo disco físico → un solo smartctl
    assert manager.submit_disk_report("C:\\").result(1) is first.result()
    assert manager.get_cached_report("C:\\") is first.result()
    manager.smart_ttl = 0
    manager.get_disk_report("C:\\", timeout=5)
    assert len(smart.calls) == 2
    manager.shutdown()


def test_network_optical_skip_smart_and_admin_and_exceptions(tmp_path, monkeypatch, windows_volumes):
    monkeypatch.setattr(dm, "win_drive_type", lambda root: None)
    monkeypatch.setattr(dm, "win_device_number", lambda mp: 1)
    smart = FakeSmart(error="admin_required")
    manager = make_manager(tmp_path, smart)
    network = manager.get_disk_report("Z:\\", timeout=5)
    assert network.error == "not_applicable" and smart.calls == []
    report = manager.get_disk_report("C:\\", timeout=5)
    assert report.admin_required and report.health["available"] is False
    manager.get_disk_report = MagicMock(side_effect=RuntimeError("boom"))
    health = manager.get_disk_health_status("C:\\")
    assert health["available"] is False and health["score"] is None


def test_build_report_exception_is_unavailable_not_critical(tmp_path, monkeypatch, windows_volumes):
    monkeypatch.setattr(dm, "win_drive_type", lambda root: None)
    manager = make_manager(tmp_path)
    monkeypatch.setattr(manager, "resolve_physical_disk", MagicMock(side_effect=RuntimeError("x")))
    report = manager.get_disk_report("C:\\", timeout=5)
    assert report.health["available"] is False and report.health["score"] is None


def test_shutdown_cancels_executor_and_kills_smartctl(tmp_path):
    smart = FakeSmart()
    manager = make_manager(tmp_path, smart)
    manager._executor = MagicMock()
    manager.shutdown()
    manager._executor.shutdown.assert_called_once_with(wait=False, cancel_futures=True)
    assert smart.closed
    manager.shutdown()  # idempotente
    assert manager.submit_disk_report("C:\\").cancelled()


def test_history_alerts_when_sectors_increase(tmp_path):
    history = SmartHistory(tmp_path / "h.db")
    base = {"disk_model": "HDD", "serial_number": "S1", "reallocated_sectors": 0, "pending_sectors": 0,
            "temperature": 40, "write_bytes": 1000}
    day1 = datetime(2026, 10, 1, 12)
    assert history.record(base, day1) == []
    assert history.record({**base, "temperature": 45}, day1 + timedelta(hours=1)) == []
    alerts = history.record({**base, "pending_sectors": 2, "write_bytes": 3000}, day1 + timedelta(days=2))
    assert alerts and "197" in alerts[0]
    rows = history.trend(base)
    assert [row["day"] for row in rows] == ["2026-10-01", "2026-10-03"]
    assert rows[0]["temperature_max"] == 45
    summary = SmartHistory.summarize(rows)
    assert summary["pending_delta"] == 2 and summary["write_bytes_per_day"] == 1000
    assert history.record({"disk_model": "sin serie"}) == []


def test_dead_helpers_removed():
    for name in ("analyze_disk_space", "_analyze_folder_contents", "get_multiple_disk_io_stats",
                 "can_write_to_disk", "_map_drives_with_smartctl_only"):
        assert not hasattr(dm.DiskManager, name)


def test_summarize_top_level(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"12")
    (tmp_path / "sub").mkdir()
    summary = dm.summarize_top_level(str(tmp_path))
    assert summary["total_files"] == 1 and summary["total_dirs"] == 1 and summary["file_types"] == {".txt": 1}
