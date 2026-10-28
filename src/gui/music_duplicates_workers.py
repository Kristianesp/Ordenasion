#!/usr/bin/env python3
"""Workers asíncronos para la vista musical (cancelables)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List

from PyQt6.QtCore import QThread, pyqtSignal

from src.core.audio_duplicates import audio_duplicate_finder
from src.core.audio_fingerprint import audio_fingerprint_service
from src.core.audio_index import audio_metadata_service
from src.core.duplicate_finder import ScanCancelled
from src.core.hash_manager import HashCancelled


class AudioLookupWorker(QThread):
    progress = pyqtSignal(str, int, int)
    result_ready = pyqtSignal(dict)
    finished_ok = pyqtSignal()
    error_occurred = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, tracks: List[Dict[str, Any]], force_refresh: bool = False):
        super().__init__()
        self.tracks = list(tracks)
        self.force_refresh = bool(force_refresh)
        self.cancel_event = threading.Event()

    def stop(self):
        self.cancel_event.set()
        self.requestInterruption()

    def _is_cancelled(self) -> bool:
        return self.cancel_event.is_set() or self.isInterruptionRequested()

    def run(self):
        try:
            total = len(self.tracks)
            for index, track in enumerate(self.tracks, start=1):
                if self._is_cancelled():
                    self.cancelled.emit()
                    return
                file_path = Path(track.get("file_path", ""))
                self.progress.emit(
                    f"🌐 Buscando online [{index}/{total}]: {file_path.name}",
                    index,
                    total,
                )
                result = audio_fingerprint_service.get_or_lookup_online_metadata(
                    file_path,
                    track,
                    force_refresh=self.force_refresh,
                )
                result["file_path"] = str(file_path)
                self.result_ready.emit(result)
            self.finished_ok.emit()
        except Exception as exc:  # el hilo no debe morir en silencio
            self.error_occurred.emit(str(exc))


class AudioLibraryWorker(QThread):
    progress = pyqtSignal(str)
    finished_ok = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, folder: str, recursive: bool, include_duplicates: bool):
        super().__init__()
        self.folder = str(folder)
        self.recursive = bool(recursive)
        self.include_duplicates = bool(include_duplicates)
        self.cancel_event = threading.Event()

    def stop(self):
        self.cancel_event.set()
        self.requestInterruption()

    def run(self):
        try:
            folder_path = Path(self.folder)
            self.progress.emit(f"🎵 Indexando biblioteca: {folder_path}")

            def on_progress(done: int, total: int) -> None:
                self.progress.emit(f"🎵 Indexando biblioteca: {done}/{total} pistas")

            metadata = audio_metadata_service.index_folder_detailed(
                folder_path,
                recursive=self.recursive,
                cancel_event=self.cancel_event,
                progress=on_progress,
            )
            indexed = sum(1 for meta in metadata if meta.error != "mutagen_no_disponible")
            duplicates: Dict[str, List[Dict[str, Any]]] = {}
            if self.include_duplicates:
                self.progress.emit("🎵 Analizando duplicados musicales...")
                duplicates = audio_duplicate_finder.scan_folder(
                    str(folder_path),
                    recursive=self.recursive,
                    metadata=metadata,
                    cancel_event=self.cancel_event,
                    progress=self.progress.emit,
                )
            self.finished_ok.emit(
                {
                    "folder": str(folder_path),
                    "recursive": self.recursive,
                    "indexed": indexed,
                    "include_duplicates": self.include_duplicates,
                    "duplicates": duplicates,
                }
            )
        except (ScanCancelled, HashCancelled):
            self.cancelled.emit()
        except Exception as exc:  # el hilo no debe morir en silencio
            self.error_occurred.emit(str(exc))
