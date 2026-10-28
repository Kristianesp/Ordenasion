#!/usr/bin/env python3
"""
Sistema de Detección de Duplicados para el Organizador de Archivos.

Estrategia Candidato → Confirmación:

1. **Enumeración** (una sola pasada con ``os.scandir`` y un ``stat`` por archivo).
   Se ignoran carpetas ocultas o de cuarentena (componentes que empiezan por
   ``.`` o ``$``), las carpetas reales del sistema (comparación por componente
   con ``os.path.normcase``, nunca por subcadena) y los hardlinks repetidos
   (mismo ``st_dev``/``st_ino``).
2. **Candidatos**: por tamaño (``deep``) o por tamaño + nombre normalizado +
   extensión (``fast`` y ``hybrid``).
3. **Confirmación** (``deep`` y ``hybrid``): prehash de los primeros 64 KB y
   hash completo solo entre los que coinciden, con un único pool de hilos.
   Los archivos de más de 5000 MB usan un hash parcial marcado como tal.

Las claves de los grupos confirmados son el hash de contenido, de modo que
"ignorar grupo" y "original preferido" sobreviven entre análisis.
"""

import os
import re
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

from src.utils.logger import debug, warn
from .hash_manager import HashCancelled, HashManager, HashResult

# Carpetas de cuarentena conocidas (además de cualquier componente con '.' o '$')
QUARANTINE_DIR_NAMES = {
    ".quarantine",
    ".duplicates_quarantine",
    "$recycle.bin",
    "system volume information",
    "recycler",
    "recycled",
    ".trash",
    ".trashes",
}
IGNORED_FILE_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}
PARTIAL_HASH_LABEL = "md5-partial"
# Por debajo de este tamaño el prehash (64 KB) no compensa: se lee el archivo completo
PREHASH_MIN_SIZE = 1024 * 1024


class ScanCancelled(Exception):
    """El usuario canceló el análisis."""


def _system_dirs() -> Set[str]:
    """Rutas reales del sistema (normalizadas) que nunca se analizan por debajo de la raíz."""
    dirs: Set[str] = set()
    if sys.platform == "win32":
        names = ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)",
                 "ProgramW6432", "ProgramData")
        for name in names:
            value = os.environ.get(name)
            if value:
                dirs.add(os.path.normcase(os.path.abspath(value)))
    else:
        for value in ("/proc", "/sys", "/dev", "/run", "/boot", "/usr", "/bin",
                      "/sbin", "/lib", "/lib64", "/etc", "/var/lib", "/snap"):
            dirs.add(os.path.normcase(value))
    return dirs


SYSTEM_DIRS = _system_dirs()


def is_excluded_component(name: str) -> bool:
    """Componente de ruta oculto, de sistema o de cuarentena."""
    if not name:
        return False
    if name[0] in ".$":
        return True
    return name.lower() in QUARANTINE_DIR_NAMES


def is_excluded_relative(path: Path, root: Path) -> bool:
    """True si algún componente de ``path`` relativo a ``root`` debe ignorarse."""
    try:
        rel = Path(path).relative_to(root)
    except ValueError:
        rel = Path(path)
    parts = rel.parts
    for part in parts[:-1]:
        if is_excluded_component(part):
            return True
    name = parts[-1] if parts else ""
    if is_excluded_file_name(name):
        return True
    current = Path(root)
    for part in parts[:-1]:
        current = current / part
        if os.path.normcase(str(current)) in SYSTEM_DIRS:
            return True
    return False


def is_excluded_file_name(name: str) -> bool:
    lowered = name.lower()
    return (
        not name
        or name[0] in ".$"
        or lowered.startswith("~$")
        or lowered in IGNORED_FILE_NAMES
    )


def normalize_filename(filename: str) -> str:
    """'document (1)' → 'document'; 'foto - copia' → 'foto'."""
    value = re.sub(r"\s*\(\d+\)$", "", filename).strip()
    value = re.sub(r"(?i)\s*[-_ ]\s*(copia|copy)(\s*\(\d+\))?$", "", value).strip()
    return value


@dataclass
class FileEntry:
    path: Path
    size: int
    mtime: float
    identity: Optional[Tuple[int, int]] = None


