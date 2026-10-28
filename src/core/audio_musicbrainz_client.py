#!/usr/bin/env python3
"""Cliente de MusicBrainz y Cover Art Archive.

Mixin de ``AudioFingerprintService`` (ver ``audio_fingerprint``)."""

from __future__ import annotations

import os
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict


class MusicBrainzClientMixin:
    """Cliente de MusicBrainz y Cover Art Archive."""

    def lookup_musicbrainz_candidates(
        self, file_path: Path, metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        metadata = dict(metadata or {})
        metadata.setdefault("file_path", str(file_path))
        queries = self._build_query_strategies(file_path, metadata)
        self._debug(
            "MusicBrainz strategies | "
            f"file={Path(file_path).name} | queries={self._preview_value(queries, 700)}"
        )
        last_query = ""
        seen: dict[str, Dict[str, Any]] = {}

        for query in queries:
            if not query:
                continue
            last_query = query
            for candidate in self._query_musicbrainz_api(query, metadata):
                key = candidate.get("mbid") or self._candidate_key(candidate)
                previous = seen.get(key)
                if not previous or candidate.get("confidence", 0) > previous.get(
                    "confidence", 0
                ):
                    candidate["query"] = query
                    seen[key] = candidate

        if not seen:
            for candidate in self._query_musicbrainz_release_group(file_path, metadata):
                key = candidate.get("mbid") or self._candidate_key(candidate)
                previous = seen.get(key)
                if not previous or candidate.get("confidence", 0) > previous.get(
                    "confidence", 0
                ):
                    seen[key] = candidate

        candidates = list(seen.values())

        candidates = sorted(
            candidates, key=lambda item: item.get("confidence", 0), reverse=True
        )
        candidates = self._dedupe_candidates(candidates)
        suggested = (
            candidates[0].get("suggested_updates", {})
            if candidates
            else self._suggest_from_local(file_path, metadata)
        )
        self._debug(
            "MusicBrainz aggregated candidates | "
            f"file={Path(file_path).name} | total={len(candidates)} | "
            f"top={self._summarize_candidates(candidates)}"
        )

        return {
            "available": True,
            "source": "musicbrainz",
            "reason": "ok" if candidates else "no_candidates",
            "query": last_query,
            "suggested_updates": suggested,
            "candidates": candidates,
        }

    def _query_musicbrainz_api(
        self, query: str, metadata: Dict[str, Any]
    ) -> list[Dict[str, Any]]:
        params = urllib.parse.urlencode({"query": query, "fmt": "json", "limit": 10})
        url = f"https://musicbrainz.org/ws/2/recording/?{params}"
        self._debug(f"MusicBrainz request | query={self._preview_value(query, 180)}")
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": f"{self._resolve_useragent()} (https://musicbrainz.org)",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response_status = (
                    getattr(response, "status", None) or response.getcode()
                )
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            self._debug(
                "MusicBrainz HTTP error | "
                f"query={self._preview_value(query, 180)} | status={exc.code} | reason={exc.reason}"
            )
            if body:
                self._debug(
                    f"MusicBrainz error body | query={self._preview_value(query, 120)} | {self._preview_value(body, 500)}"
                )
            return []
        except Exception as exc:
            self._debug(
                f"MusicBrainz lookup failed | query={self._preview_value(query, 180)} | error={type(exc).__name__}: {exc}"
            )
            return []
        self._debug(
            "MusicBrainz response | "
            f"query={self._preview_value(query, 180)} | http_status={response_status} | "
            f"recordings={len(payload.get('recordings', []))}"
        )
        candidates: list[Dict[str, Any]] = []
        for rec in payload.get("recordings", []):
            candidates.append(self._build_candidate_from_recording(rec, metadata))
        candidates = self._filter_irrelevant_candidates(candidates, metadata)
        candidates = self._dedupe_candidates(candidates)
        self._debug(
            "MusicBrainz parsed candidates | "
            f"query={self._preview_value(query, 180)} | kept={len(candidates[:10])} | "
            f"top={self._summarize_candidates(candidates)}"
        )
        return candidates[:10]

    def _query_musicbrainz_release_group(
        self, file_path: Path, metadata: Dict[str, Any]
    ) -> list[Dict[str, Any]]:
        title = self._best_value(metadata, ["title"]) or file_path.stem
        artist = self._best_value(metadata, ["artist", "album_artist"])
        query = urllib.parse.urlencode(
            {
                "query": f'title:"{title}"'
                + (f' AND artist:"{artist}"' if artist else ""),
                "fmt": "json",
                "limit": 5,
            }
        )
        url = f"https://musicbrainz.org/ws/2/recording/?{query}"
        self._debug(
            "MusicBrainz release-group request | "
            f"file={file_path.name} | query={self._preview_value(urllib.parse.unquote(query), 180)}"
        )
        try:
            with urllib.request.urlopen(url, timeout=8) as response:
                response_status = (
                    getattr(response, "status", None) or response.getcode()
                )
                data = json.loads(response.read().decode("utf-8", errors="ignore"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            self._debug(
                "MusicBrainz release-group HTTP error | "
                f"file={file_path.name} | status={exc.code} | reason={exc.reason}"
            )
            if body:
                self._debug(
                    f"MusicBrainz release-group error body | file={file_path.name} | {self._preview_value(body, 500)}"
                )
            return []
        except Exception as exc:
            self._debug(
                f"MusicBrainz release-group failed | file={file_path.name} | error={type(exc).__name__}: {exc}"
            )
            return []
        self._debug(
            "MusicBrainz release-group response | "
            f"file={file_path.name} | http_status={response_status} | recordings={len(data.get('recordings', []))}"
        )
        candidates: list[Dict[str, Any]] = []
        for rec in data.get("recordings", []):
            artist_name = ""
            if rec.get("artist-credit"):
                artist_name = " ".join(
                    part.get("name", "")
                    for part in rec["artist-credit"]
                    if isinstance(part, dict)
                )
            candidates.append(
                self._build_candidate_from_recording(
                    {
                        "id": rec.get("id", ""),
                        "title": rec.get("title", ""),
                        "artist-credit": rec.get("artist-credit", []),
                        "release-list": rec.get("releases", []),
                    },
                    metadata,
                )
            )
        filtered = self._filter_irrelevant_candidates(candidates, metadata)
        self._debug(
            "MusicBrainz release-group parsed candidates | "
            f"file={file_path.name} | kept={len(filtered)} | top={self._summarize_candidates(filtered)}"
        )
        return filtered

    def _build_candidate_from_recording(
        self, rec: Dict[str, Any], local: Dict[str, Any]
    ) -> Dict[str, Any]:
        title = rec.get("title", "")
        artist = ""
        if rec.get("artist-credit"):
            artist = " ".join(
                part.get("name", "")
                for part in rec["artist-credit"]
                if isinstance(part, dict)
            )
        releases = rec.get("release-list") or rec.get("releases") or []
        release = releases[0] if releases else {}
        album = release.get("title", "")
        year = (
            release.get("date", "")[:4]
            if release.get("date")
            else str(rec.get("first-release-date") or "")[:4]
        )
        duration = self._extract_recording_duration(rec) or self._extract_duration(
            local
        )
        search_score = self._extract_search_score(rec)
        release_mbid = str(release.get("id") or "")
        cover_url = self._build_musicbrainz_cover_url(release_mbid)
        confidence = self._score_candidate(
            local, title, artist, album, duration, search_score
        )
        suggested = {
            "title": title or local.get("title") or "",
            "artist": artist or local.get("artist") or local.get("album_artist") or "",
            "album": album or local.get("album") or "",
        }
        if year:
            suggested["year"] = year
        return {
            "title": title,
            "artist": artist,
            "album": album,
            "year": year,
            "mbid": rec.get("id", ""),
            "release_mbid": release_mbid,
            "confidence": confidence,
            "search_score": search_score,
            "duration": duration,
            "source": "musicbrainz",
            "cover_url": cover_url,
            "thumb_url": cover_url,
            "suggested_updates": suggested,
        }

    def _build_musicbrainz_cover_url(self, release_mbid: str) -> str:
        release_id = str(release_mbid or "").strip()
        if not release_id:
            return ""
        return f"https://coverartarchive.org/release/{release_id}/front-250"

    def _extract_recording_duration(self, rec: Dict[str, Any]) -> float | None:
        value = rec.get("length") or rec.get("duration")
        if value is None:
            return None
        try:
            numeric = float(value)
        except Exception:
            return None
        if numeric > 1000:
            return numeric / 1000.0
        return numeric

    def _extract_search_score(self, rec: Dict[str, Any]) -> int:
        value = rec.get("score")
        if value is None:
            return 0
        try:
            return int(float(value))
        except Exception:
            return 0

    def _build_query_strategies(
        self, file_path: Path, metadata: Dict[str, Any]
    ) -> list[str]:
        file_artist, file_title = self._split_filename_guess(file_path)
        raw_stem = self.clean_text_for_query(file_path.stem)
        title = self._sanitize_query_text(
            self._best_value(metadata, ["title", "track_name"])
            or file_title
            or raw_stem
        )
        artist = self._sanitize_query_text(
            self._best_value(metadata, ["artist", "album_artist"]) or file_artist
        )
        album = self._sanitize_query_text(self._best_value(metadata, ["album"]))

        queries: list[str] = []
        if title and artist:
            queries.append(f'recording:"{title}" AND artist:"{artist}"')
            queries.append(f'artist:"{artist}" AND recording:"{title}"')
        if raw_stem:
            queries.append(f'recording:"{raw_stem}"')
            queries.append(f'"{raw_stem}"')
        if title:
            queries.append(f'recording:"{title}"')
        if title and album:
            queries.append(f'recording:"{title}" AND release:"{album}"')
        if raw_stem and artist:
            queries.append(f'"{raw_stem}" AND artist:"{artist}"')
        if file_artist and file_title:
            queries.append(f'artist:"{file_artist}" AND recording:"{file_title}"')
            queries.append(f'artist:"{file_artist}" AND "{file_title}"')

        unique_queries: list[str] = []
        for query in queries:
            candidate = query.strip()
            if candidate and candidate not in unique_queries:
                unique_queries.append(candidate)
        return unique_queries

    def _resolve_useragent(self) -> str:
        return (
            os.environ.get("MUSICBRAINZ_USERAGENT", "").strip()
            or os.environ.get("MUSICBRAINZ_APP_NAME", "").strip()
            or "OrdenasionAlpha/1.0"
        )

    def get_useragent(self) -> str:
        """Retorna el user-agent utilizado para MusicBrainz."""
        return self._resolve_useragent()
