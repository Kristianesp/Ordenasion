import faulthandler
import sys

import pytest

from src.utils import startup_diagnostics as diag


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDENASION_DATA_DIR", str(tmp_path))
    hook = sys.excepthook
    saved = dict(diag._state)
    diag._state.update({"t0": None, "hang": None, "crash": None, "done": False,
                        "previous_crash": None, "error_shown": False})
    yield tmp_path / "logs"
    diag.shutdown()
    faulthandler.disable()
    sys.excepthook = hook
    diag._state.clear()
    diag._state.update(saved)


def test_clean_session_leaves_no_marker_and_no_crash_notice(fresh):
    diag.begin()
    assert (fresh / diag.SESSION_MARKER).exists()
    assert diag._state["previous_crash"] is None
    diag.shutdown()
    assert not (fresh / diag.SESSION_MARKER).exists()
    assert not (fresh / diag.CRASH_FILE).exists()  # vacío: se borra al salir


def test_abrupt_end_is_detected_on_next_start_with_details(fresh):
    fresh.mkdir(parents=True)
    (fresh / diag.SESSION_MARKER).write_text("4.0.1", encoding="utf-8")
    (fresh / diag.CRASH_FILE).write_text("Windows fatal exception: access violation\n", encoding="utf-8")
    diag.begin()
    assert "access violation" in diag._state["previous_crash"]["details"]
    # El informe anterior se conserva para poder enviarlo
    assert "access violation" in (fresh / "fallo-grave-anterior.txt").read_text(encoding="utf-8")


def test_uncaught_exception_is_logged_and_reported_once(fresh, monkeypatch, caplog):
    shown = []
    monkeypatch.setattr(diag, "_call_on_gui_thread", lambda callback, delay_ms=0: shown.append(callback))
    monkeypatch.delenv("ORDENASION_E2E", raising=False)
    monkeypatch.delenv("ORDENASION_SMOKE", raising=False)
    diag.begin()
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: None)
    for _ in range(2):
        try:
            raise ValueError("fallo de prueba")
        except ValueError:
            sys.excepthook(*sys.exc_info())
    assert len(shown) == 1
    # El manejador de archivo es único por proceso: se comprueba el registro en sí
    records = [r for r in caplog.records if r.getMessage() == "Excepción no capturada"]
    assert len(records) == 2 and "fallo de prueba" in str(records[0].exc_info[1])
