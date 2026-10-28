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

# Carpeta para archivos no categorizados
VARIOS_FOLDER = "VARIOS_REVISAR"

# 🎨 Colores Modernos con Accesibilidad WCAG 2.1 AA
COLORS = {
    # Colores principales con contraste mejorado
    "PRIMARY": "#1976d2",           # Azul Material Design - Ratio 4.5:1
    "SECONDARY": "#42a5f5",         # Azul claro accesible
    "ACCENT": "#ff9800",            # Naranja vibrante
    "SUCCESS": "#388e3c",           # Verde Material - Ratio 4.5:1
    "WARNING": "#f57c00",           # Naranja advertencia - Ratio 4.5:1
    "ERROR": "#d32f2f",             # Rojo error - Ratio 5.4:1
    "INFO": "#1976d2",              # Azul información

    # Superficies y fondos
    "BACKGROUND": "#fafafa",        # Fondo principal - Ratio 15.8:1
    "SURFACE": "#ffffff",           # Superficie blanca - Ratio 21:1
    "SURFACE_VARIANT": "#f5f5f5",   # Superficie alternativa

    # Texto con contraste optimizado
    "TEXT_PRIMARY": "#212121",      # Negro suave - Ratio 16.6:1
    "TEXT_SECONDARY": "#757575",    # Gris medio - Ratio 4.6:1
    "TEXT_DISABLED": "#bdbdbd",     # Gris claro para deshabilitado

    # Bordes y divisores
    "BORDER": "#e0e0e0",            # Borde sutil - Ratio 1.8:1
    "BORDER_FOCUS": "#1976d2",      # Borde en foco
    "DIVIDER": "#e0e0e0",           # Líneas divisorias

    # Estados de tabla mejorados
    "TABLE_HEADER": "#f8f9fa",      # Cabecera de tabla
    "TABLE_ROW_EVEN": "#ffffff",    # Fila par
    "TABLE_ROW_ODD": "#fafafa",     # Fila impar
    "TABLE_SELECTED": "#e3f2fd",    # Selección de tabla
    "TABLE_HOVER": "#f5f5f5",       # Hover en tabla

    # Grupos y elementos expandibles
    "GROUP_NORMAL": "#f8f9fa",      # Grupos normales con mejor contraste
    "GROUP_EXPANDED": "#e3f2fd",    # Grupos expandidos - azul suave
    "FILE_EXPANDED": "#f5f5f5",     # Archivos expandidos

    # Elementos de selección
    "SELECTION": "#1976d2",         # Color de selección principal
    "SELECTION_LIGHT": "#e3f2fd",   # Selección suave

    # Sombras para profundidad visual
    "SHADOW_LIGHT": "rgba(0, 0, 0, 0.08)",
    "SHADOW_MEDIUM": "rgba(0, 0, 0, 0.12)",
    "SHADOW_STRONG": "rgba(0, 0, 0, 0.16)",
    
    # Colores adicionales específicos
    "HEADER_BG": "#f8f9fa"           # Color de fondo para encabezados (igual que TABLE_HEADER)
}

# 🔧 Configuración Moderna de la Interfaz
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

# Los estilos de la tabla ahora se manejan dinámicamente por el sistema de temas

# 💫 Estilos CSS Modernos para Diálogos y Popups
DIALOG_STYLES = """
    /* Diálogos con diseño moderno y accesible */
    QDialog, QMessageBox, QInputDialog, QFileDialog {
        background-color: #ffffff;
        color: #212121;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
    }

    /* Etiquetas en diálogos */
    QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {
        color: #212121;
        background-color: transparent;
        font-size: 12px;
    }

    /* Botones modernos en diálogos */
    QDialog QPushButton, QMessageBox QPushButton, QInputDialog QPushButton {
        background-color: #1976d2;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 6px;
        font-weight: 600;
        min-height: 32px;
        font-size: 12px;
    }

    QDialog QPushButton:hover, QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {
        background-color: #42a5f5;
    }

    QDialog QPushButton:pressed, QMessageBox QPushButton:pressed, QInputDialog QPushButton:pressed {
        background-color: #ff9800;
    }

    /* Campos de entrada modernos */
    QDialog QLineEdit, QInputDialog QLineEdit {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        padding: 8px 12px;
        border-radius: 6px;
        color: #212121;
        font-size: 12px;
        min-height: 20px;
    }

    QDialog QLineEdit:focus, QInputDialog QLineEdit:focus {
        border-color: #1976d2;
        border-width: 2px;
    }

    /* Listas en diálogos */
    QDialog QListWidget, QInputDialog QListWidget {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        color: #212121;
        font-size: 12px;
    }

    /* Grupos en diálogos */
    QDialog QGroupBox, QInputDialog QGroupBox {
        font-weight: 600;
        color: #212121;
        border: 1px solid #e0e0e0;
        border-radius: 6px;
        margin-top: 16px;
        padding-top: 16px;
        font-size: 12px;
    }

    QDialog QGroupBox::title, QInputDialog QGroupBox::title {
        subcontrol-origin: margin;
        left: 16px;
        padding: 0 8px;
        background-color: #1976d2;
        color: white;
        border-radius: 4px;
    }
"""

# Emojis normalizados para mensajes (centralizados para i18n/consistencia)
EMOJI = {
    "green": "🟢",
    "yellow": "🟡",
    "orange": "🟠",
    "red": "🔴",
    "info": "ℹ️",
}

# Etiquetas de estado de salud (prefijos)
HEALTH_LABELS = {
    "excellent": "EXCELENTE",
    "healthy": "SALUDABLE",
    "attention": "ATENCIÓN",
    "warning": "ADVERTENCIA",
    "critical": "CRÍTICO",
}