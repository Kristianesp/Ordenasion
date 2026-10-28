from types import SimpleNamespace

import pytest

from src.core.health_service import HealthService, health_level
from src.utils.app_config import AppConfig

TB = 1024 ** 4


@pytest.fixture
def service(tmp_path):
    return HealthService(AppConfig(str(tmp_path / "config.json")))


def disk(total=TB):
    return SimpleNamespace(total_size=total)


def test_levels_are_centralized():
    assert health_level(None).key == "unknown"
    assert [health_level(score).key for score in (95, 90, 80, 60, 59, 40, 39, 0)] == [
        "excellent", "excellent", "healthy", "attention", "warning", "warning", "critical", "critical"]


def test_hdd_without_tbw_attributes_still_gets_health(service):
    result = service.calculate_health({"device_type": "hdd", "temperature": 35, "power_on_hours": 5000,
                                       "power_cycles": 300, "smart_status": True}, disk())
    assert result.score is not None and result.score >= 90
    assert result.tbw_score is None


def test_pending_sectors_and_failing_bits_cap_score(service):
    base = {"device_type": "hdd", "temperature": 35, "power_on_hours": 5000, "power_cycles": 300,
            "smart_status": True}
    pending = service.calculate_health({**base, "pending_sectors": 3}, disk())
    assert pending.score <= 45 and pending.level.key in {"warning", "critical"} and pending.alerts
    failing = service.calculate_health({**base, "smart_flags": {"failing": True}}, disk())
    assert failing.level.key == "critical"
    failed = service.calculate_health({**base, "smart_status": False}, disk())
    assert failed.level.key == "critical"


def test_unknown_smart_status_is_not_failure(service):
    result = service.calculate_health({"device_type": "ata", "temperature": 30, "smart_status": None}, disk())
    assert result.score >= 90


def test_tbw_counts_only_writes(service):
    data = {"device_type": "ata", "read_bytes": 10_000 * TB, "write_bytes": 1 * TB}
    result = service.calculate_health(data, disk())
    assert result.tbw_score == 100 and result.tbw["write_tb"] == 1.0


def test_nvme_uses_percentage_used(service):
    result = service.calculate_health({"device_type": "nvme", "health_percentage": 20, "temperature": 40}, disk())
    assert result.wear_score == 20
    assert result.score < 75


def test_no_data_means_unknown(service):
    result = service.calculate_health({"device_type": "ata"}, disk())
    assert result.score is None and not result.available and result.level.key == "unknown"
