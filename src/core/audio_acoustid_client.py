#!/usr/bin/env python3
"""Cliente de AcoustID (huella Chromaprint + búsqueda online).

Mixin de ``AudioFingerprintService`` (ver ``audio_fingerprint``)."""

from __future__ import annotations

import os
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


class AcoustIDClientMixin:
    """Cliente de AcoustID (huella Chromaprint + búsqueda online)."""

    def lookup_acoustid(
        self, file_path: Path, metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        metadata = metadata or {}
        api_key = self._get_acoustid_api_key()
        fingerprint = self.fingerprint_file(file_path)
        diagnostics = {
            "lookup_mode": "acoustid",
            "fingerprint_strategy": fingerprint.get("strategy", "none"),
            "acoustid_reason": "pending",
        }
        if not api_key:
            diagnostics["acoustid_reason"] = "missing_api_key"
            self._debug(
                f"AcoustID skipped | file={Path(file_path).name} | reason=missing_api_key"
            )
            return {
                "available": False,
                "source": "acoustid",
                "reason": "missing_api_key",
                "fingerprint_strategy": fingerprint.get("strategy", "none"),
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "diagnostics": diagnostics,
                "candidates": [],
            }
        if not fingerprint.get("available") or not fingerprint.get("fingerprint"):
            diagnostics["acoustid_reason"] = "fingerprint_unavailable"
            self._debug(
                "AcoustID skipped | "
                f"file={Path(file_path).name} | reason=fingerprint_unavailable | "
                f"strategy={fingerprint.get('strategy', 'none')}"
            )
            return {
                "available": False,
                "source": "acoustid",
                "reason": "fingerprint_unavailable",
                "fingerprint_strategy": fingerprint.get("strategy", "none"),
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "diagnostics": diagnostics,
                "candidates": [],
            }
        duration = int(float(fingerprint.get("duration") or 0))
        fingerprint_value = str(fingerprint.get("fingerprint") or "")
        if fingerprint.get("strategy") != "chromaprint" or duration <= 0:
            diagnostics["acoustid_reason"] = "invalid_fingerprint_payload"
            self._debug(
                "AcoustID skipped | "
                f"file={Path(file_path).name} | reason=invalid_fingerprint_payload | "
                f"strategy={fingerprint.get('strategy', 'none')} | duration={duration}"
            )
            return {
                "available": False,
                "source": "acoustid",
                "reason": "invalid_fingerprint_payload",
                "fingerprint_strategy": fingerprint.get("strategy", "none"),
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "diagnostics": diagnostics,
                "candidates": [],
            }
        self._debug(
            "AcoustID request | "
            f"file={Path(file_path).name} | duration={duration} | "
            f"fingerprint_strategy={fingerprint.get('strategy', 'none')} | "
            f"fingerprint_len={len(fingerprint_value)} | "
            f"fingerprint_preview={self._preview_value(fingerprint_value, 36)}"
        )
        params = urllib.parse.urlencode(
            {
                "client": api_key,
                "duration": duration,
                "fingerprint": fingerprint.get("fingerprint"),
                "meta": "recordings+releases+releasegroups+compress",
            }
        )
        request = urllib.request.Request(
            f"https://api.acoustid.org/v2/lookup?{params}",
            headers={"User-Agent": self._resolve_useragent()},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                response_status = (
                    getattr(response, "status", None) or response.getcode()
                )
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            diagnostics["acoustid_reason"] = "lookup_failed"
            body = exc.read().decode("utf-8", errors="ignore")
            error_reason = self._parse_acoustid_error_reason(body) or "lookup_failed"
            diagnostics["acoustid_reason"] = error_reason
            self._debug(
                "AcoustID HTTP error | "
                f"file={Path(file_path).name} | status={exc.code} | reason={exc.reason}"
            )
            if body:
                self._debug(
                    f"AcoustID error body | file={Path(file_path).name} | {self._preview_value(body, 700)}"
                )
            if error_reason == "invalid_client_key":
                self._debug(
                    "AcoustID hint | lookup expects the application client key; the profile page key is not valid for client="
                )
            return {
                "available": False,
                "source": "acoustid",
                "reason": error_reason,
                "fingerprint_strategy": fingerprint.get("strategy", "none"),
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "diagnostics": diagnostics,
                "candidates": [],
            }
        except Exception as exc:
            diagnostics["acoustid_reason"] = "lookup_failed"
            self._debug(
                f"AcoustID lookup failed | file={Path(file_path).name} | error={type(exc).__name__}: {exc}"
            )
            return {
                "available": False,
                "source": "acoustid",
                "reason": "lookup_failed",
                "fingerprint_strategy": fingerprint.get("strategy", "none"),
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "diagnostics": diagnostics,
                "candidates": [],
            }
        payload = self._hydrate_acoustid_results(payload, api_key, file_path)
        raw_results = payload.get("results", [])
        raw_recordings = sum(len(item.get("recordings", [])) for item in raw_results)
        self._debug(
            "AcoustID response | "
            f"file={Path(file_path).name} | http_status={response_status} | "
            f"api_status={payload.get('status')} | results={len(raw_results)} | recordings={raw_recordings}"
        )
        self._debug_payload("AcoustID response", payload, limit=900)
        candidates = self._parse_acoustid_results(payload, metadata)
        diagnostics["acoustid_reason"] = "ok" if candidates else "no_candidates"
        self._debug(
            "AcoustID parsed candidates | "
            f"file={Path(file_path).name} | kept={len(candidates)} | "
            f"top={self._summarize_candidates(candidates)}"
        )
        return {
            "available": bool(candidates),
            "source": "acoustid",
            "reason": "ok" if candidates else "no_candidates",
            "fingerprint_strategy": fingerprint.get("strategy", "none"),
            "suggested_updates": candidates[0].get("suggested_updates", {})
            if candidates
            else self._suggest_from_local(file_path, metadata),
            "diagnostics": diagnostics,
            "candidates": candidates,
        }

    def _parse_acoustid_results(
        self, payload: Dict[str, Any], local: Dict[str, Any]
    ) -> list[Dict[str, Any]]:
        candidates: list[Dict[str, Any]] = []
        for result in payload.get("results", []):
            score = float(result.get("score") or 0.0)
            for recording in result.get("recordings", []):
                candidate = self._build_candidate_from_recording(
                    self._normalize_acoustid_recording(recording), local
                )
                candidate["source"] = "acoustid"
                candidate["confidence"] = max(
                    candidate.get("confidence", 0), int(score * 100)
                )
                candidates.append(candidate)
        candidates = self._filter_irrelevant_candidates(candidates, local)
        ranked = sorted(
            candidates, key=lambda item: item.get("confidence", 0), reverse=True
        )
        return self._dedupe_candidates(ranked)[:10]

    def _hydrate_acoustid_results(
        self, payload: Dict[str, Any], api_key: str, file_path: Path
    ) -> Dict[str, Any]:
        results = payload.get("results", [])
        hydrated = False
        for result in results:
            if result.get("recordings"):
                continue
            track_id = str(result.get("id") or "").strip()
            if not track_id:
                continue
            recordings = self._lookup_acoustid_trackid(track_id, api_key, file_path)
            if recordings:
                result["recordings"] = recordings
                hydrated = True
        if hydrated:
            self._debug_payload("AcoustID hydrated response", payload, limit=900)
        return payload

    def _lookup_acoustid_trackid(
        self, track_id: str, api_key: str, file_path: Path
    ) -> list[Dict[str, Any]]:
        params = urllib.parse.urlencode(
            {
                "client": api_key,
                "trackid": track_id,
                "meta": "recordings+releases+releasegroups+compress",
            }
        )
        request = urllib.request.Request(
            f"https://api.acoustid.org/v2/lookup?{params}",
            headers={"User-Agent": self._resolve_useragent()},
        )
        self._debug(
            f"AcoustID track lookup | file={file_path.name} | trackid={track_id}"
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                response_status = (
                    getattr(response, "status", None) or response.getcode()
                )
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            self._debug(
                "AcoustID track HTTP error | "
                f"file={file_path.name} | trackid={track_id} | status={exc.code} | reason={exc.reason}"
            )
            if body:
                self._debug(
                    f"AcoustID track error body | file={file_path.name} | {self._preview_value(body, 700)}"
                )
            return []
        except Exception as exc:
            self._debug(
                f"AcoustID track lookup failed | file={file_path.name} | trackid={track_id} | error={type(exc).__name__}: {exc}"
            )
            return []
        results = payload.get("results", [])
        recordings = []
        for result in results:
            recordings.extend(result.get("recordings", []))
        self._debug(
            "AcoustID track response | "
            f"file={file_path.name} | trackid={track_id} | http_status={response_status} | recordings={len(recordings)}"
        )
        if payload:
            self._debug_payload("AcoustID track response", payload, limit=800)
        return recordings

    def _normalize_acoustid_recording(
        self, recording: Dict[str, Any]
    ) -> Dict[str, Any]:
        rec = dict(recording or {})
        if not rec.get("artist-credit") and rec.get("artists"):
            rec["artist-credit"] = [
                {"name": str(item.get("name") or "")}
                for item in rec.get("artists", [])
                if isinstance(item, dict)
            ]
        if not rec.get("release-list"):
            releases = rec.get("releases") or []
            release_groups = rec.get("releasegroups") or []
            if releases:
                rec["release-list"] = releases
            elif release_groups:
                rec["release-list"] = [
                    {
                        "title": str(group.get("title") or ""),
                        "date": str(group.get("first-release-date") or ""),
                    }
                    for group in release_groups
                    if isinstance(group, dict)
                ]
        return rec

    def _parse_acoustid_error_reason(self, body: str) -> str:
        text = str(body or "").strip()
        if not text:
            return "lookup_failed"
        try:
            payload = json.loads(text)
        except Exception:
            lowered = text.lower()
            if "invalid api key" in lowered:
                return "invalid_client_key"
            return "lookup_failed"
        message = (
            str(payload.get("error", {}).get("message") or payload.get("message") or "")
            .strip()
            .lower()
        )
        if "invalid api key" in message:
            return "invalid_client_key"
        return "lookup_failed"

    def _get_acoustid_api_key(self) -> str:
        try:
            from src.utils.app_config import AppConfig

            config_key = AppConfig().get_acoustid_api_key().strip()
            if config_key:
                return config_key
        except Exception:
            pass
        return os.environ.get("ACOUSTID_API_KEY", "").strip()
