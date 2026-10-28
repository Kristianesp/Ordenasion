import gc

from PyQt6.QtWidgets import QApplication

from src.utils import gc_guard

APP = QApplication.instance() or QApplication([])


def test_collector_disables_automatic_gc_and_collects_on_gui_thread(monkeypatch):
    collected = []
    monkeypatch.setattr(gc, "collect", lambda generation=2: collected.append(generation) or 0)
    collector = gc_guard.MainThreadGarbageCollector(interval_ms=10)
    try:
        assert not gc.isenabled()
        threshold = collector.threshold
        monkeypatch.setattr(gc, "get_count", lambda: (threshold[0] + 1, 0, 0))
        collector.check()
        monkeypatch.setattr(gc, "get_count", lambda: (0, 0, threshold[2] + 1))
        collector.check()
        assert collected == [0, 2]
    finally:
        collector.stop()
    assert gc.isenabled()
    gc.disable()  # el conftest mantiene el automático apagado durante los tests


def test_install_is_idempotent():
    first = gc_guard.install(APP)
    try:
        assert gc_guard.install(APP) is first
    finally:
        gc_guard.uninstall()
        gc.disable()
