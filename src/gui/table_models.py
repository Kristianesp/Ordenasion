#!/usr/bin/env python3
"""
Modelos virtualizados para tablas usando QAbstractTableModel
Optimizado para manejar grandes cantidades de datos sin congelar la UI
"""

from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex, QVariant
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication
from typing import List, Dict, Any, Optional
from datetime import datetime


class VirtualizedMovementsModel(QAbstractTableModel):
    """
    Modelo virtualizado para la tabla de movimientos en main_window.py
    Solo renderiza las filas visibles, manejando eficientemente 10,000+ elementos
    """
    
    def __init__(self, data: List[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self._data = data if data else []
        self._headers = ["", "Elemento", "Destino", "%", "Archivos", "Tamaño"]
        self._checked_ids = set()  # Mantener estado de checkboxes con IDs estables
        # Mapeo de extensiones a iconos
        self._icon_cache: Dict[str, QIcon] = {}
        self._ext_icons = {
            '.mp3': '🎵', '.wav': '🎵', '.flac': '🎵', '.aac': '🎵', '.ogg': '🎵', '.wma': '🎵',
            '.mp4': '🎬', '.avi': '🎬', '.mkv': '🎬', '.mov': '🎬', '.wmv': '🎬', '.flv': '🎬', '.webm': '🎬',
            '.jpg': '🖼️', '.jpeg': '🖼️', '.png': '🖼️', '.gif': '🖼️', '.bmp': '🖼️', '.svg': '🖼️', '.webp': '🖼️', '.ico': '🖼️',
            '.pdf': '📄', '.doc': '📝', '.docx': '📝', '.txt': '📝', '.rtf': '📝', '.odt': '📝',
            '.xls': '📊', '.xlsx': '📊', '.csv': '📊', '.ods': '📊',
            '.ppt': '📽️', '.pptx': '📽️', '.odp': '📽️',
            '.zip': '📦', '.rar': '📦', '.7z': '📦', '.tar': '📦', '.gz': '📦', '.bz2': '📦',
            '.exe': '⚙️', '.msi': '⚙️', '.bat': '⚙️', '.cmd': '⚙️', '.sh': '⚙️',
            '.py': '💻', '.js': '💻', '.html': '💻', '.css': '💻', '.java': '💻', '.cpp': '💻', '.c': '💻', '.h': '💻',
            '.iso': '💿', '.img': '💿', '.dmg': '💿',
        }
    
    def rowCount(self, parent=QModelIndex()) -> int:
        """Retorna el número total de filas"""
        if parent.isValid():
            return 0
        return len(self._data)
    
    def columnCount(self, parent=QModelIndex()) -> int:
        """Retorna el número de columnas"""
        if parent.isValid():
            return 0
        return len(self._headers)
    
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """
        Retorna los datos para una celda específica
        Solo se llama para celdas VISIBLES en pantalla (virtualización)
        """
        if not index.isValid() or not (0 <= index.row() < len(self._data)):
            return None
        
        row = index.row()
        col = index.column()
        item_data = self._data[row]
        
        # Rol de icono (para columna Elemento)
        if role == Qt.ItemDataRole.DecorationRole and col == 1:
            element = item_data.get('element', '')
            # Extraer extension del nombre si existe
            ext = self._get_extension(element)
            if ext:
                emoji = self._ext_icons.get(ext.lower(), '📄')
                return QIcon()  # PyQt6 no soporta emoji directo, retornamos vacio
            return None
        
        # Rol de display (texto que se muestra)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:  # Checkbox - no mostrar texto en columna de checkbox
                return None
            elif col == 1:  # Elemento
                return item_data.get('element', '')
            elif col == 2:  # Destino
                return item_data.get('category', '')
            elif col == 3:  # Porcentaje
                percentage = item_data.get('percentage', 0)
                return f"{percentage:.1f}%" if percentage > 0 else "-"
            elif col == 4:  # Archivos
                return str(item_data.get('file_count', 0))
            elif col == 5:  # Tamaño
                return item_data.get('size_formatted', '0 B')
        
        # Rol de checkbox (para columna 0)
        elif role == Qt.ItemDataRole.CheckStateRole and col == 0:
            if item_data.get('is_child', False):
                return None
            return Qt.CheckState.Checked if item_data.get('_row_id') in self._checked_ids else Qt.CheckState.Unchecked
        
        # Rol de font (negrita para grupos)
        elif role == Qt.ItemDataRole.FontRole:
            if col == 1 and item_data.get('is_group', False):
                font = QFont(QApplication.font())
                font.setBold(True)
                return font
        
        # Rol de tooltip
        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == 1:
                return item_data.get('tooltip', '')
            elif col == 5:
                size_bytes = item_data.get('size_bytes', 0)
                return f"Tamaño exacto: {size_bytes:,} bytes"
        
        return None
    
    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """Permite modificar datos (principalmente checkboxes)"""
        if not index.isValid():
            return False
        
        row = index.row()
        col = index.column()
        
        # Manejar cambio de checkbox
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            row_id = self._data[row].get('_row_id')
            if self._data[row].get('is_child', False) or not row_id:
                return False
            if value == Qt.CheckState.Checked:
                self._checked_ids.add(row_id)
            else:
                self._checked_ids.discard(row_id)
            
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            return True
        
        return False
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Define qué celdas son editables/seleccionables"""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        
        # Hacer checkboxes editables
        if index.column() == 0 and not self._data[index.row()].get('is_child', False):
            flags |= Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
        
        return flags
    
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Retorna los headers de columnas/filas"""
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self._headers[section] if section < len(self._headers) else ""
            else:
                return str(section + 1)
        
        return QVariant()
    
    def update_data(self, new_data: List[Dict[str, Any]]):
        """Actualiza los datos del modelo y notifica a las vistas"""
        self.beginResetModel()
        self._data = self._prepare_row_ids(new_data)
        self._full_data = [dict(item) for item in self._data]  # Backup para filtros
        self._checked_ids.clear()
        self._search_filter = ""
        self._category_filter = ""
        self.endResetModel()

    def _build_row_id(self, item: Dict[str, Any], index: int) -> str:
        row_type = item.get('type', 'row')
        if row_type == 'folder':
            original = item.get('original_data', {})
            folder = original.get('folder')
            return f"folder:{folder}" if folder else f"folder:{item.get('element', index)}"
        if row_type == 'file_group':
            return f"group:{item.get('category', '')}:{item.get('element', index)}"
        if row_type == 'file_item':
            original_file = item.get('original_file')
            return f"file:{original_file}" if original_file else f"file:{item.get('element', index)}"
        return f"{row_type}:{item.get('element', index)}:{index}"

    def _prepare_row_ids(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        prepared = []
        for index, item in enumerate(items):
            cloned = dict(item)
            cloned['_row_id'] = item.get('_row_id') or self._build_row_id(cloned, index)
            prepared.append(cloned)
        return prepared

    # --- API de expansión de grupos ---
    def is_group_row(self, row: int) -> bool:
        return 0 <= row < len(self._data) and self._data[row].get('is_group', False)

    def get_group_files(self, row: int) -> List[Dict[str, Any]]:
        if self.is_group_row(row):
            return self._data[row].get('group_files', [])
        return []

    def expand_group(self, row: int) -> bool:
        """Inserta filas hijas debajo del grupo y marca expandido"""
        if not self.is_group_row(row):
            return False
        group = self._data[row]
        if group.get('is_expanded', False):
            return False
        files = group.get('group_files', [])
        if not files:
            return False

        insert_at = row + 1
        items = []
        for fm in files:
            items.append({
                'type': 'file_item',
                'element': f"  📄 {fm['file'].name}",
                'category': group.get('category', ''),
                'percentage': 0,
                'file_count': 1,
                'size_bytes': fm.get('size', 0),
                'size_formatted': f"{fm.get('size', 0)} B",  # Formateo externo si se requiere
                'tooltip': str(fm['file']),
                'is_group': False,
                'is_expanded': False,
                'is_child': True,
                'parent_group_row': row,
                'original_file': str(fm['file']),
                '_row_id': f"file:{fm['file']}"
            })

        self.beginInsertRows(QModelIndex(), insert_at, insert_at + len(items) - 1)
        self._data[insert_at:insert_at] = items
        self.endInsertRows()

        group['is_expanded'] = True
        # Notificar cambio del grupo (estilo/estado)
        top_left = self.index(row, 1)
        bottom_right = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])
        return True

    def collapse_group(self, row: int) -> bool:
        """Elimina filas hijas de un grupo expandido"""
        if not self.is_group_row(row):
            return False
        group = self._data[row]
        if not group.get('is_expanded', False):
            return False

        # Encontrar rango de hijos consecutivos
        start = row + 1
        end = start
        while end < len(self._data) and self._data[end].get('is_child', False) and self._data[end].get('parent_group_row', -1) == row:
            end += 1
        count = end - start
        if count <= 0:
            group['is_expanded'] = False
            return True

        self.beginRemoveRows(QModelIndex(), start, end - 1)
        del self._data[start:end]
        self.endRemoveRows()

        group['is_expanded'] = False
        # Notificar cambio del grupo (estilo/estado)
        top_left = self.index(row, 1)
        bottom_right = self.index(row, self.columnCount() - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.DisplayRole])
        return True
    
    def get_checked_rows(self) -> List[int]:
        """Retorna lista de índices de filas marcadas"""
        return [
            index for index, row in enumerate(self._data)
            if row.get('_row_id') in self._checked_ids
        ]
    
    def get_row_data(self, row: int) -> Optional[Dict[str, Any]]:
        """Retorna los datos de una fila específica"""
        if 0 <= row < len(self._data):
            return self._data[row]
        return None
    
    def check_all(self):
        """Marca todos los checkboxes"""
        self._checked_ids = {
            row.get('_row_id')
            for row in self._data
            if row.get('_row_id') and not row.get('is_child', False)
        }
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self.rowCount() - 1, 0),
            [Qt.ItemDataRole.CheckStateRole]
        )
    
    def uncheck_all(self):
        """Desmarca todos los checkboxes"""
        self._checked_ids.clear()
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self.rowCount() - 1, 0),
            [Qt.ItemDataRole.CheckStateRole]
        )
    
    def clear_data(self):
        """Limpia todos los datos del modelo"""
        self.beginResetModel()
        self._data.clear()
        self._full_data = []
        self._checked_ids.clear()
        self._search_filter = ""
        self._category_filter = ""
        self.endResetModel()
    
    # ===== FILTROS =====
    
    def set_filter(self, search_text: str = "", category: str = ""):
        """Aplica filtros de busqueda y categoria"""
        self._search_filter = search_text.lower()
        self._category_filter = category
        self._apply_filters()
    
    def _apply_filters(self):
        """Aplica los filtros actuales a los datos"""
        if not hasattr(self, '_full_data'):
            self._full_data = list(self._data)
        
        filtered = self._full_data
        
        if self._search_filter:
            filtered = [d for d in filtered if self._search_filter in d.get('element', '').lower()]
        
        if self._category_filter:
            filtered = [d for d in filtered if d.get('category', '') == self._category_filter]
        
        self.beginResetModel()
        self._data = [dict(item) for item in filtered]
        self.endResetModel()
    
    def get_visible_count(self) -> int:
        """Retorna numero de filas visibles despues de filtrar"""
        return len(self._data)
    
    def _get_extension(self, filename: str) -> str:
        """Extrae la extension de un nombre de archivo"""
        if '.' in filename:
            return '.' + filename.rsplit('.', 1)[1].lower()
        return ""
    
    def get_file_emoji(self, filename: str) -> str:
        """Retorna el emoji correspondiente a un archivo"""
        ext = self._get_extension(filename)
        return self._ext_icons.get(ext.lower(), '📄')



