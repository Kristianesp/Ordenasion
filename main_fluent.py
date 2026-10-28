#!/usr/bin/env python3
"""Punto de entrada de Ordenasion Fluent con arranque tematizado."""

import sys
import os
import traceback

from PyQt6.QtWidgets import QApplication, QMessageBox

from src.gui.v2.startup_splash import (
    FluentStartupSplash, apply_startup_palette, branding_icon, startup_theme_mode,
)
from src.utils.version import APP_NAME, APP_VERSION


def create_window():
    # Los imports y la construcción síncrona de widgets suceden después de
    # mostrar el splash. Nunca se construyen QWidget en un worker.
    from src.utils.app_config import AppConfig
    from src.gui.main_window import FileOrganizerGUI
    from src.gui.v2.app_window import FluentAppWindow

    config = AppConfig()
    legacy_window = FileOrganizerGUI(app_config_ref=config)
    return FluentAppWindow(legacy_window)


def start_window(app):
    mode = startup_theme_mode()
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(branding_icon())
    apply_startup_palette(app, mode)
    splash = FluentStartupSplash(mode)
    splash.show()
    app.processEvents()
    window = None
    try:
        window = create_window()
        window.setWindowIcon(app.windowIcon())
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
        traceback.print_exc()
        if os.environ.get("ORDENASION_SMOKE") == "1":
            raise
        QMessageBox.critical(None, "No se pudo iniciar Ordenasion", f"{exc}\n\nCierra este mensaje y vuelve a intentarlo.")
        return None


def main() -> int:
    if os.environ.get("ORDENASION_SMOKE") == "1":
        from src.gui.v2.release_smoke import run_smoke
        return run_smoke(start_window)
    app = QApplication(sys.argv)
    window = start_window(app)
    if window is None:
        return 1
    try:
        return app.exec()
    finally:
        window._startup_splash.close()


if __name__ == "__main__":
    raise SystemExit(main())
