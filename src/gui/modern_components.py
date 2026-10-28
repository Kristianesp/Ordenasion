#!/usr/bin/env python3
"""
Componentes UI Estandarizados para el Organizador de Archivos
Componentes reutilizables con diseño consistente y temático
"""

from typing import Dict, Any, Optional, List, Callable
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QComboBox,
    QSpinBox,
    QCheckBox,
    QProgressBar,
    QGroupBox,
    QFrame,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMessageBox,
    QFileDialog,
    QSlider,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor

from ..utils.constants import UI_CONFIG

# Diccionario de temas activos inyectado externamente (por defecto del tema Claro Elegante)
_THEME_COLORS = {
    "primary": "#1976d2",
    "primary_dark": "#1565c0",
    "secondary": "#42a5f5",
    "accent": "#ff9800",
    "success": "#388e3c",
    "success_light": "#4caf50",
    "warning": "#f57c00",
    "warning_light": "#ff9800",
    "error": "#d32f2f",
    "error_light": "#f44336",
    "text_primary": "#212121",
    "text_secondary": "#757575",
    "text_disabled": "#999",
    "surface": "#ffffff",
    "surface_alt": "#fafafa",
    "background": "#fafafa",
    "border": "#e0e0e0",
    "border_light": "#f5f5f5",
    "shadow": "rgba(0, 0, 0, 0.1)",
}


def _tc(key: str) -> str:
    """Obtiene color del tema actual o fallback del diccionario."""
    return _THEME_COLORS.get(key, _THEME_COLORS["primary"])


def set_theme_colors(colors: dict):
    """Inyecta los colores del tema activo en los componentes."""
    _THEME_COLORS.update(
        {
            "primary": colors.get("primary", _THEME_COLORS["primary"]),
            "primary_dark": colors.get(
                "button_hover", colors.get("secondary", _THEME_COLORS["primary_dark"])
            ),
            "secondary": colors.get("secondary", _THEME_COLORS["secondary"]),
            "accent": colors.get("accent", _THEME_COLORS["accent"]),
            "success": colors.get("success", _THEME_COLORS["success"]),
            "success_light": _THEME_COLORS["success_light"],
            "warning": colors.get("warning", _THEME_COLORS["warning"]),
            "warning_light": colors.get("warning", _THEME_COLORS["warning_light"]),
            "error": colors.get("error", _THEME_COLORS["error"]),
            "error_light": colors.get("error", _THEME_COLORS["error_light"]),
            "text_primary": colors.get("text_primary", _THEME_COLORS["text_primary"]),
            "text_secondary": colors.get(
                "text_secondary", _THEME_COLORS["text_secondary"]
            ),
            "text_disabled": colors.get(
                "text_disabled", _THEME_COLORS["text_disabled"]
            ),
            "surface": colors.get("surface", _THEME_COLORS["surface"]),
            "surface_alt": colors.get("surface_variant", _THEME_COLORS["surface_alt"]),
            "background": colors.get("background", _THEME_COLORS["background"]),
            "border": colors.get("border", _THEME_COLORS["border"]),
            "border_light": colors.get(
                "surface_variant", _THEME_COLORS["border_light"]
            ),
            "shadow": "rgba(0, 0, 0, 0.1)",
        }
    )


