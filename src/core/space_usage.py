"""Inventario de tamaños lógicos por ruta, sin seguir enlaces ni modificar archivos."""

from dataclasses import dataclass
import heapq
import os
import shutil
import stat
import time
from typing import Callable


class SpaceScanCancelled(Exception):
    pass


class SpaceScanError(Exception):
    pass


@dataclass(slots=True)
class SpaceNode:
    id: int
    parent_id: int | None
    name: str
    path: str
    kind: str
    size: int = 0
    status: str = "ok"


@dataclass(slots=True)
class SpaceScanResult:
    root_path: str
    nodes: tuple[SpaceNode, ...]
    children: dict[int, tuple[int, ...]]
    top_files: tuple[int, ...]
    top_folders: tuple[int, ...]
    file_count: int
    folder_count: int
    denied_count: int
    missing_count: int
    skipped_links: int
    error_count: int
    volume: tuple[int, int, int] | None


def _is_link(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in {
        getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003),
    }


def scan_space(root_path: str, cancelled: Callable[[], bool] = lambda: False,
               progress: Callable[[int, int, int, int, str], None] = lambda *_: None) -> SpaceScanResult:
    """Recorrido iterativo. Progreso como máximo cada 200 ms; resultado sólo completo."""
    root_path = os.path.abspath(os.path.expanduser(root_path))
    try:
        info = os.lstat(root_path)
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise SpaceScanError("El origen debe ser una carpeta o unidad, sin enlaces.")
    except OSError as error:
        raise SpaceScanError(f"No se puede acceder al origen: {error.strerror or type(error).__name__}") from error
    nodes = [SpaceNode(0, None, os.path.basename(root_path) or root_path, root_path, "folder")]
    children: dict[int, list[int]] = {0: []}
    pending = [0]
    files = folders = denied = missing = links = logical = errors = 0
    last_progress = time.monotonic()

    def check_cancel():
        if cancelled():
            raise SpaceScanCancelled()

    def report(path):
        nonlocal last_progress
        now = time.monotonic()
        if now - last_progress >= 0.2:
            last_progress = now
            progress(files, folders, logical, denied, path)

    def mark_error(node, error):
        nonlocal denied, missing, errors
        if isinstance(error, PermissionError):
            node.status = "denied"
            denied += 1
        elif isinstance(error, FileNotFoundError):
            node.status = "missing"
            missing += 1
        else:
            node.status = "error"
            errors += 1

    while pending:
        check_cancel()
        parent_id = pending.pop()
        parent = nodes[parent_id]
        try:
            with os.scandir(parent.path) as entries:
                for entry in entries:
                    check_cancel()
                    node = SpaceNode(len(nodes), parent_id, entry.name, entry.path, "unknown")
                    nodes.append(node)
                    children[parent_id].append(node.id)
                    try:
                        entry_info = entry.stat(follow_symlinks=False)
                        if _is_link(entry_info):
                            node.kind, node.status = "link", "link"
                            links += 1
                        elif stat.S_ISDIR(entry_info.st_mode):
                            node.kind = "folder"
                            folders += 1
                            children[node.id] = []
                            pending.append(node.id)
                        elif stat.S_ISREG(entry_info.st_mode):
                            node.kind = "file"
                            node.size = max(0, entry_info.st_size)
                            logical += node.size
                            files += 1
                        else:
                            node.status = "unsupported"
                    except OSError as error:
                        mark_error(node, error)
                    report(node.path)
        except OSError as error:
            if parent_id == 0:
                raise SpaceScanError(f"No se puede leer el origen: {error.strerror or type(error).__name__}") from error
            mark_error(parent, error)
        report(parent.path)

    # IDs de hijos siempre mayores: agregación lineal sin recursión.
    for node in reversed(nodes[1:]):
        check_cancel()
        report(node.path)
        parent = nodes[node.parent_id]
        parent.size += node.size
        if node.status in {"denied", "missing", "error", "partial"} and parent.status == "ok":
            parent.status = "partial"
    ordered = {}
    def sort_key(index):
        check_cancel()
        report(nodes[index].path)
        return (-nodes[index].size, nodes[index].name.casefold())
    for parent_id, ids in children.items():
        check_cancel()
        ordered[parent_id] = tuple(sorted(ids, key=sort_key))
    def candidates(kind):
        for node in nodes[1:]:
            check_cancel()
            report(node.path)
            if node.kind == kind:
                yield node
    top_files = tuple(node.id for node in heapq.nlargest(20, candidates("file"), key=lambda node: node.size))
    top_folders = tuple(node.id for node in heapq.nlargest(20, candidates("folder"), key=lambda node: node.size))
    check_cancel()
    try:
        usage = shutil.disk_usage(root_path)
        volume = (usage.total, usage.used, usage.free)
    except OSError:
        volume = None
    return SpaceScanResult(root_path, tuple(nodes), ordered, top_files, top_folders,
                           files, folders, denied, missing, links, errors, volume)
