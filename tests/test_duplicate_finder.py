import os
import threading

import pytest

from src.core.duplicate_finder import (
    DuplicateFinder,
    ScanCancelled,
    is_excluded_relative,
    normalize_filename,
)
from src.core.hash_cache import HashCache
from src.core.hash_manager import HashManager


def _finder(tmp_path, cancel_event=None):
    cache = HashCache(str(tmp_path / "cache.db"))
    return DuplicateFinder(HashManager(cache=cache), cancel_event=cancel_event)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_hybrid_confirms_by_content_and_uses_hash_keys(tmp_path):
    root = tmp_path / "root"
    a = _write(root / "a" / "IMG_0001.JPG", b"A" * 5000)
    b = _write(root / "b" / "IMG_0001.JPG", b"A" * 5000)
    # mismo nombre y tamaño pero contenido distinto: NO es duplicado
    _write(root / "c" / "IMG_0002.JPG", b"B" * 5000)
    _write(root / "d" / "IMG_0002.JPG", b"C" * 5000)
    finder = _finder(tmp_path)
    groups = finder.scan(str(root), method="hybrid")
    assert len(groups) == 1
    key, paths = next(iter(groups.items()))
    assert set(paths) == {a, b}
    import hashlib
    assert key == hashlib.md5(b"A" * 5000).hexdigest()
    assert finder.group_meta[key].confirmed


def test_fast_mode_marks_groups_unconfirmed(tmp_path):
    root = tmp_path / "root"
    _write(root / "x" / "foto.jpg", b"1" * 100)
    _write(root / "y" / "foto (1).jpg", b"2" * 100)
    finder = _finder(tmp_path)
    groups = finder.scan(str(root), method="fast")
    assert len(groups) == 1
    meta = next(iter(finder.group_meta.values()))
    assert meta.confirmed is False
    assert finder.get_statistics()["confirmed"] is False


def test_deep_groups_by_content_regardless_of_name(tmp_path):
    root = tmp_path / "root"
    _write(root / "uno.txt", b"igual" * 30000)
    _write(root / "dos.dat", b"igual" * 30000)
    _write(root / "tres.dat", b"igual" * 29999 + b"xxxxx")
    finder = _finder(tmp_path)
    groups = finder.scan(str(root), method="deep")
    assert len(groups) == 1
    assert {p.name for p in next(iter(groups.values()))} == {"uno.txt", "dos.dat"}


def test_quarantine_and_hidden_folders_are_excluded(tmp_path):
    root = tmp_path / "root"
    original = _write(root / "doc.pdf", b"P" * 2000)
    _write(root / ".quarantine" / "doc.pdf", b"P" * 2000)
    _write(root / ".duplicates_quarantine" / "doc.pdf", b"P" * 2000)
    _write(root / "$RECYCLE.BIN" / "S-1" / "doc.pdf", b"P" * 2000)
    _write(root / "sub" / ".oculta" / "doc.pdf", b"P" * 2000)
    finder = _finder(tmp_path)
    assert finder.scan(str(root), method="deep") == {}
    assert finder.files_scanned == 1
    assert is_excluded_relative(root / ".quarantine" / "doc.pdf", root)
    assert not is_excluded_relative(original, root)


def test_scan_root_inside_hidden_folder_still_works(tmp_path):
    root = tmp_path / ".config" / "datos"
    _write(root / "a.bin", b"Z" * 300)
    _write(root / "b.bin", b"Z" * 300)
    finder = _finder(tmp_path)
    assert len(finder.scan(str(root), method="deep")) == 1


def test_system_folder_filter_is_component_based(tmp_path, monkeypatch):
    import src.core.duplicate_finder as module

    root = tmp_path / "root"
    system_dir = root / "Windows"
    # Una carpeta del usuario que contiene "windows" no debe excluirse
    _write(root / "Backup Windows" / "a.bin", b"W" * 400)
    _write(root / "Backup Windows" / "b.bin", b"W" * 400)
    _write(system_dir / "c.bin", b"W" * 400)
    monkeypatch.setattr(module, "SYSTEM_DIRS", {os.path.normcase(str(system_dir))})
    finder = _finder(tmp_path)
    groups = finder.scan(str(root), method="deep")
    names = {p.name for paths in groups.values() for p in paths}
    assert names == {"a.bin", "b.bin"}


@pytest.mark.skipif(not hasattr(os, "link"), reason="sin hardlinks")
def test_hardlinks_are_not_duplicates(tmp_path):
    root = tmp_path / "root"
    a = _write(root / "a.bin", b"H" * 1000)
    try:
        os.link(a, root / "a_link.bin")
    except OSError:
        pytest.skip("el sistema de archivos no admite hardlinks")
    finder = _finder(tmp_path)
    assert finder.scan(str(root), method="deep") == {}
    assert finder.hardlinks_skipped == 1
    assert finder.calculate_space_saved() == 0


def test_large_files_use_partial_hash_flag(tmp_path):
    root = tmp_path / "root"
    data = os.urandom(2 * 1024 * 1024)
    _write(root / "v1.mkv", data)
    _write(root / "v2.mkv", data)
    finder = _finder(tmp_path)
    finder.hash_manager.partial_threshold_mb = 1
    groups = finder.scan(str(root), method="deep")
    assert len(groups) == 1
    key = next(iter(groups))
    assert key.startswith("md5-partial:")
    meta = finder.group_meta[key]
    assert meta.partial and not meta.confirmed


def test_cancellation_stops_scan(tmp_path):
    root = tmp_path / "root"
    for i in range(30):
        _write(root / f"{i}.bin", b"x" * 100)
    event = threading.Event()
    event.set()
    finder = _finder(tmp_path, cancel_event=event)
    with pytest.raises(ScanCancelled):
        finder.scan(str(root), method="deep")


def test_unreadable_files_are_reported(tmp_path, monkeypatch):
    root = tmp_path / "root"
    _write(root / "a.bin", b"q" * 200000)
    _write(root / "b.bin", b"q" * 200000)
    finder = _finder(tmp_path)

    def boom(*args, **kwargs):
        raise PermissionError(13, "Permiso denegado")

    monkeypatch.setattr(finder.hash_manager, "_compute", boom)
    assert finder.scan(str(root), method="deep") == {}
    assert finder.errors and "Permiso" in finder.errors[0][1]


def test_warm_cache_scan_matches_and_is_used(tmp_path):
    root = tmp_path / "root"
    for i in range(10):
        _write(root / f"a{i}.bin", bytes([i]) * 70000)
        _write(root / f"b{i}.bin", bytes([i]) * 70000)
    finder = _finder(tmp_path)
    first = finder.scan(str(root), method="deep")
    second = finder.scan(str(root), method="deep")
    assert {k: set(v) for k, v in first.items()} == {k: set(v) for k, v in second.items()}
    assert len(second) == 10


def test_normalize_filename():
    assert normalize_filename("document (1)") == "document"
    assert normalize_filename("foto - copia") == "foto"
    assert normalize_filename("normal") == "normal"
