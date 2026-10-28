import os
import tempfile

# Los datos de usuario (config, cachés, registros) nunca deben tocar el
# perfil real ni el directorio del repositorio durante los tests.
os.environ.setdefault("ORDENASION_DATA_DIR", tempfile.mkdtemp(prefix="ordenasion-tests-"))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
