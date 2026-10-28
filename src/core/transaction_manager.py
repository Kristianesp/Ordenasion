#!/usr/bin/env python3
"""
Sistema de Transacciones y Rollback para el Organizador de Archivos
Permite deshacer operaciones de movimiento/eliminación de archivos

El registro es un archivo JSONL (una operación por línea) que solo se
amplía: escribir una operación cuesta lo mismo con 10 que con 100.000
entradas. El historial sobrevive a los reinicios y permite deshacer
cualquier transacción pasada que no se haya revertido ya.

Formato de cada línea (campos principales):
- ``transaction_begin``: transaction_id, description, source_folder
- ``move`` / ``rename`` / ``create_dir`` / ``delete``: op_id, details
- ``transaction_commit``: status (completado, cancelado,
  completado con errores, error) y resumen
- ``transaction_rollback``: reverted_ops (op_id revertidos) y errores

Los archivos sustituidos con la política "sobrescribir" se guardan como
``.nombre.overwrite.ext`` junto al destino y se conservan para poder
deshacer; al deshacer se restauran. ``discard_overwrite_backups`` los
envía a la papelera cuando el usuario ya no necesita deshacer.
"""

import json
import os
import shutil
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum

from src.utils.logger import error, warn, success, info

from .fs_safety import long_path, normalize

STATUS_IN_PROGRESS = "en curso"
STATUS_COMPLETED = "completado"
STATUS_COMPLETED_WITH_ERRORS = "completado con errores"
STATUS_CANCELLED = "cancelado"
STATUS_FAILED = "error"
STATUS_INTERRUPTED = "interrumpido"

ROLE_OVERWRITE_BACKUP = "overwrite_backup"


class OperationType(Enum):
    """Tipos de operaciones que se pueden deshacer"""

    MOVE = "move"
    DELETE = "delete"
    RENAME = "rename"
    CREATE_DIR = "create_dir"


_REVERTIBLE_TYPES = {OperationType.MOVE.value, OperationType.RENAME.value}
_OPERATION_TYPES = {op.value for op in OperationType}


