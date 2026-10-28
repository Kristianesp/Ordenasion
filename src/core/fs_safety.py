#!/usr/bin/env python3
"""
Utilidades de seguridad del sistema de archivos para el flujo "Organizar".

- Detección de carpetas del sistema por componentes de ruta (nunca por
  subcadenas: ``D:\\Backup Windows`` no es una carpeta del sistema).
- Archivos basura o del sistema que nunca deben moverse (desktop.ini,
  Thumbs.db, ~$borradores de Office, .DS_Store, oculto+sistema).
- Enlaces simbólicos y junctions: no se siguen al recorrer carpetas.
- Rutas largas en Windows (prefijo ``\\\\?\\``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable, Optional, Set

IS_WINDOWS = sys.platform == "win32"

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4

# Nombres que son del sistema en cualquier nivel de la ruta
SYSTEM_COMPONENT_NAMES = frozenset(
    {
        "$recycle.bin",
        "recycler",
        "system volume information",
        "$windows.~bt",
        "$windows.~ws",
        "$winreagent",
        "$sysreset",
        "config.msi",
        "msdownld.tmp",
        "windowsapps",
        "wpsystem",
    }
)

# Nombres que solo son del sistema cuando cuelgan directamente de la raíz
# de una unidad (C:\Windows, D:\Program Files de otra instalación, ...)
DRIVE_ROOT_SYSTEM_NAMES = frozenset(
    {
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "recovery",
        "boot",
        "perflogs",
    }
)

# Archivos que el sistema o las aplicaciones generan y no deben organizarse
JUNK_FILE_NAMES = frozenset(
    {
        "desktop.ini",
        "thumbs.db",
        "ehthumbs.db",
        "ehthumbs_vista.db",
        ".ds_store",
        "icon\r",
        "pagefile.sys",
        "hiberfil.sys",
        "swapfile.sys",
    }
)


def normalize(path) -> str:
    """Normaliza una ruta para compararla (mayúsculas/minúsculas en Windows)."""
    return os.path.normcase(os.path.normpath(str(path)))


def is_inside(path, parent) -> bool:
    """True si ``path`` es ``parent`` o está dentro de él (por componentes)."""
    child = normalize(path)
    base = normalize(parent)
    if child == base:
        return True
    base_with_sep = base if base.endswith(os.sep) else base + os.sep
    return child.startswith(base_with_sep)


def system_directories() -> Set[str]:
    """Carpetas reales del sistema según el entorno (normalizadas)."""
    candidates = []
    for variable in (
        "SystemRoot",
        "windir",
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramW6432",
        "ProgramData",
    ):
        value = os.environ.get(variable)
        if value:
            candidates.append(value)
    return {normalize(candidate) for candidate in candidates}


_SYSTEM_DIRS_CACHE: Optional[Set[str]] = None


def _cached_system_directories() -> Set[str]:
    global _SYSTEM_DIRS_CACHE
    if _SYSTEM_DIRS_CACHE is None:
        _SYSTEM_DIRS_CACHE = system_directories()
    return _SYSTEM_DIRS_CACHE


def _is_drive_root(path: Path) -> bool:
    drive, rest = os.path.splitdrive(str(path))
    return bool(drive) and rest in ("", "\\", "/")


def is_system_path(
    path,
    root=None,
    system_dirs: Optional[Iterable[str]] = None,
) -> bool:
    """Determina si ``path`` es (o está dentro de) una carpeta del sistema.

    La comprobación se hace por componentes relativos a ``root`` (la carpeta
    analizada) y contra las carpetas reales del sistema; nunca por subcadenas.
    """
    candidate = Path(path)
    dirs = set(system_dirs) if system_dirs is not None else _cached_system_directories()
    normalized = normalize(candidate)
    for system_dir in dirs:
        if normalized == system_dir or is_inside(normalized, system_dir):
            return True

    # Componentes relativos a la carpeta analizada
    if root is not None:
        try:
            relative_parts = candidate.relative_to(Path(root)).parts
        except ValueError:
            relative_parts = candidate.parts
        base = Path(root)
    else:
        relative_parts = candidate.parts
        base = None

    current = base
    for part in relative_parts:
        lowered = part.lower()
        if lowered in SYSTEM_COMPONENT_NAMES:
            return True
        parent_is_drive_root = current is not None and _is_drive_root(current)
        if parent_is_drive_root and lowered in DRIVE_ROOT_SYSTEM_NAMES:
            return True
        current = (current / part) if current is not None else Path(part)
    return False


def has_hidden_system_attributes(stat_result) -> bool:
    """True para elementos con atributos oculto+sistema (solo Windows)."""
    attributes = getattr(stat_result, "st_file_attributes", 0) or 0
    required = FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM
    return attributes & required == required


def is_junk_file_name(name: str) -> bool:
    """Archivos basura o del sistema (desktop.ini, Thumbs.db, ~$*, .DS_Store)."""
    lowered = name.lower()
    if lowered in JUNK_FILE_NAMES:
        return True
    if lowered.startswith("~$"):
        return True
    if lowered.startswith("._"):  # metadatos de macOS en unidades FAT/exFAT
        return True
    return False


def is_link_or_junction(entry_or_path) -> bool:
    """Detecta enlaces simbólicos y junctions sin seguirlos.

    No se usa el atributo genérico de "reparse point": OneDrive y otros
    proveedores en la nube lo ponen en carpetas normales que sí deben
    organizarse.
    """
    try:
        if isinstance(entry_or_path, os.DirEntry):
            if entry_or_path.is_symlink():
                return True
            is_junction = getattr(entry_or_path, "is_junction", None)
            return bool(callable(is_junction) and is_junction())

        path = str(entry_or_path)
        if os.path.islink(path):
            return True
        isjunction = getattr(os.path, "isjunction", None)
        return bool(callable(isjunction) and isjunction(path))
    except OSError:
        return False


def long_path(path) -> str:
    """Devuelve la ruta con prefijo ``\\\\?\\`` en Windows para superar MAX_PATH.

    En otros sistemas (o con rutas relativas) devuelve la ruta sin cambios.
    """
    text = str(path)
    if not IS_WINDOWS:
        return text
    if text.startswith("\\\\?\\") or not os.path.isabs(text):
        return text
    text = os.path.normpath(text)
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text
