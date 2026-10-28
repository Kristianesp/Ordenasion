import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication

import src.gui.music_duplicates_lookup_dialogs as lookup_dialogs_module
import src.gui.music_duplicates_view as music_view_module


class _FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)


class _FakeAudioOutput:
    def __init__(self, *args, **kwargs):
        self._volume = 0.0
        self._muted = False
        self._device = None

    def setVolume(self, value):
        self._volume = float(value)

    def volume(self):
        return self._volume

    def setMuted(self, value):
        self._muted = bool(value)

    def setDevice(self, value):
        self._device = value


class _FakeMediaPlayer:
    class PitchCompensationAvailability:
        AlwaysOn = 0
        Available = 1
        Unavailable = 2

    class PlaybackState:
        StoppedState = 0
        PlayingState = 1
        PausedState = 2

    def __init__(self, *args, **kwargs):
        self.positionChanged = _FakeSignal()
        self.durationChanged = _FakeSignal()
        self.playbackStateChanged = _FakeSignal()
        self._audio_output = None
        self._source = QUrl()
        self._position = 0
        self._state = self.PlaybackState.StoppedState
        self._playback_rate = 1.0
        self._pitch_compensation = True
        self._pitch_compensation_availability = (
            self.PitchCompensationAvailability.Available
        )

    def setAudioOutput(self, output):
        self._audio_output = output

    def setSource(self, source):
        self._source = source

    def source(self):
        return self._source

    def audioOutput(self):
        return self._audio_output

    def play(self):
        self._state = self.PlaybackState.PlayingState

    def pause(self):
        self._state = self.PlaybackState.PausedState

    def stop(self):
        self._state = self.PlaybackState.StoppedState

    def playbackState(self):
        return self._state

    def position(self):
        return self._position

    def setPosition(self, value):
        self._position = int(value)

    def setPlaybackRate(self, value):
        self._playback_rate = float(value)

    def playbackRate(self):
        return self._playback_rate

    def setPitchCompensation(self, value):
        self._pitch_compensation = bool(value)

    def pitchCompensation(self):
        return self._pitch_compensation

    def pitchCompensationAvailability(self):
        return self._pitch_compensation_availability


def _app():
    app = QApplication.instance()
    return app or QApplication([])


def _install_fake_media(monkeypatch):
    monkeypatch.setattr(music_view_module, "QAudioOutput", _FakeAudioOutput)
    monkeypatch.setattr(music_view_module, "QMediaPlayer", _FakeMediaPlayer)
    monkeypatch.setattr(
        "src.gui.music_duplicates_library_panel_logic.QMediaDevices.defaultAudioOutput",
        lambda: object(),
    )
    monkeypatch.setattr(
        "src.utils.app_config.AppConfig.get_music_last_folder",
        lambda self: "",
    )
    monkeypatch.setattr(
        "src.utils.app_config.AppConfig.get_music_recursive",
        lambda self: True,
    )
    monkeypatch.setattr(
        "src.utils.app_config.AppConfig.get_music_preview_playback_rate",
        lambda self: 1.0,
    )
    monkeypatch.setattr(
        "src.utils.app_config.AppConfig.set_music_preview_playback_rate",
        lambda self, rate: True,
    )


def test_library_detail_shows_cache_badge(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    app = _app()
    file_path = tmp_path / "track.mp3"
    file_path.write_bytes(b"demo")
    track = {
        "file_path": str(file_path),
        "title": "Track",
        "artist": "Artist",
        "album": "Album",
        "duration": 12,
        "review_status": "",
    }

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "list_tracks",
        lambda limit=1000: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_metadata",
        lambda path: dict(track),
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )

    view = music_view_module.MusicDuplicatesView()
    view._lookup_results_by_path[str(file_path)] = {
        "file_path": str(file_path),
        "source": "musicbrainz",
        "confidence": 220,
        "candidate_count": 1,
        "cache_status": "cached",
        "cache_updated_at": "2026-04-13T14:50:00",
        "suggested_updates": {"title": "Track", "artist": "Artist", "album": "Album"},
        "candidates": [
            {
                "suggested_updates": {
                    "title": "Track",
                    "artist": "Artist",
                    "album": "Album",
                }
            }
        ],
    }

    view.refresh_library()
    view.library_table.selectRow(0)
    view._update_library_detail_panel()

    assert view.library_cache_badge.text() == "cache reutilizada"
    assert (
        "Cache actualizada: 2026-04-13T14:50:00"
        in view.library_detail_text.toPlainText()
    )

    view.deleteLater()
    app.processEvents()


