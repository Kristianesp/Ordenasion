#!/usr/bin/env python3
"""Vista dedicada a duplicados musicales."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Any, cast

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
    QByteArray,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    QPoint,
)
from PyQt6.QtGui import QAction, QPixmap
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QFileDialog,
    QListWidget,
    QTextEdit,
    QMessageBox,
    QCheckBox,
    QTabWidget,
    QTableWidgetItem,
    QInputDialog,
    QDialog,
    QDialogButtonBox,
    QMenu,
    QProgressBar,
    QComboBox,
    QSplitter,
    QFrame,
    QGraphicsOpacityEffect,
    QSlider,
    QScrollBar,
)

from src.core.audio_fingerprint import audio_fingerprint_service
from src.core.audio_index import audio_metadata_service
from src.core.transaction_manager import TransactionManager
from src.gui.music_duplicates_constants import (
    DUPLICATES_COLUMN_LABELS,
    LIBRARY_COLUMN_DEFAULT_ORDER,
    LIBRARY_COLUMN_DEFAULTS,
    LIBRARY_COLUMN_LABELS,
    LIBRARY_DEFAULT_VISIBLE_COLUMNS,
    LIBRARY_FILE_COLUMN,
    LIBRARY_SELECT_COLUMN,
    LIBRARY_SPLITTER_DEFAULT_SIZES,
)
from src.gui.music_duplicates_formatters import (
    format_bitrate,
    format_duration,
    format_file_size,
    format_lookup_reason,
    format_quality,
)
from src.gui.music_duplicates_presenters import summarize_lookup_candidates
from src.gui.music_duplicates_duplicate_logic import (
    refresh_results as refresh_duplicate_results,
)
from src.gui.music_duplicates_duplicate_logic import (
    mark_selected_duplicate_as_keep,
    selected_duplicate_paths,
    select_best_duplicate,
    show_duplicates_context_menu,
    show_group_detail,
    update_duplicate_preview,
)
from src.gui.music_duplicates_library_logic import (
    get_selected_file_paths,
    get_selected_tracks,
    refresh_library as refresh_library_rows,
    restore_selected_file_paths,
)
from src.gui.music_duplicates_library_actions import (
    edit_library_columns,
    lookup_results_for_tracks,
    show_library_context_menu,
    show_selected_candidate_preview,
    update_lookup_status,
)
from src.gui.music_duplicates_lookup_logic import (
    auto_apply_high_confidence_variant,
    auto_selectable_candidate_index,
    apply_variant_choice,
    clear_applied_status,
    clear_no_match_status,
    fetch_cover_preview_bytes,
    find_candidate_index_for_updates,
    get_lookup_result,
    invalidate_lookup_cache_if_manual_updates_conflict,
    lookup_applied_candidate_index,
    lookup_result_is_applied,
    lookup_selected_candidate_index,
    normalize_lookup_value,
    select_variant_in_lookup_cache,
    selected_variant_matches_updates,
    set_track_applied,
    set_track_no_match,
    store_lookup_result,
    sync_lookup_result_after_write,
    update_lookup_result_for_candidate,
    candidate_updates_for_index,
)
from src.gui.music_duplicates_library_panel_logic import (
    clear_selected_track_cache as clear_library_track_cache,
    force_refresh_selected_track_cache as force_refresh_library_track_cache,
    format_player_time,
    load_audio_source,
    on_audio_duration_changed,
    on_audio_playback_state_changed,
    on_audio_position_changed,
    on_library_pitch_changed,
    on_library_volume_changed,
    play_selected_library_track as play_library_track,
    seek_library_preview,
    selected_library_duration_ms,
    selected_library_file_path,
    selected_library_track,
    set_library_expected_duration,
    stop_library_preview as stop_library_track,
    sync_library_audio_output,
    sync_library_playback_rate,
    update_library_detail_panel,
    update_library_player_time_label,
)
from src.gui.music_duplicates_lookup_controller import (
    on_lookup_error,
    on_lookup_finished,
    on_lookup_progress,
    on_lookup_result,
    start_lookup_for_tracks,
)
from src.gui.music_duplicates_scan_controller import (
    on_scan_error,
    on_scan_finished,
    on_scan_progress,
    refresh_from_current_folder,
    scan_library,
    set_scan_busy,
)
from src.gui.music_duplicates_lookup_dialogs import (
    prompt_cover_choice,
    show_lookup_diagnostics_dialog,
)
from src.gui.music_duplicates_metadata_editor import edit_track_metadata
from src.gui.music_duplicates_ui import build_duplicates_tab, build_metadata_tab
from src.gui.music_duplicates_variant_dialog import prompt_variant_choice
from src.gui.music_duplicates_workers import AudioLibraryWorker, AudioLookupWorker
from src.gui.v2.theme import apply_control_sizes, bind_path_tooltip


class MusicDuplicatesView(QWidget):
    status_update = pyqtSignal(str)
    LIBRARY_SELECT_COLUMN = LIBRARY_SELECT_COLUMN
    LIBRARY_FILE_COLUMN = LIBRARY_FILE_COLUMN
    LIBRARY_COLUMN_LABELS = LIBRARY_COLUMN_LABELS
    LIBRARY_COLUMN_DEFAULT_ORDER = LIBRARY_COLUMN_DEFAULT_ORDER
    LIBRARY_DEFAULT_VISIBLE_COLUMNS = LIBRARY_DEFAULT_VISIBLE_COLUMNS
    LIBRARY_COLUMN_DEFAULTS = LIBRARY_COLUMN_DEFAULTS
    LIBRARY_SPLITTER_DEFAULT_SIZES = LIBRARY_SPLITTER_DEFAULT_SIZES

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_folder: str | None = None
        self.results: Dict[str, List[Dict[str, Any]]] = {}
        self.library_all_rows: list[Dict[str, Any]] = []
        self.library_rows: list[Dict[str, Any]] = []
        self._lookup_results_by_path: dict[str, Dict[str, Any]] = {}
        self._lookup_worker: AudioLookupWorker | None = None
        self._lookup_request_token = 0
        self._lookup_active_token = 0
        self._lookup_busy = False
        self._scan_worker: AudioLibraryWorker | None = None
        self._scan_busy = False
        self._restoring_library_header = False
        self._checked_library_paths: set[str] = set()
        self._refreshing_library_table = False
        self.browse_btn = None
        self._library_filter_mode = "all"
        self._library_search_text = ""
        self._toast_target_pos = QPoint()
        self._toast_hide_timer = QTimer(self)
        self._toast_hide_timer.setSingleShot(True)
        self._toast_hide_timer.timeout.connect(self._start_hide_music_toast)
        self.transaction_manager = TransactionManager(
            "audio_duplicate_operations_log.json"
        )
        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.75)
        self.audio_player = QMediaPlayer(self)
        self.audio_player.setAudioOutput(self.audio_output)
        if hasattr(self.audio_player, "setPlaybackRate"):
            self.audio_player.setPlaybackRate(1.0)
        self._audio_context = ""
        self._audio_duration_ms = 0
        self.audio_player.positionChanged.connect(self._on_audio_position_changed)
        self.audio_player.durationChanged.connect(self._on_audio_duration_changed)
        self.audio_player.playbackStateChanged.connect(
            self._on_audio_playback_state_changed
        )
        self._build_ui()
        sync_library_audio_output(self)
        self._restore_music_state()
        sync_library_playback_rate(self)
        self.refresh_missing_metadata()
        self.refresh_library()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        title = QLabel("Duplicados de música")
        title.setObjectName("main_title_label")
        layout.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Selecciona una carpeta de musica...")
        bind_path_tooltip(self.path_input)
        row.addWidget(self.path_input, 1)

        self.browse_btn = QPushButton("Examinar")
        self.browse_btn.clicked.connect(self._browse)
        row.addWidget(self.browse_btn)

        self.scan_btn = QPushButton("Analizar audio")
        self.scan_btn.setObjectName("music_scan_button")
        self.scan_btn.clicked.connect(self.scan)
        row.addWidget(self.scan_btn)
        layout.addLayout(row)

        opts = QHBoxLayout()
        self.recursive_cb = QCheckBox("Incluir subcarpetas")
        self.recursive_cb.setChecked(True)
        opts.addWidget(self.recursive_cb)
        opts.addStretch()
        layout.addLayout(opts)

        self.summary_label = QLabel("Sin resultados todavia.")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        self.scan_status_label = QLabel("Biblioteca musical lista.")
        self.scan_status_label.setWordWrap(True)
        layout.addWidget(self.scan_status_label)
        self.scan_progress = QProgressBar()
        self.scan_progress.setVisible(False)
        self.scan_progress.setRange(0, 0)
        layout.addWidget(self.scan_progress)

        self.tabs = QTabWidget()
        dup_tab = build_duplicates_tab(self)
        meta_tab = build_metadata_tab(self)
        self.tabs.addTab(meta_tab, "Biblioteca")
        self.tabs.addTab(dup_tab, "Revisar duplicados")
        self.tabs.addTab(self.metadata_panel, "Metadatos")
        self.tabs.setObjectName("musicTabs")
        layout.addWidget(self.tabs, 1)

        self.music_toast_frame = QFrame(self)
        self.music_toast_frame.setObjectName("music_auto_toast")
        self.music_toast_frame.setVisible(False)
        self.music_toast_frame.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.music_toast_frame.setStyleSheet(
            "QFrame#music_auto_toast {"
            "background-color: rgba(46, 160, 67, 245);"
            "border: 1px solid rgba(182, 242, 194, 0.98);"
            "border-radius: 12px;"
            "}"
            "QLabel { background: transparent; color: white; }"
        )
        self.music_toast_opacity = QGraphicsOpacityEffect(self.music_toast_frame)
        self.music_toast_opacity.setOpacity(0.0)
        self.music_toast_frame.setGraphicsEffect(self.music_toast_opacity)
        toast_layout = QHBoxLayout(self.music_toast_frame)
        toast_layout.setContentsMargins(18, 12, 18, 12)
        toast_layout.setSpacing(10)
        self.music_toast_icon = QLabel("🤖")
        self.music_toast_icon.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.music_toast_icon.setStyleSheet(
            "font-size: 20px; font-weight: 700; color: white;"
        )
        toast_layout.addWidget(self.music_toast_icon)
        self.music_toast_label = QLabel("")
        self.music_toast_label.setWordWrap(True)
        self.music_toast_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.music_toast_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; color: white;"
        )
        self.music_toast_label.setMaximumWidth(520)
        toast_layout.addWidget(self.music_toast_label, 1)
        self._toast_fade_in_animation = QPropertyAnimation(
            self.music_toast_opacity, b"opacity", self
        )
        self._toast_fade_in_animation.setDuration(180)
        self._toast_fade_in_animation.setStartValue(0.0)
        self._toast_fade_in_animation.setEndValue(1.0)
        self._toast_fade_in_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._toast_fade_out_animation = QPropertyAnimation(
            self.music_toast_opacity, b"opacity", self
        )
        self._toast_fade_out_animation.setDuration(220)
        self._toast_fade_out_animation.setStartValue(1.0)
        self._toast_fade_out_animation.setEndValue(0.0)
        self._toast_fade_out_animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self._toast_fade_out_animation.finished.connect(self._hide_music_toast)
        self._toast_slide_in_animation = QPropertyAnimation(
            self.music_toast_frame, b"pos", self
        )
        self._toast_slide_in_animation.setDuration(180)
        self._toast_slide_in_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._toast_slide_out_animation = QPropertyAnimation(
            self.music_toast_frame, b"pos", self
        )
        self._toast_slide_out_animation.setDuration(220)
        self._toast_slide_out_animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self._position_music_toast()
        apply_control_sizes(self)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta de musica")
        if folder:
            self.current_folder = folder
            self.path_input.setText(folder)
            self._persist_music_state()

    def _position_music_toast(self) -> None:
        toast = getattr(self, "music_toast_frame", None)
        if toast is None:
            return
        anchor = self.tabs.geometry() if hasattr(self, "tabs") else self.rect()
        max_width = max(320, min(700, anchor.width() - 40))
        self.music_toast_label.setMaximumWidth(max_width - 74)
        toast.adjustSize()
        width = min(max_width, max(360, toast.sizeHint().width()))
        height = max(56, toast.sizeHint().height())
        x = max(12, anchor.x() + (anchor.width() - width) // 2)
        y = max(12, anchor.top() + 18)
        toast.resize(width, height)
        self._toast_target_pos = QPoint(x, y)
        if toast.isVisible() and self.music_toast_opacity.opacity() > 0.0:
            toast.move(self._toast_target_pos)
        toast.raise_()

    def _show_music_toast(self, message: str, duration_ms: int = 2000) -> None:
        if not message:
            return
        self._toast_hide_timer.stop()
        self._toast_fade_in_animation.stop()
        self._toast_fade_out_animation.stop()
        self._toast_slide_in_animation.stop()
        self._toast_slide_out_animation.stop()
        self.music_toast_label.setText(message)
        self._position_music_toast()
        start_pos = QPoint(self._toast_target_pos.x(), self._toast_target_pos.y() - 14)
        self.music_toast_frame.move(start_pos)
        self.music_toast_opacity.setOpacity(0.0)
        self.music_toast_frame.show()
        self.music_toast_frame.raise_()
        self._toast_fade_in_animation.start()
        self._toast_slide_in_animation.setStartValue(start_pos)
        self._toast_slide_in_animation.setEndValue(self._toast_target_pos)
        self._toast_slide_in_animation.start()
        self._toast_hide_timer.start(max(500, int(duration_ms) - 260))

    def _start_hide_music_toast(self) -> None:
        if getattr(self, "music_toast_frame", None) is None:
            return
        if not self.music_toast_frame.isVisible():
            return
        self._toast_fade_in_animation.stop()
        self._toast_slide_in_animation.stop()
        self._toast_fade_out_animation.stop()
        self._toast_slide_out_animation.stop()
        current_pos = self.music_toast_frame.pos()
        self._toast_slide_out_animation.setStartValue(current_pos)
        self._toast_slide_out_animation.setEndValue(
            QPoint(self._toast_target_pos.x(), self._toast_target_pos.y() - 10)
        )
        self._toast_slide_out_animation.start()
        self._toast_fade_out_animation.start()

    def _hide_music_toast(self) -> None:
        if getattr(self, "music_toast_frame", None) is not None:
            self.music_toast_opacity.setOpacity(0.0)
            self.music_toast_frame.hide()

    def _restore_music_state(self):
        from src.utils.app_config import AppConfig

        app_config = AppConfig()
        last_folder = app_config.get_music_last_folder().strip()
        recursive = app_config.get_music_recursive()
        preview_playback_rate = app_config.get_music_preview_playback_rate()
        self.recursive_cb.setChecked(recursive)
        if last_folder:
            self.current_folder = last_folder
            self.path_input.setText(last_folder)
        if hasattr(self, "library_pitch_slider"):
            self.library_pitch_slider.setValue(int(round(preview_playback_rate * 100)))

    def _set_scan_busy(self, busy: bool, message: str):
        set_scan_busy(self, busy, message)

    def _on_library_filter_changed(self):
        self._library_filter_mode = str(
            self.library_filter_combo.currentData() or "all"
        )
        self._library_search_text = self.library_search_input.text().strip().lower()
        selected_paths = self._selected_file_paths()
        self.refresh_library()
        self._restore_selected_file_paths(selected_paths)

    def _track_state_label(self, track: Dict[str, Any], lookup: Dict[str, Any]) -> str:
        review_status = str(track.get("review_status") or "")
        if review_status == "complete":
            return "completa"
        if review_status == "no_match":
            return "no coincide"
        if (
            self._lookup_selected_candidate_index(lookup) is not None
            and lookup.get("suggested_updates")
            and not self._lookup_result_is_applied(lookup)
        ):
            return "variante elegida"
        if self._lookup_result_is_applied(lookup) or review_status == "applied":
            return "aplicada"
        candidates = list(lookup.get("candidates") or [])
        if len(candidates) > 1:
            return "variantes"
        if candidates:
            local_metadata = dict(track)
            local_metadata.setdefault("file_path", track.get("file_path", ""))
            if audio_fingerprint_service.should_auto_apply_candidate(
                local_metadata, candidates[0]
            ):
                return "sugerencia fuerte"
            return "pendiente"
        if any(
            not str(track.get(key) or "").strip()
            for key in ("title", "artist", "album")
        ):
            return "pendiente"
        return "local"

    def _match_library_filter(
        self, track: Dict[str, Any], lookup: Dict[str, Any], state_label: str
    ) -> bool:
        filter_mode = self._library_filter_mode
        if filter_mode == "pending" and state_label != "pendiente":
            return False
        if filter_mode == "variants" and state_label != "variantes":
            return False
        if filter_mode == "selected_variant" and state_label != "variante elegida":
            return False
        if filter_mode == "applied" and state_label != "aplicada":
            return False
        if filter_mode == "strong" and state_label != "sugerencia fuerte":
            return False
        if filter_mode == "complete" and state_label != "completa":
            return False
        if filter_mode == "no_match" and state_label != "no coincide":
            return False

        search_text = self._library_search_text
        if not search_text:
            return True
        haystack = " ".join(
            [
                str(Path(track.get("file_path", "")).name),
                str(track.get("title") or ""),
                str(track.get("artist") or ""),
                str(track.get("album") or ""),
                str(track.get("album_artist") or ""),
                str(state_label),
            ]
        ).lower()
        return search_text in haystack

    def _set_cover_preview(self, label: QLabel, file_path: Path | None):
        if not file_path:
            self._clear_cover_preview_label(label, "Sin portada")
            return
        cover_bytes = audio_metadata_service.get_cover_art_bytes(file_path)
        if not cover_bytes:
            self._clear_cover_preview_label(label, "Sin portada")
            return
        self._set_cover_preview_from_bytes(label, cover_bytes)

    def _set_cover_preview_from_bytes(self, label: QLabel, cover_bytes: bytes | None):
        if cover_bytes:
            setattr(label, "_cover_preview_bytes", bytes(cover_bytes))
        else:
            setattr(label, "_cover_preview_bytes", None)
        self._rerender_cover_preview_label(label)

    def _clear_cover_preview_label(self, label: QLabel, text: str) -> None:
        setattr(label, "_cover_preview_bytes", None)
        label.clear()
        label.setText(text)

    def _rerender_cover_preview_label(self, label: QLabel | None) -> None:
        if label is None:
            return
        cover_bytes = getattr(label, "_cover_preview_bytes", None)
        if not cover_bytes:
            if not label.text().strip():
                label.setText("Sin portada")
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(QByteArray(bytes(cover_bytes))):
            self._clear_cover_preview_label(label, "Portada no disponible")
            return
        available_rect = label.contentsRect()
        target_width = max(1, available_rect.width() or label.width() or 180)
        target_height = max(1, available_rect.height() or label.height() or 180)
        scaled = pixmap.scaled(
            target_width,
            target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.clear()
        label.setPixmap(scaled)

    def _get_lookup_result(
        self,
        file_path: str | Path,
        track: Dict[str, Any] | None = None,
        load_cached: bool = True,
    ) -> Dict[str, Any]:
        return get_lookup_result(self, file_path, track, load_cached)

    def _store_lookup_result(
        self,
        file_path: str | Path,
        result: Dict[str, Any],
        persist: bool = True,
    ) -> Dict[str, Any]:
        return store_lookup_result(self, file_path, result, persist)

    def _fetch_cover_preview_bytes(
        self, file_path: str | Path, result: Dict[str, Any]
    ) -> bytes | None:
        return fetch_cover_preview_bytes(self, file_path, result)

    def _clear_no_match_status(self, file_path: str | Path) -> None:
        clear_no_match_status(self, file_path)

    def _set_track_no_match(self, file_path: str | Path) -> bool:
        return set_track_no_match(self, file_path)

    def _set_track_applied(self, file_path: str | Path) -> bool:
        return set_track_applied(self, file_path)

    def _clear_applied_status(self, file_path: str | Path) -> None:
        clear_applied_status(self, file_path)

    def _lookup_selected_candidate_index(
        self, result: Dict[str, Any] | None
    ) -> int | None:
        return lookup_selected_candidate_index(self, result)

    def _lookup_applied_candidate_index(
        self, result: Dict[str, Any] | None
    ) -> int | None:
        return lookup_applied_candidate_index(self, result)

    def _lookup_result_is_applied(self, result: Dict[str, Any] | None) -> bool:
        return lookup_result_is_applied(self, result)

    def _update_lookup_result_for_candidate(
        self, result: Dict[str, Any], chosen_index: int
    ) -> Dict[str, Any]:
        return update_lookup_result_for_candidate(result, chosen_index)

    def _sync_lookup_result_after_write(
        self,
        file_path: str | Path,
        applied: bool,
        chosen_index: int | None = None,
    ) -> Dict[str, Any] | None:
        return sync_lookup_result_after_write(self, file_path, applied, chosen_index)

    def _selected_variant_matches_updates(
        self, result: Dict[str, Any], updates: Dict[str, Any]
    ) -> bool:
        return selected_variant_matches_updates(self, result, updates)

    def _candidate_updates_for_index(
        self, result: Dict[str, Any] | None, index: int | None
    ) -> Dict[str, Any]:
        return candidate_updates_for_index(result, index)

    def _normalize_lookup_value(self, key: str, value: Any) -> str:
        return normalize_lookup_value(key, value)

    def _find_candidate_index_for_updates(
        self, result: Dict[str, Any] | None, updates: Dict[str, Any] | None
    ) -> int | None:
        return find_candidate_index_for_updates(self, result, updates)

    def _variant_field_styles(self, edits: list[QLineEdit], active: bool):
        from src.gui.v2.theme import _config_from_widget, current_tokens
        config = _config_from_widget(self)
        tokens = current_tokens(config.get_accent_color(), config.get_theme_mode())
        style = (f"background: {tokens.surface_alt}; color: {tokens.text_primary}; "
                 f"border: 1px solid {tokens.success}; border-radius: 6px; padding: 5px 8px;") if active else ""
        for edit in edits:
            edit.setStyleSheet(style)

    def _update_library_detail_panel(self):
        update_library_detail_panel(self)

    def _selected_library_file_path(self) -> Path | None:
        return selected_library_file_path(self)

    def _selected_library_track(self) -> Dict[str, Any] | None:
        return selected_library_track(self)

    def _selected_library_duration_ms(self) -> int:
        return selected_library_duration_ms(self)

    def _set_library_expected_duration(
        self, duration_ms: int, enable_seek: bool = False
    ) -> None:
        set_library_expected_duration(self, duration_ms, enable_seek)

    def _format_player_time(self, milliseconds: int) -> str:
        return format_player_time(milliseconds)

    def _on_library_volume_changed(self, value: int) -> None:
        on_library_volume_changed(self, value)

    def _on_library_pitch_changed(self, value: int) -> None:
        on_library_pitch_changed(self, value)

    def _update_library_player_time_label(self) -> None:
        update_library_player_time_label(self)

    def _on_audio_position_changed(self, position: int) -> None:
        on_audio_position_changed(self, position)

    def _on_audio_duration_changed(self, duration: int) -> None:
        on_audio_duration_changed(self, duration)

    def _on_audio_playback_state_changed(self, state) -> None:
        on_audio_playback_state_changed(self, state)

    def _load_audio_source(self, file_path: Path, context: str) -> None:
        load_audio_source(self, file_path, context)

    def play_selected_library_track(self) -> None:
        play_library_track(self)

    def stop_library_preview(self) -> None:
        stop_library_track(self)

    def _seek_library_preview(self, position: int) -> None:
        seek_library_preview(self, position)

    def scan(self):
        scan_library(self)

    def _on_scan_progress(self, message: str):
        on_scan_progress(self, message)

    def _on_scan_finished(self, payload: Dict[str, Any]):
        on_scan_finished(self, payload)

    def _on_scan_error(self, error: str):
        on_scan_error(self, error)

    def _refresh_results(self):
        refresh_duplicate_results(self)

    def _show_group_detail(self, current, previous):
        show_group_detail(self, current, previous)

    def _selected_duplicate_paths(self) -> list[str]:
        return selected_duplicate_paths(self)

    def _update_duplicate_preview(self):
        update_duplicate_preview(self)

    def _select_best_duplicate(self):
        select_best_duplicate(self)

    def _mark_selected_duplicate_as_keep(self):
        mark_selected_duplicate_as_keep(self)

    def _show_duplicates_context_menu(self, position) -> None:
        show_duplicates_context_menu(self, position)

    def play_selected_duplicate(self):
        selected_paths = self._selected_duplicate_paths()
        if not selected_paths:
            QMessageBox.information(
                self, "Duplicados", "Selecciona una pista duplicada para reproducir"
            )
            return
        file_path = Path(selected_paths[0])
        self._load_audio_source(file_path, "duplicate")
        self.audio_player.play()
        self.status_update.emit(f"▶ Reproduciendo: {file_path.name}")

    def stop_duplicate_preview(self):
        self.audio_player.stop()
        self.status_update.emit("⏹ Reproduccion detenida")

    def open_selected_duplicate_folder(self):
        selected_paths = self._selected_duplicate_paths()
        if not selected_paths:
            QMessageBox.information(
                self, "Duplicados", "Selecciona una pista duplicada primero"
            )
            return
        folder = Path(selected_paths[0]).parent
        try:
            os.startfile(str(folder))
        except Exception as exc:
            QMessageBox.warning(
                self, "Duplicados", f"No se pudo abrir la carpeta: {exc}"
            )

    def delete_selected_duplicates(self):
        selected_paths = self._selected_duplicate_paths()
        if not selected_paths:
            QMessageBox.information(
                self,
                "Duplicados",
                "Selecciona una o varias pistas duplicadas para enviar a papelera",
            )
            return
        reply = QMessageBox.question(
            self,
            "Enviar a papelera",
            f"Se retirarán {len(selected_paths)} pistas a la papelera. Si no hay soporte, se moverán a .quarantine junto a cada pista. Las copias sin seleccionar se conservan.\n\n"
            + "\n".join(f"- {Path(path).name}" for path in selected_paths[:10]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        deleted = []
        destinations = []
        for file_path in selected_paths:
            path = Path(file_path)
            if self.transaction_manager.safe_delete_file(path, use_trash=True):
                audio_metadata_service.remove_track(path)
                deleted.append(str(path))
                destinations.append(self.transaction_manager.last_removal_destination)
        if not deleted:
            QMessageBox.warning(
                self, "Duplicados", "No se pudo eliminar ninguna pista seleccionada"
            )
            return
        self._remove_deleted_duplicates_from_results(deleted)
        self.refresh_library()
        self.refresh_missing_metadata()
        self.status_update.emit(f"Pistas retiradas: {len(deleted)}. Destino: {', '.join(dict.fromkeys(destinations))}")

    def _remove_deleted_duplicates_from_results(self, deleted_paths: list[str]) -> None:
        deleted_set = {str(Path(path)) for path in deleted_paths}
        updated: Dict[str, List[Dict[str, Any]]] = {}
        for identity_key, group in self.results.items():
            remaining = [
                item
                for item in group
                if str(Path(item.get("file_path", ""))) not in deleted_set
            ]
            if len(remaining) >= 2:
                updated[identity_key] = remaining
        self.results = updated
        self._refresh_results()

    def refresh_missing_metadata(self):
        rows = audio_metadata_service.find_missing_metadata(limit=250)
        self.missing_count_label.setText(
            f"Pistas con metadatos incompletos: {len(rows)}"
        )

    def enrich_selected_metadata(self):
        selected = self._get_selected_tracks()
        if not selected:
            QMessageBox.information(self, "Metadatos", "Selecciona una o varias pistas")
            return
        changed = 0
        for track in selected:
            file_path = Path(track["file_path"])
            row = audio_metadata_service.get_metadata(file_path)
            if not row:
                continue
            updates = {}
            if not row.get("title"):
                updates["title"] = file_path.stem
            if not row.get("artist"):
                updates["artist"] = row.get("album_artist") or "Unknown Artist"
            if not row.get("album"):
                updates["album"] = file_path.parent.name
            if updates and audio_metadata_service.update_track_tags(file_path, updates):
                invalidate_lookup_cache_if_manual_updates_conflict(
                    self, file_path, updates
                )
                self._clear_no_match_status(file_path)
                self._sync_lookup_result_after_write(file_path, applied=False)
                changed += 1
        if changed:
            self.status_update.emit(f"✨ Metadatos actualizados: {changed}")
            self.refresh_missing_metadata()
            self.refresh_library()

    def _start_lookup_for_tracks(
        self,
        selected: list[Dict[str, Any]],
        selected_paths: list[str],
        *,
        force_refresh: bool = False,
        start_message: str | None = None,
    ) -> None:
        start_lookup_for_tracks(
            self,
            selected,
            selected_paths,
            force_refresh=force_refresh,
            start_message=start_message,
        )

    def lookup_selected_online(self, force_refresh: bool = False):
        selected = self._get_selected_tracks()
        if not selected:
            QMessageBox.information(self, "Metadatos", "Selecciona una o varias pistas")
            return
        selected_paths = self._selected_file_paths()
        self._start_lookup_for_tracks(
            selected,
            selected_paths,
            force_refresh=bool(force_refresh),
            start_message=(
                f"🌐 Forzando refresh online para {len(selected)} pista(s)..."
                if force_refresh
                else f"🌐 Iniciando busqueda online para {len(selected)} pista(s)..."
            ),
        )

    def force_refresh_selected_track_cache(self) -> None:
        force_refresh_library_track_cache(self)

    def clear_selected_track_cache(self) -> None:
        clear_library_track_cache(self)

    def choose_selected_track_cover(self) -> None:
        track = self._selected_library_track()
        if not track:
            QMessageBox.information(self, "Portadas", "Selecciona una pista primero")
            return
        prompt_cover_choice(self, str(track.get("file_path") or ""))

    def show_selected_track_diagnostics(self) -> None:
        track = self._selected_library_track()
        if not track:
            QMessageBox.information(self, "Diagnostico", "Selecciona una pista primero")
            return
        show_lookup_diagnostics_dialog(self, str(track.get("file_path") or ""))

    def _on_lookup_progress(self, token: int, message: str, current: int, total: int):
        on_lookup_progress(self, token, message, current, total)

    def _on_lookup_result(self, token: int, result: Dict[str, Any]):
        on_lookup_result(self, token, result)

    def _on_lookup_finished(self, token: int, selected_paths: list[str]):
        on_lookup_finished(self, token, selected_paths)

    def _on_lookup_error(self, token: int, error: str):
        on_lookup_error(self, token, error)

    def _set_lookup_busy(self, busy: bool, message: str):
        self._lookup_busy = busy
        self.lookup_progress.setVisible(busy)
        recursive_cb = self.recursive_cb
        if busy:
            self.lookup_progress.setRange(0, 0)
            self.lookup_progress.setValue(0)
            self.online_lookup_btn.setEnabled(False)
            self.edit_meta_btn.setEnabled(False)
            self.apply_all_btn.setEnabled(False)
            self.refresh_missing_btn.setEnabled(False)
            self.enrich_btn.setEnabled(False)
            self.library_filter_combo.setEnabled(False)
            self.library_search_input.setEnabled(False)
            self.library_columns_btn.setEnabled(False)
            self.library_reset_view_btn.setEnabled(False)
        else:
            self.lookup_progress.setRange(0, 1)
            self.lookup_progress.setValue(0)
            self.online_lookup_btn.setEnabled(True)
            self.edit_meta_btn.setEnabled(True)
            self.apply_all_btn.setEnabled(True)
            self.refresh_missing_btn.setEnabled(True)
            self.enrich_btn.setEnabled(True)
            self.library_filter_combo.setEnabled(True)
            self.library_search_input.setEnabled(True)
            self.library_columns_btn.setEnabled(True)
            self.library_reset_view_btn.setEnabled(True)
            self._lookup_worker = None
        self.lookup_status_label.setText(message)
        if self._scan_busy:
            self.scan_btn.setEnabled(False)
            self.path_input.setEnabled(False)
            self.library_filter_combo.setEnabled(False)
            self.library_search_input.setEnabled(False)
            self.library_columns_btn.setEnabled(False)
            self.library_reset_view_btn.setEnabled(False)
        if self.browse_btn is not None:
            self.browse_btn.setEnabled(not busy and not self._scan_busy)
        recursive_cb.setEnabled(not busy and not self._scan_busy)
        self.path_input.setEnabled(not busy and not self._scan_busy)

    def choose_variant_for_selected(self):
        selected_paths = self._selected_file_paths()
        if not selected_paths:
            QMessageBox.information(
                self,
                "Variantes",
                "Selecciona una o varias pistas y busca online primero",
            )
            return
        changed_variants = self._choose_variant_sequence(selected_paths)
        if not changed_variants:
            QMessageBox.information(
                self,
                "Variantes",
                "Las pistas seleccionadas no tienen varias variantes aprovechables",
            )
            return
        self.refresh_library()
        self._restore_selected_file_paths(selected_paths)
        self._show_selected_candidate_preview()
        self.refresh_missing_metadata()
        self.status_update.emit(f"🎯 Variantes elegidas: {changed_variants}")

    def apply_batch_metadata(self):
        rows = self._get_selected_tracks()
        if not rows:
            QMessageBox.information(self, "Lote", "Selecciona pistas en la biblioteca")
            return
        selected_paths = self._selected_file_paths()
        results = self._lookup_results_for_tracks(rows, fetch_missing=True)
        changed_variants = self._choose_variant_sequence(selected_paths)
        if changed_variants:
            self.refresh_library()
            self._restore_selected_file_paths(selected_paths)
            self.refresh_missing_metadata()
            results = self._lookup_results_for_tracks(rows, fetch_missing=False)
        changed = self._apply_batch_candidates(results, confirm=True)
        if changed:
            self.status_update.emit(f"📦 Lote aplicado: {changed}")
            self.refresh_library()
            self.refresh_missing_metadata()
            self._restore_selected_file_paths(selected_paths)
            self._show_selected_candidate_preview()

    def _get_selected_tracks(self) -> list[Dict[str, Any]]:
        return get_selected_tracks(self)

    def _apply_batch_candidates(
        self, candidates: list[Dict[str, Any]], confirm: bool = True
    ) -> int:
        applicable = []
        skipped = 0
        for item in candidates:
            suggested = item.get("suggested_updates")
            if not suggested:
                continue
            local_metadata = dict(item.get("local_metadata") or {})
            local_metadata.setdefault("file_path", item.get("file_path", ""))
            candidate_list = list(item.get("candidates") or [])
            selected_index = self._lookup_selected_candidate_index(item)
            candidate = None
            if selected_index is not None and 0 <= selected_index < len(candidate_list):
                candidate = candidate_list[selected_index]
            elif candidate_list:
                candidate = candidate_list[0]
            if candidate and audio_fingerprint_service.should_auto_apply_candidate(
                local_metadata, candidate
            ):
                applicable.append(item)
            else:
                skipped += 1
        if not applicable:
            if skipped:
                QMessageBox.information(
                    self,
                    "Aplicar lote",
                    "No hay coincidencias suficientemente fiables para aplicar en lote.",
                )
            return 0
        preview_lines = [
            f"Se encontraron {len(applicable)} pistas con sugerencias fiables.",
            "",
        ]
        if skipped:
            preview_lines.append(
                f"Se omiten {skipped} pista(s) por no alcanzar el umbral conservador."
            )
            preview_lines.append("")
        for item in applicable[:10]:
            suggested = item.get("suggested_updates", {})
            preview_lines.append(
                f"- {Path(item['file_path']).name}: {item.get('source')} -> {suggested.get('artist', '')} / {suggested.get('title', '')} / {suggested.get('album', '')}"
            )
        if confirm:
            reply = QMessageBox.question(
                self,
                "Aplicar lote",
                "\n".join(preview_lines)
                + "\n\n¿Aplicar sugerencias a todas las pistas seleccionadas?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return 0
        changed = 0
        for candidate in applicable:
            suggested = candidate.get("suggested_updates", {})
            if not suggested:
                continue
            path = Path(candidate["file_path"])
            if audio_metadata_service.update_track_tags(path, suggested):
                self._clear_no_match_status(path)
                self._sync_lookup_result_after_write(
                    path,
                    applied=True,
                    chosen_index=self._lookup_selected_candidate_index(candidate),
                )
                changed += 1
        return changed

    def _show_selected_candidate_preview(self):
        show_selected_candidate_preview(self)

    def _update_lookup_status(self, results: list[Dict[str, Any]]):
        update_lookup_status(self, results)

    def _show_library_context_menu(self, position):
        show_library_context_menu(self, position)

    def _toggle_track_complete(self, target: Path):
        current = audio_metadata_service.get_track_review_status(target)
        new_status = "" if current == "complete" else "complete"
        if audio_metadata_service.set_track_review_status(target, new_status):
            selected_paths = self._selected_file_paths() or [str(target)]
            self.refresh_library()
            self._restore_selected_file_paths(selected_paths, str(target))
            self.refresh_missing_metadata()
            state = "completa" if new_status == "complete" else "pendiente"
            self.status_update.emit(f"✅ Fila marcada como {state}: {target.name}")

    def _toggle_track_no_match(self, target: Path):
        current = audio_metadata_service.get_track_review_status(target)
        new_status = "" if current == "no_match" else "no_match"
        if audio_metadata_service.set_track_review_status(target, new_status):
            selected_paths = self._selected_file_paths() or [str(target)]
            self.refresh_library()
            self._restore_selected_file_paths(selected_paths, str(target))
            self.refresh_missing_metadata()
            state = "no coincide" if new_status == "no_match" else "pendiente"
            self.status_update.emit(f"🚫 Fila marcada como {state}: {target.name}")

    def refresh_library(self):
        refresh_library_rows(self)

    def _move_lookup_result_path(self, old_path: Path, new_path: Path) -> None:
        old_key = str(Path(old_path))
        new_key = str(Path(new_path))
        existing = dict(self._lookup_results_by_path.pop(old_key, {}) or {})
        if not existing:
            return
        existing["file_path"] = new_key
        local_metadata = dict(existing.get("local_metadata") or {})
        if local_metadata:
            local_metadata["file_path"] = new_key
            existing["local_metadata"] = local_metadata
        self._store_lookup_result(new_key, existing, persist=True)

    def clean_selected_titles(self):
        file_paths = self._selected_file_paths()
        if not file_paths:
            QMessageBox.information(self, "Limpieza", "Selecciona una o varias pistas")
            return
        changed_titles = 0
        renamed_files = 0
        updated_paths: list[str] = []
        for file_path in file_paths:
            target = Path(file_path)
            if not target:
                continue
            track = audio_metadata_service.get_metadata(target) or {}
            current_title = track.get("title") or target.stem
            clean_title = audio_metadata_service.clean_track_title(current_title)
            current_stem = target.stem
            clean_stem = audio_metadata_service.clean_track_filename(current_stem)
            active_path = target
            title_changed = False
            if clean_title and clean_title != current_title:
                if audio_metadata_service.update_track_tags(
                    target, {"title": clean_title}
                ):
                    invalidate_lookup_cache_if_manual_updates_conflict(
                        self, target, {"title": clean_title}
                    )
                    title_changed = True
                    changed_titles += 1
            if clean_stem and clean_stem != current_stem:
                renamed_path = target.with_name(f"{clean_stem}{target.suffix}")
                if audio_metadata_service.rename_track_file(target, renamed_path.name):
                    self._move_lookup_result_path(target, renamed_path)
                    active_path = renamed_path
                    renamed_files += 1
            if title_changed:
                self._sync_lookup_result_after_write(active_path, applied=False)
            updated_paths.append(str(active_path))
        if changed_titles or renamed_files:
            self.status_update.emit(
                "🧼 Titulos limpiados: "
                f"metadatos={changed_titles} | archivos renombrados={renamed_files}"
            )
            self.refresh_library()
            self._restore_selected_file_paths(updated_paths)
            self.refresh_missing_metadata()

    def edit_selected_metadata(self):
        selected = self._get_selected_tracks()
        if not selected:
            QMessageBox.information(self, "Edicion", "Selecciona una pista")
            return
        self._edit_track_metadata(Path(selected[0]["file_path"]))

    def _edit_track_metadata(self, target: Path):
        edit_track_metadata(self, target)

    def refresh_from_folder(self):
        refresh_from_current_folder(self)

    def resizeEvent(self, a0):
        super().resizeEvent(a0)
        self._rerender_cover_preview_label(getattr(self, "library_cover_label", None))
        self._position_music_toast()
        return

    def _persist_music_state(self):
        from src.utils.app_config import AppConfig

        app_config = AppConfig()
        app_config.set_music_last_folder(
            self.current_folder or self.path_input.text().strip()
        )
        app_config.set_music_recursive(self.recursive_cb.isChecked())

    def _apply_saved_column_widths(self):
        from src.utils.app_config import AppConfig

        widths = AppConfig().get_music_library_column_widths()
        if widths and any(width > 0 for width in widths):
            for index, width in enumerate(widths[: self.library_table.columnCount()]):
                self.library_table.setColumnWidth(index, width)
        else:
            for index, default_width in enumerate(self.LIBRARY_COLUMN_DEFAULTS):
                if index < self.library_table.columnCount():
                    self.library_table.setColumnWidth(index, default_width)

    def _restore_library_header_state(self):
        from src.utils.app_config import AppConfig

        header = self.library_table.horizontalHeader()
        if header is None:
            return
        order = AppConfig().get_music_library_column_order()
        if not order:
            order = list(self.LIBRARY_COLUMN_DEFAULT_ORDER)
        if len(order) < self.library_table.columnCount():
            order = list(self.LIBRARY_COLUMN_DEFAULT_ORDER)
        if (
            len(set(order[: self.library_table.columnCount()]))
            != self.library_table.columnCount()
        ):
            order = list(self.LIBRARY_COLUMN_DEFAULT_ORDER)
        self._restoring_library_header = True
        try:
            ordered_logical_indexes = sorted(
                range(self.library_table.columnCount()), key=lambda idx: order[idx]
            )
            for target_visual_index, logical_index in enumerate(
                ordered_logical_indexes
            ):
                current_visual_index = header.visualIndex(logical_index)
                if current_visual_index != target_visual_index:
                    header.moveSection(current_visual_index, target_visual_index)
        except Exception:
            pass
        finally:
            self._restoring_library_header = False

    def _save_library_header_state(self, *args):
        if self._restoring_library_header:
            return
        from src.utils.app_config import AppConfig

        header = self.library_table.horizontalHeader()
        if header is None:
            return
        try:
            order = [
                header.visualIndex(logical_index)
                for logical_index in range(self.library_table.columnCount())
            ]
        except Exception:
            return
        AppConfig().set_music_library_column_order(order)
        AppConfig().set_music_library_header_state(
            ",".join(str(value) for value in order)
        )

    def _restore_library_table_layout(self):
        self._apply_saved_column_widths()
        self._restore_library_header_state()
        self._apply_saved_visible_columns()

    def _apply_saved_visible_columns(self):
        from src.utils.app_config import AppConfig

        visible_columns = set(AppConfig().get_music_library_visible_columns())
        if not visible_columns:
            visible_columns = set(self.LIBRARY_DEFAULT_VISIBLE_COLUMNS)
        visible_columns.update({self.LIBRARY_SELECT_COLUMN, self.LIBRARY_FILE_COLUMN})
        for index in range(self.library_table.columnCount()):
            self.library_table.setColumnHidden(index, index not in visible_columns)

    def _save_visible_columns(self):
        from src.utils.app_config import AppConfig

        visible_columns = [
            index
            for index in range(self.library_table.columnCount())
            if not self.library_table.isColumnHidden(index)
        ]
        if self.LIBRARY_SELECT_COLUMN not in visible_columns:
            visible_columns.insert(0, self.LIBRARY_SELECT_COLUMN)
        if self.LIBRARY_FILE_COLUMN not in visible_columns:
            visible_columns.insert(1, self.LIBRARY_FILE_COLUMN)
        AppConfig().set_music_library_visible_columns(sorted(set(visible_columns)))

    def _restore_library_splitter_sizes(self):
        from src.utils.app_config import AppConfig

        if not hasattr(self, "library_splitter"):
            return
        sizes = self._normalize_library_splitter_sizes(
            AppConfig().get_music_library_splitter_sizes()
        )
        self.library_splitter.setSizes(sizes)

    def _save_library_splitter_sizes(self, *args):
        from src.utils.app_config import AppConfig

        if not hasattr(self, "library_splitter"):
            return
        AppConfig().set_music_library_splitter_sizes(
            self._normalize_library_splitter_sizes(self.library_splitter.sizes())
        )
        self._rerender_cover_preview_label(getattr(self, "library_cover_label", None))

    def _normalize_library_splitter_sizes(
        self, sizes: list[int] | tuple[int, ...] | None = None
    ) -> list[int]:
        min_left = 360
        min_right = 240
        default_sizes = list(self.LIBRARY_SPLITTER_DEFAULT_SIZES)
        requested = [int(value) for value in list(sizes or [])[:2]]
        if len(requested) < 2:
            requested = default_sizes
        total = sum(max(0, value) for value in requested)
        if total < (min_left + min_right):
            total = max(sum(default_sizes), min_left + min_right)
            requested = list(default_sizes)
        max_right = max(min_right, int(total * 0.42))
        right = max(min_right, min(int(requested[1]), max_right))
        left = max(min_left, total - right)
        if left + right < (min_left + min_right):
            left = min_left
            right = min_right
        return [left, right]

    def _sync_library_bottom_scroll(self, *args) -> None:
        if not hasattr(self, "library_bottom_scroll"):
            return
        internal_scroll = cast(QScrollBar, self.library_table.horizontalScrollBar())
        self.library_bottom_scroll.blockSignals(True)
        try:
            self.library_bottom_scroll.setRange(
                internal_scroll.minimum(), internal_scroll.maximum()
            )
            self.library_bottom_scroll.setPageStep(internal_scroll.pageStep())
            self.library_bottom_scroll.setValue(internal_scroll.value())
            self.library_bottom_scroll.setVisible(internal_scroll.maximum() > 0)
        finally:
            self.library_bottom_scroll.blockSignals(False)

    def _on_library_bottom_scroll_changed(self, value: int) -> None:
        internal_scroll = cast(QScrollBar, self.library_table.horizontalScrollBar())
        internal_scroll.setValue(int(value))

    def _edit_library_columns(self):
        edit_library_columns(self)

    def _on_library_item_changed(self, item: QTableWidgetItem) -> None:
        if self._refreshing_library_table:
            return
        if item.column() != self.LIBRARY_SELECT_COLUMN:
            return
        file_path = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not file_path:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._checked_library_paths.add(file_path)
        else:
            self._checked_library_paths.discard(file_path)

    def _save_column_widths(self):
        if self._restoring_library_header:
            return
        from src.utils.app_config import AppConfig

        header = self.library_table.horizontalHeader()
        widths = [
            header.sectionSize(i)
            if header is not None
            else self.library_table.columnWidth(i)
            for i in range(self.library_table.columnCount())
        ]
        AppConfig().set_music_library_column_widths(widths)

    def _reset_table_layout(self):
        header = self.library_table.horizontalHeader()
        if header is not None:
            self._restoring_library_header = True
            try:
                ordered_logical_indexes = list(self.LIBRARY_COLUMN_DEFAULT_ORDER)
                for target_visual_index, logical_index in enumerate(
                    ordered_logical_indexes
                ):
                    current_visual_index = header.visualIndex(logical_index)
                    if current_visual_index != target_visual_index:
                        header.moveSection(current_visual_index, target_visual_index)
            finally:
                self._restoring_library_header = False
        for index, width in enumerate(self.LIBRARY_COLUMN_DEFAULTS):
            if index < self.library_table.columnCount():
                self.library_table.setColumnWidth(index, width)
                self.library_table.setColumnHidden(
                    index, index not in self.LIBRARY_DEFAULT_VISIBLE_COLUMNS
                )
        if hasattr(self, "library_splitter"):
            self.library_splitter.setSizes(self.LIBRARY_SPLITTER_DEFAULT_SIZES)
        self._save_column_widths()
        self._save_library_header_state()
        self._save_visible_columns()
        self._save_library_splitter_sizes()
        self._sync_library_bottom_scroll()

    def _restore_column_widths(self):
        self._restore_library_table_layout()

    def _lookup_results_for_tracks(
        self, tracks: list[Dict[str, Any]], fetch_missing: bool
    ) -> list[Dict[str, Any]]:
        return lookup_results_for_tracks(self, tracks, fetch_missing)

    def _selected_file_paths(self) -> list[str]:
        return get_selected_file_paths(self)

    def _restore_selected_file_paths(
        self, file_paths: list[str], focus_file_path: str | None = None
    ) -> None:
        restore_selected_file_paths(self, file_paths, focus_file_path)

    def _edit_metadata_from_item(self, item: QTableWidgetItem):
        if item is None:
            return
        if item.column() == self.LIBRARY_SELECT_COLUMN:
            return
        target = Path(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        if not target:
            return
        self._edit_track_metadata(target)

    def _choose_variant_sequence(self, file_paths: list[str]) -> int:
        variant_targets = []
        for file_path in file_paths:
            result = self._get_lookup_result(file_path)
            if auto_selectable_candidate_index(self, file_path, result) is not None:
                continue
            if result and len(result.get("candidates") or []) > 1:
                variant_targets.append(str(Path(file_path)))
        if not variant_targets:
            return 0
        chosen_count = 0
        total = len(variant_targets)
        for index, file_path in enumerate(variant_targets, start=1):
            chosen_index = self._prompt_variant_choice(file_path, index, total)
            if chosen_index is None:
                break
            if chosen_index == -2:
                if self._set_track_no_match(file_path):
                    self.refresh_missing_metadata()
                continue
            if chosen_index < 0:
                continue
            if self._apply_variant_choice(file_path, chosen_index):
                chosen_count += 1
        return chosen_count

    def _prompt_variant_choice(
        self, file_path: str, position: int, total: int
    ) -> int | None:
        return prompt_variant_choice(self, file_path, position, total)

    def _select_variant_in_lookup_cache(
        self, file_path: str, chosen_index: int
    ) -> Dict[str, Any] | None:
        return select_variant_in_lookup_cache(self, file_path, chosen_index)

    def _apply_variant_choice(self, file_path: str, chosen_index: int) -> bool:
        return apply_variant_choice(self, file_path, chosen_index)

    def _auto_selectable_candidate_index(
        self, file_path: str | Path, result: Dict[str, Any] | None = None
    ) -> int | None:
        return auto_selectable_candidate_index(self, file_path, result)

    def _auto_apply_high_confidence_variant(
        self, file_path: str | Path, result: Dict[str, Any] | None = None
    ) -> bool:
        return auto_apply_high_confidence_variant(self, file_path, result)

    def _select_row_by_file_path(self, file_path: str) -> None:
        target = str(Path(file_path))
        self.library_table.clearSelection()
        for row in range(self.library_table.rowCount()):
            item = self.library_table.item(row, 0)
            if item and str(item.data(Qt.ItemDataRole.UserRole) or "") == target:
                self.library_table.selectRow(row)
                self.library_table.scrollToItem(item)
                break

    def _format_lookup_reason(self, reason: str) -> str:
        return format_lookup_reason(reason)

    def _summarize_lookup_candidates(
        self, result: Dict[str, Any], limit: int = 3
    ) -> str:
        return summarize_lookup_candidates(result, limit=limit)

    def _format_quality(self, track: Dict[str, Any]) -> str:
        return format_quality(track)

    def _format_bitrate(self, bitrate: Any) -> str:
        return format_bitrate(bitrate)

    def _format_file_size(self, size: Any) -> str:
        return format_file_size(size)

    def _format_duration(self, duration: Any) -> str:
        return format_duration(duration)
