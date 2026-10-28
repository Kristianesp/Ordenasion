"""Registro de transacciones JSONL, historial y deshacer persistente."""

import json
import os
import time
from pathlib import Path

from src.core.transaction_manager import (
    ROLE_OVERWRITE_BACKUP,
    STATUS_CANCELLED,
    OperationType,
    TransactionManager,
)


def _organize_one(manager, root, name="a.txt", folder="DOCS"):
    source = root / name
    source.write_text("contenido", encoding="utf-8")
    txn = manager.begin_transaction("prueba", source_folder=str(root))
    destination = root / folder / name
    manager.ensure_directory(destination.parent)
    assert manager.safe_move_file(source, destination)
    manager.end_transaction()
    return txn, source, destination


def test_undo_works_after_restart_and_removes_created_dirs(tmp_path):
    log = tmp_path / "ops.jsonl"
    root = tmp_path / "root"
    root.mkdir()
    manager = TransactionManager(str(log))
    txn, source, destination = _organize_one(manager, root, folder="DOCS/2026/10")
    assert manager.last_transaction_id == txn

    restarted = TransactionManager(str(log))
    assert restarted.last_transaction_id == txn
    assert restarted.rollback_transaction(txn)
    assert source.read_text(encoding="utf-8") == "contenido"
    # Las carpetas creadas por la transacción se eliminan si quedan vacías
    assert not (root / "DOCS").exists()

    # Un segundo intento no repite nada
    again = TransactionManager(str(log))
    assert again.last_transaction_id is None
    assert not again.rollback_transaction(txn)
    assert again.last_rollback_result["already_reverted"]
    assert again.get_transactions()[0]["undo_state"] == "deshecha"


