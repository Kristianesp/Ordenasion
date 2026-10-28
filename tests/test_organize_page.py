"""Página Organizar nativa: flujo completo y funciones de la tabla.

Todo ocurre en carpetas temporales; los diálogos modales se sustituyen por
respuestas fijas para que nada bloquee la ejecución.
"""

import os
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.utils.app_config import AppConfig

APP = QApplication.instance() or QApplication([])

SAMPLE_FILES = {
    "informe.pdf": 9, "notas.txt": 2, "presupuesto.xlsx": 3, "playa.jpg": 30,
    "captura.png": 12, "cancion.mp3": 50, "viaje.mp4": 80, "script.py": 1,
}


def _wait(predicate, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        APP.processEvents()
        if predicate():
            return True
        QTest.qWait(20)
    return False


class _Profiles:
    def __init__(self):
        self.profiles = {}
        self.active = None

    def get_profile_names(self):
        return list(self.profiles)

    def get_active_profile(self):
        return self.profiles.get(self.active)

    def get_profile(self, name):
        return self.profiles.get(name)

    def create_profile(self, name):
        self.profiles[name] = SimpleNamespace(name=name, folder_path="", move_folders=True,
                                              similarity_threshold=70, organize_by_date=False,
                                              exclude_patterns=[], selected_categories=[])
        return self.profiles[name]

    def update_profile(self, profile):
        self.profiles[profile.name] = profile

    def set_active_profile(self, name):
        self.active = name


@pytest.fixture
def page(tmp_path):
    from src.core.category_manager import CategoryManager
    from src.core.transaction_manager import TransactionManager
    from src.gui.organize_controller import OrganizeController
    from src.gui.v2.pages.organize_page import OrganizePage

    config = AppConfig(str(tmp_path / "config.json"))
    config.set_auto_analyze(False)
    controller = OrganizeController(TransactionManager(str(tmp_path / "operations.jsonl")))
    widget = OrganizePage(config, controller, CategoryManager(str(tmp_path / "categories.json")), _Profiles())
    widget._notify = MagicMock()
    widget._alert = MagicMock()
    widget.resize(1100, 760)
    widget.show()
    APP.processEvents()
    yield widget
    controller.shutdown_workers()
    widget.close()
    APP.processEvents()


@pytest.fixture
def sample(tmp_path):
    root = tmp_path / "Descargas"
    root.mkdir()
    for name, kb in SAMPLE_FILES.items():
        (root / name).write_bytes(os.urandom(kb * 1024))
    photos = root / "Fotos"
    photos.mkdir()
    for index in range(4):
        (photos / f"IMG_{index}.jpg").write_bytes(os.urandom(4096))
    return root


def _analyze(page, folder):
    page.folder_input.setText(str(folder))
    page.start_analysis()
    assert page.progress_panel.isVisibleTo(page)
    assert _wait(lambda: not page.controller.busy and page.movements_model.rowCount() > 0)


def test_empty_state_until_a_folder_is_analyzed(page, tmp_path):
    assert page.results_empty_state.isVisible() and not page.movements_table.isVisible()
    assert not page.organize_btn.isEnabled()
    assert page.results_empty_state.action_button.text() == "Elegir carpeta"
    page.start_analysis()
    page._notify.assert_called_once()
    assert page._notify.call_args.args[:2] == ("warning", "Elige una carpeta")
    empty = tmp_path / "vacia"
    empty.mkdir()
    page.folder_input.setText(str(empty))
    page.start_analysis()
    assert _wait(lambda: not page.controller.busy)
    assert _wait(lambda: page.results_empty_state.action_button.text() == "Elegir otra carpeta")
    assert page.results_empty_state.text_label.text() == "No hay nada que organizar en esta carpeta."


def test_end_to_end_analyze_organize_and_undo(page, sample, monkeypatch):
    import src.gui.v2.pages.organize_page as module

    originals = {path.relative_to(sample): path.read_bytes() for path in sample.rglob("*") if path.is_file()}
    _analyze(page, sample)
    assert not page.progress_panel.isVisibleTo(page)
    assert page.movements_table.isVisible() and not page.results_empty_state.isVisible()
    assert page.stats_label.text() != "Sin análisis"
    page.select_all_items()
    assert page.organize_btn.isEnabled()
    assert "seleccionados" in page.selection_count_label.text()

    # Vista previa aceptada sin bloquear: se usa el plan real del diálogo
    reviewed = {}

    def accept(dialog):
        reviewed["rows"] = len(dialog.preview_rows)
        return 1

    monkeypatch.setattr(module.PreviewDialog, "exec", accept)
    summaries = []
    monkeypatch.setattr(page, "show_summary", lambda summary, undo=None: summaries.append(summary))
    page.start_organization()
    assert reviewed["rows"] == len(SAMPLE_FILES) + 1
    assert page.organize_btn.text() == "Organizando…"
    assert _wait(lambda: page.controller.last_operation_summary is not None and not page.controller.busy)
    assert _wait(lambda: summaries)
    assert summaries[0]["status"] == "completado"

    moved = {path.relative_to(sample) for path in sample.rglob("*") if path.is_file()}
    assert all(path.parts[0].isupper() for path in moved), moved  # todo dentro de carpetas de categoría
    assert (sample / "IMAGENES" / "Fotos" / "IMG_0.jpg").exists()
    assert (sample / "DOCUMENTOS" / "informe.pdf").exists()
    assert page.rollback_btn.isEnabled()

    # Refresco automático tras organizar y, después, deshacer
    assert _wait(lambda: not page.controller.busy and page._analysis_result_path is not None)
    monkeypatch.setattr(page, "_ask", MagicMock(return_value=True))
    page.rollback_last_operation()
    page._ask.assert_called_once()
    assert _wait(lambda: page.controller.current_rollback_task_id is None and not page.controller.busy)
    restored = {path.relative_to(sample): path.read_bytes() for path in sample.rglob("*") if path.is_file()}
    assert restored == originals
    page._notify.assert_any_call("success", "Organización deshecha", "Los cambios se han revertido.")


def test_cancel_stops_analysis_safely(page, sample):
    page.folder_input.setText(str(sample))
    page.start_analysis()
    assert page.controller.can_cancel() and page.cancel_btn.isEnabled()
    page.cancel_operation()
    assert _wait(lambda: not page.controller.busy)
    assert not page.progress_panel.isVisibleTo(page)
    assert page.analyze_btn.isEnabled()


def test_checkbox_click_space_and_context_menu(page, sample):
    _analyze(page, sample)
    table, model = page.movements_table, page.movements_model
    rect = table.visualRect(model.index(0, 0))
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(rect.center()), QPointF(rect.center()),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(table.viewport(), press)
    assert model.get_checked_rows() == [0]
    table.setCurrentIndex(model.index(0, 0))
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Space)
    assert model.get_checked_rows() == []

    group_row = next(row for row in range(model.rowCount()) if model.get_row_data(row).get("is_group"))
    menu = page.build_context_menu(group_row)
    texts = [action.text() for action in menu.actions() if action.text()]
    assert texts == ["Abrir en el Explorador", "Expandir grupo", "Marcar"]
    next(action for action in menu.actions() if action.text() == "Expandir grupo").trigger()
    assert model.get_row_data(group_row)["is_expanded"]
    child = model.get_row_data(group_row + 1)
    assert child["is_child"] and model.data(model.index(group_row + 1, 0), Qt.ItemDataRole.CheckStateRole) is None
    child_menu = page.build_context_menu(group_row + 1)
    assert [action.text() for action in child_menu.actions()] == ["Abrir en el Explorador"]
    opened = []
    page.open_file_location = opened.append
    child_menu.actions()[0].trigger()
    assert opened == [os.path.dirname(child["original_file"])]
    page.toggle_file_group_expansion(group_row)
    assert not model.get_row_data(group_row)["is_expanded"]


