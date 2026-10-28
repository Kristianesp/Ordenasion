# -*- mode: python ; coding: utf-8 -*-
# Build onefile de la interfaz Fluent; nunca incluye preferencias del workspace.
from pathlib import Path
import sys

project_root = Path(SPECPATH)
sys.path.insert(0, str(project_root))
from src.utils.version import EXECUTABLE_NAME

datas = [
    (str(project_root / "assets" / "branding"), "assets/branding"),
    (str(project_root / "assets" / "fonts"), "assets/fonts"),
    (str(project_root / "design-tokens.json"), "."),
    (str(project_root / "LICENSE"), "licenses"),
]
binaries = [(str(project_root / "bin" / name), "bin")
            for name in ("smartctl.exe", "fpcalc.exe") if (project_root / "bin" / name).is_file()]
# Hooks oficiales de Qt/WMI reúnen sus recursos transitivos; nada de collect_all.
hiddenimports = ["PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtMultimedia",
                 "PyQt6.sip", "psutil", "wmi", "mutagen"]
excluded_modules = ["matplotlib", "numpy", "reportlab", "schedule", "torch",
                    "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtCharts", "pytest"]

a = Analysis([str(project_root / "main_fluent.py")], pathex=[str(project_root)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=excluded_modules,
    noarchive=False, optimize=0)
# Qt Windows utiliza UCRT e ICU del sistema operativo. No redistribuir copias
# encontradas en PATH de herramientas ajenas: pueden tener ABI incompatible.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in {"ucrtbase.dll", "icuuc.dll", "icudt78.dll"}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name=EXECUTABLE_NAME,
    icon=str(project_root / "assets" / "branding" / "ordenasion-icon.ico"),
    version=str(project_root / "packaging" / "windows_version_info.txt"),
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    upx_exclude=[], runtime_tmpdir=None, console=False,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None)
