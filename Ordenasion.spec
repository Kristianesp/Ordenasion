# -*- mode: python ; coding: utf-8 -*-
# Build de la interfaz Fluent; nunca incluye preferencias del workspace.
# Por defecto: un único .exe (onefile) con imagen de carga mientras se
# descomprime. Con ORDENASION_ONEDIR=1: carpeta portable, que no descomprime
# nada al arrancar y abre mucho más rápido.
from pathlib import Path
import os
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
# Las páginas y diálogos que se importan bajo demanda (dentro de funciones)
# se declaran también aquí: la página Organizar es nativa y ya no existe la
# ventana heredada que los arrastraba al arrancar.
lazy_gui_modules = ["src.gui.v2.pages.organize_page", "src.gui.v2.pages.organize_support",
                    "src.gui.v2.pages.feature_pages", "src.gui.config_dialog", "src.gui.rule_panel",
                    "src.gui.operation_summary_dialog", "src.gui.preview_dialog", "src.gui.task_center",
                    "src.gui.disk_viewer", "src.gui.music_duplicates_view", "src.gui.duplicates_dashboard",
                    "src.gui.v2.release_smoke", "src.gui.v2.release_e2e"]
hiddenimports = ["PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtMultimedia",
                 "PyQt6.sip", "psutil", "wmi", "mutagen", *lazy_gui_modules]
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
exe_options = dict(name=EXECUTABLE_NAME,
    icon=str(project_root / "assets" / "branding" / "ordenasion-icon.ico"),
    version=str(project_root / "packaging" / "windows_version_info.txt"),
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    upx_exclude=[], runtime_tmpdir=None, console=False,
    disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
    codesign_identity=None, entitlements_file=None)

if os.environ.get("ORDENASION_ONEDIR") == "1":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_options)
    coll = COLLECT(exe, a.binaries, a.datas, name=EXECUTABLE_NAME, strip=False, upx=False)
else:
    # La imagen aparece al instante, mientras el .exe se descomprime en %TEMP%;
    # main_fluent la cierra cuando ya se ve el splash de Qt.
    splash = Splash(str(project_root / "packaging" / "splash.png"), binaries=a.binaries,
                    datas=a.datas, text_pos=None, always_on_top=True)
    exe = EXE(pyz, a.scripts, splash, splash.binaries, a.binaries, a.datas, [], **exe_options)
