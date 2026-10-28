#!/usr/bin/env python3
"""
Gestor de Discos y Particiones para el Organizador de Archivos.

Responsabilidades:
- Enumerar volúmenes (psutil) con tipo de unidad (fijo, extraíble, red,
  óptica, RAM) y unidad del sistema según %SystemDrive%.
- Asociar cada volumen a su disco físico de forma determinista:
  IOCTL_STORAGE_GET_DEVICE_NUMBER → Get-Partition (PowerShell) → WMI.
- Consultar SMART (smartctl) con una única caché con TTL, un Future en vuelo
  por disco y sin tocar nunca el hilo de la interfaz (los llamadores usan
  ``submit_disk_report`` o un worker).
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import psutil

from src.core.health_service import HealthService
from src.core.smart_history import SmartHistory
from src.utils.app_config import AppConfig, get_app_config
from src.utils.formatting import format_bytes
from src.utils.smartctl_wrapper import CREATE_NO_WINDOW, SmartctlWrapper, SmartQuery, is_user_admin

logger = logging.getLogger(__name__)

try:  # pragma: no cover - sólo Windows
    import wmi  # type: ignore
except ImportError:  # pragma: no cover
    wmi = None

DRIVE_TYPE_LABELS = {
    "fixed": "Disco fijo",
    "removable": "Extraíble",
    "network": "Unidad de red",
    "optical": "Unidad óptica",
    "ram": "Disco RAM",
    "unknown": "Desconocido",
}
# Tipos en los que no tiene sentido consultar SMART.
NO_SMART_TYPES = {"network", "optical", "ram"}

# GetDriveTypeW
_WIN_DRIVE_TYPES = {2: "removable", 3: "fixed", 4: "network", 5: "optical", 6: "ram"}

IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
NEGATIVE_MAP_TTL = 60.0
DISKS_SNAPSHOT_TTL = 10.0


def usage_percent(total: int, used: int) -> float:
    """Porcentaje de uso único para toda la aplicación (Inicio y Discos)."""
    if not total or total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, used / total * 100)), 1)


def system_drive_letter() -> str:
    """Letra de la unidad del sistema (%SystemDrive%, no siempre C:)."""
    value = os.environ.get("SystemDrive") or os.environ.get("SYSTEMDRIVE") or "C:"
    return value[:1].upper()


def drive_letter_of(mountpoint: str) -> str:
    """Letra sólo si el punto de montaje es la raíz de una unidad (``D:\\``)."""
    match = re.fullmatch(r"([A-Za-z]):[\\/]?", mountpoint or "")
    return match.group(1).upper() if match else ""


def _normalize(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


@dataclass
class DiskInfo:
    """Información detallada de un disco o partición"""
    device: str
    mountpoint: str
    filesystem: str
    total_size: int
    used_size: int
    free_size: int
    usage_percent: float
    is_system_drive: bool
    is_removable: bool
    drive_letter: str
    drive_type: str = "fixed"
    opts: str = ""

    @property
    def drive_type_label(self) -> str:
        return DRIVE_TYPE_LABELS.get(self.drive_type, DRIVE_TYPE_LABELS["unknown"])

    @property
    def smart_applicable(self) -> bool:
        return self.drive_type not in NO_SMART_TYPES


@dataclass
class DiskReport:
    """Todo lo que la interfaz necesita de un disco, calculado fuera de la UI."""
    mountpoint: str
    disk: Optional[DiskInfo]
    smart: Optional[Dict[str, Any]] = None
    health: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None  # not_applicable | unmapped | unavailable | admin_required | ...
    messages: List[str] = field(default_factory=list)
    physical_disk: Optional[int] = None
    device: Optional[str] = None
    device_type: Optional[str] = None
    history: List[Dict[str, Any]] = field(default_factory=list)
    history_alerts: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def admin_required(self) -> bool:
        return self.error == "admin_required"


# ---------------------------------------------------------------- Windows
def win_drive_type(root: str) -> Optional[str]:
    """GetDriveTypeW; None si no es Windows o falla."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        code = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
    except (AttributeError, OSError):
        return None
    return _WIN_DRIVE_TYPES.get(int(code), "unknown")


