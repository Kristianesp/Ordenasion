import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.utils import smartctl_wrapper as module
from src.utils.smartctl_wrapper import SmartctlWrapper, decode_smart_flags, parse_scan_output


def load_json(name: str):
    return json.loads(Path(__file__).parent.joinpath('fixtures', name).read_text(encoding='utf-8'))


def wrapper(path="smartctl.exe"):
    return SmartctlWrapper(smartctl_path=path)


def test_parse_nvme_smart():
    data = load_json('nvme_smart.json')
    data["nvme_smart_health_information_log"]["percentage_used"] = 7
    out = wrapper()._parse_smart_json(data)
    assert out['device_type'] == 'nvme'
    assert out['temperature'] == 46
    assert out['power_on_hours'] == 1234
    assert out['read_bytes'] == 100000 * 512000
    assert out['write_bytes'] == 250000 * 512000
    # Salud NVMe = 100 - percentage_used (no available_spare)
    assert out['health_percentage'] == 93
    assert out['critical_attributes']['available_spare'] == 98


def test_parse_sata_smart_units_by_attribute_name():
    out = wrapper()._parse_smart_json(load_json('sata_smart.json'))
    assert out['device_type'] == 'ata'
    assert out['temperature'] == 35
    assert out['power_on_hours'] == 8765
    # Total_LBAs_Written: LBAs × tamaño de bloque lógico (512 por defecto)
    assert out['write_bytes'] == 12000 * 512
    assert out['read_bytes'] == 8000 * 512


def test_parse_hdd_smart_minimal():
    out = wrapper()._parse_smart_json(load_json('hdd_smart.json'))
    assert out['device_type'] == 'ata'
    assert out['temperature'] == 29
    assert out['power_on_hours'] == 22000
    assert out['read_bytes'] is None and out['write_bytes'] is None


def test_ata_normalized_fields_packed_raw_and_unit_names():
    data = {
        "model_name": "ST2000DM008", "smart_status": {"passed": True},
        "rotation_rate": 7200, "logical_block_size": 4096,
        "power_cycle_count": 900,
        "ata_smart_attributes": {"table": [
            {"id": 9, "name": "Power_On_Hours", "raw": {"value": (77 << 32) | 12000}},
            {"id": 190, "name": "Airflow_Temperature_Cel", "raw": {"value": 99}},
            {"id": 194, "name": "Temperature_Celsius", "raw": {"value": 0x0014002D0024}},
            {"id": 241, "name": "Total_LBAs_Written", "raw": {"value": 1000}},
            {"id": 5, "name": "Reallocated_Sector_Ct", "value": 100, "raw": {"value": 8}},
            {"id": 197, "name": "Current_Pending_Sector", "raw": {"value": 2}, "when_failed": ""},
        ]},
    }
    out = wrapper()._parse_smart_json(data)
    assert out['device_type'] == 'hdd' and out['media_label'] == 'HDD'
    assert out['temperature'] == 36          # 0x24 del raw empaquetado; 190 ignorado
    assert out['power_on_hours'] == 12000     # bits altos de Seagate descartados
    assert out['power_cycles'] == 900
    assert out['write_bytes'] == 1000 * 4096
    assert out['reallocated_sectors'] == 8 and out['pending_sectors'] == 2
    assert set(out['critical_attributes']) == {5, 197}

    data = {"model_name": "x", "temperature": {"current": 41}, "power_on_time": {"hours": 5},
            "ata_smart_attributes": {"table": [
                {"id": 194, "name": "Temperature_Celsius", "raw": {"value": 0x0014002D0024}},
                {"id": 241, "name": "Host_Writes_32MiB", "raw": {"value": 3}},
                {"id": 242, "name": "Host_Reads_GiB", "raw": {"value": 2}}]}}
    out = wrapper()._parse_smart_json(data)
    assert out['temperature'] == 41 and out['power_on_hours'] == 5
    assert out['write_bytes'] == 3 * 32 * 1024 ** 2 and out['read_bytes'] == 2 * 1024 ** 3


def test_samsung_860_is_not_millions_of_tb():
    data = {"model_name": "Samsung SSD 860 EVO 500GB", "smart_status": {"passed": True},
            "ata_smart_attributes": {"table": [
                {"id": 241, "name": "Total_LBAs_Written", "raw": {"value": 40_000_000_000}}]}}
    out = wrapper()._parse_smart_json(data)
    assert out['write_bytes'] / 1024 ** 4 == pytest.approx(18.6, abs=0.1)


def test_missing_smart_status_is_unknown_not_failed():
    out = wrapper()._parse_smart_json({"model_name": "USB bridge", "ata_smart_attributes": {"table": []}})
    assert out['smart_status'] is None


def test_returncode_bitmask_parses_failing_disks():
    payload = json.dumps({"model_name": "Disco", "smart_status": {"passed": False},
                          "ata_smart_attributes": {"table": []}})
    query = wrapper().interpret_output("/dev/sda", 8 | 64, payload)
    assert query.ok and query.data["smart_status"] is False
    assert query.data["smart_flags"]["failing"] and query.data["smart_flags"]["error_log"]
    assert not query.data["smart_flags"]["selftest_errors"]
    assert wrapper().interpret_output("/dev/sda", 4 | 128, payload).data["smart_flags"]["selftest_errors"]
    assert wrapper().interpret_output("/dev/sda", 1, payload).error == "cmdline"
    assert decode_smart_flags(16 | 32) == {"command_failed": False, "failing": False, "prefail_threshold": True,
                                           "past_threshold": True, "error_log": False, "selftest_errors": False}


