#!/usr/bin/env python3
"""
Configuración de la Aplicación
Maneja las preferencias del usuario como tema y tamaño de fuente
"""

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any, Optional

from src.gui.music_duplicates_constants import (
    LIBRARY_COLUMN_DEFAULT_ORDER,
    LIBRARY_COLUMN_DEFAULTS,
    LIBRARY_DEFAULT_VISIBLE_COLUMNS,
    LIBRARY_SPLITTER_DEFAULT_SIZES,
)


class AppConfig:
    """Gestor de configuración de la aplicación"""

    DEFAULT_CONFIG = {
        "interface": {
            "font_size": 13,
            "theme": "🌞 Claro Elegante",  # Tema por defecto (nombre unificado con themes.py)
            "theme_mode": "system",
            "accent_color": "#0078D4",
            "density": "comfortable",
            "ui_advanced_mode": False,
        },
        "categories": {"auto_save": True, "backup_enabled": True},
        "analysis": {
            "min_similarity": 70,
            "auto_analyze": True,
            "min_file_size_mb": 0,
            "ignored_extensions": [],
            "ignored_paths": [],
            "protected_paths": [],
            "favorite_paths": [],
            "recent_paths": [],
            "conflict_policy": "rename",
        },
        "duplicates": {"ignored_hashes": [], "preferred_originals": {}},
        "audio": {
            "enabled": True,
            "library_roots": [],
            "last_folder": "",
            "recursive": True,
            "preview_playback_rate": 1.0,
            "library_column_widths": list(LIBRARY_COLUMN_DEFAULTS),
            "library_column_order": list(LIBRARY_COLUMN_DEFAULT_ORDER),
            "library_visible_columns": list(LIBRARY_DEFAULT_VISIBLE_COLUMNS),
            "library_splitter_sizes": list(LIBRARY_SPLITTER_DEFAULT_SIZES),
            "library_header_state": "",
            "prefer_lossless": True,
            "allow_online_metadata": False,
            "discogs_enabled": False,
            "discogs_token": "",
            "duplicate_policy": "review",
            "organization_template": "MUSICA/{album_artist}/{year} - {album}/{disc_number}-{track_number} - {title}",
            "acoustid_api_key": "",
        },
        "health": {
            "temperature": {"cool_min": 40, "moderate": 65, "high": 75, "critical": 85},
            "tbw_per_tb": 150,  # TB autorizados por TB de capacidad
            "tbw_bands": {"medium": 0.5, "high": 0.8},
            "tbw_by_type": {"nvme": 150, "ata": 150, "hdd": 0},
            "degrade_on_smart_fail": True,
            "hours_bands": {"moderate": 10000, "high": 30000, "very_high": 50000},
            "cycles_bands": {"moderate": 2000, "high": 10000},
            "weights": {"temp": 0.35, "tbw": 0.35, "hours": 0.20, "cycles": 0.10},
        },
    }

    def __init__(self, config_file: str = "app_config.json"):
        self.config_file = Path(config_file)
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """Carga la configuración desde el archivo"""
        try:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
                    # Fusionar con configuración por defecto
                    return self.merge_configs(self.DEFAULT_CONFIG, loaded_config)
            else:
                # ⚠️ CRÍTICO: NO intentar escribir archivo durante __init__ en .exe
                # Solo devolver configuración por defecto - el archivo se creará cuando se guarde
                return deepcopy(self.DEFAULT_CONFIG)
        except Exception as e:
            # ⚠️ CRÍTICO: En .exe, los archivos pueden no estar disponibles aún
            # No usar logger aquí porque puede no estar inicializado
            try:
                from .logger import error

                error(f"Error cargando configuración: {e}")
            except Exception:
                pass  # Logger no disponible - continuar con defaults
            return deepcopy(self.DEFAULT_CONFIG)

    def merge_configs(self, default: Dict, loaded: Dict) -> Dict:
        """Fusiona configuración por defecto con la cargada"""
        merged = deepcopy(default)

        for key, value in loaded.items():
            if (
                key in merged
                and isinstance(value, dict)
                and isinstance(merged[key], dict)
            ):
                merged[key] = self.merge_configs(merged[key], value)
            else:
                merged[key] = value

        return merged

    def save_config(self, config: Optional[Dict] = None) -> bool:
        """Guarda la configuración en el archivo"""
        temporary_path = None
        try:
            if config is None:
                config = self.config

            # Crear directorio si no existe
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.config_file.parent,
                prefix=f".{self.config_file.name}.", suffix=".tmp", delete=False,
            ) as f:
                temporary_path = Path(f.name)
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, self.config_file)
            return True
        except Exception as e:
            from .logger import error

            error(f"Error guardando configuración: {e}")
            return False
        finally:
            if temporary_path is not None and temporary_path.exists():
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def get(self, key_path: str, default: Any = None) -> Any:
        """Obtiene un valor de configuración por ruta de claves"""
        try:
            keys = key_path.split(".")
            value = self.config

            for key in keys:
                if isinstance(value, dict) and key in value:
                    value = value[key]
                else:
                    return default

            return value
        except Exception:
            return default

    def set(self, key_path: str, value: Any) -> bool:
        """Establece un valor de configuración por ruta de claves"""
        try:
            latest_config = self.load_config()
            keys = key_path.split(".")
            config = latest_config

            # Navegar hasta el penúltimo nivel
            for key in keys[:-1]:
                if key not in config:
                    config[key] = {}
                config = config[key]

            # Establecer el valor
            config[keys[-1]] = value

            # Guardar configuración
            if not self.save_config(latest_config):
                return False
            self.config = latest_config
            return True
        except Exception as e:
            from .logger import error

            error(f"Error estableciendo configuración: {e}")
            return False

    def get_font_size(self) -> int:
        """Obtiene el tamaño de fuente configurado"""
        return self.get("interface.font_size", 13)

    def set_font_size(self, size: int) -> bool:
        """Establece el tamaño de fuente"""
        return self.set("interface.font_size", size)

    def get_theme(self) -> str:
        """Obtiene el tema configurado"""
        return self.get("interface.theme", "🌞 Claro Elegante")

    def set_theme(self, theme: str) -> bool:
        """Establece el tema"""
        return self.set("interface.theme", theme)

    def get_theme_mode(self) -> str:
        """Obtiene el modo visual Fluent: light, dark o system."""
        mode = str(self.get("interface.theme_mode", "")).lower()
        if mode in {"light", "dark", "system"}:
            return mode

        legacy_theme = self.get_theme().lower()
        return "dark" if "oscuro" in legacy_theme else "light"

    def set_theme_mode(self, mode: str) -> bool:
        """Guarda el modo visual Fluent normalizado."""
        normalized = str(mode).lower()
        if normalized not in {"light", "dark", "system"}:
            normalized = "system"
        return self.set("interface.theme_mode", normalized)

    def get_accent_color(self) -> str:
        """Obtiene el color de acento de la interfaz."""
        return str(self.get("interface.accent_color", "#0078D4"))

    def set_accent_color(self, color: str) -> bool:
        """Guarda el color de acento de la interfaz."""
        color = str(color).strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            return False
        return self.set("interface.accent_color", color.upper())

    def save_appearance(self, mode: str, density: str, font_size: int, accent: str) -> bool:
        """Valida y persiste toda la apariencia en una sola escritura."""
        accent = str(accent).strip()
        if (mode not in {"system", "light", "dark"}
                or density not in {"comfortable", "compact"}
                or font_size not in {11, 13, 15}
                or not re.fullmatch(r"#[0-9a-fA-F]{6}", accent)):
            return False
        updated = self.load_config()
        updated["interface"].update(
            theme_mode=mode, density=density, font_size=font_size,
            accent_color=accent.upper(),
        )
        if not self.save_config(updated):
            return False
        self.config = updated
        return True

    def get_interface_density(self) -> str:
        """Obtiene la densidad visual."""
        density = str(self.get("interface.density", "comfortable")).lower()
        return density if density in {"comfortable", "compact"} else "comfortable"

    def set_interface_density(self, density: str) -> bool:
        """Guarda la densidad visual."""
        normalized = str(density).lower()
        if normalized not in {"comfortable", "compact"}:
            normalized = "comfortable"
        return self.set("interface.density", normalized)

    def get_ui_advanced_mode(self) -> bool:
        """Indica si la UI debe abrirse en modo avanzado."""
        return bool(self.get("interface.ui_advanced_mode", False))

    def set_ui_advanced_mode(self, enabled: bool) -> bool:
        """Persistencia del modo básico/avanzado."""
        return self.set("interface.ui_advanced_mode", bool(enabled))

    def get_min_similarity(self) -> int:
        """Obtiene el porcentaje mínimo de similitud"""
        return self.get("analysis.min_similarity", 70)

    def set_min_similarity(self, percentage: int) -> bool:
        """Establece el porcentaje mínimo de similitud"""
        return self.set("analysis.min_similarity", percentage)

    def get_min_file_size_mb(self) -> int:
        """Obtiene el tamaño mínimo de archivo para análisis."""
        return self.get("analysis.min_file_size_mb", 0)

    def set_min_file_size_mb(self, size_mb: int) -> bool:
        """Establece el tamaño mínimo de archivo para análisis."""
        return self.set("analysis.min_file_size_mb", max(0, int(size_mb)))

    def get_auto_analyze(self) -> bool:
        """Indica si el analisis automatico esta activado."""
        return bool(self.get("analysis.auto_analyze", True))

    def set_auto_analyze(self, enabled: bool) -> bool:
        """Activa o desactiva el analisis automatico."""
        return self.set("analysis.auto_analyze", bool(enabled))

    def get_ignored_extensions(self) -> list[str]:
        """Retorna extensiones ignoradas."""
        return list(self.get("analysis.ignored_extensions", []))

    def set_ignored_extensions(self, extensions: list[str]) -> bool:
        """Guarda extensiones ignoradas normalizadas."""
        normalized = []
        for ext in extensions:
            ext = str(ext).strip().lower()
            if not ext:
                continue
            normalized.append(ext if ext.startswith(".") else f".{ext}")
        return self.set("analysis.ignored_extensions", sorted(set(normalized)))

    def get_ignored_paths(self) -> list[str]:
        """Retorna rutas ignoradas."""
        return list(self.get("analysis.ignored_paths", []))

    def set_ignored_paths(self, paths: list[str]) -> bool:
        """Guarda rutas ignoradas."""
        return self.set("analysis.ignored_paths", self._clean_path_list(paths))

    def get_protected_paths(self) -> list[str]:
        """Retorna rutas protegidas."""
        return list(self.get("analysis.protected_paths", []))

    def set_protected_paths(self, paths: list[str]) -> bool:
        """Guarda rutas protegidas."""
        return self.set("analysis.protected_paths", self._clean_path_list(paths))

    def get_favorite_paths(self) -> list[str]:
        """Retorna rutas favoritas."""
        return list(self.get("analysis.favorite_paths", []))

    def add_favorite_path(self, path: str) -> bool:
        """Añade una ruta a favoritos."""
        favorites = self.get_favorite_paths()
        normalized = self._normalize_path(path)
        if normalized and normalized not in favorites:
            favorites.append(normalized)
        return self.set("analysis.favorite_paths", favorites)

    def remove_favorite_path(self, path: str) -> bool:
        """Elimina una ruta de favoritos."""
        normalized = self._normalize_path(path)
        favorites = [item for item in self.get_favorite_paths() if item != normalized]
        return self.set("analysis.favorite_paths", favorites)

    def get_recent_paths(self) -> list[str]:
        """Retorna rutas recientes."""
        return list(self.get("analysis.recent_paths", []))

    def push_recent_path(self, path: str, limit: int = 8) -> bool:
        """Inserta una ruta en el historial reciente."""
        normalized = self._normalize_path(path)
        if not normalized:
            return False
        recents = [item for item in self.get_recent_paths() if item != normalized]
        recents.insert(0, normalized)
        return self.set("analysis.recent_paths", recents[:limit])

    def get_ignored_duplicate_hashes(self) -> list[str]:
        """Retorna hashes ignorados de duplicados."""
        return list(self.get("duplicates.ignored_hashes", []))

    def set_ignored_duplicate_hashes(self, hashes: list[str]) -> bool:
        """Guarda hashes ignorados de duplicados."""
        cleaned = [
            str(hash_value).strip() for hash_value in hashes if str(hash_value).strip()
        ]
        return self.set("duplicates.ignored_hashes", sorted(set(cleaned)))

    def get_preferred_originals(self) -> Dict[str, str]:
        """Retorna archivo preferido por hash de duplicados."""
        return dict(self.get("duplicates.preferred_originals", {}))

    def set_preferred_original(self, hash_value: str, path: str) -> bool:
        """Guarda el original preferido para un grupo de duplicados."""
        originals = self.get_preferred_originals()
        originals[str(hash_value)] = str(path)
        return self.set("duplicates.preferred_originals", originals)

    def remove_preferred_original(self, hash_value: str) -> bool:
        """Elimina la preferencia de original para un grupo."""
        originals = self.get_preferred_originals()
        originals.pop(str(hash_value), None)
        return self.set("duplicates.preferred_originals", originals)

    def get_audio_settings(self) -> Dict[str, Any]:
        """Retorna la configuracion de audio."""
        return dict(self.get("audio", {}))

    def set_audio_settings(self, settings: Dict[str, Any]) -> bool:
        """Actualiza la configuracion de audio."""
        return self.set("audio", dict(settings))

    def get_audio_enabled(self) -> bool:
        """Indica si la pestaña musical esta habilitada."""
        return bool(self.get("audio.enabled", True))

    def set_audio_enabled(self, enabled: bool) -> bool:
        """Activa o desactiva la pestaña musical."""
        return self.set("audio.enabled", bool(enabled))

    def get_audio_library_roots(self) -> list[str]:
        """Retorna carpetas raiz de biblioteca musical."""
        return list(self.get("audio.library_roots", []))

    def set_audio_library_roots(self, paths: list[str]) -> bool:
        """Guarda carpetas raiz de biblioteca musical."""
        return self.set("audio.library_roots", self._clean_path_list(paths))

    def get_audio_duplicate_policy(self) -> str:
        """Retorna la politica de resolucion de duplicados de audio."""
        return str(self.get("audio.duplicate_policy", "review"))

    def set_audio_duplicate_policy(self, policy: str) -> bool:
        """Guarda la politica de resolucion de duplicados de audio."""
        policy = str(policy).strip().lower() or "review"
        return self.set("audio.duplicate_policy", policy)

    def get_audio_organization_template(self) -> str:
        """Retorna la plantilla de organizacion de musica."""
        return str(
            self.get(
                "audio.organization_template",
                "MUSICA/{album_artist}/{year} - {album}/{disc_number}-{track_number} - {title}",
            )
        )

    def set_audio_organization_template(self, template: str) -> bool:
        """Guarda la plantilla de organizacion de musica."""
        template = str(template).strip()
        return self.set("audio.organization_template", template)

    def get_audio_online_metadata_enabled(self) -> bool:
        """Indica si se permite enriquecer metadatos online."""
        return bool(self.get("audio.allow_online_metadata", False))

    def set_audio_online_metadata_enabled(self, enabled: bool) -> bool:
        """Activa o desactiva metadatos online."""
        return self.set("audio.allow_online_metadata", bool(enabled))

    def get_organization_conflict_policy(self) -> str:
        """Retorna la politica por defecto para conflictos de organizacion."""
        return str(self.get("analysis.conflict_policy", "rename"))

    def set_organization_conflict_policy(self, policy: str) -> bool:
        """Guarda la politica por defecto para conflictos de organizacion."""
        policy = str(policy).strip().lower() or "rename"
        return self.set("analysis.conflict_policy", policy)

    def get_acoustid_api_key(self) -> str:
        """Retorna la clave de AcoustID."""
        return str(self.get("audio.acoustid_api_key", ""))

    def set_acoustid_api_key(self, api_key: str) -> bool:
        """Guarda la clave de AcoustID."""
        return self.set("audio.acoustid_api_key", str(api_key).strip())

    def get_discogs_enabled(self) -> bool:
        """Indica si Discogs esta activado."""
        return bool(self.get("audio.discogs_enabled", False))

    def set_discogs_enabled(self, enabled: bool) -> bool:
        """Activa o desactiva Discogs."""
        return self.set("audio.discogs_enabled", bool(enabled))

    def get_discogs_token(self) -> str:
        """Retorna el token personal de Discogs."""
        return str(self.get("audio.discogs_token", ""))

    def set_discogs_token(self, token: str) -> bool:
        """Guarda el token personal de Discogs."""
        return self.set("audio.discogs_token", str(token).strip())

    def get_music_last_folder(self) -> str:
        """Retorna la ultima carpeta musical usada."""
        return str(self.get("audio.last_folder", ""))

    def set_music_last_folder(self, path: str) -> bool:
        """Guarda la ultima carpeta musical usada."""
        return self.set("audio.last_folder", str(path).strip())

    def get_music_recursive(self) -> bool:
        """Indica si la musica se indexa recursivamente."""
        return bool(self.get("audio.recursive", True))

    def set_music_recursive(self, enabled: bool) -> bool:
        """Guarda el modo recursivo musical."""
        return self.set("audio.recursive", bool(enabled))

    def get_music_preview_playback_rate(self) -> float:
        """Retorna la velocidad de preescucha musical."""
        try:
            value = float(self.get("audio.preview_playback_rate", 1.0) or 1.0)
        except Exception:
            value = 1.0
        return max(0.5, min(1.5, value))

    def set_music_preview_playback_rate(self, rate: float) -> bool:
        """Guarda la velocidad de preescucha musical."""
        normalized = max(0.5, min(1.5, float(rate or 1.0)))
        return self.set("audio.preview_playback_rate", round(normalized, 2))

    def get_music_library_column_widths(self) -> list[int]:
        """Retorna anchos de columnas de la tabla musical."""
        widths = self.get(
            "audio.library_column_widths",
            list(LIBRARY_COLUMN_DEFAULTS),
        )
        return [int(value) for value in widths if str(value).strip()]

    def set_music_library_column_widths(self, widths: list[int]) -> bool:
        """Guarda anchos de columnas de la tabla musical."""
        cleaned = [max(40, int(value)) for value in widths]
        return self.set("audio.library_column_widths", cleaned)

    def get_music_library_column_order(self) -> list[int]:
        """Retorna el orden visual de columnas de la tabla musical."""
        default_order = list(LIBRARY_COLUMN_DEFAULT_ORDER)
        order = self.get(
            "audio.library_column_order",
            default_order,
        )
        normalized = [int(value) for value in order if str(value).strip()]
        legacy_order = list(range(len(default_order)))
        if normalized == legacy_order:
            return default_order
        return normalized

    def set_music_library_column_order(self, order: list[int]) -> bool:
        """Guarda el orden visual de columnas de la tabla musical."""
        cleaned = [max(0, int(value)) for value in order]
        return self.set("audio.library_column_order", cleaned)

    def get_music_library_visible_columns(self) -> list[int]:
        """Retorna columnas visibles de la tabla musical."""
        columns = self.get(
            "audio.library_visible_columns",
            list(LIBRARY_DEFAULT_VISIBLE_COLUMNS),
        )
        return [int(value) for value in columns if str(value).strip()]

    def set_music_library_visible_columns(self, columns: list[int]) -> bool:
        """Guarda columnas visibles de la tabla musical."""
        cleaned = [max(0, int(value)) for value in columns]
        return self.set("audio.library_visible_columns", cleaned)

    def get_music_library_splitter_sizes(self) -> list[int]:
        """Retorna tamaños del splitter de biblioteca musical."""
        sizes = self.get(
            "audio.library_splitter_sizes", list(LIBRARY_SPLITTER_DEFAULT_SIZES)
        )
        return [max(120, int(value)) for value in sizes if str(value).strip()]

    def set_music_library_splitter_sizes(self, sizes: list[int]) -> bool:
        """Guarda tamaños del splitter de biblioteca musical."""
        cleaned = [max(120, int(value)) for value in sizes]
        return self.set("audio.library_splitter_sizes", cleaned)

    def get_music_library_header_state(self) -> str:
        """Retorna el estado serializado del header de la tabla musical."""
        return str(self.get("audio.library_header_state", ""))

    def set_music_library_header_state(self, state: str) -> bool:
        """Guarda el estado serializado del header de la tabla musical."""
        return self.set("audio.library_header_state", str(state or "").strip())

    def _clean_path_list(self, paths: list[str]) -> list[str]:
        """Normaliza una lista de rutas configurables."""
        return [
            self._normalize_path(path) for path in paths if self._normalize_path(path)
        ]

    def _normalize_path(self, path: str) -> str:
        """Normaliza rutas manteniendo formato portable."""
        normalized = str(path).strip().replace("\\", "/")
        return normalized

    def reset_to_default(self) -> bool:
        """Restaura la configuración por defecto"""
        self.config = self.DEFAULT_CONFIG.copy()
        return self.save_config()

    def export_config(self, filepath: str) -> bool:
        """Exporta la configuración a un archivo"""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            from .logger import error

            error(f"Error exportando configuración: {e}")
            return False

    def import_config(self, filepath: str) -> bool:
        """Importa configuración desde un archivo"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                imported_config = json.load(f)

            # Fusionar con configuración actual
            self.config = self.merge_configs(self.config, imported_config)
            return self.save_config()
        except Exception as e:
            from .logger import error

            error(f"Error importando configuración: {e}")
            return False
