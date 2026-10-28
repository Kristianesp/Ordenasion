#!/usr/bin/env python3
"""
Workers para el Organizador de Archivos
Maneja el procesamiento en segundo plano para análisis y organización
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Iterable, Tuple
from collections import Counter, defaultdict
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from src.utils.constants import VARIOS_CATEGORY
from src.utils.logger import error as log_error, warn as log_warn
from .category_manager import guess_category
from .hash_manager import HashManager
from .transaction_manager import (
    ROLE_OVERWRITE_BACKUP,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    TransactionManager,
)
from .audio_index import audio_metadata_service
from .fs_safety import (
    has_hidden_system_attributes,
    is_inside,
    is_junk_file_name,
    is_link_or_junction,
    is_system_path,
    long_path,
    normalize,
)
from .organization_conflicts import (
    CONFLICT_POLICY_RENAME,
    CONFLICT_POLICY_SKIP,
    find_available_name,
)
from .organization_plan import (
    ACTION_INVALID,
    ACTION_MISSING,
    ACTION_OVERWRITE,
    ACTION_SKIP,
    OrganizationPlan,
    build_organization_plan,
    known_category_folder_names,
)

# Estados legibles del resultado de una organización
RESULT_LABELS = {
    STATUS_COMPLETED: "Completada",
    STATUS_COMPLETED_WITH_ERRORS: "Completada con errores",
    STATUS_CANCELLED: "Cancelada",
    STATUS_FAILED: "Error",
}


class AnalysisWorker(QThread):
    """Worker para analizar carpetas y archivos en segundo plano"""

    # Señales para comunicación con la UI
    progress_update = pyqtSignal(str)
    analysis_complete = pyqtSignal(list, list, dict)
    analysis_cancelled = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        folder_path: str,
        categories: Dict[str, List[str]],
        ext_to_categoria: Dict[str, str],
        min_percentage: int = 70,
        advanced_analysis: bool = True,
        min_file_size_mb: int = 0,
        ignored_extensions: Optional[List[str]] = None,
        ignored_paths: Optional[List[str]] = None,
        category_manager=None,
        excluded_folder_names: Optional[Iterable[str]] = None,
    ):
        super().__init__()
        self.folder_path = folder_path
        self.categories = categories
        self.ext_to_categoria = ext_to_categoria
        self.category_manager = category_manager
        self.min_percentage = min_percentage  # Porcentaje mínimo de similitud
        self.advanced_analysis = advanced_analysis  # Nuevo: análisis avanzado
        self.min_file_size_bytes = max(0, int(min_file_size_mb)) * 1024 * 1024
        self.ignored_extensions = {
            (ext if str(ext).startswith(".") else f".{str(ext)}").lower()
            for ext in (ignored_extensions or [])
            if str(ext).strip()
        }
        self.ignored_paths = [
            normalize(Path(path))
            for path in (ignored_paths or [])
            if str(path).strip()
        ]
        # Carpetas de categoría que ya existen: no se reorganizan
        if category_manager is not None and hasattr(category_manager, "get_category_folder_names"):
            folder_names = set(category_manager.get_category_folder_names())
        else:
            folder_names = known_category_folder_names(list((categories or {}).keys()))
        folder_names |= {os.path.normcase(name) for name in (excluded_folder_names or [])}
        self.category_folder_names = folder_names
        self.hash_manager = HashManager()
        self.is_running = True
        self.was_cancelled = False

    def run(self):
        """Ejecuta el análisis de la carpeta"""
        try:
            self.progress_update.emit("🔍 Iniciando análisis de la carpeta...")

            # Una sola pasada por la carpeta raíz
            folder_entries, file_entries = self._scan_root()

            # Analizar carpetas
            folder_movements = self.analyze_folders(folder_entries)
            if not self.is_running:
                return self._emit_cancelled()
            self.progress_update.emit(f"📁 Analizadas {len(folder_movements)} carpetas")

            # Analizar archivos sueltos
            file_movements = self.analyze_loose_files(file_entries)
            if not self.is_running:
                return self._emit_cancelled()
            self.progress_update.emit(
                f"📄 Analizados {len(file_movements)} archivos sueltos"
            )

            # Calcular estadísticas
            stats = self.calculate_statistics(folder_movements, file_movements)

            self.progress_update.emit("✅ Análisis completado exitosamente")
            self.analysis_complete.emit(folder_movements, file_movements, stats)

        except Exception as e:
            self.error_occurred.emit(f"❌ Error durante el análisis: {str(e)}")

    def _emit_cancelled(self):
        self.was_cancelled = True
        self.progress_update.emit("⏹️ Análisis cancelado por el usuario")
        self.analysis_cancelled.emit()

    # ------------------------------------------------------------------
    # Recorrido
    # ------------------------------------------------------------------
    def _scan_root(self) -> Tuple[List[os.DirEntry], List[os.DirEntry]]:
        """Lista la carpeta raíz una vez y separa carpetas y archivos."""
        folders: List[os.DirEntry] = []
        files: List[os.DirEntry] = []
        root = Path(self.folder_path)
        if not root.is_dir():
            return folders, files
        try:
            with os.scandir(long_path(root)) as entries:
                for entry in entries:
                    if not self.is_running:
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            folders.append(entry)
                        elif entry.is_file(follow_symlinks=False):
                            files.append(entry)
                    except OSError:
                        continue
        except PermissionError:
            self.progress_update.emit(f"⚠️ Sin permisos para acceder a {root}")
        folders.sort(key=lambda entry: entry.name.lower())
        files.sort(key=lambda entry: entry.name.lower())
        return folders, files

    @staticmethod
    def _entry_path(entry) -> Path:
        path = entry.path if isinstance(entry, os.DirEntry) else str(entry)
        if path.startswith("\\\\?\\UNC\\"):
            path = "\\\\" + path[8:]
        elif path.startswith("\\\\?\\"):
            path = path[4:]
        return Path(path)

    @staticmethod
    def _entry_stat(entry):
        if isinstance(entry, os.DirEntry):
            return entry.stat(follow_symlinks=False)
        return os.stat(long_path(entry), follow_symlinks=False)

    def analyze_folders(self, folder_entries: Optional[List] = None) -> List[Dict[str, Any]]:
        """Analiza carpetas y las envía a VARIOS si no superan el umbral de similitud."""
        folder_movements = []
        if folder_entries is None:
            folder_entries, _ = self._scan_root()

        for entry in folder_entries:
            if not self.is_running:
                break
            folder = self._entry_path(entry)
            try:
                if is_link_or_junction(entry):
                    self.progress_update.emit(
                        f"🔗 Omitido enlace o junction: {folder.name}"
                    )
                    continue
                # FILTRO INTELIGENTE: Solo excluir carpetas del sistema críticas
                if self.is_excluded_path(folder) or self.is_system_folder(folder, entry):
                    self.progress_update.emit(
                        f"🚫 Excluyendo carpeta del sistema: {folder.name}"
                    )
                    continue
                if os.path.normcase(folder.name) in self.category_folder_names:
                    self.progress_update.emit(
                        f"📂 Carpeta de categoría existente (no se reorganiza): {folder.name}"
                    )
                    continue

                # Analizar contenido de la carpeta
                total_files, total_size, category_counts = self.analyze_folder_content(
                    folder
                )

                if total_files > 0:
                    # Determinar categoría principal
                    main_category = max(category_counts.items(), key=lambda x: x[1])[0]
                    percentage = (category_counts[main_category] / total_files) * 100
                    assigned_category = (
                        main_category if percentage >= self.min_percentage else VARIOS_CATEGORY
                    )
                    # Si la carpeta es demasiado heterogénea para el umbral elegido,
                    # se conserva visible en resultados pero se envía a VARIOS para
                    # evitar clasificaciones agresivas e incorrectas.

                    movement = {
                        "folder": folder,
                        "category": assigned_category,
                        "matched_category": main_category,
                        "total_files": total_files,
                        "size": total_size,
                        "percentage": percentage,
                        "extension": "carpeta",
                        "category_counts": category_counts,
                        "is_expandable": True,
                        "below_similarity_threshold": percentage < self.min_percentage,
                    }
                    folder_movements.append(movement)
                    if percentage < self.min_percentage:
                        self.progress_update.emit(
                            f"📁 Carpeta marcada como VARIOS: {folder.name} ({percentage:.1f}% {main_category}, umbral {self.min_percentage}%)"
                        )
                    else:
                        self.progress_update.emit(
                            f"📁 Carpeta incluida: {folder.name} ({percentage:.1f}% {main_category})"
                        )
                else:
                    # Carpeta vacía - incluirla también
                    movement = {
                        "folder": folder,
                        "category": VARIOS_CATEGORY,
                        "total_files": 0,
                        "size": 0,
                        "percentage": 0,
                        "extension": "carpeta",
                        "category_counts": Counter(),
                        "is_expandable": True,
                    }
                    folder_movements.append(movement)
                    self.progress_update.emit(
                        f"📁 Carpeta vacía incluida: {folder.name}"
                    )

            except Exception as e:
                self.progress_update.emit(
                    f"⚠️ Error analizando carpeta {folder.name}: {str(e)}"
                )

        return folder_movements

    def analyze_folder_content(self, folder_path: Path) -> tuple:
        """Analiza el contenido de una carpeta específica (sin seguir enlaces)"""
        total_files = 0
        total_size = 0
        category_counts = Counter()

        try:
            with os.scandir(long_path(folder_path)) as entries:
                for entry in entries:
                    if not self.is_running:
                        break
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        stat_result = entry.stat(follow_symlinks=False)
                        item = Path(folder_path) / entry.name
                        if self._should_skip_file(item, stat_result):
                            continue
                        total_files += 1
                        total_size += stat_result.st_size
                        category_counts[self._categorize_path(item)] += 1
                    except (PermissionError, OSError):
                        # Ignorar archivos individuales sin permisos
                        continue

        except PermissionError:
            self.progress_update.emit(
                f"⚠️ Sin permisos para acceder a {folder_path.name}"
            )
        except Exception as e:
            self.progress_update.emit(
                f"⚠️ Error analizando contenido de {folder_path.name}: {str(e)}"
            )

        return total_files, total_size, category_counts

    def is_system_folder(self, folder_path: Path, entry=None) -> bool:
        """Determina si una carpeta es del sistema y debe ser excluida.

        Se compara por componentes de ruta (relativos a la carpeta analizada)
        y contra las carpetas reales del sistema, nunca por subcadenas.
        """
        if is_system_path(folder_path, root=self.folder_path):
            return True

        # Carpetas ocultas+sistema, o ocultas con nombre de sistema ($...)
        try:
            stat_result = self._entry_stat(entry if entry is not None else folder_path)
        except OSError:
            return False
        if has_hidden_system_attributes(stat_result):
            return True
        attributes = getattr(stat_result, "st_file_attributes", 0) or 0
        if attributes & 0x2 and folder_path.name.startswith("$"):
            return True

        # NO es carpeta del sistema - incluirla
        return False

    def get_folder_contents(self, folder_path: Path) -> List[Dict[str, Any]]:
        """Obtiene el contenido detallado de una carpeta para expansión"""
        contents = []

        try:
            with os.scandir(long_path(folder_path)) as entries:
                for entry in entries:
                    item = Path(folder_path) / entry.name
                    try:
                        if entry.is_file(follow_symlinks=False):
                            stat_result = entry.stat(follow_symlinks=False)
                            if self._should_skip_file(item, stat_result):
                                continue
                            contents.append(
                                {
                                    "type": "file",
                                    "path": item,
                                    "name": item.name,
                                    "size": stat_result.st_size,
                                    "category": self._categorize_path(item),
                                    "extension": item.suffix.lower(),
                                }
                            )
                        elif entry.is_dir(follow_symlinks=False) and not is_link_or_junction(entry):
                            # Subcarpeta
                            try:
                                with os.scandir(long_path(item)) as sub_entries:
                                    sub_files = sum(
                                        1 for sub in sub_entries if sub.is_file(follow_symlinks=False)
                                    )
                                contents.append(
                                    {
                                        "type": "subfolder",
                                        "path": item,
                                        "name": item.name,
                                        "file_count": sub_files,
                                        "is_expandable": True,
                                    }
                                )
                            except (PermissionError, OSError):
                                # Subcarpeta sin permisos
                                contents.append(
                                    {
                                        "type": "subfolder",
                                        "path": item,
                                        "name": item.name,
                                        "file_count": 0,
                                        "is_expandable": False,
                                        "no_access": True,
                                    }
                                )

                    except (PermissionError, OSError):
                        continue

        except PermissionError:
            self.progress_update.emit(
                f"⚠️ Sin permisos para acceder a {folder_path.name}"
            )
        except Exception as e:
            self.progress_update.emit(
                f"⚠️ Error obteniendo contenido de {folder_path.name}: {str(e)}"
            )

        return contents

    def analyze_loose_files(self, file_entries: Optional[List] = None) -> List[Dict[str, Any]]:
        """Analiza archivos sueltos en la carpeta principal con análisis avanzado"""
        file_movements = []
        if file_entries is None:
            _, file_entries = self._scan_root()

        for entry in file_entries:
            if not self.is_running:
                break
            file = self._entry_path(entry)
            try:
                stat_result = self._entry_stat(entry)
                # Información básica del archivo
                if self._should_skip_file(file, stat_result):
                    continue
                extension = file.suffix.lower()

                # Categorizar archivo
                category = self._categorize_path(file)

                # Análisis avanzado (si está habilitado)
                advanced_info = {}
                if self.advanced_analysis:
                    advanced_info = self._get_advanced_file_info(file, stat_result)

                # Crear diccionario completo del archivo
                movement = {
                    "file": file,
                    "category": category,
                    "extension": extension,
                    "size": stat_result.st_size,
                    "date": stat_result.st_mtime,
                    "advanced_info": advanced_info,
                    "is_expandable": True,  # Para mostrar detalles avanzados
                }

                # Agregar información adicional para UI
                if advanced_info:
                    movement.update(
                        {
                            "has_advanced_info": True,
                            "file_type": advanced_info.get("type", "unknown"),
                            "description": advanced_info.get("description", ""),
                            "metadata": advanced_info.get("metadata", {}),
                        }
                    )

                file_movements.append(movement)

            except Exception as e:
                self.progress_update.emit(
                    f"⚠️ Error analizando archivo {file.name}: {str(e)}"
                )

        return file_movements

    def _get_advanced_file_info(self, file_path: Path, stat_result=None) -> Dict[str, Any]:
        """Obtiene información avanzada de un archivo.

        No calcula hashes: el contenido solo se lee cuando hace falta
        compararlo (``compute_file_hash`` o la comprobación de duplicados).
        """
        info = {"type": "file", "description": "", "metadata": {}, "hash": None}

        try:
            stat = stat_result if stat_result is not None else file_path.stat()
            info["metadata"] = {
                "size_bytes": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime),
                "modified": datetime.fromtimestamp(stat.st_mtime),
                "accessed": datetime.fromtimestamp(stat.st_atime),
            }

            # Detectar tipo de archivo por extensión
            ext = file_path.suffix.lower()
            if audio_metadata_service.is_audio_file(file_path):
                info["type"] = "audio"
                info["description"] = "Audio"
                audio_meta = audio_metadata_service.extract_metadata(file_path)
                info["metadata"]["audio"] = {
                    "artist": audio_meta.artist,
                    "album_artist": audio_meta.album_artist,
                    "title": audio_meta.title,
                    "album": audio_meta.album,
                    "track_number": audio_meta.track_number,
                    "disc_number": audio_meta.disc_number,
                    "year": audio_meta.year,
                    "genre": audio_meta.genre,
                    "duration": audio_meta.duration,
                    "bitrate": audio_meta.bitrate,
                    "sample_rate": audio_meta.sample_rate,
                    "channels": audio_meta.channels,
                    "bit_depth": audio_meta.bit_depth,
                    "lossless": audio_meta.lossless,
                    "codec": audio_meta.codec,
                    "source": audio_meta.source,
                    "error": audio_meta.error,
                }
            elif ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"]:
                info["type"] = "image"
                info["description"] = "Imagen"
            elif ext in [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm"]:
                info["type"] = "video"
                info["description"] = "Video"
            elif ext in [".pdf", ".doc", ".docx", ".txt", ".rtf"]:
                info["type"] = "document"
                info["description"] = "Documento"
            elif ext in [".zip", ".rar", ".7z", ".tar", ".gz"]:
                info["type"] = "archive"
                info["description"] = "Archivo comprimido"
            elif ext in [".exe", ".msi", ".deb", ".rpm", ".dmg"]:
                info["type"] = "executable"
                info["description"] = "Ejecutable"
            else:
                info["type"] = "file"
                info["description"] = f"Archivo {ext.upper()}"

        except Exception as e:
            info["description"] = f"Error obteniendo información: {str(e)}"

        return info

    def compute_file_hash(self, file_path: Path) -> Optional[str]:
        """Calcula el hash MD5 bajo demanda (no durante el análisis)."""
        return self.hash_manager.calculate_file_hash(file_path, "md5")

    def _categorize_path(self, file_path: Path) -> str:
        """Delegación única de la categorización en CategoryManager.

        Respeta reglas personalizadas; sin gestor se usa la misma lógica de
        extensión, MIME, heurísticas por nombre y VARIOS.
        """
        if self.category_manager is not None:
            return self.category_manager.categorize_file(file_path)
        return guess_category(file_path, self.ext_to_categoria)

    def is_excluded_path(self, path: Path) -> bool:
        """Determina si una ruta debe excluirse del análisis."""
        return any(is_inside(path, ignored) for ignored in self.ignored_paths)

    def _should_skip_file(self, file_path: Path, stat_result=None) -> bool:
        """Aplica exclusiones: basura/sistema, ruta, extensión y tamaño mínimo."""
        if is_junk_file_name(file_path.name):
            return True
        if self.ignored_paths and self.is_excluded_path(file_path):
            return True
        if file_path.suffix.lower() in self.ignored_extensions:
            return True
        if stat_result is None:
            try:
                stat_result = os.stat(long_path(file_path), follow_symlinks=False)
            except OSError:
                return True
        if has_hidden_system_attributes(stat_result):
            return True
        if self.min_file_size_bytes <= 0:
            return False
        return stat_result.st_size < self.min_file_size_bytes

    def calculate_statistics(
        self, folder_movements: List[Dict], file_movements: List[Dict]
    ) -> Dict[str, Any]:
        """Calcula estadísticas generales del análisis"""
        total_folders = len(folder_movements)
        total_files = len(file_movements)
        total_size = sum(
            mov.get("size", 0) for mov in folder_movements + file_movements
        )

        # Estadísticas por categoría
        category_stats = defaultdict(lambda: {"count": 0, "size": 0})

        # Contar carpetas por categoría
        for mov in folder_movements:
            category = mov["category"]
            category_stats[category]["count"] += 1
            category_stats[category]["size"] += mov.get("size", 0)

        # Contar archivos por categoría
        for mov in file_movements:
            category = mov["category"]
            category_stats[category]["count"] += 1
            category_stats[category]["size"] += mov.get("size", 0)

        return {
            "total_folders": total_folders,
            "total_files": total_files,
            "total_size": total_size,
            "category_stats": dict(category_stats),
        }

    def stop(self):
        """Detiene el worker (los bucles comprueban ``is_running``)"""
        self.is_running = False


class OrganizeWorker(QThread):
    """Worker para organizar archivos y carpetas en segundo plano
    🚀 MEJORADO: Con sistema de transacciones y rollback automático

    Ejecuta un ``OrganizationPlan`` (el mismo que mostró la vista previa).
    El resultado final queda en ``summary["status"]``: completado,
    completado con errores, cancelado o error.
    """

    # Señales para comunicación con la UI
    progress_update = pyqtSignal(str)
    organize_complete = pyqtSignal(bool, str)
    rollback_available = pyqtSignal(
        str
    )  # Nueva señal para indicar que hay rollback disponible
    summary_ready = pyqtSignal(dict)

    def __init__(
        self,
        source_folder: str,
        folder_movements: List[Dict],
        file_movements: List[Dict],
        organize_by_date: bool = False,
        check_duplicates: bool = False,
        protected_paths: Optional[List[str]] = None,
        conflict_policy: str = CONFLICT_POLICY_RENAME,
        transaction_manager: Optional[TransactionManager] = None,
        plan: Optional[OrganizationPlan] = None,
        category_folder: Optional[Callable[[str], str]] = None,
    ):
        super().__init__()
        self.source_folder = source_folder
        self.folder_movements = folder_movements
        self.file_movements = file_movements
        self.is_running = True
        # Gestor compartido con la ventana para poder deshacer en la sesión
        self.transaction_manager = transaction_manager or TransactionManager()
        self.current_transaction_id = None
        self.organize_by_date = organize_by_date
        self.check_duplicates = check_duplicates
        self.conflict_policy = conflict_policy
        self.plan = plan
        self.category_folder = category_folder
        self.hash_manager = HashManager()
        self.protected_paths = [
            normalize(Path(path))
            for path in (protected_paths or [])
            if str(path).strip()
        ]
        self._moved_files = []  # Track moved files for duplicate checking
        self.summary = {
            "status": STATUS_COMPLETED,
            "status_label": RESULT_LABELS[STATUS_COMPLETED],
            "transaction_id": None,
            "folders_moved": 0,
            "files_moved": 0,
            "bytes_reorganized": 0,
            "skipped_duplicates": 0,
            "skipped_conflicts": 0,
            "skipped_invalid": 0,
            "failed": 0,
            "pending": 0,
            "total_items": 0,
            "overwrite_backups": 0,
            "warnings": [],
            "errors": [],
            "duration_seconds": 0.0,
            "created_folders": [],
        }

    # ------------------------------------------------------------------
    def _resolve_plan(self) -> OrganizationPlan:
        plan = self.plan
        if isinstance(plan, OrganizationPlan) and plan.matches(
            self.source_folder, self.conflict_policy, self.organize_by_date
        ):
            return plan
        return build_organization_plan(
            self.source_folder,
            self.folder_movements,
            self.file_movements,
            conflict_policy=self.conflict_policy,
            organize_by_date=self.organize_by_date,
            check_duplicates=self.check_duplicates,
            category_folder=self.category_folder,
        )

    def _final_status(self) -> str:
        if not self.is_running:
            return STATUS_CANCELLED
        if self.summary["errors"]:
            return STATUS_COMPLETED_WITH_ERRORS
        return STATUS_COMPLETED

    def _result_message(self, status: str) -> str:
        moved = self.summary["files_moved"] + self.summary["folders_moved"]
        if status == STATUS_CANCELLED:
            return (
                f"Organización cancelada: {moved} elementos movidos, "
                f"{self.summary['pending']} sin procesar"
            )
        if status == STATUS_COMPLETED_WITH_ERRORS:
            return (
                f"Organización completada con errores: {moved} elementos movidos, "
                f"{self.summary['failed']} fallidos"
            )
        return "Organización completada exitosamente"

    def run(self):
        """Ejecuta la organización de archivos y carpetas con transacciones"""
        started_at = datetime.now()
        try:
            plan = self._resolve_plan()
            self.plan = plan
            self.summary["total_items"] = len(plan.items)
            # 🚀 MEJORA: Iniciar transacción
            self.current_transaction_id = self.transaction_manager.begin_transaction(
                f"Organización de {len(plan.items)} elementos en {self.source_folder}",
                source_folder=self.source_folder,
            )
            self.summary["transaction_id"] = self.current_transaction_id

            self.progress_update.emit(
                "🚀 Iniciando organización con protección de datos..."
            )

            # Las carpetas de destino se crean al mover (y se registran para
            # poder borrarlas al deshacer si quedan vacías)
            self.move_folders(plan)
            self.move_loose_files(plan)

            status = self._final_status()
            self.summary["status"] = status
            self.summary["status_label"] = RESULT_LABELS[status]
            self.summary["duration_seconds"] = (
                datetime.now() - started_at
            ).total_seconds()
            self.transaction_manager.end_transaction(status, self._summary_counts())
            self.summary_ready.emit(dict(self.summary))

            message = self._result_message(status)
            icon = {"completado": "✅", "cancelado": "⏹️"}.get(status, "⚠️")
            self.progress_update.emit(f"{icon} {message}")
            self.organize_complete.emit(status == STATUS_COMPLETED, message)

            # Emitir señal de rollback disponible (también tras cancelar o con
            # errores: permite deshacer lo que sí se movió)
            if self.summary["files_moved"] or self.summary["folders_moved"]:
                self.rollback_available.emit(self.current_transaction_id)

        except Exception as e:
            error_msg = f"❌ Error durante la organización: {str(e)}"
            self.progress_update.emit(error_msg)
            log_error(error_msg)

            # 🚀 MEJORA: Intentar rollback automático
            if self.current_transaction_id:
                self.progress_update.emit("🔄 Intentando revertir cambios...")
                if self.transaction_manager.rollback_transaction(
                    self.current_transaction_id
                ):
                    error_msg += "\n✅ Cambios revertidos exitosamente"
                else:
                    error_msg += "\n⚠️ No se pudieron revertir todos los cambios"
                self.transaction_manager.end_transaction(STATUS_FAILED, self._summary_counts())

            self.summary["status"] = STATUS_FAILED
            self.summary["status_label"] = RESULT_LABELS[STATUS_FAILED]
            self.summary["errors"].append(error_msg)
            self.summary["duration_seconds"] = (
                datetime.now() - started_at
            ).total_seconds()
            self.summary_ready.emit(dict(self.summary))
            self.organize_complete.emit(False, error_msg)

    def _summary_counts(self) -> Dict[str, Any]:
        return {
            key: self.summary[key]
            for key in (
                "folders_moved",
                "files_moved",
                "bytes_reorganized",
                "skipped_duplicates",
                "skipped_conflicts",
                "skipped_invalid",
                "failed",
                "pending",
                "total_items",
                "overwrite_backups",
            )
        }

    # ------------------------------------------------------------------
    def _ensure_parent(self, destination: Path):
        created = self.transaction_manager.ensure_directory(destination.parent)
        for folder in created:
            try:
                relative = str(folder.relative_to(Path(self.source_folder))).replace("\\", "/")
            except ValueError:
                relative = str(folder)
            self.summary["created_folders"].append(relative)
            self.progress_update.emit(f"📁 Creada carpeta: {relative}")

    def _skip_common(self, item) -> bool:
        """Omite elementos protegidos, inválidos o desaparecidos."""
        if self._is_protected_path(item.source):
            prefix = "Carpeta protegida omitida" if item.is_folder else "Archivo protegido omitido"
            warning = f"{prefix}: {item.source}"
            self.summary["warnings"].append(warning)
            self.summary["skipped_invalid"] += 1
            self.progress_update.emit(f"🛡️ {warning}")
            return True
        if item.action in (ACTION_INVALID, ACTION_MISSING):
            warning = f"{item.source.name}: {item.status}"
            self.summary["warnings"].append(warning)
            self.summary["skipped_invalid"] += 1
            self.progress_update.emit(f"⏭️ {warning}")
            return True
        return False

    def move_folders(self, plan: Optional[OrganizationPlan] = None):
        """Mueve las carpetas a sus ubicaciones de destino (solo os.rename)"""
        plan = plan or self._resolve_plan()
        items = plan.folder_items
        for index, item in enumerate(items):
            if not self.is_running:
                self.summary["pending"] += len(items) - index
                break
            if self._skip_common(item):
                continue

            dest_path = item.destination
            if os.path.lexists(long_path(dest_path)):
                # El destino se ocupó después de la vista previa
                dest_path = find_available_name(dest_path)

            self._ensure_parent(dest_path)
            if self.transaction_manager.safe_move_directory(item.source, dest_path):
                self.summary["folders_moved"] += 1
                self.summary["bytes_reorganized"] += item.size
                progress = f"📁 Movida carpeta: {item.source.name} → {item.category}"
                self.progress_update.emit(progress)
            else:
                reason = self.transaction_manager.last_error or "motivo desconocido"
                error = f"Error moviendo carpeta {item.source.name}: {reason}"
                self.summary["errors"].append(error)
                self.summary["failed"] += 1
                self.progress_update.emit(f"⚠️ {error}")

    def move_loose_files(self, plan: Optional[OrganizationPlan] = None):
        """Mueve los archivos sueltos a sus carpetas de destino"""
        plan = plan or self._resolve_plan()
        items = plan.file_items
        if not self.is_running:
            self.summary["pending"] += len(items)
            return
        for index, item in enumerate(items):
            if not self.is_running:
                self.summary["pending"] += len(items) - index
                break
            if self._skip_common(item):
                continue
            file = item.source
            base_destination = item.base_destination

            # "Comprobar duplicados" funciona con cualquier política: si el
            # destino original ya contiene un archivo idéntico, se omite.
            if self.check_duplicates and os.path.lexists(long_path(base_destination)):
                if self._is_duplicate_file(file, base_destination):
                    self.summary["skipped_duplicates"] += 1
                    self.progress_update.emit(
                        f"⏭️ Duplicado omitido: {file.name} ya existe en {base_destination.parent}"
                    )
                    continue

            # Mover archivo
            if item.action == ACTION_SKIP:
                self.summary["skipped_conflicts"] += 1
                self.progress_update.emit(
                    f"⏭️ Archivo omitido por conflicto: {file.name}"
                )
                continue

            dest_path = item.destination
            occupied = os.path.lexists(long_path(dest_path))
            if item.action == ACTION_OVERWRITE and occupied:
                backup_path = find_available_name(
                    dest_path.with_name(f".{dest_path.stem}.overwrite{dest_path.suffix}")
                )
                if not self.transaction_manager.safe_move_file(
                    dest_path, backup_path, role=ROLE_OVERWRITE_BACKUP
                ):
                    reason = self.transaction_manager.last_error or "motivo desconocido"
                    error = f"Error preparando sobrescritura de {dest_path.name}: {reason}"
                    self.summary["errors"].append(error)
                    self.summary["failed"] += 1
                    self.progress_update.emit(f"⚠️ {error}")
                    continue
                self.summary["overwrite_backups"] += 1
            elif occupied:
                # El destino se ocupó después de la vista previa: nunca se
                # sobrescribe algo que el usuario no aprobó
                if self.conflict_policy == CONFLICT_POLICY_SKIP:
                    self.summary["skipped_conflicts"] += 1
                    self.progress_update.emit(
                        f"⏭️ Archivo omitido por conflicto: {file.name}"
                    )
                    continue
                dest_path = find_available_name(dest_path)

            # Mostrar información sobre la carpeta de destino
            dest_folder = dest_path.parent.name
            if dest_folder == item.category:
                progress = f"📄 Movido archivo: {file.name} → {item.category}/"
            else:
                progress = f"📄 Movido archivo: {file.name} → {dest_folder}/"

            self._ensure_parent(dest_path)
            # 🚀 MEJORA: Usar safe_move_file del transaction_manager
            if self.transaction_manager.safe_move_file(file, dest_path):
                self.summary["files_moved"] += 1
                self.summary["bytes_reorganized"] += item.size
                self.progress_update.emit(progress)
            else:
                reason = self.transaction_manager.last_error or "motivo desconocido"
                error = f"Error moviendo archivo {file.name}: {reason}"
                self.summary["errors"].append(error)
                self.summary["failed"] += 1
                self.progress_update.emit(f"⚠️ {error}")

        if self.summary["overwrite_backups"]:
            self.summary["warnings"].append(
                f"Se conservan {self.summary['overwrite_backups']} copias ocultas "
                "(.nombre.overwrite.ext) de los archivos sobrescritos para poder deshacer"
            )

    def stop(self):
        """Detiene el worker"""
        self.is_running = False

    def _is_duplicate_file(self, source: Path, destination: Path) -> bool:
        """Verifica si origen y destino son archivos idénticos (hash bajo demanda)."""
        try:
            if not destination.is_file():
                return False
            if source.stat().st_size != destination.stat().st_size:
                return False
            source_hash = self.hash_manager.calculate_file_hash(source, "md5")
            dest_hash = self.hash_manager.calculate_file_hash(destination, "md5")
            return bool(source_hash and source_hash == dest_hash)
        except Exception as error:
            log_warn(f"No se pudo verificar duplicado para {source}: {error}")
            self.progress_update.emit(
                f"⚠️ No se pudo verificar duplicado para {source.name}: {error}"
            )
            return False

    def _is_protected_path(self, path: Path) -> bool:
        """Evita mover rutas marcadas como protegidas."""
        return any(is_inside(path, protected) for protected in self.protected_paths)


class RollbackWorker(QThread):
    """Deshace una transacción fuera del hilo de la interfaz."""

    rollback_finished = pyqtSignal(str, bool, dict)

    def __init__(self, transaction_manager: TransactionManager, transaction_id: str):
        super().__init__()
        self.transaction_manager = transaction_manager
        self.transaction_id = transaction_id

    def run(self):
        try:
            ok = self.transaction_manager.rollback_transaction(self.transaction_id)
            result = dict(self.transaction_manager.last_rollback_result or {})
        except Exception as exc:
            log_error(f"Error deshaciendo {self.transaction_id}: {exc}")
            ok, result = False, {"errors": [str(exc)], "warnings": [], "reverted": 0}
        self.rollback_finished.emit(self.transaction_id, ok, result)

    def stop(self):
        """El rollback no se interrumpe a medias; se espera a que termine."""
        return None
