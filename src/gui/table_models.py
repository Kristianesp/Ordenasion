#!/usr/bin/env python3
"""
Modelos virtualizados para tablas usando QAbstractTableModel
Optimizado para manejar grandes cantidades de datos sin congelar la UI
"""

from PyQt6.QtCore import QAbstractTableModel, Qt, QModelIndex, QVariant
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import QApplication
from typing import List, Dict, Any, Optional
from pathlib import Path
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
    Modelo virtualizado para la tabla de duplicados en duplicates_dashboard.py
    Optimizado para manejar miles de archivos duplicados
    """
    
    def __init__(self, data: List[Dict[str, Any]] = None, parent=None):
        super().__init__(parent)
        self._data = data if data else []
        self._headers = ["", "Nombre", "Ubicación", "Tamaño", "Fecha", "Hash/ID", "Acciones"]
        self._checked_rows = set()
    
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
        SOLO SE RENDERIZA LO VISIBLE (virtualización = performance)
        """
        if not index.isValid() or not (0 <= index.row() < len(self._data)):
            return None
        
        row = index.row()
        col = index.column()
        item_data = self._data[row]
        
        # Display role (texto)
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:  # Checkbox - no mostrar texto
                return None
            elif col == 1:  # Nombre
                name = item_data.get('name', '')
                is_original = item_data.get('is_original', False)
                return f"Conservar · {name}" if is_original else f"Copia · {name}"
            elif col == 2:  # Ubicación
                return str(item_data.get('location', ''))
            elif col == 3:  # Tamaño
                size_mb = item_data.get('size', 0) / (1024 * 1024)
                return f"{size_mb:.2f} MB"
            elif col == 4:  # Fecha
                timestamp = item_data.get('date', 0)
                if timestamp:
                    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
                return "Desconocida"
            elif col == 5:  # Hash/ID
                hash_value = item_data.get('hash', 'N/A')
                hash_display = hash_value[:16] + "..." if hash_value and len(hash_value) > 16 else hash_value
                status = item_data.get("match_status", "Candidato")
                return f"{status} · {hash_display}"
            elif col == 6:  # Acciones
                return "🗑️"
        
        # Checkbox role
        elif role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if row in self._checked_rows else Qt.CheckState.Unchecked
        
        # Font role
        elif role == Qt.ItemDataRole.FontRole:
            if col == 1 and item_data.get('is_original', False):
                font = QFont(QApplication.font())
                font.setBold(True)
                return font
        
        # Tooltip role
        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == 1:
                path = item_data.get('path', '')
                return f"Ruta completa: {path}\n\n🖼️ Botón derecho para previsualizar imagen"
            elif col == 3:
                size_bytes = item_data.get('size', 0)
                return f"Tamaño exacto: {size_bytes:,} bytes"
            elif col == 5:
                hash_value = item_data.get('hash', 'N/A')
                return f"{item_data.get('match_status', 'Candidato')}\nHash/ID: {hash_value}"
        
        return None
    
    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        """Permite modificar datos (checkboxes)"""
        if not index.isValid():
            return False
        
        row = index.row()
        col = index.column()
        
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            if value == Qt.CheckState.Checked:
                self._checked_rows.add(row)
            else:
                self._checked_rows.discard(row)
            
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            return True
        
        return False
    
    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        """Define qué celdas son editables/seleccionables"""
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        
        if index.column() == 0:
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
        """Actualiza los datos del modelo"""
        self.beginResetModel()
        self._data = new_data
        self._checked_rows.clear()
        self.endResetModel()
    
    def get_checked_rows(self) -> List[int]:
        """Retorna lista de índices de filas marcadas"""
        return sorted(list(self._checked_rows))
    
    def get_row_data(self, row: int) -> Optional[Dict[str, Any]]:
        """Retorna los datos de una fila específica"""
        if 0 <= row < len(self._data):
            return self._data[row]
        return None
    
    def check_all_duplicates(self):
        """Marca solo los duplicados (rojos 🔴)"""
        self._checked_rows = {
            i for i in range(len(self._data)) 
            if not self._data[i].get('is_original', False)
        }
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self.rowCount() - 1, 0),
            [Qt.ItemDataRole.CheckStateRole]
        )
    
    def uncheck_all(self):
        """Desmarca todos los checkboxes"""
        self._checked_rows.clear()
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(self.rowCount() - 1, 0),
            [Qt.ItemDataRole.CheckStateRole]
        )
    
    def clear_data(self):
        """Limpia todos los datos del modelo"""
        self.beginResetModel()
        self._data = []
        self._checked_rows.clear()
        self.endResetModel()


