"""Prueba de punta a punta de «Organizar» con la ventana real (opt-in).

Se activa con ORDENASION_E2E=1 al abrir main_fluent.py o el ejecutable, o
con ``python tools/e2e_organize.py``. Crea una carpeta temporal con archivos
de ejemplo, analiza, marca «Todo», pulsa «Revisar y organizar», marca
«Confirmo que quiero proceder…», pulsa «Confirmar y organizar», cierra el
resumen, comprueba que los archivos acabaron en sus categorías, deshace y
comprueba que vuelven. Nunca toca datos del usuario (carpetas temporales).
"""

import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ERRORS = []
# El ejecutable no tiene consola: ORDENASION_E2E_LOG indica el archivo de salida
_OUT = {"file": None}


def _write(text):
    for stream in (sys.stdout, _OUT["file"]):
        if stream is not None:
            try:
                stream.write(text + "\n")
                stream.flush()
            except (OSError, ValueError):
                pass


def _hook(exc_type, exc, tb):
    ERRORS.append("".join(traceback.format_exception(exc_type, exc, tb)))
    _write("EXCEPCIÓN NO CAPTURADA:\n" + ERRORS[-1])


SAMPLES = {
    "factura.pdf": b"%PDF" + b"x" * 500,
    "foto.jpg": b"\xff\xd8" + b"y" * 900,
    "cancion.mp3": b"ID3" + b"z" * 700,
    "notas.txt": b"hola",
    "script.py": b"print(1)",
    "video.mp4": b"\x00" * 800,
}


def log(message):
    _write(f"[e2e] {message}")


def pump(app, seconds, until=None):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until is not None else True


def run(start_window, dispose_window) -> int:
    """Ejecuta el recorrido completo; devuelve 0 sólo si todo fue bien."""
    os.environ.setdefault("ORDENASION_DATA_DIR", tempfile.mkdtemp(prefix="ordenasion-e2e-data-"))
    target = os.environ.get("ORDENASION_E2E_LOG")
    if target:
        _OUT["file"] = open(target, "w", encoding="utf-8")
    crash_stream = _OUT["file"] or sys.stderr
    if crash_stream is not None:
        faulthandler.enable(file=crash_stream, all_threads=True)
        faulthandler.dump_traceback_later(120, exit=True, file=crash_stream)
    sys.excepthook = _hook
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv)

    source = Path(tempfile.mkdtemp(prefix="ordenasion-e2e-")) / "Descargas"
    source.mkdir()
    for name, data in SAMPLES.items():
        (source / name).write_bytes(data)
    (source / "Fotos verano").mkdir()
    for index in range(3):
        (source / "Fotos verano" / f"img{index}.jpg").write_bytes(b"\xff\xd8" + bytes([index]) * 300)
    original = sorted(str(p.relative_to(source)) for p in source.rglob("*"))

    window = start_window(app)
    if window is None:
        log("no se pudo crear la ventana")
        return 1
    pump(app, 4, until=lambda: not window._startup_splash.isVisible())
    log(f"ventana visible: {window.isVisible()}")
    window.switchTo(window._routes["organize"])
    page = window._routes["organize"]
    page.folder_input.setText(str(source))
    page.start_analysis()
    if not pump(app, 30, until=lambda: not page.controller.busy and page.movements_model.rowCount() > 0):
        log("el análisis no terminó")
        return 1
    log(f"análisis: {page.movements_model.rowCount()} filas")
    QTest.mouseClick(page.select_all_btn, Qt.MouseButton.LeftButton)
    pump(app, 0.3)
    log(f"«Revisar y organizar» activo: {page.organize_btn.isEnabled()}")

    seen = []

    def handle_dialogs():
        dialog = QApplication.activeModalWidget()
        if dialog is None:
            QTimer.singleShot(150, handle_dialogs)
            return
        kind = type(dialog).__name__
        if kind not in seen:
            seen.append(kind)
        log(f"diálogo: {kind}")
        if kind == "PreviewDialog":
            QTest.mouseClick(dialog.confirm_checkbox, Qt.MouseButton.LeftButton)
            pump(app, 0.2)
            log(f"casilla marcada: {dialog.confirm_checkbox.isChecked()}, botón: {dialog.confirm_btn.isEnabled()}")
            QTest.mouseClick(dialog.confirm_btn, Qt.MouseButton.LeftButton)
        else:
            dialog.accept()
        QTimer.singleShot(300, handle_dialogs)

    QTimer.singleShot(300, handle_dialogs)
    QTest.mouseClick(page.organize_btn, Qt.MouseButton.LeftButton)
    log("organización lanzada")
    pump(app, 30, until=lambda: (page.controller.last_operation_summary or {}).get("status")
         and "OperationSummaryDialog" in seen and QApplication.activeModalWidget() is None)
    summary = page.controller.last_operation_summary or {}
    organized = sorted(str(p.relative_to(source)) for p in source.rglob("*"))
    log(f"resumen: {summary.get('status')} · {summary.get('files_moved')} archivos · "
        f"{summary.get('folders_moved')} carpetas · errores {summary.get('errors')}")
    ok = summary.get("status") == "completado" and any(name.startswith("DOCUMENTOS") for name in organized)

    # Deshacer y comprobar que todo vuelve a su sitio
    transaction = summary.get("transaction_id")
    if ok and transaction:
        pump(app, 3)  # refresco automático tras organizar
        page.rollback_transaction(transaction, confirm=False)
        pump(app, 30, until=lambda: not page.controller.current_rollback_task_id
             and sorted(str(p.relative_to(source)) for p in source.rglob("*")) == original)
        restored = sorted(str(p.relative_to(source)) for p in source.rglob("*")) == original
        log(f"deshacer restauró el original: {restored}")
        ok = ok and restored
    pump(app, 1)
    dispose_window(window)
    faulthandler.cancel_dump_traceback_later()
    ok = ok and not ERRORS
    log("RESULTADO: " + ("OK" if ok else f"FALLO ({len(ERRORS)} excepciones)"))
    return 0 if ok else 1