def walk_files(folder_path, recursive: bool = True, cancel_event=None,
               errors: Optional[List[Tuple[str, str]]] = None) -> Iterable["FileEntry"]:
    """Recorre ``folder_path`` con ``os.scandir`` (un stat por archivo).

    Omite carpetas ocultas, de cuarentena y del sistema por debajo de la raíz,
    enlaces simbólicos y junctions.  Lanza :class:`ScanCancelled` si se cancela.
    """
    stack = [str(Path(folder_path))]
    while stack:
        if cancel_event is not None and cancel_event.is_set():
            raise ScanCancelled()
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                entries = list(it)
        except OSError as exc:
            if errors is not None:
                errors.append((current, f"carpeta no accesible: {exc.strerror or exc}"))
            continue
        for entry in entries:
            name = entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not recursive or is_excluded_component(name):
                        continue
                    if hasattr(entry, "is_junction") and entry.is_junction():
                        continue
                    if os.path.normcase(entry.path) in SYSTEM_DIRS:
                        continue
                    stack.append(entry.path)
                    continue
                if not entry.is_file(follow_symlinks=False) or is_excluded_file_name(name):
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                if errors is not None:
                    errors.append((entry.path, f"no accesible: {exc.strerror or exc}"))
                continue
            identity = (st.st_dev, st.st_ino) if st.st_ino else None
            yield FileEntry(Path(entry.path), st.st_size, st.st_mtime, identity)


@dataclass
class GroupMeta:
    """Información de un grupo de duplicados."""
    key: str
    method: str                      # fast | hybrid | deep
    confirmed: bool                  # contenido confirmado por hash
    partial: bool = False            # algún archivo usa hash parcial (>5000 MB)
    content_hash: Optional[str] = None
    size: int = 0
    hashes: Dict[str, str] = field(default_factory=dict)  # ruta -> hash

    def to_dict(self) -> Dict:
        return {
            "key": self.key,
            "method": self.method,
            "confirmed": self.confirmed,
            "partial": self.partial,
            "content_hash": self.content_hash,
            "size": self.size,
        }


