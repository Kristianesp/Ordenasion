from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

import src.gui.duplicates_actions_ui as actions_module
from src.core.duplicate_finder import DuplicateFinder
from src.core.hash_cache import HashCache
from src.core.hash_manager import HashManager


_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _dashboard(monkeypatch, tmp_path):
    from src.gui.duplicates_dashboard import DuplicatesDashboard

    from PyQt6.QtCore import QSettings

    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr("src.gui.duplicates_dashboard.QSettings",
                        lambda *a, **k: QSettings(ini, QSettings.Format.IniFormat))
    return DuplicatesDashboard()


def _load_scan(dashboard, root, tmp_path, method="hybrid"):
    finder = DuplicateFinder(HashManager(cache=HashCache(str(tmp_path / "c.db"))))
    data = finder.scan(str(root), method=method)
    dashboard.current_folder = str(root)
    dashboard.min_size_spin.setValue(0)
    dashboard.on_duplicates_found(data, finder.get_statistics())
    return data


def test_empty_state_before_analysis(monkeypatch, tmp_path):
    _app()
    dashboard = _dashboard(monkeypatch, tmp_path)
    assert not dashboard.summary_frame.isVisibleTo(dashboard)
    assert "Elige una carpeta" in dashboard.empty_state_label.text()
    assert dashboard.method_combo.currentData() == "hybrid"
    assert "Rápido" in dashboard.method_combo.itemText(0)
    dashboard.deleteLater()


def test_cannot_remove_all_copies(monkeypatch, tmp_path):
    _app()
    root = tmp_path / "root"
    _write(root / "a" / "f.bin", b"1" * 3000)
    _write(root / "b" / "f.bin", b"1" * 3000)
    dashboard = _dashboard(monkeypatch, tmp_path)
    _load_scan(dashboard, root, tmp_path)
    assert dashboard.duplicates_model.rowCount() == 2
    warnings = []
    monkeypatch.setattr(actions_module.QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a[2]) or QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(actions_module.QMessageBox, "question",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debe preguntar")))
    for row in range(2):
        dashboard.duplicates_model.setData(dashboard.duplicates_model.index(row, 0),
                                           Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
    dashboard.delete_selected()
    assert warnings and "todas las copias" in warnings[0]
    assert dashboard.action_worker is None
    assert (root / "a" / "f.bin").exists() and (root / "b" / "f.bin").exists()
    dashboard.deleteLater()


def test_fast_mode_delete_confirms_by_hash(monkeypatch, tmp_path):
    app = _app()
    root = tmp_path / "root"
    _write(root / "a" / "IMG_0001.JPG", b"A" * 3000)
    _write(root / "b" / "IMG_0001.JPG", b"B" * 3000)  # mismo nombre y tamaño, distinto contenido
    dashboard = _dashboard(monkeypatch, tmp_path)
    _load_scan(dashboard, root, tmp_path, method="fast")
    assert "sin confirmar" in dashboard.duplicates_model.get_row_data(0)["match_status"].lower()
    dashboard.duplicates_model.check_all_duplicates()
    monkeypatch.setattr(actions_module.QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    infos = []
    monkeypatch.setattr(actions_module.QMessageBox, "information", lambda *a, **k: infos.append(a[2]))

    class TM:
        last_error = None
        last_removal_destination = "papelera"

        def safe_delete_file(self, path, use_trash=True):
            Path(path).unlink()
            return True

    dashboard.transaction_manager = TM()
    dashboard.delete_selected()
    dashboard.action_worker.wait(5000)
    app.processEvents()
    assert (root / "a" / "IMG_0001.JPG").exists() and (root / "b" / "IMG_0001.JPG").exists()
    assert infos and "Omitidos tras verificar: 1" in infos[-1]
    dashboard.deleteLater()


def test_ignore_uses_content_hash(monkeypatch, tmp_path):
    _app()
    root = tmp_path / "root"
    _write(root / "a" / "x.bin", b"Q" * 3000)
    _write(root / "b" / "x.bin", b"Q" * 3000)
    dashboard = _dashboard(monkeypatch, tmp_path)
    data = _load_scan(dashboard, root, tmp_path)
    key = next(iter(data))
    dashboard.duplicates_table.setCurrentIndex(dashboard.duplicates_model.index(0, 1))
    dashboard.ignore_selected_group()
    assert key in dashboard.ignored_hashes
    assert dashboard.duplicates_model.rowCount() == 0
    dashboard.deleteLater()
