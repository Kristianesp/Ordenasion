"""Popups reales bajo Qt; sin búsqueda online ni escritura de metadatos."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QMenu, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import PrimaryPushButton

from src.gui.v2.theme import apply_dialog_surface, apply_fluent_theme, apply_menu_surface, contrast_ratio, current_tokens
from src.utils.app_config import AppConfig

APP = None


@pytest.fixture
def parent(tmp_path):
    global APP
    APP = QApplication.instance() or QApplication([])
    widget = QWidget()
    widget.config = AppConfig(str(tmp_path / "config.json"))
    yield widget
    widget.close()


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_dialog_without_object_name_has_visible_surface_fields_and_primary_hover(parent, mode):
    parent.config.config["interface"]["theme_mode"] = mode
    apply_fluent_theme(parent.config)
    tokens = current_tokens(parent.config.get_accent_color(), mode)
    dialog = QDialog(parent)
    layout = QVBoxLayout(dialog)
    label = QLabel("Título de la canción")
    field = QLineEdit("Canción de prueba")
    button = PrimaryPushButton("Confirmar")
    layout.addWidget(label)
    layout.addWidget(field)
    layout.addWidget(button)
    apply_dialog_surface(dialog)
    dialog.resize(400, 200)
    dialog.show()
    APP.processEvents()
    assert dialog.objectName() == "fluentDialog"
    assert dialog.grab().toImage().pixelColor(5, 5).name() == QColor(tokens.canvas).name()
    assert label.palette().color(QPalette.ColorRole.WindowText).name() == QColor(tokens.text_primary).name()
    assert field.palette().color(QPalette.ColorRole.Base).name() == QColor(tokens.surface).name()
    assert contrast_ratio(tokens.text_primary, tokens.surface) >= 4.5
    QTest.mouseMove(button, button.rect().center())
    APP.processEvents()
    image = button.grab().toImage()
    # Punto interior libre de texto: la primaria no se vuelve blanca al hover.
    assert image.pixelColor(8, button.height() // 2).name() == QColor(tokens.accent).name()
    assert contrast_ratio(tokens.accent_foreground, tokens.accent) >= 4.5
    dialog.close()


def test_persistent_menu_resolves_new_parent_and_current_theme_each_open(parent):
    detached_parent = QWidget()
    menu = QMenu(detached_parent)
    menu.addAction("Editar metadatos")
    disabled = menu.addAction("No disponible")
    disabled.setEnabled(False)
    menu.addSeparator()
    menu.addAction("Abrir carpeta")
    apply_menu_surface(menu)  # fallback anterior a reparentado del shell
    detached_parent.setParent(parent)
    for mode in ("dark", "light", "dark"):
        parent.config.config["interface"]["theme_mode"] = mode
        apply_fluent_theme(parent.config)
        tokens = current_tokens(mode=mode)
        menu.popup(QPoint(30, 30))
        APP.processEvents()
        image = menu.grab().toImage()
        assert image.pixelColor(menu.width() // 2, 3).name() == QColor(tokens.surface).name()
        assert menu.palette().color(QPalette.ColorRole.WindowText).name() == QColor(tokens.text_primary).name()
        assert tokens.text_secondary in menu.styleSheet()
        menu.close()


class MusicView(QWidget):
    def __init__(self, parent, target):
        super().__init__(parent)
        self.library_table = QTableWidget(1, 1, self)
        self.library_table.resize(400, 200)
        item = QTableWidgetItem(target.name)
        item.setData(Qt.ItemDataRole.UserRole, str(target))
        self.library_table.setItem(0, 0, item)
        self.LIBRARY_COLUMN_LABELS = ["Archivo"]
        self.LIBRARY_SELECT_COLUMN = self.LIBRARY_FILE_COLUMN = 0
        self._save_visible_columns = MagicMock()
        self._toggle_track_complete = MagicMock()
        self._toggle_track_no_match = MagicMock()
        self.clean_selected_titles = MagicMock()
        self.edit_selected_metadata = MagicMock()
        self._get_lookup_result = lambda *_: {}
        self._set_cover_preview = MagicMock()
        self._set_cover_preview_from_bytes = MagicMock()
        self._fetch_cover_preview_bytes = lambda *_: None
        self._format_duration = lambda *_: "03:12"
        self._format_quality = lambda *_: "320 kbps"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_music_editor_columns_and_library_menu_use_controller_theme_without_writes(parent, tmp_path, monkeypatch, mode):
    from src.gui import music_duplicates_library_actions as library
    from src.gui import music_duplicates_metadata_editor as metadata
    parent.config.config["interface"]["theme_mode"] = mode
    apply_fluent_theme(parent.config)
    tokens = current_tokens(mode=mode)
    target = tmp_path / "Canción de prueba.mp3"
    view = MusicView(parent, target)
    view.show()
    dialog_names, menus = [], []
    writes = MagicMock()
    monkeypatch.setattr(metadata.audio_metadata_service, "get_metadata", lambda *_: {"title": "Canción", "artist": "Artista"})
    monkeypatch.setattr(metadata.audio_metadata_service, "update_track_tags", writes)
    monkeypatch.setattr(library.audio_metadata_service, "get_track_review_status", lambda *_: "pending")

    def capture_dialog(dialog):
        dialog.show()
        APP.processEvents()
        dialog_names.append(dialog.objectName())
        assert dialog.grab().toImage().pixelColor(5, 5).name() == QColor(tokens.canvas).name()
        for label in dialog.findChildren(QLabel):
            assert label.palette().color(QPalette.ColorRole.WindowText).name() == QColor(tokens.text_primary).name()
        for field in dialog.findChildren(QLineEdit):
            assert field.palette().color(QPalette.ColorRole.Base).name() == QColor(tokens.surface).name()
        dialog.reject()
        return QDialog.DialogCode.Rejected

    def capture_menu(menu, *_):
        menu.popup(QPoint(30, 30))
        APP.processEvents()
        menus.append(menu)
        assert menu.palette().color(QPalette.ColorRole.WindowText).name() == QColor(tokens.text_primary).name()
        assert [action.text() for action in menu.actions()][-2:] == ["Limpiar títulos", "Editar metadatos"]
        menu.close()

    monkeypatch.setattr(QDialog, "exec", capture_dialog)
    monkeypatch.setattr(QMenu, "exec", capture_menu)
    metadata.edit_track_metadata(view, target)
    library.edit_library_columns(view)
    library.show_library_context_menu(view, view.library_table.visualItemRect(view.library_table.item(0, 0)).center())
    assert dialog_names == ["musicMetadataEditorDialog", "musicLibraryColumnsDialog"] and len(menus) == 1
    writes.assert_not_called()
    view._save_visible_columns.assert_not_called()
    view.clean_selected_titles.assert_not_called()
    view.edit_selected_metadata.assert_not_called()


def test_variant_highlight_uses_legible_tokens_and_can_be_cleared(parent):
    from src.gui.music_duplicates_view import MusicDuplicatesView
    parent.config.config["interface"]["theme_mode"] = "dark"
    tokens = current_tokens(mode="dark")
    editor = QLineEdit(parent)
    MusicDuplicatesView._variant_field_styles(parent, [editor], True)
    assert tokens.text_primary in editor.styleSheet() and tokens.surface_alt in editor.styleSheet()
    assert contrast_ratio(tokens.text_primary, tokens.surface_alt) >= 4.5
    MusicDuplicatesView._variant_field_styles(parent, [editor], False)
    assert not editor.styleSheet()


def test_lookup_variant_and_cover_dialogs_use_same_surface_without_network_or_writes(parent, tmp_path, monkeypatch):
    from src.gui import music_duplicates_lookup_dialogs as lookup
    from src.gui import music_duplicates_variant_dialog as variant
    parent.config.config["interface"]["theme_mode"] = "dark"
    apply_fluent_theme(parent.config)
    tokens = current_tokens(parent.config.get_accent_color(), "dark")
    target = tmp_path / "Canción.mp3"
    view = MusicView(parent, target)
    result = {"candidates": [{"source": "cache", "confidence": 90, "suggested_updates": {"title": "Canción"}},
                             {"source": "cache", "confidence": 80, "suggested_updates": {"title": "Variante"}}],
              "cover_choices": [{"label": "Portada 1", "url": "https://example.invalid/1"},
                                {"label": "Portada 2", "url": "https://example.invalid/2"}]}
    view._get_lookup_result = lambda *_: result
    monkeypatch.setattr(lookup.audio_fingerprint_service, "get_cover_art_bytes_for_url", lambda *_: None)
    writes = MagicMock()
    monkeypatch.setattr(lookup.audio_metadata_service, "update_track_tags", writes)
    names = []

    def capture(dialog):
        dialog.show()
        APP.processEvents()
        names.append(dialog.objectName())
        assert dialog.grab().toImage().pixelColor(5, 5).name() == QColor(tokens.canvas).name()
        for label in dialog.findChildren(QLabel):
            assert label.palette().color(QPalette.ColorRole.WindowText).name() == QColor(tokens.text_primary).name()
        for table in dialog.findChildren(QTableWidget):
            assert table.palette().color(QPalette.ColorRole.Base).name() == QColor(tokens.surface).name()
        dialog.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(QDialog, "exec", capture)
    lookup.show_lookup_diagnostics_dialog(view, target)
    assert variant.prompt_variant_choice(view, str(target), 1, 1) is None
    assert not lookup.prompt_cover_choice(view, target)
    assert names == ["musicLookupDiagnosticsDialog", "musicVariantChoiceDialog", "musicCoverChoiceDialog"]
    writes.assert_not_called()
