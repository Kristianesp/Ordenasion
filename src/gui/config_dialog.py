#!/usr/bin/env python3
"""
Diálogo de Configuración para el Organizador de Archivos
Maneja la gestión de categorías y extensiones
"""

import os
from typing import Dict, List, Optional
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QSplitter,
    QGroupBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QWidget,
    QTabWidget,
    QPlainTextEdit,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    TitleLabel,
)

from src.core.category_manager import CategoryManager
from src.gui.rule_panel import RulePanel
from src.gui.v2.components import TextPromptDialog, alert, ask
from src.gui.v2.theme import apply_control_sizes


class ConfigDialog(QDialog):
    """Ventana de configuración para gestionar categorías y extensiones"""

    # Señales para notificar cambios
    categories_updated = pyqtSignal()
    interface_changes_requested = pyqtSignal(int, str)  # font_size, theme

    def __init__(
        self,
        parent=None,
        category_manager: CategoryManager = None,
        app_config_ref=None,
        focus_section: str | None = None,
    ):
        super().__init__(parent)
        self.category_manager = category_manager or CategoryManager()
        self.app_config = app_config_ref or self._build_app_config()
        self.focus_section = focus_section
        self.init_ui()
        apply_control_sizes(self, self.app_config)
        self.refresh_categories_list()
        self.load_exclusions()
        self.update_stats()
        # Aplicar tema inicial
        self.apply_current_theme_to_self()
        if self.focus_section == "exclusions":
            QTimer.singleShot(0, self.focus_exclusions_section)

    def _build_app_config(self):
        from src.utils.app_config import get_app_config

        return get_app_config()

    def _tokens(self):
        """Tokens V2 del modo vigente (claro, oscuro o sistema)."""
        from src.gui.v2.theme import current_tokens

        return current_tokens(self.app_config.get_accent_color(), self.app_config.get_theme_mode())

    def init_ui(self):
        """Inicializa la interfaz del diálogo"""
        self.setWindowTitle("Configuración de categorías")
        self.setGeometry(280, 160, 980, 700)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self.title_label = TitleLabel("Configuración avanzada")
        self.title_label.setToolTip(
            "Panel principal para configurar categorías, extensiones y personalizar la interfaz"
        )
        self.title_label.setObjectName("config_title_label")
        layout.addWidget(self.title_label)

        self.stats_label = CaptionLabel()
        self.stats_label.setToolTip(
            "Resumen de categorías y extensiones configuradas en el sistema"
        )
        self.stats_label.setObjectName("config_stats_label")
        layout.addWidget(self.stats_label)

        sections = QTabWidget()
        sections.setObjectName("config_sections_tabs")

        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.setSpacing(10)

        catalog_tab = QWidget()
        catalog_layout = QVBoxLayout(catalog_tab)
        catalog_layout.setContentsMargins(0, 0, 0, 0)
        catalog_layout.setSpacing(10)

        exclusions_tab = QWidget()
        exclusions_layout_box = QVBoxLayout(exclusions_tab)
        exclusions_layout_box.setContentsMargins(0, 0, 0, 0)
        exclusions_layout_box.setSpacing(10)

        interface_group = QGroupBox("Interfaz")
        interface_group.setToolTip(
            "Personaliza el tamaño de fuente de la aplicación"
        )
        interface_layout = QGridLayout(interface_group)

        font_size_label = BodyLabel("Tamaño de fuente:")
        interface_layout.addWidget(font_size_label, 0, 0)
        self.font_size_combo = ComboBox()
        self.font_size_combo.addItems(
            [
                "Pequeño (11px)",
                "Normal (13px) - Por defecto",
                "Grande (15px)",
            ]
        )
        self.font_size_combo.setCurrentIndex(
            0 if self.app_config.get_font_size() <= 11 else 2 if self.app_config.get_font_size() >= 15 else 1
        )
        self.font_size_combo.currentTextChanged.connect(self.on_font_size_changed)
        interface_layout.addWidget(self.font_size_combo, 0, 1)

        self.apply_interface_btn = PushButton("Aplicar cambios")
        self.apply_interface_btn.clicked.connect(self.apply_interface_changes)
        interface_layout.addWidget(self.apply_interface_btn, 1, 0, 1, 2)
        general_layout.addWidget(interface_group)

        audio_group = QGroupBox("Biblioteca musical")
        audio_group.setToolTip(
            "Configura el comportamiento musical y las claves opcionales de metadatos online"
        )
        audio_layout = QGridLayout(audio_group)

        self.audio_enabled_checkbox = CheckBox("Habilitar funciones de música")
        self.audio_enabled_checkbox.setChecked(
            self.app_config.get("audio.enabled", True)
        )
        audio_layout.addWidget(self.audio_enabled_checkbox, 0, 0, 1, 2)

        audio_layout.addWidget(BodyLabel("Rutas biblioteca:"), 1, 0)
        self.audio_roots_input = QPlainTextEdit()
        self.audio_roots_input.setPlaceholderText("Una ruta por línea")
        self.audio_roots_input.setFixedHeight(88)
        self.audio_roots_input.setPlainText(
            "\n".join(self.app_config.get_audio_library_roots())
        )
        audio_layout.addWidget(self.audio_roots_input, 1, 1)

        audio_layout.addWidget(BodyLabel("Plantilla de organización:"), 2, 0)
        self.audio_template_input = LineEdit()
        self.audio_template_input.setText(
            self.app_config.get_audio_organization_template()
        )
        audio_layout.addWidget(self.audio_template_input, 2, 1)

        audio_layout.addWidget(BodyLabel("Política de duplicados:"), 3, 0)
        self.audio_policy_combo = ComboBox()
        self.audio_policy_combo.addItems(["review", "quarantine", "prefer_lossless"])
        self.audio_policy_combo.setCurrentText(
            self.app_config.get_audio_duplicate_policy()
        )
        audio_layout.addWidget(self.audio_policy_combo, 3, 1)

        self.audio_online_checkbox = CheckBox("Permitir metadatos online")
        self.audio_online_checkbox.setChecked(
            self.app_config.get_audio_online_metadata_enabled()
        )
        audio_layout.addWidget(self.audio_online_checkbox, 4, 0, 1, 2)

        acoustid_label = BodyLabel("AcoustID client key:")
        acoustid_label.setToolTip(
            "Clave client de una aplicacion registrada en AcoustID. La clave personal del perfil no sirve para lookup."
        )
        audio_layout.addWidget(acoustid_label, 5, 0)
        self.acoustid_key_input = LineEdit()
        self.acoustid_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.acoustid_key_input.setPlaceholderText("Client key de AcoustID para lookup")
        self.acoustid_key_input.setToolTip(
            "No uses la clave de tu página de perfil. La búsqueda usa el parámetro client= de una aplicación registrada."
        )
        self.acoustid_key_input.setText(self.app_config.get_acoustid_api_key())
        self.acoustid_key_input.textChanged.connect(self._persist_audio_settings_live)
        audio_layout.addWidget(self.acoustid_key_input, 5, 1)

        self.discogs_enabled_checkbox = CheckBox("Usar Discogs como fuente secundaria")
        self.discogs_enabled_checkbox.setChecked(self.app_config.get_discogs_enabled())
        self.discogs_enabled_checkbox.toggled.connect(self._persist_audio_settings_live)
        audio_layout.addWidget(self.discogs_enabled_checkbox, 6, 0, 1, 2)

        audio_layout.addWidget(BodyLabel("Discogs token personal:"), 7, 0)
        self.discogs_token_input = LineEdit()
        self.discogs_token_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.discogs_token_input.setText(self.app_config.get_discogs_token())
        self.discogs_token_input.textChanged.connect(self._persist_audio_settings_live)
        audio_layout.addWidget(self.discogs_token_input, 7, 1)

        general_layout.addWidget(audio_group)

        catalog_splitter = QSplitter(Qt.Orientation.Horizontal)

        categories_group = QGroupBox("Categorías")
        categories_group.setToolTip(
            "Gestiona las categorías del sistema y crea nuevas personalizadas"
        )
        categories_layout = QVBoxLayout(categories_group)
        self.categories_list = ListWidget()
        self.categories_list.itemClicked.connect(self.on_category_selected)
        self.categories_list.setMinimumHeight(160)
        categories_layout.addWidget(self.categories_list)

        cat_buttons_layout = QHBoxLayout()
        self.add_cat_btn = PushButton(FluentIcon.ADD, "Añadir")
        self.add_cat_btn.clicked.connect(self.add_category)
        self.add_cat_btn.setProperty("styleClass", "success")
        cat_buttons_layout.addWidget(self.add_cat_btn)

        self.remove_cat_btn = PushButton(FluentIcon.DELETE, "Eliminar")
        self.remove_cat_btn.clicked.connect(self.remove_category)
        self.remove_cat_btn.setProperty("styleClass", "danger")
        cat_buttons_layout.addWidget(self.remove_cat_btn)

        self.rules_btn = PushButton(FluentIcon.FILTER, "Reglas")
        self.rules_btn.clicked.connect(self.open_rules_panel)
        cat_buttons_layout.addWidget(self.rules_btn)
        categories_layout.addLayout(cat_buttons_layout)

        extensions_group = QGroupBox("Extensiones de la categoría")
        extensions_group.setToolTip(
            "Gestiona las extensiones de archivo de la categoría seleccionada"
        )
        extensions_layout = QVBoxLayout(extensions_group)
        self.extensions_list = ListWidget()
        self.extensions_list.setMinimumHeight(160)
        extensions_layout.addWidget(self.extensions_list)

        ext_buttons_layout = QHBoxLayout()
        self.add_ext_btn = PushButton(FluentIcon.ADD, "Añadir")
        self.add_ext_btn.clicked.connect(self.add_extension)
        ext_buttons_layout.addWidget(self.add_ext_btn)

        self.remove_ext_btn = PushButton(FluentIcon.DELETE, "Eliminar")
        self.remove_ext_btn.clicked.connect(self.remove_extension)
        ext_buttons_layout.addWidget(self.remove_ext_btn)
        extensions_layout.addLayout(ext_buttons_layout)

        catalog_splitter.addWidget(categories_group)
        catalog_splitter.addWidget(extensions_group)
        catalog_splitter.setStretchFactor(0, 1)
        catalog_splitter.setStretchFactor(1, 2)
        catalog_layout.addWidget(catalog_splitter)

        cat_actions_layout = QHBoxLayout()
        self.export_btn = PushButton(FluentIcon.SHARE, "Exportar")
        self.export_btn.clicked.connect(self.export_to_txt)
        cat_actions_layout.addWidget(self.export_btn)

        self.reset_btn = PushButton(FluentIcon.SYNC, "Restaurar")
        self.reset_btn.clicked.connect(self.reset_to_default)
        cat_actions_layout.addWidget(self.reset_btn)
        catalog_layout.addLayout(cat_actions_layout)

        exclusions_group = QGroupBox("Exclusiones")
        exclusions_group.setToolTip(
            "Gestiona extensiones ignoradas, rutas protegidas y carpetas excluidas"
        )
        exclusions_grid = QGridLayout(exclusions_group)

        exclusions_grid.addWidget(BodyLabel("Extensiones ignoradas"), 0, 0)
        self.ignored_extension_input = LineEdit()
        self.ignored_extension_input.setPlaceholderText(".tmp")
        exclusions_grid.addWidget(self.ignored_extension_input, 0, 1)
        self.add_ignored_extension_btn = PushButton("Añadir")
        self.add_ignored_extension_btn.clicked.connect(self.add_ignored_extension)
        self.add_ignored_extension_btn.setText("Añadir")
        self.add_ignored_extension_btn.setIcon(FluentIcon.ADD)
        self.add_ignored_extension_btn.setToolTip("Añadir extensión ignorada")
        self.add_ignored_extension_btn.setProperty("styleClass", "icon")
        exclusions_grid.addWidget(self.add_ignored_extension_btn, 0, 2)
        self.ignored_extensions_list = ListWidget()
        self.ignored_extensions_list.setMinimumHeight(64)
        exclusions_grid.addWidget(self.ignored_extensions_list, 1, 0, 1, 2)
        self.remove_ignored_extension_btn = PushButton("Eliminar")
        self.remove_ignored_extension_btn.clicked.connect(
            self.remove_selected_ignored_extension
        )
        self.remove_ignored_extension_btn.setText("Quitar")
        self.remove_ignored_extension_btn.setIcon(FluentIcon.REMOVE)
        self.remove_ignored_extension_btn.setToolTip(
            "Eliminar extensión ignorada seleccionada"
        )
        self.remove_ignored_extension_btn.setProperty("styleClass", "icon")
        exclusions_grid.addWidget(self.remove_ignored_extension_btn, 1, 2)

        exclusions_grid.addWidget(BodyLabel("Rutas protegidas"), 2, 0)
        self.protected_path_input = LineEdit()
        self.protected_path_input.setPlaceholderText("/home/usuario/Documentos")
        self.protected_path_input.returnPressed.connect(self.add_protected_path)
        exclusions_grid.addWidget(self.protected_path_input, 2, 1)
        self.browse_protected_path_btn = PushButton(FluentIcon.FOLDER, "Examinar")
        self.browse_protected_path_btn.clicked.connect(self.browse_protected_path)
        self.browse_protected_path_btn.setProperty("styleClass", "ghost")
        exclusions_grid.addWidget(self.browse_protected_path_btn, 2, 2)
        self.protected_paths_list = ListWidget()
        self.protected_paths_list.setMinimumHeight(64)
        exclusions_grid.addWidget(self.protected_paths_list, 3, 0, 1, 2)
        self.remove_protected_path_btn = PushButton("Eliminar")
        self.remove_protected_path_btn.clicked.connect(
            self.remove_selected_protected_path
        )
        self.remove_protected_path_btn.setText("Quitar")
        self.remove_protected_path_btn.setIcon(FluentIcon.REMOVE)
        self.remove_protected_path_btn.setToolTip(
            "Eliminar ruta protegida seleccionada"
        )
        self.remove_protected_path_btn.setProperty("styleClass", "icon")
        exclusions_grid.addWidget(self.remove_protected_path_btn, 3, 2)

        exclusions_grid.addWidget(BodyLabel("Carpetas ignoradas"), 4, 0)
        self.ignored_path_input = LineEdit()
        self.ignored_path_input.setPlaceholderText("/home/usuario/Descargas/tmp")
        self.ignored_path_input.returnPressed.connect(self.add_ignored_path)
        exclusions_grid.addWidget(self.ignored_path_input, 4, 1)
        self.browse_ignored_path_btn = PushButton(FluentIcon.FOLDER, "Examinar")
        self.browse_ignored_path_btn.clicked.connect(self.browse_ignored_path)
        self.browse_ignored_path_btn.setProperty("styleClass", "ghost")
        exclusions_grid.addWidget(self.browse_ignored_path_btn, 4, 2)
        self.ignored_paths_list = ListWidget()
        self.ignored_paths_list.setMinimumHeight(64)
        exclusions_grid.addWidget(self.ignored_paths_list, 5, 0, 1, 2)
        self.remove_ignored_path_btn = PushButton("Eliminar")
        self.remove_ignored_path_btn.clicked.connect(self.remove_selected_ignored_path)
        self.remove_ignored_path_btn.setText("Quitar")
        self.remove_ignored_path_btn.setIcon(FluentIcon.REMOVE)
        self.remove_ignored_path_btn.setToolTip(
            "Eliminar carpeta ignorada seleccionada"
        )
        self.remove_ignored_path_btn.setProperty("styleClass", "icon")
        exclusions_grid.addWidget(self.remove_ignored_path_btn, 5, 2)
        exclusions_layout_box.addWidget(exclusions_group)

        sections.addTab(general_tab, "General")
        sections.addTab(catalog_tab, "Catálogo")
        sections.addTab(exclusions_tab, "Exclusiones")
        layout.addWidget(sections)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        button_row.addStretch()
        self.cancel_btn = PushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_btn)
        self.save_btn = PrimaryPushButton(FluentIcon.SAVE, "Guardar y cerrar")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.accept)
        button_row.addWidget(self.save_btn)
        layout.addLayout(button_row)

        self.remove_cat_btn.setEnabled(False)
        self.add_ext_btn.setEnabled(False)
        self.remove_ext_btn.setEnabled(False)

    def refresh_categories_list(self):
        """Actualiza la lista de categorías"""
        self.categories_list.clear()

        tokens = self._tokens()
        categories = self.category_manager.get_categories()

        for category_name in sorted(categories.keys()):
            item = QListWidgetItem(category_name)
            # Las categorías del sistema se distinguen con el color de acento
            if self.category_manager.is_system_category(category_name):
                item.setForeground(QColor(tokens.accent_text))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setToolTip("Categoría del sistema (no se puede eliminar)")
            else:
                item.setForeground(QColor(tokens.text_primary))
                item.setToolTip("Categoría personalizada (se puede eliminar)")

            self.categories_list.addItem(item)

    def on_category_selected(self, item):
        """Maneja la selección de una categoría"""
        if not item:
            return

        category_name = item.text()
        self.refresh_extensions_list(category_name)

        # Habilitar/deshabilitar botones según el tipo de categoría
        is_system = self.category_manager.is_system_category(category_name)
        self.remove_cat_btn.setEnabled(not is_system)
        self.add_ext_btn.setEnabled(True)
        self.remove_ext_btn.setEnabled(True)

    def refresh_extensions_list(self, category_name: str):
        """Actualiza la lista de extensiones de una categoría"""
        self.extensions_list.clear()

        tokens = self._tokens()
        extensions = self.category_manager.get_extensions_for_category(category_name)

        for extension in sorted(extensions):
            item = QListWidgetItem(extension)
            item.setForeground(QColor(tokens.text_primary))
            self.extensions_list.addItem(item)

    def add_category(self):
        """Añade una nueva categoría"""
        name, ok = self._ask_text("Nueva categoría", "Nombre de la nueva categoría:"
        )

        if ok and name.strip():
            name = name.strip().upper()

            if name in self.category_manager.get_categories():
                self._warn("Advertencia", f"La categoría '{name}' ya existe."
                )
                return

            # Añadir categoría vacía
            if self.category_manager.add_category(name, []):
                self.refresh_categories_list()
                self.update_stats()
                self._info("Éxito", f"Categoría '{name}' creada exitosamente."
                )
            else:
                self._error("Error", "No se pudo crear la categoría.")

    def remove_category(self):
        """Elimina la categoría seleccionada"""
        current_item = self.categories_list.currentItem()
        if not current_item:
            return

        category_name = current_item.text()

        if self.category_manager.is_system_category(category_name):
            self._warn("Advertencia", "No se pueden eliminar categorías del sistema."
            )
            return

        reply = self._confirm("Confirmar Eliminación",
            f"¿Estás seguro de que quieres eliminar la categoría '{category_name}'?\n\n"
            "Esta acción no se puede deshacer."
        )

        if reply:
            if self.category_manager.remove_category(category_name):
                self.refresh_categories_list()
                self.extensions_list.clear()
                self.update_stats()
                self._info("Éxito",
                    f"Categoría '{category_name}' eliminada exitosamente.",
                )
            else:
                self._error("Error", "No se pudo eliminar la categoría.")

    def add_extension(self):
        """Añade una extensión a la categoría seleccionada"""
        current_item = self.categories_list.currentItem()
        if not current_item:
            return

        category_name = current_item.text()
        extension, ok = self._ask_text("Nueva extensión",
            f"Extensión para la categoría '{category_name}':\n\n"
            "Formato: .ext (ejemplo: .pdf)",
        )

        if ok and extension.strip():
            extension = extension.strip()

            # Validar formato
            if not self.category_manager.validate_extension(extension):
                self._warn("Formato Inválido",
                    "La extensión debe comenzar con '.' y tener al menos 2 caracteres.\n\n"
                    "Ejemplo: .pdf, .mp3, .jpg",
                )
                return

            # Verificar si ya existe
            if extension in self.category_manager.get_extensions_for_category(
                category_name
            ):
                self._warn("Advertencia",
                    f"La extensión '{extension}' ya existe en esta categoría.",
                )
                return

            # Añadir extensión
            if self.category_manager.add_extension_to_category(
                category_name, extension
            ):
                self.refresh_extensions_list(category_name)
                self.update_stats()
                self._info("Éxito", f"Extensión '{extension}' añadida exitosamente."
                )
            else:
                self._error("Error", "No se pudo añadir la extensión.")

    def remove_extension(self):
        """Elimina la extensión seleccionada"""
        current_cat_item = self.categories_list.currentItem()
        current_ext_item = self.extensions_list.currentItem()

        if not current_cat_item or not current_ext_item:
            return

        category_name = current_cat_item.text()
        extension = current_ext_item.text()

        reply = self._confirm("Confirmar Eliminación",
            f"¿Estás seguro de que quieres eliminar la extensión '{extension}' "
            f"de la categoría '{category_name}'?"
        )

        if reply:
            if self.category_manager.remove_extension_from_category(
                category_name, extension
            ):
                self.refresh_extensions_list(category_name)
                self.update_stats()
                self._info("Éxito", f"Extensión '{extension}' eliminada exitosamente."
                )
            else:
                self._error("Error", "No se pudo eliminar la extensión.")

    def export_to_txt(self):
        """Exporta las categorías a un archivo de texto"""
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar categorías",
            "categorias_organizador.txt",
            "Archivos de texto (*.txt)",
        )

        if filepath:
            if self.category_manager.export_to_txt(filepath):
                self._info("Éxito", f"Categorías exportadas exitosamente a:\n{filepath}"
                )
            else:
                self._error("Error", "No se pudo exportar las categorías."
                )

    def reset_to_default(self):
        """Restaura las categorías por defecto"""
        reply = self._confirm("Confirmar Restauración",
            "¿Estás seguro de que quieres restaurar las categorías por defecto?\n\n"
            "Esta acción eliminará todas las categorías personalizadas y no se puede deshacer."
        )

        if reply:
            self.category_manager.reset_to_default()
            self.refresh_categories_list()
            self.extensions_list.clear()
            self.update_stats()
            self._info("Éxito", "Categorías restauradas por defecto exitosamente."
            )

    def update_stats(self):
        """Actualiza las estadísticas mostradas"""
        stats = self.category_manager.get_stats()
        total_categories = len(stats)
        total_extensions = sum(stats.values())

        stats_text = (
            f"{total_categories} categorías · {total_extensions} extensiones"
        )
        self.stats_label.setText(stats_text)

    def accept(self):
        """Maneja la aceptación del diálogo"""
        self.save_exclusions()
        self.app_config.set_audio_settings(
            {
                **self.app_config.get_audio_settings(),
                "enabled": self.audio_enabled_checkbox.isChecked(),
                "library_roots": [
                    line.strip()
                    for line in self.audio_roots_input.toPlainText().splitlines()
                    if line.strip()
                ],
                "organization_template": self.audio_template_input.text().strip(),
                "duplicate_policy": self.audio_policy_combo.currentText().strip(),
                "allow_online_metadata": self.audio_online_checkbox.isChecked(),
                "acoustid_api_key": self.acoustid_key_input.text().strip(),
                "discogs_enabled": self.discogs_enabled_checkbox.isChecked(),
                "discogs_token": self.discogs_token_input.text().strip(),
            }
        )
        categories_saved = self.category_manager.save_configuration()
        if not categories_saved:
            self._warn("Configuración",
                "No se pudieron guardar algunos cambios de categorías, pero la configuración de audio sí se ha guardado.",
            )
        self.categories_updated.emit()
        super().accept()

    def _persist_audio_settings_live(self, *args):
        """Guarda en vivo los ajustes de audio sin cerrar el dialogo."""
        try:
            self.app_config.set_audio_settings(
                {
                    **self.app_config.get_audio_settings(),
                    "enabled": self.audio_enabled_checkbox.isChecked(),
                    "library_roots": [
                        line.strip()
                        for line in self.audio_roots_input.toPlainText().splitlines()
                        if line.strip()
                    ],
                    "organization_template": self.audio_template_input.text().strip(),
                    "duplicate_policy": self.audio_policy_combo.currentText().strip(),
                    "allow_online_metadata": self.audio_online_checkbox.isChecked(),
                    "acoustid_api_key": self.acoustid_key_input.text().strip(),
                    "discogs_enabled": self.discogs_enabled_checkbox.isChecked(),
                    "discogs_token": self.discogs_token_input.text().strip(),
                }
            )
        except Exception:
            pass

    def get_updated_categories(self) -> Dict[str, List[str]]:
        """Retorna las categorías actualizadas"""
        return self.category_manager.get_categories()

    def open_rules_panel(self):
        """Abre el panel visual de reglas personalizadas"""
        dialog = RulePanel(self, self.category_manager)
        dialog.exec()

    def update_global_index(self):
        """Actualiza el índice inverso global"""
        # Este método se puede usar para sincronizar con otros componentes
        pass

    def on_font_size_changed(self, value):
        """Maneja el cambio en el tamaño de fuente"""
        # El cambio se aplicará cuando se presione "Aplicar cambios"
        pass

    def apply_interface_changes(self):
        """Aplica los cambios de interfaz INMEDIATAMENTE"""
        try:
            # Obtener valores actuales
            font_size = self.get_font_size_from_combo()
            theme_text = self.app_config.get_theme()

            # Guardar configuración PRIMERO
            if not self.app_config.set_font_size(font_size):
                self._warn("No se guardaron los cambios", "No se pudo guardar el tamaño de texto. La apariencia anterior sigue activa.")
                return

            # Emitir señal para aplicar cambios INMEDIATAMENTE
            refresh_fluent = self._fluent_refresh_hook()
            if callable(refresh_fluent):
                refresh_fluent()
            else:
                self.interface_changes_requested.emit(font_size, theme_text)

            # Aplicar el tema a este mismo diálogo inmediatamente (después de guardar)
            # Usar QTimer para asegurar que se aplica después de que se procesen los eventos
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(50, self.apply_current_theme_to_self)

            self._info(
                "Cambios aplicados",
                f"Tamaño: {self.get_font_size_description(font_size)}. "
                "Los cambios se han aplicado a toda la aplicación.",
            )

        except Exception as e:
            self._error("Error", f"Error al aplicar cambios de interfaz:\n{str(e)}"
            )

    # ------------------------------------------------- avisos Fluent
    def _info(self, title: str, content: str) -> None:
        InfoBar.success(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self, duration=3500)

    def _warn(self, title: str, content: str) -> None:
        InfoBar.warning(title, content, position=InfoBarPosition.TOP_RIGHT, parent=self, duration=6000)

    def _error(self, title: str, content: str) -> None:
        alert(self, title, content)

    def _confirm(self, title: str, content: str) -> bool:
        return ask(self, title, content)

    def _ask_text(self, title: str, label: str, text: str = "") -> tuple[str, bool]:
        return TextPromptDialog.get_text(self, title, label, text)

    def _fluent_refresh_hook(self):
        """``refresh_fluent_appearance`` de la ventana Fluent que abrió el diálogo."""
        widget = self.parentWidget()
        while widget is not None:
            hook = getattr(widget, "refresh_fluent_appearance", None)
            if callable(hook):
                return hook
            widget = widget.parentWidget()
        return None

    def get_font_size_from_combo(self) -> int:
        """Obtiene el tamaño de fuente en píxeles desde el combo"""
        current_text = self.font_size_combo.currentText()
        if "Pequeño" in current_text:
            return 11
        if "Normal" in current_text:
            return 13
        if "Grande" in current_text:
            return 15
        return 13  # Por defecto

    def get_font_size_description(self, size: int) -> str:
        """Convierte el tamaño de fuente a descripción legible"""
        if size <= 11:
            return "Pequeño"
        if size <= 13:
            return "Normal (Por defecto)"
        return "Grande"

    def apply_current_theme_to_self(self):
        """Aplica los tokens V2 del modo vigente al diálogo y a sus listas."""
        from src.gui.v2.theme import apply_dialog_surface

        apply_dialog_surface(self)
        current_category = None
        if hasattr(self, "categories_list") and self.categories_list.currentItem():
            current_category = self.categories_list.currentItem().text()
        self.refresh_categories_list()
        if current_category:
            for index in range(self.categories_list.count()):
                item = self.categories_list.item(index)
                if item and item.text() == current_category:
                    self.categories_list.setCurrentItem(item)
                    self.refresh_extensions_list(current_category)
                    break

    def focus_exclusions_section(self):
        """Lleva el foco inicial a la gestión de exclusiones."""
        self.ignored_extension_input.setFocus()

    def _list_values(self, widget: QListWidget) -> List[str]:
        return [widget.item(i).text() for i in range(widget.count())]

    def _set_list_values(self, widget: QListWidget, values: List[str]):
        widget.clear()
        for value in values:
            widget.addItem(value)

    def load_exclusions(self):
        """Carga exclusiones persistidas en la UI."""
        self._set_list_values(
            self.ignored_extensions_list, self.app_config.get_ignored_extensions()
        )
        self._set_list_values(
            self.protected_paths_list, self.app_config.get_protected_paths()
        )
        self._set_list_values(
            self.ignored_paths_list, self.app_config.get_ignored_paths()
        )

    def save_exclusions(self):
        """Guarda exclusiones persistentes."""
        self.app_config.set_ignored_extensions(
            self._list_values(self.ignored_extensions_list)
        )
        self.app_config.set_protected_paths(
            self._list_values(self.protected_paths_list)
        )
        self.app_config.set_ignored_paths(self._list_values(self.ignored_paths_list))

    def add_ignored_extension(self):
        value = self.ignored_extension_input.text().strip()
        if not value:
            return
        values = self._list_values(self.ignored_extensions_list)
        if value not in values:
            values.append(value)
            self._set_list_values(self.ignored_extensions_list, sorted(values))
        self.ignored_extension_input.clear()

    def remove_selected_ignored_extension(self):
        row = self.ignored_extensions_list.currentRow()
        if row >= 0:
            self.ignored_extensions_list.takeItem(row)

    def _append_unique_path(self, widget: QListWidget, value: str):
        value = value.strip()
        if not value:
            return
        values = self._list_values(widget)
        if value not in values:
            values.append(value)
            self._set_list_values(widget, values)

    def browse_protected_path(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar ruta protegida")
        if path:
            self._append_unique_path(self.protected_paths_list, path)
        self.protected_path_input.clear()

    def add_protected_path(self):
        self._append_unique_path(
            self.protected_paths_list, self.protected_path_input.text().strip()
        )
        self.protected_path_input.clear()

    def remove_selected_protected_path(self):
        row = self.protected_paths_list.currentRow()
        if row >= 0:
            self.protected_paths_list.takeItem(row)

    def browse_ignored_path(self):
        path = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta ignorada")
        if path:
            self._append_unique_path(self.ignored_paths_list, path)
        self.ignored_path_input.clear()

    def add_ignored_path(self):
        self._append_unique_path(
            self.ignored_paths_list, self.ignored_path_input.text().strip()
        )
        self.ignored_path_input.clear()

    def remove_selected_ignored_path(self):
        row = self.ignored_paths_list.currentRow()
        if row >= 0:
            self.ignored_paths_list.takeItem(row)
