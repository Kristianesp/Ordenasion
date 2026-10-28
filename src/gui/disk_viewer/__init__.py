"""Visor de Discos (paquete).

- ``viewer``: DiskViewer, la vista principal (compatibilidad con
  ``from src.gui.disk_viewer import DiskViewer``).
- ``disk_list``: rejilla de tarjetas de unidades.
- ``detail_panel``: panel de detalle de la unidad seleccionada.
- ``health_renderer``: HTML puro de salud, información y contenido.
- ``styles``: paletas y hoja de estilos del modo heredado.
- ``controller``: consultas SMART y de contenido fuera del hilo de la UI.
"""

from PyQt6.QtWidgets import QMessageBox  # noqa: F401  (los tests lo parchean aquí)

from src.gui.disk_viewer.viewer import DiskViewer

__all__ = ["DiskViewer"]
