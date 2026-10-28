import importlib.util
from pathlib import Path

from src.utils.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    spec = importlib.util.spec_from_file_location("release_notes", ROOT / "tools" / "release_notes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_changelog_has_section_for_current_version():
    notes = load_tool().section(APP_VERSION)
    assert notes.startswith("1. ")
    assert "## " not in notes


def test_release_notes_file_includes_hash_and_data_location(tmp_path):
    out = tmp_path / "notes.md"
    load_tool().main([APP_VERSION, "--out", str(out), "--exe", f"Ordenasion_v{APP_VERSION}.exe",
                      "--mb", "60.5", "--sha", "ab" * 32])
    text = out.read_text(encoding="utf-8")
    assert f"Ordenasion_v{APP_VERSION}.exe · 60.5 MB" in text
    assert "`" + "ab" * 32 + "`" in text
    assert "%LOCALAPPDATA%\\Ordenasion" in text
