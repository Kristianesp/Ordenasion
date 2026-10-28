#!/usr/bin/env python3
"""
Punto de entrada OPTIMIZADO para el Organizador de Archivos
🚀 Arranque 3-4x más rápido con carga progresiva y caché
"""

import sys
import os
import traceback
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING
from src.utils.version import APP_VERSION

if TYPE_CHECKING:
    from src.gui.splash_screen import ModernSplashScreen

ModernSplashScreen: Any = None
ProgressiveLoader: Any = None
theme_cache: Any = None

# ===== CONFIGURAR LOGGING DESDE EL INICIO =====
log_file = "startup_log.txt"
IS_FROZEN = bool(getattr(sys, "frozen", False))

# ⚠️ CRÍTICO: Redirigir stdout/stderr para capturar TODOS los prints en el log
_original_stdout = sys.stdout
_original_stderr = sys.stderr


def _safe_console_write(
    text: str, add_newline: bool = False, target_handle=None
) -> None:
    """Escribe texto al stdout/err original usando solo caracteres soportados."""
    handle = target_handle or _original_stdout
    if handle is None or IS_FROZEN:
        return
    try:
        encoding = getattr(handle, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="ignore").decode(
            encoding, errors="ignore"
        )
        if add_newline:
            safe_text = safe_text + ("\n" if not safe_text.endswith("\n") else "")
        handle.write(safe_text)
        handle.flush()
    except Exception:
        pass


class LoggingStdout:
    """Wrapper para stdout que escribe al log"""

    def __init__(self, original_stdout, forward_to_console=True):
        self.original_stdout = original_stdout
        self.buffer = []
        self.forward_to_console = forward_to_console

    def write(self, text):
        """Escribe tanto al stdout original como al log"""
        if text.strip():  # Solo escribir si hay contenido
            try:
                # Escribir al log
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                log_line = f"[{timestamp}] {text.rstrip()}\n"
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(log_line)
                    f.flush()
            except Exception:
                pass
        if self.forward_to_console:
            self._write_safe(text)

    def flush(self):
        try:
            if self.forward_to_console and self.original_stdout:
                self.original_stdout.flush()
        except Exception:
            pass

    def _write_safe(self, text: str) -> None:
        """Escribe al stdout original ignorando caracteres no soportados (ej. emojis)"""
        _safe_console_write(text, add_newline=False, target_handle=self.original_stdout)


# Redirigir stdout para capturar prints
sys.stdout = LoggingStdout(_original_stdout, forward_to_console=not IS_FROZEN)
sys.stderr = LoggingStdout(_original_stderr, forward_to_console=not IS_FROZEN)


