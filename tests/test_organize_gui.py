"""Regresiones de la interfaz de "Organizar": perfiles, log, cierre e historial."""

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QTextEdit

from src.gui import organize_controller
from src.gui.v2.pages import organize_page as module
from src.utils.app_config import AppConfig


APP = None


def _app():
    global APP
    APP = QApplication.instance() or QApplication([])
    return APP


def _controller(tmp_path):
    from src.core.transaction_manager import TransactionManager
    from src.gui.organize_controller import OrganizeController

    return OrganizeController(TransactionManager(str(tmp_path / "ops.jsonl")))


class _Profiles:
    """ProfileManager mínimo en memoria."""

    def __init__(self, profiles=()):
        self.profiles = {profile.name: profile for profile in profiles}

    def get_profile_names(self):
        return list(self.profiles)

    def get_active_profile(self):
        return None

    def get_profile(self, name):
        return self.profiles.get(name)


def _page(tmp_path, controller=None, profiles=()):
    """Página Organizar real con configuración, historial y categorías temporales."""
    from src.core.category_manager import CategoryManager

    _app()
    config = AppConfig(str(tmp_path / "config.json"))
    page = module.OrganizePage(config, controller or _controller(tmp_path),
                               CategoryManager(str(tmp_path / "categories.json")), _Profiles(profiles))
    # Sin análisis automático al escribir la ruta (temporizador de 1 s)
    page.config.set_auto_analyze(False)
    page._notify = MagicMock()
    page._alert = MagicMock()
    return page


def test_loading_profile_keeps_protected_paths_and_folder(tmp_path):
    profile = SimpleNamespace(
        name="Descargas", folder_path="", move_folders=False, similarity_threshold=55,
        organize_by_date=True, exclude_patterns=[str(tmp_path / "excluida")],
    )
    page = _page(tmp_path, profiles=[profile])
    page.config.set_protected_paths([str(tmp_path / "importante")])
    page.folder_input.setText(str(tmp_path / "actual"))
    page.profile_combo.setCurrentText("Descargas")
    page.load_selected_profile()
    assert page.config.get_protected_paths() == [str(tmp_path / "importante")]
    assert page.folder_input.text() == str(tmp_path / "actual")
    assert page._profile_exclusions == [str(tmp_path / "excluida")]
    assert not page.move_folders_checkbox.isChecked()
    assert page.organize_by_date_checkbox.isChecked()
    assert page.similarity_spinbox.value() == 55


def test_log_messages_are_batched_and_counted_incrementally(tmp_path):
    _app()
    controller = _controller(tmp_path)
    batches = []
    controller.log_appended.connect(batches.append)
    for index in range(500):
        controller.log(f"mensaje {index}")
    # Nada se emite hasta el volcado del temporizador
    assert batches == []
    assert controller._log_flush_timer.isActive()
    controller.flush_log()
    assert controller.log_entry_count == 500
    assert len(batches) == 1 and len(batches[0]) == 500
    view = QTextEdit()
    for line in controller.log_history():
        view.append(line)
    assert view.document().blockCount() == 500
    exported = tmp_path / "registro.txt"
    assert controller.export_log(str(exported)) == 500
    assert "mensaje 499" in exported.read_text(encoding="utf-8")


def test_task_progress_is_throttled(tmp_path, monkeypatch):
    _app()
    controller = _controller(tmp_path)
    updates = []
    monkeypatch.setattr(organize_controller.task_registry, "update_task", lambda task, msg: updates.append((task, msg)))
    for index in range(100):
        controller.handle_task_progress("t1", f"archivo {index}")
    assert updates == []
    controller.flush_log()
    assert updates == [("t1", "archivo 99")]


class _FakeWorker(organize_controller.OrganizeWorker):
    def __init__(self):
        QObject.__init__(self)
        self.stopped = False
        self.waited = False

    def isRunning(self):
        return not self.waited

    def stop(self):
        self.stopped = True

    def wait(self, *_args):
        self.waited = True
        return True


def test_close_asks_and_waits_for_running_organization(tmp_path, monkeypatch):
    _app()
    worker = _FakeWorker()
    controller = _controller(tmp_path)
    controller.active_workers.append(worker)
    page = _page(tmp_path, controller)

    monkeypatch.setattr(page, "_ask", MagicMock(return_value=False))
    assert page.request_shutdown() is False
    assert not worker.stopped

    monkeypatch.setattr(page, "_ask", MagicMock(return_value=True))
    assert page.request_shutdown() is True
    assert worker.stopped and worker.waited


def test_summary_dialog_shows_status_and_offers_partial_undo():
    _app()
    from src.gui.operation_summary_dialog import OperationSummaryDialog

    undo = MagicMock()
    dialog = OperationSummaryDialog(
        {"status": "cancelado", "files_moved": 2, "pending": 3, "transaction_id": "t"},
        undo_callback=undo,
    )
    text = "\n".join(dialog.summary_lines())
    assert "Cancelada" in text and "Sin procesar (cancelado): 3" in text
    assert dialog.undo_btn is not None
    dialog.undo_btn.click()
    undo.assert_called_once()

    errors = OperationSummaryDialog({"status": "completado con errores", "files_moved": 1, "failed": 2})
    assert "Completada con errores" in "\n".join(errors.summary_lines())
    assert "Elementos con error: 2" in "\n".join(errors.summary_lines())
    assert errors.undo_btn is None


