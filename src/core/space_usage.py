"""Inventario de tamaños por ruta, sin seguir enlaces ni modificar archivos.

Almacenamiento compacto: en lugar de un objeto con la ruta completa por nodo
se guardan arrays paralelos (padre, nombre, tipo, tamaños, estado) y la ruta se
reconstruye desde el padre cuando se necesita. Además del tamaño lógico se
mide el tamaño en disco (GetCompressedFileSizeW/clúster en Windows, st_blocks
en el resto) contando una sola vez los hardlinks, y se desglosa por extensión.
"""

from __future__ import annotations

import csv
import heapq
import os
import shutil
import stat
import sys
import time
from array import array
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple


class SpaceScanCancelled(Exception):
    pass


class SpaceScanError(Exception):
    pass


KINDS = ("folder", "file", "link", "unknown")
STATUSES = ("ok", "partial", "denied", "missing", "error", "link", "unsupported")
_KIND = {name: index for index, name in enumerate(KINDS)}
_STATUS = {name: index for index, name in enumerate(STATUSES)}
_FOLDER, _FILE, _LINK, _UNKNOWN = (_KIND[name] for name in KINDS)
_PROBLEMS = {_STATUS["denied"], _STATUS["missing"], _STATUS["error"], _STATUS["partial"]}
NO_EXTENSION = "(sin extensión)"
FLAG_HARDLINK_DUPLICATE = 1

# Atributos de Windows que hacen que el tamaño en disco no sea el lógico.
_WIN_COMPRESSED = 0x800
_WIN_SPARSE = 0x200
_WIN_OFFLINE = 0x1000
_WIN_RECALL_ON_OPEN = 0x40000
_WIN_RECALL_ON_DATA_ACCESS = 0x400000
_WIN_SPECIAL = _WIN_COMPRESSED | _WIN_SPARSE | _WIN_OFFLINE | _WIN_RECALL_ON_OPEN | _WIN_RECALL_ON_DATA_ACCESS
_WIN_HARDLINK_MIN_SIZE = 1024 * 1024


@dataclass(slots=True)
class SpaceNode:
    """Nodo independiente (p. ej. para pruebas o para el mapa)."""
    id: int
    parent_id: int | None
    name: str
    path: str
    kind: str
    size: int = 0
    status: str = "ok"
    disk_size: int = 0


class _Raw:
    """Datos medidos por nodo (los totales de carpetas se calculan aparte)."""

    __slots__ = ("root_path", "parents", "names", "kinds", "sizes", "disk", "statuses", "flags")

    def __init__(self, root_path: str):
        self.root_path = root_path
        self.parents = array("i")
        self.names: List[str] = []
        self.kinds = bytearray()
        self.sizes = array("q")
        self.disk = array("q")
        self.statuses = bytearray()
        self.flags = bytearray()

    def append(self, parent: int, name: str, kind: int, size: int = 0, disk: int = 0,
               status: int = 0, flags: int = 0) -> int:
        self.parents.append(parent)
        self.names.append(name)
        self.kinds.append(kind)
        self.sizes.append(size)
        self.disk.append(disk)
        self.statuses.append(status)
        self.flags.append(flags)
        return len(self.names) - 1

    def __len__(self) -> int:
        return len(self.names)


class NodeView:
    """Vista ligera de un nodo; la ruta se reconstruye bajo demanda."""

    __slots__ = ("_result", "id")

    def __init__(self, result: "SpaceScanResult", node_id: int):
        self._result = result
        self.id = node_id

    @property
    def parent_id(self) -> Optional[int]:
        parent = self._result._raw.parents[self.id]
        return None if parent < 0 else parent

    @property
    def name(self) -> str:
        return self._result._raw.names[self.id]

    @property
    def path(self) -> str:
        return self._result.path_of(self.id)

    @property
    def kind(self) -> str:
        return KINDS[self._result._raw.kinds[self.id]]

    @property
    def size(self) -> int:
        return self._result._sizes[self.id]

    @size.setter
    def size(self, value: int) -> None:
        self._result._sizes[self.id] = int(value)

    @property
    def disk_size(self) -> int:
        return self._result._disk[self.id]

    @property
    def status(self) -> str:
        return STATUSES[self._result._statuses[self.id]]

    @status.setter
    def status(self, value: str) -> None:
        self._result._statuses[self.id] = _STATUS[value]

    @property
    def extension(self) -> str:
        return extension_of(self.name)

    def __eq__(self, other):
        return isinstance(other, NodeView) and other._result is self._result and other.id == self.id

    def __hash__(self):
        return hash((id(self._result), self.id))

    def __repr__(self):
        return f"NodeView({self.id}, {self.name!r}, {self.kind}, {self.size})"


