#!/usr/bin/env python3
"""Resolución compartida de conflictos de organización."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional

from src.utils.constants import LEGACY_VARIOS_FOLDERS, VARIOS_CATEGORY, VARIOS_FOLDER


CONFLICT_POLICY_RENAME = "rename"
CONFLICT_POLICY_OVERWRITE = "overwrite"
CONFLICT_POLICY_SKIP = "skip"


@dataclass(frozen=True)
class ConflictResolution:
    destination: Path
    status: str
    action: str
    conflict: bool


ExistsFn = Callable[[Path], bool]


def _default_exists(path: Path) -> bool:
    return path.exists()


def category_to_folder(
    category: str,
    nested_categories: Optional[Mapping[str, list]] = None,
) -> str:
    """Carpeta (relativa a la raíz) donde se guarda una categoría.

    Es la ÚNICA función que traduce categoría → carpeta; la usan la vista
    previa, el plan y el worker. VARIOS (y el nombre antiguo VARIOS_REVISAR)
    van a ``VARIOS_FOLDER``. Una categoría anidada (hija de otra en
    ``nested_categories``) se guarda dentro de la carpeta de su padre.
    """
    name = str(category or VARIOS_CATEGORY).strip() or VARIOS_CATEGORY
    upper = name.upper()
    if upper == VARIOS_CATEGORY or upper in {n.upper() for n in LEGACY_VARIOS_FOLDERS}:
        return VARIOS_FOLDER
    if nested_categories:
        chain = [name]
        seen = {name}
        current = name
        while True:
            parent = next(
                (
                    parent_name
                    for parent_name, children in nested_categories.items()
                    if current in (children or [])
                ),
                None,
            )
            if parent is None or parent in seen:
                break
            chain.append(parent)
            seen.add(parent)
            current = parent
        if len(chain) > 1:
            return "/".join(reversed(chain))
    return name


def build_base_destination(
    source_folder: str,
    category: str,
    name: str,
    organize_by_date: bool = False,
    modified_at: float | None = None,
    category_folder: Optional[Callable[[str], str]] = None,
) -> Path:
    folder = category_folder(category) if category_folder else category_to_folder(category)
    base_path = Path(source_folder).joinpath(*folder.split("/"))
    if organize_by_date and modified_at is not None:
        date_info = datetime.fromtimestamp(modified_at)
        base_path = base_path / str(date_info.year) / f"{date_info.month:02d}"
    return base_path / name


def build_numbered_name(path: Path, counter: int) -> Path:
    suffix = path.suffix
    stem = path.stem
    return path.parent / f"{stem} ({counter}){suffix}"


def find_available_name(
    path: Path,
    reserved: set[Path] | None = None,
    exists: ExistsFn | None = None,
) -> Path:
    reserved = reserved or set()
    exists = exists or _default_exists
    if not exists(path) and path not in reserved:
        return path
    counter = 1
    candidate = build_numbered_name(path, counter)
    while exists(candidate) or candidate in reserved:
        counter += 1
        candidate = build_numbered_name(path, counter)
    return candidate


def conflict_status_for_destination(destination: Path) -> str:
    return "Ya existe en destino" if destination.exists() else "Sin conflicto"


def resolve_destination(
    base_destination: Path,
    conflict_policy: str = CONFLICT_POLICY_RENAME,
    is_folder: bool = False,
    reserved: set[Path] | None = None,
    exists: ExistsFn | None = None,
) -> ConflictResolution:
    exists_fn = exists or _default_exists
    occupied = exists_fn(base_destination) or base_destination in (reserved or set())
    if not occupied:
        return ConflictResolution(
            destination=base_destination,
            status="Sin conflicto",
            action="move",
            conflict=False,
        )

    if is_folder or conflict_policy == CONFLICT_POLICY_RENAME:
        destination = find_available_name(base_destination, reserved, exists_fn)
        return ConflictResolution(
            destination=destination,
            status=f"Se renombrará a {destination.name}",
            action="rename",
            conflict=True,
        )

    if conflict_policy == CONFLICT_POLICY_SKIP:
        return ConflictResolution(
            destination=base_destination,
            status="Se omitirá por conflicto",
            action="skip",
            conflict=True,
        )

    return ConflictResolution(
        destination=base_destination,
        status="Se sobrescribirá el archivo existente",
        action="overwrite",
        conflict=True,
    )
