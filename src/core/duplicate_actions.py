#!/usr/bin/env python3
"""
Acciones compartidas sobre grupos de duplicados (generales y de música).

- Selección de la copia a conservar con reglas configurables.
- Validación: nunca se retiran todas las copias de un grupo.
- Plan de acciones (retirar a la papelera, mover, sustituir por hardlink)
  exportable a CSV.
- ``DuplicateActionWorker`` ejecuta el plan fuera del hilo de la interfaz y
  verifica el contenido (hash completo y, opcionalmente, byte a byte) contra
  la copia que se conserva antes de tocar cada archivo.
"""

from __future__ import annotations

import csv
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from PyQt6.QtCore import QThread, pyqtSignal

from src.utils.logger import warn
from .hash_manager import HashCancelled, HashManager

ACTION_DELETE = "delete"
ACTION_MOVE = "move"
ACTION_HARDLINK = "hardlink"

ACTION_LABELS = {
    ACTION_DELETE: "Retirar a la papelera",
    ACTION_MOVE: "Mover",
    ACTION_HARDLINK: "Sustituir por hardlink",
}

KEEP_RULES: Dict[str, str] = {
    "newest": "Más reciente",
    "oldest": "Más antiguo",
    "preferred_folder": "En carpeta preferida",
    "clean_name": "Nombre sin \" (1)\" ni \"copia\"",
    "shortest_path": "Ruta más corta",
}
DEFAULT_KEEP_RULE = "newest"

_COPY_SUFFIX = re.compile(r"(?i)(\s*\(\d+\)|\s*[-_ ]\s*(copia|copy)(\s*\(\d+\))?|\s+copia de)$")
_COPY_PREFIX = re.compile(r"(?i)^(copia de|copy of)\s+")


def has_copy_marker(name: str) -> bool:
    """True si el nombre parece una copia: 'foto (1).jpg', 'foto - copia.jpg'..."""
    stem = Path(name).stem
    return bool(_COPY_SUFFIX.search(stem) or _COPY_PREFIX.search(stem))


def _norm(path: Any) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _is_under(path: str, folder: str) -> bool:
    folder_n = _norm(folder).rstrip("\\/")
    path_n = _norm(path)
    return path_n == folder_n or path_n.startswith(folder_n + os.sep)


def _date(item: Mapping[str, Any]) -> float:
    for key in ("date", "mtime"):
        value = item.get(key)
        if value:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return 0.0


def _path(item: Mapping[str, Any]) -> str:
    return str(item.get("path") or item.get("file_path") or "")


def choose_keep_index(
    files: Sequence[Mapping[str, Any]],
    rule: str = DEFAULT_KEEP_RULE,
    preferred_folders: Sequence[str] = (),
    preferred_path: Optional[str] = None,
) -> int:
    """Índice del archivo a conservar según la regla (con desempates estables)."""
    if not files:
        return -1
    if preferred_path:
        target = _norm(preferred_path)
        for index, item in enumerate(files):
            if _norm(_path(item)) == target:
                return index

    def key(index: int):
        item = files[index]
        path = _path(item)
        in_preferred = any(_is_under(path, folder) for folder in preferred_folders or ())
        clean = not has_copy_marker(Path(path).name)
        newest = -_date(item)
        primary: tuple
        if rule == "oldest":
            primary = (_date(item),)
        elif rule == "preferred_folder":
            primary = (not in_preferred, newest)
        elif rule == "clean_name":
            primary = (not clean, newest)
        elif rule == "shortest_path":
            primary = (len(path), newest)
        else:
            primary = (newest,)
        return primary + (not in_preferred, not clean, len(path), path.lower())

    return min(range(len(files)), key=key)


def find_emptied_groups(
    groups: Mapping[str, Sequence[Any]],
    marked: Iterable[Any],
    exists: Callable[[str], bool] = os.path.exists,
) -> List[str]:
    """Claves de los grupos en los que no quedaría ninguna copia sin marcar."""
    marked_set = {_norm(p) for p in marked}
    emptied = []
    for key, paths in groups.items():
        normalized = [_norm(_path(p) if isinstance(p, Mapping) else p) for p in paths]
        if not any(p in marked_set for p in normalized):
            continue
        if not any(p not in marked_set and exists(p) for p in normalized):
            emptied.append(key)
    return emptied