class _NodeSequence(Sequence):
    __slots__ = ("_result",)

    def __init__(self, result: "SpaceScanResult"):
        self._result = result

    def __len__(self) -> int:
        return len(self._result._raw)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [NodeView(self._result, i) for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if not 0 <= index < len(self):
            raise IndexError(index)
        return NodeView(self._result, index)

    def __iter__(self) -> Iterator[NodeView]:
        for index in range(len(self)):
            yield NodeView(self._result, index)


class _ChildrenMap(Mapping):
    """Hijos ordenados de cada carpeta en formato CSR (dos arrays de enteros).

    Devuelve tuplas bajo demanda: evita un objeto ``int`` y una tupla por
    nodo mientras el resultado vive en memoria.
    """

    __slots__ = ("_kinds", "_start", "_ids")

    def __init__(self, kinds: bytearray, start: array, ids: array):
        self._kinds, self._start, self._ids = kinds, start, ids

    def __getitem__(self, node_id: int) -> Tuple[int, ...]:
        if not isinstance(node_id, int) or not 0 <= node_id < len(self._kinds) or self._kinds[node_id] != _FOLDER:
            raise KeyError(node_id)
        return tuple(self._ids[self._start[node_id]:self._start[node_id + 1]])

    def __iter__(self):
        return (index for index, kind in enumerate(self._kinds) if kind == _FOLDER)

    def __len__(self) -> int:
        return self._kinds.count(_FOLDER)


class SpaceScanResult:
    """Resultado inmutable en estructura; ``nodes`` expone vistas por nodo."""

    def __init__(self, raw: _Raw, sizes, disk, statuses, children, top_files, top_folders, extensions,
                 counters: Dict[str, int], volume, measured_disk: bool):
        self._raw = raw
        self._sizes = sizes
        self._disk = disk
        self._statuses = statuses
        self.root_path = raw.root_path
        self.children: Mapping = children
        self.top_files: Tuple[int, ...] = top_files
        self.top_folders: Tuple[int, ...] = top_folders
        self.extensions: Dict[str, Tuple[int, int, int]] = extensions
        self.file_count = counters["files"]
        self.folder_count = counters["folders"]
        self.denied_count = counters["denied"]
        self.missing_count = counters["missing"]
        self.skipped_links = counters["links"]
        self.error_count = counters["errors"]
        self.hardlinks_deduped = counters["hardlinks"]
        self.volume = volume
        self.measured_disk = measured_disk
        self.nodes = _NodeSequence(self)

    def path_of(self, node_id: int) -> str:
        parts = []
        parents, names = self._raw.parents, self._raw.names
        while node_id > 0:
            parts.append(names[node_id])
            node_id = parents[node_id]
        if not parts:
            return self.root_path
        parts.reverse()
        return os.path.join(self.root_path, *parts)

    @property
    def disk_size(self) -> int:
        return self._disk[0]

    def subtree_ids(self, node_id: int) -> List[int]:
        """IDs del subárbol (incluido el nodo), sin recursión."""
        result, pending = [], [node_id]
        while pending:
            current = pending.pop()
            result.append(current)
            pending.extend(self.children.get(current, ()))
        return result

    def find(self, path: str) -> Optional[int]:
        """Id del nodo con esa ruta (comparación de nombres por niveles)."""
        try:
            relative = os.path.relpath(os.path.abspath(path), self.root_path)
        except ValueError:
            return None
        if relative == os.curdir:
            return 0
        if relative.startswith(os.pardir):
            return None
        node_id = 0
        names = self._raw.names
        for part in relative.split(os.sep):
            node_id = next((child for child in self.children.get(node_id, ()) if names[child] == part), None)
            if node_id is None:
                return None
        return node_id

    def sorted_extensions(self) -> List[Tuple[str, int, int, int]]:
        """[(extensión, archivos, bytes lógicos, bytes en disco)] por tamaño."""
        return sorted(((ext, *values) for ext, values in self.extensions.items()),
                      key=lambda item: (-item[2], item[0]))


def extension_of(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    return ext if ext and ext != "." else NO_EXTENSION


def _is_link(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or getattr(info, "st_reparse_tag", 0) in {
        getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C),
        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003),
    }


def _win_cluster_size(root: str) -> int:
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        sectors, bytes_per_sector, free, total = (wintypes.DWORD() for _ in range(4))
        drive = os.path.splitdrive(os.path.abspath(root))[0] + "\\"
        if ctypes.windll.kernel32.GetDiskFreeSpaceW(drive, ctypes.byref(sectors), ctypes.byref(bytes_per_sector),
                                                    ctypes.byref(free), ctypes.byref(total)):
            return int(sectors.value) * int(bytes_per_sector.value)
    except (AttributeError, OSError):
        pass
    return 4096


def _win_compressed_size(path: str) -> Optional[int]:
    """GetCompressedFileSizeW: bytes realmente asignados (comprimidos, dispersos, nube)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        high = wintypes.DWORD()
        function = ctypes.windll.kernel32.GetCompressedFileSizeW
        function.restype = wintypes.DWORD
        low = function(ctypes.c_wchar_p(path), ctypes.byref(high))
        if low == 0xFFFFFFFF and ctypes.GetLastError() != 0:
            return None
        return (int(high.value) << 32) + int(low)
    except (AttributeError, OSError):
        return None


class _DiskMeter:
    """Mide el tamaño en disco de un archivo y detecta hardlinks repetidos."""

    def __init__(self, root: str, measure: bool, dedupe: bool):
        self.measure = measure
        self.dedupe = dedupe
        self.windows = sys.platform == "win32"
        self.cluster = _win_cluster_size(root) if (measure and self.windows) else 0
        self.seen: set = set()

    def measure_file(self, entry, info) -> Tuple[int, int]:
        """(bytes en disco, flags)."""
        size = max(0, info.st_size)
        flags = 0
        if self.dedupe:
            key = None
            if self.windows:
                if size >= _WIN_HARDLINK_MIN_SIZE:
                    try:
                        full = os.stat(entry.path, follow_symlinks=False)
                        if full.st_nlink > 1:
                            key = (full.st_dev, full.st_ino)
                    except OSError:
                        key = None
            elif getattr(info, "st_nlink", 1) > 1:
                key = (info.st_dev, info.st_ino)
            if key is not None:
                if key in self.seen:
                    return 0, FLAG_HARDLINK_DUPLICATE
                self.seen.add(key)
        if not self.measure:
            return size, flags
        if self.windows:
            attributes = getattr(info, "st_file_attributes", 0)
            if attributes & _WIN_SPECIAL:
                compressed = _win_compressed_size(entry.path)
                if compressed is not None:
                    return compressed, flags
            if self.cluster:
                return -(-size // self.cluster) * self.cluster, flags
            return size, flags
        blocks = getattr(info, "st_blocks", None)
        return (blocks * 512 if blocks is not None else size), flags


def _scan_into(raw: _Raw, root_id: int, root_path: str, cancelled, progress, meter: _DiskMeter,
               root_is_origin: bool, counters: Dict[str, int]) -> None:
    pending: List[Tuple[int, str]] = [(root_id, root_path)]
    last_progress = time.monotonic()

    def report(path):
        nonlocal last_progress
        now = time.monotonic()
        if now - last_progress >= 0.2:
            last_progress = now
            progress(counters["files"], counters["folders"], counters["logical"], counters["denied"], path)

    def mark_error(node_id, error):
        if isinstance(error, PermissionError):
            raw.statuses[node_id] = _STATUS["denied"]
            counters["denied"] += 1
        elif isinstance(error, FileNotFoundError):
            raw.statuses[node_id] = _STATUS["missing"]
            counters["missing"] += 1
        else:
            raw.statuses[node_id] = _STATUS["error"]
            counters["errors"] += 1

    while pending:
        if cancelled():
            raise SpaceScanCancelled()
        parent_id, parent_path = pending.pop()
        try:
            with os.scandir(parent_path) as entries:
                for entry in entries:
                    if cancelled():
                        raise SpaceScanCancelled()
                    node_id = raw.append(parent_id, entry.name, _UNKNOWN)
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if _is_link(info):
                            raw.kinds[node_id] = _LINK
                            raw.statuses[node_id] = _STATUS["link"]
                            counters["links"] += 1
                        elif stat.S_ISDIR(info.st_mode):
                            raw.kinds[node_id] = _FOLDER
                            counters["folders"] += 1
                            pending.append((node_id, entry.path))
                        elif stat.S_ISREG(info.st_mode):
                            raw.kinds[node_id] = _FILE
                            size = max(0, info.st_size)
                            disk, flags = meter.measure_file(entry, info)
                            raw.sizes[node_id] = size
                            raw.disk[node_id] = disk
                            raw.flags[node_id] = flags
                            counters["logical"] += size
                            counters["files"] += 1
                        else:
                            raw.statuses[node_id] = _STATUS["unsupported"]
                    except OSError as error:
                        mark_error(node_id, error)
                    report(entry.path)
        except OSError as error:
            if parent_id == root_id and root_is_origin:
                raise SpaceScanError(f"No se puede leer el origen: {error.strerror or type(error).__name__}") from error
            mark_error(parent_id, error)
        report(parent_path)


def _check_origin(root_path: str) -> str:
    root_path = os.path.abspath(os.path.expanduser(root_path))
    try:
        info = os.lstat(root_path)
        if _is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise SpaceScanError("El origen debe ser una carpeta o unidad, sin enlaces.")
    except OSError as error:
        raise SpaceScanError(f"No se puede acceder al origen: {error.strerror or type(error).__name__}") from error
    return root_path


def _finalize(raw: _Raw, cancelled, progress, measured_disk: bool) -> SpaceScanResult:
    """Totales por carpeta, hijos ordenados, tops, extensiones y contadores."""
    count = len(raw)
    parents, kinds, names = raw.parents, raw.kinds, raw.names
    files = [i for i in range(1, count) if kinds[i] == _FILE]
    folders = [i for i in range(1, count) if kinds[i] == _FOLDER]
    counters = {
        "files": len(files),
        "folders": len(folders),
        "links": sum(1 for i in range(1, count) if kinds[i] == _LINK),
        "denied": raw.statuses.count(_STATUS["denied"]),
        "missing": raw.statuses.count(_STATUS["missing"]),
        "errors": raw.statuses.count(_STATUS["error"]),
        "hardlinks": raw.flags.count(FLAG_HARDLINK_DUPLICATE),
    }
    logical_total = sum(raw.sizes[i] for i in files)
    sizes = array("q", raw.sizes)
    disk = array("q", raw.disk)
    statuses = bytearray(raw.statuses)
    last = time.monotonic()

    def tick(index):
        nonlocal last
        if index & 0x3FF == 0:
            if cancelled():
                raise SpaceScanCancelled()
            now = time.monotonic()
            if now - last >= 0.2:
                last = now
                progress(counters["files"], counters["folders"], logical_total, counters["denied"],
                         os.path.join(raw.root_path, names[index]) if index else raw.root_path)

    # IDs de hijos siempre mayores que el padre: agregación lineal sin recursión.
    child_count = array("i", bytes(4 * (count + 1)))
    for node_id in range(count - 1, 0, -1):
        tick(node_id)
        parent = parents[node_id]
        sizes[parent] += sizes[node_id]
        disk[parent] += disk[node_id]
        if statuses[node_id] in _PROBLEMS and statuses[parent] == 0:
            statuses[parent] = _STATUS["partial"]
        child_count[parent + 1] += 1
    start = child_count  # prefijos acumulados → CSR
    for index in range(1, count + 1):
        start[index] += start[index - 1]
    child_ids = array("i", bytes(4 * max(0, count - 1)))
    cursor = array("i", start[:count])
    for node_id in range(1, count):
        parent = parents[node_id]
        child_ids[cursor[parent]] = node_id
        cursor[parent] += 1
    del cursor
    for node_id in range(count):
        tick(node_id)
        first, end = start[node_id], start[node_id + 1]
        if end - first > 1:
            child_ids[first:end] = array("i", sorted(child_ids[first:end],
                                                     key=lambda i: (-sizes[i], names[i].casefold())))
    ordered = _ChildrenMap(kinds, start, child_ids)
    top_files = tuple(heapq.nlargest(20, files, key=lambda i: sizes[i]))
    top_folders = tuple(heapq.nlargest(20, folders, key=lambda i: sizes[i]))
    extensions: Dict[str, List[int]] = {}
    for index in files:
        bucket = extensions.setdefault(extension_of(names[index]), [0, 0, 0])
        bucket[0] += 1
        bucket[1] += raw.sizes[index]
        bucket[2] += raw.disk[index]
    if cancelled():
        raise SpaceScanCancelled()
    try:
        usage = shutil.disk_usage(raw.root_path)
        volume = (usage.total, usage.used, usage.free)
    except OSError:
        volume = None
    # Los tamaños propios de cada archivo ya están en ``sizes``/``disk`` (las
    # carpetas valen 0 en bruto): no se guardan dos veces.
    raw.sizes = raw.disk = None
    return SpaceScanResult(raw, sizes, disk, statuses, ordered, top_files, top_folders,
                           {ext: tuple(values) for ext, values in extensions.items()},
                           counters, volume, measured_disk)


def _new_counters() -> Dict[str, int]:
    return {"files": 0, "folders": 0, "logical": 0, "denied": 0, "missing": 0, "errors": 0, "links": 0}


def scan_space(root_path: str, cancelled: Callable[[], bool] = lambda: False,
               progress: Callable[[int, int, int, int, str], None] = lambda *_: None,
               measure_disk: bool = True, dedupe_hardlinks: bool = True) -> SpaceScanResult:
    """Recorrido iterativo. Progreso como máximo cada 200 ms; resultado sólo completo."""
    root_path = _check_origin(root_path)
    raw = _Raw(root_path)
    raw.append(-1, os.path.basename(root_path) or root_path, _FOLDER)
    counters = _new_counters()
    meter = _DiskMeter(root_path, measure_disk, dedupe_hardlinks)
    _scan_into(raw, 0, root_path, cancelled, progress, meter, True, counters)
    return _finalize(raw, cancelled, progress, measure_disk)


def rescan_subtree(result: SpaceScanResult, node_id: int, cancelled: Callable[[], bool] = lambda: False,
                   progress: Callable[[int, int, int, int, str], None] = lambda *_: None,
                   measure_disk: Optional[bool] = None, dedupe_hardlinks: bool = True) -> SpaceScanResult:
    """Vuelve a medir sólo una subcarpeta y recalcula los totales.

    El nodo conserva su id; los nodos posteriores pueden cambiar de id. Los
    hardlinks sólo se deduplican dentro de la subcarpeta reanalizada.
    """
    if node_id == 0:
        return scan_space(result.root_path, cancelled, progress,
                          result.measured_disk if measure_disk is None else measure_disk, dedupe_hardlinks)
    old = result._raw
    if old.kinds[node_id] != _FOLDER:
        raise SpaceScanError("Sólo se pueden volver a analizar carpetas.")
    measure = result.measured_disk if measure_disk is None else measure_disk
    folder_path = _check_origin(result.path_of(node_id))
    block = _Raw(folder_path)
    block.append(-1, old.names[node_id], _FOLDER)
    meter = _DiskMeter(folder_path, measure, dedupe_hardlinks)
    _scan_into(block, 0, folder_path, cancelled, progress, meter, True, _new_counters())

    removed = set(result.subtree_ids(node_id))
    merged = _Raw(old.root_path)
    remap: Dict[int, int] = {}
    for old_id in range(len(old)):
        if old_id == node_id:
            base = len(merged)
            for local in range(len(block)):
                parent = remap[old.parents[node_id]] if local == 0 else base + block.parents[local]
                merged.append(parent, block.names[local], block.kinds[local], block.sizes[local],
                              block.disk[local], block.statuses[local], block.flags[local])
            remap[old_id] = base
            continue
        if old_id in removed:
            continue
        parent = old.parents[old_id]
        is_file = old.kinds[old_id] == _FILE
        remap[old_id] = merged.append(remap[parent] if parent >= 0 else -1, old.names[old_id], old.kinds[old_id],
                                      result._sizes[old_id] if is_file else 0,
                                      result._disk[old_id] if is_file else 0,
                                      old.statuses[old_id], old.flags[old_id])
    return _finalize(merged, cancelled, progress, measure)


def export_csv(result: SpaceScanResult, destination: str, node_id: int = 0) -> int:
    """Exporta el subárbol de ``node_id`` a CSV (UTF-8 con BOM, separador ';').

    Devuelve el número de filas escritas.
    """
    rows = 0
    with open(destination, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Ruta", "Tipo", "Extensión", "Tamaño lógico (bytes)", "Tamaño en disco (bytes)", "Estado"])
        pending = [node_id]
        while pending:
            current = pending.pop()
            node = result.nodes[current]
            writer.writerow([node.path, node.kind, node.extension if node.kind == "file" else "",
                             node.size, node.disk_size, node.status])
            rows += 1
            pending.extend(reversed(result.children.get(current, ())))
    return rows


def export_extensions_csv(result: SpaceScanResult, destination: str) -> int:
    with open(destination, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Extensión", "Archivos", "Tamaño lógico (bytes)", "Tamaño en disco (bytes)"])
        rows = result.sorted_extensions()
        writer.writerows(rows)
    return len(rows)
