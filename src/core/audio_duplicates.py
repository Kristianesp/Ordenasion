#!/usr/bin/env python3
"""
Detección de duplicados musicales.

Reglas de identidad (de más a menos segura):

1. **Metadatos**: solo pistas legibles (sin error de mutagen), con duración y
   con al menos título y artista.  Se agrupan por artista + título + álbum
   normalizados y la duración se compara con tolerancia (±2 s por defecto),
   nunca redondeando.
2. **Chromaprint local** (si ``fpcalc`` está disponible): para pistas
   legibles sin título/artista; misma huella y duración compatible.
3. **Contenido**: hash MD5 completo (leído por bloques, con caché) entre
   archivos del mismo tamaño.  Es la única regla para archivos con error.

Las pistas sin identidad fiable nunca se agrupan entre sí.
"""

from __future__ import annotations

import hashlib
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.utils.logger import debug
from .audio_index import AudioMetadata, audio_metadata_service

DEFAULT_DURATION_TOLERANCE = 2.0

MATCH_METADATA = "metadatos"
MATCH_CHROMAPRINT = "chromaprint"
MATCH_CONTENT = "contenido"


@dataclass
class AudioDuplicateCandidate:
    file_path: str
    title: str = ""
    artist: str = ""
    album: str = ""
    codec: str = "unknown"
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    bit_depth: Optional[int] = None
    duration: Optional[float] = None
    lossless: Optional[bool] = None
    file_size: int = 0
    identity_key: str = ""
    quality_score: int = 0
    match_basis: str = MATCH_METADATA

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AudioDuplicateFinder:
    """Agrupa audio por identidad fiable y calcula calidad relativa."""

    def __init__(self, duration_tolerance: float = DEFAULT_DURATION_TOLERANCE,
                 use_chromaprint: Optional[bool] = None, hash_manager=None):
        self.audio_service = audio_metadata_service
        self.duration_tolerance = float(duration_tolerance)
        self.use_chromaprint = use_chromaprint
        self._hash_manager = hash_manager

    # ------------------------------------------------------------------ helpers
    @property
    def hash_manager(self):
        if self._hash_manager is None:
            from .hash_manager import HashManager

            self._hash_manager = HashManager()
        return self._hash_manager

    def _normalize_text(self, value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _cancelled(cancel_event) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _has_metadata_identity(self, meta: AudioMetadata) -> bool:
        if meta.error:
            return False
        if not meta.duration or float(meta.duration) <= 0:
            return False
        artist = self._normalize_text(meta.artist) or self._normalize_text(meta.album_artist)
        return bool(self._normalize_text(meta.title) and artist)

    def _metadata_bucket(self, meta: AudioMetadata) -> str:
        artist = self._normalize_text(meta.artist) or self._normalize_text(meta.album_artist)
        raw = "|".join([artist, self._normalize_text(meta.title), self._normalize_text(meta.album)])
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def _build_identity_key(self, meta: AudioMetadata) -> str:
        """Clave del cubo de metadatos (la duración se agrupa aparte con tolerancia)."""
        if self._has_metadata_identity(meta):
            return f"meta:{self._metadata_bucket(meta)}"
        return f"md5:{self._file_fingerprint(Path(meta.file_path))}"

    def _file_fingerprint(self, file_path: Path) -> str:
        """Hash de contenido leído por bloques (nunca ``read_bytes``)."""
        result = self.hash_manager.hash_file(Path(file_path), allow_partial=False)
        if result.ok:
            return result.value
        return hashlib.sha1(f"sin-hash:{file_path}".encode("utf-8")).hexdigest()

    def _cluster_by_duration(self, items: Sequence[AudioMetadata],
                             duration_of: Callable[[AudioMetadata], float]) -> List[List[AudioMetadata]]:
        """Clusters cuyos miembros distan como mucho ``tolerance`` del primero."""
        ordered = sorted(items, key=duration_of)
        clusters: List[List[AudioMetadata]] = []
        for meta in ordered:
            if clusters and duration_of(meta) - duration_of(clusters[-1][0]) <= self.duration_tolerance:
                clusters[-1].append(meta)
            else:
                clusters.append([meta])
        return [c for c in clusters if len(c) >= 2]

    def _chromaprint_enabled(self) -> bool:
        if self.use_chromaprint is not None:
            return bool(self.use_chromaprint)
        try:
            from src.utils.app_config import AppConfig

            return bool(AppConfig().get("audio.local_chromaprint", True))
        except (ImportError, OSError, ValueError):
            return True

    def _chromaprint(self, meta: AudioMetadata) -> Optional[Dict[str, Any]]:
        try:
            from .audio_fingerprint import audio_fingerprint_service

            return audio_fingerprint_service.local_chromaprint(Path(meta.file_path))
        except (ImportError, OSError) as exc:
            debug(f"Chromaprint local no disponible: {exc}")
            return None

    # ------------------------------------------------------------------ API
    def scan_folder(
        self,
        folder_path: str,
        recursive: bool = True,
        metadata: Optional[Sequence[AudioMetadata]] = None,
        cancel_event: Optional[threading.Event] = None,
        progress: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Grupos de duplicados ``{clave: [pistas ordenadas por calidad]}``.

        ``metadata`` permite reutilizar el resultado de ``index_folder_detailed``
        para no volver a analizar cada pista con mutagen.
        """
        root = Path(folder_path)
        if not root.exists():
            return {}
        if metadata is None:
            metadata = self.audio_service.index_folder_detailed(
                root, recursive=recursive, cancel_event=cancel_event)

        by_meta: Dict[str, List[AudioMetadata]] = defaultdict(list)
        no_identity: List[AudioMetadata] = []
        for meta in metadata:
            if meta.error == "mutagen_no_disponible" and not meta.file_size:
                continue
            if self._has_metadata_identity(meta):
                by_meta[self._metadata_bucket(meta)].append(meta)
            else:
                no_identity.append(meta)

        groups: Dict[str, List[AudioDuplicateCandidate]] = {}

        # 1. Metadatos con tolerancia de duración
        for bucket, items in by_meta.items():
            if len(items) < 2:
                continue
            for index, cluster in enumerate(
                self._cluster_by_duration(items, lambda m: float(m.duration or 0))
            ):
                key = f"meta:{bucket}:{index}"
                groups[key] = [self._build_candidate(m, key, MATCH_METADATA) for m in cluster]

        if self._cancelled(cancel_event):
            from .duplicate_finder import ScanCancelled
            raise ScanCancelled()

        # 2. Chromaprint local para pistas legibles sin título/artista
        remaining: List[AudioMetadata] = []
        readable = [m for m in no_identity if not m.error and m.duration]
        if len(readable) >= 2 and self._chromaprint_enabled():
            if progress:
                progress(f"🎼 Huellas Chromaprint de {len(readable)} pista(s) sin etiquetas...")
            by_print: Dict[str, List[AudioMetadata]] = defaultdict(list)
            durations: Dict[str, float] = {}
            available = True
            for meta in readable:
                if self._cancelled(cancel_event):
                    from .duplicate_finder import ScanCancelled
                    raise ScanCancelled()
                if not available:
                    remaining.append(meta)
                    continue
                printed = self._chromaprint(meta)
                if printed is None:
                    available = False  # fpcalc ausente: el resto va por contenido
                    remaining.append(meta)
                    continue
                fingerprint = str(printed.get("fingerprint") or "")
                if not fingerprint:
                    remaining.append(meta)
                    continue
                digest = hashlib.sha1(fingerprint.encode("ascii", errors="ignore")).hexdigest()
                by_print[digest].append(meta)
                durations[meta.file_path] = float(printed.get("duration") or meta.duration or 0)
            for digest, items in by_print.items():
                if len(items) < 2:
                    continue
                for index, cluster in enumerate(
                    self._cluster_by_duration(items, lambda m: durations.get(m.file_path, 0.0))
                ):
                    key = f"chromaprint:{digest}:{index}"
                    groups[key] = [self._build_candidate(m, key, MATCH_CHROMAPRINT) for m in cluster]
            readable_ids = {id(m) for m in readable}
            remaining.extend(m for m in no_identity if id(m) not in readable_ids)
        else:
            remaining = list(no_identity)

        # 3. Contenido idéntico (mismo tamaño → hash completo por bloques)
        by_size: Dict[int, List[AudioMetadata]] = defaultdict(list)
        for meta in remaining:
            if meta.file_size:
                by_size[meta.file_size].append(meta)
        to_hash = [Path(m.file_path) for items in by_size.values() if len(items) >= 2 for m in items]
        if to_hash:
            if progress:
                progress(f"🔍 Comparando contenido de {len(to_hash)} pista(s) sin identidad fiable...")
            results = self.hash_manager.hash_many(to_hash, allow_partial=False, cancel_event=cancel_event)
            by_hash: Dict[str, List[AudioMetadata]] = defaultdict(list)
            for items in by_size.values():
                if len(items) < 2:
                    continue
                for meta in items:
                    result = results.get(Path(meta.file_path))
                    if result and result.ok:
                        by_hash[result.value].append(meta)
            for value, items in by_hash.items():
                if len(items) >= 2:
                    key = f"md5:{value}"
                    groups[key] = [self._build_candidate(m, key, MATCH_CONTENT) for m in items]

        duplicate_groups: Dict[str, List[Dict[str, Any]]] = {}
        for key, candidates in groups.items():
            ranked = sorted(candidates, key=lambda item: item.quality_score, reverse=True)
            duplicate_groups[key] = [item.to_dict() for item in ranked]
        return duplicate_groups

    def _iter_audio_files(self, root: Path, recursive: bool):
        for entry in self.audio_service.iter_audio_files(root, recursive):
            yield entry.path

    def _build_candidate(self, meta: AudioMetadata, identity_key: str,
                         match_basis: str = MATCH_METADATA) -> AudioDuplicateCandidate:
        return AudioDuplicateCandidate(
            file_path=meta.file_path,
            title=meta.title,
            artist=meta.artist,
            album=meta.album,
            codec=meta.codec,
            bitrate=meta.bitrate,
            sample_rate=meta.sample_rate,
            channels=meta.channels,
            bit_depth=meta.bit_depth,
            duration=meta.duration,
            lossless=meta.lossless,
            file_size=meta.file_size,
            identity_key=identity_key,
            quality_score=self._quality_score(meta),
            match_basis=match_basis,
        )

    def _quality_score(self, meta: AudioMetadata) -> int:
        score = 0
        if meta.lossless:
            score += 5000
        if meta.bitrate:
            score += min(meta.bitrate // 1000, 3200)
        if meta.sample_rate:
            score += min(meta.sample_rate // 10, 500)
        if meta.channels:
            score += meta.channels * 100
        if meta.bit_depth:
            score += meta.bit_depth * 50
        score += min(meta.file_size // (1024 * 1024), 2000)
        if meta.codec:
            codec = meta.codec.lower()
            if any(token in codec for token in ("flac", "alac", "wav")):
                score += 1500
            elif any(token in codec for token in ("mp3", "aac", "ogg", "wma")):
                score += 500
        return score


audio_duplicate_finder = AudioDuplicateFinder()
