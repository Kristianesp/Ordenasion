"""Smoke opt-in del paquete: GUI real, cwd temporal y servicios bloqueados."""

import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
from unittest.mock import patch

from src.utils.version import APP_VERSION


def run_smoke(start_window):
    original_cwd = Path.cwd()
    temporary = Path(tempfile.mkdtemp(prefix="ordenasion-release-smoke-"))
    target = os.environ.get("ORDENASION_SMOKE_REPORT")
    report_path = Path(target).resolve() if target else temporary / "smoke-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = report_path.with_suffix(".log")
    report = {"version": APP_VERSION, "status": "error", "frozen": bool(getattr(sys, "frozen", False)),
              "temporary_cwd": str(temporary), "log": str(log_path)}
    exit_code = 1
    window = None
    try:
        os.chdir(temporary)
        with log_path.open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                from PyQt6.QtCore import QTimer
                from PyQt6.QtGui import QImage, QFont, QFontMetrics
                from PyQt6.QtWidgets import QApplication
                from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
                from src.gui.v2.startup_splash import BRANDING_DIR, ICON_PATH, BACKGROUND_PATH, startup_font_family
                from src.gui.main_window import FileOrganizerGUI
                from src.core.disk_manager import DiskManager
                from src.core.audio_index import audio_metadata_service
                from src.core.audio_fingerprint import audio_fingerprint_service

                app = QApplication.instance() or QApplication(sys.argv)
                bundle = BRANDING_DIR.parents[1]
                report["assets"] = {
                    "icon": not QImage(str(ICON_PATH)).isNull(),
                    "ico": not QImage(str(ICON_PATH.with_suffix(".ico"))).isNull(),
                    "background": not QImage(str(BACKGROUND_PATH)).isNull(),
                    "fonts": QFontMetrics(QFont(startup_font_family())).inFont("…"),
                    "font_license": (BRANDING_DIR.parent / "fonts" / "OFL.txt").is_file(),
                    "tokens": isinstance(json.loads((bundle / "design-tokens.json").read_text(encoding="utf-8")), dict),
                }
                if not all(report["assets"].values()):
                    raise RuntimeError("Assets incompletos en el paquete")
                if report["frozen"]:
                    assert not (bundle / "app_config.json").exists()
                    assert not (bundle / "organization_profiles.json").exists()
                    report["private_config_excluded"] = True
                report["qt_multimedia"] = bool(QMediaPlayer and QAudioOutput)
                denied = AssertionError("Servicio externo no permitido durante smoke")
                with contextlib.ExitStack() as guards:
                    guards.enter_context(patch.object(FileOrganizerGUI, "_init_disk_manager", lambda self: None))
                    guards.enter_context(patch.object(FileOrganizerGUI, "_refresh_disk_viewer_after_theme", lambda *_: None))
                    guards.enter_context(patch.object(FileOrganizerGUI, "start_analysis", side_effect=denied))
                    guards.enter_context(patch.object(DiskManager, "get_all_disks", side_effect=denied))
                    guards.enter_context(patch.object(audio_metadata_service, "update_track_tags", side_effect=denied))
                    guards.enter_context(patch.object(audio_fingerprint_service, "get_or_lookup_online_metadata", side_effect=denied))
                    guards.enter_context(patch.object(audio_fingerprint_service, "get_cover_art_bytes_for_url", side_effect=denied))
                    guards.enter_context(patch("socket.create_connection", side_effect=denied))
                    guards.enter_context(patch("urllib.request.urlopen", side_effect=denied))
                    window = start_window(app)
                    if window is None:
                        raise RuntimeError("No se creó la ventana Fluent")
                    state = {"finished": False}
                    watchdog = QTimer()
                    watchdog.setSingleShot(True)

                    def fail_timeout():
                        state["error"] = "La primera pintura no terminó dentro del límite de smoke"
                        app.quit()

                    def ready():
                        try:
                            assert not window._startup_splash.isVisible()
                            assert window.isVisible() and window.windowOpacity() == 1
                            assert not window.windowIcon().isNull()
                            assert app.applicationVersion() == APP_VERSION
                            assert APP_VERSION in window.windowTitle()
                            assert window._routes["disks"].space_page._worker is None
                            assert not window.grab().isNull()
                            report["first_frame"] = True
                            report["routes"] = list(window._routes)
                            capture = os.environ.get("ORDENASION_SMOKE_CAPTURE")
                            if capture:
                                assert window.grab().save(capture)
                            window.close()
                            assert not window.isVisible()
                            report["graceful_close"] = True
                            state["finished"] = True
                        except Exception:
                            state["error"] = traceback.format_exc()
                        finally:
                            app.quit()

                    watchdog.timeout.connect(fail_timeout)
                    watchdog.start(15000)
                    if window._startup_splash.isVisible():
                        window._startup_splash.finished.connect(ready)
                    else:
                        QTimer.singleShot(0, ready)
                    app.exec()
                    watchdog.stop()
                    if not state["finished"]:
                        raise RuntimeError(state.get("error", "La ventana cerró antes de completar smoke"))
                    report["status"] = "ok"
                    exit_code = 0
            except Exception:
                report["error"] = traceback.format_exc()
                traceback.print_exc()
            finally:
                if window is not None:
                    window._startup_splash.close()
                    if window.isVisible():
                        window.close()
    finally:
        os.chdir(original_cwd)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return exit_code