class ModernButton(QPushButton):
    """
    Botón moderno con estilos consistentes y efectos hover
    """

    # Señales personalizadas
    clicked_with_data = pyqtSignal(object)  # Para pasar datos adicionales

    def __init__(
        self,
        text: str = "",
        icon: str = "",
        button_type: str = "primary",
        data: Any = None,
        parent=None,
    ):
        super().__init__(text, parent)

        self.button_type = button_type
        self.data = data
        self.icon_text = icon

        self.setup_ui()
        self.setup_styles()
        self.setup_connections()

    def setup_ui(self):
        """Configura la UI del botón"""
        # Configuración básica
        self.setMinimumHeight(UI_CONFIG["BUTTON_HEIGHT"])
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # Icono si se proporciona
        if self.icon_text:
            self.setText(f"{self.icon_text} {self.text()}")

    def setup_styles(self):
        """Aplica estilos según el tipo de botón con colores del tema."""
        p, pd, s = _tc("primary"), _tc("primary_dark"), _tc("secondary")
        succ, succ_l = _tc("success"), _tc("success_light")
        warn, warn_l = _tc("warning"), _tc("warning_light")
        err, err_l = _tc("error"), _tc("error_light")
        dis = _tc("text_disabled")

        styles = {
            "primary": f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {p}, stop:1 {pd});
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {s}, stop:1 {p});
                }}
                QPushButton:pressed {{
                    background: {pd};
                }}
                QPushButton:disabled {{
                    background: #666;
                    color: {dis};
                }}
            """,
            "secondary": f"""
                QPushButton {{
                    background: transparent;
                    color: {p};
                    border: 2px solid {p};
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 6px 16px;
                }}
                QPushButton:hover {{
                    background: {p}15;
                    border-color: {pd};
                }}
                QPushButton:pressed {{
                    background: {p}30;
                }}
                QPushButton:disabled {{
                    background: transparent;
                    color: {dis};
                    border-color: {dis};
                }}
            """,
            "success": f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {succ_l}, stop:1 {succ});
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background: {succ_l};
                }}
                QPushButton:pressed {{
                    background: {succ};
                }}
            """,
            "warning": f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {warn_l}, stop:1 {warn});
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background: {warn_l};
                }}
                QPushButton:pressed {{
                    background: {warn};
                }}
            """,
            "danger": f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 {err_l}, stop:1 {err});
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: bold;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background: {err_l};
                }}
                QPushButton:pressed {{
                    background: {err};
                }}
            """,
            "ghost": f"""
                QPushButton {{
                    background: transparent;
                    color: {_tc("text_secondary")};
                    border: none;
                    border-radius: 8px;
                    padding: 8px 16px;
                }}
                QPushButton:hover {{
                    background: {_tc("border_light")};
                    color: {_tc("text_primary")};
                }}
                QPushButton:pressed {{
                    background: {_tc("border")};
                }}
            """,
        }

        self.setStyleSheet(styles.get(self.button_type, styles["primary"]))

    def setup_connections(self):
        """Configura las conexiones de señales"""
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        """Maneja el clic del botón"""
        self.clicked_with_data.emit(self.data)

    def set_button_type(self, button_type: str):
        """Cambia el tipo de botón"""
        self.button_type = button_type
        self.setup_styles()

    def set_data(self, data: Any):
        """Establece datos adicionales"""
        self.data = data


