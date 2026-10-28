#!/usr/bin/env python3
"""Fingerprint opcional y enriquecimiento online de metadatos."""

from __future__ import annotations

import hashlib
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.error
import urllib.parse
import urllib.request
import json
import subprocess
import shutil


from .audio_acoustid_client import AcoustIDClientMixin
from .audio_candidate_scoring import CandidateScoringMixin
from .audio_discogs_client import DiscogsClientMixin
from .audio_musicbrainz_client import MusicBrainzClientMixin


class AudioFingerprintService(
    AcoustIDClientMixin,
    MusicBrainzClientMixin,
    DiscogsClientMixin,
    CandidateScoringMixin,
):
    """Servicio opcional que prepara fingerprints y metadatos externos."""


    def _is_online_metadata_enabled(self) -> bool:
        try:
            from src.utils.app_config import get_app_config

            return get_app_config().get_audio_online_metadata_enabled()
        except Exception:
            return True

    def _disabled_lookup_result(
        self,
        file_path: Path,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        reason: str = "not_attempted",
    ) -> Dict[str, Any]:
        metadata = dict(metadata or {})
        metadata.setdefault("file_path", str(file_path))
        return {
            "available": False,
            "source": "offline",
            "reason": reason,
            "suggested_updates": self._suggest_from_local(file_path, metadata),
            "confidence": 0,
            "cover_url": "",
            "thumb_url": "",
            "candidates": [],
            "diagnostics": {
                "lookup_mode": "disabled",
                "fingerprint_strategy": "none",
                "acoustid_reason": reason,
                "musicbrainz_reason": reason,
                "discogs_reason": reason,
                "candidate_counts": {
                    "acoustid": 0,
                    "musicbrainz": 0,
                    "discogs": 0,
                },
            },
        }

    def build_lookup_cache_key(
        self, file_path: Path, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        payload = {
            "file_path": str(Path(file_path)),
            "file_size": str((metadata or {}).get("file_size") or ""),
            "mtime": str((metadata or {}).get("mtime") or ""),
            "title": str((metadata or {}).get("title") or "").strip(),
            "artist": str((metadata or {}).get("artist") or "").strip(),
            "album_artist": str((metadata or {}).get("album_artist") or "").strip(),
            "album": str((metadata or {}).get("album") or "").strip(),
            "year": str((metadata or {}).get("year") or "").strip(),
            "genre": str((metadata or {}).get("genre") or "").strip(),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def get_or_lookup_online_metadata(
        self,
        file_path: Path,
        metadata: Optional[Dict[str, Any]] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        from src.core.audio_index import audio_metadata_service

        file_path = Path(file_path)
        metadata = dict(metadata or {})
        metadata.setdefault("file_path", str(file_path))
        cache_key = self.build_lookup_cache_key(file_path, metadata)
        if not force_refresh:
            cached = audio_metadata_service.get_lookup_cache(file_path, cache_key)
            if cached:
                cached.setdefault("file_path", str(file_path))
                cached.setdefault("local_metadata", dict(metadata))
                cached.setdefault(
                    "candidate_count", len(cached.get("candidates") or [])
                )
                cached["cache_status"] = "cached"
                return cached

        if not self._is_online_metadata_enabled():
            disabled_result = self._disabled_lookup_result(
                file_path,
                metadata,
                reason="not_attempted",
            )
            disabled_result["file_path"] = str(file_path)
            disabled_result["local_metadata"] = dict(metadata)
            disabled_result["cache_key"] = cache_key
            disabled_result["candidate_count"] = 0
            return disabled_result

        raw_result = self.lookup_online_metadata(file_path, metadata)
        prepared = self._prepare_lookup_result(
            file_path, metadata, raw_result, cache_key
        )
        prepared["cache_status"] = "fresh"
        prepared["cache_updated_at"] = datetime.now().isoformat(timespec="seconds")
        audio_metadata_service.set_lookup_cache(
            file_path,
            cache_key,
            prepared,
            cover_art=prepared.get("cached_cover_art"),
        )
        return prepared

    def get_cover_art_bytes_for_result(
        self, file_path: Path, result: Optional[Dict[str, Any]] = None
    ) -> bytes | None:
        from src.core.audio_index import audio_metadata_service

        file_path = Path(file_path)
        result = dict(result or {})
        cached_cover_art = result.get("cached_cover_art")
        if cached_cover_art:
            return bytes(cached_cover_art)

        cache_key = str(result.get("cache_key") or "").strip()
        if not cache_key:
            local_metadata = dict(result.get("local_metadata") or {})
            if local_metadata:
                cache_key = self.build_lookup_cache_key(file_path, local_metadata)
        if cache_key:
            cached = audio_metadata_service.get_lookup_cache(file_path, cache_key)
            if cached and cached.get("cached_cover_art"):
                return bytes(cached.get("cached_cover_art") or b"")

        cover_art = self._download_cover_art_for_result(result)
        if cover_art and cache_key:
            audio_metadata_service.update_lookup_cache_cover_art(
                file_path,
                cache_key,
                cover_art,
            )
        return cover_art

    def get_cover_art_bytes_for_url(self, url: str) -> bytes | None:
        return self._download_cover_art_from_url(url)

    def _cover_urls_for_result(
        self, result: Optional[Dict[str, Any]] = None
    ) -> list[str]:
        result = dict(result or {})
        urls: list[str] = []

        def add_url(value: Any) -> None:
            candidate = str(value or "").strip()
            if candidate and candidate not in urls:
                urls.append(candidate)

        add_url(result.get("selected_cover_url"))
        for choice in result.get("cover_choices") or []:
            if isinstance(choice, dict):
                add_url(choice.get("url"))
            else:
                add_url(choice)
        for key in ("cover_url", "thumb_url"):
            add_url(result.get(key))
        for candidate in result.get("candidates") or []:
            for choice in candidate.get("cover_choices") or []:
                if isinstance(choice, dict):
                    add_url(choice.get("url"))
                else:
                    add_url(choice)
            for key in ("cover_url", "thumb_url"):
                add_url(candidate.get(key))
        return urls

    def _download_cover_art_for_result(
        self, result: Optional[Dict[str, Any]] = None
    ) -> bytes | None:
        for url in self._cover_urls_for_result(result):
            data = self._download_cover_art_from_url(url)
            if data:
                return data
        return None

    def _download_cover_art_from_url(self, url: str) -> bytes | None:
        value = str(url or "").strip()
        if not value:
            return None
        try:
            request = urllib.request.Request(
                value,
                headers={"User-Agent": self._resolve_useragent()},
            )
            with urllib.request.urlopen(request, timeout=12) as response:
                data = response.read()
            return data if data else None
        except Exception:
            return None

    def _prepare_lookup_result(
        self,
        file_path: Path,
        metadata: Dict[str, Any],
        result: Dict[str, Any],
        cache_key: str,
    ) -> Dict[str, Any]:
        diagnostics = result.get("diagnostics", {})
        candidate_list = list(result.get("candidates", []))
        cover_choices = self._build_cover_choices(result, candidate_list)
        for candidate in candidate_list:
            candidate.setdefault("diagnostics", diagnostics)
            candidate.setdefault("reason", result.get("reason", "ok"))
            candidate.setdefault(
                "fingerprint_strategy",
                diagnostics.get("fingerprint_strategy", "none"),
            )
        cover_art = self._download_cover_art_for_result(result)
        return {
            "file_path": str(file_path),
            "local_metadata": dict(metadata),
            "confidence": candidate_list[0].get("confidence", 0)
            if candidate_list
            else 0,
            "candidate_count": len(candidate_list),
            "cache_key": cache_key,
            "cached_cover_art": cover_art,
            "cache_status": "fresh",
            "cover_choices": cover_choices,
            **result,
            "candidates": candidate_list,
        }

    def _build_cover_choices(
        self, result: Dict[str, Any], candidate_list: list[Dict[str, Any]]
    ) -> list[Dict[str, str]]:
        seen: set[str] = set()
        choices: list[Dict[str, str]] = []

        def add_choice(url: str, source: str, label: str) -> None:
            normalized = str(url or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            choices.append(
                {
                    "url": normalized,
                    "source": str(source or "unknown"),
                    "label": str(label or "Portada"),
                }
            )

        add_choice(
            str(result.get("cover_url") or result.get("thumb_url") or ""),
            str(result.get("source") or "unknown"),
            "Principal",
        )
        add_choice(
            str(result.get("thumb_url") or ""),
            str(result.get("source") or "unknown"),
            "Miniatura principal",
        )
        for index, candidate in enumerate(candidate_list, start=1):
            suggested = dict(candidate.get("suggested_updates") or {})
            album = str(suggested.get("album") or candidate.get("album") or "").strip()
            label = album or f"Candidata {index}"
            add_choice(
                str(candidate.get("cover_url") or candidate.get("thumb_url") or ""),
                str(candidate.get("source") or result.get("source") or "unknown"),
                label,
            )
            add_choice(
                str(candidate.get("thumb_url") or ""),
                str(candidate.get("source") or result.get("source") or "unknown"),
                f"{label} (miniatura)",
            )
        return choices

    def fingerprint_file(self, file_path: Path) -> Dict[str, Any]:
        file_path = Path(file_path)
        acoustid_key = self._get_acoustid_api_key()
        fpcalc_path = self._resolve_fpcalc_path()
        self._debug(
            f"Fingerprint start | file={file_path.name} | acoustid_key={self._mask_secret(acoustid_key)} | fpcalc={fpcalc_path or 'missing'}"
        )
        if acoustid_key and fpcalc_path:
            try:
                self._debug(
                    f"Running fpcalc | file={file_path.name} | binary={fpcalc_path}"
                )
                result = subprocess.run(
                    [fpcalc_path, str(file_path)],
                    capture_output=True,
                    text=True,
                    timeout=25,
                    check=True,
                )
                payload = self._parse_fpcalc_output(result.stdout)
                if not payload:
                    self._debug(
                        f"fpcalc unparsed stdout | file={file_path.name} | {self._preview_value(result.stdout, 700)}"
                    )
                    if result.stderr:
                        self._debug(
                            f"fpcalc stderr | file={file_path.name} | {self._preview_value(result.stderr, 280)}"
                        )
                    raise ValueError("fpcalc_output_unparsed")
                fingerprint_value = str(payload.get("fingerprint") or "")
                self._debug(
                    "fpcalc ok | "
                    f"file={file_path.name} | duration={payload.get('duration')} | "
                    f"fingerprint_len={len(fingerprint_value)} | "
                    f"fingerprint_preview={self._preview_value(fingerprint_value, 36)}"
                )
                return {
                    "file_path": str(file_path),
                    "fingerprint": payload.get("fingerprint"),
                    "duration": payload.get("duration"),
                    "strategy": "chromaprint",
                    "available": True,
                }
            except Exception as exc:
                self._debug(
                    f"fpcalc failed | file={file_path.name} | error={type(exc).__name__}: {exc}"
                )
                stdout = getattr(exc, "stdout", "")
                stderr = getattr(exc, "stderr", "")
                if stdout:
                    self._debug(
                        f"fpcalc stdout | file={file_path.name} | {self._preview_value(stdout, 280)}"
                    )
                if stderr:
                    self._debug(
                        f"fpcalc stderr | file={file_path.name} | {self._preview_value(stderr, 280)}"
                    )
        else:
            reasons = []
            if not acoustid_key:
                reasons.append("missing_acoustid_key")
            if not fpcalc_path:
                reasons.append("missing_fpcalc")
            self._debug(
                f"Chromaprint skip | file={file_path.name} | reason={'+'.join(reasons) or 'unknown'}"
            )
        try:
            digest = hashlib.sha1()
            size = 0
            with open(file_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    size += len(chunk)
            sha1_value = digest.hexdigest()
            self._debug(
                f"SHA1 fallback | file={file_path.name} | size={size} | sha1={sha1_value[:16]}..."
            )
            return {
                "file_path": str(file_path),
                "fingerprint": sha1_value,
                "strategy": "sha1-file",
                "available": True,
            }
        except Exception as exc:
            self._debug(
                f"Fingerprint unavailable | file={file_path.name} | error={type(exc).__name__}: {exc}"
            )
            return {
                "file_path": str(file_path),
                "fingerprint": None,
                "strategy": "unavailable",
                "available": False,
                "error": str(exc),
            }

    def local_chromaprint(self, file_path: Path) -> Dict[str, Any] | None:
        """Huella Chromaprint local con ``fpcalc`` (sin clave de AcoustID ni red).

        Devuelve ``{"fingerprint", "duration"}`` o None si ``fpcalc`` no está
        disponible o falla.
        """
        fpcalc_path = self._resolve_fpcalc_path()
        if not fpcalc_path:
            return None
        try:
            result = subprocess.run(
                [fpcalc_path, str(file_path)],
                capture_output=True,
                text=True,
                timeout=25,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._debug(f"fpcalc local falló | file={Path(file_path).name} | {exc}")
            return None
        payload = self._parse_fpcalc_output(result.stdout)
        if not payload or not payload.get("fingerprint"):
            return None
        return payload

    def lookup_online_metadata(
        self, file_path: Path, metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Busca candidatos online gratuitos y devuelve sugerencias priorizadas."""
        metadata = metadata or {}
        if not self._is_online_metadata_enabled():
            return self._disabled_lookup_result(
                Path(file_path),
                metadata,
                reason="not_attempted",
            )
        self._debug(
            "Online lookup start | "
            f"file={Path(file_path).name} | "
            f"title={self._preview_value(metadata.get('title') or '', 80)} | "
            f"artist={self._preview_value(metadata.get('artist') or metadata.get('album_artist') or '', 80)} | "
            f"album={self._preview_value(metadata.get('album') or '', 80)}"
        )
        useragent = self._resolve_useragent()
        self._debug(
            f"Online lookup user-agent | file={Path(file_path).name} | ua={useragent}"
        )
        if not useragent:
            return {
                "available": False,
                "source": "offline",
                "reason": "missing_useragent",
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "candidates": [],
            }

        acoustid_result = self.lookup_acoustid(file_path, metadata)
        self._debug(
            "AcoustID result | "
            f"file={Path(file_path).name} | reason={acoustid_result.get('reason', 'unknown')} | "
            f"candidates={len(acoustid_result.get('candidates', []))} | "
            f"fingerprint={acoustid_result.get('fingerprint_strategy', 'none')}"
        )
        musicbrainz_result = self.lookup_musicbrainz_candidates(file_path, metadata)
        self._debug(
            "MusicBrainz result | "
            f"file={Path(file_path).name} | reason={musicbrainz_result.get('reason', 'unknown')} | "
            f"candidates={len(musicbrainz_result.get('candidates', []))} | "
            f"query={self._preview_value(musicbrainz_result.get('query') or '', 120)}"
        )
        discogs_result = self.lookup_discogs(file_path, metadata)
        discogs_reason = discogs_result.get("reason", "unknown")
        self._debug(
            "Discogs result | "
            f"file={Path(file_path).name} | reason={discogs_reason} | "
            f"candidates={len(discogs_result.get('candidates', []))}"
        )

        acoustid_candidates = list(acoustid_result.get("candidates", []))
        musicbrainz_candidates = list(musicbrainz_result.get("candidates", []))
        discogs_candidates = list(discogs_result.get("candidates", []))
        combined_candidates = self._merge_lookup_candidates(
            acoustid_candidates,
            musicbrainz_candidates,
            discogs_candidates,
        )
        diagnostics = {
            "acoustid_reason": acoustid_result.get("reason", "not_used"),
            "fingerprint_strategy": acoustid_result.get("fingerprint_strategy", "none"),
            "lookup_mode": "combined",
            "musicbrainz_query": musicbrainz_result.get("query", ""),
            "musicbrainz_reason": musicbrainz_result.get("reason", "not_run"),
            "discogs_reason": discogs_reason,
            "candidate_counts": {
                "acoustid": len(acoustid_candidates),
                "musicbrainz": len(musicbrainz_candidates),
                "discogs": len(discogs_candidates),
            },
        }
        self._debug(
            "Combined lookup result | "
            f"file={Path(file_path).name} | acoustid={len(acoustid_candidates)} | "
            f"musicbrainz={len(musicbrainz_candidates)} | discogs={len(discogs_candidates)} | "
            f"total={len(combined_candidates)} | top={self._summarize_candidates(combined_candidates)}"
        )

        if combined_candidates:
            top_candidate = combined_candidates[0]
            return {
                "available": True,
                "source": top_candidate.get("source", "unknown"),
                "reason": "ok",
                "suggested_updates": top_candidate.get("suggested_updates", {}),
                "confidence": top_candidate.get("confidence", 0),
                "cover_url": top_candidate.get("cover_url", ""),
                "thumb_url": top_candidate.get("thumb_url", ""),
                "diagnostics": diagnostics,
                "candidates": combined_candidates,
            }

        return {
            "available": False,
            "source": "mixed",
            "reason": self._select_lookup_reason(
                [
                    acoustid_result.get("reason", ""),
                    musicbrainz_result.get("reason", ""),
                    discogs_result.get("reason", ""),
                ]
            ),
            "suggested_updates": self._suggest_from_local(file_path, metadata),
            "confidence": 0,
            "cover_url": "",
            "thumb_url": "",
            "diagnostics": diagnostics,
            "candidates": [],
        }





    def build_batch_suggestions(
        self, tracks: list[Dict[str, Any]]
    ) -> list[Dict[str, Any]]:
        items = []
        for track in tracks:
            file_path = Path(track.get("file_path", ""))
            result = self.get_or_lookup_online_metadata(file_path, track)
            result["file_path"] = str(file_path)
            items.append(result)
        return items

































    def _suggest_from_local(
        self, file_path: Path, metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        updates: Dict[str, Any] = {}
        if not metadata.get("title"):
            updates["title"] = file_path.stem
        if not metadata.get("album"):
            updates["album"] = file_path.parent.name
        if not metadata.get("artist"):
            updates["artist"] = metadata.get("album_artist") or "Unknown Artist"
        return updates

    def _parse_fpcalc_output(self, output: str) -> Dict[str, Any]:
        text = str(output or "").strip()
        if not text:
            return {}
        if text.startswith("{"):
            try:
                payload = json.loads(text)
                return {
                    "fingerprint": payload.get("fingerprint"),
                    "duration": self._coerce_numeric(payload.get("duration")),
                }
            except Exception:
                return {}
        parsed: Dict[str, Any] = {}
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            normalized_key = key.strip().lower()
            parsed[normalized_key] = value.strip()
        fingerprint = parsed.get("fingerprint")
        duration = self._coerce_numeric(parsed.get("duration"))
        if not fingerprint:
            return {}
        return {"fingerprint": fingerprint, "duration": duration}

    def _coerce_numeric(self, value: Any) -> float | int | None:
        if value in (None, ""):
            return None
        try:
            numeric = float(value)
        except Exception:
            return None
        if numeric.is_integer():
            return int(numeric)
        return numeric


    def _debug(self, message: str) -> None:
        from src.utils.logger import debug as logger_debug

        logger_debug(f"[AudioFingerprint] {message}")

    def _mask_secret(self, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            return "missing"
        if len(value) <= 8:
            return "*" * len(value)
        return f"{value[:4]}...{value[-4:]}"

    def _preview_value(self, value: Any, limit: int = 400) -> str:
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, ensure_ascii=True, default=str)
        else:
            text = str(value or "")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "...(truncated)"

    def _debug_payload(self, label: str, payload: Any, limit: int = 600) -> None:
        self._debug(f"{label} | payload={self._preview_value(payload, limit)}")

    def _summarize_candidates(
        self, candidates: list[Dict[str, Any]], limit: int = 3
    ) -> str:
        parts: list[str] = []
        for candidate in candidates[:limit]:
            artist = (
                self.clean_text_for_query(str(candidate.get("artist") or "")) or "?"
            )
            title = self.clean_text_for_query(str(candidate.get("title") or "")) or "?"
            source = str(candidate.get("source") or "?")
            confidence = candidate.get("confidence", 0)
            parts.append(f"{artist} - {title} [{source}:{confidence}]")
        return " | ".join(parts) if parts else "none"


    def _resolve_fpcalc_path(self) -> str | None:
        exe_name = "fpcalc.exe" if os.name == "nt" else "fpcalc"
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "bin" / exe_name)
        candidates.append(Path.cwd() / "bin" / exe_name)
        candidates.append(Path(__file__).resolve().parents[2] / "bin" / exe_name)
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return shutil.which(exe_name) or shutil.which("fpcalc")





audio_fingerprint_service = AudioFingerprintService()
