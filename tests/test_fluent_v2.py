import os
import shutil
import tempfile
from pathlib import Path
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from src.core.organization_profiles import ProfileManager
from src.gui.filter_bar import FilterBar
from src.gui.v2.pages.home_page import HomePage
from src.gui.v2.theme import (
    apply_fluent_theme,
    preferred_font_family,
    register_bundled_fonts,
    typography_scale,
    fluent_window_stylesheet,
    legacy_surface_stylesheet,
)
from src.utils.app_config import AppConfig


APP = None


def _application():
    global APP
    application = QApplication.instance()
    APP = application or QApplication([])
    return APP


def _temporary_directory() -> Path:
    return Path(tempfile.mkdtemp(prefix="ordenasion-fluent-"))


def test_fluent_theme_modes_are_persisted():
    _application()
    temp_dir = _temporary_directory()
    config = AppConfig(str(temp_dir / "config.json"))

    try:
        assert config.get_theme_mode() == "system"
        assert config.set_theme_mode("dark")
        assert config.set_interface_density("compact")
        assert config.set_accent_color("#123456")

        assert config.get_theme_mode() == "dark"
        assert config.get_interface_density() == "compact"
        assert config.get_accent_color() == "#123456"
        assert apply_fluent_theme(config).accent == "#123456"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_home_page_exposes_primary_actions():
    _application()
    temp_dir = _temporary_directory()
    try:
        config = AppConfig(str(temp_dir / "config.json"))
        profiles = ProfileManager(str(temp_dir / "profiles.json"))
        page = HomePage(config, profiles)
        received_paths = []
        page.analyze_requested.connect(received_paths.append)

        page.path_input.setText(str(temp_dir))
        page._analyze()

        assert received_paths == [str(temp_dir)]
        assert page.disk_metric.value_label.text() == "—"
        assert page.space_metric.detail_label.text() == "Sin análisis de espacio"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_filter_bar_keeps_legacy_signal_contract():
    _application()
    bar = FilterBar(["DOCUMENTOS", "MUSICA"])
    filters = []
    bar.filter_changed.connect(lambda text, category: filters.append((text, category)))

    bar.search_input.setText("informe")
    bar.category_filter.setCurrentText("DOCUMENTOS")
    bar._emit_filter()

    assert filters[-1] == ("informe", "DOCUMENTOS")
    assert bar.category_filter.count() == 3


def test_typography_tokens_follow_density_and_pixels():
    _application()
    temp_dir = _temporary_directory()
    try:
        config = AppConfig(str(temp_dir / "config.json"))
        config.set_font_size(13)
        config.set_interface_density("comfortable")
        comfortable = typography_scale(config)
        config.set_interface_density("compact")
        compact = typography_scale(config)

        assert comfortable.body == compact.body
        assert compact.control_height == compact.body + 16
        assert comfortable.control_height == comfortable.body + 20
        assert compact.control_height < comfortable.control_height

        compact_qss = fluent_window_stylesheet(config)
        compact_legacy = legacy_surface_stylesheet(config)
        inner = compact.control_height - 2
        assert f"min-height: {inner}px" in compact_qss
        assert f"min-height: {inner}px" in compact_legacy
        assert f"min-height: {compact.control_height}px" in compact_legacy
        assert "max(control_height, 34)" not in compact_legacy
        assert f"font-size: {compact.display}px" in compact_qss
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_bundled_font_family_resolves():
    _application()
    register_bundled_fonts()
    family = preferred_font_family()
    assert family
    assert family != "Sans Serif"


def test_primary_and_secondary_buttons_share_control_height():
    from PyQt6.QtWidgets import QPushButton

    from src.gui.v2.theme import apply_control_size

    _application()
    temp_dir = _temporary_directory()
    try:
        config = AppConfig(str(temp_dir / "config.json"))
        config.set_font_size(13)
        config.set_interface_density("comfortable")
        expected = typography_scale(config).control_height
        primary = QPushButton("Tareas")
        secondary = QPushButton("Configurar")
        apply_control_size(primary, config)
        apply_control_size(secondary, config)
        assert primary.minimumHeight() == expected
        assert secondary.minimumHeight() == expected
        assert primary.height() == expected
        assert secondary.height() == expected
        assert primary.minimumHeight() == secondary.minimumHeight()

        config.set_interface_density("compact")
        compact_height = typography_scale(config).control_height
        apply_control_size(primary, config)
        apply_control_size(secondary, config)
        assert compact_height < expected
        assert primary.minimumHeight() == compact_height
        assert secondary.minimumHeight() == compact_height
        assert primary.height() == compact_height
        assert secondary.height() == compact_height
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_glass_composition_keeps_text_contrast_and_static_background(mode):
    from PyQt6.QtWidgets import QWidget
    from src.gui.v2.components import GlassCard
    from src.gui.v2.theme import OceanBackdrop, contrast_ratio, current_tokens

    app = _application()
    temp_dir = _temporary_directory()
    try:
        config = AppConfig(str(temp_dir / "config.json"))
        config.set_theme_mode(mode)
        apply_fluent_theme(config)
        root = QWidget()
        root.config = config
        root.resize(800, 400)
        backdrop = OceanBackdrop(config, root)
        backdrop.setGeometry(root.rect())
        card = GlassCard(root)
        card.setGeometry(200, 50, 560, 300)
        root.show()
        app.processEvents()
        rendered = root.grab().toImage()
        tokens = current_tokens(config.get_accent_color(), mode)
        # Validate the composed pixels, including the white glass layer.
        for point in ((20, 20), (780, 20), (220, 80), (740, 320)):
            background = rendered.pixelColor(*point).name()
            assert contrast_ratio(tokens.text_primary, background) >= 4.5
            assert contrast_ratio(tokens.text_secondary, background) >= 4.5
        assert rendered.pixelColor(20, 20) != rendered.pixelColor(780, 20)
        cached = backdrop._image.cacheKey()
        root.grab()
        assert backdrop._image.cacheKey() == cached
        root.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
