#!/usr/bin/env python3
"""Builders de UI para la vista musical."""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollBar,
    QSlider,
    QSplitter,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from src.gui.music_duplicates_constants import DUPLICATES_COLUMN_LABELS
from src.gui.v2.theme import apply_control_size


def build_duplicates_tab(view: Any) -> QWidget:
    dup_tab = QWidget()
    dup_layout = QHBoxLayout(dup_tab)
    dup_layout.setContentsMargins(0, 0, 0, 0)
    dup_layout.setSpacing(12)
    view.groups_list = QListWidget()
    view.groups_list.currentItemChanged.connect(view._show_group_detail)
    dup_layout.addWidget(view.groups_list, 1)

    dup_right = QVBoxLayout()
    dup_actions = QGridLayout()
    dup_actions.setHorizontalSpacing(8)
    dup_actions.setVerticalSpacing(8)
    view.play_duplicate_btn = QPushButton("Reproducir")
    view.play_duplicate_btn.clicked.connect(view.play_selected_duplicate)
    dup_actions.addWidget(view.play_duplicate_btn, 0, 0)
    view.stop_duplicate_btn = QPushButton("Detener")
    view.stop_duplicate_btn.clicked.connect(view.stop_duplicate_preview)
    dup_actions.addWidget(view.stop_duplicate_btn, 0, 1)
    view.select_best_duplicate_btn = QPushButton("Elegir mejor")
    view.select_best_duplicate_btn.clicked.connect(view._select_best_duplicate)
    dup_actions.addWidget(view.select_best_duplicate_btn, 0, 2)
    view.keep_duplicate_btn = QPushButton("Conservar")
    view.keep_duplicate_btn.clicked.connect(view._mark_selected_duplicate_as_keep)
    dup_actions.addWidget(view.keep_duplicate_btn, 1, 0)
    view.open_duplicate_folder_btn = QPushButton("Abrir carpeta")
    view.open_duplicate_folder_btn.clicked.connect(view.open_selected_duplicate_folder)
    dup_actions.addWidget(view.open_duplicate_folder_btn, 1, 1)
    view.delete_duplicate_btn = QPushButton("Retirar selección")
    view.delete_duplicate_btn.setEnabled(False)
    view.delete_duplicate_btn.clicked.connect(view.delete_selected_duplicates)
    dup_actions.addWidget(view.delete_duplicate_btn, 1, 2)
    for action_button in (
        view.play_duplicate_btn,
        view.stop_duplicate_btn,
        view.select_best_duplicate_btn,
        view.keep_duplicate_btn,
        view.open_duplicate_folder_btn,
        view.delete_duplicate_btn,
    ):
        apply_control_size(action_button)
        action_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
    dup_right.addLayout(dup_actions)

    view.duplicate_group_info = QLabel(
        "Selecciona un grupo de duplicados para revisar las copias en tabla."
    )
    view.duplicate_group_info.setWordWrap(True)
    dup_right.addWidget(view.duplicate_group_info)

    view.duplicates_table = QTableWidget(0, len(DUPLICATES_COLUMN_LABELS))
    view.duplicates_table.setHorizontalHeaderLabels(DUPLICATES_COLUMN_LABELS)
    view.duplicates_table.setSelectionBehavior(
        view.duplicates_table.SelectionBehavior.SelectRows
    )
    view.duplicates_table.setSelectionMode(
        view.duplicates_table.SelectionMode.ExtendedSelection
    )
    view.duplicates_table.setAlternatingRowColors(True)
    view.duplicates_table.setShowGrid(False)
    view.duplicates_table.setWordWrap(False)
    view.duplicates_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    view.duplicates_table.setSortingEnabled(True)
    duplicate_header = view.duplicates_table.horizontalHeader()
    if duplicate_header is not None:
        duplicate_header.setStretchLastSection(False)
        duplicate_header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        duplicate_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        duplicate_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        duplicate_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        duplicate_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        duplicate_header.setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        duplicate_header.setSectionResizeMode(
            6, QHeaderView.ResizeMode.ResizeToContents
        )
        duplicate_header.setSectionResizeMode(
            7, QHeaderView.ResizeMode.ResizeToContents
        )
        duplicate_header.setSectionResizeMode(
            8, QHeaderView.ResizeMode.ResizeToContents
        )
        duplicate_header.setSectionResizeMode(
            9, QHeaderView.ResizeMode.ResizeToContents
        )
        duplicate_header.setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
    view.duplicates_table.itemSelectionChanged.connect(view._update_duplicate_preview)
    view.duplicates_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    view.duplicates_table.customContextMenuRequested.connect(
        view._show_duplicates_context_menu
    )
    dup_right.addWidget(view.duplicates_table, 1)

    view.best_duplicate_hint = QLabel(
        "La mejor copia sugerida se resaltara al analizar duplicados."
    )
    view.best_duplicate_hint.setWordWrap(True)
    dup_right.addWidget(view.best_duplicate_hint)

    view.detail = QTextEdit()
    view.detail.setReadOnly(True)
    view.detail.setMinimumHeight(120)
    dup_right.addWidget(view.detail)

    dup_layout.addLayout(dup_right, 2)
    return dup_tab


