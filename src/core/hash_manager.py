#!/usr/bin/env python3
"""
Gestor de Hashes para el Organizador de Archivos
Maneja el cálculo de hashes MD5/SHA256 para detección de duplicados.

- Lectura en bloques de 1 MiB.
- Prehash de los primeros 64 KB para descartar archivos del mismo tamaño.
- Un único ThreadPoolExecutor para todos los archivos de una fase.
- Caché en SQLite consultada y escrita por lotes.
- Los archivos de más de ``max_size_mb`` usan un hash parcial (inicio + fin)
  que se marca como parcial (``md5-partial``) y nunca se confunde con uno completo.
- Cancelación real con ``threading.Event`` comprobada en cada bloque.
- Los errores (permisos, tiempo agotado) se devuelven en ``HashResult.error``.
"""

import hashlib
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .hash_cache import HashCache, cache_key_for

CHUNK_SIZE = 1024 * 1024
PREHASH_SIZE = 64 * 1024
DEFAULT_PARTIAL_THRESHOLD_MB = 5000
PARTIAL_SUFFIX = "-partial"
PREHASH_SUFFIX = "-head64k"


class HashCancelled(Exception):
    """Se lanzó una cancelación mientras se calculaba un hash."""


@dataclass
class HashResult:
    path: Path
    value: Optional[str] = None
    partial: bool = False
    error: str = ""
    algorithm: str = "md5"
    cached: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.value) and not self.error


def _is_cancelled(cancel_event) -> bool:
    if cancel_event is None:
        return False
    if isinstance(cancel_event, threading.Event):
        return cancel_event.is_set()
    try:
        return bool(cancel_event())
    except TypeError:
        return False