def test_admin_detection_reads_json_messages_on_stdout():
    payload = json.dumps({"smartctl": {"messages": [
        {"string": "Smartctl open device: /dev/sda failed: Access denied", "severity": "error"}]}})
    query = wrapper().interpret_output("/dev/sda", 2, payload, stderr="")
    assert query.admin_required and query.messages
    other = json.dumps({"smartctl": {"messages": [{"string": "No such device", "severity": "error"}]}})
    assert wrapper().interpret_output("/dev/sdz", 2, other).error == "open_failed"


def test_scan_output_windows_formats_keep_device_type():
    output = """/dev/sda -d ata # /dev/sda, ATA device
/dev/sdb -d sat # /dev/sdb [SAT], ATA device
/dev/nvme0 -d nvme # /dev/nvme0, NVMe device
/dev/csmi0,1 -d ata # /dev/csmi0,1, ATA device
/dev/pd3 -d scsi # /dev/pd3, SCSI device
# comentario
"""
    disks = parse_scan_output(output)
    assert [(d["device"], d["type"], d["physical_index"]) for d in disks] == [
        ("/dev/sda", "ata", 0), ("/dev/sdb", "sat", 1), ("/dev/nvme0", "nvme", None),
        ("/dev/csmi0,1", "ata", None), ("/dev/pd3", "scsi", 3)]
    assert disks[0]["physical_drive"] == "PHYSICALDRIVE0" and disks[2]["physical_drive"] is None


def test_subprocess_uses_utf8_no_window_and_registered_for_shutdown(monkeypatch):
    calls = {}

    class FakeProcess:
        returncode = 0

        def __init__(self, args, **kwargs):
            calls.update(kwargs, args=args)
            self.killed = False

        def communicate(self, timeout=None):
            return json.dumps({"model_name": "X", "temperature": {"current": 30}}), ""

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    monkeypatch.setattr(module.subprocess, "Popen", FakeProcess)
    smart = wrapper()
    data = smart.get_disk_smart_data("PHYSICALDRIVE2", device_type="nvme")
    assert data["temperature"] == 30
    assert calls["args"][-3:] == ["-d", "nvme", "/dev/pd2"]
    assert calls["encoding"] == "utf-8" and calls["errors"] == "replace"
    assert "creationflags" in calls

    live = FakeProcess([])
    smart._processes.add(live)
    smart.shutdown()
    assert live.killed and not smart.is_available()
    assert smart.query("PHYSICALDRIVE0").error == "unavailable"


def test_timeout_kills_process(monkeypatch):
    killed = []

    class SlowProcess:
        returncode = None

        def __init__(self, *a, **k):
            self.calls = 0

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("smartctl", timeout)
            return "", ""

        def kill(self):
            killed.append(True)

    monkeypatch.setattr(module.subprocess, "Popen", SlowProcess)
    query = wrapper().query("/dev/sda", timeout=1, max_retries=0)
    assert query.error == "timeout" and killed


def test_find_smartctl_uses_which_not_where(monkeypatch, tmp_path):
    monkeypatch.setattr(module.Path, "is_file", lambda self: False)
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/sbin/" + name)
    run = MagicMock()
    monkeypatch.setattr(module.subprocess, "run", run)
    assert SmartctlWrapper().smartctl_path.startswith("/usr/sbin/smartctl")
    run.assert_not_called()


def test_elevated_command_is_safe_and_reads_json(monkeypatch, tmp_path):
    smart = wrapper(r"C:\App\bin\smartctl.exe")
    command, outputs = smart.build_elevated_command([("PHYSICALDRIVE0", "nvme"), ("/dev/sdb", None)], str(tmp_path))
    assert "-d nvme /dev/pd0" in command and "/dev/sdb" in command and len(outputs) == 2
    with pytest.raises(ValueError):
        smart.build_elevated_command([("/dev/sda & del C:\\", None)], str(tmp_path))
    with pytest.raises(ValueError):
        smart.build_elevated_command([("/dev/sda", "ata & calc")], str(tmp_path))

    monkeypatch.setattr(module.sys, "platform", "win32")

    def fake_elevated(executable, parameters, timeout):
        for path in smart_outputs.values():
            Path(path).write_text(json.dumps({"model_name": "M", "smart_status": {"passed": True},
                                              "smartctl": {"exit_status": 0}}), encoding="utf-8")
        return True

    smart_outputs = {}
    original = smart.build_elevated_command

    def capture(targets, output_dir):
        result = original(targets, output_dir)
        smart_outputs.update(result[1])
        return result

    monkeypatch.setattr(smart, "build_elevated_command", capture)
    monkeypatch.setattr(module, "_shell_execute_elevated", fake_elevated)
    results = smart.query_elevated([("PHYSICALDRIVE0", None)])
    assert results["/dev/pd0"].ok and results["/dev/pd0"].data["smart_status"] is True
    monkeypatch.setattr(module, "_shell_execute_elevated", lambda *a: False)
    assert smart.query_elevated([("PHYSICALDRIVE0", None)])["/dev/pd0"].error == "cancelled"


def test_is_user_admin_uses_shell32(monkeypatch):
    import ctypes
    monkeypatch.setattr(module.sys, "platform", "win32")
    fake = SimpleNamespace(shell32=SimpleNamespace(IsUserAnAdmin=lambda: 1))
    monkeypatch.setattr(ctypes, "windll", fake, raising=False)
    assert module.is_user_admin() is True
