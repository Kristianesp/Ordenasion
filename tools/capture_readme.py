"""Capturas reales del README con fixtures temporales y servicios bloqueados.

Ejecutar desde la raíz con venv/Scripts/python.exe tools/capture_readme.py.
No carga preferencias del workspace ni analiza unidades o archivos personales.
"""

import contextlib
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "images"
sys.path.insert(0, str(ROOT))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "1"
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def main():
    original = Path.cwd()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ordenasion-readme-") as temporary:
        try:
            os.chdir(temporary)
            # Imports después de aislar cwd: servicios singleton y JSON locales.
            from PyQt6.QtTest import QTest
            from PyQt6.QtCore import QRectF
            from PyQt6.QtGui import QColor, QImage, QPainter
            from PyQt6.QtSvg import QSvgRenderer
            from PyQt6.QtWidgets import QApplication
            from src.core.space_usage import scan_space
            from src.core.disk_manager import DiskManager
            from src.core.audio_index import audio_metadata_service
            from src.core.audio_fingerprint import audio_fingerprint_service
            from src.gui.main_window import FileOrganizerGUI
            from src.gui.v2.app_window import FluentAppWindow
            from src.gui.v2.theme import register_bundled_fonts
            from src.utils.app_config import AppConfig

            fixture = Path(temporary) / "Demo temporal"
            fixture.mkdir()
            for folder, files in {
                "Documentos": [("Informe de ejemplo.pdf", 90), ("Notas del proyecto.txt", 28)],
                "Imagenes": [("Paisaje demo.png", 180), ("Ilustracion demo.jpg", 120)],
                "Musica": [("Pista de ejemplo.mp3", 250), ("Ambiente demo.wav", 140)],
                "Videos": [("Presentacion demo.mp4", 320)],
                "Codigo": [("Proyecto de ejemplo.py", 40)],
            }.items():
                target = fixture / folder
                target.mkdir()
                for name, size in files:
                    (target / name).write_bytes(b"0" * size * 1024)
            (fixture / "Leeme demo.txt").write_bytes(b"0" * 12 * 1024)
            # Solo este árbol temporal; la ocupación de unidad es un fixture.
            with patch("src.core.space_usage.shutil.disk_usage", return_value=SimpleNamespace(total=256 * 1024**3, used=156 * 1024**3, free=100 * 1024**3)):
                result = scan_space(str(fixture))
            # Rutas de presentación ficticias; no se abre ni escanea esta unidad.
            for node in result.nodes:
                relative = Path(node.path).relative_to(fixture)
                node.path = str(Path("Z:/DEMO TEMPORAL") / relative)
            result.root_path = "Z:/DEMO TEMPORAL"
            drive = SimpleNamespace(mountpoint="Z:/ · DEMO", total_size=256 * 1024**3,
                                    used_size=156 * 1024**3, free_size=100 * 1024**3)
            denied = AssertionError("Servicio externo bloqueado en captura README")
            with contextlib.ExitStack() as guards:
                for owner, method in ((FileOrganizerGUI, "start_analysis"),
                                      (DiskManager, "get_all_disks"),
                                      (audio_metadata_service, "update_track_tags"),
                                      (audio_fingerprint_service, "get_or_lookup_online_metadata"),
                                      (audio_fingerprint_service, "get_cover_art_bytes_for_url")):
                    guards.enter_context(patch.object(owner, method, side_effect=denied))
                guards.enter_context(patch.object(FileOrganizerGUI, "_init_disk_manager", lambda *_: None))
                guards.enter_context(patch.object(FileOrganizerGUI, "_refresh_disk_viewer_after_theme", lambda *_: None))
                guards.enter_context(patch("socket.create_connection", side_effect=denied))
                guards.enter_context(patch("urllib.request.urlopen", side_effect=denied))
                app = QApplication.instance() or QApplication([])
                register_bundled_fonts()
                renderer = QSvgRenderer(str(OUTPUT / "banner.svg"))
                assert renderer.isValid()
                banner = QImage(1200, 400, QImage.Format.Format_ARGB32)
                banner.fill(QColor("#101e36"))
                painter = QPainter(banner)
                renderer.render(painter)
                painter.end()
                assert banner.save(str(OUTPUT / "banner.png"))
                social = QImage(1200, 630, QImage.Format.Format_ARGB32)
                social.fill(QColor("#101e36"))
                painter = QPainter(social)
                renderer.render(painter, QRectF(0, 115, 1200, 400))
                painter.end()
                assert social.save(str(OUTPUT / "social-preview.png"))
                config = AppConfig(str(Path(temporary) / "capture-config.json"))
                config.set_theme_mode("dark")
                controller = FileOrganizerGUI(app_config_ref=config)
                window = FluentAppWindow(controller)
                window.setWindowTitle("Ordenasion 3.5.0 · DEMO / datos ficticios")
                window.resize(1440, 960)
                window.show()
                viewer = controller.disk_viewer
                viewer.available_disks = [drive]
                viewer.disks_updated_at = datetime(2026, 9, 27, 12, 30)
                space = window._routes["disks"].space_page
                space.path_input.setText(result.root_path)
                space._completed(0, result)

                def capture(name, route):
                    window._switch_route(route)
                    QTest.qWait(450)
                    app.processEvents()
                    image = window.grab()
                    assert image.width() == 1440 and not image.isNull()
                    assert image.save(str(OUTPUT / name))

                capture("inicio-oscuro.png", "home")
                config.set_theme_mode("light")
                window._refresh_theme()
                capture("inicio-claro.png", "home")
                config.set_theme_mode("dark")
                window._refresh_theme()
                capture("uso-del-espacio.png", "space")
                capture("configuracion.png", "settings")
                assert space._worker is None
                window.close()
                app.processEvents()
        finally:
            os.chdir(original)
    print("4 capturas Qt reales · fixtures temporales · servicios bloqueados")


if __name__ == "__main__":
    main()
