import os

from src.utils.app_config import AppConfig


def native(path):
    """Las rutas se guardan con los separadores del sistema."""
    return os.path.normpath(path)


def test_audio_config_roundtrip(tmp_path):
    config = AppConfig(str(tmp_path / "app_config.json"))

    assert config.set_audio_library_roots(["/music", "/archive/music"])
    assert config.set_audio_duplicate_policy("review")
    assert config.set_audio_organization_template(
        "MUSICA/{album_artist}/{year} - {album}"
    )
    assert config.set_audio_online_metadata_enabled(True)

    reloaded = AppConfig(str(tmp_path / "app_config.json"))
    assert reloaded.get_audio_library_roots() == [native("/music"), native("/archive/music")]
    assert reloaded.get_audio_duplicate_policy() == "review"
    assert reloaded.get_audio_online_metadata_enabled() is True
    assert (
        reloaded.get_audio_organization_template()
        == "MUSICA/{album_artist}/{year} - {album}"
    )


def test_audio_music_table_layout_roundtrip(tmp_path):
    config = AppConfig(str(tmp_path / "app_config.json"))

    assert config.set_music_library_column_widths([320, 140, 250])
    assert config.set_music_library_column_order([2, 0, 1])
    assert config.set_music_library_visible_columns([0, 1, 2])
    assert config.set_music_library_splitter_sizes([880, 360])

    reloaded = AppConfig(str(tmp_path / "app_config.json"))
    assert reloaded.get_music_library_column_widths()[:3] == [320, 140, 250]
    assert reloaded.get_music_library_column_order() == [2, 0, 1]
    assert reloaded.get_music_library_visible_columns() == [0, 1, 2]
    assert reloaded.get_music_library_splitter_sizes() == [880, 360]
