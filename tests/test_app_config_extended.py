import os

from src.utils.app_config import AppConfig


def test_app_config_persists_path_memory_and_exclusions(tmp_path):
    config = AppConfig(str(tmp_path / "app_config.json"))

    assert config.set_ignored_extensions(["tmp", ".log", " .bak "])
    assert config.set_ignored_paths(["/tmp/cache", "/tmp/cache/sub", ""])
    assert config.set_protected_paths(["/home/user/Documents"])
    assert config.set_min_file_size_mb(25)
    assert config.set_ui_advanced_mode(True)
    assert config.add_favorite_path("/data/media")
    assert config.push_recent_path("/data/downloads")

    reloaded = AppConfig(str(tmp_path / "app_config.json"))
    assert reloaded.get_ignored_extensions() == [".bak", ".log", ".tmp"]
    assert reloaded.get_ignored_paths() == ["/tmp/cache", "/tmp/cache/sub"]
    assert reloaded.get_protected_paths() == ["/home/user/Documents"]
    assert reloaded.get_min_file_size_mb() == 25
    assert reloaded.get_ui_advanced_mode() is True
    assert reloaded.get_favorite_paths() == ["/data/media"]
    assert reloaded.get_recent_paths()[0] == "/data/downloads"


def test_app_config_persists_duplicate_preferences(tmp_path):
    config = AppConfig(str(tmp_path / "app_config.json"))

    assert config.set_ignored_duplicate_hashes(["abc", "def", "abc"])
    assert config.set_preferred_original("hash1", "/tmp/fileA")
    assert config.set_preferred_original("hash2", "/tmp/fileB")
    assert config.remove_preferred_original("hash1")

    reloaded = AppConfig(str(tmp_path / "app_config.json"))
    assert reloaded.get_ignored_duplicate_hashes() == ["abc", "def"]
    assert reloaded.get_preferred_originals() == {"hash2": "/tmp/fileB"}


def test_app_config_persists_audio_settings(tmp_path):
    config = AppConfig(str(tmp_path / "app_config.json"))

    assert config.set_auto_analyze(False)
    assert config.set_audio_library_roots(["/music"])
    assert config.set_audio_duplicate_policy("quarantine")
    assert config.set_music_preview_playback_rate(1.25)

    reloaded = AppConfig(str(tmp_path / "app_config.json"))
    assert reloaded.get_auto_analyze() is False
    assert reloaded.get_audio_library_roots() == ["/music"]
    assert reloaded.get_audio_duplicate_policy() == "quarantine"
    assert reloaded.get_music_preview_playback_rate() == 1.25


def test_app_config_keeps_music_header_legacy_field(tmp_path):
    config = AppConfig(str(tmp_path / "app_config.json"))

    assert config.set_music_library_header_state("0,1,2")

    reloaded = AppConfig(str(tmp_path / "app_config.json"))
    assert reloaded.get_music_library_header_state() == "0,1,2"


def test_app_config_does_not_lose_audio_keys_between_instances(tmp_path):
    first = AppConfig(str(tmp_path / "app_config.json"))
    second = AppConfig(str(tmp_path / "app_config.json"))

    assert first.set_music_library_visible_columns([0, 1, 2, 3, 4])
    assert second.set_music_library_column_widths([320, 140, 250, 90, 120])

    reloaded = AppConfig(str(tmp_path / "app_config.json"))
    assert reloaded.get_music_library_visible_columns() == [0, 1, 2, 3, 4]
    assert reloaded.get_music_library_column_widths()[:5] == [320, 140, 250, 90, 120]


def test_paths_use_windows_semantics_with_old_forward_slash_configs(tmp_path, monkeypatch):
    """En Windows: separadores nativos, rutas antiguas con '/' y sin distinguir mayúsculas."""
    import ntpath
    import types
    import src.utils.app_config as app_config_module

    windows_os = types.SimpleNamespace(**{name: getattr(os, name) for name in dir(os) if not name.startswith("__")})
    windows_os.path = ntpath
    monkeypatch.setattr(app_config_module, "os", windows_os)
    config = AppConfig(str(tmp_path / "config.json"))
    config.set("analysis.favorite_paths", ["C:/Users/Ana/Fotos"])  # formato de la 3.5
    assert config.get_favorite_paths() == ["C:\\Users\\Ana\\Fotos"]
    assert config.is_favorite_path("c:\\users\\ana\\fotos\\")
    config.add_favorite_path("C:\\Users\\Ana\\Fotos")
    assert config.get_favorite_paths() == ["C:\\Users\\Ana\\Fotos"]
    config.remove_favorite_path("c:/users/ana/FOTOS")
    assert config.get_favorite_paths() == []
    config.set_protected_paths(["D:/Datos/Boda", "d:\\datos\\boda"])
    assert config.get_protected_paths() == ["D:\\Datos\\Boda"]
