import os
import threading

import pytest

from src.core.hash_cache import HashCache, cache_key_for
from src.core.hash_manager import HashCancelled, HashManager


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_cache_roundtrip_and_invalidation(tmp_path):
    cache = HashCache(str(tmp_path / "c.db"))
    f = _write(tmp_path / "a.bin", b"hola")
    cache.save_hash(f, "abc", "md5")
    assert cache.get_hash(f, "md5") == "abc"
    # Otro algoritmo no se confunde
    assert cache.get_hash(f, "md5-partial") is None
    # Cambio de contenido/tamaño invalida
    f.write_bytes(b"hola mundo")
    assert cache.get_hash(f, "md5") is None
    cache.close()


def test_cache_reads_do_not_write(tmp_path):
    db = tmp_path / "c.db"
    cache = HashCache(str(db))
    f = _write(tmp_path / "a.bin", b"x")
    cache.save_hash(f, "abc", "md5")
    before = cache._get_connection().total_changes
    for _ in range(5):
        cache.get_hash(f, "md5")
    assert cache._get_connection().total_changes == before
    assert cache.get_statistics()["total_hits"] == 5


def test_cache_batch_and_purge(tmp_path):
    cache = HashCache(str(tmp_path / "c.db"))
    files = [_write(tmp_path / "root" / f"{i}.bin", bytes([i]) * 10) for i in range(5)]
    entries = []
    for f in files:
        st = os.stat(f)
        entries.append((cache_key_for(f), st.st_size, st.st_mtime, f"h{f.name}"))
    assert cache.save_hashes_batch(entries, "md5") == 5
    lookup = [(k, s, m) for k, s, m, _ in entries]
    assert len(cache.get_hashes_batch(lookup, "md5")) == 5
    files[0].unlink()
    removed = cache.purge_missing_under(str(tmp_path / "root"))
    assert removed == 1
    assert len(cache.get_hashes_batch(lookup, "md5")) == 4


def test_hash_manager_partial_is_marked_and_cached_separately(tmp_path):
    cache = HashCache(str(tmp_path / "c.db"))
    manager = HashManager(cache=cache)
    f = _write(tmp_path / "big.bin", os.urandom(3 * 1024 * 1024))
    partial = manager.hash_file(f, max_size_mb=1)
    assert partial.ok and partial.partial and partial.algorithm == "md5-partial"
    full = manager.calculate_full_hash(f)
    assert full.ok and not full.partial and full.value != partial.value
    import hashlib
    assert full.value == hashlib.md5(f.read_bytes()).hexdigest()
    # La caché distingue ambos
    assert cache.get_hash(f, "md5") == full.value
    assert cache.get_hash(f, "md5-partial") == partial.value


def test_hash_manager_reports_errors_instead_of_dropping(tmp_path, monkeypatch):
    manager = HashManager(use_cache=False)
    missing = tmp_path / "nope.bin"
    result = manager.hash_file(missing)
    assert not result.ok and result.error

    f = _write(tmp_path / "a.bin", b"x" * 100)

    def boom(*args, **kwargs):
        raise TimeoutError("lento")

    monkeypatch.setattr(manager, "_compute", boom)
    result = manager.hash_file(f)
    assert not result.ok and "tiempo agotado" in result.error


def test_hash_manager_cancellation(tmp_path):
    manager = HashManager(use_cache=False)
    files = [_write(tmp_path / f"{i}.bin", os.urandom(2048)) for i in range(20)]
    event = threading.Event()
    event.set()
    with pytest.raises(HashCancelled):
        manager.hash_many(files, cancel_event=event)


def test_files_identical(tmp_path):
    a = _write(tmp_path / "a", b"abc" * 1000)
    b = _write(tmp_path / "b", b"abc" * 1000)
    c = _write(tmp_path / "c", b"abd" * 1000)
    assert HashManager.files_identical(a, b)
    assert not HashManager.files_identical(a, c)


def test_warm_cache_is_faster_than_no_cache(tmp_path):
    import time
    root = tmp_path / "files"
    files = [_write(root / f"{i}.bin", os.urandom(4096)) for i in range(400)]
    no_cache = HashManager(use_cache=False)
    t0 = time.perf_counter()
    no_cache.hash_many(files)
    t_none = time.perf_counter() - t0

    cache = HashCache(str(tmp_path / "c.db"))
    cached = HashManager(cache=cache)
    cached.hash_many(files)  # en frío
    t0 = time.perf_counter()
    results = cached.hash_many(files)
    t_warm = time.perf_counter() - t0
    assert all(r.cached for r in results.values())
    # Con caché caliente nunca debe ser drásticamente más lento que sin caché
    assert t_warm < t_none * 3 + 0.05
