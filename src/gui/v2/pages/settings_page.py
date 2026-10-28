"""Configuración visual y accesos a la configuración avanzada."""

from PyQt6.QtCore import Qt, pyqtSignal
import re

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
)

from src.gui.v2.components import GlassCard, PageHeader
from src.gui.v2.theme import apply_fluent_theme
from src.utils.app_config import AppConfig


class SettingsPage(ScrollArea):
    """Ajustes de apariencia y puente hacia la configuración existente."""

    theme_changed = pyqtSignal()
    advanced_settings_requested = pyqtSignal()

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("settingsPage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWidgetResizable(True)
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        self.enableTransparentBackground()

        self.content = QWidget()
        self.content.setObjectName("settingsContent")
        self.setWidget(self.content)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(28, 24, 28, 28)
        outer.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.settings_panel = QWidget()
        self.settings_panel.setObjectName("settingsPanel")
        self.settings_panel.setMaximumWidth(1120)
        self.settings_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        outer.addWidget(self.settings_panel)
        layout = QVBoxLayout(self.settings_panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(PageHeader(
            "Configuración", "Ajusta el texto, el espacio y el color de la interfaz."
        ))

        self.appearance_grid = QGridLayout()
        self.appearance_grid.setSpacing(16)
        self.text_card = GlassCard()
        self.text_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        text_layout = QVBoxLayout(self.text_card)
        text_layout.setContentsMargins(20, 18, 20, 18)
        text_layout.setSpacing(10)
        text_layout.addWidget(SubtitleLabel("Texto y espacio"))
        self.font_size = ComboBox()
        self.font_size.setAccessibleName("Tamaño de texto")
        self.font_size.setMaximumWidth(320)
        for label, size in (("Pequeño", 11), ("Normal", 13), ("Grande", 15)):
            self.font_size.addItem(label)
            self.font_size.setItemData(self.font_size.count() - 1, size)
        text_layout.addWidget(BodyLabel("Tamaño de texto"))
        text_layout.addWidget(self.font_size)
        self.density = ComboBox()
        self.density.setAccessibleName("Densidad de interfaz")
        self.density.setMaximumWidth(320)
        for label, density in (("Cómoda", "comfortable"), ("Compacta", "compact")):
            self.density.addItem(label)
            self.density.setItemData(self.density.count() - 1, density)
        text_layout.addWidget(BodyLabel("Densidad de interfaz"))
        text_layout.addWidget(self.density)
        text_layout.addStretch()

        self.color_card = GlassCard()
        self.color_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        color_layout = QVBoxLayout(self.color_card)
        color_layout.setContentsMargins(20, 18, 20, 18)
        color_layout.setSpacing(10)
        color_layout.addWidget(SubtitleLabel("Color de acento"))
        description = BodyLabel("El color de los botones principales y la selección.")
        description.setWordWrap(True)
        color_layout.addWidget(description)
        color_layout.addWidget(BodyLabel("Color (#RRGGBB)"))
        color_row = QHBoxLayout()
        color_row.setSpacing(10)
        self.accent_swatch = QLabel()
        self.accent_swatch.setFixedSize(32, 32)
        color_row.addWidget(self.accent_swatch)
        self.accent = LineEdit()
        self.accent.setAccessibleName("Color de acento")
        self.accent.setPlaceholderText("#0078D4")
        self.accent.setMaximumWidth(180)
        self.accent.textChanged.connect(self._update_swatch)
        color_row.addWidget(self.accent, 1)
        color_row.addStretch()
        color_layout.addLayout(color_row)
        self.color_button = PushButton(FluentIcon.PALETTE, "Elegir color")
        self.color_button.clicked.connect(self.choose_accent)
        color_layout.addWidget(self.color_button, alignment=Qt.AlignmentFlag.AlignLeft)
        color_layout.addStretch()
        self.appearance_grid.addWidget(self.text_card, 0, 0)
        self.appearance_grid.addWidget(self.color_card, 0, 1)
        self.appearance_grid.setColumnStretch(0, 1)
        self.appearance_grid.setColumnStretch(1, 1)
        layout.addLayout(self.appearance_grid)

        self.validation_label = BodyLabel("")
        self.validation_label.setWordWrap(True)
        self.validation_label.hide()
        layout.addWidget(self.validation_label)
        self.apply_button = PrimaryPushButton(FluentIcon.PALETTE, "Aplicar apariencia")
        self.apply_button.setAccessibleName("Aplicar apariencia")
        self.apply_button.clicked.connect(self.apply_appearance)
        layout.addWidget(self.apply_button, alignment=Qt.AlignmentFlag.AlignLeft)

        advanced = GlassCard()
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.setContentsMargins(20, 18, 20, 18)
        advanced_layout.setSpacing(10)
        advanced_layout.addWidget(SubtitleLabel("Organización y audio"))
        description = BodyLabel("Configura categorías, exclusiones, protección de carpetas y biblioteca musical.")
        description.setWordWrap(True)
        advanced_layout.addWidget(description)
        advanced_button = PushButton(FluentIcon.SETTING, "Configurar organización y audio")
        advanced_button.clicked.connect(self.advanced_settings_requested.emit)
        advanced_layout.addWidget(advanced_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(advanced)
        layout.addStretch()
        self._settings_columns = 2

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "appearance_grid"):
            return
        columns = 2 if self.viewport().width() - 56 >= 880 else 1
        if columns != self._settings_columns:
            self._settings_columns = columns
            self.appearance_grid.removeWidget(self.color_card)
            self.appearance_grid.addWidget(self.color_card, 0 if columns == 2 else 1, 1 if columns == 2 else 0)
            self.appearance_grid.setColumnStretch(1, 1 if columns == 2 else 0)

    def _update_swatch(self, value: str) -> None:
        if re.fullmatch(r"#[0-9a-fA-F]{6}", value.strip()):
            self.accent_swatch.setStyleSheet(f"background-color: {value.strip()}; border-radius: 8px;")
            self.accent_swatch.setAccessibleName(f"Muestra de color {value.strip()}")
            self.accent_swatch.setToolTip(value.strip().upper())

    def _load_values(self) -> None:
        density = self.config.get_interface_density()
        font_size = self.config.get_font_size()
        self.density.setCurrentIndex(max(0, self.density.findData(density)))
        font_index = self.font_size.findData(font_size)
        self.font_size.setCurrentIndex(font_index if font_index >= 0 else 1)
        self.accent.setText(self.config.get_accent_color())

    def apply_appearance(self) -> None:
        mode = self.config.get_theme_mode()
        density = self.density.currentData()
        font_size = self.font_size.currentData()
        accent = self.accent.text().strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            self.validation_label.setText("Introduce un color válido, por ejemplo #0078D4.")
            self.validation_label.show()
            self.accent.setFocus()
            return
        if not self.config.save_appearance(mode, density, font_size, accent):
            self.validation_label.setText("No se pudo guardar la apariencia. Revisa los permisos y vuelve a intentarlo.")
            self.validation_label.show()
            InfoBar.error("No se guardaron los cambios", "La apariencia anterior sigue activa.",
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return
        self.validation_label.setText("")
        self.validation_label.hide()
        apply_fluent_theme(self.config)
        InfoBar.success(
            "Apariencia actualizada",
            "El acento, texto y densidad se aplicaron correctamente.",
            position=InfoBarPosition.TOP_RIGHT,
            parent=self,
        )
        self.theme_changed.emit()

    def choose_accent(self) -> None:
        color = QColorDialog.getColor(QColor(self.accent.text()), self, "Color de acento")
        if color.isValid():
            self.accent.setText(color.name().upper())
