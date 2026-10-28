#!/usr/bin/env python3
"""
Constantes de la aplicación Organizador de Archivos
"""

# Configuración de categorías por defecto
CATEGORIAS = {
    "MUSICA": [".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".wma"],
    "VIDEOS": [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"],
    "IMAGENES": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".svg"],
    "DOCUMENTOS": [".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".ppt", ".pptx"],
    "PROGRAMAS": [".exe", ".msi", ".deb", ".rpm", ".dmg", ".pkg", ".zip", ".rar", ".7z"],
    "CODIGO": [".py", ".js", ".html", ".css", ".cpp", ".c", ".java", ".php", ".rb", ".go"]
}

# Categoría y carpeta para archivos no categorizados.
# Antes convivían "VARIOS" (donde acababan los archivos) y "VARIOS_REVISAR"
# (que se creaba vacía). Ahora hay una sola carpeta; el nombre antiguo se
# reconoce como carpeta de categoría para no reorganizarla.
VARIOS_CATEGORY = "VARIOS"
VARIOS_FOLDER = "VARIOS"
LEGACY_VARIOS_FOLDERS = ("VARIOS_REVISAR",)

UI_CONFIG = {
    "WINDOW_TITLE": "Organizador de Archivos y Carpetas",  # Sin emoji para profesionalidad
    "WINDOW_WIDTH": 1200,
    "WINDOW_HEIGHT": 800,
    "WINDOW_MIN_WIDTH": 800,        # Ancho mínimo para responsive
    "WINDOW_MIN_HEIGHT": 600,       # Alto mínimo para responsive

    # Alturas optimizadas para usabilidad de escritorio
    "TABLE_ROW_HEIGHT": 37,
    "BUTTON_HEIGHT": 33,
    "INPUT_HEIGHT": 33,
    "TAB_HEIGHT": 36,                # Altura de pestañas

    # Espaciado y padding
    "PADDING_SMALL": 8,              # Padding pequeño
    "PADDING_MEDIUM": 16,            # Padding medio
    "PADDING_LARGE": 24,             # Padding grande
    "MARGIN_SMALL": 8,               # Margen pequeño
    "MARGIN_MEDIUM": 16,             # Margen medio
    "MARGIN_LARGE": 24,              # Margen grande

    # Bordes y redondeo
    "BORDER_RADIUS": 8,              # Radio de bordes estándar
    "BORDER_RADIUS_LARGE": 12,       # Radio de bordes grande
    "BORDER_WIDTH": 1,               # Ancho de borde estándar
    "BORDER_WIDTH_FOCUS": 2,         # Ancho de borde en foco

    # Tipografía
    "FONT_SIZE_SMALL": 11,           # Texto pequeño
    "FONT_SIZE_NORMAL": 13,          # Texto normal
    "FONT_SIZE_MEDIUM": 15,          # Texto medio
    "FONT_SIZE_LARGE": 16,           # Texto grande
    "FONT_SIZE_TITLE": 20,           # Títulos
    "FONT_FAMILY": "'Nunito', 'Segoe UI Variable', 'Segoe UI', sans-serif",

    # Animaciones y transiciones
    "ANIMATION_DURATION": 200,       # Duración de animaciones en ms
    "ANIMATION_EASING": "cubic-bezier(0.4, 0, 0.2, 1)",  # Curva de animación Material
}

# Métodos de búsqueda de duplicados (clave, etiqueta visible)
DUPLICATE_METHODS = [
    ("fast", "Rápido (candidatos)"),
    ("hybrid", "Híbrido (confirmado por hash)"),
    ("deep", "Profundo (por contenido)"),
    ("similar", "Imágenes parecidas"),
]