def test_sorting_filtering_and_selection_summary(page, sample):
    _analyze(page, sample)
    model = page.movements_model
    page.on_header_clicked(5)
    sizes = [model.get_row_data(row)["size_bytes"] for row in range(model.rowCount())]
    assert sizes == sorted(sizes)
    page.on_header_clicked(5)
    sizes = [model.get_row_data(row)["size_bytes"] for row in range(model.rowCount())]
    assert sizes == sorted(sizes, reverse=True)
    assert page.movements_table.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    page.on_header_clicked(0)  # la casilla no ordena
    assert model.get_sort_info()["column"] == 5

    total = model.rowCount()
    page.select_all_items()
    assert page.selection_count_label.text().startswith(f"{total} de {total} seleccionados")
    page.filter_bar.category_filter.setCurrentText("IMAGENES")
    assert 0 < model.rowCount() < total
    assert all(model.get_row_data(row)["category"] == "IMAGENES" for row in range(model.rowCount()))
    assert page.filter_bar.count_label.isVisibleTo(page)
    page.filter_bar.clear_filters()
    assert model.rowCount() == total
    page.deselect_all_items()
    assert not page.organize_btn.isEnabled()
    # Otra carpeta en la ruta: la selección antigua no se puede revisar
    page.select_all_items()
    page.folder_input.setText(str(sample.parent))
    assert not page.organize_btn.isEnabled()


