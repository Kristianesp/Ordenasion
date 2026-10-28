#!/usr/bin/env python3
"""Library detail, player and cache helpers for the music tab."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PyQt6.QtCore import QUrl
from PyQt6.QtMultimedia import QMediaDevices
from PyQt6.QtWidgets import QMessageBox

from src.core.audio_index import audio_metadata_service
from src.gui.music_duplicates_presenters import (
    build_library_detail_text,
    lookup_cache_badge,
)


def sync_library_playback_rate(view: Any, persist: bool = False) -> None:
    slider = getattr(view, "library_pitch_slider", None)
    try:
        pitch_percent = int(slider.value()) if slider is not None else 100
    except Exception:
        pitch_percent = 100
    pitch_percent = max(50, min(150, pitch_percent))
    playback_rate = pitch_percent / 100.0

    try:
        if hasattr(view.audio_player, "pitchCompensationAvailability"):
            availability = view.audio_player.pitchCompensationAvailability()
        else:
            availability = None
    except Exception:
        availability = None

    try:
        if hasattr(view.audio_player, "setPitchCompensation"):
            enum_type = getattr(
                type(view.audio_player), "PitchCompensationAvailability", None
            )
            always_on = getattr(enum_type, "AlwaysOn", None)
            if availability != always_on:
                view.audio_player.setPitchCompensation(False)
    except Exception:
        pass

    try:
        if hasattr(view.audio_player, "setPlaybackRate"):
            view.audio_player.setPlaybackRate(playback_rate)
    except Exception:
        pass

    if hasattr(view, "library_pitch_label"):
        view.library_pitch_label.setText(f"{playback_rate:.2f}x")

    if persist:
        try:
            from src.utils.app_config import AppConfig

            AppConfig().set_music_preview_playback_rate(playback_rate)
        except Exception:
            pass


def update_library_detail_panel(view: Any) -> None:
    selected = view._get_selected_tracks()
    if not selected:
        view.library_detail_title.setText("Detalle de pista")
        view.library_cache_badge.clear()
        view.library_cache_badge.setVisible(False)
        view.library_detail_text.setPlainText(
            "Selecciona una pista de la biblioteca para ver detalle local y sugerido."
        )
        view._set_cover_preview(view.library_cover_label, None)
        view.library_player_hint.setText("Selecciona una pista para escucharla aqui.")
        view._set_library_expected_duration(0)
        view.library_refresh_cache_btn.setEnabled(False)
        view.library_clear_cache_btn.setEnabled(False)
        view.library_cover_choice_btn.setEnabled(False)
        view.library_diagnostics_btn.setEnabled(False)
        return

    track = selected[0]
    file_path = Path(str(track.get("file_path") or ""))
    current = audio_metadata_service.get_metadata(file_path) or track
    lookup = view._get_lookup_result(file_path, current)
    state_label = view._track_state_label(current, lookup)

    view.library_detail_title.setText(file_path.name)
    badge_text, badge_style = lookup_cache_badge(lookup)
    view.library_cache_badge.setVisible(bool(badge_text))
    view.library_cache_badge.setText(badge_text)
    view.library_cache_badge.setStyleSheet(badge_style)

    selected_variant_index = view._lookup_selected_candidate_index(lookup)
    view.library_detail_text.setPlainText(
        build_library_detail_text(
            file_path,
            current,
            lookup,
            state_label=state_label,
            quality_text=view._format_quality(current),
            lookup_reason_text=view._format_lookup_reason(
                lookup.get(
                    "reason",
                    dict(lookup.get("diagnostics") or {}).get("acoustid_reason", ""),
                )
            ),
            is_applied=view._lookup_result_is_applied(lookup),
            selected_variant_index=selected_variant_index,
        )
    )
    current_source = str(view.audio_player.source().toLocalFile() or "")
    if current_source == str(file_path):
        context_text = (
            "Reproduciendo esta pista."
            if view._audio_context == "library"
            else "Pista cargada en el reproductor."
        )
    else:
        context_text = f"Lista para reproducir: {file_path.name}"
    view.library_player_hint.setText(context_text)
    view.library_refresh_cache_btn.setEnabled(True)
    view.library_clear_cache_btn.setEnabled(bool(lookup))
    view.library_cover_choice_btn.setEnabled(len(lookup.get("cover_choices") or []) > 1)
    view.library_diagnostics_btn.setEnabled(bool(lookup))
    expected_duration = view._selected_library_duration_ms()
    if not (current_source == str(file_path) and view._audio_context == "library"):
        view._set_library_expected_duration(
            expected_duration,
            enable_seek=expected_duration > 0,
        )
    elif expected_duration > 0 and not view.library_seek_slider.isEnabled():
        view.library_seek_slider.setRange(
            0, max(0, int(view._audio_duration_ms or expected_duration))
        )
        view.library_seek_slider.setEnabled(True)

    local_cover = audio_metadata_service.get_cover_art_bytes(file_path)
    if local_cover:
        view._set_cover_preview_from_bytes(view.library_cover_label, local_cover)
        return
    online_cover = view._fetch_cover_preview_bytes(file_path, lookup)
    if online_cover:
        view._set_cover_preview_from_bytes(view.library_cover_label, online_cover)
        return
    view._set_cover_preview(view.library_cover_label, None)


def selected_library_file_path(view: Any) -> Path | None:
    tracks = view._get_selected_tracks()
    if not tracks:
        return None
    file_path = Path(str(tracks[0].get("file_path") or ""))
    return file_path if file_path.exists() else None


def selected_library_track(view: Any) -> Dict[str, Any] | None:
    tracks = view._get_selected_tracks()
    return tracks[0] if tracks else None


def selected_library_duration_ms(view: Any) -> int:
    track = selected_library_track(view) or {}
    duration = track.get("duration")
    try:
        return max(0, int(round(float(duration or 0) * 1000)))
    except Exception:
        return 0


def sync_library_audio_output(view: Any, ensure_default_device: bool = False) -> None:
    slider = getattr(view, "library_volume_slider", None)
    try:
        normalized = int(slider.value()) if slider is not None else 75
    except Exception:
        normalized = 75
    normalized = max(0, min(100, normalized))

    try:
        current_output = getattr(view.audio_player, "audioOutput", lambda: None)()
    except Exception:
        current_output = None
    if current_output is not view.audio_output:
        try:
            view.audio_player.setAudioOutput(view.audio_output)
        except Exception:
            pass

    if ensure_default_device:
        try:
            default_device = QMediaDevices.defaultAudioOutput()
            if hasattr(view.audio_output, "setDevice") and default_device is not None:
                view.audio_output.setDevice(default_device)
        except Exception:
            pass

    try:
        if hasattr(view.audio_output, "setMuted"):
            view.audio_output.setMuted(False)
    except Exception:
        pass

    try:
        view.audio_output.setVolume(normalized / 100)
    except Exception:
        pass

    if hasattr(view, "library_volume_label"):
        view.library_volume_label.setText(f"{normalized}%")


def set_library_expected_duration(
    view: Any, duration_ms: int, enable_seek: bool = False
) -> None:
    view._audio_duration_ms = max(0, int(duration_ms))
    view.library_seek_slider.setValue(0)
    allow_seek = bool(enable_seek and view._audio_duration_ms > 0)
    view.library_seek_slider.setRange(0, view._audio_duration_ms if allow_seek else 0)
    view.library_seek_slider.setEnabled(allow_seek)
    update_library_player_time_label(view)


def format_player_time(milliseconds: int) -> str:
    total_seconds = max(0, int(milliseconds // 1000))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def on_library_volume_changed(view: Any, value: int) -> None:
    del value
    sync_library_audio_output(view)


def on_library_pitch_changed(view: Any, value: int) -> None:
    del value
    sync_library_playback_rate(view, persist=True)


def update_library_player_time_label(view: Any) -> None:
    position = (
        int(view.audio_player.position()) if view._audio_context == "library" else 0
    )
    duration = int(view._audio_duration_ms)
    view.library_time_label.setText(
        f"{format_player_time(position)} / {format_player_time(duration)}"
    )


def on_audio_position_changed(view: Any, position: int) -> None:
    if view._audio_context != "library":
        return
    if not view.library_seek_slider.isSliderDown():
        view.library_seek_slider.setValue(int(position))
    update_library_player_time_label(view)


def on_audio_duration_changed(view: Any, duration: int) -> None:
    if view._audio_context != "library":
        return
    view._audio_duration_ms = int(duration)
    view.library_seek_slider.setEnabled(duration > 0)
    view.library_seek_slider.setRange(0, max(0, int(duration)))
    update_library_player_time_label(view)


def on_audio_playback_state_changed(view: Any, state: Any) -> None:
    playback_state = getattr(type(view.audio_player), "PlaybackState", None)
    playing_state = getattr(playback_state, "PlayingState", None)
    stopped_state = getattr(playback_state, "StoppedState", None)
    if view._audio_context == "library":
        is_playing = state == playing_state
        view.library_play_btn.setText("Pausar" if is_playing else "Reproducir")
        current_file = view.audio_player.source().toLocalFile()
        if current_file:
            name = Path(current_file).name
            if state == stopped_state:
                expected_duration = selected_library_duration_ms(view)
                set_library_expected_duration(
                    view,
                    expected_duration,
                    enable_seek=expected_duration > 0,
                )
                view.library_player_hint.setText(f"Lista para reproducir: {name}")
            else:
                view.library_player_hint.setText(
                    f"{'Reproduciendo' if is_playing else 'Pausada'}: {name}"
                )
        else:
            view.library_player_hint.setText(
                "Selecciona una pista para escucharla aqui."
            )
    elif view._audio_context != "library":
        view.library_play_btn.setText("Reproducir")


def load_audio_source(view: Any, file_path: Path, context: str) -> None:
    if str(view.audio_player.source().toLocalFile() or "") != str(file_path):
        view.audio_player.setSource(QUrl.fromLocalFile(str(file_path)))
    view._audio_context = context
    if context == "library":
        expected_duration = selected_library_duration_ms(view)
        set_library_expected_duration(
            view,
            expected_duration,
            enable_seek=expected_duration > 0,
        )
    else:
        view.library_play_btn.setText("Reproducir")
        view.library_seek_slider.setEnabled(False)
        view.library_seek_slider.setRange(0, 0)
        view.library_seek_slider.setValue(0)
        view.library_time_label.setText("0:00 / 0:00")


def play_selected_library_track(view: Any) -> None:
    file_path = selected_library_file_path(view)
    if not file_path:
        QMessageBox.information(
            view,
            "Metadatos",
            "Selecciona una pista valida de la biblioteca para reproducir",
        )
        return
    current_source = str(view.audio_player.source().toLocalFile() or "")
    playing_state = getattr(type(view.audio_player).PlaybackState, "PlayingState", None)
    if (
        view._audio_context == "library"
        and current_source == str(file_path)
        and view.audio_player.playbackState() == playing_state
    ):
        view.audio_player.pause()
        view.status_update.emit(f"⏸ Pausada: {file_path.name}")
        return
    sync_library_audio_output(view, ensure_default_device=True)
    sync_library_playback_rate(view)
    load_audio_source(view, file_path, "library")
    view.audio_player.play()
    view.status_update.emit(f"▶ Reproduciendo: {file_path.name}")


def stop_library_preview(view: Any) -> None:
    if view._audio_context == "library":
        view.audio_player.stop()
        expected_duration = selected_library_duration_ms(view)
        set_library_expected_duration(
            view,
            expected_duration,
            enable_seek=expected_duration > 0,
        )
        file_path = selected_library_file_path(view)
        view.library_player_hint.setText(
            f"Lista para reproducir: {file_path.name}"
            if file_path is not None
            else "Selecciona una pista para escucharla aqui."
        )
        view.status_update.emit("⏹ Reproduccion detenida")


def seek_library_preview(view: Any, position: int) -> None:
    if view._audio_context == "library":
        view.audio_player.setPosition(int(position))


def force_refresh_selected_track_cache(view: Any) -> None:
    track = selected_library_track(view)
    if not track:
        QMessageBox.information(
            view,
            "Metadatos",
            "Selecciona una pista de la biblioteca primero",
        )
        return
    file_path = str(Path(track.get("file_path") or ""))
    if not file_path:
        return
    view._lookup_results_by_path.pop(file_path, None)
    view._start_lookup_for_tracks(
        [track],
        [file_path],
        force_refresh=True,
        start_message=f"🌐 Forzando refresh online para: {Path(file_path).name}",
    )


def clear_selected_track_cache(view: Any) -> None:
    track = selected_library_track(view)
    if not track:
        QMessageBox.information(
            view,
            "Metadatos",
            "Selecciona una pista de la biblioteca primero",
        )
        return
    file_path = Path(str(track.get("file_path") or ""))
    if not file_path:
        return
    view._lookup_results_by_path.pop(str(file_path), None)
    if audio_metadata_service.clear_lookup_cache(file_path):
        view.lookup_status_label.setText(f"🧹 Cache online limpiada: {file_path.name}")
        view.status_update.emit(f"🧹 Cache online limpiada: {file_path.name}")
        view.refresh_library()
        view._restore_selected_file_paths([str(file_path)], str(file_path))
        view._update_library_detail_panel()
