#!/usr/bin/env python3
"""
Gestor de Discos y Particiones para el Organizador de Archivos
Maneja la información del sistema, análisis de espacio y gestión segura de unidades
"""

import os
import sys
import psutil
import platform
import subprocess
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

if platform.system() == "Windows":
    try:
        import wmi  # type: ignore
    except ImportError:
        wmi = None

# Importar smartctl wrapper para datos SMART reales
from src.utils.smartctl_wrapper import SmartctlWrapper
from src.utils.logger import info, warn, error, success, debug, SmartCache
from src.utils.app_config import AppConfig
from src.utils.constants import EMOJI, HEALTH_LABELS
from src.core.health_service import HealthService

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


class DiskManager:
    """Gestor principal de discos y particiones del sistema"""
    
    def __init__(self):
        self.safe_mode = True  # Por defecto en modo seguro (solo lectura)
        self._disks_cache = None
        self._last_scan_time = 0
        self._drive_map = None  # --- CAMBIO ---: Inicia como None para lazy loading
        self._smart_cache = SmartCache(ttl_seconds=30)  # Cache con TTL de 30 segundos
        self.app_config = AppConfig()
        self.health_service = HealthService(self.app_config)
        self._executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="smartctl")
        self._lock = threading.Lock()
        
        # Inicializar smartctl wrapper para datos SMART lifetime
        self.smartctl = SmartctlWrapper()
        if self.smartctl.is_available():
            success("smartctl disponible - Se usarán datos SMART reales lifetime")
        else:
            warn("smartctl no disponible - Se usarán datos psutil como fallback")
        
        # --- CAMBIO ---: Eliminada toda la inicialización de WMI de __init__
        self.wmi_service = None # Inicia como None
    
    def __del__(self):
        """Limpia recursos al destruir la instancia"""
        if hasattr(self, '_executor'):
            self._executor.shutdown(wait=False)

    # --- CAMBIO ---: Nuevo método thread-safe para obtener/crear el mapa WMI
    def _get_or_create_drive_map(self) -> Dict[str, str]:
        """
        Obtiene el mapeo WMI (lógico a físico), creándolo si no existe.
        Este método es thread-safe usando self._lock.
        """
        # 1. Comprobación rápida sin bloqueo
        if self._drive_map is not None:
            return self._drive_map
        
        # 2. Si no existe, usar el cerrojo para crearlo
        with self._lock:
            # 3. Doble comprobación (quizás otro hilo lo creó mientras este esperaba)
            if self._drive_map is not None:
                return self._drive_map
            
            info("Inicializando WMI y creando mapeo de unidades por primera vez (lazy load)...")
            
            if platform.system() != "Windows" or not wmi:
                warn("WMI no disponible o no es Windows. Mapeo de discos físicos desactivado.")
                self._drive_map = {} # Cachear el fallo
                return self._drive_map

            try:
                import time
                time.sleep(0.5)  # Esperar a que el sistema esté listo
                self.wmi_service = wmi.WMI()
                success("WMI service inicializado (lazy load)")
                drive_map = self._map_logical_to_physical_drives()
                self._drive_map = drive_map
                return self._drive_map
            
            except Exception as e:
                error(f"Error al inicializar WMI (lazy load): {e}")
                info("Reintentando inicialización WMI (lazy load)...")
                try:
                    import time
                    time.sleep(2)  # Esperar más tiempo
                    self.wmi_service = wmi.WMI()
                    success("WMI service inicializado en segundo intento (lazy load)")
                    drive_map = self._map_logical_to_physical_drives()
                    self._drive_map = drive_map
                    return self._drive_map
                except Exception as e2:
                    error(f"Error crítico final al inicializar WMI (lazy load): {e2}")
                    self.wmi_service = None
                    self._drive_map = {} # Cachear el fallo definitivo
                    return self._drive_map
    
    def _map_drives_with_smartctl_only(self) -> Dict[str, Dict[str, Any]]:
        """
        Mapea letras de unidad a discos físicos usando SOLO smartctl (sin WMI)
        Usa smartctl --scan, tamaño de disco y datos SMART para mapeo preciso
        """
        drive_map = {}
        
        if not self.smartctl.is_available():
            warn("smartctl no disponible para mapeo")
            return drive_map
        
        try:
            # Obtener todos los discos usando smartctl --scan (método profesional)
            info("🔍 Escaneando discos con smartctl --scan...")
            scanned_disks = self.smartctl.scan_all_disks()
            
            if not scanned_disks:
                warn("No se encontraron discos con smartctl")
                return drive_map
            
            info(f"✅ Encontrados {len(scanned_disks)} discos físicos")
            
            # Obtener información de cada disco físico (tamaño, modelo, etc.)
            disk_info_map = {}  # physical_drive -> {size, model, device, type}
            for disk_info in scanned_disks:
                physical_drive = disk_info.get('physical_drive')
                device = disk_info.get('device')
                device_type = disk_info.get('type')
                
                if not physical_drive:
                    continue
                
                # Obtener información completa del disco
                try:
                    # Primero obtener tamaño (más rápido y necesario para mapeo)
                    disk_size = self._get_disk_size_from_smartctl(physical_drive, device_type)
                    
                    # Luego intentar obtener datos SMART (puede fallar, pero no es crítico para mapeo)
                    smart_data = None
                    try:
                        smart_data = self.smartctl.get_disk_smart_data(
                            physical_drive,
                            timeout=3,
                            max_retries=0,
                            device_type=device_type
                        )
                    except Exception:
                        # Si falla obtener SMART, continuar sin datos SMART
                        pass
                    
                    # Usar modelo de smart_data si está disponible, sino usar nombre básico
                    if smart_data:
                        model = smart_data.get('disk_model', f'Disco {physical_drive}')
                    else:
                        model = f'Disco {physical_drive}'
                    
                    # Agregar al mapa aunque no tenga datos SMART (el mapeo es lo importante)
                    disk_info_map[physical_drive] = {
                        'model': model,
                        'device': device,
                        'type': device_type,
                        'size': disk_size,
                        'smart_data': smart_data  # Puede ser None
                    }
                    debug(f"  Disco {physical_drive}: {model} ({disk_size / 1024**3:.1f} GB)")
                except Exception as e:
                    debug(f"Error obteniendo info de {physical_drive}: {e}")
                    # Aún así, agregar información básica para permitir mapeo
                    try:
                        disk_info_map[physical_drive] = {
                            'model': f'Disco {physical_drive}',
                            'device': device,
                            'type': device_type,
                            'size': 0,  # No se pudo obtener tamaño
                            'smart_data': None
                        }
                    except:
                        continue
            
            # Obtener todas las particiones del sistema con sus tamaños
            partitions = psutil.disk_partitions()
            partition_info = []
            
            for partition in partitions:
                drive_letter = self._extract_drive_letter(partition.mountpoint)
                if not drive_letter:
                    continue
                
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    partition_info.append({
                        'drive_letter': drive_letter,
                        'drive_key': (drive_letter + ":").upper(),
                        'mountpoint': partition.mountpoint,
                        'total_size': usage.total,
                        'partition': partition
                    })
                except Exception:
                    continue
            
            # Mapear cada unidad al disco físico más probable
            # Estrategia: comparar tamaños y asignar el disco que mejor coincida
            used_physical_drives = set()  # Evitar asignar el mismo disco a múltiples unidades
            
            for part_info in partition_info:
                drive_key = part_info['drive_key']
                drive_letter = part_info['drive_letter']
                partition_size = part_info['total_size']
                
                best_match = None
                best_score = 0
                
                # Buscar el mejor disco físico que coincida
                for physical_drive, disk_data in disk_info_map.items():
                    # Si este disco ya está asignado, saltarlo
                    if physical_drive in used_physical_drives:
                        continue
                    
                    disk_size = disk_data.get('size', 0)
                    
                    # Calcular score de coincidencia basado en tamaño
                    # Si el tamaño de la partición es menor o igual al tamaño del disco, es una buena coincidencia
                    if disk_size > 0:
                        size_ratio = min(partition_size, disk_size) / max(partition_size, disk_size)
                        score = size_ratio
                        
                        # Bonus si el tamaño de la partición es exactamente el tamaño del disco (partición única)
                        if abs(partition_size - disk_size) < (100 * 1024 * 1024):  # Diferencia < 100MB
                            score = 1.0
                        
                        if score > best_score:
                            best_score = score
                            best_match = {
                                'physical_drive': physical_drive,
                                'device': disk_data['device'],
                                'type': disk_data['type'],
                                'model': disk_data['model'],
                                'mountpoint': part_info['mountpoint'],
                                'score': score
                            }
                
                # Si encontramos una buena coincidencia (score > 0.5), asignarla
                if best_match and best_score > 0.5:
                    drive_map[drive_key] = best_match
                    used_physical_drives.add(best_match['physical_drive'])
                    success(f"✅ Mapeado: {drive_key} -> {best_match['physical_drive']} ({best_match['model']}) [score: {best_score:.2f}]")
                else:
                    # Si no hay buena coincidencia, intentar asignar cualquier disco disponible
                    # pero solo si no hay mejor opción
                    for physical_drive, disk_data in disk_info_map.items():
                        if physical_drive not in used_physical_drives:
                            drive_map[drive_key] = {
                                'physical_drive': physical_drive,
                                'device': disk_data['device'],
                                'type': disk_data['type'],
                                'model': disk_data['model'],
                                'mountpoint': part_info['mountpoint'],
                                'score': 0.3  # Score bajo porque no hay buena coincidencia
                            }
                            used_physical_drives.add(physical_drive)
                            # Mensaje menos alarmante - es normal cuando no hay coincidencia exacta
                            debug(f"ℹ️ Mapeo aproximado: {drive_key} -> {physical_drive} ({disk_data['model']}) [score: 0.3]")
                            break
            
            if drive_map:
                info(f"✅ Mapeo completado: {len(drive_map)} unidades mapeadas")
            else:
                warn("⚠️ No se pudo mapear ninguna unidad")
            
            return drive_map
            
        except Exception as e:
            error(f"Error en mapeo con smartctl: {e}")
            return drive_map
    
    def _get_disk_size_from_smartctl(self, physical_drive: str, device_type: Optional[str] = None) -> int:
        """Obtiene el tamaño del disco físico usando smartctl"""
        try:
            device = None
            if 'PHYSICALDRIVE' in physical_drive:
                drive_num = physical_drive.replace('PHYSICALDRIVE', '').strip()
                device = f"/dev/pd{drive_num}"
            else:
                device = physical_drive
            
            if not device:
                return 0
            
            cmd = [self.smartctl.smartctl_path, "-i", "-j", device]
            if device_type:
                cmd = [self.smartctl.smartctl_path, "-i", "-j", "-d", device_type, device]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
            )
            
            if result.returncode in [0, 4] and result.stdout:
                import json
                data = json.loads(result.stdout)
                # El tamaño puede venir en diferentes campos según el tipo de disco
                user_capacity = data.get('user_capacity', {})
                if isinstance(user_capacity, dict):
                    bytes_value = user_capacity.get('bytes', 0)
                    if bytes_value:
                        return int(bytes_value)
                
                # Alternativa: buscar en otros campos
                capacity = data.get('capacity', {})
                if isinstance(capacity, dict):
                    bytes_value = capacity.get('bytes', 0)
                    if bytes_value:
                        return int(bytes_value)
            
            return 0
        except Exception:
            return 0
    
    def _map_logical_to_physical_drives(self) -> Dict[str, str]:
        """Crea un mapeo de letra de unidad (ej. 'C:') a disco físico (ej. 'PhysicalDrive0') usando WMI."""
        if not self.wmi_service:
            error("WMI service no disponible para mapeo")
            return {}
        
        drive_map = {}
        try:
            debug("Iniciando mapeo WMI...")
            for physical_disk in self.wmi_service.Win32_DiskDrive():
                debug(f"Disco físico encontrado: {physical_disk.DeviceID}")
                for partition in physical_disk.associators("Win32_DiskDriveToDiskPartition"):
                    debug(f"  Partición: {partition.DeviceID}")
                    for logical_disk in partition.associators("Win32_LogicalDiskToPartition"):
                        psutil_key = physical_disk.DeviceID.replace('\\\\.\\', '').upper()
                        logical_drive = logical_disk.DeviceID.upper()
                        drive_map[logical_drive] = psutil_key
                        debug(f"  Mapeado: {logical_drive} -> {psutil_key}")
            
            info(f"Mapeo final: {drive_map}")
            
            # También mostrar qué claves tiene psutil
            import psutil
            all_io_counters = psutil.disk_io_counters(perdisk=True)
            debug(f"Claves de psutil disponibles: {list(all_io_counters.keys())}")
            
        except Exception as e:
            error(f"Error al mapear discos lógicos a físicos: {e}")
            
        return drive_map
    

    def get_all_disks(self) -> List[DiskInfo]:
        """Obtiene información de todos los discos y particiones disponibles"""
        try:
            disks = []
            
            # Obtener todas las particiones
            partitions = psutil.disk_partitions()
            
            for partition in partitions:
                try:
                    # Obtener estadísticas de uso
                    usage = psutil.disk_usage(partition.mountpoint)
                    
                    # Determinar si es unidad del sistema
                    is_system = self._is_system_drive(partition.mountpoint)
                    
                    # Determinar si es removible
                    is_removable = self._is_removable_drive(partition.device)
                    
                    # Extraer letra de unidad (Windows)
                    drive_letter = self._extract_drive_letter(partition.mountpoint)
                    
                    disk_info = DiskInfo(
                        device=partition.device,
                        mountpoint=partition.mountpoint,
                        filesystem=partition.fstype or "Desconocido",
                        total_size=usage.total,
                        used_size=usage.used,
                        free_size=usage.free,
                        usage_percent=usage.percent,
                        is_system_drive=is_system,
                        is_removable=is_removable,
                        drive_letter=drive_letter
                    )
                    
                    disks.append(disk_info)
                    
                except (PermissionError, OSError) as e:
                    # Ignorar unidades sin permisos
                    continue
            
            # Ordenar por letra de unidad (Windows) o por punto de montaje
            disks.sort(key=lambda x: x.drive_letter or x.mountpoint)
            
            return disks
            
        except Exception as e:
            error(f"Error al obtener información de discos: {e}")
            return []
    
    def get_disk_info(self, path: str) -> Optional[DiskInfo]:
        """Obtiene información de un disco específico por ruta"""
        try:
            # Encontrar la partición que contiene la ruta
            path_obj = Path(path).resolve()
            
            for disk in self.get_all_disks():
                if path_obj.is_relative_to(Path(disk.mountpoint)):
                    return disk
            
            return None
            
        except Exception as e:
            error(f"Error al obtener información del disco {path}: {e}")
            return None
    
    def get_disk_io_stats(self, path: str) -> Optional[dict]:
        """Obtiene SOLO datos SMART lifetime reales - Sin fallbacks"""
        try:
            disk_info = self.get_disk_info(path)
            if not disk_info:
                return None

            # Obtener SOLO datos SMART lifetime reales
            smart_data = self._get_smart_data(disk_info.drive_letter)
            
            # Si no hay datos SMART, devolver None (sin fallback)
            if not smart_data:
                warn(f"No hay datos SMART disponibles para {path}")
                return None
            
            return smart_data

        except (ImportError, OSError, KeyError) as e:
            error(f"Error al obtener estadísticas I/O del disco {path}: {e}")
            return None
    
    def get_multiple_disk_io_stats(self, paths: List[str]) -> Dict[str, Optional[dict]]:
        """Obtiene datos SMART para múltiples discos en paralelo"""
        results = {}
        
        # Enviar tareas al executor
        future_to_path = {}
        for path in paths:
            future = self._executor.submit(self.get_disk_io_stats, path)
            future_to_path[future] = path
        
        # Recoger resultados
        for future in as_completed(future_to_path):
            path = future_to_path[future]
            try:
                results[path] = future.result()
            except Exception as e:
                error(f"Error obteniendo SMART para {path}: {e}")
                results[path] = None
        
        return results

    def prefetch_smart_for_disks(self, paths: List[str]) -> None:
        """Precarga asíncrona de SMART para calentar la caché de sesión.
        Lanza tareas en segundo plano y no bloquea la UI.
        """
        if not paths:
            return
        for path in paths:
            # Ejecutar en background, resultado ignorado (cacheará internamente)
            self._executor.submit(self.get_disk_io_stats, path)

    def _get_smart_data(self, drive_letter: str) -> Optional[dict]:
        """Obtiene SOLO datos SMART lifetime reales usando smartctl - NO fallback, SIN WMI"""
        if not drive_letter:
            return None
        
        # Si smartctl no está disponible, no devolver nada
        if not self.smartctl.is_available():
            error(f"smartctl no disponible - No se pueden obtener datos SMART para {drive_letter}")
            return None
        
        # Crear mapeo usando solo smartctl (sin WMI)
        if not self._drive_map:
            debug("Creando mapeo de unidades usando smartctl (sin WMI)...")
            self._drive_map = self._map_drives_with_smartctl_only()
        
        drive_key = (drive_letter + ":").upper()
        drive_info = self._drive_map.get(drive_key)  # Ahora es un dict con más info
        
        if not drive_info:
            debug(f"No se pudo mapear {drive_letter} a disco físico. Mapeo actual: {list(self._drive_map.keys())}")
            return None
        
        physical_drive_id = drive_info.get('physical_drive')
        device_type = drive_info.get('type')
        
        if not physical_drive_id:
            return None
        
        # Verificar si ya tenemos estos datos en cache de sesión
        cache_key = f"smart_{physical_drive_id}"
        cached_data = self._smart_cache.get(cache_key)
        if cached_data:
            debug(f"Datos SMART de cache de sesión para {drive_letter}")
            return cached_data
        
        try:
            debug(f"Obteniendo datos SMART lifetime para {drive_letter} ({physical_drive_id})...")
            # Mostrar en terminal primero para debugging
            info(f"🔍 Obteniendo datos SMART para {drive_letter}: ({physical_drive_id})")
            smart_data = self.smartctl.get_disk_smart_data(physical_drive_id, device_type=device_type)
            
            # Mostrar datos en terminal
            if smart_data:
                model = smart_data.get('disk_model', 'Desconocido')
                read_tb = (smart_data.get('read_bytes') or 0) / 1024**4
                write_tb = (smart_data.get('write_bytes') or 0) / 1024**4
                temp = smart_data.get('temperature')
                hours = smart_data.get('power_on_hours')
                success(f"✅ SMART datos para {drive_letter}: {model} | {read_tb:.2f} TB leídos | {write_tb:.2f} TB escritos | Temp: {temp}°C | Horas: {hours:,}")
            else:
                warn(f"⚠️ No se obtuvieron datos SMART para {drive_letter}")
            
            if not smart_data:
                warn(f"smartctl no devolvió datos para {drive_letter} - Datos SMART no disponibles")
                return None
            
            read_bytes = smart_data.get('read_bytes') or 0
            write_bytes = smart_data.get('write_bytes') or 0
            read_tb = read_bytes / 1024**4 if read_bytes else 0
            write_tb = write_bytes / 1024**4 if write_bytes else 0
            
            # Si ambos son 0 o muy pequeños (< 1GB), el disco no soporta estos atributos o los datos son inválidos
            if read_bytes == 0 and write_bytes == 0:
                warn(f"Disco {drive_letter} no reporta datos de lectura/escritura SMART")
                return None
            
            # Si los datos parecen incorrectos (< 100MB total), también rechazar
            if (read_bytes + write_bytes) < (100 * 1024 * 1024):
                warn(f"Disco {drive_letter} reporta datos SMART sospechosos ({read_bytes + write_bytes} bytes)")
                return None
            
            success(f"SMART lifetime: {read_tb:.1f} TB leídos, {write_tb:.1f} TB escritos")
            
            result = {
                'read_count': smart_data.get('read_count', 0),
                'write_count': smart_data.get('write_count', 0),
                'read_bytes': read_bytes,
                'write_bytes': write_bytes,
                'disk_model': smart_data.get('disk_model', 'Desconocido'),
                'device_type': smart_data.get('device_type', None),
                'temperature': smart_data.get('temperature'),
                'power_on_hours': smart_data.get('power_on_hours'),
                'power_cycles': smart_data.get('power_cycles'),
                'health_percentage': smart_data.get('health_percentage', 100),
                'smart_status': smart_data.get('smart_status', True),
                'note': '📊 Datos SMART lifetime reales del disco'
            }
            
            # Guardar en cache de sesión
            self._smart_cache.set(cache_key, result)
            return result
                
        except Exception as e:
            error(f"Error obteniendo SMART para {drive_letter}: {e}")
            return None
    
    
    def analyze_disk_space(self, path: str) -> Dict[str, Any]:
        """Analiza el uso de espacio en una ruta específica"""
        try:
            disk_info = self.get_disk_info(path)
            if not disk_info:
                return {}
            
            # Análisis básico de la carpeta
            folder_stats = self._analyze_folder_contents(path)
            
            return {
                "disk_info": disk_info,
                "folder_analysis": folder_stats,
                "recommendations": self._generate_recommendations(disk_info, folder_stats)
            }
            
        except Exception as e:
            error(f"Error al analizar espacio del disco: {e}")
            return {}
    
    def get_safe_mode_status(self) -> bool:
        """Retorna el estado del modo seguro"""
        return self.safe_mode
    
    def set_safe_mode(self, enabled: bool) -> bool:
        """Cambia el modo seguro (solo administradores)"""
        # En una implementación real, aquí verificaríamos permisos de administrador
        self.safe_mode = enabled
        return True
    
    def can_write_to_disk(self, path: str) -> bool:
        """Verifica si se puede escribir en el disco (considerando modo seguro)"""
        if self.safe_mode:
            return False
        
        try:
            disk_info = self.get_disk_info(path)
            if not disk_info:
                return False
            
            # Verificar permisos de escritura
            test_file = Path(path) / ".test_write_permission"
            try:
                test_file.touch()
                test_file.unlink()
                return True
            except (PermissionError, OSError):
                return False
                
        except Exception:
            return False
    
    def _is_system_drive(self, mountpoint: str) -> bool:
        """Determina si una unidad es del sistema"""
        try:
            # En Windows, la unidad C: es típicamente la del sistema
            if os.name == 'nt':
                drive_letter = mountpoint[0].upper() if len(mountpoint) >= 1 else ''
                if drive_letter == 'C':
                    return True
                
                # También verificar si contiene rutas del sistema
                system_paths = [
                    os.environ.get('SystemRoot', 'C:\\Windows'),
                    os.environ.get('ProgramFiles', 'C:\\Program Files'),
                    os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)')
                ]
                
                mountpoint_path = Path(mountpoint)
                for system_path in system_paths:
                    if system_path and Path(system_path).exists():
                        try:
                            if mountpoint_path.is_relative_to(Path(system_path)):
                                return True
                        except ValueError:
                            continue
            
            # En otros sistemas, verificar rutas típicas
            elif os.name == 'posix':
                system_paths = ['/', '/usr', '/etc', '/var']
                mountpoint_path = Path(mountpoint)
                for system_path in system_paths:
                    try:
                        if mountpoint_path.is_relative_to(Path(system_path)):
                            return True
                    except ValueError:
                        continue
                        
            return False
            
        except Exception:
            return False
    
    def _is_removable_drive(self, device: str) -> bool:
        """Determina si una unidad es removible"""
        try:
            # En Windows, verificar si es una unidad removible
            if os.name == 'nt':
                drive_letter = device[0] if len(device) >= 1 else ''
                if drive_letter and drive_letter.isalpha():
                    # Por ahora, asumir que no es removible para evitar errores
                    # En una implementación futura se puede usar win32api
                    return False
            return False
        except:
            return False
    
    def _extract_drive_letter(self, mountpoint: str) -> str:
        """Extrae la letra de unidad en Windows"""
        if os.name == 'nt' and len(mountpoint) >= 2:
            if mountpoint[1] == ':':
                return mountpoint[0].upper()
        return ""
    
    def _analyze_folder_contents(self, path: str) -> Dict[str, Any]:
        """Analiza el contenido de una carpeta para estadísticas detalladas"""
        try:
            path_obj = Path(path)
            if not path_obj.exists() or not path_obj.is_dir():
                return {}
            
            total_files = 0
            total_dirs = 0
            total_size = 0
            file_types = {}
            large_files = []  # Archivos grandes (>100MB)
            recent_files = []  # Archivos recientes (<7 días)
            old_files = []     # Archivos antiguos (>30 días)
            
            from datetime import datetime, timedelta
            now = datetime.now()
            week_ago = now - timedelta(days=7)
            month_ago = now - timedelta(days=30)
            
            # Análisis más detallado pero limitado para no bloquear la interfaz
            max_items = 10000  # Límite para no bloquear
            item_count = 0
            
            for item in path_obj.iterdir():
                if item_count >= max_items:
                    break
                    
                try:
                    if item.is_file():
                        total_files += 1
                        item_count += 1
                        
                        # Obtener estadísticas del archivo
                        stat = item.stat()
                        file_size = stat.st_size
                        total_size += file_size
                        
                        # Contar tipos de archivo
                        ext = item.suffix.lower()
                        if ext:
                            file_types[ext] = file_types.get(ext, 0) + 1
                        else:
                            file_types["sin_extension"] = file_types.get("sin_extension", 0) + 1
                        
                        # Identificar archivos grandes (>100MB)
                        if file_size > 100 * 1024 * 1024:  # 100MB
                            large_files.append({
                                'name': item.name,
                                'size': file_size,
                                'path': str(item)
                            })
                        
                        # Identificar archivos por fecha
                        mtime = datetime.fromtimestamp(stat.st_mtime)
                        if mtime > week_ago:
                            recent_files.append(item.name)
                        elif mtime < month_ago:
                            old_files.append(item.name)
                            
                    elif item.is_dir():
                        total_dirs += 1
                        item_count += 1
                        
                except (PermissionError, OSError):
                    continue
            
            # Ordenar archivos grandes por tamaño
            large_files.sort(key=lambda x: x['size'], reverse=True)
            
            return {
                "total_files": total_files,
                "total_dirs": total_dirs,
                "total_size": total_size,
                "file_types": file_types,
                "large_files": large_files[:10],  # Top 10 archivos grandes
                "recent_files_count": len(recent_files),
                "old_files_count": len(old_files),
                "analysis_limit_reached": item_count >= max_items
            }
            
        except Exception as e:
            error(f"Error al analizar contenido de carpeta: {e}")
            return {}
    
    def _generate_recommendations(self, disk_info: DiskInfo, folder_stats: Dict) -> List[str]:
        """Genera recomendaciones basadas en el análisis del disco"""
        recommendations = []
        
        # Recomendaciones basadas en espacio libre
        if disk_info.usage_percent > 90:
            recommendations.append("⚠️ Disco casi lleno. Considera limpiar archivos temporales.")
        elif disk_info.usage_percent > 80:
            recommendations.append("🔍 Disco con poco espacio libre. Revisa archivos grandes.")
        
        # Recomendaciones basadas en contenido
        if folder_stats.get("total_files", 0) > 10000:
            recommendations.append("📁 Muchos archivos. Considera organizar en subcarpetas.")
        
        if not recommendations:
            recommendations.append("✅ Disco en buen estado. No se requieren acciones inmediatas.")
        
        return recommendations
    
    def format_size(self, size_bytes: int) -> str:
        """Formatea bytes en formato legible"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def get_disk_health_status(self, path: str) -> Dict[str, Any]:
        """Obtiene el estado de salud del disco usando el servicio de salud"""
        try:
            disk_info = self.get_disk_info(path)
            if not disk_info:
                return {"status": "Desconocido", "score": 0, "factors": []}
            
            # Obtener SMART reales
            smart = self.get_disk_io_stats(path) or {}
            if not smart or not any(
                smart.get(key) is not None
                for key in ("temperature", "power_on_hours", "power_cycles", "smart_status")
            ):
                return {"status": "Datos SMART no disponibles", "score": None,
                        "factors": [], "available": False}
            
            # Usar el servicio de salud
            health_result = self.health_service.calculate_health(smart, disk_info)
            
            return {
                "status": health_result.status,
                "available": True,
                "score": health_result.score,
                "factors": health_result.factors,
                "temp_score": health_result.temp_score,
                "tbw_score": health_result.tbw_score,
                "hours_score": health_result.hours_score,
                "cycles_score": health_result.cycles_score,
                "device_type": health_result.device_type,
                "temperature": health_result.temperature,
                "power_on_hours": health_result.power_on_hours,
                "power_cycles": health_result.power_cycles,
                "tbw": health_result.tbw
            }
            
        except Exception as e:
            error(f"Error al obtener estado de salud del disco: {e}")
            return {"status": "Error", "score": 0, "factors": ["Error al analizar el disco"]}
