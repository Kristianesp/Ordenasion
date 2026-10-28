#!/usr/bin/env python3
"""Resolución compartida de conflictos de organización."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


CONFLICT_POLICY_RENAME = "rename"
CONFLICT_POLICY_OVERWRITE = "overwrite"
CONFLICT_POLICY_SKIP = "skip"


@dataclass(frozen=True)
class ConflictResolution:
    destination: Path
    status: str
    action: str
    conflict: bool


def build_base_destination(
    source_folder: str,
    category: str,
    name: str,
    organize_by_date: bool = False,
    modified_at: float | None = None,
) -> Path:
    base_folder = "VARIOS" if category == "VARIOS" else category
    base_path = Path(source_folder) / base_folder
    if organize_by_date and modified_at is not None:
        date_info = datetime.fromtimestamp(modified_at)
        base_path = base_path / str(date_info.year) / f"{date_info.month:02d}"
    return base_path / name


def build_numbered_name(path: Path, counter: int) -> Path:
    suffix = path.suffix
    stem = path.stem
    return path.parent / f"{stem} ({counter}){suffix}"


def find_available_name(path: Path, reserved: set[Path] | None = None) -> Path:
    reserved = reserved or set()
    if not path.exists() and path not in reserved:
        return path
    counter = 1
    candidate = build_numbered_name(path, counter)
    while candidate.exists() or candidate in reserved:
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
) -> ConflictResolution:
    exists = base_destination.exists() or base_destination in (reserved or set())
    if not exists:
        return ConflictResolution(
            destination=base_destination,
            status="Sin conflicto",
            action="move",
            conflict=False,
        )

    if is_folder or conflict_policy == CONFLICT_POLICY_RENAME:
        destination = find_available_name(base_destination, reserved)
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
