"""Prueba de punta a punta de «Organizar» con la ventana real.

Uso: python -X faulthandler tools/e2e_organize.py
(equivale a abrir la app con ORDENASION_E2E=1; ver src/gui/v2/release_e2e.py)
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    import main_fluent
    from src.gui.v2.release_e2e import run

    raise SystemExit(run(main_fluent.start_window, main_fluent.dispose_window))