class VirtualizedDuplicatesModel(QAbstractTableModel):
    """
    Modelo virtualizado para la tabla de duplicados.

    El estado de los checkboxes se guarda por ruta (no por número de fila),
    de modo que se conserva al cambiar de página, ordenar o filtrar.
    """

    def __init__(self, data: List[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self._data = data if data else []
        self._headers = ["", "Nombre", "Ubicación", "Tamaño", "Fecha", "Comparación", "Acciones"]
        self._checked_paths: set = set()

    # ------------------------------------------------------------------ Qt
    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._data)

    def columnCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._headers)

    def _is_checked(self, item_data: Dict[str, Any]) -> bool:
        return str(item_data.get("path", "")) in self._checked_paths

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._data)):
            return None
        row = index.row()
        col = index.column()
        item_data = self._data[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return None
            if col == 1:
                name = item_data.get("name", "")
                return f"Conservar · {name}" if item_data.get("is_original", False) else f"Copia · {name}"
            if col == 2:
                return str(item_data.get("location", ""))
            if col == 3:
                size_mb = item_data.get("size", 0) / (1024 * 1024)
                return f"{size_mb:.2f} MB"
            if col == 4:
                timestamp = item_data.get("date", 0)
                if timestamp:
                    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
                return "Desconocida"
            if col == 5:
                hash_value = str(item_data.get("hash", "") or "")
                hash_display = hash_value[:12] + "…" if len(hash_value) > 12 else hash_value
                status = item_data.get("match_status", "Candidato")
                return f"{status} · {hash_display}" if hash_display else status
            if col == 6:
                return "🗑️"

        elif role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if self._is_checked(item_data) else Qt.CheckState.Unchecked

        elif role == Qt.ItemDataRole.FontRole:
            if col == 1 and item_data.get("is_original", False):
                font = QFont(QApplication.font())
                font.setBold(True)
                return font

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == 1:
                return f"Ruta completa: {item_data.get('path', '')}\n\nBotón derecho para previsualizar"
            if col == 3:
                return f"Tamaño exacto: {item_data.get('size', 0):,} bytes"
            if col == 5:
                return f"{item_data.get('match_status', 'Candidato')}\nGrupo: {item_data.get('hash', 'N/A')}"
            if col == 6:
                return "Doble clic para retirar solo este archivo"
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            path = str(self._data[index.row()].get("path", ""))
            if value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value:
                self._checked_paths.add(path)
            else:
                self._checked_paths.discard(path)
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            return True
        return False

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
        return flags

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal:
                return self._headers[section] if section < len(self._headers) else ""
            return str(section + 1)
        return QVariant()

    # ------------------------------------------------------------------ datos
    def update_data(self, new_data: List[Dict[str, Any]], keep_checks: bool = True):
        self.beginResetModel()
        self._data = new_data
        if not keep_checks:
            self._checked_paths.clear()
        self.endResetModel()

    def _all_rows(self) -> List[Dict[str, Any]]:
        return self._data

    def _emit_checks_changed(self):
        if self.rowCount() > 0:
            self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount() - 1, 0),
                                  [Qt.ItemDataRole.CheckStateRole])

    def get_checked_rows(self) -> List[int]:
        """Filas marcadas de la vista actual (página)."""
        return [i for i, item in enumerate(self._data) if self._is_checked(item)]

    def get_checked_paths(self) -> List[str]:
        """Rutas marcadas en todas las páginas (solo de filas cargadas)."""
        present = {str(item.get("path", "")) for item in self._all_rows()}
        return sorted(self._checked_paths & present)

    def get_checked_entries(self) -> List[Dict[str, Any]]:
        return [item for item in self._all_rows() if self._is_checked(item)]

    def set_checked_paths(self, paths) -> None:
        self._checked_paths = {str(p) for p in paths}
        self._emit_checks_changed()

    def get_row_data(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    def check_all_duplicates(self):
        """Marca todas las copias (no las que se conservan) en todas las páginas."""
        self._checked_paths = {
            str(item.get("path", "")) for item in self._all_rows() if not item.get("is_original", False)
        }
        self._emit_checks_changed()

    def uncheck_all(self):
        self._checked_paths.clear()
        self._emit_checks_changed()

    def clear_data(self):
        self.beginResetModel()
        self._data = []
        self._checked_paths.clear()
        self.endResetModel()


def _group_key(item: Dict[str, Any]) -> str:
    return str(item.get("group_key") or item.get("hash") or "")


class PaginatedDuplicatesModel(VirtualizedDuplicatesModel):
    """
    Modelo paginado por grupos: un grupo de duplicados nunca se parte entre
    dos páginas y las marcas se conservan al cambiar de página.
    """

    def __init__(self, page_size: int = 1000, parent=None):
        super().__init__([], parent)
        self._full_data: List[Dict[str, Any]] = []
        self._page_size = page_size
        self._current_page = 0
        self._pages: List[tuple] = []  # (inicio, fin) en _full_data
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    @property
    def _total_pages(self) -> int:
        return len(self._pages)

    def _all_rows(self) -> List[Dict[str, Any]]:
        return self._full_data

    def _build_pages(self) -> None:
        self._pages = []
        start = 0
        count = 0
        total = len(self._full_data)
        for idx in range(total):
            count += 1
            last = idx == total - 1
            boundary = last or _group_key(self._full_data[idx + 1]) != _group_key(self._full_data[idx])
            if boundary and (count >= self._page_size or last):
                self._pages.append((start, idx + 1))
                start = idx + 1
                count = 0

    def load_full_data(self, full_data: List[Dict[str, Any]], keep_checks: bool = True):
        present = {str(item.get("path", "")) for item in full_data}
        if keep_checks:
            self._checked_paths &= present
        else:
            self._checked_paths.clear()
        self._full_data = list(full_data)
        if self._sort_column != -1:
            self._sort_data_respecting_groups()
        self._build_pages()
        self._current_page = min(self._current_page, max(0, self._total_pages - 1))
        self._load_current_page()

    def _load_current_page(self):
        if not self._pages:
            self.update_data([])
            return
        start, end = self._pages[self._current_page]
        self.update_data(self._full_data[start:end])

    def clear_data(self):
        self._full_data = []
        self._pages = []
        self._current_page = 0
        super().clear_data()

    def remove_paths(self, paths) -> None:
        """Quita filas (p. ej. tras retirarlas) y descarta grupos con menos de 2 copias."""
        removed = {str(p) for p in paths}
        remaining = [item for item in self._full_data if str(item.get("path", "")) not in removed]
        counts: Dict[str, int] = {}
        for item in remaining:
            counts[_group_key(item)] = counts.get(_group_key(item), 0) + 1
        remaining = [item for item in remaining if counts.get(_group_key(item), 0) >= 2]
        self._checked_paths -= removed
        self.load_full_data(remaining)

    def next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._load_current_page()
            return True
        return False

    def previous_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._load_current_page()
            return True
        return False

    def go_to_page(self, page_number: int):
        if 0 <= page_number < self._total_pages:
            self._current_page = page_number
            self._load_current_page()
            return True
        return False

    def get_page_info(self) -> Dict[str, int]:
        if self._pages:
            start, end = self._pages[self._current_page]
        else:
            start, end = 0, 0
        return {
            "current_page": self._current_page + 1,
            "total_pages": max(1, self._total_pages),
            "page_size": self._page_size,
            "total_items": len(self._full_data),
            "showing_from": start + 1 if end else 0,
            "showing_to": end,
        }

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        if not self._full_data:
            return
        self._sort_column = column
        self._sort_order = order
        self._sort_data_respecting_groups()
        self._current_page = 0
        self._build_pages()
        self._load_current_page()

    def _sort_data_respecting_groups(self):
        """Ordena los grupos entre sí (por su primer archivo) sin separarlos."""
        if self._sort_column == -1:
            return
        column_name = self._headers[self._sort_column] if self._sort_column < len(self._headers) else ""

        def item_key(item):
            if column_name == "Tamaño":
                return item.get("size", 0)
            if column_name == "Fecha":
                return item.get("date", 0)
            if column_name == "Nombre":
                return str(item.get("name", "")).lower()
            if column_name == "Ubicación":
                return str(item.get("location", "")).lower()
            return str(item.get("name", ""))

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in self._full_data:
            groups.setdefault(_group_key(item), []).append(item)
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder
        ordered = []
        for items in groups.values():
            originals = [i for i in items if i.get("is_original")]
            rest = sorted((i for i in items if not i.get("is_original")), key=item_key, reverse=reverse)
            ordered.append(originals + rest)
        ordered.sort(key=lambda items: item_key(items[0]), reverse=reverse)
        self._full_data = [item for items in ordered for item in items]

    def get_sort_info(self) -> Dict[str, Any]:
        return {
            "column": self._sort_column,
            "order": self._sort_order,
            "column_name": self._headers[self._sort_column] if 0 <= self._sort_column < len(self._headers) else "",
        }
