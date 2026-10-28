#!/usr/bin/env python3
"""Recolector de basura sólo en el hilo de la interfaz.

El recolector automático de Python se ejecuta en el hilo que esté reservando
memoria en ese momento. Si recoge un ciclo que contiene widgets de Qt mientras
trabaja un hilo de fondo (organizar, analizar, leer discos), PyQt destruye esos
widgets desde ese hilo: en Windows es un fallo nativo que cierra la aplicación
sin pasar por ``sys.excepthook``. Y si ocurre mientras qfluentwidgets recorre
sus widgets (``updateStyleSheet``), su señal ``destroyed`` modifica el
diccionario a mitad («dictionary changed size during iteration»).

Solución habitual en PyQt: desactivar el recolector automático y ejecutarlo
periódicamente desde un QTimer, que siempre corre en el hilo de la interfaz.
Los objetos sin ciclos se siguen liberando al instante por recuento de
referencias; sólo cambia cuándo se recogen los ciclos.
"""

import gc

from PyQt6.QtCore import QObject, QTimer

INTERVAL_MS = 500


class MainThreadGarbageCollector(QObject):
    """Ejecuta ``gc.collect`` por generaciones desde el hilo de la interfaz."""

    def __init__(self, parent=None, interval_ms: int = INTERVAL_MS):
        super().__init__(parent)
        self.threshold = gc.get_threshold()
        gc.disable()
        self.timer = QTimer(self)
        self.timer.setInterval(interval_ms)
        self.timer.timeout.connect(self.check)
        self.timer.start()

    def check(self) -> None:
        """Recoge la generación más antigua cuyo umbral se ha superado."""
        counts = gc.get_count()
        for generation in (2, 1, 0):
            if counts[generation] > self.threshold[generation]:
                gc.collect(generation)
                break

    def stop(self) -> None:
        """Vuelve al recolector automático (al cerrar la aplicación)."""
        self.timer.stop()
        gc.enable()
        gc.collect()


_collector = None


def install(app) -> MainThreadGarbageCollector:
    """Instala el recolector (una vez) colgado de la QApplication."""
    global _collector
    if _collector is None:
        _collector = MainThreadGarbageCollector(app)
    return _collector


def uninstall() -> None:
    global _collector
    if _collector is not None:
        _collector.stop()
        _collector = None