class HashManager:
    """Gestor principal de hashes para archivos con caché inteligente"""

    def __init__(
        self,
        use_cache: bool = True,
        cache: Optional[HashCache] = None,
        max_workers: int = 4,
        partial_threshold_mb: int = DEFAULT_PARTIAL_THRESHOLD_MB,
    ):
        self.supported_algorithms = {"md5": hashlib.md5, "sha256": hashlib.sha256}
        self.use_cache = use_cache
        self.cache = cache if cache is not None else (HashCache() if use_cache else None)
        self.max_workers = max(1, int(max_workers))
        self.partial_threshold_mb = partial_threshold_mb

    # ------------------------------------------------------------------ básicos
    def _hash_func(self, algorithm: str):
        func = self.supported_algorithms.get(str(algorithm).lower())
        if func is None:
            raise ValueError(f"Algoritmo no soportado: {algorithm}")
        return func

    def _read_into(self, hash_obj, f, limit: Optional[int], chunk_size: int,
                   cancel_event, deadline: Optional[float], path: Path) -> None:
        remaining = limit
        while True:
            if _is_cancelled(cancel_event):
                raise HashCancelled(str(path))
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"Tiempo agotado calculando hash: {path}")
            size = chunk_size if remaining is None else min(chunk_size, remaining)
            if size <= 0:
                return
            chunk = f.read(size)
            if not chunk:
                return
            hash_obj.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)

    def _compute(self, path: Path, algorithm: str, *, mode: str, size: int,
                 cancel_event=None, timeout_seconds: Optional[float] = None,
                 chunk_size: int = CHUNK_SIZE) -> str:
        """Calcula el hash. ``mode``: 'full', 'partial' o 'prehash'."""
        hash_obj = self._hash_func(algorithm)()
        deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
        with open(path, "rb") as f:
            if mode == "prehash":
                self._read_into(hash_obj, f, PREHASH_SIZE, chunk_size, cancel_event, deadline, path)
            elif mode == "partial":
                hash_obj.update(str(size).encode())
                half = 5 * 1024 * 1024
                self._read_into(hash_obj, f, half, chunk_size, cancel_event, deadline, path)
                if size > half * 2:
                    f.seek(size - half)
                    self._read_into(hash_obj, f, half, chunk_size, cancel_event, deadline, path)
            else:
                self._read_into(hash_obj, f, None, chunk_size, cancel_event, deadline, path)
        return hash_obj.hexdigest()

    def _mode_for(self, size: int, allow_partial: bool, max_size_mb: Optional[int]) -> str:
        threshold = self.partial_threshold_mb if max_size_mb is None else max_size_mb
        if allow_partial and size > threshold * 1024 * 1024:
            return "partial"
        return "full"

    @staticmethod
    def cache_algorithm(algorithm: str, mode: str) -> str:
        if mode == "partial":
            return algorithm + PARTIAL_SUFFIX
        if mode == "prehash":
            return algorithm + PREHASH_SUFFIX
        return algorithm

    # ------------------------------------------------------------------ un archivo
    def hash_file(self, file_path: Path, algorithm: str = "md5", *,
                  allow_partial: bool = True, max_size_mb: Optional[int] = None,
                  timeout_seconds: Optional[float] = None, cancel_event=None,
                  prehash: bool = False) -> HashResult:
        """Hash de un archivo con información de parcialidad y errores."""
        results = self.hash_many(
            [Path(file_path)], algorithm, allow_partial=allow_partial,
            max_size_mb=max_size_mb, timeout_seconds=timeout_seconds,
            cancel_event=cancel_event, prehash=prehash, max_workers=1,
        )
        return results.get(Path(file_path)) or HashResult(Path(file_path), error="sin resultado")

    def calculate_file_hash(self, file_path: Path, algorithm: str = "md5",
                            chunk_size: int = CHUNK_SIZE, max_size_mb: int = DEFAULT_PARTIAL_THRESHOLD_MB,
                            timeout_seconds: int = 300) -> Optional[str]:
        """Compatibilidad: devuelve el hash (completo o parcial) o None si hay error."""
        result = self.hash_file(
            Path(file_path), algorithm, max_size_mb=max_size_mb,
            timeout_seconds=timeout_seconds,
        )
        return result.value if result.ok else None

    def calculate_full_hash(self, file_path: Path, algorithm: str = "md5",
                            cancel_event=None) -> HashResult:
        """Hash de contenido completo (nunca parcial), usado antes de borrar."""
        return self.hash_file(Path(file_path), algorithm, allow_partial=False,
                              cancel_event=cancel_event)

    # ------------------------------------------------------------------ muchos archivos
    def hash_many(
        self,
        file_paths: Sequence[Path],
        algorithm: str = "md5",
        *,
        allow_partial: bool = True,
        max_size_mb: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
        cancel_event=None,
        prehash: bool = False,
        stats: Optional[Dict[Path, os.stat_result]] = None,
        max_workers: Optional[int] = None,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[Path, HashResult]:
        """Calcula hashes de muchos archivos con un único pool de hilos.

        Consulta la caché por lotes, calcula solo los que faltan y guarda los
        nuevos en una sola transacción.  Lanza :class:`HashCancelled` si se
        cancela.
        """
        results: Dict[Path, HashResult] = {}
        pending: List[Tuple[Path, str, int, float, str]] = []  # path, key, size, mtime, mode
        by_algorithm: Dict[str, List[Tuple[str, int, float]]] = {}

        for path in file_paths:
            path = Path(path)
            try:
                st = stats.get(path) if stats else None
                if st is None:
                    st = os.stat(path)
            except OSError as exc:
                results[path] = HashResult(path, error=f"no accesible: {exc.strerror or exc}",
                                           algorithm=algorithm)
                continue
            mode = "prehash" if prehash else self._mode_for(st.st_size, allow_partial, max_size_mb)
            key = cache_key_for(path)
            pending.append((path, key, st.st_size, st.st_mtime, mode))
            by_algorithm.setdefault(self.cache_algorithm(algorithm, mode), []).append(
                (key, st.st_size, st.st_mtime)
            )

        cached: Dict[Tuple[str, str], str] = {}
        if self.use_cache and self.cache is not None:
            for cache_algo, entries in by_algorithm.items():
                for key, value in self.cache.get_hashes_batch(entries, cache_algo).items():
                    cached[(cache_algo, key)] = value

        to_compute = []
        for path, key, size, mtime, mode in pending:
            cache_algo = self.cache_algorithm(algorithm, mode)
            value = cached.get((cache_algo, key))
            if value:
                results[path] = HashResult(path, value, partial=(mode == "partial"),
                                           algorithm=cache_algo, cached=True)
            else:
                to_compute.append((path, key, size, mtime, mode))

        total = len(to_compute)
        new_entries: Dict[str, List[Tuple[str, int, float, str]]] = {}

        def work(item):
            path, key, size, mtime, mode = item
            cache_algo = self.cache_algorithm(algorithm, mode)
            try:
                value = self._compute(path, algorithm, mode=mode, size=size,
                                      cancel_event=cancel_event,
                                      timeout_seconds=timeout_seconds)
                return item, HashResult(path, value, partial=(mode == "partial"),
                                        algorithm=cache_algo)
            except HashCancelled:
                raise
            except TimeoutError as exc:
                return item, HashResult(path, error=f"tiempo agotado: {exc}", algorithm=cache_algo)
            except (OSError, ValueError) as exc:
                reason = getattr(exc, "strerror", None) or str(exc)
                return item, HashResult(path, error=f"error de lectura: {reason}", algorithm=cache_algo)

        done = 0
        if total:
            workers = max(1, min(max_workers or self.max_workers, total))
            if workers == 1:
                for item in to_compute:
                    if _is_cancelled(cancel_event):
                        raise HashCancelled("cancelado")
                    item, result = work(item)
                    results[item[0]] = result
                    if result.ok:
                        new_entries.setdefault(result.algorithm, []).append(
                            (item[1], item[2], item[3], result.value))
                    done += 1
                    if progress:
                        progress(done, total)
            else:
                executor = ThreadPoolExecutor(max_workers=workers)
                cancelled = False
                try:
                    futures = [executor.submit(work, item) for item in to_compute]
                    for future in as_completed(futures):
                        if _is_cancelled(cancel_event):
                            cancelled = True
                            break
                        try:
                            item, result = future.result()
                        except HashCancelled:
                            cancelled = True
                            break
                        results[item[0]] = result
                        if result.ok:
                            new_entries.setdefault(result.algorithm, []).append(
                                (item[1], item[2], item[3], result.value))
                        done += 1
                        if progress:
                            progress(done, total)
                finally:
                    executor.shutdown(wait=True, cancel_futures=True)
                if cancelled:
                    self._save(new_entries)
                    raise HashCancelled("cancelado")

        self._save(new_entries)
        return results

    def _save(self, new_entries: Dict[str, List[Tuple[str, int, float, str]]]) -> None:
        if self.use_cache and self.cache is not None:
            for cache_algo, entries in new_entries.items():
                self.cache.save_hashes_batch(entries, cache_algo)

    def calculate_multiple_hashes(self, file_paths: List[Path], algorithm: str = "md5",
                                  max_workers: int = 4) -> Dict[Path, Optional[str]]:
        """Compatibilidad: ruta -> hash (None si hubo error)."""
        results = self.hash_many(file_paths, algorithm, max_workers=max_workers)
        return {Path(p): (results.get(Path(p)).value if results.get(Path(p)) and results[Path(p)].ok else None)
                for p in file_paths}

    # ------------------------------------------------------------------ comparación
    @staticmethod
    def files_identical(path_a: Path, path_b: Path, cancel_event=None,
                        chunk_size: int = CHUNK_SIZE) -> bool:
        """Compara dos archivos byte a byte."""
        try:
            if os.path.getsize(path_a) != os.path.getsize(path_b):
                return False
            with open(path_a, "rb") as fa, open(path_b, "rb") as fb:
                while True:
                    if _is_cancelled(cancel_event):
                        raise HashCancelled(str(path_a))
                    a = fa.read(chunk_size)
                    b = fb.read(chunk_size)
                    if a != b:
                        return False
                    if not a:
                        return True
        except OSError:
            return False

    # ------------------------------------------------------------------ utilidades
    def get_file_size_and_date(self, file_path: Path) -> Tuple[int, float]:
        try:
            stat = os.stat(file_path)
            return stat.st_size, stat.st_mtime
        except OSError:
            return 0, 0.0

    def is_large_file(self, file_path: Path, threshold_mb: int = 100) -> bool:
        try:
            return os.stat(file_path).st_size / (1024 * 1024) > threshold_mb
        except OSError:
            return False