class PaginatedDuplicatesModel(VirtualizedDuplicatesModel):
    """
    Modelo paginado para optimizar memoria con grandes cantidades de datos
    Carga solo una "página" de datos a la vez
    """
    
    def __init__(self, page_size: int = 1000, parent=None):
        super().__init__([], parent)
        self._full_data = []  # Todos los datos
        self._page_size = page_size
        self._current_page = 0
        self._total_pages = 0
        self._sort_column = -1  # Columna por la que se ordena (-1 = sin ordenar)
        self._sort_order = Qt.SortOrder.AscendingOrder  # Orden ascendente/descendente
    
    def load_full_data(self, full_data: List[Dict[str, Any]]):
        """Carga todos los datos pero muestra solo la primera página"""
        self._full_data = full_data
        self._total_pages = (len(full_data) + self._page_size - 1) // self._page_size
        self._current_page = 0
        self._load_current_page()
    
    def _load_current_page(self):
        """Carga solo los datos de la página actual"""
        start_idx = self._current_page * self._page_size
        end_idx = min(start_idx + self._page_size, len(self._full_data))
        page_data = self._full_data[start_idx:end_idx]
        self.update_data(page_data)
    
    def next_page(self):
        """Avanza a la siguiente página"""
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._load_current_page()
            return True
        return False
    
    def previous_page(self):
        """Retrocede a la página anterior"""
        if self._current_page > 0:
            self._current_page -= 1
            self._load_current_page()
            return True
        return False
    
    def go_to_page(self, page_number: int):
        """Va a una página específica (0-indexed)"""
        if 0 <= page_number < self._total_pages:
            self._current_page = page_number
            self._load_current_page()
            return True
        return False
    
    def get_page_info(self) -> Dict[str, int]:
        """Retorna información sobre la paginación actual"""
        return {
            'current_page': self._current_page + 1,  # 1-indexed para UI
            'total_pages': self._total_pages,
            'page_size': self._page_size,
            'total_items': len(self._full_data),
            'showing_from': self._current_page * self._page_size + 1,
            'showing_to': min((self._current_page + 1) * self._page_size, len(self._full_data))
        }
    
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder):
        """Ordena los datos por la columna especificada respetando grupos de duplicados"""
        if not self._full_data:
            return
            
        self._sort_column = column
        self._sort_order = order
        
        # Ordenar respetando grupos de duplicados
        self._sort_data_respecting_groups()
        
        # Recargar la página actual
        self._current_page = 0
        self._total_pages = (len(self._full_data) + self._page_size - 1) // self._page_size
        self._load_current_page()
    
    def _sort_data_respecting_groups(self):
        """Ordena los datos respetando los grupos de duplicados"""
        if self._sort_column == -1:
            return
            
        # Obtener nombre de la columna
        column_name = self._headers[self._sort_column] if self._sort_column < len(self._headers) else ""
        
        # Función de ordenamiento
        def sort_key(item):
            if column_name == "Tamaño":
                return item.get('size', 0)
            elif column_name == "Fecha":
                return item.get('date', 0)  # Usar 'date' en lugar de 'modified_time'
            elif column_name == "Nombre":
                return item.get('name', '').lower()  # Usar 'name' en lugar de 'filename'
            elif column_name == "Ubicación":
                return item.get('location', '').lower()  # Usar 'location' en lugar de 'path'
            else:
                return str(item.get('name', ''))
        
        # Los datos son una lista plana de diccionarios, no grupos anidados
        # Ordenar directamente la lista
        self._full_data.sort(
            key=sort_key,
            reverse=(self._sort_order == Qt.SortOrder.DescendingOrder)
        )
    
    def get_sort_info(self) -> Dict[str, Any]:
        """Retorna información sobre el ordenamiento actual"""
        return {
            'column': self._sort_column,
            'order': self._sort_order,
            'column_name': self._headers[self._sort_column] if 0 <= self._sort_column < len(self._headers) else ""
        }