@dataclass
class PlanItem:
    action: str
    source: str
    reference: str           # copia que se conserva y contra la que se verifica
    group_key: str
    size: int = 0
    destination: str = ""
    confirmed: bool = False  # el grupo ya estaba confirmado por hash completo
    similar_only: bool = False  # grupo de imágenes parecidas (no idénticas)
    status: str = "pendiente"
    reason: str = ""
    item_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_plan(
    groups: Mapping[str, Sequence[Any]],
    marked: Iterable[Any],
    action: str,
    *,
    sizes: Optional[Mapping[str, int]] = None,
    keep_paths: Optional[Mapping[str, str]] = None,
    destination_dir: Optional[str] = None,
    group_meta: Optional[Mapping[str, Mapping[str, Any]]] = None,
    exists: Callable[[str], bool] = os.path.exists,
) -> List[PlanItem]:
    """Construye el plan para los archivos marcados.

    Cada archivo marcado se verifica contra una copia sin marcar del mismo
    grupo (la preferida si está en ``keep_paths``).  Los grupos que quedarían
    vacíos no generan acciones: hay que bloquearlos antes con
    :func:`find_emptied_groups`.
    """
    marked_norm = {_norm(p) for p in marked}
    plan: List[PlanItem] = []
    for key, paths in groups.items():
        str_paths = [_path(p) if isinstance(p, Mapping) else str(p) for p in paths]
        selected = [p for p in str_paths if _norm(p) in marked_norm]
        if not selected:
            continue
        retained = [p for p in str_paths if _norm(p) not in marked_norm and exists(p)]
        if not retained:
            continue
        reference = retained[0]
        preferred = (keep_paths or {}).get(key)
        if preferred and any(_norm(preferred) == _norm(p) for p in retained):
            reference = preferred
        meta = dict((group_meta or {}).get(key) or {})
        for source in selected:
            destination = ""
            if action == ACTION_MOVE and destination_dir:
                destination = str(Path(destination_dir) / Path(source).name)
            plan.append(
                PlanItem(
                    action=action,
                    source=source,
                    reference=reference,
                    group_key=key,
                    size=int((sizes or {}).get(source, 0) or 0),
                    destination=destination,
                    confirmed=bool(meta.get("confirmed")),
                    similar_only=meta.get("method") == "similar",
                )
            )
    return plan


CSV_FIELDS = ["accion", "origen", "se_conserva", "grupo", "tamaño_bytes", "destino", "estado", "motivo"]