class ModernInput(QLineEdit):
    """
    Campo de entrada moderno con validación y estilos consistentes
    """

    # Señales personalizadas
    validation_changed = pyqtSignal(bool)  # valid/invalid
    value_changed = pyqtSignal(str)  # nuevo valor

    def __init__(
        self,
        placeholder: str = "",
        input_type: str = "text",
        required: bool = False,
        validator: Callable = None,
        parent=None,
    ):
        super().__init__(parent)

        self.placeholder = placeholder
        self.input_type = input_type
        self.required = required
        self.validator = validator
        self.is_valid = True

        self.setup_ui()
        self.setup_styles()
        self.setup_connections()

    def setup_ui(self):
        """Configura la UI del campo de entrada"""
        if hasattr(self, "placeholder") and self.placeholder:
            self.setPlaceholderText(self.placeholder)
        self.setMinimumHeight(UI_CONFIG["INPUT_HEIGHT"])

        # Configuración según el tipo
        if self.input_type == "password":
            self.setEchoMode(QLineEdit.EchoMode.Password)
        elif self.input_type == "number":
            self.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly)

    def setup_styles(self):
        """Aplica estilos al campo de entrada con colores del tema."""
        self.setStyleSheet(f"""
            QLineEdit {{
                border: 2px solid {_tc("border")};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 14px;
                background-color: {_tc("surface")};
                color: {_tc("text_primary")};
            }}
            QLineEdit:focus {{
                border-color: {_tc("primary")};
                background-color: {_tc("surface_alt")};
            }}
            QLineEdit:invalid {{
                border-color: {_tc("error")};
                background-color: {_tc("error")}15;
            }}
            QLineEdit:disabled {{
                background-color: {_tc("border_light")};
                color: {_tc("text_disabled")};
                border-color: {_tc("border")};
            }}
        """)

    def setup_connections(self):
        """Configura las conexiones de señales"""
        self.textChanged.connect(self._on_text_changed)
        self.editingFinished.connect(self._validate)

    def _on_text_changed(self, text: str):
        """Maneja el cambio de texto"""
        self.value_changed.emit(text)

        # Validación en tiempo real para campos requeridos
        if self.required and not text.strip():
            self._set_validity(False)
        elif self.validator:
            self._validate()

    def _validate(self):
        """Valida el contenido del campo"""
        text = self.text().strip()

        # Validación requerida
        if self.required and not text:
            self._set_validity(False)
            return False

        # Validación personalizada
        if self.validator and text:
            is_valid = self.validator(text)
            self._set_validity(is_valid)
            return is_valid

        # Si llega aquí, es válido
        self._set_validity(True)
        return True

    def _set_validity(self, is_valid: bool):
        """Establece el estado de validez - re-aplica estilos completos."""
        if self.is_valid != is_valid:
            self.is_valid = is_valid
            self.validation_changed.emit(is_valid)
            # Re-aplicar estilos para forzar actualización visual correcta
            self.setup_styles()

    def get_value(self) -> str:
        """Obtiene el valor del campo"""
        return self.text().strip()

    def set_value(self, value: str):
        """Establece el valor del campo"""
        self.setText(value)
        self._validate()