def test_library_side_controls_use_accessible_layout(monkeypatch):
    _install_fake_media(monkeypatch)
    app = _app()

    view = music_view_module.MusicDuplicatesView()

    assert view.library_volume_title.text() == "Volumen"
    assert view.library_volume_label.text() == "75%"
    assert (
        view.library_volume_slider.orientation()
        == music_view_module.Qt.Orientation.Horizontal
    )
    assert view.library_pitch_title.text() == "Pitch DJ"
    assert view.library_pitch_label.text() == "1.00x"
    assert (
        view.library_pitch_slider.orientation()
        == music_view_module.Qt.Orientation.Horizontal
    )
    assert view.library_refresh_cache_btn.text() == "Refrescar cache"
    assert view.library_clear_cache_btn.text() == "Limpiar cache"
    assert view.library_cover_choice_btn.text() == "Elegir portada"
    assert view.library_diagnostics_btn.text() == "Ver diagnostico"
    from src.gui.v2.theme import typography_scale
    from src.utils.app_config import AppConfig
    expected = typography_scale(AppConfig()).control_height
    assert view.library_refresh_cache_btn.minimumHeight() == expected
    assert view.library_cover_choice_btn.minimumHeight() == expected

    view.deleteLater()
    app.processEvents()


def test_library_pitch_slider_updates_playback_rate(monkeypatch):
    _install_fake_media(monkeypatch)
    app = _app()

    view = music_view_module.MusicDuplicatesView()
    view.library_pitch_slider.setValue(125)

    assert round(view.audio_player.playbackRate(), 2) == 1.25
    assert view.audio_player.pitchCompensation() is False
    assert view.library_pitch_label.text() == "1.25x"

    view.deleteLater()
    app.processEvents()


def test_library_play_rebinds_audio_output_and_volume(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    app = _app()
    file_path = tmp_path / "track.mp3"
    file_path.write_bytes(b"demo")
    track = {
        "file_path": str(file_path),
        "title": "Track",
        "artist": "Artist",
        "album": "Album",
        "duration": 12,
        "review_status": "",
    }

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "list_tracks",
        lambda limit=1000: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_metadata",
        lambda path: dict(track),
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )

    view = music_view_module.MusicDuplicatesView()
    view.refresh_library()
    view.library_table.selectRow(0)
    view.audio_player.setAudioOutput(None)
    view.audio_output.setMuted(True)
    view.library_volume_slider.setValue(35)

    view.play_selected_library_track()

    assert view.audio_player.audioOutput() is view.audio_output
    assert round(view.audio_output.volume(), 2) == 0.35
    assert view.audio_output._muted is False
    assert view.library_volume_label.text() == "35%"
    assert Path(view.audio_player.source().toLocalFile()) == file_path

    view.deleteLater()
    app.processEvents()


def test_library_seek_stays_enabled_for_same_selected_track(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    app = _app()
    file_path = tmp_path / "track.mp3"
    file_path.write_bytes(b"demo")
    track = {
        "file_path": str(file_path),
        "title": "Track",
        "artist": "Artist",
        "album": "Album",
        "duration": 12,
        "review_status": "",
    }

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "list_tracks",
        lambda limit=1000: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_metadata",
        lambda path: dict(track),
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )

    view = music_view_module.MusicDuplicatesView()
    view.refresh_library()
    view.library_table.selectRow(0)
    view.play_selected_library_track()

    view.library_seek_slider.setEnabled(False)
    view._audio_context = "library"
    view.audio_player.setSource(QUrl.fromLocalFile(str(file_path)))
    view._update_library_detail_panel()

    assert view.library_seek_slider.isEnabled() is True
    assert view.library_seek_slider.maximum() == 12000

    view.deleteLater()
    app.processEvents()