class TransactionManager:
    """
    Gestor de transacciones con capacidad de rollback automático

    Registra todas las operaciones de archivos y permite revertirlas
    en caso de error o por petición del usuario.
    """

    LOG_NAME = "operations_log.jsonl"
    LEGACY_LOG_NAME = "operations_log.json"

    def __init__(self, log_file: Optional[str] = None):
        """
        Inicializa el gestor de transacciones

        Args:
            log_file: Archivo donde se registran las operaciones. Si termina
                en ``.json`` (formato antiguo) se usa el ``.jsonl`` hermano y
                el antiguo se migra una vez.
        """
        legacy_file: Optional[Path] = None
        if log_file is None:
            from src.utils.paths import user_data_dir

            path = user_data_dir() / self.LOG_NAME
            if not path.exists():
                from src.utils.paths import user_data_file

                legacy_file = user_data_file(self.LEGACY_LOG_NAME)
        else:
            path = Path(log_file)
            if path.suffix.lower() == ".json":
                legacy_file = path
                path = path.with_suffix(".jsonl")
            else:
                legacy_file = path.with_suffix(".json")
        self.log_file = path
        self.legacy_log_file = legacy_file

        self._lock = threading.RLock()
        self._handle = None
        self.current_transaction: Optional[str] = None
        self.last_transaction_id: Optional[str] = None
        self.operations: List[Dict[str, Any]] = []
        self.is_transaction_active = False
        self.last_error: Optional[str] = None
        self.last_removal_destination: Optional[str] = None
        self.last_rollback_result: Dict[str, Any] = {}
        self._transactions: Dict[str, Dict[str, Any]] = {}
        self._txn_ops: Dict[str, List[Dict[str, Any]]] = {}
        self._reverted: set = set()
        self._dir_checks: Dict[str, Dict[str, Any]] = {}
        self._known_dirs: set = set()
        self._load_log()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def _load_log(self):
        """Carga el log de operaciones previas (y migra el formato antiguo)"""
        with self._lock:
            self.operations = []
            self._transactions = {}
            self._txn_ops = {}
            self._reverted = set()
            if not self.log_file.exists():
                self._migrate_legacy_log()
            try:
                if self.log_file.exists():
                    with open(self.log_file, "r", encoding="utf-8") as handle:
                        for line in handle:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                record = json.loads(line)
                            except json.JSONDecodeError:
                                # Línea truncada por un cierre inesperado
                                continue
                            if isinstance(record, dict):
                                self.operations.append(record)
                                self._index_record(record)
            except OSError as exc:
                warn(f"No se pudo leer el registro de operaciones: {exc}")
            for txn in self._transactions.values():
                if txn["status"] == STATUS_IN_PROGRESS:
                    txn["status"] = STATUS_INTERRUPTED
            self.last_transaction_id = self.get_last_undoable_transaction_id()

    def _migrate_legacy_log(self):
        """Convierte operations_log.json (JSON completo) en JSONL."""
        legacy = self.legacy_log_file
        if legacy is None or not legacy.exists():
            return
        try:
            with open(legacy, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            operations = data.get("operations", []) if isinstance(data, dict) else []
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            warn(f"No se pudo migrar el registro antiguo {legacy}: {exc}")
            return
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.log_file.with_suffix(".jsonl.tmp")
            with open(tmp, "w", encoding="utf-8") as handle:
                for record in operations:
                    if isinstance(record, dict):
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.replace(tmp, self.log_file)
            info(f"Registro de operaciones migrado a {self.log_file.name} ({len(operations)} entradas)")
        except OSError as exc:
            warn(f"No se pudo escribir el registro migrado: {exc}")
            return
        try:
            legacy.rename(legacy.with_name(legacy.name + ".migrated"))
        except OSError:
            pass

    def _write_record(self, record: Dict[str, Any]):
        line = json.dumps(record, ensure_ascii=False) + "\n"
        try:
            if self._handle is not None:
                self._handle.write(line)
                self._handle.flush()
            else:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_file, "a", encoding="utf-8") as handle:
                    handle.write(line)
        except (OSError, ValueError) as exc:
            warn(f"Error guardando log: {exc}")

    def _append(self, record: Dict[str, Any]):
        with self._lock:
            self.operations.append(record)
            self._index_record(record)
            self._write_record(record)

    def _save_log(self):
        """Reescribe el log completo (solo para compactar, nunca por operación)."""
        with self._lock:
            try:
                tmp = self.log_file.with_suffix(".jsonl.tmp")
                with open(tmp, "w", encoding="utf-8") as handle:
                    for record in self.operations:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                os.replace(tmp, self.log_file)
            except OSError as exc:
                warn(f"Error guardando log: {exc}")

    # ------------------------------------------------------------------
    # Índice en memoria de transacciones
    # ------------------------------------------------------------------
    def _index_record(self, record: Dict[str, Any]):
        record_type = record.get("type")
        txn_id = record.get("transaction_id")
        if record_type == "transaction_begin" and txn_id:
            self._transactions[txn_id] = {
                "id": txn_id,
                "description": record.get("description", ""),
                "timestamp": record.get("timestamp", ""),
                "source_folder": record.get("source_folder", ""),
                "status": STATUS_IN_PROGRESS,
                "ended_at": None,
                "summary": {},
                "moves": 0,
                "bytes": 0,
                "created_dirs": 0,
                "backups": 0,
                "rollbacks": 0,
                "rollback_errors": 0,
            }
            self._txn_ops.setdefault(txn_id, [])
            return

        if record_type in _OPERATION_TYPES:
            if not txn_id:
                return
            ops = self._txn_ops.setdefault(txn_id, [])
            if "op_id" not in record:
                record["op_id"] = f"{txn_id}#{len(ops)}"
            ops.append(record)
            txn = self._transactions.get(txn_id)
            if txn is None:
                return
            details = record.get("details", {})
            if record_type in _REVERTIBLE_TYPES:
                if details.get("role") == ROLE_OVERWRITE_BACKUP:
                    txn["backups"] += 1
                else:
                    txn["moves"] += 1
                    txn["bytes"] += int(details.get("size", 0) or 0)
            elif record_type == OperationType.CREATE_DIR.value:
                txn["created_dirs"] += 1
            return

        txn = self._transactions.get(txn_id) if txn_id else None
        if record_type == "transaction_commit" and txn is not None:
            txn["status"] = record.get("status", STATUS_COMPLETED)
            txn["ended_at"] = record.get("timestamp")
            txn["summary"] = record.get("summary", {}) or {}
        elif record_type == "transaction_rollback" and txn_id:
            reverted = record.get("reverted_ops")
            if reverted is None:
                # Formato antiguo: el rollback no detallaba qué se revirtió
                reverted = [op["op_id"] for op in self._txn_ops.get(txn_id, [])]
            self._reverted.update(reverted)
            if txn is not None:
                txn["rollbacks"] += 1
                txn["rollback_errors"] = int(record.get("errors", 0) or 0)

    def _pending_ops(self, transaction_id: str) -> List[Dict[str, Any]]:
        return [
            op
            for op in self._txn_ops.get(transaction_id, [])
            if op["op_id"] not in self._reverted
        ]

    def _pending_revertible(self, transaction_id: str) -> int:
        pending = 0
        for op in self._pending_ops(transaction_id):
            if op.get("type") in _REVERTIBLE_TYPES:
                pending += 1
            elif op.get("type") == OperationType.DELETE.value and op.get(
                "details", {}
            ).get("operation_type") == "delete_to_quarantine":
                pending += 1
        return pending

    # ------------------------------------------------------------------
    # Ciclo de vida de la transacción
    # ------------------------------------------------------------------
    def begin_transaction(self, description: str = "", source_folder: str = "") -> str:
        """
        Inicia una nueva transacción

        Args:
            description: Descripción de la transacción
            source_folder: Carpeta organizada (se muestra en el historial)

        Returns:
            ID de la transacción
        """
        with self._lock:
            transaction_id = f"txn_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            suffix = 1
            base_id = transaction_id
            while transaction_id in self._transactions:
                transaction_id = f"{base_id}_{suffix}"
                suffix += 1
            self.current_transaction = transaction_id
            self.is_transaction_active = True
            self._dir_checks = {}
            self._known_dirs = set()
            try:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                self._handle = open(self.log_file, "a", encoding="utf-8")
            except OSError as exc:
                warn(f"No se pudo abrir el registro de operaciones: {exc}")
                self._handle = None

            self._append(
                {
                    "type": "transaction_begin",
                    "transaction_id": transaction_id,
                    "description": description,
                    "source_folder": str(source_folder or ""),
                    "timestamp": datetime.now().isoformat(),
                    "operations_count": 0,
                }
            )
            return transaction_id

    def end_transaction(
        self, status: str = STATUS_COMPLETED, summary: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Cierra la transacción actual con el estado indicado."""
        with self._lock:
            if not self.is_transaction_active:
                return False
            transaction_id = self.current_transaction
            self._append(
                {
                    "type": "transaction_commit",
                    "transaction_id": transaction_id,
                    "status": status,
                    "summary": summary or {},
                    "timestamp": datetime.now().isoformat(),
                }
            )
            self.is_transaction_active = False
            self.current_transaction = None
            self._close_handle()
            if self._pending_revertible(transaction_id):
                self.last_transaction_id = transaction_id
            return True

    def commit_transaction(self) -> bool:
        """
        Confirma la transacción actual

        Returns:
            True si se confirmó exitosamente
        """
        return self.end_transaction(STATUS_COMPLETED)

    def _close_handle(self):
        if self._handle is not None:
            try:
                self._handle.close()
            except OSError:
                pass
            self._handle = None

    # ------------------------------------------------------------------
    # Operaciones registradas
    # ------------------------------------------------------------------
    def ensure_directory(self, directory: Path) -> List[Path]:
        """Crea ``directory`` (con sus padres) y registra cada carpeta creada.

        Returns:
            Carpetas creadas, de la más externa a la más interna.
        """
        directory = Path(directory)
        key = normalize(directory)
        if key in self._known_dirs:
            return []
        missing: List[Path] = []
        current = directory
        while not os.path.isdir(long_path(current)):
            missing.append(current)
            if current.parent == current:
                break
            current = current.parent
        created: List[Path] = []
        if missing:
            os.makedirs(long_path(directory), exist_ok=True)
            for folder in reversed(missing):
                self._log_operation(OperationType.CREATE_DIR, {"path": str(folder)})
                created.append(folder)
        self._known_dirs.add(key)
        return created

    def _check_destination(self, dest_dir: Path, required: int, same_device: bool):
        """Comprueba permisos y espacio una vez por carpeta de destino."""
        key = normalize(dest_dir)
        check = self._dir_checks.get(key)
        if check is None:
            if not os.access(long_path(dest_dir), os.W_OK):
                raise PermissionError(f"Sin permisos de escritura: {dest_dir}")
            try:
                free = shutil.disk_usage(long_path(dest_dir)).free
            except OSError:
                free = None
            check = {"free": free}
            self._dir_checks[key] = check
        if same_device or check["free"] is None:
            return
        if required > check["free"]:
            raise IOError(f"Espacio insuficiente: {required} > {check['free']}")
        check["free"] -= required

    def _reset_caches_outside_transaction(self):
        """Las cachés por carpeta solo valen dentro de una transacción."""
        if not self.is_transaction_active:
            self._dir_checks = {}
            self._known_dirs = set()

    def _device_of(self, path: Path) -> Optional[int]:
        try:
            return os.stat(long_path(path)).st_dev
        except OSError:
            return None

    def safe_move_file(self, source: Path, destination: Path, role: str = "") -> bool:
        """
        Mueve un archivo con validación y registro

        Nunca sobrescribe: si el destino existe la operación falla.

        Args:
            source: Ruta origen
            destination: Ruta destino
            role: Marca opcional (``overwrite_backup`` para copias previas)

        Returns:
            True si se movió exitosamente
        """
        source = Path(source)
        destination = Path(destination)
        self._reset_caches_outside_transaction()
        try:
            self.last_error = None
            try:
                source_stat = os.stat(long_path(source))
            except FileNotFoundError:
                raise FileNotFoundError(f"Archivo origen no existe: {source}")

            if os.path.isdir(long_path(source)):
                return self.safe_move_directory(source, destination)

            dest_dir = destination.parent
            self.ensure_directory(dest_dir)
            if os.path.lexists(long_path(destination)):
                raise FileExistsError(f"El destino ya existe: {destination}")

            dest_device = self._dir_checks.get(normalize(dest_dir), {}).get("device")
            if dest_device is None:
                dest_device = self._device_of(dest_dir)
            same_device = dest_device is not None and dest_device == source_stat.st_dev
            required_space = source_stat.st_size
            self._check_destination(dest_dir, required_space, same_device)
            self._dir_checks[normalize(dest_dir)]["device"] = dest_device

            if same_device:
                os.rename(long_path(source), long_path(destination))
            else:
                shutil.move(long_path(source), long_path(destination))

            details = {
                "source": str(source),
                "destination": str(destination),
                "size": required_space,
            }
            if role:
                details["role"] = role
            self._log_operation(OperationType.MOVE, details)
            return True

        except Exception as e:
            self.last_error = str(e)
            error(f"Error moviendo {source}: {e}")
            return False

    def safe_move_directory(self, source: Path, destination: Path) -> bool:
        """Mueve una carpeta completa con ``os.rename`` (misma unidad).

        No hay copia+borrado de respaldo: si la carpeta está en otra unidad o
        contiene archivos en uso, la operación falla sin dejar dos árboles a
        medias y se informa del motivo.
        """
        source = Path(source)
        destination = Path(destination)
        self._reset_caches_outside_transaction()
        try:
            self.last_error = None
            if not os.path.isdir(long_path(source)):
                raise FileNotFoundError(f"La carpeta origen no existe: {source}")
            self.ensure_directory(destination.parent)
            if os.path.lexists(long_path(destination)):
                raise FileExistsError(f"El destino ya existe: {destination}")
            try:
                os.rename(long_path(source), long_path(destination))
            except OSError as exc:
                import errno

                if getattr(exc, "errno", None) == errno.EXDEV or getattr(exc, "winerror", None) == 17:
                    raise OSError(
                        f"La carpeta {source.name} está en otra unidad; las carpetas solo se mueven dentro de la misma unidad"
                    ) from exc
                raise OSError(
                    f"No se pudo mover la carpeta {source.name} (¿archivos abiertos o sin permisos?): {exc}"
                ) from exc
            self._log_operation(
                OperationType.MOVE,
                {
                    "source": str(source),
                    "destination": str(destination),
                    "size": 0,
                    "is_dir": True,
                },
            )
            return True
        except Exception as e:
            self.last_error = str(e)
            error(f"Error moviendo carpeta {source}: {e}")
            return False

    def safe_delete_file(self, file_path: Path, use_trash: bool = True) -> bool:
        """
        Elimina un archivo de forma segura

        Args:
            file_path: Ruta del archivo a eliminar
            use_trash: Si True, mueve a papelera en lugar de eliminar

        Returns:
            True si se eliminó exitosamente
        """
        try:
            self.last_error = None
            self.last_removal_destination = None
            if not file_path.exists():
                raise FileNotFoundError(f"Archivo no existe: {file_path}")

            file_size = file_path.stat().st_size
            destination = None

            if use_trash:
                # Intentar mover a papelera
                try:
                    import send2trash

                    send2trash.send2trash(str(file_path))
                    operation_type = "delete_to_trash"
                except ImportError:
                    # Si send2trash no está disponible, usar cuarentena en lugar de borrado directo
                    destination = self._quarantine_destination(file_path)
                    shutil.move(str(file_path), str(destination))
                    operation_type = "delete_to_quarantine"
                    warn(
                        f"send2trash no disponible; archivo enviado a cuarentena: {destination}"
                    )
            else:
                destination = self._quarantine_destination(file_path)
                shutil.move(str(file_path), str(destination))
                operation_type = "delete_to_quarantine"

            # Registrar operación
            self.last_removal_destination = (
                "papelera" if operation_type == "delete_to_trash" else str(destination)
            )
            self._log_operation(
                OperationType.DELETE,
                {
                    "path": str(file_path),
                    "size": file_size,
                    "operation_type": operation_type,
                    "destination": self.last_removal_destination,
                },
            )

            return True

        except Exception as e:
            self.last_error = str(e)
            error(f"Error eliminando {file_path}: {e}")
            return False

    @staticmethod
    def _quarantine_destination(file_path: Path) -> Path:
        quarantine_dir = file_path.parent / ".quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        destination = quarantine_dir / file_path.name
        counter = 1
        while destination.exists():
            destination = quarantine_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
            counter += 1
        return destination

    def safe_rename_file(self, old_path: Path, new_name: str) -> bool:
        """
        Renombra un archivo de forma segura

        Args:
            old_path: Ruta actual del archivo
            new_name: Nuevo nombre del archivo

        Returns:
            True si se renombró exitosamente
        """
        try:
            self.last_error = None
            if not old_path.exists():
                raise FileNotFoundError(f"Archivo no existe: {old_path}")

            new_path = old_path.parent / new_name

            if new_path.exists():
                raise FileExistsError(f"Ya existe: {new_path}")

            old_path.rename(new_path)

            # Registrar operación
            self._log_operation(
                OperationType.RENAME,
                {
                    "old_path": str(old_path),
                    "new_path": str(new_path),
                    "old_name": old_path.name,
                    "new_name": new_name,
                },
            )

            return True

        except Exception as e:
            self.last_error = str(e)
            error(f"Error renombrando {old_path}: {e}")
            return False

    def _log_operation(self, operation_type: OperationType, details: Dict[str, Any]):
        """
        Registra una operación en el log (una línea añadida al JSONL)

        Args:
            operation_type: Tipo de operación
            details: Detalles específicos de la operación
        """
        operation = {
            "type": operation_type.value,
            "transaction_id": self.current_transaction,
            "timestamp": datetime.now().isoformat(),
            "details": details,
        }
        self._append(operation)

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------
    @staticmethod
    def _free_target(target: Path) -> Path:
        """Si el origen está ocupado, devuelve un nombre libre junto a él."""
        from .organization_conflicts import find_available_name

        if not os.path.lexists(long_path(target)):
            return target
        return find_available_name(target, exists=lambda p: os.path.lexists(long_path(p)))

    def _revert_move(self, current: Path, original: Path, is_dir: bool, result: Dict[str, Any]) -> bool:
        if not os.path.lexists(long_path(current)):
            result["errors"].append(f"No se puede revertir: {current} no existe")
            return False
        target = self._free_target(original)
        if target != original:
            result["renamed"].append((str(original), str(target)))
            result["warnings"].append(
                f"El origen {original} está ocupado; se restauró como {target.name}"
            )
        os.makedirs(long_path(target.parent), exist_ok=True)
        if is_dir or os.path.isdir(long_path(current)):
            os.rename(long_path(current), long_path(target))
        else:
            shutil.move(long_path(current), long_path(target))
        return True

    def rollback_transaction(self, transaction_id: Optional[str] = None) -> bool:
        """
        Revierte una transacción completa

        Solo se revierten las operaciones pendientes: si un rollback anterior
        ya restauró parte de la transacción, no se repite.

        Args:
            transaction_id: ID de la transacción a revertir (None = la actual
                o la última que se puede deshacer)

        Returns:
            True si se revirtió exitosamente
        """
        result: Dict[str, Any] = {
            "transaction_id": transaction_id,
            "reverted": 0,
            "errors": [],
            "warnings": [],
            "renamed": [],
            "already_reverted": False,
        }
        self.last_rollback_result = result
        try:
            with self._lock:
                if transaction_id is None:
                    transaction_id = self.current_transaction or self.get_last_undoable_transaction_id()
                result["transaction_id"] = transaction_id

                if not transaction_id:
                    warn("No hay transacción activa para revertir")
                    return False

                all_ops = self._txn_ops.get(transaction_id, [])
                if not all_ops:
                    warn(f"No se encontraron operaciones para la transacción {transaction_id}")
                    return False

                pending = self._pending_ops(transaction_id)
                if not self._pending_revertible(transaction_id):
                    result["already_reverted"] = True
                    warn(f"La transacción {transaction_id} ya se había deshecho")
                    return False

            reverted_ids: List[str] = []
            for op in reversed(pending):
                op_type = op.get("type")
                details = op.get("details", {})
                try:
                    if op_type == OperationType.MOVE.value:
                        if self._revert_move(
                            Path(details["destination"]),
                            Path(details["source"]),
                            bool(details.get("is_dir")),
                            result,
                        ):
                            reverted_ids.append(op["op_id"])
                    elif op_type == OperationType.RENAME.value:
                        if self._revert_move(
                            Path(details["new_path"]),
                            Path(details["old_path"]),
                            False,
                            result,
                        ):
                            reverted_ids.append(op["op_id"])
                    elif op_type == OperationType.CREATE_DIR.value:
                        folder = Path(details["path"])
                        try:
                            os.rmdir(long_path(folder))
                        except FileNotFoundError:
                            pass
                        except OSError:
                            result["warnings"].append(
                                f"Se conserva la carpeta {folder} porque no está vacía"
                            )
                        reverted_ids.append(op["op_id"])
                    elif op_type == OperationType.DELETE.value:
                        if details.get("operation_type") == "delete_to_quarantine" and details.get(
                            "destination"
                        ):
                            if self._revert_move(
                                Path(details["destination"]),
                                Path(details["path"]),
                                False,
                                result,
                            ):
                                reverted_ids.append(op["op_id"])
                        else:
                            result["errors"].append(
                                f"No se puede recuperar archivo enviado a la papelera: {details.get('path')}"
                            )
                except Exception as e:
                    error(f"Error revirtiendo operación: {e}")
                    result["errors"].append(str(e))

            result["reverted"] = len(reverted_ids)
            # Registrar resultado del rollback
            self._append(
                {
                    "type": "transaction_rollback",
                    "transaction_id": transaction_id,
                    "timestamp": datetime.now().isoformat(),
                    "reverted_operations": len(reverted_ids),
                    "errors": len(result["errors"]),
                    "reverted_ops": reverted_ids,
                }
            )
            if self.last_transaction_id == transaction_id or self.last_transaction_id is None:
                self.last_transaction_id = self.get_last_undoable_transaction_id()

            success(
                f"Rollback completado: {len(reverted_ids)} operaciones revertidas, {len(result['errors'])} errores"
            )
            return not result["errors"]

        except Exception as e:
            error(f"Error durante rollback: {e}")
            result["errors"].append(str(e))
            return False

    def discard_overwrite_backups(self, transaction_id: str) -> int:
        """Envía a la papelera las copias ``.overwrite`` de una transacción.

        Después ya no se podrán restaurar los archivos sustituidos al deshacer.
        Si send2trash no está disponible, las copias se conservan.

        Returns:
            Número de copias enviadas a la papelera.
        """
        try:
            import send2trash
        except ImportError:
            warn("send2trash no disponible; se conservan las copias de seguridad")
            return 0
        discarded = 0
        with self._lock:
            pending = [
                op
                for op in self._pending_ops(transaction_id)
                if op.get("details", {}).get("role") == ROLE_OVERWRITE_BACKUP
            ]
        for op in pending:
            backup = Path(op["details"]["destination"])
            try:
                if backup.exists():
                    send2trash.send2trash(str(backup))
                discarded += 1
            except Exception as exc:
                warn(f"No se pudo enviar a la papelera {backup}: {exc}")
        if discarded:
            self._append(
                {
                    "type": "transaction_backups_discarded",
                    "transaction_id": transaction_id,
                    "timestamp": datetime.now().isoformat(),
                    "count": discarded,
                }
            )
            with self._lock:
                txn = self._transactions.get(transaction_id)
                if txn is not None:
                    txn["backups_discarded"] = True
        return discarded

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def get_transactions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Resumen de las transacciones más recientes (la más nueva primero).

        Cada entrada incluye ``can_undo`` (quedan operaciones por deshacer) y
        ``undo_state``: "no", "parcial" o "deshecha".
        """
        with self._lock:
            result = []
            for txn_id in reversed(list(self._transactions)):
                txn = dict(self._transactions[txn_id])
                pending = self._pending_revertible(txn_id)
                total = txn["moves"] + txn["backups"]
                txn["pending_operations"] = pending
                active = self.is_transaction_active and self.current_transaction == txn_id
                txn["can_undo"] = bool(pending) and not active
                if total == 0:
                    txn["undo_state"] = "no"
                elif pending == 0:
                    txn["undo_state"] = "deshecha"
                elif pending < total:
                    txn["undo_state"] = "parcial"
                else:
                    txn["undo_state"] = "no"
                if total == 0 and txn["created_dirs"] == 0:
                    continue
                result.append(txn)
                if len(result) >= limit:
                    break
            return result

    def get_last_undoable_transaction_id(self) -> Optional[str]:
        """ID de la transacción más reciente que aún se puede deshacer."""
        with self._lock:
            for txn_id in reversed(list(self._transactions)):
                if self.is_transaction_active and self.current_transaction == txn_id:
                    continue
                if self._pending_revertible(txn_id):
                    return txn_id
            return None

    def get_transaction_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Obtiene el historial de transacciones

        Args:
            limit: Número máximo de transacciones a retornar

        Returns:
            Lista de transacciones
        """
        with self._lock:
            transactions = []
            for txn_id in reversed(list(self._transactions)):
                txn = self._transactions[txn_id]
                transactions.append(
                    {
                        "id": txn_id,
                        "description": txn.get("description", ""),
                        "timestamp": txn.get("timestamp", ""),
                        "status": txn.get("status"),
                        "operations": list(self._txn_ops.get(txn_id, [])),
                    }
                )
                if len(transactions) >= limit:
                    break
            return transactions

    def get_statistics(self) -> Dict[str, Any]:
        """
        Obtiene estadísticas de operaciones

        Returns:
            Diccionario con estadísticas
        """
        counts = {"move": 0, "delete": 0, "rename": 0, "rollback": 0, "begin": 0}
        with self._lock:
            for op in self.operations:
                op_type = op.get("type")
                if op_type == OperationType.MOVE.value:
                    counts["move"] += 1
                elif op_type == OperationType.DELETE.value:
                    counts["delete"] += 1
                elif op_type == OperationType.RENAME.value:
                    counts["rename"] += 1
                elif op_type == "transaction_rollback":
                    counts["rollback"] += 1
                elif op_type == "transaction_begin":
                    counts["begin"] += 1

        return {
            "total_operations": counts["move"] + counts["delete"] + counts["rename"],
            "move_operations": counts["move"],
            "delete_operations": counts["delete"],
            "rename_operations": counts["rename"],
            "rollbacks_performed": counts["rollback"],
            "transactions_count": counts["begin"],
        }

    def clear_old_logs(self, days_old: int = 30):
        """
        Limpia logs antiguos (transacciones completas, nunca a medias)

        Args:
            days_old: Días de antigüedad para limpiar
        """
        from datetime import timedelta

        cutoff_date = datetime.now() - timedelta(days=days_old)
        with self._lock:
            old_transactions = set()
            for txn_id, txn in self._transactions.items():
                try:
                    if datetime.fromisoformat(txn["timestamp"]) <= cutoff_date:
                        old_transactions.add(txn_id)
                except (TypeError, ValueError):
                    continue

            kept = []
            for op in self.operations:
                txn_id = op.get("transaction_id")
                if txn_id in old_transactions:
                    continue
                if not txn_id:
                    try:
                        if datetime.fromisoformat(op["timestamp"]) <= cutoff_date:
                            continue
                    except (KeyError, TypeError, ValueError):
                        pass
                kept.append(op)
            self.operations = kept
            self._save_log()
            self._load_log()
        success(f"Logs antiguos limpiados (>{days_old} días)")

    def print_statistics(self):
        """Imprime estadísticas de forma legible"""
        stats = self.get_statistics()

        success(
            f"Operaciones={stats['total_operations']:,}, Movimientos={stats['move_operations']:,}, "
            f"Eliminaciones={stats['delete_operations']:,}, Renombrados={stats['rename_operations']:,}, "
            f"Rollbacks={stats['rollbacks_performed']:,}, Transacciones={stats['transactions_count']:,}"
        )