class ModernCard(QFrame):
    """
    Tarjeta moderna con sombra y efectos hover
    """

    def __init__(
        self,
        title: str = "",
        content_widget: QWidget = None,
        card_type: str = "default",
        parent=None,
    ):
        super().__init__(parent)

        self.title = title
        self.content_widget = content_widget
        self.card_type = card_type

        self.setup_ui()
        self.setup_styles()

    def setup_ui(self):
        """Configura la UI de la tarjeta"""
        self.setFrameStyle(QFrame.Shape.Box)
        self.setMinimumHeight(100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Título si se proporciona
        if self.title:
            title_label = QLabel(self.title)
            title_label.setObjectName("card_title")
            title_label.setStyleSheet(f"""
                QLabel#card_title {{
                    font-size: 18px;
                    font-weight: bold;
                    color: {_tc("text_primary")};
                    margin-bottom: 10px;
                }}
            """)
            layout.addWidget(title_label)

        # Widget de contenido si se proporciona
        if self.content_widget:
            layout.addWidget(self.content_widget)

    def setup_styles(self):
        """Aplica estilos a la tarjeta con colores del tema."""
        surf = _tc("surface")
        bdr = _tc("border")
        p = _tc("primary")

        styles = {
            "default": f"""
                QFrame {{
                    background-color: {surf};
                    border: 1px solid {bdr};
                    border-radius: 12px;
                }}
                QFrame:hover {{
                    border-color: {p};
                }}
            """,
            "elevated": f"""
                QFrame {{
                    background-color: {surf};
                    border: none;
                    border-radius: 12px;
                }}
            """,
            "outlined": f"""
                QFrame {{
                    background-color: transparent;
                    border: 2px solid {bdr};
                    border-radius: 12px;
                }}
                QFrame:hover {{
                    border-color: {p};
                    background-color: {_tc("surface_alt")};
                }}
            """,
        }

        self.setStyleSheet(styles.get(self.card_type, styles["default"]))


class ModernProgressBar(QProgressBar):
    """
    Barra de progreso moderna con estilos mejorados
    """

    def __init__(
        self, progress_type: str = "default", show_text: bool = True, parent=None
    ):
        super().__init__(parent)

        self.progress_type = progress_type
        self.show_text = show_text

        self.setup_ui()
        self.setup_styles()

    def setup_ui(self):
        """Configura la UI de la barra de progreso"""
        self.setMinimumHeight(8)
        self.setMaximumHeight(12)

        if self.show_text:
            self.setTextVisible(True)
        else:
            self.setTextVisible(False)

    def setup_styles(self):
        """Aplica estilos a la barra de progreso con colores del tema."""
        bdr = _tc("border")
        tp = _tc("text_primary")
        p = _tc("primary")
        s = _tc("secondary")
        succ = _tc("success")
        succ_l = _tc("success_light")
        warn = _tc("warning")
        warn_l = _tc("warning_light")
        err = _tc("error")
        err_l = _tc("error_light")

        styles = {
            "default": f"""
                QProgressBar {{
                    border: none;
                    border-radius: 6px;
                    background-color: {bdr};
                    text-align: center;
                    color: {tp};
                    font-weight: bold;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 {p}, stop:1 {s});
                    border-radius: 6px;
                }}
            """,
            "success": f"""
                QProgressBar {{
                    border: none;
                    border-radius: 6px;
                    background-color: {bdr};
                    text-align: center;
                    color: {tp};
                    font-weight: bold;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 {succ}, stop:1 {succ_l});
                    border-radius: 6px;
                }}
            """,
            "warning": f"""
                QProgressBar {{
                    border: none;
                    border-radius: 6px;
                    background-color: {bdr};
                    text-align: center;
                    color: {tp};
                    font-weight: bold;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 {warn}, stop:1 {warn_l});
                    border-radius: 6px;
                }}
            """,
            "danger": f"""
                QProgressBar {{
                    border: none;
                    border-radius: 6px;
                    background-color: {bdr};
                    text-align: center;
                    color: {tp};
                    font-weight: bold;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 {err}, stop:1 {err_l});
                    border-radius: 6px;
                }}
            """,
        }

        self.setStyleSheet(styles.get(self.progress_type, styles["default"]))

    def set_progress_type(self, progress_type: str):
        """Cambia el tipo de barra de progreso"""
        self.progress_type = progress_type
        self.setup_styles()


class ModernCheckbox(QCheckBox):
    """
    Checkbox moderno con estilos mejorados
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)

        self.setup_styles()

    def setup_styles(self):
        """Aplica estilos al checkbox con colores del tema."""
        p = _tc("primary")
        tp = _tc("text_primary")
        bdr = _tc("border")
        surf = _tc("surface")
        bl = _tc("border_light")

        self.setStyleSheet(f"""
            QCheckBox {{
                font-size: 14px;
                color: {tp};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 2px solid {bdr};
                border-radius: 4px;
                background-color: {surf};
            }}
            QCheckBox::indicator:checked {{
                background-color: {p};
                border-color: {p};
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEwIDNMNC41IDguNUwyIDYiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }}
            QCheckBox::indicator:hover {{
                border-color: {p};
            }}
            QCheckBox::indicator:disabled {{
                background-color: {bl};
                border-color: {bdr};
            }}
        """)


class ModernComboBox(QComboBox):
    """
    ComboBox moderno con estilos mejorados
    """

    def __init__(self, items: List[str] = None, parent=None):
        super().__init__(parent)

        if items:
            self.addItems(items)

        self.setup_styles()

    def setup_styles(self):
        """Aplica estilos al ComboBox con colores del tema."""
        bdr = _tc("border")
        p = _tc("primary")
        surf = _tc("surface")
        tp = _tc("text_primary")

        self.setStyleSheet(f"""
            QComboBox {{
                border: 2px solid {bdr};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 14px;
                background-color: {surf};
                color: {tp};
                min-width: 100px;
            }}
            QComboBox:focus {{
                border-color: {p};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTMgNEw2IDdMOSA0IiBzdHJva2U9IiM2NjYiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }}
            QComboBox QAbstractItemView {{
                border: 1px solid {bdr};
                border-radius: 8px;
                background-color: {surf};
                color: {tp};
                selection-background-color: {p}30;
            }}
        """)


class ModernSpinBox(QSpinBox):
    """
    SpinBox moderno con estilos mejorados
    """

    def __init__(
        self, minimum: int = 0, maximum: int = 100, value: int = 0, parent=None
    ):
        super().__init__(parent)

        self.setRange(minimum, maximum)
        self.setValue(value)

        self.setup_styles()

    def setup_styles(self):
        """Aplica estilos al SpinBox con colores del tema."""
        bdr = _tc("border")
        p = _tc("primary")
        surf = _tc("surface")
        tp = _tc("text_primary")
        bl = _tc("border_light")

        self.setStyleSheet(f"""
            QSpinBox {{
                border: 2px solid {bdr};
                border-radius: 8px;
                padding: 8px 12px;
                font-size: 14px;
                background-color: {surf};
                color: {tp};
                min-width: 80px;
            }}
            QSpinBox:focus {{
                border-color: {p};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                border: none;
                background-color: {bl};
                width: 20px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background-color: {bdr};
            }}
            QSpinBox::up-arrow, QSpinBox::down-arrow {{
                width: 8px;
                height: 8px;
            }}
        """)


# Funciones de utilidad para crear componentes rápidamente
def create_button(
    text: str,
    button_type: str = "primary",
    icon: str = "",
    data: Any = None,
    parent=None,
) -> ModernButton:
    """Crea un botón moderno rápidamente"""
    return ModernButton(text, icon, button_type, data, parent)


def create_input(
    placeholder: str = "",
    input_type: str = "text",
    required: bool = False,
    validator: Callable = None,
    parent=None,
) -> ModernInput:
    """Crea un campo de entrada moderno rápidamente"""
    return ModernInput(placeholder, input_type, required, validator, parent)


def create_card(
    title: str = "",
    content_widget: QWidget = None,
    card_type: str = "default",
    parent=None,
) -> ModernCard:
    """Crea una tarjeta moderna rápidamente"""
    return ModernCard(title, content_widget, card_type, parent)


def create_progress_bar(
    progress_type: str = "default", show_text: bool = True, parent=None
) -> ModernProgressBar:
    """Crea una barra de progreso moderna rápidamente"""
    return ModernProgressBar(progress_type, show_text, parent)


def create_checkbox(text: str = "", parent=None) -> ModernCheckbox:
    """Crea un checkbox moderno rápidamente"""
    return ModernCheckbox(text, parent)


def create_combo_box(items: List[str] = None, parent=None) -> ModernComboBox:
    """Crea un ComboBox moderno rápidamente"""
    return ModernComboBox(items, parent)


def create_spin_box(
    minimum: int = 0, maximum: int = 100, value: int = 0, parent=None
) -> ModernSpinBox:
    """Crea un SpinBox moderno rápidamente"""
    return ModernSpinBox(minimum, maximum, value, parent)


class TabHeaderWidget(QWidget):
    config_requested = pyqtSignal()
    tasks_requested = pyqtSignal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("tab_header_title")
        self.title_label.setWordWrap(True)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        layout.addWidget(self.title_label, 1)

        self.config_btn = QPushButton("⚙️ Config")
        self.config_btn.setObjectName("tab_header_config_btn")
        self.config_btn.setFixedHeight(UI_CONFIG["BUTTON_HEIGHT"])
        self.config_btn.setMinimumWidth(80)
        self.config_btn.clicked.connect(self.config_requested.emit)
        layout.addWidget(self.config_btn)

        self.tasks_btn = QPushButton("🧵 Tareas")
        self.tasks_btn.setObjectName("tab_header_tasks_btn")
        self.tasks_btn.setFixedHeight(UI_CONFIG["BUTTON_HEIGHT"])
        self.tasks_btn.setMinimumWidth(80)
        self.tasks_btn.clicked.connect(self.tasks_requested.emit)
        layout.addWidget(self.tasks_btn)