def test_options_favorites_profiles_and_conflict_policy_persist(page, sample, monkeypatch):
    config = page.config
    page.folder_input.setText(str(sample))
    assert page.add_favorite_btn.text() == "Guardar favorito"
    page.add_current_path_to_favorites()
    assert config.get_favorite_paths() == [str(sample)]
    assert page.add_favorite_btn.text() == "Quitar favorito"
    assert page.path_memory_combo.findData(str(sample)) >= 0
    page.folder_input.setText("")
    page.path_memory_combo.setCurrentIndex(page.path_memory_combo.findData(str(sample)))
    assert page.folder_input.text() == str(sample)

    page.advanced_mode_toggle.click()
    assert page.advanced_controls.isVisibleTo(page) and config.get_ui_advanced_mode()
    assert page.advanced_mode_toggle.text() == "Ocultar opciones avanzadas"
    page.conflict_policy_combo.setCurrentIndex(page.conflict_policy_combo.findData("skip"))
    assert config.get_organization_conflict_policy() == "skip"

    monkeypatch.setattr(page, "_prompt_text", lambda *_args: ("Descargas", True))
    page.organize_by_date_checkbox.setChecked(True)
    page.similarity_spinbox.setValue(55)
    page.save_current_profile()
    profile = page.profile_manager.get_profile("Descargas")
    assert profile.folder_path == str(sample) and profile.organize_by_date and profile.similarity_threshold == 55
    assert page.profile_combo.currentText() == "Descargas" and page.load_profile_btn.isEnabled()

    # Las opciones se usan al analizar y al organizar
    starts = MagicMock(return_value="analysis")
    monkeypatch.setattr(page.controller, "start_analysis", starts)
    page.min_size_spinbox.setValue(2)
    page.start_analysis()
    assert starts.call_args.args[3] == 55 and starts.call_args.kwargs["min_file_size_mb"] == 2
    assert config.get_min_similarity() == 55 and config.get_min_file_size_mb() == 2


def test_configure_and_tasks_buttons(page, monkeypatch):
    from src.gui import config_dialog

    focus = []

    class _Dialog:
        def __init__(self, parent, manager, app_config_ref=None, focus_section=None):
            focus.append(focus_section)
            self.category_manager = manager

        def exec(self):
            return 1

    monkeypatch.setattr(config_dialog, "ConfigDialog", _Dialog)
    changed = MagicMock()
    page.configuration_changed.connect(changed)
    page.config_btn.click()
    page.manage_exclusions_btn.click()
    assert focus == [None, "exclusions"]
    assert changed.call_count == 2
    activity = MagicMock()
    page.activity_requested.connect(activity)
    page.task_center_btn.click()
    activity.assert_called_once()
