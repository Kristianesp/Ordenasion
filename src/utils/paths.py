#!/usr/bin/env python3
"""Rutas de datos de usuario (configuración, cachés y registros).

Los datos viven en %LOCALAPPDATA%\\Ordenasion en Windows (o en
$XDG_DATA_HOME/Ordenasion en otros sistemas), nunca en el directorio de
trabajo: instalada en Program Files la aplicación no puede escribir allí.
La variable de entorno ORDENASION_DATA_DIR permite redirigirlos (tests).
"""

import os
import shutil
import sys
from pathlib import Path

APP_DIR_NAME = "Ordenasion"


def user_data_dir() -> Path:
    override = os.environ.get("ORDENASION_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        base = Path(root) / APP_DIR_NAME
    else:
        root = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(root) / APP_DIR_NAME
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return base


def _legacy_locations(name: str):
    """Ubicaciones antiguas (versiones <= 3.5 guardaban junto al cwd o al exe)."""
    seen = set()
    candidates = [Path.cwd() / name]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / name)
    for candidate in candidates:
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            yield candidate


def user_data_file(name: str) -> Path:
    """Ruta de un archivo de datos; copia una vez el archivo de la ubicación antigua."""
    target = user_data_dir() / name
    if not target.exists() and not os.environ.get("ORDENASION_DATA_DIR"):
        for legacy in _legacy_locations(name):
            try:
                if legacy.is_file() and legacy.resolve() != target.resolve():
                    shutil.copy2(legacy, target)
                    break
            except OSError:
                continue
    return target
