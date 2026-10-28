"""Regresiones del flujo "Organizar" (análisis, plan, worker y deshacer)."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication

from src.core.category_manager import CategoryManager
from src.core.fs_safety import is_junk_file_name, is_system_path, long_path
from src.core.organization_conflicts import category_to_folder
from src.core.organization_plan import (
    ACTION_INVALID,
    STATUS_CATEGORY_FOLDER,
    build_organization_plan,
)
from src.core.transaction_manager import TransactionManager
from src.core.workers import AnalysisWorker, OrganizeWorker
from src.utils.constants import VARIOS_FOLDER


def _app():
    return QCoreApplication.instance() or QCoreApplication([])


def _manager(tmp_path):
    return CategoryManager(str(tmp_path / "categories.json"))


def _analyze(root, manager, **kwargs):
    result = {}
    worker = AnalysisWorker(
        str(root), manager.get_categories(), manager.ext_to_categoria, 70,
        category_manager=manager, **kwargs,
    )
    worker.analysis_complete.connect(lambda f, fi, s: result.update(folders=f, files=fi))
    worker.run()
    return result, worker


def _organize(root, result, tm, **kwargs):
    worker = OrganizeWorker(str(root), result["folders"], result["files"], transaction_manager=tm, **kwargs)
    worker.run()
    return worker


def _tree(root):
    return sorted(str(p.relative_to(root)).replace("\\", "/") for p in root.rglob("*"))


def test_organize_by_date_creates_nested_folders_and_undo_cleans_them(tmp_path):
    _app()
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.pdf").write_text("a", encoding="utf-8")
    (root / "b.jpg").write_text("b", encoding="utf-8")
    manager = _manager(tmp_path)
    tm = TransactionManager(str(tmp_path / "ops.jsonl"))
    result, _ = _analyze(root, manager)
    worker = _organize(root, result, tm, organize_by_date=True)
    assert worker.summary["status"] == "completado"
    assert worker.summary["files_moved"] == 2
    assert any(path.startswith("DOCUMENTOS/") and path.endswith("/a.pdf") for path in _tree(root))

    # Ventana y worker comparten el gestor: deshacer funciona en la sesión
    assert tm.last_transaction_id == worker.current_transaction_id
    assert tm.rollback_transaction(tm.last_transaction_id)
    assert _tree(root) == ["a.pdf", "b.jpg"]


def test_reanalysis_skips_category_folders_and_single_varios(tmp_path):
    _app()
    root = tmp_path / "root"
    root.mkdir()
    (root / "fotos").mkdir()
    (root / "fotos" / "1.jpg").write_text("1", encoding="utf-8")
    (root / "raro.zzz").write_text("z", encoding="utf-8")
    manager = _manager(tmp_path)
    tm = TransactionManager(str(tmp_path / "ops.jsonl"))
    result, _ = _analyze(root, manager)
    _organize(root, result, tm)
    assert (root / VARIOS_FOLDER / "raro.zzz").exists()
    assert not (root / "VARIOS_REVISAR").exists()
    (root / "imagenes_lower").mkdir()

    second, _ = _analyze(root, manager)
    names = {mov["folder"].name for mov in second["folders"]}
    assert "IMAGENES" not in names and VARIOS_FOLDER not in names
    assert "imagenes_lower" in names


def test_plan_flags_category_folder_and_destination_inside_source(tmp_path):
    root = tmp_path / "root"
    (root / "IMAGENES").mkdir(parents=True)
    plan = build_organization_plan(
        str(root),
        [{"folder": root / "IMAGENES", "category": "IMAGENES", "size": 0}],
        [],
    )
    assert plan.items[0].action == ACTION_INVALID
    assert plan.items[0].status == STATUS_CATEGORY_FOLDER


def test_check_duplicates_skips_identical_with_rename_policy(tmp_path):
    _app()
    root = tmp_path / "root"
    (root / "DOCUMENTOS").mkdir(parents=True)
    (root / "DOCUMENTOS" / "a.pdf").write_bytes(b"igual")
    (root / "a.pdf").write_bytes(b"igual")
    (root / "b.pdf").write_bytes(b"distinto")
    (root / "DOCUMENTOS" / "b.pdf").write_bytes(b"otro")
    manager = _manager(tmp_path)
    tm = TransactionManager(str(tmp_path / "ops.jsonl"))
    result, _ = _analyze(root, manager)
    worker = _organize(root, result, tm, check_duplicates=True, conflict_policy="rename")
    assert worker.summary["skipped_duplicates"] == 1
    assert (root / "a.pdf").exists()
    assert not (root / "DOCUMENTOS" / "a (1).pdf").exists()
    assert (root / "DOCUMENTOS" / "b (1).pdf").read_bytes() == b"distinto"


def test_cancel_reports_cancelled_and_allows_partial_undo(tmp_path):
    _app()
    root = tmp_path / "root"
    root.mkdir()
    for index in range(5):
        (root / f"{index}.txt").write_text(str(index), encoding="utf-8")
    manager = _manager(tmp_path)
    tm = TransactionManager(str(tmp_path / "ops.jsonl"))
    result, _ = _analyze(root, manager)
    worker = OrganizeWorker(str(root), [], result["files"], transaction_manager=tm)
    messages = []
    original_emit_count = {"moved": 0}

    def on_progress(message):
        messages.append(message)
        if message.startswith("📄 Movido"):
            original_emit_count["moved"] += 1
            if original_emit_count["moved"] == 2:
                worker.stop()

    worker.progress_update.connect(on_progress)
    completed = []
    worker.organize_complete.connect(lambda ok, msg: completed.append((ok, msg)))
    worker.run()
    assert worker.summary["status"] == "cancelado"
    assert worker.summary["files_moved"] == 2
    assert worker.summary["pending"] == 3
    assert completed and completed[0][0] is False and "cancelada" in completed[0][1]
    assert tm.get_transactions()[0]["status"] == "cancelado"
    assert tm.rollback_transaction(worker.current_transaction_id)
    assert len(list(root.glob("*.txt"))) == 5


def test_failed_move_reports_completed_with_errors(tmp_path, monkeypatch):
    _app()
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")
    manager = _manager(tmp_path)
    tm = TransactionManager(str(tmp_path / "ops.jsonl"))
    result, _ = _analyze(root, manager)
    original = tm.safe_move_file

    def flaky(source, destination, role=""):
        if Path(source).name == "b.txt":
            tm.last_error = "simulado"
            return False
        return original(source, destination, role=role)

    monkeypatch.setattr(tm, "safe_move_file", flaky)
    worker = _organize(root, result, tm)
    assert worker.summary["status"] == "completado con errores"
    assert worker.summary["failed"] == 1 and worker.summary["files_moved"] == 1
    assert "simulado" in worker.summary["errors"][0]


def test_analysis_stop_really_stops(tmp_path):
    _app()
    root = tmp_path / "root"
    root.mkdir()
    for index in range(3):
        (root / f"{index}.txt").write_text("x", encoding="utf-8")
    manager = _manager(tmp_path)
    worker = AnalysisWorker(str(root), manager.get_categories(), manager.ext_to_categoria, category_manager=manager)
    completed, cancelled = [], []
    worker.analysis_complete.connect(lambda *args: completed.append(args))
    worker.analysis_cancelled.connect(lambda: cancelled.append(True))
    worker.stop()
    worker.run()
    assert not completed and cancelled


def test_junk_system_and_custom_rules(tmp_path):
    _app()
    root = tmp_path / "root"
    root.mkdir()
    for name in ("desktop.ini", "Thumbs.db", "~$informe.docx", ".DS_Store", "factura_2024.xyz"):
        (root / name).write_text("x", encoding="utf-8")
    (root / "Backup Windows").mkdir()
    (root / "Backup Windows" / "a.pdf").write_text("x", encoding="utf-8")
    (root / "$RECYCLE.BIN").mkdir()
    (root / "$RECYCLE.BIN" / "a.pdf").write_text("x", encoding="utf-8")
    manager = _manager(tmp_path)
    manager.add_custom_rule("Facturas", "factura", "DOCUMENTOS", 10)
    result, _ = _analyze(root, manager)
    assert [mov["file"].name for mov in result["files"]] == ["factura_2024.xyz"]
    assert result["files"][0]["category"] == "DOCUMENTOS"  # regla del usuario
    assert "hash" not in result["files"][0]["advanced_info"] or result["files"][0]["advanced_info"]["hash"] is None
    assert [mov["folder"].name for mov in result["folders"]] == ["Backup Windows"]


def test_system_path_checks_are_component_based(tmp_path, monkeypatch):
    assert not is_system_path(r"D:\Backup Windows\fotos", root="D:\\", system_dirs=set())
    assert is_system_path(str(tmp_path / "System Volume Information"), root=str(tmp_path), system_dirs=set())
    sysroot = str(tmp_path / "Windows")
    assert is_system_path(os.path.join(sysroot, "System32"), system_dirs={os.path.normcase(sysroot)})
    assert not is_system_path(str(tmp_path / "Windowsfotos"), system_dirs={os.path.normcase(sysroot)})
    assert is_junk_file_name("~$doc.docx") and is_junk_file_name("Thumbs.db")
    assert not is_junk_file_name("informe.docx")
    assert long_path("relativo") == "relativo"


def test_symlinked_folders_are_not_followed(tmp_path):
    _app()
    root = tmp_path / "root"
    root.mkdir()
    target = tmp_path / "fuera"
    target.mkdir()
    (target / "a.jpg").write_text("x", encoding="utf-8")
    try:
        os.symlink(target, root / "enlace", target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    result, _ = _analyze(root, _manager(tmp_path))
    assert result["folders"] == []


def test_category_to_folder_is_single_source_of_truth():
    assert category_to_folder("VARIOS") == VARIOS_FOLDER
    assert category_to_folder("VARIOS_REVISAR") == VARIOS_FOLDER
    assert category_to_folder("FOTOS", {"IMAGENES": ["FOTOS"]}) == "IMAGENES/FOTOS"
    assert category_to_folder("IMAGENES") == "IMAGENES"


def test_worker_executes_preview_plan_as_is(tmp_path):
    _app()
    root = tmp_path / "root"
    root.mkdir()
    file_path = root / "a.txt"
    file_path.write_text("a", encoding="utf-8")
    movements = [{"file": file_path, "category": "TEXTOS", "size": 1}]
    plan = build_organization_plan(str(root), [], movements, conflict_policy="rename")
    # Si el plan coincide, el worker no vuelve a calcular destinos
    plan.items[0].destination = root / "TEXTOS" / "elegido.txt"
    tm = TransactionManager(str(tmp_path / "ops.jsonl"))
    worker = OrganizeWorker(str(root), [], movements, transaction_manager=tm, plan=plan)
    worker.run()
    assert (root / "TEXTOS" / "elegido.txt").exists()


def test_folder_move_uses_rename_only(tmp_path, monkeypatch):
    import shutil

    root = tmp_path / "root"
    (root / "carpeta").mkdir(parents=True)
    (root / "carpeta" / "x.txt").write_text("x", encoding="utf-8")
    tm = TransactionManager(str(tmp_path / "ops.jsonl"))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("no debe copiar carpetas")

    monkeypatch.setattr(shutil, "copytree", forbidden)
    monkeypatch.setattr(shutil, "rmtree", forbidden)
    tm.begin_transaction("carpetas")
    assert tm.safe_move_directory(root / "carpeta", root / "DOCS" / "carpeta")
    tm.end_transaction()

    def failing_rename(*_args):
        raise OSError(18, "Invalid cross-device link")

    (root / "otra").mkdir()
    monkeypatch.setattr(os, "rename", failing_rename)
    assert not tm.safe_move_directory(root / "otra", root / "DOCS" / "otra")
    assert "otra unidad" in tm.last_error
    assert (root / "otra").is_dir()