def test_rollback_never_overwrites_occupied_source(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    manager = TransactionManager(str(tmp_path / "ops.jsonl"))
    txn, source, destination = _organize_one(manager, root)
    source.write_text("nuevo archivo del usuario", encoding="utf-8")

    assert manager.rollback_transaction(txn)
    assert source.read_text(encoding="utf-8") == "nuevo archivo del usuario"
    restored = root / "a (1).txt"
    assert restored.read_text(encoding="utf-8") == "contenido"
    assert manager.last_rollback_result["renamed"]


def test_overwrite_backup_is_restored_on_rollback(tmp_path):
    root = tmp_path / "root"
    (root / "DOCS").mkdir(parents=True)
    existing = root / "DOCS" / "a.txt"
    existing.write_text("original", encoding="utf-8")
    source = root / "a.txt"
    source.write_text("nuevo", encoding="utf-8")
    manager = TransactionManager(str(tmp_path / "ops.jsonl"))
    txn = manager.begin_transaction("sobrescribir")
    backup = root / "DOCS" / ".a.overwrite.txt"
    assert manager.safe_move_file(existing, backup, role=ROLE_OVERWRITE_BACKUP)
    assert manager.safe_move_file(source, existing)
    manager.end_transaction()

    assert manager.rollback_transaction(txn)
    assert existing.read_text(encoding="utf-8") == "original"
    assert source.read_text(encoding="utf-8") == "nuevo"
    assert not backup.exists()


def test_overwrite_backups_can_be_sent_to_trash(tmp_path, monkeypatch):
    import sys
    import types

    trashed = []
    monkeypatch.setitem(sys.modules, "send2trash", types.SimpleNamespace(send2trash=trashed.append))
    root = tmp_path / "root"
    root.mkdir()
    existing = root / "a.txt"
    existing.write_text("original", encoding="utf-8")
    manager = TransactionManager(str(tmp_path / "ops.jsonl"))
    txn = manager.begin_transaction("sobrescribir")
    backup = root / ".a.overwrite.txt"
    assert manager.safe_move_file(existing, backup, role=ROLE_OVERWRITE_BACKUP)
    manager.end_transaction()
    assert manager.discard_overwrite_backups(txn) == 1
    assert trashed == [str(backup)]


def test_safe_move_refuses_to_overwrite(tmp_path):
    manager = TransactionManager(str(tmp_path / "ops.jsonl"))
    source = tmp_path / "a.txt"
    source.write_text("a", encoding="utf-8")
    target = tmp_path / "b.txt"
    target.write_text("b", encoding="utf-8")
    assert not manager.safe_move_file(source, target)
    assert target.read_text(encoding="utf-8") == "b"
    assert source.exists()


def test_multi_undo_of_any_past_transaction(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    manager = TransactionManager(str(tmp_path / "ops.jsonl"))
    first, first_source, _ = _organize_one(manager, root, "uno.txt", "A")
    second, second_source, second_dest = _organize_one(manager, root, "dos.txt", "B")

    history = manager.get_transactions()
    assert [entry["id"] for entry in history] == [second, first]
    assert all(entry["can_undo"] for entry in history)
    assert history[0]["moves"] == 1 and history[0]["source_folder"] == str(root)

    assert manager.rollback_transaction(first)
    assert first_source.exists()
    assert second_dest.exists()  # la otra transacción no se toca
    assert manager.last_transaction_id == second


def test_cancelled_status_is_persisted(tmp_path):
    log = tmp_path / "ops.jsonl"
    root = tmp_path / "root"
    root.mkdir()
    manager = TransactionManager(str(log))
    source = root / "x.txt"
    source.write_text("x", encoding="utf-8")
    manager.begin_transaction("parcial")
    assert manager.safe_move_file(source, root / "X" / "x.txt")
    manager.end_transaction(STATUS_CANCELLED, {"files_moved": 1})
    assert TransactionManager(str(log)).get_transactions()[0]["status"] == STATUS_CANCELLED


def test_legacy_json_log_is_migrated(tmp_path):
    root = tmp_path / "root"
    (root / "DOCS").mkdir(parents=True)
    moved = root / "DOCS" / "a.txt"
    moved.write_text("a", encoding="utf-8")
    legacy = tmp_path / "operations_log.json"
    legacy.write_text(
        json.dumps(
            {
                "operations": [
                    {"type": "transaction_begin", "transaction_id": "txn_old", "description": "antigua", "timestamp": "2025-01-01T10:00:00"},
                    {"type": "move", "transaction_id": "txn_old", "timestamp": "2025-01-01T10:00:01",
                     "details": {"source": str(root / "a.txt"), "destination": str(moved), "size": 1}},
                    {"type": "transaction_commit", "transaction_id": "txn_old", "timestamp": "2025-01-01T10:00:02"},
                ]
            }
        ),
        encoding="utf-8",
    )
    manager = TransactionManager(str(legacy))
    assert manager.log_file.suffix == ".jsonl" and manager.log_file.exists()
    assert manager.last_transaction_id == "txn_old"
    assert manager.rollback_transaction("txn_old")
    assert (root / "a.txt").exists()
    assert not TransactionManager(str(legacy)).get_transactions()[0]["can_undo"]


def test_log_append_is_linear_for_100k_operations(tmp_path):
    log = tmp_path / "ops.jsonl"
    manager = TransactionManager(str(log))
    started = time.perf_counter()
    manager.begin_transaction("masiva")
    for index in range(100_000):
        manager._log_operation(
            OperationType.MOVE,
            {"source": f"/a/{index}", "destination": f"/b/{index}", "size": 1},
        )
    manager.end_transaction()
    elapsed = time.perf_counter() - started
    assert elapsed < 15, f"El registro tardó {elapsed:.1f}s"
    with open(log, encoding="utf-8") as handle:
        assert sum(1 for _ in handle) == 100_002
    reloaded = TransactionManager(str(log))
    assert reloaded.get_transactions()[0]["moves"] == 100_000


def test_truncated_last_line_is_ignored(tmp_path):
    log = tmp_path / "ops.jsonl"
    root = tmp_path / "root"
    root.mkdir()
    manager = TransactionManager(str(log))
    txn, _, _ = _organize_one(manager, root)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write('{"type": "move", "transac')
    assert TransactionManager(str(log)).last_transaction_id == txn