def log_message(msg):
    """Escribe mensaje en el log con timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    log_line = f"[{timestamp}] {msg}\n"
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_line)
            f.flush()  # Forzar escritura inmediata
        _safe_console_write(log_line.strip(), add_newline=True)
    except Exception as e:
        _safe_console_write(f"ERROR escribiendo log: {e}", add_newline=True)


# Hook global para capturar TODAS las excepciones
def excepthook(exc_type, exc_value, exc_traceback):
    """Captura TODAS las excepciones no manejadas"""
    try:
        log_message("=" * 80)
        log_message("❌ EXCEPCIÓN NO CAPTURADA")
        log_message("=" * 80)
        log_message(f"Tipo: {exc_type.__name__}")
        log_message(f"Error: {exc_value}")
        log_message("Traceback completo:")
        import traceback

        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        for line in tb_lines:
            log_message(line.strip())
        log_message("=" * 80)
    except:
        pass
    # Llamar al hook original
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


# Configurar el hook ANTES de cualquier otra cosa
sys.excepthook = excepthook

# Iniciar log
try:
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write(f"ORDENASION v{APP_VERSION} - LOG DE INICIO\n")
        f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")
        f.flush()
    log_message("✅ Log iniciado correctamente")
except Exception as e:
    print(f"❌ ERROR creando archivo de log: {e}")

log_message(f"Python version: {sys.version}")
log_message(f"Platform: {sys.platform}")
log_message(f"Executable: {sys.executable}")
log_message(f"Current directory: {os.getcwd()}")

# Añadir el directorio src al path para importaciones
log_message("Añadiendo directorio src al path...")
try:
    # Detectar si estamos ejecutando desde PyInstaller
    if getattr(sys, "frozen", False):
        # Ejecutando desde ejecutable empaquetado
        application_path = getattr(sys, "_MEIPASS", Path(__file__).parent)
        log_message(f"Ejecutando desde PyInstaller: {application_path}")
    else:
        # Ejecutando desde script Python
        application_path = Path(__file__).parent
        log_message(f"Ejecutando desde script: {application_path}")

    src_path = str(Path(application_path) / "src")
    sys.path.insert(0, src_path)
    sys.path.insert(0, str(application_path))
    log_message(f"✅ Path añadido: {src_path}")
    log_message(f"✅ Application path añadido: {application_path}")

    # Verificar que el directorio src existe
    if Path(src_path).exists():
        log_message(f"✅ Directorio src existe")
        # Listar contenido para debug
        try:
            contents = list(Path(src_path).iterdir())
            log_message(f"Contenido de src: {[p.name for p in contents[:10]]}")
        except Exception as e:
            log_message(f"⚠️ No se pudo listar contenido: {e}")
    else:
        log_message(f"❌ ADVERTENCIA: Directorio src NO existe en {src_path}")

except Exception as e:
    log_message(f"❌ ERROR añadiendo path: {e}")
    log_message(traceback.format_exc())

log_message("Importando PyQt6...")
try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QFont

    log_message("✅ PyQt6 importado correctamente")
except Exception as e:
    log_message(f"❌ ERROR importando PyQt6: {e}")
    log_message(traceback.format_exc())
    sys.exit(1)


def show_error_dialog(title, message, details=""):
    """Muestra un diálogo de error cuando falla la carga"""
    log_message(f"Mostrando diálogo de error: {title}")
    try:
        app = QApplication.instance()
        if app is None:
            log_message("Creando nueva instancia de QApplication para error...")
            app = QApplication(sys.argv)

        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        if details:
            msg_box.setDetailedText(details)
        msg_box.exec()
        log_message("Diálogo de error cerrado")
    except Exception as e:
        log_message(f"❌ ERROR mostrando diálogo: {e}")
        log_message(traceback.format_exc())


def main():
    """Función principal OPTIMIZADA de la aplicación con manejo de errores"""
    log_message("=" * 80)
    log_message("INICIANDO FUNCIÓN MAIN")
    log_message("=" * 80)

    try:
        # Crear aplicación Qt
        log_message("Creando QApplication...")
        app = QApplication(sys.argv)
        log_message("✅ QApplication creada")

        app.setApplicationName("Organizador de Archivos")
        app.setApplicationVersion(APP_VERSION)
        log_message("✅ Nombre y versión configurados")

        # Configurar fuente por defecto
        log_message("Configurando fuente por defecto...")
        font = QFont("Segoe UI", 9)
        app.setFont(font)
        log_message("✅ Fuente configurada")

        # Intentar cargar con splash screen
        log_message("Intentando cargar splash screen...")
        use_splash = False
        try:
            from src.gui.splash_screen import ModernSplashScreen, ProgressiveLoader
            from src.utils.theme_cache import theme_cache

            use_splash = True
            log_message("✅ Splash screen importado correctamente")
        except Exception as e:
            log_message(f"⚠️ No se pudo cargar splash screen: {e}")
            log_message(traceback.format_exc())
            use_splash = False

        splash: Any = None
        window = None

        if use_splash:
            # ✅ OPTIMIZACIÓN 1: Mostrar splash screen
            log_message("Creando y mostrando splash screen...")
            try:
                splash = ModernSplashScreen(width=500, height=300)
                splash.show()
                app.processEvents()
                log_message("✅ Splash screen mostrado")
            except Exception as e:
                log_message(f"❌ Error mostrando splash: {e}")
                log_message(traceback.format_exc())
                use_splash = False

            # ✅ OPTIMIZACIÓN 2: Precargar caché de temas
            if use_splash:
                try:
                    log_message("Precargando caché de temas...")
                    assert splash is not None
                    splash.set_progress(
                        10, "Precargando temas...", "Optimizando rendimiento"
                    )
                    app.processEvents()
                    theme_cache.preload_theme(
                        "🌞 Claro Elegante", font_sizes=[10, 11, 12, 14, 16]
                    )
                    theme_cache.preload_theme("🌙 Oscuro Profesional", font_sizes=[12])
                    theme_cache.preload_theme("⚫ Lujo Minimalista", font_sizes=[12])
                    log_message("✅ Temas precargados")
                except Exception as e:
                    log_message(f"⚠️ Error precargando temas: {e}")
                    log_message(traceback.format_exc())

            # ✅ OPTIMIZACIÓN 3: Importar componentes
            if use_splash:
                log_message("Actualizando splash: Cargando componentes...")
                assert splash is not None
                splash.set_progress(30, "Cargando componentes...", "Importando módulos")
                app.processEvents()

        # Importar ventana principal
        log_message("Importando ventana principal...")
        log_message("Paso 1: Verificando sys.path...")
        log_message(f"sys.path contiene: {sys.path[:5]}...")

        log_message("Paso 2: Intentando importar src...")
        try:
            import src

            log_message(f"✅ src importado desde: {src.__file__}")
        except Exception as e:
            log_message(f"❌ ERROR importando src: {e}")
            log_message(traceback.format_exc())
            raise

        log_message("Paso 3: Intentando importar src.gui...")
        try:
            import src.gui

            log_message(f"✅ src.gui importado desde: {src.gui.__file__}")
        except Exception as e:
            log_message(f"❌ ERROR importando src.gui: {e}")
            log_message(traceback.format_exc())
            raise

        log_message("Paso 4: Intentando importar src.gui.main_window...")
        log_message("  Usando import directo con manejo robusto de errores...")

        # Importar módulos necesarios primero para evitar errores
        log_message("  4.0: Pre-importando dependencias críticas...")
        try:
            log_message("     - Importando src.utils.constants...")
            from src.utils.constants import COLORS, DIALOG_STYLES, UI_CONFIG

            log_message("     ✅ src.utils.constants importado")
        except Exception as e:
            log_message(f"     ❌ Error importando constants: {e}")
            log_message(traceback.format_exc())
            raise

        try:
            log_message("     - Importando src.utils.themes...")
            from src.utils.themes import ThemeManager

            log_message("     ✅ src.utils.themes importado")
        except Exception as e:
            log_message(f"     ❌ Error importando themes: {e}")
            log_message(traceback.format_exc())
            raise

        try:
            log_message("     - Importando src.utils.app_config...")
            from src.utils.app_config import AppConfig

            log_message("     ✅ src.utils.app_config importado")
        except Exception as e:
            log_message(f"     ❌ Error importando app_config: {e}")
            log_message(traceback.format_exc())
            raise

        try:
            log_message("     - Importando src.core.application_state...")
            from src.core.application_state import app_state, EventType

            log_message("     ✅ src.core.application_state importado")
        except Exception as e:
            log_message(f"     ❌ Error importando application_state: {e}")
            log_message(traceback.format_exc())
            raise

        try:
            log_message("     - Importando src.gui.table_models...")
            from src.gui.table_models import VirtualizedMovementsModel

            log_message("     ✅ src.gui.table_models importado")
        except Exception as e:
            log_message(f"     ❌ Error importando table_models: {e}")
            log_message(traceback.format_exc())
            raise

        # Ahora intentar importar main_window
        log_message(
            "  4.1: Importando src.gui.main_window (todas las dependencias ya están cargadas)..."
        )
        try:
            from src.gui.main_window import FileOrganizerGUI
            from src.gui.v2.app_window import FluentAppWindow

            log_message("  ✅ FileOrganizerGUI y FluentAppWindow importados correctamente")
        except ImportError as import_err:
            log_message(f"  ❌ ImportError: {import_err}")
            if hasattr(import_err, "name"):
                log_message(f"     Módulo faltante: {import_err.name}")
            log_message("     Traceback completo:")
            for line in traceback.format_exc().split("\n"):
                if line.strip():
                    log_message(f"       {line}")
            raise
        except Exception as e:
            log_message(f"  ❌ Error importando main_window: {type(e).__name__}: {e}")
            log_message("     Traceback completo:")
            for line in traceback.format_exc().split("\n"):
                if line.strip():
                    log_message(f"       {line}")
            raise

        # FileOrganizerGUI ya fue importado en el paso 4.1
        log_message("✅ Todos los módulos necesarios importados correctamente")

        if use_splash:
            log_message("Actualizando splash: Creando interfaz...")
            assert splash is not None
            splash.set_progress(50, "Creando interfaz...", "Inicializando ventana")
            app.processEvents()

        # Crear ventana principal
        log_message("Creando shell Fluent V2 y controlador heredado...")
        try:
            # Los prints ahora se capturan automáticamente por LoggingStdout
            legacy_window = FileOrganizerGUI()
            window = FluentAppWindow(legacy_window)
            log_message("✅ Shell Fluent V2 creado")
        except Exception as e:
            log_message(f"❌ ERROR CRÍTICO creando ventana: {e}")
            log_message(traceback.format_exc())
            raise

        if use_splash:
            log_message("Actualizando splash: Inicializando gestores...")
            assert splash is not None
            splash.set_progress(70, "Inicializando gestores...", "Preparando sistema")
            app.processEvents()

        # Nota: _init_disk_manager() y apply_saved_interface_settings() ya se llaman
        # automáticamente dentro de FileOrganizerGUI.__init__() para evitar duplicación
        if use_splash:
            log_message("Actualizando splash: Finalizando...")
            assert splash is not None
            splash.set_progress(100, "¡Listo!", "Abriendo aplicación...")
            app.processEvents()

        # Mostrar ventana
        log_message("Mostrando ventana principal...")
        if use_splash and splash:
            # Cerrar splash con fade y mostrar ventana
            log_message("Cerrando splash con fade...")
            QTimer.singleShot(300, lambda: splash.finish_with_fade(window))
            QTimer.singleShot(350, window.show_maximized_safe)
        else:
            window.show_maximized_safe()

        log_message("✅ Ventana mostrada")
        log_message("Iniciando event loop de Qt...")
        log_message("=" * 80)
        log_message("APLICACIÓN INICIADA CORRECTAMENTE")
        log_message("=" * 80)

        if os.environ.get("ORDENASION_SMOKE") == "1":
            log_message("Modo smoke activo: cerrando tras validar el arranque")
            QTimer.singleShot(500, app.quit)

        # Ejecutar aplicación
        return app.exec()

    except Exception as e:
        # Capturar cualquier error y mostrarlo
        log_message("=" * 80)
        log_message("❌ ERROR FATAL EN MAIN")
        log_message("=" * 80)
        error_msg = f"Error al iniciar la aplicación:\n\n{str(e)}"
        error_details = traceback.format_exc()
        log_message(f"Error: {error_msg}")
        log_message(f"Detalles:\n{error_details}")

        print(f"❌ {error_msg}")
        print(error_details)

        try:
            log_message("Intentando mostrar diálogo de error...")
            show_error_dialog("Error de Inicio", error_msg, error_details)
        except Exception as dialog_error:
            log_message(f"❌ No se pudo mostrar diálogo: {dialog_error}")
            # Si ni siquiera podemos mostrar el diálogo, escribir a archivo
            try:
                with open("error_log.txt", "w", encoding="utf-8") as f:
                    f.write(f"{error_msg}\n\n{error_details}")
                log_message("Error guardado en error_log.txt")
            except Exception as file_error:
                log_message(f"❌ No se pudo guardar error_log.txt: {file_error}")

        log_message("=" * 80)
        log_message("SALIENDO CON ERROR")
        log_message("=" * 80)
        return 1


if __name__ == "__main__":
    log_message("=" * 80)
    log_message("SCRIPT INICIADO")
    log_message("=" * 80)
    try:
        exit_code = main()
        log_message(f"Aplicación terminada con código: {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        log_message(f"❌ EXCEPCIÓN NO CAPTURADA: {e}")
        log_message(traceback.format_exc())
        sys.exit(1)
