"""
Wrapper para smartctl: obtiene datos SMART reales (lifetime) de los discos.

Notas importantes:
- El código de retorno de smartctl es una máscara de bits. Solo los bits 0 y 1
  impiden interpretar la salida; los bits 2-7 son avisos o señales de salud
  (bit 3: el disco informa de fallo; 4/5: atributos por debajo del umbral;
  6: registro de errores; 7: errores en autodiagnósticos).
- Se usan los campos normalizados del JSON (``temperature.current``,
  ``power_on_time.hours``, ``power_cycle_count``) y sólo se recurre a los
  atributos crudos cuando faltan.
- Todos los procesos se lanzan sin ventana, con UTF-8 y registrados para poder
  matarlos al cerrar la aplicación (``shutdown``).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0

# Bits del código de retorno de smartctl (man smartctl, "RETURN VALUES").
RC_CMDLINE_ERROR = 1 << 0
RC_OPEN_FAILED = 1 << 1
RC_COMMAND_FAILED = 1 << 2
RC_DISK_FAILING = 1 << 3
RC_PREFAIL_BELOW_THRESHOLD = 1 << 4
RC_PAST_BELOW_THRESHOLD = 1 << 5
RC_ERROR_LOG = 1 << 6
RC_SELFTEST_ERRORS = 1 << 7

SMART_FLAG_BITS = {
    "command_failed": RC_COMMAND_FAILED,
    "failing": RC_DISK_FAILING,
    "prefail_threshold": RC_PREFAIL_BELOW_THRESHOLD,
    "past_threshold": RC_PAST_BELOW_THRESHOLD,
    "error_log": RC_ERROR_LOG,
    "selftest_errors": RC_SELFTEST_ERRORS,
}

SMART_FLAG_TEXT = {
    "failing": "El propio disco informa de fallo inminente (SMART FAILING)",
    "prefail_threshold": "Hay atributos de prefallo por debajo del umbral",
    "past_threshold": "Algún atributo estuvo por debajo del umbral en el pasado",
    "error_log": "El registro de errores del disco contiene entradas",
    "selftest_errors": "El registro de autodiagnósticos contiene errores",
}

# Atributos ATA críticos para la integridad de los datos.
CRITICAL_ATA_ATTRIBUTES = {
    5: "reallocated_sectors",
    187: "reported_uncorrect",
    197: "pending_sectors",
    198: "uncorrectable_sectors",
    199: "crc_errors",
}

_ADMIN_PATTERNS = (
    "access denied",
    "access is denied",
    "permission denied",
    "administrator",
    "requires root",
    "root privilege",
    "operation not permitted",
    "acceso denegado",
)

_SAFE_DEVICE = re.compile(r"^/dev/[A-Za-z0-9,]+$")
_SAFE_TYPE = re.compile(r"^[A-Za-z0-9,+_-]+$")
_FIRST_INT = re.compile(r"-?\d+")


def is_user_admin() -> bool:
    """True si el proceso tiene privilegios de administrador (o root)."""
    if sys.platform == "win32":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def decode_smart_flags(returncode: Optional[int]) -> Dict[str, bool]:
    """Traduce los bits 2-7 del código de retorno a señales con nombre."""
    rc = int(returncode or 0)
    return {name: bool(rc & bit) for name, bit in SMART_FLAG_BITS.items()}


def physical_drive_to_device(physical_drive: str) -> str:
    """'PHYSICALDRIVE3' -> '/dev/pd3'; rutas /dev/... se devuelven tal cual."""
    text = (physical_drive or "").strip()
    upper = text.upper()
    if "PHYSICALDRIVE" in upper:
        number = upper.split("PHYSICALDRIVE", 1)[1].strip()
        return f"/dev/pd{number}"
    return text


def device_to_physical_index(device: str) -> Optional[int]:
    """Índice de disco físico de Windows para /dev/pdN y /dev/sdX (sda = 0).

    /dev/nvmeN y /dev/csmiX,Y no corresponden a un número de disco físico, por
    lo que devuelven None.
    """
    match = re.fullmatch(r"/dev/pd(\d+)", device or "")
    if match:
        return int(match.group(1))
    match = re.fullmatch(r"/dev/sd([a-z]{1,2})", device or "")
    if match:
        letters = match.group(1)
        if len(letters) == 1:
            return ord(letters) - ord("a")
        return (ord(letters[0]) - ord("a") + 1) * 26 + ord(letters[1]) - ord("a")
    return None


def parse_scan_output(stdout: str) -> List[Dict[str, Any]]:
    """Parsea ``smartctl --scan`` (formatos /dev/sda -d ata, /dev/nvme0 -d nvme,
    /dev/csmi0,1 -d ata, /dev/pd0 ...), conservando el tipo ``-d``."""
    disks = []
    for line in (stdout or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("#", 1)[0].split()
        if not parts or not parts[0].startswith("/dev/"):
            continue
        device = parts[0]
        device_type = None
        if "-d" in parts:
            index = parts.index("-d")
            if index + 1 < len(parts):
                device_type = parts[index + 1]
        physical_index = device_to_physical_index(device)
        disks.append({
            "device": device,
            "type": device_type,
            "physical_index": physical_index,
            "physical_drive": f"PHYSICALDRIVE{physical_index}" if physical_index is not None else None,
            "raw_line": stripped,
        })
    return disks


def _raw_int(attribute: Dict[str, Any]) -> Optional[int]:
    raw = attribute.get("raw") or {}
    value = raw.get("value")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _raw_string_int(attribute: Dict[str, Any]) -> Optional[int]:
    text = (attribute.get("raw") or {}).get("string")
    if not isinstance(text, str):
        return None
    match = _FIRST_INT.search(text)
    return int(match.group()) if match else None


def decode_temperature_raw(attribute: Dict[str, Any]) -> Optional[int]:
    """Temperatura del atributo 194: el raw suele venir empaquetado (min/max)."""
    from_string = _raw_string_int(attribute)
    if from_string is not None and -40 <= from_string <= 150:
        return from_string
    raw = _raw_int(attribute)
    if raw is None:
        return None
    for mask in (0xFFFF, 0xFF):
        value = raw & mask
        if 0 < value <= 150:
            return value
    return None


def decode_power_on_hours_raw(attribute: Dict[str, Any]) -> Optional[int]:
    """Horas del atributo 9. Seagate empaqueta milisegundos en los bits altos."""
    raw = _raw_int(attribute)
    if raw is None:
        return None
    name = (attribute.get("name") or "").lower()
    value = raw & 0xFFFFFFFF
    if "half_minutes" in name:
        return value // 120
    if "minutes" in name:
        return value // 60
    if "seconds" in name:
        return value // 3600
    return value


def lba_unit_bytes(name: str, logical_block_size: int = 512) -> Optional[int]:
    """Bytes por unidad de los atributos 241/242/246 según su nombre."""
    lowered = (name or "").lower()
    if "32mib" in lowered:
        return 32 * 1024 ** 2
    if "gib" in lowered or lowered.endswith("_gb") or "_gb_" in lowered:
        return 1024 ** 3
    if "mib" in lowered or lowered.endswith("_mb"):
        return 1024 ** 2
    if "lba" in lowered or "sectors" in lowered:
        return max(512, int(logical_block_size or 512))
    return None


@dataclass
class SmartQuery:
    """Resultado de una consulta a smartctl."""

    device: str
    returncode: Optional[int] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None  # admin_required | open_failed | timeout | parse_error | unavailable | cancelled | cmdline
    messages: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.data is not None

    @property
    def admin_required(self) -> bool:
        return self.error == "admin_required"


class SmartctlWrapper:
    """Wrapper para interactuar con smartctl."""

    def __init__(self, smartctl_path: Optional[str] = None):
        self._processes: set = set()
        self._process_lock = threading.Lock()
        self._closed = False
        self.smartctl_path = smartctl_path or self._find_smartctl()

    # ------------------------------------------------------------------ setup
    def _find_smartctl(self) -> Optional[str]:
        """Busca smartctl en bin/ del proyecto (o del ejecutable) y en el PATH."""
        if getattr(sys, "frozen", False):
            base_path = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        else:
            base_path = Path(__file__).resolve().parent.parent.parent
        names = ("smartctl.exe",) if sys.platform == "win32" else ("smartctl", "smartctl.exe")
        for name in names:
            candidate = base_path / "bin" / name
            if candidate.is_file() and (sys.platform == "win32" or name == "smartctl"):
                logger.info("smartctl encontrado en %s", candidate)
                return str(candidate)
        for name in names:
            found = shutil.which(name)
            if found:
                logger.info("smartctl encontrado en PATH: %s", found)
                return found
        logger.warning("smartctl no encontrado. Coloca smartctl.exe en la carpeta bin/")
        return None

    def is_available(self) -> bool:
        return self.smartctl_path is not None and not self._closed

    # ------------------------------------------------------------- procesos
    def _run(self, args: List[str], timeout: float) -> Tuple[int, str, str]:
        """Ejecuta smartctl registrando el proceso para poder matarlo al cerrar."""
        if self._closed:
            raise RuntimeError("smartctl cerrado")
        process = subprocess.Popen(
            [self.smartctl_path, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        with self._process_lock:
            self._processes.add(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return process.returncode, stdout or "", stderr or ""
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        finally:
            with self._process_lock:
                self._processes.discard(process)

    def shutdown(self) -> None:
        """Mata los smartctl en curso e impide lanzar más (idempotente)."""
        self._closed = True
        with self._process_lock:
            processes = list(self._processes)
            self._processes.clear()
        for process in processes:
            try:
                if process.poll() is None:
                    process.kill()
            except OSError as exc:
                logger.debug("No se pudo terminar smartctl: %s", exc)

    # ------------------------------------------------------------ consultas
    def query(self, physical_drive: str, timeout: float = 10, device_type: Optional[str] = None,
              max_retries: int = 1) -> SmartQuery:
        """Consulta SMART completa (-a -j) con diagnóstico del error."""
        device = physical_drive_to_device(physical_drive)
        query = SmartQuery(device=device)
        if not self.is_available():
            query.error = "unavailable"
            return query
        args = ["-a", "-j"]
        if device_type:
            args += ["-d", device_type]
        args.append(device)
        for attempt in range(max_retries + 1):
            try:
                rc, stdout, stderr = self._run(args, timeout + attempt * 5)
            except subprocess.TimeoutExpired:
                logger.warning("Timeout ejecutando smartctl para %s (intento %d)", device, attempt + 1)
                query.error = "timeout"
                continue
            except (OSError, RuntimeError) as exc:
                query.error = "cancelled" if self._closed else "unavailable"
                logger.warning("No se pudo ejecutar smartctl: %s", exc)
                return query
            return self.interpret_output(device, rc, stdout, stderr)
        return query

    def interpret_output(self, device: str, returncode: int, stdout: str, stderr: str = "") -> SmartQuery:
        """Convierte la salida de smartctl en un SmartQuery (sin ejecutar nada)."""
        query = SmartQuery(device=device, returncode=returncode)
        raw = None
        if stdout and stdout.strip():
            try:
                raw = json.loads(stdout)
            except json.JSONDecodeError:
                raw = None
        if isinstance(raw, dict):
            query.messages = [
                str(message.get("string", ""))
                for message in (raw.get("smartctl") or {}).get("messages", [])
                if isinstance(message, dict)
            ]
        text = " ".join(query.messages + [stderr or ""]).lower()
        if returncode & RC_CMDLINE_ERROR:
            query.error = "cmdline"
            return query
        if returncode & RC_OPEN_FAILED:
            needs_admin = any(pattern in text for pattern in _ADMIN_PATTERNS)
            if not needs_admin and not text.strip() and not is_user_admin():
                needs_admin = sys.platform == "win32"
            query.error = "admin_required" if needs_admin else "open_failed"
            return query
        if not isinstance(raw, dict):
            query.error = "parse_error"
            return query
        parsed = self._parse_smart_json(raw)
        parsed["smart_flags"] = decode_smart_flags(returncode)
        parsed["smartctl_returncode"] = returncode
        parsed["smartctl_messages"] = query.messages
        self._sanitize(parsed)
        query.data = parsed
        return query

    def get_disk_smart_data(self, physical_drive: str, timeout: int = 10, max_retries: int = 1,
                            device_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Compatibilidad: datos SMART parseados o None."""
        return self.query(physical_drive, timeout=timeout, device_type=device_type,
                          max_retries=max_retries).data

    # --------------------------------------------------------------- parseo
    def _parse_smart_json(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extrae los datos relevantes del JSON de smartctl."""
        smart_status = data.get("smart_status")
        passed = smart_status.get("passed") if isinstance(smart_status, dict) else None
        result: Dict[str, Any] = {
            "disk_model": data.get("model_name") or data.get("model_family") or "Desconocido",
            "serial_number": data.get("serial_number", "N/A"),
            "firmware": data.get("firmware_version", "N/A"),
            # Sin smart_status (puentes USB, RAID) el estado es desconocido, no fallo.
            "smart_status": passed if isinstance(passed, bool) else None,
            "device_type": None,
            "media_label": None,
            "temperature": None,
            "power_on_hours": None,
            "power_cycles": None,
            "read_bytes": None,
            "write_bytes": None,
            "read_count": None,
            "write_count": None,
            "health_percentage": None,
            "critical_attributes": {},
            "failing_attributes": [],
        }

        temperature = data.get("temperature")
        if isinstance(temperature, dict) and isinstance(temperature.get("current"), (int, float)):
            result["temperature"] = int(temperature["current"])
        power_on = data.get("power_on_time")
        if isinstance(power_on, dict) and isinstance(power_on.get("hours"), (int, float)):
            result["power_on_hours"] = int(power_on["hours"])
        if isinstance(data.get("power_cycle_count"), (int, float)):
            result["power_cycles"] = int(data["power_cycle_count"])

        protocol = ((data.get("device") or {}).get("protocol") or "").lower()
        if "nvme_smart_health_information_log" in data or protocol == "nvme":
            self._parse_nvme(data, result)
        elif "ata_smart_attributes" in data or protocol == "ata":
            self._parse_ata(data, result)
        else:
            logger.debug("Estructura SMART desconocida para %s", result["disk_model"])
        return result

    def _parse_nvme(self, data: Dict[str, Any], result: Dict[str, Any]) -> None:
        log = data.get("nvme_smart_health_information_log") or {}
        result["device_type"] = "nvme"
        result["media_label"] = "SSD NVMe"
        if result["temperature"] is None:
            temp_value = log.get("temperature")
            if isinstance(temp_value, dict):
                temp_value = temp_value.get("current") or temp_value.get("value")
            if isinstance(temp_value, (int, float)):
                if temp_value > 200:  # Kelvin
                    temp_value -= 273
                result["temperature"] = int(temp_value)
        if result["power_on_hours"] is None and isinstance(log.get("power_on_hours"), (int, float)):
            result["power_on_hours"] = int(log["power_on_hours"])
        if result["power_cycles"] is None and isinstance(log.get("power_cycles"), (int, float)):
            result["power_cycles"] = int(log["power_cycles"])
        # Unidades de 1000 bloques de 512 bytes.
        units_read = log.get("data_units_read")
        units_written = log.get("data_units_written")
        if isinstance(units_read, (int, float)):
            result["read_bytes"] = int(units_read) * 512000
        if isinstance(units_written, (int, float)):
            result["write_bytes"] = int(units_written) * 512000
        if isinstance(log.get("host_reads"), (int, float)):
            result["read_count"] = int(log["host_reads"])
        if isinstance(log.get("host_writes"), (int, float)):
            result["write_count"] = int(log["host_writes"])
        percentage_used = log.get("percentage_used")
        if isinstance(percentage_used, (int, float)):
            result["health_percentage"] = max(0, min(100, 100 - int(percentage_used)))
        critical = {}
        for key in ("critical_warning", "media_errors", "percentage_used", "available_spare",
                    "available_spare_threshold", "num_err_log_entries", "unsafe_shutdowns"):
            if isinstance(log.get(key), (int, float)):
                critical[key] = int(log[key])
        result["critical_attributes"] = critical
        for key in ("critical_warning", "media_errors", "percentage_used", "available_spare"):
            if key in critical:
                result[key] = critical[key]

    def _parse_ata(self, data: Dict[str, Any], result: Dict[str, Any]) -> None:
        table = (data.get("ata_smart_attributes") or {}).get("table") or []
        rotation = data.get("rotation_rate")
        if isinstance(rotation, (int, float)) and rotation > 0:
            result["device_type"] = "hdd"
            result["media_label"] = "HDD"
        else:
            result["device_type"] = "ata"
            result["media_label"] = "SSD SATA" if rotation == 0 else "Disco SATA"
        block_size = data.get("logical_block_size") or 512
        critical: Dict[int, Dict[str, Any]] = {}
        for attribute in table:
            if not isinstance(attribute, dict):
                continue
            attr_id = attribute.get("id")
            name = attribute.get("name") or ""
            when_failed = attribute.get("when_failed") or ""
            if when_failed:
                result["failing_attributes"].append({"id": attr_id, "name": name, "when_failed": when_failed})
            if attr_id == 9 and result["power_on_hours"] is None:
                result["power_on_hours"] = decode_power_on_hours_raw(attribute)
            elif attr_id == 12 and result["power_cycles"] is None:
                raw = _raw_int(attribute)
                result["power_cycles"] = raw & 0xFFFFFFFF if raw is not None else None
            elif attr_id == 194 and result["temperature"] is None:
                # 190 (Airflow) no es la temperatura del disco: sólo 194.
                result["temperature"] = decode_temperature_raw(attribute)
            elif attr_id in (241, 242):
                raw = _raw_int(attribute)
                unit = lba_unit_bytes(name, block_size)
                if raw is not None and unit:
                    result["write_bytes" if attr_id == 241 else "read_bytes"] = raw * unit
                elif raw is not None:
                    logger.debug("Unidad desconocida para el atributo %s (%s)", attr_id, name)
            if attr_id in CRITICAL_ATA_ATTRIBUTES:
                raw = _raw_int(attribute)
                if raw is not None:
                    raw &= 0xFFFFFFFFFFFF
                critical[attr_id] = {
                    "name": name,
                    "value": attribute.get("value"),
                    "worst": attribute.get("worst"),
                    "thresh": attribute.get("thresh"),
                    "raw": raw,
                    "when_failed": when_failed,
                }
                result[CRITICAL_ATA_ATTRIBUTES[attr_id]] = raw
        result["critical_attributes"] = critical

    @staticmethod
    def _sanitize(data: Dict[str, Any]) -> None:
        """Anula campos imposibles en lugar de descartar el disco entero."""
        limits = {
            "temperature": (-40, 150),
            "power_on_hours": (0, 1_000_000),
            "power_cycles": (0, 10_000_000),
            "health_percentage": (0, 100),
        }
        for key, (low, high) in limits.items():
            value = data.get(key)
            if value is not None and (not isinstance(value, (int, float)) or not low <= value <= high):
                data[key] = None
        for key in ("read_bytes", "write_bytes", "read_count", "write_count"):
            value = data.get(key)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                data[key] = None

    def _validate_smart_data(self, data: Dict[str, Any]) -> bool:
        """True si hay algún dato útil (los campos imposibles ya se anularon)."""
        if not isinstance(data, dict):
            return False
        return any(data.get(key) is not None for key in (
            "temperature", "power_on_hours", "power_cycles", "smart_status",
            "read_bytes", "write_bytes", "health_percentage"))

    # ------------------------------------------------------------- escaneo
    def scan_all_disks(self) -> List[Dict[str, Any]]:
        """Lista los dispositivos de ``smartctl --scan`` con su tipo ``-d``."""
        if not self.is_available():
            return []
        try:
            rc, stdout, _stderr = self._run(["--scan"], timeout=10)
        except (subprocess.TimeoutExpired, OSError, RuntimeError) as exc:
            logger.warning("smartctl --scan falló: %s", exc)
            return []
        if rc & (RC_CMDLINE_ERROR | RC_OPEN_FAILED):
            return []
        return parse_scan_output(stdout)

    def get_disk_info_quick(self, physical_drive: str, device_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Información básica (-i) sin datos SMART completos."""
        if not self.is_available():
            return None
        device = physical_drive_to_device(physical_drive)
        args = ["-i", "-j"] + (["-d", device_type] if device_type else []) + [device]
        try:
            rc, stdout, _ = self._run(args, timeout=5)
        except (subprocess.TimeoutExpired, OSError, RuntimeError):
            return None
        if rc & (RC_CMDLINE_ERROR | RC_OPEN_FAILED) or not stdout:
            return None
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return None
        capacity = (data.get("user_capacity") or {}).get("bytes")
        return {
            "model_name": data.get("model_name", "Desconocido"),
            "serial_number": data.get("serial_number", "N/A"),
            "size": int(capacity) if isinstance(capacity, (int, float)) else 0,
            "device": device,
            "physical_drive": physical_drive,
        }

    # ------------------------------------------------- consulta elevada (UAC)
    def build_elevated_command(self, targets: Iterable[Tuple[str, Optional[str]]],
                               output_dir: str) -> Tuple[str, Dict[str, str]]:
        """Construye la línea de cmd.exe que ejecuta smartctl por dispositivo y
        vuelca cada JSON a un archivo temporal (el JSON ya incluye
        ``smartctl.exit_status``, así que no hace falta el código de retorno).

        Sólo acepta dispositivos y tipos con caracteres seguros: nunca se
        interpola texto libre en el comando elevado.
        """
        outputs: Dict[str, str] = {}
        commands = []
        for index, (device, device_type) in enumerate(targets):
            device = physical_drive_to_device(device)
            if not _SAFE_DEVICE.match(device) or (device_type and not _SAFE_TYPE.match(device_type)):
                raise ValueError(f"Dispositivo no válido para la consulta elevada: {device!r}")
            output = os.path.join(output_dir, f"smart_{index}.json")
            outputs[device] = output
            type_args = f" -d {device_type}" if device_type else ""
            commands.append(f'"{self.smartctl_path}" -a -j{type_args} {device} > "{output}"')
        return " & ".join(commands), outputs

    def query_elevated(self, targets: List[Tuple[str, Optional[str]]], timeout: float = 120) -> Dict[str, SmartQuery]:
        """Relanza sólo smartctl elevado (UAC) y lee los JSON resultantes.

        Es opcional y seguro: un único aviso de UAC, sin shell interactiva y
        con archivos temporales en un directorio propio que se borra al final.
        """
        results: Dict[str, SmartQuery] = {}
        if sys.platform != "win32" or not self.is_available() or not targets:
            for device, _type in targets:
                results[physical_drive_to_device(device)] = SmartQuery(
                    device=physical_drive_to_device(device), error="unavailable")
            return results
        output_dir = tempfile.mkdtemp(prefix="ordenasion-smart-")
        try:
            command, outputs = self.build_elevated_command(targets, output_dir)
            comspec = os.environ.get("ComSpec") or "cmd.exe"
            launched = _shell_execute_elevated(comspec, f'/d /s /c "{command}"', timeout)
            for device, path in outputs.items():
                if not launched:
                    results[device] = SmartQuery(device=device, error="cancelled")
                    continue
                try:
                    stdout = Path(path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    results[device] = SmartQuery(device=device, error="parse_error")
                    continue
                results[device] = self.interpret_output(device, _exit_status(stdout), stdout)
        finally:
            shutil.rmtree(output_dir, ignore_errors=True)
        return results


def _exit_status(stdout: str) -> int:
    """Código de retorno guardado por smartctl dentro de su JSON."""
    try:
        status = (json.loads(stdout).get("smartctl") or {}).get("exit_status", 0)
        return int(status)
    except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return RC_OPEN_FAILED


def _shell_execute_elevated(executable: str, parameters: str, timeout: float) -> bool:
    """ShellExecuteExW con el verbo 'runas'; espera a que termine el proceso.

    Devuelve False si el usuario cancela el UAC o no es Windows.
    """
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NO_CONSOLE = 0x00008000
    SW_HIDE = 0
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NO_CONSOLE
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    info.nShow = SW_HIDE
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False
    if not info.hProcess:
        return False
    try:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, int(timeout * 1000))
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)
    return True