def export_plan_csv(plan: Sequence[PlanItem], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(CSV_FIELDS)
        for item in plan:
            writer.writerow([
                ACTION_LABELS.get(item.action, item.action),
                item.source,
                item.reference,
                item.group_key,
                item.size,
                item.destination,
                item.status,
                item.reason,
            ])


def unique_destination(destination: Path) -> Path:
    candidate = destination
    counter = 1
    while candidate.exists():
        candidate = destination.with_name(f"{destination.stem}_{counter}{destination.suffix}")
        counter += 1
    return candidate


def verify_item(item: PlanItem, hash_manager: HashManager, *, verify_bytes: bool = False,
                cancel_event=None) -> Optional[str]:
    """Comprueba que ``source`` es idéntico a ``reference``. Devuelve el motivo si no."""
    source, reference = Path(item.source), Path(item.reference)
    if not source.exists():
        return "el archivo ya no existe"
    if not reference.exists():
        return "la copia que se conserva ya no existe"
    try:
        st_s, st_r = os.stat(source), os.stat(reference)
    except OSError as exc:
        return f"no accesible: {exc.strerror or exc}"
    if st_s.st_ino and st_s.st_ino == st_r.st_ino and st_s.st_dev == st_r.st_dev:
        return "es un hardlink de la copia que se conserva (no libera espacio)"
    if item.similar_only:
        return None  # imágenes parecidas: se confirmó explícitamente en la interfaz
    if st_s.st_size != st_r.st_size:
        return "el tamaño ya no coincide con la copia que se conserva"
    results = hash_manager.hash_many([source, reference], allow_partial=False,
                                     cancel_event=cancel_event, max_workers=2)
    rs, rr = results.get(source), results.get(reference)
    if not rs or not rs.ok:
        return f"no se pudo calcular el hash: {rs.error if rs else 'sin resultado'}"
    if not rr or not rr.ok:
        return f"no se pudo calcular el hash de la copia: {rr.error if rr else 'sin resultado'}"
    if rs.value != rr.value:
        return "el contenido no es idéntico (hash distinto)"
    if verify_bytes and not HashManager.files_identical(source, reference, cancel_event):
        return "el contenido no es idéntico (comparación byte a byte)"
    return None


def replace_with_hardlink(source: Path, reference: Path) -> Optional[str]:
    """Sustituye ``source`` por un hardlink a ``reference``. Devuelve el error o None."""
    try:
        st_s, st_r = os.stat(source), os.stat(reference)
    except OSError as exc:
        return f"no accesible: {exc.strerror or exc}"
    if st_s.st_dev != st_r.st_dev:
        return "están en volúmenes distintos (los hardlinks requieren el mismo volumen NTFS)"
    if not HashManager.files_identical(source, reference):
        return "el contenido no es idéntico (comparación byte a byte)"
    temp = source.with_name(f".{source.name}.{uuid.uuid4().hex[:8]}.lnk_tmp")
    try:
        os.link(reference, temp)
        os.replace(temp, source)
        return None
    except OSError as exc:
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass
        return f"no se pudo crear el hardlink: {exc.strerror or exc}"


class DuplicateActionWorker(QThread):
    """Ejecuta un plan de acciones en segundo plano con verificación previa."""

    progress = pyqtSignal(str, int, int)
    item_finished = pyqtSignal(dict)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, plan: Sequence[PlanItem], transaction_manager, *,
                 verify_hash: bool = True, verify_bytes: bool = False,
                 hash_manager: Optional[HashManager] = None,
                 on_success: Optional[Callable[[PlanItem], None]] = None):
        super().__init__()
        self.plan = list(plan)
        self.transaction_manager = transaction_manager
        self.verify_hash = verify_hash
        self.verify_bytes = verify_bytes
        self.hash_manager = hash_manager or HashManager()
        self.cancel_event = threading.Event()
        self.on_success = on_success

    def stop(self):
        self.cancel_event.set()
        self.requestInterruption()

    def _cancelled(self) -> bool:
        return self.cancel_event.is_set() or self.isInterruptionRequested()

    def run(self):
        summary = {"done": [], "skipped": [], "failed": [], "cancelled": False, "bytes": 0}
        total = len(self.plan)
        try:
            for index, item in enumerate(self.plan, start=1):
                if self._cancelled():
                    summary["cancelled"] = True
                    break
                self.progress.emit(f"{ACTION_LABELS.get(item.action, item.action)}: {Path(item.source).name}",
                                   index, total)
                reason = None
                if self.verify_hash or item.action == ACTION_HARDLINK:
                    try:
                        reason = verify_item(item, self.hash_manager,
                                             verify_bytes=self.verify_bytes,
                                             cancel_event=self.cancel_event)
                    except HashCancelled:
                        summary["cancelled"] = True
                        break
                if reason:
                    item.status, item.reason = "omitido", reason
                    summary["skipped"].append(item.to_dict())
                    self.item_finished.emit(item.to_dict())
                    continue
                error_reason = self._execute(item)
                if error_reason:
                    item.status, item.reason = "error", error_reason
                    summary["failed"].append(item.to_dict())
                else:
                    item.status = "hecho"
                    summary["done"].append(item.to_dict())
                    summary["bytes"] += item.size
                    if self.on_success:
                        try:
                            self.on_success(item)
                        except Exception as exc:  # el callback no debe abortar el lote
                            warn(f"on_success falló: {exc}")
                self.item_finished.emit(item.to_dict())
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        summary["plan"] = [item.to_dict() for item in self.plan]
        self.finished_ok.emit(summary)

    def _execute(self, item: PlanItem) -> Optional[str]:
        source = Path(item.source)
        tm = self.transaction_manager
        if item.action == ACTION_DELETE:
            if tm.safe_delete_file(source, use_trash=True):
                item.destination = str(getattr(tm, "last_removal_destination", "") or "")
                return None
            return getattr(tm, "last_error", None) or "motivo no disponible"
        if item.action == ACTION_MOVE:
            if not item.destination:
                return "sin carpeta de destino"
            destination = unique_destination(Path(item.destination))
            destination.parent.mkdir(parents=True, exist_ok=True)
            if tm.safe_move_file(source, destination):
                item.destination = str(destination)
                return None
            return getattr(tm, "last_error", None) or "motivo no disponible"
        if item.action == ACTION_HARDLINK:
            return replace_with_hardlink(source, Path(item.reference))
        return f"acción desconocida: {item.action}"