def build_metadata_tab(view: Any) -> QWidget:
    meta_tab = QWidget()
    meta_layout = QVBoxLayout(meta_tab)
    meta_box = QGroupBox("Enriquecimiento de metadatos")
    meta_box_layout = QVBoxLayout(meta_box)
    meta_top = QHBoxLayout()
    view.refresh_missing_btn = QPushButton("Buscar faltantes")
    view.refresh_missing_btn.clicked.connect(view.refresh_missing_metadata)
    meta_top.addWidget(view.refresh_missing_btn)
    view.enrich_btn = QPushButton("Rellenar selección")
    view.enrich_btn.clicked.connect(view.enrich_selected_metadata)
    meta_top.addWidget(view.enrich_btn)
    view.online_lookup_btn = QPushButton("Buscar online")
    view.online_lookup_btn.clicked.connect(view.lookup_selected_online)
    meta_top.addWidget(view.online_lookup_btn)
    view.apply_all_btn = QPushButton("Aplicar lote")
    view.apply_all_btn.clicked.connect(view.apply_batch_metadata)
    meta_top.addWidget(view.apply_all_btn)
    meta_top.addStretch()
    meta_box_layout.addLayout(meta_top)
    view.missing_count_label = QLabel("Pistas con metadatos incompletos: 0")
    view.lookup_status_label = QLabel("Busqueda online: sin ejecutar.")
    view.lookup_status_label.setWordWrap(True)
    view.lookup_progress = QProgressBar()
    view.lookup_progress.setVisible(False)
    view.lookup_progress.setRange(0, 0)
    view.lookup_info_label = QLabel(
        "Selecciona pistas en la tabla para editar o buscar online."
    )
    view.lookup_info_label.setWordWrap(True)
    meta_box_layout.addWidget(view.missing_count_label)
    meta_box_layout.addWidget(view.lookup_status_label)
    meta_box_layout.addWidget(view.lookup_progress)
    meta_box_layout.addWidget(view.lookup_info_label)
    view.metadata_panel = QWidget()
    metadata_layout = QVBoxLayout(view.metadata_panel)
    hint = QLabel("Selecciona pistas en Biblioteca; aquí puedes revisar y editar sus metadatos.")
    hint.setWordWrap(True)
    metadata_layout.addWidget(hint)
    edit_button = QPushButton("Editar pistas seleccionadas")
    edit_button.clicked.connect(view.edit_selected_metadata)
    metadata_layout.addWidget(edit_button)
    metadata_layout.addWidget(meta_box)
    metadata_layout.addStretch()

    library_box = QGroupBox("Biblioteca musical")
    library_layout = QVBoxLayout(library_box)
    library_top = QHBoxLayout()
    library_top.addWidget(QLabel("Estado"))
    view.library_filter_combo = QComboBox()
    view.library_filter_combo.addItem("Todas", "all")
    view.library_filter_combo.addItem("Pendientes", "pending")
    view.library_filter_combo.addItem("Con variantes", "variants")
    view.library_filter_combo.addItem("Variante elegida", "selected_variant")
    view.library_filter_combo.addItem("Aplicadas", "applied")
    view.library_filter_combo.addItem("Con sugerencia fuerte", "strong")
    view.library_filter_combo.addItem("Completas", "complete")
    view.library_filter_combo.addItem("Sin coincidencia", "no_match")
    view.library_filter_combo.currentIndexChanged.connect(
        view._on_library_filter_changed
    )
    library_top.addWidget(view.library_filter_combo)
    view.library_search_input = QLineEdit()
    view.library_search_input.setPlaceholderText(
        "Filtrar por archivo, titulo, artista..."
    )
    view.library_search_input.textChanged.connect(view._on_library_filter_changed)
    library_top.addWidget(view.library_search_input, 1)
    view.library_columns_btn = QPushButton("Columnas")
    view.library_columns_btn.clicked.connect(view._edit_library_columns)
    library_top.addWidget(view.library_columns_btn)
    view.library_reset_view_btn = QPushButton("Restablecer vista")
    view.library_reset_view_btn.clicked.connect(view._reset_table_layout)
    library_top.addWidget(view.library_reset_view_btn)
    view.edit_meta_btn = QPushButton("Editar metadatos")
    view.edit_meta_btn.clicked.connect(lambda: view.tabs.setCurrentWidget(view.metadata_panel))
    library_top.addWidget(view.edit_meta_btn)
    library_top.addStretch()
    library_layout.addLayout(library_top)
    view.library_table = QTableWidget(0, len(view.LIBRARY_COLUMN_LABELS))
    view.library_table.setHorizontalHeaderLabels(view.LIBRARY_COLUMN_LABELS)
    view.library_table.setSortingEnabled(True)
    view.library_table.setSelectionBehavior(
        view.library_table.SelectionBehavior.SelectRows
    )
    view.library_table.setSelectionMode(
        view.library_table.SelectionMode.ExtendedSelection
    )
    view.library_table.setAlternatingRowColors(True)
    view.library_table.setShowGrid(False)
    view.library_table.setWordWrap(False)
    view.library_table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
    view.library_table.setHorizontalScrollBarPolicy(
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    header = view.library_table.horizontalHeader()
    if header is not None:
        header.setSectionsMovable(True)
        header.setStretchLastSection(False)
        header.sectionResized.connect(view._save_column_widths)
        header.sectionMoved.connect(view._save_library_header_state)
        for index, width in enumerate(view.LIBRARY_COLUMN_DEFAULTS):
            view.library_table.setColumnWidth(index, width)
        view._restore_library_table_layout()
    view.library_table.itemChanged.connect(view._on_library_item_changed)
    view.library_table.itemSelectionChanged.connect(
        view._show_selected_candidate_preview
    )
    view.library_table.itemSelectionChanged.connect(view._update_library_detail_panel)
    view.library_table.itemDoubleClicked.connect(view._edit_metadata_from_item)
    view.library_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    view.library_table.customContextMenuRequested.connect(
        view._show_library_context_menu
    )

    view.library_splitter = QSplitter(Qt.Orientation.Horizontal)
    view.library_splitter.setHandleWidth(12)
    view.library_splitter.setChildrenCollapsible(False)
    view.library_splitter.setCollapsible(0, False)
    view.library_splitter.setCollapsible(1, False)
    view.library_splitter.addWidget(view.library_table)
    view.library_table.setMinimumWidth(360)
    view.library_table.setSizePolicy(
        QSizePolicy.Policy.Expanding,
        QSizePolicy.Policy.Expanding,
    )
    library_detail_frame = QFrame()
    library_detail_frame.setMinimumWidth(240)
    library_detail_frame.setSizePolicy(
        QSizePolicy.Policy.Preferred,
        QSizePolicy.Policy.Expanding,
    )
    library_detail_layout = QVBoxLayout(library_detail_frame)
    library_detail_layout.setContentsMargins(8, 8, 8, 8)
    library_detail_layout.setSpacing(8)
    detail_title_row = QHBoxLayout()
    view.library_detail_title = QLabel("Detalle de pista")
    detail_title_row.addWidget(view.library_detail_title, 1)
    view.library_cache_badge = QLabel("")
    view.library_cache_badge.setVisible(False)
    detail_title_row.addWidget(view.library_cache_badge)
    library_detail_layout.addLayout(detail_title_row)
    view.library_cover_label = QLabel("Sin portada")
    view.library_cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    view.library_cover_label.setFixedHeight(180)
    view.library_cover_label.setStyleSheet(
        "border: 1px solid rgba(127,127,127,0.35); padding: 6px;"
    )
    library_detail_layout.addWidget(view.library_cover_label)
    detail_player_row = QHBoxLayout()
    view.library_play_btn = QPushButton("Reproducir")
    view.library_play_btn.setAccessibleName("Reproducir o pausar pista")
    view.library_play_btn.clicked.connect(view.play_selected_library_track)
    detail_player_row.addWidget(view.library_play_btn)
    view.library_stop_btn = QPushButton("Detener")
    view.library_stop_btn.setAccessibleName("Detener reproducción")
    view.library_stop_btn.clicked.connect(view.stop_library_preview)
    detail_player_row.addWidget(view.library_stop_btn)
    view.library_seek_slider = QSlider(Qt.Orientation.Horizontal)
    view.library_seek_slider.setRange(0, 0)
    view.library_seek_slider.setEnabled(False)
    view.library_seek_slider.sliderMoved.connect(view._seek_library_preview)
    seek_row = QHBoxLayout()
    seek_row.addWidget(view.library_seek_slider, 1)
    view.library_time_label = QLabel("0:00 / 0:00")
    view.library_time_label.setMinimumWidth(84)
    seek_row.addWidget(view.library_time_label)
    library_detail_layout.addLayout(detail_player_row)
    library_detail_layout.addLayout(seek_row)
    view.library_player_hint = QLabel("Selecciona una pista para escucharla aqui.")
    view.library_player_hint.setWordWrap(True)
    library_detail_layout.addWidget(view.library_player_hint)
    detail_actions_layout = QVBoxLayout()
    detail_actions_layout.setSpacing(8)
    volume_header_row = QHBoxLayout()
    view.library_volume_title = QLabel("Volumen")
    volume_header_row.addWidget(view.library_volume_title)
    volume_header_row.addStretch()
    view.library_volume_label = QLabel("75%")
    view.library_volume_label.setMinimumWidth(44)
    view.library_volume_label.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    volume_header_row.addWidget(view.library_volume_label)
    detail_actions_layout.addLayout(volume_header_row)
    view.library_volume_slider = QSlider(Qt.Orientation.Horizontal)
    view.library_volume_slider.setRange(0, 100)
    view.library_volume_slider.setValue(int(round(view.audio_output.volume() * 100)))
    view.library_volume_slider.valueChanged.connect(view._on_library_volume_changed)
    view.library_volume_slider.setSingleStep(5)
    view.library_volume_slider.setPageStep(10)
    view.library_volume_slider.setToolTip("Ajusta el volumen de la preescucha")
    detail_actions_layout.addWidget(view.library_volume_slider)
    pitch_header_row = QHBoxLayout()
    view.library_pitch_title = QLabel("Pitch DJ")
    pitch_header_row.addWidget(view.library_pitch_title)
    pitch_header_row.addStretch()
    view.library_pitch_label = QLabel("1.00x")
    view.library_pitch_label.setMinimumWidth(48)
    view.library_pitch_label.setAlignment(
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    )
    pitch_header_row.addWidget(view.library_pitch_label)
    view.library_pitch_slider = QSlider(Qt.Orientation.Horizontal)
    view.library_pitch_slider.setRange(50, 150)
    view.library_pitch_slider.setValue(100)
    view.library_pitch_slider.setSingleStep(5)
    view.library_pitch_slider.setPageStep(10)
    view.library_pitch_slider.setToolTip(
        "Ajusta el pitch DJ: cambia tono y velocidad entre 0.50x y 1.50x"
    )
    view.library_pitch_slider.valueChanged.connect(view._on_library_pitch_changed)
    actions_grid = QGridLayout()
    actions_grid.setHorizontalSpacing(8)
    actions_grid.setVerticalSpacing(8)
    view.library_refresh_cache_btn = QPushButton("Refrescar cache")
    view.library_refresh_cache_btn.clicked.connect(
        view.force_refresh_selected_track_cache
    )
    view.library_refresh_cache_btn.setToolTip(
        "Repite la consulta online para la pista seleccionada"
    )
    actions_grid.addWidget(view.library_refresh_cache_btn, 0, 0)
    view.library_clear_cache_btn = QPushButton("Limpiar cache")
    view.library_clear_cache_btn.clicked.connect(view.clear_selected_track_cache)
    view.library_clear_cache_btn.setToolTip(
        "Borra la cache online guardada para esta pista"
    )
    actions_grid.addWidget(view.library_clear_cache_btn, 0, 1)
    view.library_cover_choice_btn = QPushButton("Elegir portada")
    view.library_cover_choice_btn.clicked.connect(view.choose_selected_track_cover)
    view.library_cover_choice_btn.setToolTip(
        "Selecciona manualmente otra portada disponible"
    )
    actions_grid.addWidget(view.library_cover_choice_btn, 1, 0)
    view.library_diagnostics_btn = QPushButton("Ver diagnostico")
    view.library_diagnostics_btn.clicked.connect(view.show_selected_track_diagnostics)
    view.library_diagnostics_btn.setToolTip(
        "Muestra el diagnostico completo del lookup online"
    )
    actions_grid.addWidget(view.library_diagnostics_btn, 1, 1)
    for button in (
        view.library_refresh_cache_btn,
        view.library_clear_cache_btn,
        view.library_cover_choice_btn,
        view.library_diagnostics_btn,
    ):
        apply_control_size(button)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    actions_grid.setColumnStretch(0, 1)
    actions_grid.setColumnStretch(1, 1)
    advanced = QWidget()
    advanced_toggle = QPushButton("Opciones avanzadas")
    advanced_toggle.setCheckable(True)
    advanced_content = QWidget()
    expert_layout = QVBoxLayout(advanced_content)
    expert_layout.addLayout(pitch_header_row)
    expert_layout.addWidget(view.library_pitch_slider)
    expert_layout.addWidget(view.library_cache_badge)
    expert_layout.addLayout(actions_grid)
    advanced_layout = QVBoxLayout(advanced)
    advanced_layout.addWidget(advanced_toggle)
    advanced_layout.addWidget(advanced_content)
    advanced_content.setVisible(False)
    advanced_toggle.toggled.connect(advanced_content.setVisible)
    detail_actions_layout.addWidget(advanced)
    library_detail_layout.addLayout(detail_actions_layout)
    view.library_detail_text = QTextEdit()
    view.library_detail_text.setReadOnly(True)
    library_detail_layout.addWidget(view.library_detail_text, 1)
    view.library_splitter.addWidget(library_detail_frame)
    view.library_splitter.setStretchFactor(0, 5)
    view.library_splitter.setStretchFactor(1, 2)
    view.library_splitter.splitterMoved.connect(view._save_library_splitter_sizes)
    view._restore_library_splitter_sizes()
    library_layout.addWidget(view.library_splitter, 1)
    view.library_bottom_scroll = QScrollBar(Qt.Orientation.Horizontal)
    view.library_bottom_scroll.valueChanged.connect(
        view._on_library_bottom_scroll_changed
    )
    library_layout.addWidget(view.library_bottom_scroll)
    internal_scroll = view.library_table.horizontalScrollBar()
    if internal_scroll is not None:
        internal_scroll.rangeChanged.connect(view._sync_library_bottom_scroll)
        internal_scroll.valueChanged.connect(view._sync_library_bottom_scroll)
    view._sync_library_bottom_scroll()
    meta_layout.addWidget(library_box, 1)
    return meta_tab
