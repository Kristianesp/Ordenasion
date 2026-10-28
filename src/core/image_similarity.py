#!/usr/bin/env python3
"""
Imágenes parecidas mediante hash perceptual dHash (64 bits) calculado con QImage.

No añade dependencias: QImageReader decodifica a tamaño reducido y se compara
la luminosidad de píxeles vecinos en una rejilla 9x8.  Las imágenes cuya
distancia de Hamming es menor o igual que el umbral se agrupan (BK-tree +
unión de conjuntos).  Los grupos son *parecidos*, no idénticos.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QSize, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QImageReader

from .duplicate_finder import DuplicateFinder, GroupMeta, ScanCancelled

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
DEFAULT_THRESHOLD = 10


def dhash(path, hash_size: int = 8) -> Optional[int]:
    """dHash de ``hash_size*hash_size`` bits o None si la imagen no se puede leer."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    original = reader.size()
    if original.isValid() and original.width() > 256 and original.height() > 256:
        # Decodificación reducida (rápida en JPEG) conservando proporción aproximada
        reader.setScaledSize(QSize(256, max(1, int(256 * original.height() / original.width()))))
    image = reader.read()
    if image.isNull():
        return None
    small = image.convertToFormat(QImage.Format.Format_Grayscale8).scaled(
        hash_size + 1, hash_size,
    )
    value = 0
    for y in range(hash_size):
        for x in range(hash_size):
            left = small.pixelColor(x, y).value()
            right = small.pixelColor(x + 1, y).value()
            value = (value << 1) | (1 if left > right else 0)
    return value


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


class _BKTree:
    def __init__(self):
        self.root: Optional[Tuple[int, int, Dict[int, tuple]]] = None

    def add(self, value: int, ident: int) -> None:
        node = (value, ident, {})
        if self.root is None:
            self.root = node
            return
        current = self.root
        while True:
            distance = hamming(value, current[0])
            child = current[2].get(distance)
            if child is None:
                current[2][distance] = node
                return
            current = child

    def query(self, value: int, threshold: int) -> List[int]:
        if self.root is None:
            return []
        found, stack = [], [self.root]
        while stack:
            node = stack.pop()
            distance = hamming(value, node[0])
            if distance <= threshold:
                found.append(node[1])
            for d, child in node[2].items():
                if distance - threshold <= d <= distance + threshold:
                    stack.append(child)
        return found


def group_similar(hashes: List[Tuple[Path, int]], threshold: int = DEFAULT_THRESHOLD) -> List[List[Path]]:
    """Agrupa por distancia de Hamming (componentes conexas)."""
    parent = list(range(len(hashes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    tree = _BKTree()
    for index, (_, value) in enumerate(hashes):
        for other in tree.query(value, threshold):
            ra, rb = find(index), find(other)
            if ra != rb:
                parent[ra] = rb
        tree.add(value, index)
    groups: Dict[int, List[Path]] = {}
    for index, (path, _) in enumerate(hashes):
        groups.setdefault(find(index), []).append(path)
    return [paths for paths in groups.values() if len(paths) >= 2]


def find_similar_images(folder: str, *, recursive: bool = True, threshold: int = DEFAULT_THRESHOLD,
                        cancel_event=None, progress: Optional[Callable[[str], None]] = None,
                        finder: Optional[DuplicateFinder] = None):
    """Devuelve ``(grupos, file_info, group_meta, errores)``."""
    finder = finder or DuplicateFinder(cancel_event=cancel_event or threading.Event())
    if cancel_event is not None:
        finder.cancel_event = cancel_event
    entries = [e for e in finder.iter_files(Path(folder), recursive)
               if e.path.suffix.lower() in IMAGE_EXTENSIONS and e.size > 0]
    entries = finder._dedupe_hardlinks(entries)
    hashes: List[Tuple[Path, int]] = []
    errors: List[Tuple[str, str]] = list(finder.errors)
    for index, entry in enumerate(entries, start=1):
        if finder.cancel_event.is_set():
            raise ScanCancelled()
        value = dhash(entry.path)
        if value is None:
            errors.append((str(entry.path), "imagen no legible"))
        else:
            hashes.append((entry.path, value))
        if progress and index % 50 == 0:
            progress(f"🖼️ {index}/{len(entries)} imágenes analizadas...")
    info = {e.path: {"size": e.size, "date": e.mtime, "name": e.path.name} for e in entries}
    by_path = dict(hashes)
    groups: Dict[str, List[Path]] = {}
    meta: Dict[str, GroupMeta] = {}
    for paths in group_similar(hashes, threshold):
        paths.sort(key=lambda p: -info[p]["size"])
        key = f"similar:{by_path[paths[0]]:016x}"
        groups[key] = paths
        meta[key] = GroupMeta(key=key, method="similar", confirmed=False,
                              size=info[paths[0]]["size"])
    return groups, info, meta, errors


class SimilarImagesWorker(QThread):
    """Busca imágenes parecidas en segundo plano (señales compatibles con DuplicateScanWorker)."""

    scan_progress = pyqtSignal(str)
    scan_complete = pyqtSignal(dict, dict)
    duplicates_found = pyqtSignal(dict, dict)
    error_occurred = pyqtSignal(str)
    scan_cancelled = pyqtSignal()

    def __init__(self, folder_path: str, recursive: bool = True, threshold: int = DEFAULT_THRESHOLD):
        super().__init__()
        self.folder_path = folder_path
        self.recursive = recursive
        self.threshold = threshold
        self.cancel_event = threading.Event()
        self.method = "similar"

    def stop(self):
        self.cancel_event.set()
        self.requestInterruption()

    def run(self):
        try:
            self.scan_progress.emit(f"🖼️ Buscando imágenes parecidas (umbral {self.threshold})...")
            groups, info, meta, errors = find_similar_images(
                self.folder_path, recursive=self.recursive, threshold=self.threshold,
                cancel_event=self.cancel_event, progress=self.scan_progress.emit,
            )
            space = sum(sum(info[p]["size"] for p in paths[1:]) for paths in groups.values())
            stats = {
                "total_duplicate_files": sum(len(p) for p in groups.values()),
                "total_duplicate_groups": len(groups),
                "space_saved_bytes": space,
                "space_saved_mb": space / (1024 * 1024),
                "method": "similar",
                "confirmed": False,
                "errors": errors,
                "hardlinks_skipped": 0,
                "group_meta": {k: m.to_dict() for k, m in meta.items()},
                "file_info": {str(p): {"size": v["size"], "date": v["date"]} for p, v in info.items()},
            }
            if groups:
                self.duplicates_found.emit(groups, stats)
            self.scan_complete.emit(groups, stats)
        except ScanCancelled:
            self.scan_progress.emit("⏹ Análisis cancelado")
            self.scan_cancelled.emit()
        except Exception as exc:
            self.error_occurred.emit(f"❌ Error buscando imágenes parecidas: {exc}")
