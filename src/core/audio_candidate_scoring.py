#!/usr/bin/env python3
"""Puntuación, fusión y filtrado de candidatos de metadatos.

Mixin de ``AudioFingerprintService`` (ver ``audio_fingerprint``)."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict


class CandidateScoringMixin:
    """Puntuación, fusión y filtrado de candidatos de metadatos."""

    AUTO_APPLY_CONFIDENCE_THRESHOLD = 210
    AUTO_APPLY_EXACT_RATIO = 0.985
    AUTO_APPLY_STRONG_TITLE_RATIO = 0.94
    AUTO_APPLY_STRONG_ARTIST_RATIO = 0.90

    def should_auto_apply_result(self, result: Dict[str, Any]) -> bool:
        candidates = list(result.get("candidates") or [])
        if len(candidates) != 1:
            return False
        local_metadata = dict(result.get("local_metadata") or {})
        file_path = str(
            result.get("file_path") or local_metadata.get("file_path") or ""
        )
        if file_path and not local_metadata.get("file_path"):
            local_metadata["file_path"] = file_path
        return self.should_auto_apply_candidate(local_metadata, candidates[0])

    def should_auto_apply_candidate(
        self, local_metadata: Dict[str, Any], candidate: Dict[str, Any]
    ) -> bool:
        suggested = candidate.get("suggested_updates") or {}
        if not suggested:
            return False

        confidence = int(candidate.get("confidence", 0) or 0)
        if confidence < self.AUTO_APPLY_CONFIDENCE_THRESHOLD:
            return False

        match = self._auto_apply_match_context(local_metadata, candidate)
        expected_title = match["expected_title"]
        expected_artist = match["expected_artist"]
        candidate_title = match["candidate_title"]
        title_ratio = match["title_ratio"]
        artist_ratio = match["artist_ratio"]

        if not expected_title or not candidate_title:
            return False

        title_exact = title_ratio >= self.AUTO_APPLY_EXACT_RATIO
        artist_exact = (
            not expected_artist or artist_ratio >= self.AUTO_APPLY_EXACT_RATIO
        )
        if title_exact and artist_exact:
            return True

        if title_ratio < self.AUTO_APPLY_STRONG_TITLE_RATIO:
            return False
        if expected_artist and artist_ratio < self.AUTO_APPLY_STRONG_ARTIST_RATIO:
            return False
        return True

    def _auto_apply_match_context(
        self, local_metadata: Dict[str, Any], candidate: Dict[str, Any]
    ) -> Dict[str, Any]:
        file_path = Path(str(local_metadata.get("file_path") or "track.mp3"))
        file_artist, file_title = self._split_filename_guess(file_path)
        expected_title = self.clean_text_for_query(
            self._best_value(local_metadata, ["title"]) or file_title or file_path.stem
        ).lower()
        expected_artist = self.clean_text_for_query(
            self._best_value(local_metadata, ["artist", "album_artist"]) or file_artist
        ).lower()
        suggested = candidate.get("suggested_updates") or {}
        candidate_title = self.clean_text_for_query(
            str(candidate.get("title") or suggested.get("title") or "")
        ).lower()
        candidate_artist = self.clean_text_for_query(
            str(candidate.get("artist") or suggested.get("artist") or "")
        ).lower()
        return {
            "expected_title": expected_title,
            "expected_artist": expected_artist,
            "candidate_title": candidate_title,
            "candidate_artist": candidate_artist,
            "title_ratio": self._similarity_ratio(expected_title, candidate_title),
            "artist_ratio": self._similarity_ratio(expected_artist, candidate_artist),
        }

    def _similarity_ratio(self, expected: str, candidate: str) -> float:
        left = str(expected or "").strip().lower()
        right = str(candidate or "").strip().lower()
        if not left or not right:
            return 0.0
        if left == right:
            return 1.0
        return SequenceMatcher(None, left, right).ratio()

    def _score_candidate(
        self,
        local: Dict[str, Any],
        title: str,
        artist: str,
        album: str,
        duration: float | None = None,
        search_score: int = 0,
    ) -> int:
        score = max(0, search_score)
        local_title = str(local.get("title") or "").strip().lower()
        local_artist = (
            str(local.get("artist") or local.get("album_artist") or "").strip().lower()
        )
        local_album = str(local.get("album") or "").strip().lower()
        file_artist, file_title = self._split_filename_guess(
            Path(str(local.get("file_path") or "track.mp3"))
        )
        if local_title:
            score += int(SequenceMatcher(None, local_title, title.lower()).ratio() * 50)
        if local_artist:
            score += int(
                SequenceMatcher(None, local_artist, artist.lower()).ratio() * 30
            )
        if local_album:
            score += int(SequenceMatcher(None, local_album, album.lower()).ratio() * 20)
        if file_title:
            score += int(
                SequenceMatcher(
                    None,
                    self.clean_text_for_query(file_title).lower(),
                    self.clean_text_for_query(title).lower(),
                ).ratio()
                * 35
            )
        if file_artist:
            score += int(
                SequenceMatcher(
                    None,
                    self.clean_text_for_query(file_artist).lower(),
                    self.clean_text_for_query(artist).lower(),
                ).ratio()
                * 20
            )
        if duration:
            local_duration = self._extract_duration(local)
            if local_duration:
                delta = abs(local_duration - duration)
                score += max(0, 20 - int(delta * 2))
        file_artist = self._best_value(local, ["artist", "album_artist"])
        file_title = self._best_value(local, ["title"]) or self.clean_text_for_query(
            str(local.get("file_path", ""))
        )
        if file_title:
            score += int(
                SequenceMatcher(
                    None,
                    self.clean_text_for_query(file_title).lower(),
                    self.clean_text_for_query(title).lower(),
                ).ratio()
                * 20
            )
        if file_artist:
            score += int(
                SequenceMatcher(
                    None,
                    self.clean_text_for_query(file_artist).lower(),
                    self.clean_text_for_query(artist).lower(),
                ).ratio()
                * 10
            )
        if score == 0:
            score = 5
        return score

    def _candidate_key(self, candidate: Dict[str, Any]) -> str:
        return "|".join(
            [
                str(candidate.get("title") or ""),
                str(candidate.get("artist") or ""),
                str(candidate.get("album") or ""),
            ]
        )

    def _merge_lookup_candidates(
        self, *candidate_groups: list[Dict[str, Any]]
    ) -> list[Dict[str, Any]]:
        merged: list[Dict[str, Any]] = []
        for group in candidate_groups:
            for candidate in group or []:
                merged.append(dict(candidate))
        merged = self._dedupe_candidates(merged)
        priority = {"acoustid": 0, "musicbrainz": 1, "discogs": 2}
        return sorted(
            merged,
            key=lambda item: (
                priority.get(str(item.get("source") or "").lower(), 99),
                -(int(item.get("confidence") or 0)),
                self.clean_text_for_query(str(item.get("artist") or "")).lower(),
                self.clean_text_for_query(str(item.get("title") or "")).lower(),
            ),
        )

    def _select_lookup_reason(self, reasons: list[str]) -> str:
        ordered = [str(reason or "") for reason in reasons if str(reason or "")]
        for preferred in (
            "invalid_client_key",
            "lookup_failed",
            "fingerprint_unavailable",
            "invalid_fingerprint_payload",
            "missing_api_key",
            "disabled_or_missing_token",
            "no_candidates",
        ):
            if preferred in ordered:
                return preferred
        return ordered[0] if ordered else "lookup_failed"

    def _dedupe_candidates(
        self, candidates: list[Dict[str, Any]]
    ) -> list[Dict[str, Any]]:
        ordered: list[Dict[str, Any]] = []
        seen: dict[str, int] = {}
        for candidate in candidates:
            key = "|".join(
                [
                    self.clean_text_for_query(
                        str(candidate.get("title") or "")
                    ).lower(),
                    self.clean_text_for_query(
                        str(candidate.get("artist") or "")
                    ).lower(),
                    self.clean_text_for_query(
                        str(candidate.get("album") or "")
                    ).lower(),
                    str(candidate.get("year") or "").strip(),
                    str(candidate.get("source") or "").strip().lower(),
                ]
            )
            previous_index = seen.get(key)
            if previous_index is None:
                seen[key] = len(ordered)
                ordered.append(candidate)
                continue
            previous = ordered[previous_index]
            if candidate.get("confidence", 0) > previous.get("confidence", 0):
                ordered[previous_index] = candidate
        return ordered

    def _filter_irrelevant_candidates(
        self, candidates: list[Dict[str, Any]], local: Dict[str, Any]
    ) -> list[Dict[str, Any]]:
        file_artist, file_title = self._split_filename_guess(
            Path(str(local.get("file_path") or "track.mp3"))
        )
        expected_title = self.clean_text_for_query(
            self._best_value(local, ["title"]) or file_title
        ).lower()
        expected_artist = self.clean_text_for_query(
            self._best_value(local, ["artist", "album_artist"]) or file_artist
        ).lower()
        filtered: list[Dict[str, Any]] = []
        for candidate in candidates:
            candidate_title = self.clean_text_for_query(
                str(candidate.get("title") or "")
            ).lower()
            candidate_artist = self.clean_text_for_query(
                str(candidate.get("artist") or "")
            ).lower()
            title_ratio = (
                SequenceMatcher(None, expected_title, candidate_title).ratio()
                if expected_title
                else 0.0
            )
            artist_ratio = (
                SequenceMatcher(None, expected_artist, candidate_artist).ratio()
                if expected_artist
                else 0.0
            )
            if (
                expected_title
                and title_ratio < 0.35
                and expected_artist
                and artist_ratio < 0.35
            ):
                continue
            filtered.append(candidate)
        return filtered or candidates

    def clean_text_for_query(self, value: str) -> str:
        value = re.sub(r"(?i)\.(mp3|flac|wav|m4a|aac|ogg|wma)$", "", value)
        value = re.sub(r"(?i)https?://\S+|www\.\S+", " ", value)
        value = re.sub(
            r"(?i)[\[(]?(?:www|http|https|com|net|org|es|info|blog|download)[^\])]*[\])]?,?",
            " ",
            value,
        )
        value = re.sub(r"(?i)^\s*0\d{1,2}[\s._-]+", "", value)
        value = re.sub(r"(?i)^\s*\d{1,3}[._-]+\s*", "", value)
        value = re.sub(r"(?i)[\s._-]+\d{1,3}\s*$", "", value)
        value = re.sub(r"[_\-]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value

    def _clean_artist_hint(self, value: str) -> str:
        value = str(value or "").strip()
        value = re.sub(r"(?i)https?://\S+|www\.\S+", " ", value)
        value = re.sub(r"\s+", " ", value).strip(" _-.")
        return value

    def _best_value(self, metadata: Dict[str, Any], keys: list[str]) -> str:
        for key in keys:
            value = metadata.get(key)
            if value:
                return str(value).strip()
        return ""

    def _extract_duration(self, metadata: Dict[str, Any]) -> float | None:
        for key in ("duration", "length", "track_length"):
            value = metadata.get(key)
            if value:
                try:
                    return float(value)
                except Exception:
                    continue
        return None

    def _sanitize_query_text(self, value: str) -> str:
        value = str(value or "").strip().replace('"', " ")
        return self.clean_text_for_query(value)

    def _split_filename_guess(self, file_path: Path) -> tuple[str, str]:
        raw_stem = str(file_path.stem or "").strip()
        if " - " in raw_stem:
            left, right = raw_stem.split(" - ", 1)
            return self._clean_artist_hint(left), self.clean_text_for_query(right)
        normalized = raw_stem.replace(" - ", "_")
        if "_" in normalized:
            parts = [p.strip() for p in normalized.split("_") if p.strip()]
            if len(parts) >= 2:
                return self._clean_artist_hint(parts[0]), self.clean_text_for_query(
                    " ".join(parts[1:])
                )
        stem = self.clean_text_for_query(raw_stem)
        return "", stem
