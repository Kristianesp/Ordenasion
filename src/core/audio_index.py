#!/usr/bin/env python3
"""
Indexador de audio local para musica.

Extrae metadatos tecnicos y tags basicos de ficheros de audio. Si `mutagen`
no esta disponible, devuelve informacion de fallback sin romper el flujo.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import re
import base64
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from src.utils.logger import debug


@dataclass
class AudioMetadata:
    file_path: str
    file_size: int = 0
    mtime: float = 0.0
    extension: str = ""
    codec: str = "unknown"
    duration: Optional[float] = None
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    bit_depth: Optional[int] = None
    lossless: Optional[bool] = None
    artist: str = ""
    album_artist: str = ""
    title: str = ""
    album: str = ""
    track_number: str = ""
    disc_number: str = ""
    year: str = ""
    genre: str = ""
    tags: Dict[str, Any] = field(default_factory=dict)
    source: str = "local"
    error: str = ""

    def to_record(self) -> Dict[str, Any]:
        record = asdict(self)
        record["tags"] = json.dumps(self.tags, ensure_ascii=False)
        record["indexed_at"] = datetime.now().isoformat(timespec="seconds")
        return record


class AudioMetadataService:
    """Extrae y persiste metadatos de audio de forma local."""

    AUDIO_EXTENSIONS = {
        ".mp3",
        ".flac",
        ".wav",
        ".m4a",
        ".aac",
        ".ogg",
        ".wma",
        ".alac",
        ".aiff",
        ".aif",
    }

    LOSSLESS_EXTENSIONS = {".flac", ".wav", ".alac", ".aiff", ".aif"}
    RESERVED_FILENAMES = {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }

    TAG_KEY_ALIASES = {
        "artist": {"artist", "tpe1", "author", "\xa9art"},
        "albumartist": {"albumartist", "album artist", "album_artist", "tpe2", "aart"},
        "title": {"title", "tit2", "\xa9nam"},
        "album": {"album", "talb", "\xa9alb"},
        "tracknumber": {"tracknumber", "track", "track_number", "trck", "trkn"},
        "discnumber": {
            "discnumber",
            "disc",
            "disk",
            "disc_number",
            "disknumber",
            "tpos",
        },
        "date": {"date", "year", "tdrc", "\xa9day"},
        "genre": {"genre", "tcon", "\xa9gen"},
    }

    WRITABLE_TAG_KEYS = {
        "title",
        "artist",
        "album",
        "albumartist",
        "tracknumber",
        "discnumber",
        "date",
        "genre",
    }

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            from src.utils.paths import user_data_file
            db_path = user_data_file("media_index.db")
        self.db_path = Path(db_path)
        self.lock = threading.RLock()
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self.lock:
            conn = self._get_connection()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS audio_tracks (
                        file_path TEXT PRIMARY KEY,
                        file_size INTEGER NOT NULL,
                        mtime REAL NOT NULL,
                        extension TEXT NOT NULL,
                        codec TEXT NOT NULL,
                        duration REAL,
                        bitrate INTEGER,
                        sample_rate INTEGER,
                        channels INTEGER,
                        bit_depth INTEGER,
                        lossless INTEGER,
                        artist TEXT,
                        album_artist TEXT,
                        title TEXT,
                        album TEXT,
                        track_number TEXT,
                        disc_number TEXT,
                        year TEXT,
                        genre TEXT,
                        tags TEXT,
                        source TEXT,
                        error TEXT,
                        indexed_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_audio_tracks_mtime ON audio_tracks(mtime);
                    CREATE INDEX IF NOT EXISTS idx_audio_tracks_codec ON audio_tracks(codec);
                    CREATE TABLE IF NOT EXISTS audio_track_review_state (
                        file_path TEXT PRIMARY KEY,
                        review_status TEXT NOT NULL,
                        reviewed_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_audio_track_review_state_status
                        ON audio_track_review_state(review_status);
                    CREATE TABLE IF NOT EXISTS audio_lookup_cache (
                        file_path TEXT PRIMARY KEY,
                        cache_key TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        cover_art BLOB,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_audio_lookup_cache_updated_at
                        ON audio_lookup_cache(updated_at);
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def is_audio_file(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.AUDIO_EXTENSIONS

    def extract_metadata(self, file_path: Path) -> AudioMetadata:
        file_path = Path(file_path)
        try:
            stat = file_path.stat()
        except OSError as exc:
            return AudioMetadata(file_path=str(file_path), error=str(exc))

        metadata = AudioMetadata(
            file_path=str(file_path),
            file_size=stat.st_size,
            mtime=stat.st_mtime,
            extension=file_path.suffix.lower(),
            codec=file_path.suffix.lower().lstrip(".") or "unknown",
            lossless=file_path.suffix.lower() in self.LOSSLESS_EXTENSIONS,
        )

        try:
            from mutagen import File as MutagenFile
        except Exception:
            metadata.error = "mutagen_no_disponible"
            return metadata

        try:
            audio = MutagenFile(str(file_path), easy=False)
            if audio is None:
                metadata.error = "formato_no_soportado"
                return metadata

            info = getattr(audio, "info", None)
            metadata.codec = (
                getattr(info, "codec", None) or audio.__class__.__name__.lower()
            )
            metadata.duration = getattr(info, "length", None)
            metadata.bitrate = getattr(info, "bitrate", None)
            metadata.sample_rate = getattr(info, "sample_rate", None)
            metadata.channels = getattr(info, "channels", None)
            metadata.bit_depth = getattr(info, "bits_per_sample", None)

            tags = self._read_tags(audio)
            if self._needs_easy_tags(audio):
                try:
                    easy_audio = MutagenFile(str(file_path), easy=True)
                    if easy_audio is not None:
                        tags = {**tags, **self._read_tags(easy_audio)}
                except Exception as exc:  # mutagen lanza tipos variados por formato
                    debug(f"Tags 'easy' no disponibles para {file_path.name}: {exc}")
            metadata.tags = tags
            metadata.artist = tags.get("artist", "")
            metadata.album_artist = tags.get("albumartist", "") or tags.get(
                "album artist", ""
            )
            metadata.title = tags.get("title", "")
            metadata.album = tags.get("album", "")
            metadata.track_number = tags.get("tracknumber", "")
            metadata.disc_number = tags.get("discnumber", "")
            metadata.year = tags.get("date", "") or tags.get("year", "")
            metadata.genre = tags.get("genre", "")

            if metadata.lossless is None:
                metadata.lossless = metadata.extension in self.LOSSLESS_EXTENSIONS

            return metadata

        except Exception as exc:
            metadata.error = str(exc)
            return metadata

    @staticmethod
    def _needs_easy_tags(audio) -> bool:
        """Los comentarios Vorbis (FLAC/OGG/Opus) ya son legibles: no hace falta reabrir."""
        tags = getattr(audio, "tags", None)
        if tags is None:
            return False
        try:
            from mutagen._vorbis import VComment

            if isinstance(tags, VComment):
                return False
        except ImportError:
            pass
        return True

    def _read_tags(self, audio) -> Dict[str, str]:
        tags: Dict[str, str] = {}
        raw_tags = getattr(audio, "tags", None)
        if not raw_tags:
            return tags

        try:
            items = raw_tags.items()
        except Exception:
            return tags

        for key, value in items:
            raw_key = str(key).strip().lower()
            normalized_key = self._normalize_tag_key(raw_key)
            try:
                tag_value = self._coerce_tag_value(value)
            except Exception:
                tag_value = ""
            tag_text = str(tag_value).strip()
            if not tag_text:
                continue
            tags.setdefault(raw_key, tag_text)
            tags[normalized_key] = tag_text

        return tags

    def _normalize_tag_key(self, key: str) -> str:
        value = str(key or "").strip().lower()
        if not value:
            return value
        for canonical, aliases in self.TAG_KEY_ALIASES.items():
            if value == canonical or value in aliases:
                return canonical
        return value

    def _coerce_tag_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            if not value:
                return ""
            return self._coerce_tag_value(value[0])
        if isinstance(value, tuple):
            if not value:
                return ""
            return self._coerce_tag_value(value[0])
        if hasattr(value, "text"):
            return self._coerce_tag_value(getattr(value, "text", []))
        if hasattr(value, "value"):
            return self._coerce_tag_value(getattr(value, "value", ""))
        return str(value).strip()

    def upsert_metadata(self, metadata: AudioMetadata) -> bool:
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    record = metadata.to_record()
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO audio_tracks (
                            file_path, file_size, mtime, extension, codec, duration,
                            bitrate, sample_rate, channels, bit_depth, lossless,
                            artist, album_artist, title, album, track_number,
                            disc_number, year, genre, tags, source, error, indexed_at
                        ) VALUES (
                            :file_path, :file_size, :mtime, :extension, :codec, :duration,
                            :bitrate, :sample_rate, :channels, :bit_depth, :lossless,
                            :artist, :album_artist, :title, :album, :track_number,
                            :disc_number, :year, :genre, :tags, :source, :error, :indexed_at
                        )
                        """,
                        {
                            **record,
                            "lossless": 1 if metadata.lossless else 0,
                        },
                    )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def get_metadata(self, file_path: Path) -> Optional[Dict[str, Any]]:
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    row = conn.execute(
                        """
                        SELECT t.*, COALESCE(r.review_status, '') AS review_status,
                               COALESCE(r.reviewed_at, '') AS reviewed_at
                        FROM audio_tracks t
                        LEFT JOIN audio_track_review_state r ON r.file_path = t.file_path
                        WHERE t.file_path = ?
                        """,
                        (str(Path(file_path)),),
                    ).fetchone()
                    if not row:
                        return None
                    data = dict(row)
                    tags = data.get("tags") or "{}"
                    try:
                        data["tags"] = json.loads(tags)
                    except Exception:
                        data["tags"] = {}
                    data["lossless"] = bool(data.get("lossless"))
                    return data
                finally:
                    conn.close()
        except Exception:
            return None

    def find_missing_metadata(self, limit: int = 200) -> list[Dict[str, Any]]:
        """Retorna pistas con tags incompletos para enriquecimiento posterior."""
        query = """
            SELECT t.*, COALESCE(r.review_status, '') AS review_status,
                   COALESCE(r.reviewed_at, '') AS reviewed_at
            FROM audio_tracks t
            LEFT JOIN audio_track_review_state r ON r.file_path = t.file_path
            WHERE (
                COALESCE(title, '') = ''
                OR COALESCE(artist, '') = ''
                OR COALESCE(album, '') = ''
            )
              AND COALESCE(r.review_status, '') NOT IN ('complete', 'no_match', 'applied')
            ORDER BY indexed_at DESC
            LIMIT ?
        """
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    rows = conn.execute(query, (limit,)).fetchall()
                    results = []
                    for row in rows:
                        item = dict(row)
                        try:
                            item["tags"] = json.loads(item.get("tags") or "{}")
                        except Exception:
                            item["tags"] = {}
                        results.append(item)
                    return results
                finally:
                    conn.close()
        except Exception:
            return []

    def update_track_tags(
        self,
        file_path: Path,
        updates: Dict[str, Any],
        cover_art: bytes | None = None,
        cover_mime: str | None = None,
    ) -> bool:
        """Escribe tags en el archivo y reindexa metadatos persistidos."""
        file_path = Path(file_path)
        normalized_updates = self._normalize_updates_for_write(updates)
        if not self._write_file_tags(
            file_path,
            normalized_updates,
            cover_art=cover_art,
            cover_mime=cover_mime,
        ):
            return False
        try:
            metadata = self.extract_metadata(file_path)
            if metadata.error == "mutagen_no_disponible":
                return False
            return self.upsert_metadata(metadata)
        except Exception:
            return False

    def get_cover_art_bytes(self, file_path: Path) -> bytes | None:
        file_path = Path(file_path)
        try:
            from mutagen import File as MutagenFile
        except Exception:
            return None

        try:
            audio = MutagenFile(str(file_path), easy=False)
            if audio is None:
                return None

            pictures = getattr(audio, "pictures", None) or []
            for picture in pictures:
                data = getattr(picture, "data", None)
                if data:
                    return bytes(data)

            tags = getattr(audio, "tags", None)
            if not tags:
                return None

            getall = getattr(tags, "getall", None)
            if callable(getall):
                for frame in getall("APIC"):
                    data = getattr(frame, "data", None)
                    if data:
                        return bytes(data)

            try:
                covr = tags.get("covr")
            except Exception:
                covr = None
            if covr:
                first = covr[0] if isinstance(covr, (list, tuple)) else covr
                try:
                    return bytes(first)
                except Exception:
                    pass

            try:
                metadata_picture = tags.get("metadata_block_picture")
            except Exception:
                metadata_picture = None
            if metadata_picture:
                values = (
                    metadata_picture
                    if isinstance(metadata_picture, (list, tuple))
                    else [metadata_picture]
                )
                for item in values:
                    try:
                        from mutagen.flac import Picture

                        payload = base64.b64decode(item)
                        return bytes(Picture(payload).data)
                    except Exception:
                        continue

            return None
        except Exception:
            return None

    def get_track_review_status(self, file_path: Path) -> str:
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    row = conn.execute(
                        "SELECT review_status FROM audio_track_review_state WHERE file_path = ?",
                        (str(Path(file_path)),),
                    ).fetchone()
                    return str(row[0] or "") if row else ""
                finally:
                    conn.close()
        except Exception:
            return ""

    def set_track_review_status(self, file_path: Path, status: str) -> bool:
        path = str(Path(file_path))
        normalized = str(status or "").strip().lower()
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    if not normalized:
                        conn.execute(
                            "DELETE FROM audio_track_review_state WHERE file_path = ?",
                            (path,),
                        )
                    else:
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO audio_track_review_state
                            (file_path, review_status, reviewed_at)
                            VALUES (?, ?, ?)
                            """,
                            (
                                path,
                                normalized,
                                datetime.now().isoformat(timespec="seconds"),
                            ),
                        )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def get_lookup_cache(
        self, file_path: Path, cache_key: str | None = None
    ) -> Optional[Dict[str, Any]]:
        path = str(Path(file_path))
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    if cache_key:
                        row = conn.execute(
                            """
                            SELECT result_json, cover_art, cache_key, updated_at
                            FROM audio_lookup_cache
                            WHERE file_path = ? AND cache_key = ?
                            """,
                            (path, str(cache_key)),
                        ).fetchone()
                    else:
                        row = conn.execute(
                            """
                            SELECT result_json, cover_art, cache_key, updated_at
                            FROM audio_lookup_cache
                            WHERE file_path = ?
                            """,
                            (path,),
                        ).fetchone()
                    if not row:
                        return None
                    data = json.loads(str(row["result_json"] or "{}"))
                    data["cache_key"] = str(
                        row["cache_key"] or data.get("cache_key") or ""
                    )
                    data["cache_updated_at"] = str(row["updated_at"] or "")
                    cover_art = row["cover_art"]
                    if cover_art:
                        data["cached_cover_art"] = bytes(cover_art)
                    return data
                finally:
                    conn.close()
        except Exception:
            return None

    def set_lookup_cache(
        self,
        file_path: Path,
        cache_key: str,
        result: Dict[str, Any],
        cover_art: bytes | None = None,
    ) -> bool:
        path = str(Path(file_path))
        serialized = dict(result or {})
        serialized.pop("cached_cover_art", None)
        serialized["cache_key"] = str(cache_key or "")
        try:
            payload = json.dumps(serialized, ensure_ascii=False)
        except Exception:
            return False
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO audio_lookup_cache
                        (file_path, cache_key, result_json, cover_art, updated_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            path,
                            str(cache_key or ""),
                            payload,
                            sqlite3.Binary(cover_art) if cover_art else None,
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def update_lookup_cache_cover_art(
        self, file_path: Path, cache_key: str, cover_art: bytes
    ) -> bool:
        path = str(Path(file_path))
        if not cover_art:
            return False
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute(
                        """
                        UPDATE audio_lookup_cache
                        SET cover_art = ?, updated_at = ?
                        WHERE file_path = ? AND cache_key = ?
                        """,
                        (
                            sqlite3.Binary(cover_art),
                            datetime.now().isoformat(timespec="seconds"),
                            path,
                            str(cache_key or ""),
                        ),
                    )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def clear_lookup_cache(self, file_path: Path) -> bool:
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute(
                        "DELETE FROM audio_lookup_cache WHERE file_path = ?",
                        (str(Path(file_path)),),
                    )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def _normalize_updates_for_write(self, updates: Dict[str, Any]) -> Dict[str, str]:
        normalized: Dict[str, str] = {}
        for key, value in (updates or {}).items():
            normalized_key = self._normalize_tag_key(str(key).replace("_", " "))
            if normalized_key == "album artist":
                normalized_key = "albumartist"
            if normalized_key not in self.WRITABLE_TAG_KEYS:
                normalized_key = self._normalize_tag_key(str(key))
            if normalized_key == "year":
                normalized_key = "date"
            if normalized_key not in self.WRITABLE_TAG_KEYS:
                continue
            normalized[normalized_key] = str(value or "").strip()
        return normalized

    def _write_file_tags(
        self,
        file_path: Path,
        updates: Dict[str, str],
        cover_art: bytes | None = None,
        cover_mime: str | None = None,
    ) -> bool:
        if not updates and cover_art is None:
            return True
        text_ok = True
        if updates:
            text_ok = self._write_text_tags(file_path, updates)
        cover_ok = True
        if cover_art is not None:
            cover_ok = self._write_cover_art(file_path, cover_art, cover_mime)
        return text_ok and cover_ok

    def _write_text_tags(self, file_path: Path, updates: Dict[str, str]) -> bool:
        try:
            from mutagen import File as MutagenFile
        except Exception:
            return False

        try:
            audio = MutagenFile(str(file_path), easy=True)
            if audio is None:
                return False
            if getattr(audio, "tags", None) is None:
                try:
                    audio.add_tags()
                except Exception:
                    pass
            for key, value in updates.items():
                if value:
                    audio[key] = [value]
                else:
                    try:
                        if key in audio:
                            del audio[key]
                    except Exception:
                        pass
            audio.save()
            return True
        except Exception:
            return False

    def _write_cover_art(
        self, file_path: Path, cover_art: bytes, cover_mime: str | None = None
    ) -> bool:
        if not cover_art:
            return True
        try:
            from mutagen import File as MutagenFile
            from mutagen.flac import Picture
            from mutagen.id3 import APIC
            from mutagen.mp4 import MP4Cover
        except Exception:
            return False

        mime = self._detect_cover_mime(cover_art, cover_mime)
        try:
            audio = MutagenFile(str(file_path), easy=False)
            if audio is None:
                return False
            if getattr(audio, "tags", None) is None:
                try:
                    audio.add_tags()
                except Exception:
                    pass

            suffix = file_path.suffix.lower()
            class_name = audio.__class__.__name__.lower()

            if suffix in {".mp3", ".wav", ".aiff", ".aif"} or any(
                token in class_name for token in ("mp3", "wave", "aiff")
            ):
                tags = getattr(audio, "tags", None)
                if tags is None:
                    return False
                delall = getattr(tags, "delall", None)
                if callable(delall):
                    delall("APIC")
                else:
                    for key in list(getattr(tags, "keys", lambda: [])()):
                        if str(key).startswith("APIC"):
                            del tags[key]
                tags.add(
                    APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_art)
                )
                audio.save()
                return True

            if suffix in {".flac"} or hasattr(audio, "pictures"):
                picture = Picture()
                picture.data = cover_art
                picture.type = 3
                picture.mime = mime
                try:
                    audio.clear_pictures()
                except Exception:
                    pass
                audio.add_picture(picture)
                audio.save()
                return True

            if suffix in {".m4a", ".mp4", ".alac"} or class_name.startswith("mp4"):
                image_format = (
                    MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
                )
                audio["covr"] = [MP4Cover(cover_art, imageformat=image_format)]
                audio.save()
                return True

            if suffix in {".ogg"} or "ogg" in class_name:
                picture = Picture()
                picture.data = cover_art
                picture.type = 3
                picture.mime = mime
                encoded = base64.b64encode(picture.write()).decode("ascii")
                audio["metadata_block_picture"] = [encoded]
                audio.save()
                return True

            return False
        except Exception:
            return False

    def _detect_cover_mime(self, cover_art: bytes, fallback: str | None = None) -> str:
        fallback_mime = str(fallback or "").strip().lower()
        if fallback_mime in {"image/jpeg", "image/jpg", "image/png"}:
            return "image/jpeg" if fallback_mime == "image/jpg" else fallback_mime
        if cover_art.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if cover_art.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        return "image/jpeg"

    def list_tracks(self, limit: Optional[int] = 500) -> list[Dict[str, Any]]:
        """Lista las pistas indexadas (``limit`` None o 0 = todas)."""
        query = """
            SELECT t.*, COALESCE(r.review_status, '') AS review_status,
                   COALESCE(r.reviewed_at, '') AS reviewed_at
            FROM audio_tracks t
            LEFT JOIN audio_track_review_state r ON r.file_path = t.file_path
            ORDER BY indexed_at DESC
            LIMIT ?
        """
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    rows = conn.execute(query, (limit if limit and limit > 0 else -1,)).fetchall()
                    results = []
                    for row in rows:
                        item = dict(row)
                        try:
                            item["tags"] = json.loads(item.get("tags") or "{}")
                        except Exception:
                            item["tags"] = {}
                        results.append(item)
                    return results
                finally:
                    conn.close()
        except Exception:
            return []

    def remove_track(self, file_path: Path) -> bool:
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    conn.execute(
                        "DELETE FROM audio_tracks WHERE file_path = ?",
                        (str(Path(file_path)),),
                    )
                    conn.execute(
                        "DELETE FROM audio_track_review_state WHERE file_path = ?",
                        (str(Path(file_path)),),
                    )
                    conn.execute(
                        "DELETE FROM audio_lookup_cache WHERE file_path = ?",
                        (str(Path(file_path)),),
                    )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def clean_track_title(self, title: str) -> str:
        """Normaliza titulos basura de descargas antiguas."""
        value = str(title or "").strip()
        if not value:
            return value
        value = re.sub(r"(?i)\.(mp3|flac|wav|m4a|aac|ogg|wma)$", "", value)
        value = re.sub(
            r"(?i)https?://\S+|www\.\S+|\([^)]*\b(?:www|http|https|com|net|org|es|info|blog|download)\b[^)]*\)",
            " ",
            value,
        )
        value = re.sub(r"(?i)(?:_title_|_pista_|-title-|-pista-)+", " ", value)
        value = re.sub(r"(?i)(?:track|title|pista)[_\- ]*\d*", "", value)
        value = re.sub(r"(?i)^\s*\d{1,3}[\s._-]+", "", value)
        value = re.sub(r"(?i)[\s._-]+\d{1,3}\s*$", "", value)
        value = re.sub(r"[_\-]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip(" _-.")
        value = re.sub(r"(?i)\b(?:by|from)\b\s+.*$", "", value).strip()
        return value or str(title).strip()

    def clean_track_filename(self, name: str) -> str:
        """Limpia un nombre de archivo sin extension para que sea renombrable."""
        value = str(name or "").strip()
        if not value:
            return ""
        value = re.sub(
            r"(?i)\.(mp3|flac|wav|m4a|aac|ogg|wma|alac|aiff|aif)$", "", value
        )
        value = re.sub(r'[<>:"/\\|?*]+', " ", value)
        value = re.sub(
            r"(?i)https?://\S+|www\.\S+|\([^)]*\b(?:www|http|https|com|net|org|es|info|blog|download)\b[^)]*\)",
            " ",
            value,
        )
        value = re.sub(r"(?i)(?:_title_|_pista_|-title-|-pista-)+", " ", value)
        value = re.sub(r"(?i)^\s*\d{1,3}[\s._:-]+", "", value)
        value = re.sub(r"(?i)[\s._-]+\d{1,3}\s*$", "", value)
        value = re.sub(r"[_\-]+", " ", value)
        value = re.sub(r"\s+", " ", value).strip(" .")
        if not value:
            return ""
        if value.upper() in self.RESERVED_FILENAMES:
            value = f"{value}_"
        return value

    def rename_track_file(self, old_path: Path, new_name: str) -> bool:
        """Renombra el archivo y sincroniza el indice local."""
        old_path = Path(old_path)
        new_name = Path(str(new_name or "")).name
        if not new_name:
            return False
        new_path = old_path.parent / new_name
        if old_path == new_path:
            return True
        if not old_path.exists() or new_path.exists():
            return False
        try:
            old_path.rename(new_path)
            with self.lock:
                conn = self._get_connection()
                try:
                    lookup_row = conn.execute(
                        "SELECT result_json FROM audio_lookup_cache WHERE file_path = ?",
                        (str(old_path),),
                    ).fetchone()
                    lookup_payload = None
                    if lookup_row:
                        try:
                            lookup_payload = json.loads(
                                str(lookup_row["result_json"] or "{}")
                            )
                        except Exception:
                            lookup_payload = None
                    if isinstance(lookup_payload, dict):
                        lookup_payload["file_path"] = str(new_path)
                        local_metadata = dict(
                            lookup_payload.get("local_metadata") or {}
                        )
                        if local_metadata:
                            local_metadata["file_path"] = str(new_path)
                            lookup_payload["local_metadata"] = local_metadata
                    conn.execute(
                        "UPDATE audio_tracks SET file_path = ? WHERE file_path = ?",
                        (str(new_path), str(old_path)),
                    )
                    conn.execute(
                        "UPDATE audio_track_review_state SET file_path = ? WHERE file_path = ?",
                        (str(new_path), str(old_path)),
                    )
                    conn.execute(
                        "UPDATE audio_lookup_cache SET file_path = ?, result_json = COALESCE(?, result_json) WHERE file_path = ?",
                        (
                            str(new_path),
                            json.dumps(lookup_payload, ensure_ascii=False)
                            if isinstance(lookup_payload, dict)
                            else None,
                            str(old_path),
                        ),
                    )
                    conn.commit()
                    return True
                finally:
                    conn.close()
        except Exception:
            return False

    def iter_audio_files(self, folder_path: Path, recursive: bool = True, cancel_event=None):
        """Archivos de audio de la carpeta, sin carpetas ocultas/cuarentena/sistema."""
        from src.core.duplicate_finder import walk_files

        for entry in walk_files(Path(folder_path), recursive, cancel_event=cancel_event):
            if self.is_audio_file(entry.path):
                yield entry

    def _row_to_metadata(self, row: Dict[str, Any]) -> AudioMetadata:
        tags = row.get("tags") or {}
        if isinstance(tags, str):
            try:
                tags = json.loads(tags or "{}")
            except ValueError:
                tags = {}
        return AudioMetadata(
            file_path=str(row.get("file_path") or ""),
            file_size=int(row.get("file_size") or 0),
            mtime=float(row.get("mtime") or 0.0),
            extension=str(row.get("extension") or ""),
            codec=str(row.get("codec") or "unknown"),
            duration=row.get("duration"),
            bitrate=row.get("bitrate"),
            sample_rate=row.get("sample_rate"),
            channels=row.get("channels"),
            bit_depth=row.get("bit_depth"),
            lossless=bool(row.get("lossless")),
            artist=str(row.get("artist") or ""),
            album_artist=str(row.get("album_artist") or ""),
            title=str(row.get("title") or ""),
            album=str(row.get("album") or ""),
            track_number=str(row.get("track_number") or ""),
            disc_number=str(row.get("disc_number") or ""),
            year=str(row.get("year") or ""),
            genre=str(row.get("genre") or ""),
            tags=dict(tags),
            source=str(row.get("source") or "local"),
            error=str(row.get("error") or ""),
        )

    def _load_rows(self, file_paths: List[str]) -> Dict[str, Dict[str, Any]]:
        rows: Dict[str, Dict[str, Any]] = {}
        if not file_paths:
            return rows
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    for start in range(0, len(file_paths), 500):
                        chunk = file_paths[start:start + 500]
                        placeholders = ",".join("?" * len(chunk))
                        for row in conn.execute(
                            f"SELECT * FROM audio_tracks WHERE file_path IN ({placeholders})", chunk
                        ).fetchall():
                            rows[row["file_path"]] = dict(row)
                finally:
                    conn.close()
        except sqlite3.Error as exc:
            debug(f"No se pudo leer el índice de audio: {exc}")
        return rows

    def upsert_many(self, items: Iterable[AudioMetadata]) -> int:
        """Guarda varias pistas en una sola transacción."""
        records = []
        for metadata in items:
            record = metadata.to_record()
            record["lossless"] = 1 if metadata.lossless else 0
            records.append(record)
        if not records:
            return 0
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    with conn:
                        conn.executemany(
                            """
                            INSERT OR REPLACE INTO audio_tracks (
                                file_path, file_size, mtime, extension, codec, duration,
                                bitrate, sample_rate, channels, bit_depth, lossless,
                                artist, album_artist, title, album, track_number,
                                disc_number, year, genre, tags, source, error, indexed_at
                            ) VALUES (
                                :file_path, :file_size, :mtime, :extension, :codec, :duration,
                                :bitrate, :sample_rate, :channels, :bit_depth, :lossless,
                                :artist, :album_artist, :title, :album, :track_number,
                                :disc_number, :year, :genre, :tags, :source, :error, :indexed_at
                            )
                            """,
                            records,
                        )
                finally:
                    conn.close()
            return len(records)
        except sqlite3.Error as exc:
            debug(f"No se pudo guardar el índice de audio: {exc}")
            return 0

    def index_folder_detailed(
        self,
        folder_path: Path,
        recursive: bool = True,
        cancel_event=None,
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> List[AudioMetadata]:
        """Indexa la carpeta y devuelve los metadatos de cada pista.

        Cada pista se analiza con mutagen una sola vez; las que no cambiaron
        (mismo tamaño y mtime) se reutilizan del índice sin abrir el archivo.
        """
        folder_path = Path(folder_path)
        if not folder_path.exists():
            return []
        entries = list(self.iter_audio_files(folder_path, recursive, cancel_event))
        known = self._load_rows([str(entry.path) for entry in entries])
        results: List[AudioMetadata] = []
        pending: List[AudioMetadata] = []
        total = len(entries)
        for index, entry in enumerate(entries, start=1):
            if cancel_event is not None and cancel_event.is_set():
                from src.core.duplicate_finder import ScanCancelled

                self.upsert_many(pending)
                raise ScanCancelled()
            row = known.get(str(entry.path))
            if (
                row
                and int(row.get("file_size") or -1) == entry.size
                and float(row.get("mtime") or -1) == entry.mtime
                and str(row.get("error") or "") != "mutagen_no_disponible"
            ):
                results.append(self._row_to_metadata(row))
            else:
                meta = self.extract_metadata(entry.path)
                results.append(meta)
                if meta.error != "mutagen_no_disponible":
                    pending.append(meta)
                if len(pending) >= 200:
                    self.upsert_many(pending)
                    pending = []
            if progress and (index % 25 == 0 or index == total):
                progress(index, total)
        self.upsert_many(pending)
        return results

    def index_folder(self, folder_path: Path, recursive: bool = True) -> int:
        """Indexa todos los archivos de audio de una carpeta (devuelve cuántos)."""
        return sum(
            1
            for meta in self.index_folder_detailed(folder_path, recursive=recursive)
            if meta.error != "mutagen_no_disponible"
        )

    def count_tracks(self) -> int:
        try:
            with self.lock:
                conn = self._get_connection()
                try:
                    return int(conn.execute("SELECT COUNT(*) FROM audio_tracks").fetchone()[0])
                finally:
                    conn.close()
        except sqlite3.Error:
            return 0


audio_metadata_service = AudioMetadataService()