class _Controller(QObject):
    operation_state_changed = pyqtSignal()
    log_appended = pyqtSignal(list)
    log_cleared = pyqtSignal()
    log_entry_count = 0

    def log_history(self):
        return []

    def __init__(self, entries):
        super().__init__()
        self.entries = entries
        self.last_operation_summary = None
        self.last_transaction_id = entries[0]["id"] if entries else None
        self.current_organize_task_id = None
        self.current_rollback_task_id = None
        self.rollback_transaction = MagicMock()
        self.rollback_last_operation = MagicMock()
        self.clear_log = MagicMock()
        self.export_log = MagicMock()
        self.scroll_log_to_bottom = MagicMock()

    def get_transaction_history(self, limit):
        return self.entries[:limit]


def test_activity_page_lists_history_with_undo_per_entry():
    _app()
    from src.gui.v2.pages.activity_page import ActivityPage

    entries = [
        {"id": "txn_2", "timestamp": "2026-10-28T10:00:00", "status": "cancelado",
         "moves": 3, "source_folder": "C:/Descargas", "can_undo": True, "undo_state": "no"},
        {"id": "txn_1", "timestamp": "2026-10-27T09:00:00", "status": "completado",
         "moves": 5, "source_folder": "C:/Fotos", "can_undo": False, "undo_state": "deshecha"},
    ]
    controller = _Controller(entries)
    page = ActivityPage(controller)
    assert [entry[0] for entry in page.history_entries] == ["txn_2", "txn_1"]
    first_undo, second_undo = page.history_entries[0][1], page.history_entries[1][1]
    assert first_undo.isEnabled() and not second_undo.isEnabled()
    assert "deshecha" in page.history_entries[1][2].text()
    first_undo.click()
    controller.rollback_transaction.assert_called_once_with("txn_2")

    controller.current_organize_task_id = "activa"
    controller.operation_state_changed.emit()
    assert not page.history_entries[0][1].isEnabled()


def test_rollback_transaction_runs_in_background(tmp_path, monkeypatch):
    _app()
    started = []

    class _Worker(QObject):
        rollback_finished = pyqtSignal(str, bool, dict)
        finished = pyqtSignal()

        def __init__(self, manager, txn):
            super().__init__()
            self.txn = txn

        def start(self):
            started.append(self.txn)

    monkeypatch.setattr(organize_controller, "RollbackWorker", _Worker)
    monkeypatch.setattr(organize_controller.task_registry, "start_task", MagicMock())
    controller = _controller(tmp_path)
    controller.last_transaction_id = "txn_a"
    page = _page(tmp_path, controller)
    ask = MagicMock(return_value=False)
    monkeypatch.setattr(page, "_ask", ask)
    # Con confirmación: si el usuario no acepta, no se deshace nada
    assert not page.rollback_transaction("txn_a")
    ask.assert_called_once()
    assert page.rollback_transaction("txn_b", confirm=False)
    assert started == ["txn_b"]
    assert controller.current_rollback_task_id
    assert not page.rollback_btn.isEnabled() and not page.organize_btn.isEnabled()
    assert page.progress_panel.isVisibleTo(page) and not page.cancel_btn.isVisibleTo(page)
    # Mientras se deshace no se puede lanzar otra operación
    assert not page.rollback_transaction("txn_a", confirm=False)
    assert not controller.start_rollback("txn_a")


def test_preview_tolerates_vanished_files_and_flags_category_folders(tmp_path):
    _app()
    from src.gui.preview_dialog import PreviewDialog

    root = tmp_path / "root"
    (root / "IMAGENES").mkdir(parents=True)
    gone = root / "borrado.txt"
    movements = [{"file": gone, "category": "TEXTOS", "size": 1}]
    dialog = PreviewDialog(
        [{"folder": root / "IMAGENES", "category": "IMAGENES", "size": 0}],
        movements, str(root), organize_by_date=True,
    )
    statuses = [row["status"] for row in dialog.preview_rows]
    assert statuses[0].startswith("Omitido: ya es una carpeta de categoría")
    assert statuses[1] == "Omitido: el elemento ya no existe"
    assert "No se moverán 2 elementos" in dialog.summary_label.text()
    assert dialog.get_plan().items[1].action == "missing"
    assert dialog.preview_model.rowCount() == 2


def test_schedule_post_organization_refresh_triggers_analysis(tmp_path, monkeypatch):
    page = _page(tmp_path)
    page.folder_input.setText(str(tmp_path))
    scheduled = {}
    monkeypatch.setattr(module.QTimer, "singleShot",
                        lambda delay, callback: scheduled.update(delay=delay, callback=callback))
    page._schedule_post_organization_refresh()
    assert scheduled["delay"] == 150
    assert scheduled["callback"] == page.start_analysis
    page.controller.flush_log()
    assert page.controller.log_text().endswith("🔄 Refrescando resultados tras la organización...")
    page.folder_input.setText(str(tmp_path / "ya-no-existe"))
    scheduled.clear()
    page._schedule_post_organization_refresh()
    assert not scheduled
