#!/usr/bin/env python3
"""
Sistema de Caché de Hashes para el Organizador de Archivos
Almacena hashes calculados previamente para evitar recálculos innecesarios.

Diseño (v4):
- Una única conexión SQLite persistente protegida por un lock (``check_same_thread``
  desactivado), en modo WAL con ``synchronous=NORMAL``.
- Las lecturas nunca escriben (sin contadores de aciertos en la base de datos;
  las estadísticas de la sesión se guardan en memoria).
- Búsquedas y guardados por lotes (``executemany`` en una sola transacción).
- Los hashes parciales se guardan con un algoritmo distinto (``md5-partial``)
  para que nunca se confundan con un hash de contenido completo.
- ``purge_missing_under`` elimina entradas de archivos que ya no existen.
"""

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.utils.logger import debug, warn

# Tamaño máximo de parámetros por consulta (SQLite admite 999 en versiones antiguas)
_BATCH = 500


def cache_key_for(path) -> str:
    """Clave normalizada de una ruta (absoluta y con mayúsculas normalizadas)."""
    return os.path.normcase(os.path.abspath(str(path)))


class HashCache:
    """
    Caché persistente de hashes con invalidación automática por fecha de modificación
    y tamaño.
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from src.utils.paths import user_data_file
            db_path = user_data_file("hash_cache.db")
        self.db_path = Path(db_path)
        self.lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self.session_hits = 0
        self.session_misses = 0
        self._create_tables()

    # ------------------------------------------------------------------ conexión
    def _get_connection(self) -> sqlite3.Connection:
        """Devuelve la conexión persistente (se crea la primera vez)."""
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False, timeout=10
            )
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA temp_store=MEMORY")
            except sqlite3.Error as exc:
                warn(f"HashCache: no se pudo activar WAL: {exc}")
            self._conn = conn
        return self._conn

    def close(self) -> None:
        with self.lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None

    def __del__(self):  # pragma: no cover - depende del recolector
        try:
            self.close()
        except Exception:
            pass

    def _create_tables(self):
        with self.lock:
            conn = self._get_connection()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS hash_cache (
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    hash_value TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    hit_count INTEGER DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_hash_cache_file_algo
                ON hash_cache(file_path, algorithm);
                CREATE TABLE IF NOT EXISTS cache_stats (
                    id INTEGER PRIMARY KEY,
                    total_hits INTEGER DEFAULT 0,
                    total_misses INTEGER DEFAULT 0,
                    total_saved_time_seconds REAL DEFAULT 0,
                    last_cleanup TIMESTAMP
                );
                INSERT OR IGNORE INTO cache_stats (id) VALUES (1);
                """
            )
            conn.commit()

    # ------------------------------------------------------------------ lectura
    def get_hash(self, file_path: Path, algorithm: str = "md5") -> Optional[str]:
        """Hash en caché si el archivo no cambió (tamaño y mtime); nunca escribe."""
        try:
            stat = os.stat(file_path)
        except OSError:
            return None
        result = self.get_hashes_batch(
            [(cache_key_for(file_path), stat.st_size, stat.st_mtime)], algorithm
        )
        return next(iter(result.values()), None)

    def get_hashes_batch(
        self, entries: Sequence[Tuple[str, int, float]], algorithm: str = "md5"
    ) -> Dict[str, str]:
        """Busca varios archivos a la vez.

        Args:
            entries: tuplas ``(clave, tamaño, mtime)``; la clave debe venir de
                :func:`cache_key_for`.
        Returns:
            ``{clave: hash}`` solo para entradas válidas (mismo tamaño y mtime).
        """
        found: Dict[str, str] = {}
        if not entries:
            return found
        expected = {key: (size, mtime) for key, size, mtime in entries}
        keys = list(expected)
        try:
            with self.lock:
                conn = self._get_connection()
                for start in range(0, len(keys), _BATCH):
                    chunk = keys[start:start + _BATCH]
                    placeholders = ",".join("?" * len(chunk))
                    rows = conn.execute(
                        f"SELECT file_path, file_size, mtime, hash_value FROM hash_cache "
                        f"WHERE algorithm = ? AND file_path IN ({placeholders})",
                        (algorithm, *chunk),
                    ).fetchall()
                    for row in rows:
                        size, mtime = expected[row["file_path"]]
                        if row["file_size"] == size and row["mtime"] == mtime:
                            found[row["file_path"]] = row["hash_value"]
        except sqlite3.Error as exc:
            warn(f"HashCache: error leyendo caché: {exc}")
            return {}
        self.session_hits += len(found)
        self.session_misses += len(keys) - len(found)
        return found

    # ------------------------------------------------------------------ escritura
    def save_hash(self, file_path: Path, hash_value: str, algorithm: str = "md5"):
        try:
            stat = os.stat(file_path)
        except OSError:
            return
        self.save_hashes_batch(
            [(cache_key_for(file_path), stat.st_size, stat.st_mtime, hash_value)],
            algorithm,
        )

    def save_hashes_batch(
        self,
        entries: Iterable[Tuple[str, int, float, str]],
        algorithm: str = "md5",
    ) -> int:
        """Guarda ``(clave, tamaño, mtime, hash)`` en una sola transacción."""
        now = datetime.now().isoformat()
        rows = [
            (key, size, mtime, value, algorithm, now)
            for key, size, mtime, value in entries
            if value
        ]
        if not rows:
            return 0
        try:
            with self.lock:
                conn = self._get_connection()
                with conn:
                    conn.executemany(
                        "INSERT OR REPLACE INTO hash_cache "
                        "(file_path, file_size, mtime, hash_value, algorithm, cached_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        rows,
                    )
            return len(rows)
        except sqlite3.Error as exc:
            warn(f"HashCache: error guardando caché: {exc}")
            return 0

    # ------------------------------------------------------------------ limpieza
    def purge_missing_under(
        self, root: str, existing_keys: Optional[Iterable[str]] = None
    ) -> int:
        """Elimina entradas bajo ``root`` cuyos archivos ya no existen.

        ``existing_keys`` (opcional) son las claves vistas en el escaneo actual;
        las que no estén se comprueban en disco antes de borrarlas.
        """
        root_key = cache_key_for(root).rstrip("\\/")
        prefix = root_key + os.sep
        seen = set(existing_keys or ())
        try:
            with self.lock:
                conn = self._get_connection()
                rows = conn.execute(
                    "SELECT DISTINCT file_path FROM hash_cache "
                    "WHERE file_path >= ? AND file_path < ?",
                    (prefix, prefix[:-1] + chr(ord(prefix[-1]) + 1)),
                ).fetchall()
            stale = [
                (row[0],)
                for row in rows
                if row[0] not in seen and not os.path.exists(row[0])
            ]
            if stale:
                with self.lock:
                    conn = self._get_connection()
                    with conn:
                        conn.executemany(
                            "DELETE FROM hash_cache WHERE file_path = ?", stale
                        )
                debug(f"HashCache: {len(stale)} entradas obsoletas eliminadas")
            return len(stale)
        except sqlite3.Error as exc:
            warn(f"HashCache: error purgando caché: {exc}")
            return 0

    def cleanup_missing_files(self, limit: Optional[int] = None) -> int:
        """Elimina entradas de archivos que ya no existen en todo el caché."""
        try:
            with self.lock:
                conn = self._get_connection()
                sql = "SELECT DISTINCT file_path FROM hash_cache"
                if limit:
                    sql += f" LIMIT {int(limit)}"
                rows = conn.execute(sql).fetchall()
            stale = [(row[0],) for row in rows if not os.path.exists(row[0])]
            if stale:
                with self.lock:
                    conn = self._get_connection()
                    with conn:
                        conn.executemany(
                            "DELETE FROM hash_cache WHERE file_path = ?", stale
                        )
                        conn.execute(
                            "UPDATE cache_stats SET last_cleanup = CURRENT_TIMESTAMP WHERE id = 1"
                        )
            return len(stale)
        except sqlite3.Error as exc:
            warn(f"HashCache: error limpiando caché: {exc}")
            return 0

    def cleanup_old_entries(self, days_old: int = 30) -> int:
        """Elimina entradas antiguas cuyo archivo ya no existe o no se ha refrescado."""
        try:
            with self.lock:
                conn = self._get_connection()
                with conn:
                    cursor = conn.execute(
                        "DELETE FROM hash_cache "
                        "WHERE cached_at < datetime('now', '-' || ? || ' days')",
                        (days_old,),
                    )
                    conn.execute(
                        "UPDATE cache_stats SET last_cleanup = CURRENT_TIMESTAMP WHERE id = 1"
                    )
                return cursor.rowcount
        except sqlite3.Error as exc:
            warn(f"HashCache: error limpiando entradas antiguas: {exc}")
            return 0

    def clear_cache(self):
        with self.lock:
            conn = self._get_connection()
            with conn:
                conn.execute("DELETE FROM hash_cache")
        self.session_hits = 0
        self.session_misses = 0

    # ------------------------------------------------------------------ estadísticas
    def get_statistics(self) -> Dict[str, object]:
        total_requests = self.session_hits + self.session_misses
        hit_rate = (self.session_hits / total_requests * 100) if total_requests else 0
        count, _ = self.get_cache_size()
        return {
            "total_hits": self.session_hits,
            "total_misses": self.session_misses,
            "hit_rate_percentage": round(hit_rate, 2),
            "total_entries": count,
            "total_hit_count": self.session_hits,
            "avg_hits_per_entry": round(self.session_hits / count, 2) if count else 0,
            "estimated_time_saved_seconds": 0.0,
        }

    def get_cache_size(self) -> Tuple[int, float]:
        with self.lock:
            conn = self._get_connection()
            count = conn.execute("SELECT COUNT(*) FROM hash_cache").fetchone()[0]
        db_size_mb = (
            self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0
        )
        return count, round(db_size_mb, 2)

    def print_statistics(self):
        """Registra estadísticas del caché de forma legible."""
        stats = self.get_statistics()
        cache_size = self.get_cache_size()
        debug(
            f"Cache hits={stats['total_hits']:,}, misses={stats['total_misses']:,}, "
            f"hit_rate={stats['hit_rate_percentage']:.2f}%, entries={cache_size[0]:,}, "
            f"size_mb={cache_size[1]:.2f}"
        )

    def all_keys(self, algorithm: Optional[str] = None) -> List[str]:
        with self.lock:
            conn = self._get_connection()
            if algorithm:
                rows = conn.execute(
                    "SELECT file_path FROM hash_cache WHERE algorithm = ?", (algorithm,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT file_path FROM hash_cache").fetchall()
        return [row[0] for row in rows]
