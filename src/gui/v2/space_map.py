"""Mapa squarified propio: áreas lógicas, selección y navegación por teclado."""

from PyQt6.QtCore import Qt, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QFontMetrics
from PyQt6.QtWidgets import QWidget, QToolTip
from src.gui.v2.theme import current_tokens, typography_scale


def format_bytes(value: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024


def squarified(areas: list[float], bounds: QRectF) -> list[QRectF]:
    """Divide un rectángulo sin solapamientos intentando áreas cuadradas."""
    if not areas or bounds.width() <= 0 or bounds.height() <= 0:
        return []
    rectangles = []
    remaining = QRectF(bounds)
    row = []
    positive = [area for area in areas if area > 0]
    if not positive:
        return []
    scale = bounds.width() * bounds.height() / sum(positive)
    areas = [area * scale for area in positive]

    def worst(values, edge):
        total = sum(values)
        return max(edge * edge * max(values) / (total * total),
                   total * total / (edge * edge * min(values)))

    def place(values):
        total = sum(values)
        width_left, height_left = max(0, remaining.width()), max(0, remaining.height())
        if width_left < 1e-9 or height_left < 1e-9:
            rectangles.extend(QRectF(remaining.x(), remaining.y(), 0, 0) for _ in values)
            return
        if remaining.width() >= remaining.height():
            width = min(width_left, total / height_left)
            y = remaining.y()
            for index, area in enumerate(values):
                height = max(0, min(remaining.bottom() - y, area / width))
                if index == len(values) - 1:
                    height = max(0, remaining.bottom() - y)
                rectangles.append(QRectF(remaining.x(), y, width, height))
                y += height
            remaining.setRect(remaining.x() + width, remaining.y(), max(0, width_left - width), height_left)
        else:
            height = min(height_left, total / width_left)
            x = remaining.x()
            for index, area in enumerate(values):
                width = max(0, min(remaining.right() - x, area / height))
                if index == len(values) - 1:
                    width = max(0, remaining.right() - x)
                rectangles.append(QRectF(x, remaining.y(), width, height))
                x += width
            remaining.setRect(remaining.x(), remaining.y() + height, width_left, max(0, height_left - height))

    for area in areas:
        if area <= 0:
            continue
        edge = min(remaining.width(), remaining.height())
        if edge < 1e-9:
            if row:
                place(row)
                row = []
            rectangles.append(QRectF(remaining.x(), remaining.y(), 0, 0))
            continue
        if row and worst(row + [area], edge) > worst(row, edge):
            place(row)
            row = []
        row.append(area)
    if row:
        place(row)
    return rectangles


class SpaceMap(QWidget):
    selected = pyqtSignal(int)
    folder_opened = pyqtSignal(int)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.items = []
        self.blocks = []
        self.selected_id = None
        self.setMinimumHeight(300)
        self.setMinimumWidth(0)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Mapa del uso del espacio. Flechas para seleccionar; Intro para entrar en una carpeta.")

    def set_items(self, items, tail_count=0, tail_size=0):
        # La tabla conserva todos. El mapa agrupa la cola para mantener fluidez.
        self.items = [(node.id, node.name, node.size, node.path, node.kind) for node in items[:200] if node.size > 0]
        if tail_size:
            self.items.append((None, f"Otros {tail_count} elementos", tail_size, "Consulta todos en la tabla", "aggregate"))
        self._layout_blocks()

    def _layout_blocks(self):
        bounds = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        total = sum(item[2] for item in self.items)
        shown = []
        small = []
        area = max(0, bounds.width() * bounds.height())
        for item in self.items:
            (small if item[0] is None or (total and item[2] / total * area < 144) else shown).append(item)
        if small:
            shown.append((None, "Otros elementos pequeños", sum(item[2] for item in small),
                          "Todos los elementos siguen disponibles en la tabla", "aggregate"))
        areas = [item[2] / total * area for item in shown] if total else []
        self.blocks = list(zip(squarified(areas, bounds), shown))
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_blocks()

    def set_selected(self, node_id):
        self.selected_id = node_id
        self.update()

    def paintEvent(self, event):
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        dark = QColor(tokens.canvas).lightness() < 128
        palette = ("#254F68", "#295466", "#3C4B63", "#314E70") if dark else ("#D0E3F4", "#CAE7E9", "#DCE1F1", "#C9DDED")
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = painter.font()
        font.setPixelSize(typography_scale(self.config).body)
        painter.setFont(font)
        if not self.blocks:
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No hay tamaños disponibles para dibujar.\nLos elementos de 0 B siguen en la tabla.")
        for index, (rect, item) in enumerate(self.blocks):
            cell = rect.adjusted(1, 1, -1, -1)
            if cell.width() < 1 or cell.height() < 1:
                continue
            painter.setBrush(QColor(palette[index % len(palette)]))
            selected = item[0] is not None and item[0] == self.selected_id
            painter.setPen(QPen(QColor(tokens.text_primary if selected else tokens.stroke), 2 if selected else 1))
            painter.drawRoundedRect(cell, 4, 4)
            if cell.width() > 70 and cell.height() > 42:
                painter.setPen(QColor(tokens.text_primary))
                text = QFontMetrics(font).elidedText(item[1], Qt.TextElideMode.ElideMiddle, max(1, int(cell.width()) - 16))
                painter.drawText(cell.adjusted(8, 6, -8, -6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                                 text + "\n" + format_bytes(item[2]))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens.text_primary), 2))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

    def _item_at(self, position):
        return next((item for rect, item in self.blocks if rect.contains(position)), None)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        item = self._item_at(event.position())
        if item and item[0] is not None:
            self.set_selected(item[0])
            self.selected.emit(item[0])

    def mouseDoubleClickEvent(self, event):
        item = self._item_at(event.position())
        if item and item[4] == "folder":
            self.folder_opened.emit(item[0])

    def mouseMoveEvent(self, event):
        item = self._item_at(event.position())
        if item:
            QToolTip.showText(event.globalPosition().toPoint(), f"{item[3]}\n{item[2]:,} bytes lógicos", self)
        else:
            QToolTip.hideText()

    def keyPressEvent(self, event):
        valid = [item for _, item in self.blocks if item[0] is not None]
        if not valid:
            return super().keyPressEvent(event)
        index = next((index for index, item in enumerate(valid) if item[0] == self.selected_id), -1)
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            delta = -1 if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 1
            item = valid[(index + delta) % len(valid)]
            self.set_selected(item[0])
            self.selected.emit(item[0])
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and index >= 0 and valid[index][4] == "folder":
            self.folder_opened.emit(valid[index][0])
        else:
            super().keyPressEvent(event)
