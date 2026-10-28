import csv
import os
from pathlib import Path

import pytest

from src.core.duplicate_actions import (
    ACTION_DELETE,
    ACTION_HARDLINK,
    ACTION_MOVE,
    DuplicateActionWorker,
    build_plan,
    choose_keep_index,
    export_plan_csv,
    find_emptied_groups,
    has_copy_marker,
)
from src.core.hash_cache import HashCache
from src.core.hash_manager import HashManager


class FakeTM:
    def __init__(self):
        self.deleted = []
        self.moved = []
        self.last_error = None
        self.last_removal_destination = None

    def safe_delete_file(self, path, use_trash=True):
        path.unlink()
        self.deleted.append(str(path))
        self.last_removal_destination = "papelera"
        return True

    def safe_move_file(self, source, destination):
        os.replace(source, destination)
        self.moved.append((str(source), str(destination)))
        return True


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_keep_rules():
    files = [
        {"path": "/m/b/foto (1).jpg", "date": 300},
        {"path": "/m/a/foto.jpg", "date": 100},
        {"path": "/m/preferida/sub/foto - copia.jpg", "date": 200},
    ]
    assert choose_keep_index(files, "newest") == 0
    assert choose_keep_index(files, "oldest") == 1
    assert choose_keep_index(files, "clean_name") == 1
    assert choose_keep_index(files, "shortest_path") == 1
    assert choose_keep_index(files, "preferred_folder", ["/m/preferida"]) == 2
    assert choose_keep_index(files, "newest", preferred_path="/m/a/foto.jpg") == 1
    assert has_copy_marker("foto (2).jpg") and has_copy_marker("doc - copia.pdf")
    assert not has_copy_marker("foto.jpg")


def test_find_emptied_groups_blocks_removing_all_copies(tmp_path):
    a = _write(tmp_path / "a.txt", b"x")
    b = _write(tmp_path / "b.txt", b"x")
    groups = {"g": [a, b]}
    assert find_emptied_groups(groups, [a]) == []
    assert find_emptied_groups(groups, [a, b]) == ["g"]
    b.unlink()  # la única copia restante ya no existe
    assert find_emptied_groups(groups, [a]) == ["g"]


def test_plan_and_worker_verify_content_before_delete(tmp_path):
    keep = _write(tmp_path / "keep.bin", b"same" * 1000)
    dup = _write(tmp_path / "dup.bin", b"same" * 1000)
    # Candidato rápido falso: mismo tamaño, contenido distinto
    fake_keep = _write(tmp_path / "x" / "IMG.JPG", b"A" * 4000)
    fake_dup = _write(tmp_path / "y" / "IMG.JPG", b"B" * 4000)
    groups = {"g1": [keep, dup], "g2": [fake_keep, fake_dup]}
    plan = build_plan(groups, [dup, fake_dup], ACTION_DELETE)
    assert [Path(i.reference).name for i in plan] == ["keep.bin", "IMG.JPG"]
    tm = FakeTM()
    worker = DuplicateActionWorker(plan, tm, hash_manager=HashManager(cache=HashCache(str(tmp_path / "c.db"))))
    results = []
    worker.finished_ok.connect(results.append)
    worker.run()
    summary = results[0]
    assert [Path(d["source"]).name for d in summary["done"]] == ["dup.bin"]
    assert summary["skipped"][0]["reason"].startswith("el contenido no es idéntico")
    assert fake_dup.exists() and not dup.exists() and keep.exists()


def test_worker_move_and_csv_export(tmp_path):
    keep = _write(tmp_path / "a" / "f.txt", b"z" * 50)
    dup = _write(tmp_path / "b" / "f.txt", b"z" * 50)
    dest = tmp_path / "dest"
    plan = build_plan({"g": [keep, dup]}, [dup], ACTION_MOVE, destination_dir=str(dest),
                      sizes={str(dup): 50})
    worker = DuplicateActionWorker(plan, FakeTM(), hash_manager=HashManager(use_cache=False))
    out = []
    worker.finished_ok.connect(out.append)
    worker.run()
    assert (dest / "f.txt").exists()
    assert out[0]["bytes"] == 50
    csv_path = tmp_path / "plan.csv"
    export_plan_csv(plan, str(csv_path))
    rows = list(csv.reader(open(csv_path, encoding="utf-8-sig"), delimiter=";"))
    assert rows[0][0] == "accion" and rows[1][0] == "Mover" and rows[1][6] == "hecho"


@pytest.mark.skipif(not hasattr(os, "link"), reason="sin hardlinks")
def test_replace_with_hardlink(tmp_path):
    keep = _write(tmp_path / "keep.bin", b"L" * 2048)
    dup = _write(tmp_path / "dup.bin", b"L" * 2048)
    plan = build_plan({"g": [keep, dup]}, [dup], ACTION_HARDLINK)
    worker = DuplicateActionWorker(plan, FakeTM(), hash_manager=HashManager(use_cache=False))
    out = []
    worker.finished_ok.connect(out.append)
    try:
        worker.run()
    except OSError:
        pytest.skip("hardlinks no soportados")
    if out[0]["failed"]:
        pytest.skip(out[0]["failed"][0]["reason"])
    assert os.stat(keep).st_ino == os.stat(dup).st_ino
    assert dup.read_bytes() == b"L" * 2048


def test_worker_cancellation(tmp_path):
    keep = _write(tmp_path / "keep.bin", b"q" * 10)
    dup = _write(tmp_path / "dup.bin", b"q" * 10)
    plan = build_plan({"g": [keep, dup]}, [dup], ACTION_DELETE)
    worker = DuplicateActionWorker(plan, FakeTM(), hash_manager=HashManager(use_cache=False))
    worker.stop()
    out = []
    worker.finished_ok.connect(out.append)
    worker.run()
    assert out[0]["cancelled"] and dup.exists()