def _win_volume_path(mountpoint: str) -> Optional[str]:
    """Ruta de dispositivo del volumen: ``\\\\.\\D:`` o el GUID de un montaje en carpeta."""
    letter = drive_letter_of(mountpoint)
    if letter:
        return f"\\\\.\\{letter}:"
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(64)
        root = mountpoint if mountpoint.endswith("\\") else mountpoint + "\\"
        if ctypes.windll.kernel32.GetVolumeNameForVolumeMountPointW(root, buffer, len(buffer)):
            return buffer.value.rstrip("\\")
    except (AttributeError, OSError):
        return None
    return None


def win_device_number(mountpoint: str) -> Optional[int]:
    """IOCTL_STORAGE_GET_DEVICE_NUMBER sobre el volumen (no requiere administrador)."""
    if sys.platform != "win32":
        return None
    volume = _win_volume_path(mountpoint)
    if not volume:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]

        class STORAGE_DEVICE_NUMBER(ctypes.Structure):
            _fields_ = [("DeviceType", wintypes.DWORD), ("DeviceNumber", wintypes.DWORD),
                        ("PartitionNumber", wintypes.DWORD)]

        handle = kernel32.CreateFileW(volume, 0, 0x1 | 0x2, None, 3, 0, None)
        if not handle or handle == wintypes.HANDLE(-1).value:
            return None
        try:
            number = STORAGE_DEVICE_NUMBER()
            returned = wintypes.DWORD()
            ok = kernel32.DeviceIoControl(handle, IOCTL_STORAGE_GET_DEVICE_NUMBER, None, 0,
                                          ctypes.byref(number), ctypes.sizeof(number),
                                          ctypes.byref(returned), None)
            return int(number.DeviceNumber) if ok else None
        finally:
            kernel32.CloseHandle(handle)
    except (AttributeError, OSError) as exc:
        logger.debug("IOCTL_STORAGE_GET_DEVICE_NUMBER falló para %s: %s", mountpoint, exc)
        return None


def parse_partition_json(stdout: str) -> Dict[str, int]:
    """Salida JSON de Get-Partition → {'C': 0, 'D': 0, 'E': 1}."""
    try:
        data = json.loads(stdout or "null")
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        data = [data]
    mapping: Dict[str, int] = {}
    for item in data or []:
        if not isinstance(item, dict):
            continue
        letter = item.get("DriveLetter")
        number = item.get("DiskNumber")
        if isinstance(letter, int):  # [char] serializado como número
            letter = chr(letter) if letter > 0 else ""
        if isinstance(letter, str) and letter.strip("\x00 ") and isinstance(number, int):
            mapping[letter.strip("\x00 ")[0].upper()] = number
    return mapping