def test_library_checked_rows_drive_batch_selection(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    app = _app()
    first = tmp_path / "one.mp3"
    second = tmp_path / "two.mp3"
    first.write_bytes(b"1")
    second.write_bytes(b"2")
    tracks = [
        {
            "file_path": str(first),
            "title": "One",
            "artist": "A",
            "album": "X",
            "duration": 5,
            "review_status": "",
        },
        {
            "file_path": str(second),
            "title": "Two",
            "artist": "B",
            "album": "Y",
            "duration": 6,
            "review_status": "",
        },
    ]

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "list_tracks",
        lambda limit=1000: [dict(item) for item in tracks],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [dict(item) for item in tracks],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_metadata",
        lambda path: next(
            dict(item) for item in tracks if item["file_path"] == str(Path(path))
        ),
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )

    view = music_view_module.MusicDuplicatesView()
    view.refresh_library()
    checkbox_item = view.library_table.item(1, view.LIBRARY_SELECT_COLUMN)
    assert checkbox_item is not None
    checkbox_item.setCheckState(music_view_module.Qt.CheckState.Checked)

    assert view._selected_file_paths() == [str(second)]

    view.deleteLater()
    app.processEvents()


def test_duplicates_table_marks_best_copy(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    app = _app()

    monkeypatch.setattr(
        music_view_module.audio_metadata_service, "list_tracks", lambda limit=1000: []
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service, "get_metadata", lambda path: {}
    )

    best = tmp_path / "best.mp3"
    other = tmp_path / "other.mp3"
    best.write_bytes(b"best")
    other.write_bytes(b"other")

    view = music_view_module.MusicDuplicatesView()
    view.results = {
        "group-1": [
            {
                "file_path": str(best),
                "title": "Best",
                "artist": "Artist",
                "album": "Album",
                "duration": 3,
                "codec": "mp3",
                "bitrate": 192000,
                "quality_score": 95,
                "file_size": 3000,
            },
            {
                "file_path": str(other),
                "title": "Other",
                "artist": "Artist",
                "album": "Album",
                "duration": 3,
                "codec": "mp3",
                "bitrate": 128000,
                "quality_score": 70,
                "file_size": 2000,
            },
        ]
    }

    view._refresh_results()

    decision_values = []
    for row in range(view.duplicates_table.rowCount()):
        item = view.duplicates_table.item(row, 0)
        assert item is not None
        decision_values.append(item.text())
    assert any(value.startswith("⭐") for value in decision_values)
    assert "Ahorro potencial" in view.best_duplicate_hint.text()
    assert view.duplicates_table.rowCount() == 2

    view.duplicates_table.selectRow(1)
    view._select_best_duplicate()
    selected_decisions = {
        view.duplicates_table.item(index.row(), 0).text()
        for index in view.duplicates_table.selectedIndexes()
        if view.duplicates_table.item(index.row(), 0) is not None
    }
    assert any(value.startswith("⭐") for value in selected_decisions)

    keep_row = next(
        row
        for row in range(view.duplicates_table.rowCount())
        if view.duplicates_table.item(row, 1) is not None
        and view.duplicates_table.item(row, 1).text() == "other.mp3"
    )
    view.duplicates_table.selectRow(keep_row)
    view._mark_selected_duplicate_as_keep()

    decision_values_after_keep = [
        view.duplicates_table.item(row, 0).text()
        for row in range(view.duplicates_table.rowCount())
        if view.duplicates_table.item(row, 0) is not None
    ]
    assert any(value == "⭐ Conservar" for value in decision_values_after_keep)
    assert any(
        view.duplicates_table.item(row, 1).text() == "other.mp3"
        and view.duplicates_table.item(row, 0).text() == "⭐ Conservar"
        for row in range(view.duplicates_table.rowCount())
        if view.duplicates_table.item(row, 1) is not None
        and view.duplicates_table.item(row, 0) is not None
    )

    view.deleteLater()
    app.processEvents()


def test_library_reset_view_restores_default_layout(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    app = _app()
    file_path = tmp_path / "track.mp3"
    file_path.write_bytes(b"demo")
    track = {
        "file_path": str(file_path),
        "title": "Track",
        "artist": "Artist",
        "album": "Album",
        "duration": 12,
        "review_status": "",
    }

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "list_tracks",
        lambda limit=1000: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_metadata",
        lambda path: dict(track),
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )

    view = music_view_module.MusicDuplicatesView()
    header = view.library_table.horizontalHeader()
    assert header is not None

    header.moveSection(header.visualIndex(1), 0)
    view.library_table.setColumnHidden(12, True)
    view.library_splitter.setSizes([650, 520])
    recorded_sizes = []
    original_set_sizes = view.library_splitter.setSizes

    def _record_sizes(values):
        recorded_sizes.append(list(values))
        original_set_sizes(values)

    monkeypatch.setattr(view.library_splitter, "setSizes", _record_sizes)

    view._reset_table_layout()

    assert header.visualIndex(0) == 0
    assert header.visualIndex(2) == 1
    assert view.library_table.isColumnHidden(12) is False
    assert view.library_table.isColumnHidden(14) is True
    assert recorded_sizes[-1] == view.LIBRARY_SPLITTER_DEFAULT_SIZES

    view.deleteLater()
    app.processEvents()


def test_lookup_finished_auto_applies_high_confidence_multi_candidate(
    monkeypatch, tmp_path
):
    _install_fake_media(monkeypatch)
    app = _app()
    file_path = tmp_path / "track.mp3"
    file_path.write_bytes(b"demo")
    track = {
        "file_path": str(file_path),
        "title": "The Only",
        "artist": "Static-X",
        "album": "",
        "duration": 12,
        "review_status": "",
    }

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "list_tracks",
        lambda limit=1000: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_metadata",
        lambda path: dict(track),
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )

    applied_calls = []

    def _fake_update_tags(path, updates, cover_art=None):
        applied_calls.append((str(path), dict(updates), cover_art))
        return True

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "update_track_tags",
        _fake_update_tags,
    )

    view = music_view_module.MusicDuplicatesView()
    view.show()
    app.processEvents()
    result = {
        "file_path": str(file_path),
        "local_metadata": dict(track),
        "source": "musicbrainz",
        "confidence": 247,
        "selected_candidate_index": 0,
        "suggested_updates": {
            "title": "The Only",
            "artist": "Static-X",
            "album": "Shadow Zone",
            "year": "2003",
        },
        "candidates": [
            {
                "source": "musicbrainz",
                "confidence": 247,
                "suggested_updates": {
                    "title": "The Only",
                    "artist": "Static-X",
                    "album": "Shadow Zone",
                    "year": "2003",
                },
            },
            {
                "source": "musicbrainz",
                "confidence": 246,
                "suggested_updates": {
                    "title": "The Only",
                    "artist": "Static X",
                    "album": "Cannibal Killers Live",
                    "year": "2008",
                },
            },
        ],
    }
    view._lookup_results_by_path[str(file_path)] = dict(result)

    prompted = []
    monkeypatch.setattr(
        view,
        "_prompt_variant_choice",
        lambda *args, **kwargs: prompted.append((args, kwargs)) or 0,
    )

    view._on_lookup_finished(0, [str(file_path)])

    assert prompted == []
    assert len(applied_calls) == 1
    assert applied_calls[0][1]["album"] == "Shadow Zone"
    assert "Se ha seleccionado automaticamente" in view.lookup_status_label.text()
    assert view.music_toast_frame.isVisible() is True
    assert "Se ha seleccionado automaticamente" in view.music_toast_label.text()
    assert view.music_toast_frame.pos().x() > 0

    view.deleteLater()
    app.processEvents()


