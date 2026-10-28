"""Configuración visual y accesos a la configuración avanzada."""

from PyQt6.QtCore import Qt, pyqtSignal
import re

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QColorDialog, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    DoubleSpinBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
)

from src.core.duplicate_actions import KEEP_RULES
from src.gui.v2.components import GlassCard, PageHeader
from src.gui.v2.theme import apply_fluent_theme
from src.utils.app_config import AppConfig
from src.utils.constants import DUPLICATE_METHODS

THEME_CHOICES = (("Claro", "light"), ("Oscuro", "dark"), ("Sistema", "system"))


class SettingsPage(ScrollArea):
    """Ajustes de apariencia y puente hacia la configuración existente."""

    theme_changed = pyqtSignal()
    theme_mode_selected = pyqtSignal(str)
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
        self.theme_selector = ComboBox()
        self.theme_selector.setAccessibleName("Tema de la interfaz")
        self.theme_selector.setMaximumWidth(320)
        for label, mode in THEME_CHOICES:
            self.theme_selector.addItem(label)
            self.theme_selector.setItemData(self.theme_selector.count() - 1, mode)
        self.theme_selector.currentIndexChanged.connect(self._on_theme_selected)
        text_layout.addWidget(BodyLabel("Tema"))
        text_layout.addWidget(self.theme_selector)
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
        self._build_tools_settings(layout)
        layout.addStretch()
        self._settings_columns = 2

    @staticmethod
    def _tool_card(title: str, description: str):
        card = GlassCard()
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(10)
        card_layout.addWidget(SubtitleLabel(title))
        text = CaptionLabel(description)
        text.setWordWrap(True)
        card_layout.addWidget(text)
        return card, card_layout

    @staticmethod
    def _switch_row(layout: QVBoxLayout, label: str, accessible: str) -> SwitchButton:
        row = QHBoxLayout()
        text = BodyLabel(label)
        text.setWordWrap(True)
        row.addWidget(text, 1)
        switch = SwitchButton()
        switch.setOnText("Sí")
        switch.setOffText("No")
        switch.setAccessibleName(accessible)
        row.addWidget(switch)
        layout.addLayout(row)
        return switch

    @staticmethod
    def _value_row(layout: QVBoxLayout, label: str, control: QWidget) -> None:
        row = QHBoxLayout()
        text = BodyLabel(label)
        text.setWordWrap(True)
        row.addWidget(text, 1)
        row.addWidget(control)
        layout.addLayout(row)

    def _build_tools_settings(self, layout: QVBoxLayout) -> None:
        """Preferencias de Duplicados, Música, Discos y Uso del espacio."""
        self.tools_grid = QGridLayout()
        self.tools_grid.setSpacing(16)

        self.duplicates_card, dup = self._tool_card(
            "Duplicados", "Valores iniciales de la página Duplicados y reglas para conservar copias.")
        dup.addWidget(BodyLabel("Método predeterminado"))
        self.dup_method = ComboBox()
        self.dup_method.setAccessibleName("Método de duplicados predeterminado")
        for key, label in DUPLICATE_METHODS:
            self.dup_method.addItem(label)
            self.dup_method.setItemData(self.dup_method.count() - 1, key)
        dup.addWidget(self.dup_method)
        dup.addWidget(BodyLabel("Copia que se conserva"))
        self.keep_rule = ComboBox()
        self.keep_rule.setAccessibleName("Regla para conservar copias")
        for key, label in KEEP_RULES.items():
            self.keep_rule.addItem(label)
            self.keep_rule.setItemData(self.keep_rule.count() - 1, key)
        dup.addWidget(self.keep_rule)
        dup.addWidget(BodyLabel("Carpetas preferidas (sus copias se conservan)"))
        self.preferred_folders = ListWidget()
        self.preferred_folders.setAccessibleName("Carpetas preferidas")
        self.preferred_folders.setMaximumHeight(110)
        dup.addWidget(self.preferred_folders)
        folder_row = QHBoxLayout()
        self.add_folder_button = PushButton(FluentIcon.ADD, "Añadir carpeta")
        self.add_folder_button.clicked.connect(self._add_preferred_folder)
        self.remove_folder_button = PushButton(FluentIcon.REMOVE, "Quitar")
        self.remove_folder_button.clicked.connect(self._remove_preferred_folder)
        folder_row.addWidget(self.add_folder_button)
        folder_row.addWidget(self.remove_folder_button)
        folder_row.addStretch()
        dup.addLayout(folder_row)
        self.verify_bytes = self._switch_row(
            dup, "Comparar byte a byte antes de retirar", "Comparar byte a byte antes de retirar")
        self.similar_threshold = SpinBox()
        self.similar_threshold.setAccessibleName("Umbral de imágenes parecidas")
        self.similar_threshold.setRange(0, 30)
        self._value_row(dup, "Umbral de imágenes parecidas (bits)", self.similar_threshold)

        self.music_card, music = self._tool_card(
            "Música", "Cómo se agrupan las pistas duplicadas de la biblioteca.")
        self.duration_tolerance = DoubleSpinBox()
        self.duration_tolerance.setAccessibleName("Tolerancia de duración en segundos")
        self.duration_tolerance.setRange(0.0, 30.0)
        self.duration_tolerance.setSingleStep(0.5)
        self.duration_tolerance.setDecimals(1)
        self._value_row(music, "Tolerancia de duración (segundos)", self.duration_tolerance)
        self.local_chromaprint = self._switch_row(
            music, "Huella acústica local (Chromaprint)", "Usar huella acústica local")

        self.disks_card, disks = self._tool_card(
            "Discos y uso del espacio", "Los ajustes SMART se aplican al reiniciar la aplicación.")
        self.smart_ttl = SpinBox()
        self.smart_ttl.setAccessibleName("Segundos que se reutiliza una lectura SMART")
        self.smart_ttl.setRange(0, 3600)
        self.smart_ttl.setSingleStep(30)
        self._value_row(disks, "Reutilizar lectura SMART (segundos)", self.smart_ttl)
        self.smart_history = self._switch_row(
            disks, "Guardar historial SMART diario", "Guardar historial SMART")
        self.size_on_disk = self._switch_row(
            disks, "Medir también el tamaño real en disco", "Medir tamaño en disco")
        self.dedupe_hardlinks = self._switch_row(
            disks, "Contar una sola vez los hardlinks", "Contar hardlinks una sola vez")

        self._place_tool_cards(2)
        self.tools_grid.setColumnStretch(0, 1)
        layout.addLayout(self.tools_grid)
        self.save_tools_button = PrimaryPushButton(FluentIcon.SAVE, "Guardar preferencias")
        self.save_tools_button.setAccessibleName("Guardar preferencias de herramientas")
        self.save_tools_button.clicked.connect(self.save_tool_settings)
        layout.addWidget(self.save_tools_button, alignment=Qt.AlignmentFlag.AlignLeft)

    def _place_tool_cards(self, columns: int) -> None:
        cards = (self.duplicates_card, self.music_card, self.disks_card)
        for card in cards:
            self.tools_grid.removeWidget(card)
        if columns == 2:
            self.tools_grid.addWidget(self.duplicates_card, 0, 0, 2, 1)
            self.tools_grid.addWidget(self.music_card, 0, 1)
            self.tools_grid.addWidget(self.disks_card, 1, 1)
        else:
            for row, card in enumerate(cards):
                self.tools_grid.addWidget(card, row, 0)
        self.tools_grid.setColumnStretch(1, 1 if columns == 2 else 0)

    def _add_preferred_folder(self) -> None:
        from PyQt6.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Carpeta cuyas copias se conservan")
        if folder and not self.preferred_folders.findItems(folder, Qt.MatchFlag.MatchExactly):
            self.preferred_folders.addItem(folder)

    def _remove_preferred_folder(self) -> None:
        row = self.preferred_folders.currentRow()
        if row >= 0:
            self.preferred_folders.takeItem(row)

    def _load_tool_settings(self) -> None:
        get = self.config.get
        self.dup_method.setCurrentIndex(max(0, self.dup_method.findData(get("duplicates.default_method", "hybrid"))))
        self.keep_rule.setCurrentIndex(max(0, self.keep_rule.findData(get("duplicates.keep_rule", "newest"))))
        self.preferred_folders.clear()
        for folder in get("duplicates.preferred_folders", []) or []:
            self.preferred_folders.addItem(str(folder))
        self.verify_bytes.setChecked(bool(get("duplicates.verify_bytes_before_delete", False)))
        self.similar_threshold.setValue(int(get("duplicates.similar_images_threshold", 10) or 0))
        self.duration_tolerance.setValue(float(get("audio.duplicate_duration_tolerance", 2.0) or 0.0))
        self.local_chromaprint.setChecked(bool(get("audio.local_chromaprint", True)))
        self.smart_ttl.setValue(int(get("disks.smart_cache_ttl", 120) or 0))
        self.smart_history.setChecked(bool(get("disks.smart_history", True)))
        self.size_on_disk.setChecked(bool(get("space_usage.size_on_disk", True)))
        self.dedupe_hardlinks.setChecked(bool(get("space_usage.dedupe_hardlinks", True)))

    def tool_settings(self) -> dict:
        """Valores actuales del formulario, con las claves de AppConfig."""
        return {
            "duplicates.default_method": self.dup_method.currentData(),
            "duplicates.keep_rule": self.keep_rule.currentData(),
            "duplicates.preferred_folders": [
                self.preferred_folders.item(row).text() for row in range(self.preferred_folders.count())
            ],
            "duplicates.verify_bytes_before_delete": self.verify_bytes.isChecked(),
            "duplicates.similar_images_threshold": self.similar_threshold.value(),
            "audio.duplicate_duration_tolerance": round(self.duration_tolerance.value(), 1),
            "audio.local_chromaprint": self.local_chromaprint.isChecked(),
            "disks.smart_cache_ttl": self.smart_ttl.value(),
            "disks.smart_history": self.smart_history.isChecked(),
            "space_usage.size_on_disk": self.size_on_disk.isChecked(),
            "space_usage.dedupe_hardlinks": self.dedupe_hardlinks.isChecked(),
        }

    def save_tool_settings(self) -> bool:
        failed = [key for key, value in self.tool_settings().items()
                  if self.config.get(key) != value and not self.config.set(key, value)]
        if failed:
            InfoBar.error("No se guardaron las preferencias",
                          "Revisa los permisos de la carpeta de configuración y vuelve a intentarlo.",
                          position=InfoBarPosition.TOP_RIGHT, parent=self)
            return False
        InfoBar.success("Preferencias guardadas", "Se aplicarán en el próximo análisis.",
                        position=InfoBarPosition.TOP_RIGHT, parent=self)
        return True

    def _on_theme_selected(self, _index: int) -> None:
        mode = self.theme_selector.currentData()
        if mode and mode != self.config.get_theme_mode():
            self.theme_mode_selected.emit(mode)

    def sync_theme_selector(self) -> None:
        """Refleja el modo guardado sin volver a emitir la señal."""
        self.theme_selector.blockSignals(True)
        self.theme_selector.setCurrentIndex(max(0, self.theme_selector.findData(self.config.get_theme_mode())))
        self.theme_selector.blockSignals(False)

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
            self._place_tool_cards(columns)

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
        self.sync_theme_selector()
        self._load_tool_settings()

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