def powershell_partition_map(timeout: float = 15) -> Dict[str, int]:
    """Get-Partition | Select DriveLetter, DiskNumber (sólo Windows)."""
    if sys.platform != "win32":
        return {}
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if not executable:
        return {}
    script = ("Get-Partition | Where-Object { $_.DriveLetter } | "
              "Select-Object @{n='DriveLetter';e={[string]$_.DriveLetter}},DiskNumber | "
              "ConvertTo-Json -Compress")
    try:
        result = subprocess.run(
            [executable, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.debug("Get-Partition falló: %s", exc)
        return {}
    return parse_partition_json(result.stdout) if result.returncode == 0 else {}


def summarize_top_level(path: str, max_items: int = 10000) -> Dict[str, Any]:
    """Resumen rápido del primer nivel de una carpeta (para el panel de Discos).

    Se ejecuta siempre en un hilo de trabajo; nunca recorre subcarpetas.
    """
    from datetime import datetime, timedelta

    summary: Dict[str, Any] = {"total_files": 0, "total_dirs": 0, "total_size": 0, "file_types": {},
                               "large_files": [], "recent_files_count": 0, "old_files_count": 0,
                               "analysis_limit_reached": False}
    now = datetime.now().timestamp()
    week_ago = now - timedelta(days=7).total_seconds()
    month_ago = now - timedelta(days=30).total_seconds()
    count = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if count >= max_items:
                    summary["analysis_limit_reached"] = True
                    break
                count += 1
                try:
                    if entry.is_dir(follow_symlinks=False):
                        summary["total_dirs"] += 1
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                summary["total_files"] += 1
                summary["total_size"] += info.st_size
                ext = os.path.splitext(entry.name)[1].lower() or "sin_extension"
                summary["file_types"][ext] = summary["file_types"].get(ext, 0) + 1
                if info.st_size > 100 * 1024 * 1024:
                    summary["large_files"].append({"name": entry.name, "size": info.st_size, "path": entry.path})
                if info.st_mtime > week_ago:
                    summary["recent_files_count"] += 1
                elif info.st_mtime < month_ago:
                    summary["old_files_count"] += 1
    except OSError as exc:
        logger.debug("No se pudo resumir %s: %s", path, exc)
        return {}
    summary["large_files"] = sorted(summary["large_files"], key=lambda item: item["size"], reverse=True)[:10]
    return summary


class DiskManager:
    """Gestor principal de discos y particiones del sistema"""

    def __init__(self, app_config: Optional[AppConfig] = None, smartctl: Optional[SmartctlWrapper] = None,
                 history: Optional[SmartHistory] = None):
        self.safe_mode = True  # Por defecto en modo seguro (solo lectura)
        self.app_config = app_config or get_app_config()
        self.health_service = HealthService(self.app_config)
        disks_cfg = self.app_config.get("disks", {}) or {}
        self.smart_ttl = float(disks_cfg.get("smart_cache_ttl", 120))
        self.smart_timeout = float(disks_cfg.get("smart_timeout", 20))
        self._history_enabled = bool(disks_cfg.get("smart_history", True))
        self.history = history if history is not None else (SmartHistory() if self._history_enabled else None)

        self._disks_cache: Optional[List[DiskInfo]] = None
        self._disks_cache_time = 0.0
        self._lock = threading.RLock()
        # mountpoint normalizado -> (número de disco o None, instante)
        self._drive_map: Dict[str, Tuple[Optional[int], float]] = {}
        self._partition_map: Optional[Dict[str, int]] = None
        self._wmi_map: Optional[Dict[str, str]] = None
        self._scan: Optional[List[Dict[str, Any]]] = None
        # Caché única de informes SMART: clave de disco -> (DiskReport, instante)
        self._reports: Dict[str, Tuple[DiskReport, float]] = {}
        self._inflight: Dict[str, Future] = {}
        # Consultas smartctl por disco físico: varias letras comparten una sola.
        self._queries: Dict[int, Tuple[SmartQuery, float]] = {}
        self._query_inflight: Dict[int, Future] = {}
        self._closed = False
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="smartctl")
        self.wmi_service = None
        self.smartctl = smartctl or SmartctlWrapper()
        if not self.smartctl.is_available():
            logger.warning("smartctl no disponible: la salud SMART no se podrá consultar")
        atexit.register(self.shutdown)

    # ------------------------------------------------------------ ciclo de vida
    def shutdown(self) -> None:
        """Cancela trabajos pendientes y mata smartctl en curso (idempotente)."""
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.smartctl.shutdown()
        with self._lock:
            for future in self._inflight.values():
                future.cancel()
            self._inflight.clear()

    # --------------------------------------------------------------- volúmenes
    def _drive_type(self, partition) -> str:
        mountpoint = partition.mountpoint
        opts = (getattr(partition, "opts", "") or "").lower()
        detected = win_drive_type(mountpoint if mountpoint.endswith(("\\", "/")) else mountpoint + "\\")
        if detected:
            return detected
        fstype = (getattr(partition, "fstype", "") or "").lower()
        if "cdrom" in opts or fstype in {"cdfs", "udf", "iso9660"}:
            return "optical"
        if "remote" in opts or fstype in {"nfs", "nfs4", "cifs", "smbfs", "smb3", "sshfs", "fuse.sshfs"}:
            return "network"
        if "removable" in opts:
            return "removable"
        if fstype in {"tmpfs", "ramfs"}:
            return "ram"
        return "fixed"

    def _is_system_drive(self, mountpoint: str) -> bool:
        if sys.platform == "win32" or drive_letter_of(mountpoint):
            letter = drive_letter_of(mountpoint)
            return bool(letter) and letter == system_drive_letter()
        return os.path.normpath(mountpoint) == os.path.sep

    def _is_removable_drive(self, device: str) -> bool:
        """Compatibilidad: True si GetDriveTypeW indica unidad extraíble."""
        return win_drive_type(device if device.endswith("\\") else device + "\\") == "removable"

    def _extract_drive_letter(self, mountpoint: str) -> str:
        return drive_letter_of(mountpoint)

    def get_all_disks(self) -> List[DiskInfo]:
        """Enumera los volúmenes (siempre lee de nuevo; refresca la instantánea)."""
        disks: List[DiskInfo] = []
        try:
            partitions = psutil.disk_partitions(all=False)
        except OSError as exc:
            logger.error("Error al enumerar particiones: %s", exc)
            raise
        for partition in partitions:
            drive_type = self._drive_type(partition)
            if drive_type == "optical":
                # Lectores vacíos lanzan errores; con disco sólo informan.
                if not os.path.exists(partition.mountpoint):
                    continue
            try:
                usage = psutil.disk_usage(partition.mountpoint)
            except (PermissionError, OSError):
                continue
            disks.append(DiskInfo(
                device=partition.device,
                mountpoint=partition.mountpoint,
                filesystem=partition.fstype or "Desconocido",
                total_size=usage.total,
                used_size=usage.used,
                free_size=usage.free,
                usage_percent=usage_percent(usage.total, usage.used),
                is_system_drive=self._is_system_drive(partition.mountpoint),
                is_removable=drive_type == "removable",
                drive_letter=drive_letter_of(partition.mountpoint),
                drive_type=drive_type,
                opts=getattr(partition, "opts", "") or "",
            ))
        disks.sort(key=lambda disk: (disk.drive_letter or "~", disk.mountpoint))
        with self._lock:
            self._disks_cache = disks
            self._disks_cache_time = time.monotonic()
        return disks

    def _disks_snapshot(self) -> List[DiskInfo]:
        with self._lock:
            fresh = self._disks_cache is not None and time.monotonic() - self._disks_cache_time < DISKS_SNAPSHOT_TTL
            if fresh:
                return list(self._disks_cache)
        try:
            return self.get_all_disks()
        except OSError:
            return list(self._disks_cache or [])

    def get_disk_info(self, path: str) -> Optional[DiskInfo]:
        """Volumen que contiene ``path``: el punto de montaje más específico.

        Usa la instantánea en caché; no vuelve a enumerar en cada llamada.
        """
        try:
            target = _normalize(path)
        except (TypeError, ValueError):
            return None
        best: Optional[DiskInfo] = None
        best_len = -1
        for disk in self._disks_snapshot():
            mount = _normalize(disk.mountpoint)
            prefix = mount if mount.endswith(os.sep) else mount + os.sep
            if (target == mount or target.startswith(prefix)) and len(mount) > best_len:
                best, best_len = disk, len(mount)
        return best

    # -------------------------------------------------------- disco físico
    def _get_or_create_drive_map(self) -> Dict[str, str]:
        """Mapa WMI letra → PHYSICALDRIVEn (último recurso). Cachea también el fallo."""
        with self._lock:
            if self._wmi_map is not None:
                return self._wmi_map
            self._wmi_map = {}
            if sys.platform != "win32" or wmi is None:
                return self._wmi_map
            try:
                try:
                    import pythoncom  # type: ignore

                    pythoncom.CoInitialize()
                except ImportError:
                    pass
                self.wmi_service = wmi.WMI()
                self._wmi_map = self._map_logical_to_physical_drives()
            except Exception as exc:  # WMI lanza excepciones COM propias
                logger.warning("WMI no disponible para el mapeo de discos: %s", exc)
                self.wmi_service = None
            return self._wmi_map

    def _map_logical_to_physical_drives(self) -> Dict[str, str]:
        drive_map: Dict[str, str] = {}
        if not self.wmi_service:
            return drive_map
        for physical_disk in self.wmi_service.Win32_DiskDrive():
            key = physical_disk.DeviceID.replace("\\\\.\\", "").upper()
            for partition in physical_disk.associators("Win32_DiskDriveToDiskPartition"):
                for logical_disk in partition.associators("Win32_LogicalDiskToPartition"):
                    drive_map[logical_disk.DeviceID.upper()] = key
        return drive_map

    def resolve_physical_disk(self, mountpoint: str) -> Optional[int]:
        """Número de disco físico del volumen, con caché y caché negativa con TTL.

        Varias letras pueden apuntar al mismo disco. Nunca se usan tamaños.
        """
        key = _normalize(mountpoint)
        with self._lock:
            cached = self._drive_map.get(key)
            if cached is not None:
                number, stamp = cached
                if number is not None or time.monotonic() - stamp < NEGATIVE_MAP_TTL:
                    return number
        number = win_device_number(mountpoint)
        letter = drive_letter_of(mountpoint)
        if number is None and letter:
            with self._lock:
                partition_map = self._partition_map
            if partition_map is None:
                partition_map = powershell_partition_map()
                with self._lock:
                    self._partition_map = partition_map
            number = partition_map.get(letter)
        if number is None and letter:
            physical = self._get_or_create_drive_map().get(f"{letter}:")
            match = re.search(r"(\d+)$", physical or "")
            number = int(match.group(1)) if match else None
        with self._lock:
            self._drive_map[key] = (number, time.monotonic())
        return number

    def _smart_target(self, number: int) -> Tuple[str, Optional[str]]:
        """Dispositivo y tipo ``-d`` de smartctl para el disco físico ``number``."""
        with self._lock:
            scan = self._scan
        if scan is None:
            scan = self.smartctl.scan_all_disks()
            with self._lock:
                self._scan = scan
        for entry in scan:
            if entry.get("physical_index") == number:
                return entry["device"], entry.get("type")
        return f"/dev/pd{number}", None

    # ------------------------------------------------------------- SMART
    def _report_key(self, disk: Optional[DiskInfo], mountpoint: str) -> str:
        return _normalize(disk.mountpoint if disk else mountpoint)

    def get_cached_report(self, mountpoint: str) -> Optional[DiskReport]:
        disk = self.get_disk_info(mountpoint)
        key = self._report_key(disk, mountpoint)
        with self._lock:
            entry = self._reports.get(key)
        if entry and time.monotonic() - entry[1] < self.smart_ttl:
            return entry[0]
        return None

    def submit_disk_report(self, mountpoint: str, force: bool = False) -> Future:
        """Future con el DiskReport; reutiliza el que ya esté en vuelo para ese disco."""
        disk = self.get_disk_info(mountpoint)
        key = self._report_key(disk, mountpoint)
        with self._lock:
            if not force:
                entry = self._reports.get(key)
                if entry and time.monotonic() - entry[1] < self.smart_ttl:
                    done: Future = Future()
                    done.set_result(entry[0])
                    return done
            inflight = self._inflight.get(key)
            if inflight is not None and not inflight.done():
                return inflight
            if self._closed:
                cancelled: Future = Future()
                cancelled.cancel()
                return cancelled
            future = self._executor.submit(self._build_report, mountpoint, disk, key)
            self._inflight[key] = future

        def _cleanup(done_future, cache_key=key):
            with self._lock:
                if self._inflight.get(cache_key) is done_future:
                    del self._inflight[cache_key]
        future.add_done_callback(_cleanup)
        return future

    def get_disk_report(self, mountpoint: str, force: bool = False, timeout: Optional[float] = None) -> DiskReport:
        """Versión bloqueante (para workers y tests). No llamar desde la UI."""
        return self.submit_disk_report(mountpoint, force=force).result(timeout=timeout)

    def _build_report(self, mountpoint: str, disk: Optional[DiskInfo], key: str) -> DiskReport:
        report = DiskReport(mountpoint=mountpoint, disk=disk)
        try:
            self._fill_report(report)
        except Exception as exc:  # El informe nunca debe tumbar el worker
            logger.exception("Error obteniendo SMART para %s", mountpoint)
            report.error = "error"
            report.messages.append(str(exc))
            report.health = {"available": False, "status": "Error al leer SMART", "score": None, "factors": []}
        with self._lock:
            self._reports[key] = (report, time.monotonic())
        return report

    def _fill_report(self, report: DiskReport) -> None:
        disk = report.disk
        unavailable = {"available": False, "score": None, "factors": []}
        if disk is None:
            report.error = "no_disk"
            report.health = {**unavailable, "status": "Unidad no encontrada"}
            return
        if not disk.smart_applicable:
            report.error = "not_applicable"
            report.health = {**unavailable, "status": f"SMART no aplica a {disk.drive_type_label.lower()}"}
            return
        if not self.smartctl.is_available():
            report.error = "unavailable"
            report.health = {**unavailable, "status": "smartctl no disponible"}
            return
        number = self.resolve_physical_disk(disk.mountpoint)
        if number is None:
            report.error = "unmapped"
            report.health = {**unavailable, "status": "No se pudo asociar la unidad a un disco físico"}
            return
        report.physical_disk = number
        device, device_type = self._smart_target(number)
        report.device, report.device_type = device, device_type
        self._apply_query(report, self._query_disk(number, device, device_type))

    def _query_disk(self, number: int, device: str, device_type: Optional[str]) -> SmartQuery:
        """Un único smartctl en vuelo por disco físico, con la misma TTL que los informes."""
        with self._lock:
            entry = self._queries.get(number)
            if entry and time.monotonic() - entry[1] < self.smart_ttl:
                return entry[0]
            future = self._query_inflight.get(number)
            owner = future is None
            if owner:
                future = Future()
                self._query_inflight[number] = future
        if not owner:
            return future.result()
        try:
            query = self.smartctl.query(device, timeout=self.smart_timeout, device_type=device_type)
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._query_inflight.pop(number, None)
        with self._lock:
            self._queries[number] = (query, time.monotonic())
        future.set_result(query)
        return query

    def _apply_query(self, report: DiskReport, query: SmartQuery) -> None:
        report.messages = list(query.messages)
        if not query.ok:
            report.error = query.error or "error"
            status = {
                "admin_required": "Se necesitan permisos de administrador para leer SMART",
                "timeout": "El disco no respondió a tiempo",
                "open_failed": "No se pudo abrir el dispositivo",
            }.get(report.error, "Datos SMART no disponibles")
            report.health = {"available": False, "score": None, "factors": [], "status": status,
                             "admin_required": report.error == "admin_required"}
            return
        report.error = None
        report.smart = query.data
        report.health = self._health_dict(query.data, report.disk)
        if self.history is not None:
            report.history_alerts = self.history.record(query.data)
            report.history = self.history.trend(query.data)
            if report.history_alerts:
                report.health.setdefault("alerts", []).extend(report.history_alerts)

    def _health_dict(self, smart: Dict[str, Any], disk: DiskInfo) -> Dict[str, Any]:
        try:
            result = self.health_service.calculate_health(smart, disk)
        except (TypeError, ValueError, KeyError) as exc:
            logger.warning("No se pudo calcular la salud: %s", exc)
            return {"available": False, "score": None, "factors": [], "status": "No se pudo calcular la salud"}
        return {
            "status": result.status,
            "available": result.available,
            "score": result.score,
            "level": result.level,
            "factors": result.factors,
            "temp_score": result.temp_score,
            "tbw_score": result.tbw_score,
            "hours_score": result.hours_score,
            "cycles_score": result.cycles_score,
            "wear_score": result.wear_score,
            "device_type": result.device_type,
            "temperature": result.temperature,
            "power_on_hours": result.power_on_hours,
            "power_cycles": result.power_cycles,
            "tbw": result.tbw,
            "sectors": result.sectors,
            "alerts": list(result.alerts),
        }

    def retry_elevated(self, mountpoints: List[str]) -> Dict[str, DiskReport]:
        """Relanza smartctl elevado (UAC) para las unidades indicadas.

        Bloquea hasta que termina: llamar desde un hilo de trabajo.
        """
        targets = []
        pending: Dict[str, List[DiskReport]] = {}
        for mountpoint in mountpoints:
            disk = self.get_disk_info(mountpoint)
            report = DiskReport(mountpoint=mountpoint, disk=disk)
            if disk is None or not disk.smart_applicable:
                continue
            number = self.resolve_physical_disk(disk.mountpoint)
            if number is None:
                continue
            device, device_type = self._smart_target(number)
            report.physical_disk, report.device, report.device_type = number, device, device_type
            if device not in pending:
                targets.append((device, device_type))
            pending.setdefault(device, []).append(report)
        results = self.smartctl.query_elevated(targets) if targets else {}
        reports: Dict[str, DiskReport] = {}
        for device, items in pending.items():
            query = results.get(device) or SmartQuery(device=device, error="cancelled")
            if query.ok and items[0].physical_disk is not None:
                with self._lock:
                    self._queries[items[0].physical_disk] = (query, time.monotonic())
            for report in items:
                self._apply_query(report, query)
                with self._lock:
                    self._reports[self._report_key(report.disk, report.mountpoint)] = (report, time.monotonic())
                reports[report.mountpoint] = report
        return reports

    def invalidate(self) -> None:
        """Olvida mapeos y SMART cacheados (botón Actualizar)."""
        with self._lock:
            self._reports.clear()
            self._queries.clear()
            self._drive_map.clear()
            self._partition_map = None
            self._scan = None

    @staticmethod
    def needs_admin_hint() -> bool:
        return not is_user_admin()

    # --------------------------------------------- API de compatibilidad
    def prefetch_smart_for_disks(self, paths: List[str]) -> None:
        """Precarga en segundo plano (no bloquea)."""
        for path in paths or ():
            self.submit_disk_report(path)

    def get_disk_io_stats(self, path: str) -> Optional[dict]:
        """Datos SMART del disco (bloqueante: sólo desde hilos de trabajo)."""
        return self.get_disk_report(path).smart

    def get_disk_health_status(self, path: str) -> Dict[str, Any]:
        """Estado de salud (bloqueante: sólo desde hilos de trabajo)."""
        try:
            return self.get_disk_report(path).health
        except Exception as exc:  # Nunca "CRÍTICO 0/100" por una excepción
            logger.exception("Error al obtener estado de salud de %s", path)
            return {"status": "Error al leer SMART", "score": None, "factors": [], "available": False,
                    "error": str(exc)}

    def get_safe_mode_status(self) -> bool:
        return self.safe_mode

    def set_safe_mode(self, enabled: bool) -> bool:
        self.safe_mode = bool(enabled)
        return True

    def format_size(self, size_bytes: int) -> str:
        return format_bytes(size_bytes)
