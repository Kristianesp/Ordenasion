"""Inicio y Discos muestran el mismo porcentaje y el donut dibuja bien lo ocupado."""

import math
from collections import namedtuple
from types import SimpleNamespace

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

from src.core import disk_manager as dm
from src.gui.task_center import task_registry
from src.gui.v2.dashboard_charts import RESERVED_LABEL, DiskUsageChart, usage_percent_of
from src.gui.v2.pages.home_page import HomePage
from src.gui.v2.theme import current_tokens
from src.utils.app_config import AppConfig

APP = None
GB = 1024 ** 3
Partition = namedtuple("Partition", "device mountpoint fstype opts")
Usage = namedtuple("Usage", "total used free percent")


@pytest.fixture
def config(tmp_path):
    global APP
    APP = QApplication.instance() or QApplication([])
    return AppConfig(str(tmp_path / "config.json"))


def test_home_and_disks_share_the_same_percent(tmp_path, monkeypatch, config):
    # ext4 con bloques reservados: psutil.percent (used / (used + free)) ≠ used / total.
    monkeypatch.setattr(dm.psutil, "disk_partitions", lambda all=False: [Partition("/dev/a", "/", "ext4", "rw")])
    monkeypatch.setattr(dm.psutil, "disk_usage", lambda mp: Usage(100 * GB, 20 * GB, 75 * GB, 21.1))
    manager = dm.DiskManager(config, history=None)
    manager.history = None
    disk = manager.get_all_disks()[0]
    assert disk.usage_percent == 20.0
    monkeypatch.setattr(task_registry, "_tasks", {})
    home = HomePage(config, SimpleNamespace())
    home.update_dashboard([disk], None, selected_mountpoint="/")
    assert home.disk_metric.value_label.text() == f"{disk.usage_percent:.1f}%"
    assert usage_percent_of(disk) == disk.usage_percent
    assert RESERVED_LABEL in home.usage_chart.accessibleDescription()
    home.close()


def test_home_follows_the_drive_selected_in_disks(config, monkeypatch):
    monkeypatch.setattr(task_registry, "_tasks", {})
    home = HomePage(config, SimpleNamespace())
    disks = [SimpleNamespace(mountpoint=m, total_size=100, used_size=u, free_size=100 - u, usage_percent=float(u))
             for m, u in (("C:\\", 30), ("D:\\", 60))]
    home.update_dashboard(disks, None, selected_mountpoint="C:\\")
    assert home.drive_selector.currentData() == "C:\\"
    home.update_dashboard(disks, None, selected_mountpoint="D:\\")
    assert home.drive_selector.currentData() == "D:\\" and home.disk_metric.value_label.text() == "60.0%"
    home.drive_selector.setCurrentIndex(0)  # elección local en Inicio
    home.update_dashboard(disks, None, selected_mountpoint="D:\\")
    assert home.drive_selector.currentData() == "C:\\"
    home.close()


def test_empty_space_message_is_not_repeated(config, monkeypatch):
    monkeypatch.setattr(task_registry, "_tasks", {})
    home = HomePage(config, SimpleNamespace())
    home.resize(1200, 900)
    home.show()
    APP.processEvents()
    visible_texts = [label.text() for label in (home.space_path_label, home.space_snapshot_label) if label.isVisible()]
    assert not any("Sin análisis de espacio" in text for text in visible_texts)
    assert not any("Analiza una carpeta" in text for text in visible_texts)
    home.close()


def test_small_used_segment_is_drawn_with_flat_caps(config):
    chart = DiskUsageChart(config)
    chart.resize(420, 170)
    chart.set_disk(SimpleNamespace(total_size=1000, used_size=40, free_size=960))
    image = chart.grab().toImage()
    diameter = min(140, chart.height() - 24, chart.width() * 0.38)
    stroke = max(10, diameter * 0.13)
    radius = (diameter - stroke) / 2
    center_x, center_y = 9 + diameter / 2, (chart.height() - diameter) / 2 + diameter / 2
    tokens = current_tokens(config.get_accent_color(), config.get_theme_mode())

    def color_at(degrees):
        angle = math.radians(degrees)
        pixel = image.pixelColor(round(center_x + radius * math.cos(angle)), round(center_y - radius * math.sin(angle)))
        return pixel

    def close(pixel, expected):
        target = QColor(expected)
        return abs(pixel.red() - target.red()) + abs(pixel.green() - target.green()) + abs(pixel.blue() - target.blue()) < 60

    # 4 % ocupado = 14,4°: justo a la derecha de las 12 es "ocupado", más allá "libre".
    assert close(color_at(90 - 7), tokens.accent)
    assert close(color_at(90 - 40), tokens.success)
