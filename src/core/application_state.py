#!/usr/bin/env python3
"""
Estado Centralizado de la Aplicación
Patrón Singleton + Observer para gestión unificada del estado
"""

import threading
from typing import Dict, Any, List, Optional, Callable, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass
from PyQt6.QtCore import QObject, pyqtSignal

from src.utils.logger import debug, error as log_error, warn as log_warn

# Importaciones lazy para evitar problemas en PyInstaller
if TYPE_CHECKING:
    from .category_manager import CategoryManager
    from .disk_manager import DiskManager
    from src.utils.app_config import AppConfig


class EventType(Enum):
    """Tipos de eventos del sistema"""
    STATE_CHANGED = "state_changed"
    THEME_CHANGED = "theme_changed"
    CATEGORIES_UPDATED = "categories_updated"
    DISK_SELECTED = "disk_selected"
    ANALYSIS_STARTED = "analysis_started"
    ANALYSIS_COMPLETED = "analysis_completed"
    WORKER_STARTED = "worker_started"
    WORKER_FINISHED = "worker_finished"
    MEMORY_CLEANUP = "memory_cleanup"


@dataclass
class ApplicationEvent:
    """Evento del sistema con datos"""
    event_type: EventType
    data: Dict[str, Any]
    timestamp: float
    source: str


class _SignalEmitter(QObject):
    """QObject interno solo para emitir señales - evita problemas de inicialización"""
    state_changed = pyqtSignal(object)
    theme_changed = pyqtSignal(str)
    categories_updated = pyqtSignal()
    disk_selected = pyqtSignal(str)
    
    def __init__(self, parent=None):
        # Inicializar QObject de forma diferida y segura
        debug("[SignalEmitter] Creando QObject para señales...")
        try:
            super().__init__(parent)
            debug("[SignalEmitter] QObject inicializado correctamente")
        except Exception as e:
            log_error(f"[SignalEmitter] ERROR: {e}")
            # Intentar sin parent
            try:
                super().__init__(None)
                debug("[SignalEmitter] QObject inicializado sin parent")
            except Exception as e2:
                log_error(f"[SignalEmitter] ERROR CRÍTICO: {e2}")
                raise


