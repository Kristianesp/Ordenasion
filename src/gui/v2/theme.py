"""Configuración visual centralizada para la interfaz Fluent.

Fachada estable (``from src.gui.v2.theme import ...``) sobre tres módulos:

- ``theme_tokens``: colores, vidrio, tipografía y firma visual;
- ``theme_palette``: paleta, tema de qfluentwidgets y alturas de control;
- ``theme_qss``: hojas de estilo del shell, puente heredado, diálogos y menús.
"""

from src.gui.v2.theme_tokens import *  # noqa: F401,F403
from src.gui.v2.theme_tokens import _to_theme  # noqa: F401
from src.gui.v2.theme_palette import *  # noqa: F401,F403
from src.gui.v2.theme_palette import _config_from_widget  # noqa: F401
from src.gui.v2.theme_qss import *  # noqa: F401,F403
