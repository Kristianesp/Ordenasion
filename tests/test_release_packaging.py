"""Contratos de release y smoke en subproceso aislado, sin datos reales."""

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from src.utils.version import APP_VERSION, EXECUTABLE_NAME, VERSION_INFO


ROOT = Path(__file__).resolve().parents[1]
# En el runner aislado las pruebas se copian a temp; el módulo fuente mantiene
# la ubicación real y evita depender del cwd o recorrer directorios de usuario.
import main_fluent
ROOT = Path(main_fluent.__file__).resolve().parent


def test_release_version_and_spec_use_fluent_assets_without_private_data():
    assert APP_VERSION == "3.5.0" and VERSION_INFO == (3, 5, 0, 0)
    assert EXECUTABLE_NAME == "Ordenasion_v3.5.0"
    calls = {}

    def analysis(*args, **kwargs):
        calls["analysis"] = args, kwargs
        binaries = [*kwargs["binaries"], ("ucrtbase.dll", "external/ucrtbase.dll", "BINARY"),
                    ("icuuc.dll", "external/icuuc.dll", "BINARY"),
                    ("icudt78.dll", "external/icudt78.dll", "BINARY"),
                    ("PyQt6/Qt6/bin/Qt6Core.dll", "qt/Qt6Core.dll", "BINARY")]
        return SimpleNamespace(pure=(), scripts=(), binaries=binaries, datas=kwargs["datas"])

    def exe(*args, **kwargs):
        calls["exe"] = kwargs
        calls["exe_args"] = args

    spec = (ROOT / "OrganizadorAlpha_OPTIMIZED.spec").read_text(encoding="utf-8")
    exec(compile(spec, "release.spec", "exec"), {"SPECPATH": str(ROOT), "Analysis": analysis,
         "PYZ": lambda *_: None, "EXE": exe})
    args, options = calls["analysis"]
    assert args[0] == [str(ROOT / "main_fluent.py")]
    assert "PyQt6.QtMultimedia" in options["hiddenimports"]
    assert calls["exe"]["name"] == EXECUTABLE_NAME and not calls["exe"]["console"]
    assert "collect_all(" not in spec
    packaged_binaries = {Path(entry[0]).name.lower() for entry in calls["exe_args"][2]}
    assert not {"ucrtbase.dll", "icuuc.dll", "icudt78.dll"} & packaged_binaries
    assert "qt6core.dll" in packaged_binaries
    included = [Path(source).name for source, _ in options["datas"]]
    assert {"branding", "fonts", "design-tokens.json", "LICENSE"} <= set(included)
    assert not {"app_config.json", "organization_profiles.json", "categories_config.json"} & set(included)
    pe = Path(calls["exe"]["version"]).read_text(encoding="utf-8")
    assert "filevers=(3, 5, 0, 0)" in pe and "Ordenasion_v3.5.0.exe" in pe


def test_source_release_smoke_preserves_caller_config_and_exits_cleanly(tmp_path):
    config = tmp_path / "app_config.json"
    content = b'{"analysis":{"recent_paths":["Z:/example"]}}'
    config.write_bytes(content)
    report = tmp_path / "source-smoke.json"
    environment = {**os.environ, "ORDENASION_SMOKE": "1", "ORDENASION_SMOKE_REPORT": str(report),
                   "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    process = subprocess.run([sys.executable, "-B", str(ROOT / "main_fluent.py")], cwd=tmp_path,
                             env=environment, capture_output=True, text=True, timeout=35)
    result = json.loads(report.read_text(encoding="utf-8"))
    assert process.returncode == 0, result.get("error", process.stderr)
    assert result["version"] == APP_VERSION and result["status"] == "ok"
    assert all(result["assets"].values()) and result["qt_multimedia"]
    assert result["first_frame"] and result["graceful_close"]
    assert config.read_bytes() == content
    assert Path(result["temporary_cwd"]) != tmp_path


def test_missing_asset_smoke_returns_failure_without_modal_dialog(tmp_path):
    report = tmp_path / "failure-smoke.json"
    script = (f"import sys;sys.path.insert(0,{str(ROOT)!r});from pathlib import Path;"
              "from src.gui.v2 import startup_splash;startup_splash.ICON_PATH=Path('absent-icon.png');"
              "import main_fluent;raise SystemExit(main_fluent.main())")
    environment = {**os.environ, "ORDENASION_SMOKE": "1", "ORDENASION_SMOKE_REPORT": str(report),
                   "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    process = subprocess.run([sys.executable, "-B", "-c", script], cwd=tmp_path, env=environment,
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 1
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["status"] == "error" and not result["assets"]["icon"]
    assert "Assets incompletos" in result["error"]
