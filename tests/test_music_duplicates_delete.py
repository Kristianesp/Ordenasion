import src.gui.music_duplicates_view as music_view_module
from tests.test_music_duplicates_view_gui import _app, _install_fake_media


def _music_view_with_group(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    for name, value in (("list_tracks", lambda limit=1000: []),
                        ("find_missing_metadata", lambda limit=200: []),
                        ("get_cover_art_bytes", lambda path: None),
                        ("get_metadata", lambda path: {})):
        monkeypatch.setattr(music_view_module.audio_metadata_service, name, value)
    best = tmp_path / "best.flac"
    other = tmp_path / "other.mp3"
    best.write_bytes(b"best")
    other.write_bytes(b"other")
    view = music_view_module.MusicDuplicatesView()
    view.results = {
        "meta:g:0": [
            {"file_path": str(best), "title": "S", "artist": "A", "quality_score": 9, "file_size": 4},
            {"file_path": str(other), "title": "S", "artist": "A", "quality_score": 1, "file_size": 5},
        ]
    }
    view._refresh_results()
    return view, best, other


def _no_question(*args, **kwargs):
    raise AssertionError("no debe pedir confirmación")


def test_music_delete_blocks_removing_every_copy(monkeypatch, tmp_path):
    app = _app()
    view, best, other = _music_view_with_group(monkeypatch, tmp_path)
    warnings = []
    monkeypatch.setattr(music_view_module.QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a[2]))
    monkeypatch.setattr(music_view_module.QMessageBox, "question", _no_question)
    view.duplicates_table.selectAll()
    view.delete_selected_duplicates()
    assert warnings and "todas las copias" in warnings[0]
    assert best.exists() and other.exists()
    view.deleteLater()
    app.processEvents()


def test_music_delete_reports_failure_reasons(monkeypatch, tmp_path):
    app = _app()
    view, best, other = _music_view_with_group(monkeypatch, tmp_path)

    class FailingTM:
        last_error = "send2trash: acceso denegado"
        last_removal_destination = None

        def safe_delete_file(self, path, use_trash=True):
            return False

    view.transaction_manager = FailingTM()
    warnings = []
    monkeypatch.setattr(music_view_module.QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a[2]))
    monkeypatch.setattr(music_view_module.QMessageBox, "question",
                        lambda *a, **k: music_view_module.QMessageBox.StandardButton.Yes)
    for row in range(view.duplicates_table.rowCount()):
        if view.duplicates_table.item(row, 1).text() == "other.mp3":
            view.duplicates_table.selectRow(row)
    view.delete_selected_duplicates()
    view._delete_worker.wait(5000)
    app.processEvents()
    assert warnings and "acceso denegado" in warnings[-1]
    assert other.exists()
    view.deleteLater()
    app.processEvents()