def test_library_states_and_lookup_actions(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    app = _app()
    paths = []
    tracks = []
    statuses = ["", "", "applied", "complete", "no_match"]
    titles = ["Pending", "Variant", "Applied", "Complete", "Rejected"]
    for index, title in enumerate(titles, start=1):
        file_path = tmp_path / f"track_{index}.mp3"
        file_path.write_bytes(b"demo")
        paths.append(file_path)
        tracks.append(
            {
                "file_path": str(file_path),
                "title": title,
                "artist": "Artist",
                "album": "" if index == 1 else "Album",
                "duration": 12,
                "review_status": statuses[index - 1],
            }
        )

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "list_tracks",
        lambda limit=1000: [dict(item) for item in tracks],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [dict(item) for item in tracks],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_metadata",
        lambda path: next(
            dict(item) for item in tracks if item["file_path"] == str(Path(path))
        ),
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )

    view = music_view_module.MusicDuplicatesView()
    view._lookup_results_by_path[str(paths[1])] = {
        "file_path": str(paths[1]),
        "selected_candidate_index": 0,
        "suggested_updates": {"title": "Variant", "artist": "Artist"},
        "candidates": [
            {
                "confidence": 220,
                "suggested_updates": {"title": "Variant", "artist": "Artist"},
            },
            {
                "confidence": 180,
                "suggested_updates": {"title": "Variant Live", "artist": "Artist"},
            },
        ],
        "cover_choices": [
            {"url": "https://img/one.jpg", "label": "One", "source": "musicbrainz"},
            {"url": "https://img/two.jpg", "label": "Two", "source": "discogs"},
        ],
    }
    view._lookup_results_by_path[str(paths[2])] = {
        "file_path": str(paths[2]),
        "selected_candidate_index": 0,
        "applied_candidate_index": 0,
        "suggested_updates": {"title": "Applied", "artist": "Artist"},
        "candidates": [
            {
                "confidence": 225,
                "suggested_updates": {"title": "Applied", "artist": "Artist"},
            }
        ],
    }

    view.refresh_library()
    states = [
        view.library_table.item(row, 2).text()
        for row in range(view.library_table.rowCount())
        if view.library_table.item(row, 2) is not None
    ]
    assert "pendiente" in states
    assert "variante elegida" in states
    assert "aplicada" in states
    assert "completa" in states
    assert "no coincide" in states

    variant_row = next(
        row
        for row in range(view.library_table.rowCount())
        if view.library_table.item(row, 1) is not None
        and view.library_table.item(row, 1).text() == paths[1].name
    )
    view.library_table.selectRow(variant_row)
    view._update_library_detail_panel()
    assert view.library_cover_choice_btn.isEnabled() is True
    assert view.library_diagnostics_btn.isEnabled() is True

    cover_calls = []
    monkeypatch.setattr(
        music_view_module,
        "prompt_cover_choice",
        lambda *args, **kwargs: cover_calls.append((args, kwargs)) or True,
    )
    diagnostics_calls = []
    monkeypatch.setattr(
        music_view_module,
        "show_lookup_diagnostics_dialog",
        lambda *args, **kwargs: diagnostics_calls.append((args, kwargs)) or None,
    )

    view.choose_selected_track_cover()
    view.show_selected_track_diagnostics()

    assert len(cover_calls) == 1
    assert len(diagnostics_calls) == 1

    view.deleteLater()
    app.processEvents()


