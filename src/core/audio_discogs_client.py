#!/usr/bin/env python3
"""Cliente de Discogs.

Mixin de ``AudioFingerprintService`` (ver ``audio_fingerprint``)."""

from __future__ import annotations

import os
import re
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


class DiscogsClientMixin:
    """Cliente de Discogs."""

    def lookup_discogs(
        self, file_path: Path, metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        metadata = metadata or {}
        token = self._get_discogs_token()
        discogs_enabled = self._get_discogs_enabled()
        diagnostics = {
            "lookup_mode": "discogs_fallback",
            "fingerprint_strategy": "none",
            "acoustid_reason": "not_used",
            "discogs_reason": "pending",
        }
        self._debug(
            "Discogs config | "
            f"file={Path(file_path).name} | enabled={discogs_enabled} | token={self._mask_secret(token)}"
        )
        if not token or not discogs_enabled:
            diagnostics["discogs_reason"] = "disabled_or_missing_token"
            self._debug(
                f"Discogs skipped | file={Path(file_path).name} | reason=disabled_or_missing_token"
            )
            return {
                "available": False,
                "source": "discogs",
                "reason": "disabled_or_missing_token",
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "diagnostics": diagnostics,
                "candidates": [],
            }

        file_artist, file_title = self._split_filename_guess(file_path)
        query = self.clean_text_for_query(file_title or file_path.stem)
        local_title = (
            self._best_value(metadata, ["title"]) or file_title or file_path.stem
        )
        local_artist = (
            self._best_value(metadata, ["artist", "album_artist"]) or file_artist
        )
        artist = self.clean_text_for_query(local_artist)
        params = {"q": query, "type": "release", "per_page": 10}
        if artist:
            params["artist"] = artist
        url = "https://api.discogs.com/database/search?" + urllib.parse.urlencode(
            params
        )
        self._debug(
            "Discogs request | "
            f"file={Path(file_path).name} | query={self._preview_value(query, 120)} | "
            f"artist={self._preview_value(artist, 120)} | url={url}"
        )
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": self._resolve_useragent(),
                "Authorization": f"Discogs token={token}",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                response_status = (
                    getattr(response, "status", None) or response.getcode()
                )
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            diagnostics["discogs_reason"] = "lookup_failed"
            body = exc.read().decode("utf-8", errors="ignore")
            self._debug(
                "Discogs HTTP error | "
                f"file={Path(file_path).name} | status={exc.code} | reason={exc.reason}"
            )
            if body:
                self._debug(
                    f"Discogs error body | file={Path(file_path).name} | {self._preview_value(body, 700)}"
                )
            return {
                "available": False,
                "source": "discogs",
                "reason": "lookup_failed",
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "diagnostics": diagnostics,
                "candidates": [],
            }
        except Exception as exc:
            diagnostics["discogs_reason"] = "lookup_failed"
            self._debug(
                f"Discogs lookup failed | file={Path(file_path).name} | error={type(exc).__name__}: {exc}"
            )
            return {
                "available": False,
                "source": "discogs",
                "reason": "lookup_failed",
                "suggested_updates": self._suggest_from_local(file_path, metadata),
                "diagnostics": diagnostics,
                "candidates": [],
            }
        self._debug(
            "Discogs response | "
            f"file={Path(file_path).name} | http_status={response_status} | results={len(payload.get('results', []))}"
        )
        self._debug_payload("Discogs response", payload, limit=900)

        candidates: list[Dict[str, Any]] = []
        for item in payload.get("results", []):
            title_text = str(item.get("title") or "")
            guessed_artist, guessed_title = self._split_discogs_title(title_text)
            album_title = self._normalize_discogs_album_title(
                item,
                fallback=guessed_title or title_text,
            )
            artist_name = guessed_artist or artist or local_artist
            year_value = self._normalize_discogs_year(item.get("year"))
            genre_value = self._normalize_discogs_genre(item)
            candidate = {
                "title": local_title,
                "artist": artist_name,
                "album": album_title,
                "year": year_value,
                "genre": genre_value,
                "mbid": str(item.get("id") or ""),
                "release_id": str(item.get("id") or ""),
                "cover_url": str(item.get("cover_image") or item.get("thumb") or ""),
                "thumb_url": str(item.get("thumb") or item.get("cover_image") or ""),
                "confidence": max(
                    0,
                    self._score_candidate(
                        {**metadata, "file_path": str(file_path)},
                        local_title,
                        artist_name,
                        album_title,
                        self._extract_duration(metadata),
                        52,
                    )
                    - self._discogs_candidate_penalty(item, album_title),
                ),
                "source": "discogs",
                "suggested_updates": {
                    "title": local_title,
                    "artist": artist_name,
                    "album": album_title,
                    "year": year_value,
                    "genre": genre_value,
                },
            }
            candidates.append(candidate)

        candidates = self._filter_irrelevant_candidates(
            candidates, {**metadata, "file_path": str(file_path)}
        )
        diagnostics["discogs_reason"] = "ok" if candidates else "no_candidates"
        ranked_candidates = sorted(
            candidates, key=lambda item: item.get("confidence", 0), reverse=True
        )
        ranked_candidates = self._dedupe_candidates(ranked_candidates)[:10]
        self._debug(
            "Discogs parsed candidates | "
            f"file={Path(file_path).name} | kept={len(ranked_candidates)} | "
            f"top={self._summarize_candidates(ranked_candidates)}"
        )
        return {
            "available": bool(ranked_candidates),
            "source": "discogs",
            "reason": "ok" if ranked_candidates else "no_candidates",
            "suggested_updates": ranked_candidates[0].get("suggested_updates", {})
            if ranked_candidates
            else self._suggest_from_local(file_path, metadata),
            "candidates": ranked_candidates,
            "diagnostics": diagnostics,
        }

    def _split_discogs_title(self, title_text: str) -> tuple[str, str]:
        value = str(title_text or "").strip()
        if " - " in value:
            artist, title = value.split(" - ", 1)
            return artist.strip(), title.strip()
        return "", value

    def _normalize_discogs_album_title(
        self, item: Dict[str, Any], fallback: str = ""
    ) -> str:
        raw_title = str(item.get("title") or fallback or "").strip()
        _, release_title = self._split_discogs_title(raw_title)
        album = release_title or raw_title or str(fallback or "").strip()
        album = re.sub(
            r"\s*\((?:\d{4}|\d+|CD\d+|File|Compilation|Album|Single|EP)\)\s*$",
            "",
            album,
            flags=re.IGNORECASE,
        )
        album = re.sub(r"\s{2,}", " ", album).strip(" -_")
        return album

    def _normalize_discogs_year(self, value: Any) -> str:
        text = str(value or "").strip()
        match = re.search(r"(19|20)\d{2}", text)
        return match.group(0) if match else ""

    def _normalize_discogs_genre(self, item: Dict[str, Any]) -> str:
        for key in ("style", "genre"):
            values = item.get(key) or []
            if isinstance(values, list) and values:
                return str(values[0] or "").strip()
            if isinstance(values, str) and values.strip():
                return values.strip()
        return ""

    def _discogs_candidate_penalty(self, item: Dict[str, Any], album_title: str) -> int:
        penalty = 0
        formats = item.get("format") or []
        format_values = (
            [str(value or "").lower() for value in formats]
            if isinstance(formats, list)
            else [str(formats or "").lower()]
        )
        if any(
            token in value
            for value in format_values
            for token in ("comp", "sampler", "promo", "bootleg", "unofficial")
        ):
            penalty += 12
        if any(token in str(item.get("type") or "").lower() for token in ("master",)):
            penalty += 4
        label_text = " ".join(
            str(value or "").lower() for value in (item.get("label") or [])
        )
        if any(token in label_text for token in ("various", "unknown", "promo")):
            penalty += 6
        country = str(item.get("country") or "").strip().lower()
        if country in {"unknown", "none"}:
            penalty += 4
        normalized_album = self.clean_text_for_query(album_title).lower()
        if any(
            token in normalized_album
            for token in (
                "greatest hits",
                "best of",
                "live",
                "collection",
                "anthology",
                "soundtrack",
            )
        ):
            penalty += 10
        if not album_title:
            penalty += 12
        return penalty

    def _get_discogs_token(self) -> str:
        try:
            from src.utils.app_config import get_app_config

            token = get_app_config().get_discogs_token().strip()
            if token:
                return token
        except Exception:
            pass
        return os.environ.get("DISCOGS_TOKEN", "").strip()

    def _get_discogs_enabled(self) -> bool:
        try:
            from src.utils.app_config import get_app_config

            return bool(get_app_config().get_discogs_enabled())
        except Exception:
            return False
