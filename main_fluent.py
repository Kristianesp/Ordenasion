#!/usr/bin/env python3
"""Punto de entrada de Ordenasion Fluent con arranque tematizado."""

import sys
import os
import traceback

if __name__ == "__main__":
    # Antes de importar Qt: también mide (y vigila) la carga de librerías,
    # que en el ejecutable onefile es la parte más lenta del arranque.
    from src.utils import startup_diagnostics

    startup_diagnostics.begin()

from PyQt6.QtWidgets import QApplication, QMessageBox

from src.gui.v2.startup_splash import (
    FluentStartupSplash, apply_startup_palette, branding_icon, startup_theme_mode,
)
from src.utils.version import APP_NAME, APP_VERSION


def create_window():
    # Los imports y la construcción síncrona de widgets suceden después de
    # mostrar el splash. Nunca se construyen QWidget en un worker.
    from src.utils.app_config import AppConfig
    from src.gui.organize_controller import OrganizeController
    from src.gui.v2.app_window import FluentAppWindow

    config = AppConfig()
    controller = OrganizeController()
    window = FluentAppWindow(config, controller)
    controller.setParent(window)
    return window


def dispose_window(window) -> None:
    """Destruye la ventana y el splash antes de que Python finalice.

    Si quedan vivos hasta el final, la limpieza de PyQt los borra mientras
    recorre sus envoltorios y la cascada de hijos (tablas Fluent incluidas)
    puede acabar en un fallo de segmentación al salir.
    """
    from PyQt6 import sip

    for widget in (getattr(window, "_startup_splash", None), window):
        if widget is not None and not sip.isdeleted(widget):
            sip.delete(widget)


def _milestone(name: str) -> None:
    from src.utils import startup_diagnostics

    startup_diagnostics.milestone(name)


def start_window(app):
    mode = startup_theme_mode()
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(branding_icon())
    apply_startup_palette(app, mode)
    splash = FluentStartupSplash(mode)
    splash.show()
    app.processEvents()
    _close_bootloader_splash()
    _milestone("splash visible")
    window = None
    try:
        window = create_window()
        _milestone("ventana construida")
        window.setWindowIcon(app.windowIcon())
        from src.utils import startup_diagnostics

        splash.finished.connect(lambda: startup_diagnostics.finish(splash.revealed_by_fallback))
        splash.prepare_window(window)
        window.show_maximized_safe()
        # Mantener referencia durante el event loop; el splash se cierra al
        # terminar la primera pintura, aunque el usuario cierre inmediatamente.
        window._startup_splash = splash
        return window
    except Exception as exc:
        splash.close()
        if window is not None:
            window.close()
        from src.utils.logger import get_logger, log_directory
        get_logger().error("No se pudo iniciar Ordenasion:\n%s", traceback.format_exc())
        if os.environ.get("ORDENASION_SMOKE") == "1":
            raise
        QMessageBox.critical(None, "No se pudo iniciar Ordenasion",
                             f"{exc}\n\nEl detalle está en {log_directory()}.\n"
                             "Cierra este mensaje y vuelve a intentarlo.")
        return None


def _close_bootloader_splash() -> None:
    """Cierra la imagen que muestra el ejecutable mientras se descomprime."""
    try:
        import pyi_splash  # sólo existe en el ejecutable con Splash de PyInstaller
    except ImportError:
        return
    try:
        pyi_splash.close()
    except RuntimeError:
        pass


def main() -> int:
    if os.environ.get("ORDENASION_SMOKE") == "1":
        from src.gui.v2.release_smoke import run_smoke
        return run_smoke(start_window, dispose_window)
    _milestone("librerías cargadas")
    app = QApplication(sys.argv)
    _milestone("QApplication creada")
    window = start_window(app)
    if window is None:
        _close_bootloader_splash()
        return 1
    try:
        return app.exec()
    finally:
        window._startup_splash.close()
        dispose_window(window)
        from src.utils import startup_diagnostics

        startup_diagnostics.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