def test_cover_choice_persists_across_refresh_and_panel_preview(monkeypatch, tmp_path):
    _install_fake_media(monkeypatch)
    app = _app()
    file_path = tmp_path / "track.mp3"
    file_path.write_bytes(b"demo")
    track = {
        "file_path": str(file_path),
        "title": "Track",
        "artist": "Artist",
        "album": "Album",
        "duration": 12,
        "review_status": "",
    }

    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "list_tracks",
        lambda limit=1000: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "find_missing_metadata",
        lambda limit=200: [dict(track)],
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_metadata",
        lambda path: dict(track),
    )
    monkeypatch.setattr(
        music_view_module.audio_metadata_service,
        "get_cover_art_bytes",
        lambda path: None,
    )
    monkeypatch.setattr(
        lookup_dialogs_module.audio_fingerprint_service,
        "get_cover_art_bytes_for_url",
        lambda url: b"cover-two" if url.endswith("two.jpg") else None,
    )
    embedded_cover_calls = []
    monkeypatch.setattr(
        lookup_dialogs_module.audio_metadata_service,
        "update_track_tags",
        lambda path, updates, cover_art=None: (
            embedded_cover_calls.append((str(path), dict(updates), cover_art)) or True
        ),
    )

    preview_requests = []

    def _fake_cover_preview(path, result):
        preview_requests.append(dict(result))
        return None

    monkeypatch.setattr(
        music_view_module.audio_fingerprint_service,
        "get_cover_art_bytes_for_result",
        _fake_cover_preview,
    )

    def _accept_second_choice(dialog):
        choices_list = dialog.findChild(lookup_dialogs_module.QListWidget)
        assert choices_list is not None
        choices_list.setCurrentRow(1)
        return lookup_dialogs_module.QDialog.DialogCode.Accepted

    monkeypatch.setattr(
        lookup_dialogs_module.QDialog,
        "exec",
        _accept_second_choice,
        raising=False,
    )

    view = music_view_module.MusicDuplicatesView()
    view._lookup_results_by_path[str(file_path)] = {
        "file_path": str(file_path),
        "cache_key": "track-cache",
        "source": "musicbrainz",
        "selected_candidate_index": 0,
        "suggested_updates": {"title": "Track", "artist": "Artist"},
        "cover_url": "https://img/one.jpg",
        "thumb_url": "https://img/one.jpg",
        "cover_choices": [
            {"url": "https://img/one.jpg", "label": "One", "source": "musicbrainz"},
            {"url": "https://img/two.jpg", "label": "Two", "source": "discogs"},
        ],
        "candidates": [
            {
                "confidence": 220,
                "suggested_updates": {"title": "Track", "artist": "Artist"},
                "cover_url": "https://img/one.jpg",
                "thumb_url": "https://img/one.jpg",
            }
        ],
    }

    view.refresh_library()
    view.library_table.selectRow(0)

    assert lookup_dialogs_module.prompt_cover_choice(view, str(file_path)) is True

    chosen = view._get_lookup_result(str(file_path))
    assert chosen["selected_cover_url"] == "https://img/two.jpg"
    assert chosen["cover_url"] == "https://img/two.jpg"
    assert chosen["thumb_url"] == "https://img/two.jpg"
    assert embedded_cover_calls[-1][2] == b"cover-two"

    view._store_lookup_result(
        str(file_path),
        {
            "file_path": str(file_path),
            "cache_key": "track-cache",
            "source": "musicbrainz",
            "cover_url": "https://img/one.jpg",
            "thumb_url": "https://img/one.jpg",
            "cover_choices": [
                {"url": "https://img/one.jpg", "label": "One", "source": "musicbrainz"},
                {"url": "https://img/two.jpg", "label": "Two", "source": "discogs"},
            ],
            "candidates": [
                {
                    "confidence": 220,
                    "suggested_updates": {"title": "Track", "artist": "Artist"},
                    "cover_url": "https://img/one.jpg",
                    "thumb_url": "https://img/one.jpg",
                }
            ],
        },
        persist=False,
    )

    preview_requests.clear()
    view.library_table.selectRow(0)
    view._update_library_detail_panel()

    assert preview_requests
    assert preview_requests[-1]["selected_cover_url"] == "https://img/two.jpg"
    assert preview_requests[-1]["cover_url"] == "https://img/two.jpg"

    view.deleteLater()
    app.processEvents()
