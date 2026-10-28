#!/usr/bin/env python3
"""Lookup cache and candidate state helpers for the music tab."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from src.core.audio_fingerprint import audio_fingerprint_service
from src.core.audio_index import audio_metadata_service


def get_lookup_result(
    view: Any,
    file_path: str | Path,
    track: Dict[str, Any] | None = None,
    load_cached: bool = True,
) -> Dict[str, Any]:
    normalized_path = str(Path(file_path))
    cached_result = view._lookup_results_by_path.get(normalized_path)
    if cached_result is not None or not load_cached:
        return cached_result or {}

    track_payload = dict(track or {})
    cache_key = ""
    if track_payload:
        cache_key = audio_fingerprint_service.build_lookup_cache_key(
            Path(normalized_path), track_payload
        )
    result = audio_metadata_service.get_lookup_cache(
        Path(normalized_path),
        cache_key or None,
    )
    if not result:
        return {}
    result.setdefault("file_path", normalized_path)
    result.setdefault("local_metadata", track_payload or {"file_path": normalized_path})
    result.setdefault("candidate_count", len(result.get("candidates") or []))
    result.setdefault("cache_status", "cached")
    view._lookup_results_by_path[normalized_path] = result
    return result


def store_lookup_result(
    view: Any,
    file_path: str | Path,
    result: Dict[str, Any],
    persist: bool = True,
) -> Dict[str, Any]:
    normalized_path = str(Path(file_path))
    previous_result = view._lookup_results_by_path.get(normalized_path, {})
    updated_result = dict(result or {})
    updated_result["file_path"] = normalized_path
    updated_result.setdefault(
        "local_metadata",
        dict(updated_result.get("local_metadata") or {"file_path": normalized_path}),
    )
    updated_result.setdefault(
        "cache_status",
        str(previous_result.get("cache_status") or "cached")
        if previous_result
        else "cached",
    )
    if lookup_selected_candidate_index(view, updated_result) is None:
        previous_selected_updates = candidate_updates_for_index(
            previous_result,
            lookup_selected_candidate_index(view, previous_result),
        ) or dict(previous_result.get("suggested_updates") or {})
        restored_selected_index = find_candidate_index_for_updates(
            view,
            updated_result,
            previous_selected_updates,
        )
        if restored_selected_index is not None:
            updated_result = update_lookup_result_for_candidate(
                updated_result,
                restored_selected_index,
            )
    if lookup_applied_candidate_index(view, updated_result) is None:
        previous_applied_updates = candidate_updates_for_index(
            previous_result,
            lookup_applied_candidate_index(view, previous_result),
        )
        restored_applied_index = find_candidate_index_for_updates(
            view,
            updated_result,
            previous_applied_updates,
        )
        if restored_applied_index is not None:
            updated_result["applied_candidate_index"] = restored_applied_index
            if previous_result.get("applied_at"):
                updated_result["applied_at"] = previous_result.get("applied_at")
    updated_result = restore_selected_cover_choice(previous_result, updated_result)
    updated_result["candidate_count"] = len(updated_result.get("candidates") or [])
    view._lookup_results_by_path[normalized_path] = updated_result
    cache_key = str(updated_result.get("cache_key") or "").strip()
    if persist and cache_key:
        audio_metadata_service.set_lookup_cache(
            Path(normalized_path),
            cache_key,
            updated_result,
            cover_art=updated_result.get("cached_cover_art"),
        )
    return updated_result


def fetch_cover_preview_bytes(
    view: Any, file_path: str | Path, result: Dict[str, Any]
) -> bytes | None:
    normalized_path = str(Path(file_path))
    active_result = dict(result or {})
    if not active_result:
        return None
    cover_bytes = audio_fingerprint_service.get_cover_art_bytes_for_result(
        Path(normalized_path),
        active_result,
    )
    if cover_bytes and active_result.get("cached_cover_art") != cover_bytes:
        active_result["cached_cover_art"] = cover_bytes
        store_lookup_result(view, normalized_path, active_result, persist=True)
    return cover_bytes


def clear_no_match_status(view: Any, file_path: str | Path) -> None:
    del view
    target = Path(file_path)
    if audio_metadata_service.get_track_review_status(target) == "no_match":
        audio_metadata_service.set_track_review_status(target, "")


def set_track_no_match(view: Any, file_path: str | Path) -> bool:
    del view
    target = Path(file_path)
    return audio_metadata_service.set_track_review_status(target, "no_match")


def set_track_applied(view: Any, file_path: str | Path) -> bool:
    del view
    target = Path(file_path)
    current = audio_metadata_service.get_track_review_status(target)
    if current == "complete":
        return True
    return audio_metadata_service.set_track_review_status(target, "applied")


def clear_applied_status(view: Any, file_path: str | Path) -> None:
    del view
    target = Path(file_path)
    if audio_metadata_service.get_track_review_status(target) == "applied":
        audio_metadata_service.set_track_review_status(target, "")


def lookup_selected_candidate_index(
    view: Any, result: Dict[str, Any] | None
) -> int | None:
    del view
    value = (result or {}).get("selected_candidate_index")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def lookup_applied_candidate_index(
    view: Any, result: Dict[str, Any] | None
) -> int | None:
    del view
    value = (result or {}).get("applied_candidate_index")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except Exception:
        return None


def lookup_result_is_applied(view: Any, result: Dict[str, Any] | None) -> bool:
    selected_index = lookup_selected_candidate_index(view, result)
    applied_index = lookup_applied_candidate_index(view, result)
    return (
        selected_index is not None
        and applied_index is not None
        and selected_index == applied_index
        and bool((result or {}).get("suggested_updates"))
    )


def update_lookup_result_for_candidate(
    result: Dict[str, Any], chosen_index: int
) -> Dict[str, Any]:
    updated_result = dict(result or {})
    candidates = list(updated_result.get("candidates") or [])
    if not (0 <= chosen_index < len(candidates)):
        return updated_result
    chosen = candidates[chosen_index]
    updated_result["selected_candidate_index"] = chosen_index
    updated_result["suggested_updates"] = dict(chosen.get("suggested_updates", {}))
    updated_result["confidence"] = chosen.get("confidence", 0)
    updated_result["source"] = chosen.get("source", result.get("source", "unknown"))
    updated_result["cover_url"] = chosen.get("cover_url", result.get("cover_url", ""))
    updated_result["thumb_url"] = chosen.get("thumb_url", result.get("thumb_url", ""))
    return updated_result


def sync_lookup_result_after_write(
    view: Any,
    file_path: str | Path,
    applied: bool,
    chosen_index: int | None = None,
) -> Dict[str, Any] | None:
    normalized_path = str(Path(file_path))
    result = get_lookup_result(view, normalized_path)
    if not result:
        if applied:
            set_track_applied(view, normalized_path)
        else:
            clear_applied_status(view, normalized_path)
        return None
    updated_result = dict(result)
    resolved_index = chosen_index
    if resolved_index is None:
        resolved_index = lookup_selected_candidate_index(view, updated_result)
    if applied and resolved_index is None and (updated_result.get("candidates") or []):
        resolved_index = 0
    if applied and resolved_index is not None:
        updated_result = update_lookup_result_for_candidate(
            updated_result, resolved_index
        )
        updated_result["applied_candidate_index"] = resolved_index
        updated_result["applied_at"] = datetime.now().isoformat(timespec="seconds")
        set_track_applied(view, normalized_path)
    else:
        updated_result.pop("applied_candidate_index", None)
        updated_result.pop("applied_at", None)
        clear_applied_status(view, normalized_path)
    current_metadata = audio_metadata_service.get_metadata(Path(normalized_path)) or {}
    local_metadata = dict(updated_result.get("local_metadata") or {})
    local_metadata.update(current_metadata)
    local_metadata["file_path"] = normalized_path
    updated_result["local_metadata"] = local_metadata
    updated_result["cache_key"] = audio_fingerprint_service.build_lookup_cache_key(
        Path(normalized_path), local_metadata
    )
    return store_lookup_result(view, normalized_path, updated_result, persist=True)


def selected_variant_matches_updates(
    view: Any, result: Dict[str, Any], updates: Dict[str, Any]
) -> bool:
    selected_index = lookup_selected_candidate_index(view, result)
    candidates = list((result or {}).get("candidates") or [])
    if selected_index is None or not (0 <= selected_index < len(candidates)):
        return False
    suggested = dict(candidates[selected_index].get("suggested_updates") or {})
    if not suggested:
        return False
    matched_any = False
    for key in ("title", "artist", "album", "year", "genre"):
        suggested_value = str(suggested.get(key) or "").strip()
        if not suggested_value:
            continue
        matched_any = True
        update_value = str(updates.get(key) or "").strip()
        if key == "title":
            suggested_value = audio_metadata_service.clean_track_title(suggested_value)
            update_value = audio_metadata_service.clean_track_title(update_value)
        if update_value != suggested_value:
            return False
    return matched_any


def candidate_updates_for_index(
    result: Dict[str, Any] | None, index: int | None
) -> Dict[str, Any]:
    candidates = list((result or {}).get("candidates") or [])
    if index is None or not (0 <= index < len(candidates)):
        return {}
    return dict(candidates[index].get("suggested_updates") or {})


def normalize_lookup_value(key: str, value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if key == "title":
        normalized = audio_metadata_service.clean_track_title(normalized)
    return normalized


def lookup_cover_urls(result: Dict[str, Any] | None) -> set[str]:
    urls: set[str] = set()

    def add_url(value: Any) -> None:
        candidate = str(value or "").strip()
        if candidate:
            urls.add(candidate)

    active_result = dict(result or {})
    add_url(active_result.get("selected_cover_url"))
    for choice in active_result.get("cover_choices") or []:
        if isinstance(choice, dict):
            add_url(choice.get("url"))
        else:
            add_url(choice)
    for key in ("cover_url", "thumb_url"):
        add_url(active_result.get(key))
    for candidate in active_result.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        for choice in candidate.get("cover_choices") or []:
            if isinstance(choice, dict):
                add_url(choice.get("url"))
            else:
                add_url(choice)
        for key in ("cover_url", "thumb_url"):
            add_url(candidate.get(key))
    return urls


def restore_selected_cover_choice(
    previous_result: Dict[str, Any] | None, updated_result: Dict[str, Any] | None
) -> Dict[str, Any]:
    restored = dict(updated_result or {})
    previous_selected_cover_url = str(
        (previous_result or {}).get("selected_cover_url")
        or (previous_result or {}).get("cover_url")
        or (previous_result or {}).get("thumb_url")
        or ""
    ).strip()
    selected_cover_url = str(
        restored.get("selected_cover_url")
        or (previous_result or {}).get("selected_cover_url")
        or ""
    ).strip()
    if not selected_cover_url:
        return restored
    if selected_cover_url not in lookup_cover_urls(restored):
        return restored
    restored["selected_cover_url"] = selected_cover_url
    restored["cover_url"] = selected_cover_url
    restored["thumb_url"] = selected_cover_url
    if (
        previous_result
        and previous_result.get("cached_cover_art")
        and not restored.get("cached_cover_art")
        and previous_selected_cover_url == selected_cover_url
    ):
        restored["cached_cover_art"] = previous_result.get("cached_cover_art")
    return restored


def find_candidate_index_for_updates(
    view: Any, result: Dict[str, Any] | None, updates: Dict[str, Any] | None
) -> int | None:
    del view
    expected = {}
    for key in ("title", "artist", "album", "year", "genre"):
        value = normalize_lookup_value(key, (updates or {}).get(key))
        if value:
            expected[key] = value
    if not expected:
        return None
    candidates = list((result or {}).get("candidates") or [])
    for index, candidate in enumerate(candidates):
        suggested = dict(candidate.get("suggested_updates") or {})
        if all(
            normalize_lookup_value(key, suggested.get(key)) == value
            for key, value in expected.items()
        ):
            return index
    return None


def select_variant_in_lookup_cache(
    view: Any, file_path: str, chosen_index: int
) -> Dict[str, Any] | None:
    normalized_path = str(Path(file_path))
    result = get_lookup_result(view, normalized_path)
    if not result:
        return None
    candidates = result.get("candidates") or []
    if not (0 <= chosen_index < len(candidates)):
        return None
    updated_result = update_lookup_result_for_candidate(result, chosen_index)
    updated_result.pop("cached_cover_art", None)
    return store_lookup_result(view, normalized_path, updated_result, persist=True)


def apply_variant_choice(view: Any, file_path: str, chosen_index: int) -> bool:
    normalized_path = str(Path(file_path))
    updated_result = select_variant_in_lookup_cache(view, normalized_path, chosen_index)
    if not updated_result:
        return False
    suggested = updated_result.get("suggested_updates", {})
    if suggested:
        cover_art = fetch_cover_preview_bytes(view, normalized_path, updated_result)
        changed = audio_metadata_service.update_track_tags(
            Path(normalized_path), suggested, cover_art=cover_art
        )
        if changed:
            clear_no_match_status(view, normalized_path)
            sync_lookup_result_after_write(
                view,
                normalized_path,
                applied=True,
                chosen_index=chosen_index,
            )
        return changed
    return False


def invalidate_lookup_cache_if_manual_updates_conflict(
    view: Any, file_path: str | Path, updates: Dict[str, Any]
) -> bool:
    normalized_path = str(Path(file_path))
    result = get_lookup_result(view, normalized_path)
    if not result:
        return False
    if not lookup_result_is_applied(view, result):
        return False
    if selected_variant_matches_updates(view, result, updates):
        return False
    view._lookup_results_by_path.pop(normalized_path, None)
    audio_metadata_service.clear_lookup_cache(Path(normalized_path))
    return True


def auto_selectable_candidate_index(
    view: Any, file_path: str | Path, result: Dict[str, Any] | None = None
) -> int | None:
    normalized_path = str(Path(file_path))
    active_result = dict(result or get_lookup_result(view, normalized_path))
    candidates = list(active_result.get("candidates") or [])
    if not candidates:
        return None
    chosen_index = lookup_selected_candidate_index(view, active_result)
    if chosen_index is None or not (0 <= chosen_index < len(candidates)):
        chosen_index = 0
    local_metadata = dict(active_result.get("local_metadata") or {})
    local_metadata.setdefault("file_path", normalized_path)
    candidate = candidates[chosen_index]
    if not audio_fingerprint_service.should_auto_apply_candidate(
        local_metadata, candidate
    ):
        return None
    return chosen_index


def auto_apply_high_confidence_variant(
    view: Any, file_path: str | Path, result: Dict[str, Any] | None = None
) -> bool:
    normalized_path = str(Path(file_path))
    active_result = dict(result or get_lookup_result(view, normalized_path))
    chosen_index = auto_selectable_candidate_index(view, normalized_path, active_result)
    if chosen_index is None:
        return False
    updated_result = select_variant_in_lookup_cache(view, normalized_path, chosen_index)
    if not updated_result:
        return False

    suggested = dict(updated_result.get("suggested_updates") or {})
    if not suggested:
        return False

    cover_art = fetch_cover_preview_bytes(view, normalized_path, updated_result)
    changed = audio_metadata_service.update_track_tags(
        Path(normalized_path), suggested, cover_art=cover_art
    )
    if changed:
        clear_no_match_status(view, normalized_path)
        sync_lookup_result_after_write(
            view,
            normalized_path,
            applied=True,
            chosen_index=chosen_index,
        )
    else:
        current_metadata = (
            audio_metadata_service.get_metadata(Path(normalized_path)) or {}
        )
        if not selected_variant_matches_updates(view, updated_result, current_metadata):
            return False
        clear_no_match_status(view, normalized_path)
        sync_lookup_result_after_write(
            view,
            normalized_path,
            applied=True,
            chosen_index=chosen_index,
        )

    candidates = list(updated_result.get("candidates") or [])
    chosen_candidate = (
        candidates[chosen_index] if 0 <= chosen_index < len(candidates) else {}
    )
    chosen_updates = dict(chosen_candidate.get("suggested_updates") or suggested)
    message = (
        "🤖 Se ha seleccionado automáticamente: "
        f"{Path(normalized_path).name} -> "
        f"{chosen_updates.get('artist', '-') or '-'} / "
        f"{chosen_updates.get('title', '-') or '-'} / "
        f"{chosen_updates.get('album', '-') or '-'} | "
        f"confianza={chosen_candidate.get('confidence', updated_result.get('confidence', 0))}"
    )
    if hasattr(view, "lookup_status_label") and view.lookup_status_label is not None:
        view.lookup_status_label.setText(message)
    view.status_update.emit(message)
    return True