class ApplicationState:
    """
    Estado centralizado de la aplicación con patrón Singleton + Observer
    Thread-safe y optimizado para performance
    
    ⚠️ CAMBIO: Ya NO hereda de QObject directamente para evitar bloqueos en PyInstaller
    Usa un QObject interno (_signal_emitter) para las señales
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Implementación Singleton thread-safe"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    debug("[AppState] Creando nueva instancia en __new__...")
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
                    cls._instance._signal_emitter = None
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        debug("[AppState] Iniciando __init__ de ApplicationState...")
        
        # ⚠️ CRÍTICO: NO heredar de QObject - usar uno interno
        # Esto evita el bloqueo en PyInstaller
        debug("[AppState] QObject interno se creará bajo demanda cuando se necesite...")
        
        debug("[AppState] Configurando atributos iniciales...")
        
        # === COMPONENTES PRINCIPALES ===
        self.category_manager: Optional['CategoryManager'] = None
        self.disk_manager: Optional['DiskManager'] = None
        self.app_config: Optional['AppConfig'] = None
        
        # === ESTADO DE LA APLICACIÓN ===
        self.current_theme: str = "elegant_light"
        self.current_font_size: int = 12
        self.current_disk: Optional[str] = None
        self.is_analysis_running: bool = False
        self.is_organization_running: bool = False
        
        # === GESTIÓN DE WORKERS ===
        self.active_workers: Dict[str, Any] = {}
        self.worker_lock = threading.Lock()
        
        # === CACHÉS Y MEMORIA ===
        self.caches: Dict[str, Any] = {}
        self.cache_lock = threading.Lock()
        
        # === OBSERVADORES ===
        self._observers: List[Callable[[ApplicationEvent], None]] = []
        self._observer_lock = threading.Lock()
        
        debug("[AppState] Atributos y locks inicializados")
        
        # === INICIALIZACIÓN ===
        debug("[AppState] Llamando _initialize_components()...")
        self._initialize_components()
        debug("[AppState] _initialize_components() completado")
        
        self._initialized = True
        debug("[AppState] Flag _initialized = True")
        
        # Emitir evento de inicialización (diferido - después de que UI esté lista)
        debug("[AppState] Evento de inicialización se emitirá cuando UI esté lista")
    
    def _get_signal_emitter(self) -> Optional[_SignalEmitter]:
        """Obtiene o crea el QObject interno para señales (lazy initialization)"""
        if self._signal_emitter is None:
            debug("[AppState] Creando QObject interno para señales (primera vez)...")
            try:
                # Intentar obtener QApplication como parent
                from PyQt6.QtWidgets import QApplication
                app = QApplication.instance()
                parent = app if app else None
                debug(f"[AppState] QApplication parent: {parent is not None}")
                
                self._signal_emitter = _SignalEmitter(parent)
                debug("[AppState] QObject interno creado exitosamente")
            except Exception as e:
                log_error(f"[AppState] ERROR creando QObject interno: {e}")
                import traceback
                debug(f"[AppState] Traceback: {traceback.format_exc()}")
                # Crear sin parent como último recurso
                try:
                    self._signal_emitter = _SignalEmitter(None)
                    debug("[AppState] QObject interno creado sin parent")
                except Exception as e2:
                    log_error(f"[AppState] ERROR CRÍTICO: No se pudo crear QObject interno: {e2}")
                    # Continuar sin señales Qt - la app funcionará sin ellas
                    self._signal_emitter = None
        return self._signal_emitter
    
    @property
    def state_changed(self):
        """Propiedad para acceder a la señal state_changed"""
        emitter = self._get_signal_emitter()
        return emitter.state_changed if emitter else None
    
    @property
    def theme_changed(self):
        """Propiedad para acceder a la señal theme_changed"""
        emitter = self._get_signal_emitter()
        return emitter.theme_changed if emitter else None
    
    @property
    def categories_updated(self):
        """Propiedad para acceder a la señal categories_updated"""
        emitter = self._get_signal_emitter()
        return emitter.categories_updated if emitter else None
    
    @property
    def disk_selected(self):
        """Propiedad para acceder a la señal disk_selected"""
        emitter = self._get_signal_emitter()
        return emitter.disk_selected if emitter else None
    
    def _initialize_components(self):
        """
        Inicializa los componentes principales de forma segura
        ⚠️ CRÍTICO: Este método NO debe fallar nunca, solo registrar errores
        
        NUEVO: Inicialización SUPER LAZY - Solo configura defaults, 
        los componentes se crean bajo demanda
        """
        try:
            debug("[AppState] Inicializando componentes (modo super lazy)...")
            
            # === PASO 1: Solo establecer None - NO crear nada todavía ===
            self.app_config = None
            self.category_manager = None
            self.disk_manager = None
            
            # === PASO 2: Configurar valores por defecto (sin cargar config) ===
            # Evitar emojis que causan problemas de Unicode en Windows
            self.current_theme = "Claro Elegante"
            self.current_font_size = 12
            
            debug(f"[AppState] Valores por defecto: {self.current_theme}, {self.current_font_size}px")
            debug("[AppState] Componentes en modo lazy (se crearán bajo demanda)")
            
        except Exception as e:
            # ⚠️ ÚLTIMO RECURSO: Capturar TODO para evitar que el módulo falle
            import traceback
            log_error(f"[AppState] ❌ ERROR CRÍTICO en _initialize_components: {e}")
            debug(f"[AppState] Traceback completo:")
            log_error(traceback.format_exc())
            
            # Asegurar que al menos tenemos valores por defecto
            if not hasattr(self, 'app_config'):
                self.app_config = None
            if not hasattr(self, 'category_manager'):
                self.category_manager = None
            if not hasattr(self, 'disk_manager'):
                self.disk_manager = None
            if not hasattr(self, 'current_theme'):
                self.current_theme = "Claro Elegante"
            if not hasattr(self, 'current_font_size'):
                self.current_font_size = 12
            
            # NO re-lanzar la excepción - dejar que la aplicación continúe
    
    def get_app_config(self) -> Optional['AppConfig']:
        """Obtiene AppConfig con inicialización lazy thread-safe"""
        if self.app_config is None:
            with self._lock:
                if self.app_config is None:
                    try:
                        debug("[AppState] Inicializando AppConfig de forma lazy...")
                        from src.utils.app_config import AppConfig
                        self.app_config = AppConfig()
                        
                        # Cargar configuración guardada
                        try:
                            self.current_theme = self.app_config.get_theme()
                            self.current_font_size = self.app_config.get_font_size()
                        except Exception as e:
                            log_warn(f"[AppState] No se pudo leer el tema guardado: {e}")
                        
                        debug("[AppState] ✅ AppConfig inicializado")
                        self._emit_event(EventType.STATE_CHANGED, {
                            "component": "app_config",
                            "action": "initialized"
                        }, "ApplicationState")
                    except Exception as e:
                        log_error(f"[AppState] ⚠️ ERROR creando AppConfig: {e}")
                        import traceback
                        log_error(traceback.format_exc())
                        self.app_config = None
        return self.app_config
    
    def get_category_manager(self) -> Optional['CategoryManager']:
        """Obtiene CategoryManager con inicialización lazy thread-safe"""
        if self.category_manager is None:
            with self._lock:
                if self.category_manager is None:
                    try:
                        debug("[AppState] Inicializando CategoryManager de forma lazy...")
                        from .category_manager import CategoryManager
                        self.category_manager = CategoryManager()
                        debug("[AppState] ✅ CategoryManager inicializado")
                        self._emit_event(EventType.STATE_CHANGED, {
                            "component": "category_manager",
                            "action": "initialized"
                        }, "ApplicationState")
                    except Exception as e:
                        log_error(f"[AppState] ⚠️ ERROR creando CategoryManager: {e}")
                        import traceback
                        log_error(traceback.format_exc())
                        self.category_manager = None
        return self.category_manager
    
    def get_disk_manager(self) -> Optional['DiskManager']:
        """Obtiene DiskManager con inicialización lazy thread-safe"""
        if self.disk_manager is None:
            with self._lock:
                if self.disk_manager is None:
                    try:
                        from .disk_manager import DiskManager
                        self.disk_manager = DiskManager()
                        self._emit_event(EventType.STATE_CHANGED, {
                            "component": "disk_manager",
                            "action": "initialized"
                        }, "ApplicationState")
                    except Exception as e:
                        self._emit_event(EventType.STATE_CHANGED, {
                            "component": "disk_manager",
                            "action": "initialization_error",
                            "error": str(e)
                        }, "ApplicationState")
                        return None
        return self.disk_manager
    
    def set_theme(self, theme: str):
        """Cambia el tema de la aplicación usando el ThemeManager optimizado"""
        if theme != self.current_theme:
            old_theme = self.current_theme
            
            # Usar ThemeManager optimizado (temporalmente comentado)
            # if theme_manager.set_theme(theme):
            self.current_theme = theme
                
            # Guardar en configuración (usar getter lazy)
            app_config = self.get_app_config()
            if app_config:
                try:
                    app_config.set_theme(theme)
                except Exception as e:
                    log_error(f"[AppState] ⚠️ Error guardando tema: {e}")
                
            # Emitir eventos
            self._emit_event(EventType.THEME_CHANGED, {
                "old_theme": old_theme,
                "new_theme": theme
            }, "ApplicationState")
                
            emitter = self._get_signal_emitter()
            if emitter:
                emitter.theme_changed.emit(theme)
            # else:
            #     print(f"❌ No se pudo cambiar el tema a: {theme}")
    
    def set_font_size(self, font_size: int):
        """Cambia el tamaño de fuente usando el ThemeManager optimizado"""
        if font_size != self.current_font_size:
            old_size = self.current_font_size
            
            # Usar ThemeManager optimizado (temporalmente comentado)
            # if theme_manager.set_font_size(font_size):
            self.current_font_size = font_size
                
            # Guardar en configuración (usar getter lazy)
            app_config = self.get_app_config()
            if app_config:
                try:
                    app_config.set_font_size(font_size)
                except Exception as e:
                    log_error(f"[AppState] ⚠️ Error guardando font_size: {e}")
                
            self._emit_event(EventType.STATE_CHANGED, {
                "component": "font_size",
                "old_size": old_size,
                "new_size": font_size
            }, "ApplicationState")
            # else:
            #     print(f"❌ No se pudo cambiar el tamaño de fuente a: {font_size}")
    
    def set_current_disk(self, disk_path: str):
        """Establece el disco actualmente seleccionado"""
        if disk_path != self.current_disk:
            old_disk = self.current_disk
            self.current_disk = disk_path
            
            self._emit_event(EventType.DISK_SELECTED, {
                "old_disk": old_disk,
                "new_disk": disk_path
            }, "ApplicationState")
            
            emitter = self._get_signal_emitter()
            if emitter:
                emitter.disk_selected.emit(disk_path)
    
    def register_worker(self, worker_id: str, worker):
        """Registra un worker activo"""
        with self.worker_lock:
            self.active_workers[worker_id] = worker
            
            self._emit_event(EventType.WORKER_STARTED, {
                "worker_id": worker_id,
                "worker_type": type(worker).__name__
            }, "ApplicationState")
    
    def unregister_worker(self, worker_id: str):
        """Desregistra un worker completado"""
        with self.worker_lock:
            if worker_id in self.active_workers:
                del self.active_workers[worker_id]
                
                self._emit_event(EventType.WORKER_FINISHED, {
                    "worker_id": worker_id
                }, "ApplicationState")
    
    def get_active_workers(self) -> Dict[str, Any]:
        """Obtiene lista de workers activos"""
        with self.worker_lock:
            return self.active_workers.copy()
    
    def terminate_all_workers(self):
        """Termina todos los workers activos"""
        with self.worker_lock:
            for worker_id, worker in self.active_workers.items():
                try:
                    if hasattr(worker, 'terminate'):
                        worker.terminate()
                    elif hasattr(worker, 'stop'):
                        worker.stop()
                except Exception as e:
                    self._emit_event(EventType.STATE_CHANGED, {
                        "component": "worker_termination",
                        "worker_id": worker_id,
                        "error": str(e)
                    }, "ApplicationState")
            
            self.active_workers.clear()
    
    def set_cache(self, cache_name: str, data: Any):
        """Establece datos en caché"""
        with self.cache_lock:
            self.caches[cache_name] = data
    
    def get_cache(self, cache_name: str) -> Optional[Any]:
        """Obtiene datos del caché"""
        with self.cache_lock:
            return self.caches.get(cache_name)
    
    def clear_cache(self, cache_name: Optional[str] = None):
        """Limpia caché específico o todos los cachés"""
        with self.cache_lock:
            if cache_name:
                if cache_name in self.caches:
                    del self.caches[cache_name]
            else:
                self.caches.clear()
            
            self._emit_event(EventType.MEMORY_CLEANUP, {
                "cache_name": cache_name or "all",
                "action": "cleared"
            }, "ApplicationState")
    
    def add_observer(self, observer: Callable[[ApplicationEvent], None]):
        """Añade un observador del estado"""
        with self._observer_lock:
            if observer not in self._observers:
                self._observers.append(observer)
    
    def remove_observer(self, observer: Callable[[ApplicationEvent], None]):
        """Remueve un observador del estado"""
        with self._observer_lock:
            if observer in self._observers:
                self._observers.remove(observer)
    
    def _emit_event(self, event_type: EventType, data: Dict[str, Any], source: str):
        """Emite un evento a todos los observadores"""
        import time
        
        event = ApplicationEvent(
            event_type=event_type,
            data=data,
            timestamp=time.time(),
            source=source
        )
        
        # Emitir señal Qt (solo si el emisor está disponible)
        emitter = self._get_signal_emitter()
        if emitter:
            try:
                emitter.state_changed.emit(event)
            except Exception as e:
                log_error(f"[AppState] Error emitiendo señal: {e}")
        
        # Notificar observadores Python
        with self._observer_lock:
            for observer in self._observers:
                try:
                    observer(event)
                except Exception as e:
                    # Log error pero no interrumpir otros observadores
                    log_error(f"Error en observador: {e}")
    
    def get_state_summary(self) -> Dict[str, Any]:
        """Obtiene un resumen del estado actual"""
        return {
            "theme": self.current_theme,
            "font_size": self.current_font_size,
            "current_disk": self.current_disk,
            "active_workers": len(self.active_workers),
            "cache_count": len(self.caches),
            "observers_count": len(self._observers),
            "is_analysis_running": self.is_analysis_running,
            "is_organization_running": self.is_organization_running
        }
    
    def cleanup(self):
        """Limpieza completa del estado"""
        # Terminar workers
        self.terminate_all_workers()
        
        # Limpiar cachés
        self.clear_cache()
        
        # Limpiar observadores
        with self._observer_lock:
            self._observers.clear()
        
        # Limpiar ThemeManager (temporalmente comentado)
        # theme_manager.cleanup()
        
        self._emit_event(EventType.STATE_CHANGED, {
            "component": "ApplicationState",
            "action": "cleanup_completed"
        }, "ApplicationState")


# Instancia global del estado (lazy initialization)
_app_state_instance: Optional[ApplicationState] = None
_app_state_lock = threading.Lock()

def get_app_state() -> ApplicationState:
    """
    Obtiene la instancia global del estado (Singleton lazy)
    Crea la instancia solo cuando se solicita por primera vez
    """
    global _app_state_instance
    
    if _app_state_instance is None:
        with _app_state_lock:
            if _app_state_instance is None:
                debug("[AppState] Creando instancia global de ApplicationState...")
                try:
                    _app_state_instance = ApplicationState()
                    debug("[AppState] Instancia global creada OK")
                except Exception as e:
                    log_error(f"[AppState] ERROR CRÍTICO al crear instancia global: {e}")
                    import traceback
                    log_error(traceback.format_exc())
                    raise
    
    return _app_state_instance

# ===== PROXY MEJORADO CON LAZY INITIALIZATION VERDADERA =====
class _AppStateProxy:
    """
    Proxy para acceso lazy a app_state
    ⚠️ CRÍTICO: Solo crea la instancia cuando se accede a un atributo real
    
    Este proxy retrasa la creación de ApplicationState hasta que realmente se necesite,
    evitando problemas de importación circular y errores de inicialización prematura.
    """
    def __init__(self):
        # NO crear la instancia aquí - solo cuando se necesite
        object.__setattr__(self, '_instance_cache', None)
        object.__setattr__(self, '_initialization_attempted', False)
    
    def _get_instance(self):
        """Obtiene o crea la instancia de forma lazy"""
        cache = object.__getattribute__(self, '_instance_cache')
        if cache is None:
            attempted = object.__getattribute__(self, '_initialization_attempted')
            if not attempted:
                # Primera vez que se intenta crear la instancia
                object.__setattr__(self, '_initialization_attempted', True)
                try:
                    cache = get_app_state()
                    object.__setattr__(self, '_instance_cache', cache)
                except Exception as e:
                    log_error(f"[AppStateProxy] ERROR CRÍTICO creando ApplicationState: {e}")
                    import traceback
                    log_error(traceback.format_exc())
                    # No re-intentar en el futuro
                    cache = None
            else:
                # Ya se intentó antes y falló
                cache = None
        return cache
    
    def __getattr__(self, name):
        """Acceso lazy a atributos - crea instancia solo cuando se necesita"""
        try:
            instance = self._get_instance()
            if instance is None:
                log_warn(f"[AppStateProxy] ⚠️ ApplicationState no disponible, '{name}' = None")
                return None
            
            # ⚠️ CRÍTICO: Usar getters lazy para componentes pesados
            if name == 'app_config':
                return instance.get_app_config()
            elif name == 'category_manager':
                return instance.get_category_manager()
            elif name == 'disk_manager':
                # disk_manager ya tiene su getter
                return instance.get_disk_manager()
            else:
                # Para otros atributos, acceso directo
                return getattr(instance, name)
        except Exception as e:
            log_error(f"[AppStateProxy] ERROR accediendo a '{name}': {e}")
            import traceback
            log_error(traceback.format_exc())
            # Devolver None en lugar de fallar
            return None
    
    def __setattr__(self, name, value):
        """Establece atributos - crea instancia solo cuando se necesita"""
        if name.startswith('_'):
            # Atributos internos del proxy
            object.__setattr__(self, name, value)
        else:
            try:
                instance = self._get_instance()
                if instance is not None:
                    setattr(instance, name, value)
                else:
                    log_warn(f"[AppStateProxy] ⚠️ No se puede establecer '{name}': ApplicationState no disponible")
            except Exception as e:
                log_error(f"[AppStateProxy] ERROR estableciendo '{name}': {e}")
                import traceback
                log_error(traceback.format_exc())
    
    def __bool__(self):
        """Permite usar el proxy en condiciones booleanas"""
        try:
            instance = self._get_instance()
            return instance is not None
        except Exception:
            return False
    
    def __repr__(self):
        """Representación del proxy para debug"""
        try:
            cache = object.__getattribute__(self, '_instance_cache')
            attempted = object.__getattribute__(self, '_initialization_attempted')
            if cache is not None:
                return f"<AppStateProxy: instance={type(cache).__name__}>"
            elif attempted:
                return "<AppStateProxy: initialization failed>"
            else:
                return "<AppStateProxy: not initialized>"
        except AttributeError:
            return "<AppStateProxy: unknown state>"

# ⚠️ CRÍTICO: Crear el proxy pero NO la instancia
# La instancia se creará solo cuando se acceda a un atributo por primera vez
app_state = _AppStateProxy()
