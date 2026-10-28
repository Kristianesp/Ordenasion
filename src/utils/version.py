"""Versión de la aplicación y del ejecutable de Windows."""

APP_NAME = "Ordenasion"
APP_VERSION = "3.5.0"
VERSION_INFO = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)
EXECUTABLE_NAME = f"{APP_NAME}_v{APP_VERSION}"
