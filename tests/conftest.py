import gc
import os
import tempfile

import pytest

# Los datos de usuario (config, cachés, registros) nunca deben tocar el
# perfil real ni el directorio del repositorio durante los tests.
os.environ.setdefault("ORDENASION_DATA_DIR", tempfile.mkdtemp(prefix="ordenasion-tests-"))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


@pytest.fixture(autouse=True)
def _main_thread_garbage_collection():
    """Como en la app (src/utils/gc_guard.py): los ciclos con widgets se recogen
    en el hilo principal entre tests, nunca desde un hilo de fondo ni a mitad de
    un recorrido de qfluentwidgets (updateStyleSheet)."""
    gc.disable()
    gc.collect()
    yield
    gc.collect()
