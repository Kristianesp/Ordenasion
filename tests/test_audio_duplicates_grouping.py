import os
import threading

import pytest

from src.core.audio_duplicates import AudioDuplicateFinder
from src.core.audio_index import AudioMetadata, AudioMetadataService
from src.core.hash_cache import HashCache
from src.core.hash_manager import HashManager


def _meta(path, **kw):
    base = dict(file_path=str(path), file_size=1000, duration=200.0, title="Song",
                artist="Artist", album="Album", codec="mp3")
    base.update(kw)
    return AudioMetadata(**base)


def _finder(tmp_path):
    return AudioDuplicateFinder(use_chromaprint=False,
                                hash_manager=HashManager(cache=HashCache(str(tmp_path / "c.db"))))


def test_untagged_or_broken_tracks_are_not_grouped_by_empty_metadata(tmp_path):
    finder = _finder(tmp_path)
    files = []
    for i in range(3):
        p = tmp_path / f"cancion_distinta_{i}.mp3"
        p.write_bytes(os.urandom(3000))
        files.append(p)
    metas = [_meta(p, title="", artist="", album="", duration=None,
                   error="can't sync to MPEG frame", file_size=3000) for p in files]
    assert finder.scan_folder(str(tmp_path), metadata=metas) == {}


def test_identical_broken_files_group_by_content(tmp_path):
    finder = _finder(tmp_path)
    data = os.urandom(4000)
    a, b = tmp_path / "a.mp3", tmp_path / "b.mp3"
    a.write_bytes(data)
    b.write_bytes(data)
    metas = [_meta(p, title="", artist="", error="corrupto", duration=None, file_size=4000)
             for p in (a, b)]
    groups = finder.scan_folder(str(tmp_path), metadata=metas)
    assert len(groups) == 1
    key, items = next(iter(groups.items()))
    assert key.startswith("md5:") and items[0]["match_basis"] == "contenido"


def test_title_and_artist_required_for_metadata_identity(tmp_path):
    finder = _finder(tmp_path)
    (tmp_path / "x.mp3").write_bytes(b"1" * 10)
    (tmp_path / "y.mp3").write_bytes(b"2" * 10)
    metas = [_meta(tmp_path / "x.mp3", artist="", file_size=10),
             _meta(tmp_path / "y.mp3", artist="", file_size=10)]
    assert finder.scan_folder(str(tmp_path), metadata=metas) == {}


def test_duration_tolerance_instead_of_rounding(tmp_path):
    finder = _finder(tmp_path)
    metas = [
        _meta(tmp_path / "a.mp3", duration=200.04),
        _meta(tmp_path / "b.flac", duration=201.9, codec="flac", lossless=True),
        _meta(tmp_path / "c.mp3", duration=230.0),  # otra versión (remix)
    ]
    groups = finder.scan_folder(str(tmp_path), metadata=metas)
    assert len(groups) == 1
    items = next(iter(groups.values()))
    assert {os.path.basename(i["file_path"]) for i in items} == {"a.mp3", "b.flac"}
    assert items[0]["file_path"].endswith("b.flac")  # la mejor calidad primero
    assert items[0]["match_basis"] == "metadatos"


def test_chromaprint_used_for_untagged_readable_tracks(tmp_path, monkeypatch):
    finder = AudioDuplicateFinder(use_chromaprint=True, hash_manager=HashManager(use_cache=False))
    metas = [_meta(tmp_path / "1.mp3", title="", artist=""),
             _meta(tmp_path / "2.mp3", title="", artist="", duration=201)]
    monkeypatch.setattr(finder, "_chromaprint",
                        lambda meta: {"fingerprint": "AQAAxyz", "duration": meta.duration})
    groups = finder.scan_folder(str(tmp_path), metadata=metas)
    assert len(groups) == 1 and next(iter(groups)).startswith("chromaprint:")


def test_index_folder_detailed_skips_unchanged_and_hidden(tmp_path, monkeypatch):
    service = AudioMetadataService(str(tmp_path / "media.db"))
    music = tmp_path / "music"
    (music / ".quarantine").mkdir(parents=True)
    (music / "a.mp3").write_bytes(b"x" * 100)
    (music / ".quarantine" / "a.mp3").write_bytes(b"x" * 100)
    calls = []
    original = service.extract_metadata
    monkeypatch.setattr(service, "extract_metadata", lambda p: calls.append(p) or original(p))
    first = service.index_folder_detailed(music)
    assert [os.path.basename(m.file_path) for m in first] == ["a.mp3"]
    second = service.index_folder_detailed(music)
    assert len(calls) == 1 and len(second) == 1


def test_scan_folder_cancellation(tmp_path):
    from src.core.duplicate_finder import ScanCancelled

    event = threading.Event()
    event.set()
    (tmp_path / "a.mp3").write_bytes(b"1")
    with pytest.raises(ScanCancelled):
        _finder(tmp_path).scan_folder(str(tmp_path), cancel_event=event)


def test_list_tracks_without_silent_limit(tmp_path):
    service = AudioMetadataService(str(tmp_path / "media.db"))
    service.upsert_many(
        AudioMetadata(file_path=str(tmp_path / f"{i}.mp3"), file_size=1, mtime=1.0, extension=".mp3")
        for i in range(1205)
    )
    assert len(service.list_tracks(limit=None)) == 1205
    assert len(service.list_tracks(limit=10)) == 10
