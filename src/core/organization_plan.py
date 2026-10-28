#!/usr/bin/env python3
"""
Plan de organización compartido entre la vista previa y el worker.

El plan se calcula una sola vez (al revisar) y el worker lo ejecuta tal cual,
de modo que lo que el usuario confirma en la vista previa es exactamente lo
que se mueve. El worker solo vuelve a comprobar en el momento de mover si el
destino se ha ocupado entretanto (nunca sobrescribe algo no previsto).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set

from src.utils.constants import LEGACY_VARIOS_FOLDERS, VARIOS_FOLDER

from .fs_safety import is_inside
from .organization_conflicts import (
    CONFLICT_POLICY_RENAME,
    build_base_destination,
    category_to_folder,
    resolve_destination,
)

ACTION_MOVE = "move"
ACTION_RENAME = "rename"
ACTION_OVERWRITE = "overwrite"
ACTION_SKIP = "skip"
ACTION_INVALID = "invalid"
ACTION_MISSING = "missing"

STATUS_NO_CONFLICT = "Sin conflicto"
STATUS_CATEGORY_FOLDER = "Omitido: ya es una carpeta de categoría"
STATUS_INSIDE_SOURCE = "Omitido: el destino está dentro del propio elemento"
STATUS_MISSING = "Omitido: el elemento ya no existe"


@dataclass
class PlanItem:
    """Un elemento del plan: qué se mueve, adónde y por qué."""

    kind: str  # "folder" | "file"
    source: Path
    category: str
    base_destination: Path
    destination: Path
    action: str
    status: str
    size: int = 0
    movement: Dict = field(default_factory=dict, repr=False)

    @property
    def is_folder(self) -> bool:
        return self.kind == "folder"

    @property
    def conflict(self) -> bool:
        return self.status != STATUS_NO_CONFLICT

    @property
    def will_move(self) -> bool:
        return self.action in (ACTION_MOVE, ACTION_RENAME, ACTION_OVERWRITE)


@dataclass
class OrganizationPlan:
    source_folder: str
    conflict_policy: str
    organize_by_date: bool
    check_duplicates: bool
    items: List[PlanItem] = field(default_factory=list)

    @property
    def folder_items(self) -> List[PlanItem]:
        return [item for item in self.items if item.kind == "folder"]

    @property
    def file_items(self) -> List[PlanItem]:
        return [item for item in self.items if item.kind == "file"]

    @property
    def conflict_count(self) -> int:
        return sum(1 for item in self.items if item.conflict)

    @property
    def skipped_count(self) -> int:
        return sum(1 for item in self.items if not item.will_move)

    @property
    def invalid_count(self) -> int:
        return sum(1 for item in self.items if item.action in (ACTION_INVALID, ACTION_MISSING))

    def matches(self, source_folder: str, conflict_policy: str, organize_by_date: bool) -> bool:
        """Indica si el plan sigue siendo válido para estos parámetros."""
        return (
            os.path.normcase(os.path.normpath(str(self.source_folder)))
            == os.path.normcase(os.path.normpath(str(source_folder)))
            and self.conflict_policy == conflict_policy
            and bool(self.organize_by_date) == bool(organize_by_date)
        )


class DirectoryListingCache:
    """Comprueba existencia leyendo cada carpeta de destino una sola vez.

    Evita un ``stat()`` por elemento al construir el plan de miles de archivos.
    La comparación respeta las reglas del sistema (sin distinción de
    mayúsculas en Windows).
    """

    def __init__(self):
        self._listings: Dict[str, Optional[Set[str]]] = {}

    def _listing(self, folder: Path) -> Optional[Set[str]]:
        key = os.path.normcase(str(folder))
        if key not in self._listings:
            try:
                with os.scandir(folder) as entries:
                    self._listings[key] = {os.path.normcase(entry.name) for entry in entries}
            except FileNotFoundError:
                self._listings[key] = set()
            except OSError:
                self._listings[key] = None  # sin acceso: se usará exists()
        return self._listings[key]

    def exists(self, path: Path) -> bool:
        listing = self._listing(path.parent)
        if listing is None:
            return os.path.lexists(path)
        return os.path.normcase(path.name) in listing


def known_category_folder_names(
    categories: Iterable[str],
    category_folder: Optional[Callable[[str], str]] = None,
) -> Set[str]:
    """Nombres (normalizados) de las carpetas de categoría de primer nivel."""
    resolver = category_folder or category_to_folder
    names = {VARIOS_FOLDER, *LEGACY_VARIOS_FOLDERS}
    for category in categories:
        folder = resolver(category)
        if folder:
            names.add(folder.split("/")[0])
    return {os.path.normcase(name) for name in names}


def _file_mtime(movement: Dict, file_path: Path) -> Optional[float]:
    value = movement.get("date")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return file_path.stat().st_mtime
    except OSError:
        return None


def build_organization_plan(
    source_folder: str,
    folder_movements: List[Dict],
    file_movements: List[Dict],
    conflict_policy: str = CONFLICT_POLICY_RENAME,
    organize_by_date: bool = False,
    check_duplicates: bool = False,
    category_folder: Optional[Callable[[str], str]] = None,
    category_folder_names: Optional[Set[str]] = None,
) -> OrganizationPlan:
    """Calcula el destino de cada elemento seleccionado.

    Mismo orden que la ejecución: primero carpetas y después archivos; los
    destinos ya reservados por elementos anteriores cuentan como ocupados.
    """
    plan = OrganizationPlan(
        source_folder=str(source_folder),
        conflict_policy=conflict_policy,
        organize_by_date=bool(organize_by_date),
        check_duplicates=bool(check_duplicates),
    )
    cache = DirectoryListingCache()
    reserved: Set[Path] = set()
    root = Path(source_folder)
    folder_names = category_folder_names
    if folder_names is None:
        folder_names = known_category_folder_names(
            [mov.get("category", "") for mov in list(folder_movements) + list(file_movements)],
            category_folder,
        )

    for mov in folder_movements:
        folder = Path(mov["folder"])
        category = mov.get("category", "VARIOS")
        base_destination = build_base_destination(
            str(source_folder),
            category,
            folder.name,
            organize_by_date=False,
            category_folder=category_folder,
        )
        item = PlanItem(
            kind="folder",
            source=folder,
            category=category,
            base_destination=base_destination,
            destination=base_destination,
            action=ACTION_MOVE,
            status=STATUS_NO_CONFLICT,
            size=int(mov.get("size", 0) or 0),
            movement=mov,
        )
        is_category_folder = (
            folder.parent == root and os.path.normcase(folder.name) in folder_names
        )
        if is_category_folder:
            item.action, item.status = ACTION_INVALID, STATUS_CATEGORY_FOLDER
        elif is_inside(base_destination, folder):
            item.action, item.status = ACTION_INVALID, STATUS_INSIDE_SOURCE
        elif not cache.exists(folder):
            item.action, item.status = ACTION_MISSING, STATUS_MISSING
        else:
            resolved = resolve_destination(
                base_destination,
                conflict_policy=conflict_policy,
                is_folder=True,
                reserved=reserved,
                exists=cache.exists,
            )
            item.destination, item.action, item.status = (
                resolved.destination,
                resolved.action,
                resolved.status,
            )
            reserved.add(resolved.destination)
        plan.items.append(item)

    for mov in file_movements:
        file_path = Path(mov["file"])
        category = mov.get("category", "VARIOS")
        modified_at = _file_mtime(mov, file_path) if organize_by_date else None
        base_destination = build_base_destination(
            str(source_folder),
            category,
            file_path.name,
            organize_by_date=organize_by_date,
            modified_at=modified_at,
            category_folder=category_folder,
        )
        item = PlanItem(
            kind="file",
            source=file_path,
            category=category,
            base_destination=base_destination,
            destination=base_destination,
            action=ACTION_MOVE,
            status=STATUS_NO_CONFLICT,
            size=int(mov.get("size", 0) or 0),
            movement=mov,
        )
        if not cache.exists(file_path) or (organize_by_date and modified_at is None):
            item.action, item.status = ACTION_MISSING, STATUS_MISSING
        else:
            resolved = resolve_destination(
                base_destination,
                conflict_policy=conflict_policy,
                is_folder=False,
                reserved=reserved,
                exists=cache.exists,
            )
            item.destination, item.action, item.status = (
                resolved.destination,
                resolved.action,
                resolved.status,
            )
            if resolved.action != ACTION_SKIP:
                reserved.add(resolved.destination)
        plan.items.append(item)

    return plan
