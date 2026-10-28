#!/usr/bin/env python3
"""Constantes de layout para la vista musical."""

LIBRARY_SELECT_COLUMN = 0
LIBRARY_FILE_COLUMN = 1

LIBRARY_COLUMN_LABELS = [
    "",
    "Archivo",
    "Estado",
    "Título",
    "Artista",
    "Álbum",
    "Artista del álbum",
    "Año",
    "Género",
    "Codec",
    "Calidad",
    "Duración",
    "Fuente online",
    "Confianza",
    "Diagnóstico",
    "Título sugerido",
    "Artista sugerido",
    "Álbum sugerido",
    "Año sugerido",
]

LIBRARY_COLUMN_DEFAULT_ORDER = [
    0,
    2,
    12,
    13,
    1,
    11,
    3,
    4,
    5,
    7,
    8,
    9,
    10,
    6,
    14,
    15,
    16,
    17,
    18,
]

LIBRARY_DEFAULT_VISIBLE_COLUMNS = [0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13]

LIBRARY_COLUMN_DEFAULTS = [
    44,
    320,
    120,
    240,
    240,
    220,
    200,
    90,
    130,
    120,
    150,
    90,
    110,
    90,
    160,
    220,
    220,
    220,
    90,
]

LIBRARY_SPLITTER_DEFAULT_SIZES = [900, 320]

DUPLICATES_COLUMN_LABELS = [
    "Decision",
    "Archivo",
    "Título",
    "Artista",
    "Álbum",
    "Duración",
    "Codec",
    "Bitrate",
    "Calidad",
    "Tamaño",
    "Ruta",
]

LOOKUP_REASON_LABELS = {
    "": "",
    "ok": "OK",
    "mixed": "mixto",
    "no_candidates": "sin candidatos",
    "missing_api_key": "sin clave AcoustID",
    "invalid_client_key": "clave cliente AcoustID invalida",
    "fingerprint_unavailable": "sin fingerprint",
    "invalid_fingerprint_payload": "fingerprint no válido",
    "lookup_failed": "fallo de consulta",
    "disabled_or_missing_token": "Discogs desactivado o sin token",
    "not_attempted": "no intentado",
}