class DuplicateFinder:
    """Sistema principal para encontrar archivos duplicados"""

    def __init__(self, hash_manager: Optional[HashManager] = None, cancel_event=None):
        self.hash_manager = hash_manager or HashManager()
        self.cancel_event = cancel_event or threading.Event()
        self.duplicates_db: Dict[str, List[Path]] = {}
        self.fast_duplicates_db: Dict[str, List[Path]] = {}
        self.file_info: Dict[Path, Dict] = {}
        self.group_meta: Dict[str, GroupMeta] = {}
        self.errors: List[Tuple[str, str]] = []
        self.hardlinks_skipped: int = 0
        self.files_scanned: int = 0
        self._entries: Dict[Path, FileEntry] = {}
        self.detection_method = "hybrid"
        self.progress_callback: Optional[Callable[[str], None]] = None

    # ------------------------------------------------------------------ utilidades
    def cancel(self) -> None:
        self.cancel_event.set()

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise ScanCancelled()

    def _progress(self, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(message)

    def _normalize_filename(self, filename: str) -> str:
        return normalize_filename(filename)

    def _reset(self, method: str) -> None:
        self.duplicates_db = {}
        self.fast_duplicates_db = {}
        self.file_info = {}
        self.group_meta = {}
        self.errors = []
        self.hardlinks_skipped = 0
        self.files_scanned = 0
        self._entries = {}
        self.detection_method = method

    # ------------------------------------------------------------------ enumeración
    def iter_files(self, folder_path: Path, recursive: bool = True) -> Iterable[FileEntry]:
        """Recorre la carpeta con ``os.scandir`` (un stat por archivo)."""
        return walk_files(folder_path, recursive, cancel_event=self.cancel_event, errors=self.errors)

    def _get_all_files(self, folder_path: Path, recursive: bool = True) -> List[Path]:
        return [entry.path for entry in self.iter_files(Path(folder_path), recursive)]

    def _is_system_file(self, file_path: Path, root: Optional[Path] = None) -> bool:
        """Compatibilidad: comprueba exclusiones relativas a ``root`` (o la ruta completa)."""
        try:
            if root is None:
                return is_excluded_file_name(Path(file_path).name)
            return is_excluded_relative(Path(file_path), Path(root))
        except (OSError, ValueError) as exc:
            debug(f"_is_system_file: {exc}")
            return False

    @staticmethod
    def _real_identity(entry: FileEntry) -> Optional[Tuple[int, int]]:
        if entry.identity:
            return entry.identity
        try:  # En Windows DirEntry.stat() no rellena st_ino
            st = os.stat(entry.path)
            return (st.st_dev, st.st_ino) if st.st_ino else None
        except OSError:
            return None

    def _dedupe_hardlinks(self, entries: List[FileEntry]) -> List[FileEntry]:
        """Mantiene una sola ruta por inodo: los hardlinks no son duplicados."""
        seen: Set[Tuple[int, int]] = set()
        unique: List[FileEntry] = []
        for entry in entries:
            identity = self._real_identity(entry)
            if identity is not None:
                if identity in seen:
                    self.hardlinks_skipped += 1
                    continue
                seen.add(identity)
            unique.append(entry)
        return unique

    def _collect(self, folder_path: Path, recursive: bool,
                 min_size: int = 0) -> List[FileEntry]:
        entries = []
        for entry in self.iter_files(folder_path, recursive):
            self.files_scanned += 1
            if entry.size < max(min_size, 1):  # vacíos no cuentan como duplicados
                continue
            entries.append(entry)
            if self.files_scanned % 2000 == 0:
                self._progress(f"📁 {self.files_scanned} archivos revisados...")
        return entries

    # ------------------------------------------------------------------ candidatos
    def _candidate_groups(self, entries: List[FileEntry], by_name: bool) -> Dict[str, List[FileEntry]]:
        groups: Dict[str, List[FileEntry]] = defaultdict(list)
        for entry in entries:
            if by_name:
                name = normalize_filename(entry.path.stem.lower())
                key = f"{entry.size}|{name}|{entry.path.suffix.lower()}"
            else:
                key = str(entry.size)
            groups[key].append(entry)
        result = {}
        for key, items in groups.items():
            if len(items) < 2:
                continue
            items = self._dedupe_hardlinks(items)
            if len(items) >= 2:
                result[key] = items
        return result

    # ------------------------------------------------------------------ confirmación
    def _record_errors(self, results: Dict[Path, HashResult]) -> None:
        for path, result in results.items():
            if result.error:
                self.errors.append((str(path), result.error))

    def _confirm_by_hash(self, candidates: Dict[str, List[FileEntry]],
                         algorithm: str = "md5") -> Dict[str, Tuple[List[FileEntry], Dict[Path, HashResult]]]:
        """Prehash (64 KB) y hash completo solo para los que coinciden."""
        stats = {}
        need_prehash: List[Path] = []
        small: List[Path] = []
        for items in candidates.values():
            for entry in items:
                stats[entry.path] = entry
                if entry.size <= PREHASH_MIN_SIZE:
                    small.append(entry.path)
                else:
                    need_prehash.append(entry.path)

        self._check_cancel()
        # Hashes completos ya cacheados: evitan prehash y relectura
        full_results: Dict[Path, HashResult] = {}
        if self.hash_manager.use_cache and self.hash_manager.cache is not None:
            full_results.update(self._cached_full(need_prehash, algorithm))

        to_prehash = [p for p in need_prehash if p not in full_results]
        self._progress(f"🔎 Prehash de {len(to_prehash)} archivos (64 KB)...")
        prehash_results = self.hash_manager.hash_many(
            to_prehash, algorithm, prehash=True, cancel_event=self.cancel_event,
        )
        self._record_errors(prehash_results)

        # Agrupar por (tamaño, prehash) para decidir qué hash completo hace falta
        need_full: List[Path] = list(small)
        for items in candidates.values():
            buckets: Dict[str, List[Path]] = defaultdict(list)
            for entry in items:
                if entry.path in full_results or entry.size <= PREHASH_MIN_SIZE:
                    continue
                pre = prehash_results.get(entry.path)
                if pre and pre.ok:
                    buckets[pre.value].append(entry.path)
            cached_in_group = [e.path for e in items if e.path in full_results]
            for paths in buckets.values():
                if len(paths) >= 2 or (paths and cached_in_group):
                    need_full.extend(paths)

        self._check_cancel()
        self._progress(f"🔍 Hash completo de {len(need_full)} archivos...")
        computed = self.hash_manager.hash_many(
            need_full, algorithm, cancel_event=self.cancel_event, timeout_seconds=600,
        )
        self._record_errors(computed)
        full_results.update(computed)

        confirmed: Dict[str, Tuple[List[FileEntry], Dict[Path, HashResult]]] = {}
        for items in candidates.values():
            by_hash: Dict[Tuple[str, bool], List[FileEntry]] = defaultdict(list)
            for entry in items:
                result = full_results.get(entry.path)
                if result and result.ok:
                    by_hash[(result.value, result.partial)].append(entry)
            for (value, partial), group in by_hash.items():
                if len(group) < 2:
                    continue
                key = f"{PARTIAL_HASH_LABEL}:{value}" if partial else value
                confirmed[key] = (group, {e.path: full_results[e.path] for e in group})
        return confirmed

    def _cached_full(self, paths: List[Path], algorithm: str) -> Dict[Path, HashResult]:
        from .hash_cache import cache_key_for
        out: Dict[Path, HashResult] = {}
        if not paths:
            return out
        cache = self.hash_manager.cache
        by_key = {}
        entries_full, entries_partial = [], []
        for path in paths:
            entry = self._entries.get(path)
            if entry is None:
                continue
            key = cache_key_for(path)
            by_key[key] = path
            mode = self.hash_manager._mode_for(entry.size, True, None)
            target = entries_partial if mode == "partial" else entries_full
            target.append((key, entry.size, entry.mtime))
        for key, value in cache.get_hashes_batch(entries_full, algorithm).items():
            out[by_key[key]] = HashResult(by_key[key], value, algorithm=algorithm, cached=True)
        for key, value in cache.get_hashes_batch(entries_partial, f"{algorithm}-partial").items():
            out[by_key[key]] = HashResult(by_key[key], value, partial=True,
                                          algorithm=f"{algorithm}-partial", cached=True)
        return out

    # ------------------------------------------------------------------ API pública
    def scan(self, folder_path: str, method: str = "hybrid", recursive: bool = True,
             min_size: int = 0, algorithm: str = "md5") -> Dict[str, List[Path]]:
        """Análisis unificado. ``method``: 'fast', 'hybrid' o 'deep'."""
        root = Path(folder_path)
        self._reset(method)
        if not root.exists() or not root.is_dir():
            return {}
        self._progress("📁 Enumerando archivos...")
        entries = self._collect(root, recursive, min_size)
        self._entries = {entry.path: entry for entry in entries}
        self._check_cancel()

        candidates = self._candidate_groups(entries, by_name=(method in ("fast", "hybrid")))
        self._progress(f"⚡ {len(candidates)} grupos candidatos")

        for items in candidates.values():
            for entry in items:
                self.file_info[entry.path] = {
                    "size": entry.size,
                    "date": entry.mtime,
                    "name": entry.path.name,
                    "extension": entry.path.suffix.lower(),
                    "algorithm": "fast",
                }

        if method == "fast":
            cached = self._cached_full([e.path for items in candidates.values() for e in items], algorithm) \
                if self.hash_manager.use_cache and self.hash_manager.cache is not None else {}
            for key, items in candidates.items():
                paths = [entry.path for entry in items]
                self.fast_duplicates_db[key] = paths
                values = {cached[p].value for p in paths if p in cached and not cached[p].partial}
                content_hash = values.pop() if len(values) == 1 and all(p in cached for p in paths) else None
                self.group_meta[key] = GroupMeta(
                    key=key, method="fast", confirmed=False, content_hash=content_hash,
                    size=items[0].size,
                    hashes={str(p): cached[p].value for p in paths if p in cached},
                )
            self.duplicates_db = dict(self.fast_duplicates_db)
        else:
            confirmed = self._confirm_by_hash(candidates, algorithm)
            for key, (group, hashes) in confirmed.items():
                paths = [entry.path for entry in group]
                partial = any(result.partial for result in hashes.values())
                self.duplicates_db[key] = paths
                content = next(iter(hashes.values())).value
                self.group_meta[key] = GroupMeta(
                    key=key, method=method, confirmed=not partial, partial=partial,
                    content_hash=None if partial else content, size=group[0].size,
                    hashes={str(p): r.value for p, r in hashes.items()},
                )
                for path, result in hashes.items():
                    info = self.file_info.setdefault(path, {})
                    info["hash"] = result.value
                    info["algorithm"] = PARTIAL_HASH_LABEL if result.partial else algorithm
                    info["partial"] = result.partial

        if recursive and self.hash_manager.cache is not None:
            try:
                from .hash_cache import cache_key_for
                self.hash_manager.cache.purge_missing_under(
                    str(root), (cache_key_for(p) for p in self._entries))
            except Exception as exc:  # la limpieza nunca debe romper el análisis
                warn(f"No se pudo purgar la caché de hashes: {exc}")
        return self.duplicates_db

    def scan_for_duplicates_fast(self, folder_path: str, recursive: bool = True) -> Dict[str, List[Path]]:
        """Candidatos por tamaño + nombre normalizado + extensión (sin confirmar)."""
        self.scan(folder_path, method="fast", recursive=recursive)
        return self.fast_duplicates_db

    def scan_for_duplicates(self, folder_path: str, algorithms: List[str] = None,
                            recursive: bool = True) -> Dict[str, List[Path]]:
        """Duplicados por contenido: candidatos por tamaño y confirmación por hash."""
        algorithm = (algorithms or ["md5"])[0]
        return self.scan(folder_path, method="deep", recursive=recursive, algorithm=algorithm)

    def scan_for_duplicates_hybrid(self, folder_path: str, progress_callback=None,
                                   recursive: bool = True) -> Dict[str, List[Path]]:
        """Candidatos por nombre + tamaño confirmados por hash (recomendado)."""
        if progress_callback:
            self.progress_callback = progress_callback
        result = self.scan(folder_path, method="hybrid", recursive=recursive)
        self._progress(f"✅ HÍBRIDO completado: {len(result)} grupos confirmados")
        return result

    def _group_files_by_size(self, files: List[Path]) -> Dict[int, List[Path]]:
        size_groups = defaultdict(list)
        for file_path in files:
            try:
                size_groups[os.stat(file_path).st_size].append(file_path)
            except OSError:
                continue
        return size_groups

    # ------------------------------------------------------------------ resultados
    def get_duplicate_groups(self) -> Dict[str, List[Dict]]:
        """Grupos con metadatos por archivo, ordenados del más reciente al más antiguo."""
        groups = {}
        for key, file_paths in self.duplicates_db.items():
            if len(file_paths) < 2:
                continue
            meta = self.group_meta.get(key)
            group_info = []
            for file_path in file_paths:
                info = self.file_info.get(file_path, {})
                group_info.append({
                    "path": file_path,
                    "name": file_path.name,
                    "size": info.get("size", 0),
                    "date": info.get("date", 0),
                    "extension": info.get("extension", ""),
                    "hash": info.get("hash", key),
                    "fast_key": key,
                    "algorithm": info.get("algorithm", meta.method if meta else "md5"),
                    "confirmed": bool(meta and meta.confirmed),
                    "partial": bool(meta and meta.partial),
                })
            group_info.sort(key=lambda x: x["date"], reverse=True)
            groups[key] = group_info
        return groups

    def get_duplicate_groups_fast(self) -> Dict[str, List[Dict]]:
        return self.get_duplicate_groups()

    def calculate_space_saved(self) -> int:
        """Espacio recuperable conservando una copia por grupo (los hardlinks ya no cuentan)."""
        total = 0
        for file_paths in self.duplicates_db.values():
            if len(file_paths) > 1:
                sizes = [self.file_info.get(p, {}).get("size", 0) for p in file_paths]
                total += sum(sizes) - max(sizes)
        return total

    def _calculate_space_saved_fast(self) -> int:
        return self.calculate_space_saved()

    def get_statistics(self) -> Dict:
        total_files = sum(len(files) for files in self.duplicates_db.values())
        total_groups = len([g for g in self.duplicates_db.values() if len(g) > 1])
        space_saved = self.calculate_space_saved()
        return {
            "total_duplicate_files": total_files,
            "total_duplicate_groups": total_groups,
            "space_saved_bytes": space_saved,
            "space_saved_mb": space_saved / (1024 * 1024),
            "unique_hashes": len(self.duplicates_db),
            "unique_keys": len(self.duplicates_db),
            "method": self.detection_method,
            "confirmed": self.detection_method != "fast",
            "files_scanned": self.files_scanned,
            "hardlinks_skipped": self.hardlinks_skipped,
            "errors": list(self.errors),
            "partial_groups": sum(1 for m in self.group_meta.values() if m.partial),
            "group_meta": {k: m.to_dict() for k, m in self.group_meta.items()},
            "file_info": {
                str(path): {"size": self.file_info.get(path, {}).get("size", 0),
                            "date": self.file_info.get(path, {}).get("date", 0),
                            "hash": self.file_info.get(path, {}).get("hash", "")}
                for paths in self.duplicates_db.values() for path in paths
            },
        }

    def get_statistics_fast(self) -> Dict:
        return self.get_statistics()

    def export_results(self, output_path: str) -> bool:
        """Exporta los resultados a un archivo de texto."""
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("🔍 RESULTADOS DE ANÁLISIS DE DUPLICADOS\n")
                f.write("=" * 60 + "\n\n")
                stats = self.get_statistics()
                f.write("📊 Estadísticas Generales:\n")
                f.write(f"   • Grupos de duplicados: {stats['total_duplicate_groups']}\n")
                f.write(f"   • Archivos duplicados totales: {stats['total_duplicate_files']}\n")
                f.write(f"   • Espacio recuperable: {stats['space_saved_mb']:.2f} MB\n")
                f.write(f"   • Hashes únicos: {stats['unique_hashes']}\n\n")
                for i, (key, files) in enumerate(self.get_duplicate_groups().items(), 1):
                    f.write(f"📁 Grupo {i}: {files[0]['name']}\n")
                    f.write(f"   Hash ({files[0]['algorithm']}): {key[:24]}...\n")
                    f.write(f"   Tamaño: {files[0]['size'] / (1024*1024):.2f} MB\n")
                    f.write("   Archivos:\n")
                    for file_info in files:
                        status = "✅ MÁS RECIENTE" if file_info is files[0] else "❌ DUPLICADO"
                        f.write(f"      • {status}: {file_info['path']}\n")
                    f.write(f"   Espacio a recuperar: {(sum(x['size'] for x in files[1:])) / (1024*1024):.2f} MB\n\n")
            return True
        except OSError as exc:
            warn(f"No se pudieron exportar los resultados: {exc}")
            return False


class DuplicateScanWorker(QThread):
    """Worker para escanear duplicados en segundo plano con cancelación real."""

    scan_progress = pyqtSignal(str)
    scan_complete = pyqtSignal(dict, dict)  # duplicates_db, statistics
    duplicates_found = pyqtSignal(dict, dict)
    error_occurred = pyqtSignal(str)
    scan_cancelled = pyqtSignal()

    def __init__(self, folder_path: str, method: str = "hybrid", algorithms: List[str] = None,
                 recursive: bool = True, min_size: int = 0):
        super().__init__()
        self.folder_path = folder_path
        self.method = method if method in ("fast", "hybrid", "deep") else "hybrid"
        self.algorithms = algorithms or ["md5"]
        self.recursive = recursive
        self.min_size = min_size
        self.cancel_event = threading.Event()
        self.duplicate_finder = DuplicateFinder(cancel_event=self.cancel_event)
        self.duplicate_finder.progress_callback = self._emit_progress
        self.is_running = True

    def _emit_progress(self, message: str) -> None:
        if not self.cancel_event.is_set():
            self.scan_progress.emit(message)

    def run(self):
        try:
            labels = {"fast": "RÁPIDA (candidatos sin confirmar)",
                      "hybrid": "HÍBRIDA (confirmada por hash)",
                      "deep": "PROFUNDA (por contenido)"}
            self.scan_progress.emit(f"🚀 Iniciando búsqueda {labels[self.method]}...")
            duplicates = self.duplicate_finder.scan(
                self.folder_path, method=self.method, recursive=self.recursive,
                min_size=self.min_size, algorithm=self.algorithms[0],
            )
            statistics = self.duplicate_finder.get_statistics()
            if duplicates:
                self.duplicates_found.emit(duplicates, statistics)
            self.scan_progress.emit("✅ Búsqueda completada")
            self.scan_complete.emit(duplicates, statistics)
        except (ScanCancelled, HashCancelled):
            self.scan_progress.emit("⏹ Análisis cancelado")
            self.scan_cancelled.emit()
        except Exception as e:  # el hilo no debe morir en silencio
            self.error_occurred.emit(f"❌ Error durante el análisis: {e}")

    def stop(self):
        """Solicita la cancelación (se comprueba en bucles y en cada bloque de hash)."""
        self.is_running = False
        self.cancel_event.set()
        self.requestInterruption()
