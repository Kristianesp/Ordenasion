"""Gráficas de snapshots existentes: no consultan discos ni recorren archivos."""

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from src.gui.v2.space_map import format_bytes
from src.gui.v2.theme import current_tokens, typography_scale


def disk_values(disk):
    """Rechaza snapshots incompletos antes de dibujar proporciones."""
    if disk is None:
        return None
    try:
        total, used, free = (int(getattr(disk, name)) for name in ("total_size", "used_size", "free_size"))
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None
    if total <= 0 or min(used, free) < 0 or used + free > total:
        return None
    return total, used, free


class DiskUsageChart(QWidget):
    """Donut con leyenda numérica; las cifras también son accesibles como texto."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.values = None
        self.setMinimumWidth(0)
        self.setFixedHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Ocupación de la unidad")
        self.set_disk(None)

    def set_disk(self, disk):
        self.values = disk_values(disk)
        if self.values:
            total, used, free = self.values
            text = f"{used / total * 100:.1f}% ocupado. {used:,} bytes ocupados; {free:,} bytes libres; {total:,} bytes totales."
        else:
            text = "Ocupación no disponible. Abre Discos para consultar las unidades."
        self.setAccessibleDescription(text)
        self.setToolTip(text)
        self.update()

    def paintEvent(self, event):
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        scale = typography_scale(self.config)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPixelSize(scale.body)
        painter.setFont(font)
        diameter = min(140, self.height() - 24, self.width() * 0.38)
        ring = QRectF(9, (self.height() - diameter) / 2, diameter, diameter)
        stroke = max(10, diameter * 0.13)
        ring = ring.adjusted(stroke / 2, stroke / 2, -stroke / 2, -stroke / 2)
        painter.setPen(QPen(QColor(tokens.stroke), stroke))
        painter.drawEllipse(ring)
        if not self.values:
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(ring, Qt.AlignmentFlag.AlignCenter, "—")
            painter.drawText(QRectF(diameter + 27, 20, max(0, self.width() - diameter - 35), 130),
                             Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                             "Sin datos de ocupación\nConsulta las unidades en Discos.")
            return
        total, used, free = self.values
        colors = [tokens.accent, tokens.success, tokens.stroke]
        segments = [used, free, total - used - free]
        angle = 90 * 16
        for value, color in zip(segments, colors):
            span = round(value / total * 360 * 16)
            painter.setPen(QPen(QColor(color), stroke))
            painter.drawArc(ring, angle, -span)
            angle -= span
        painter.setPen(QColor(tokens.text_primary))
        bold = QFont(font)
        bold.setBold(True)
        bold.setPixelSize(scale.display)
        painter.setFont(bold)
        painter.drawText(ring, Qt.AlignmentFlag.AlignCenter, f"{used / total * 100:.0f}%")
        painter.setFont(font)
        legend = [("Ocupado", used), ("Libre", free)]
        if segments[2]:
            legend.append(("Sin desglose", segments[2]))
        x = diameter + 28
        for index, ((name, value), color) in enumerate(zip(legend, colors)):
            y = 39 + index * 35
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(x, y + 3, 9, 9), 3, 3)
            painter.setPen(QColor(tokens.text_primary))
            painter.drawText(QRectF(x + 17, y - 4, max(0, self.width() - x - 20), 26),
                             Qt.AlignmentFlag.AlignVCenter, f"{name} · {format_bytes(value)}")


class FolderSizeChart(QWidget):
    """Cinco hijos directos de raíz y el resto, sin sumar carpetas anidadas."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.bars = ()
        self.total = 0
        self.partial = False
        self.has_result = False
        self.setMinimumWidth(0)
        self.setFixedHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Distribución del último análisis de espacio")
        self.set_result(None)

    def set_result(self, result):
        self.bars = ()
        self.has_result = result is not None
        self.total = result.nodes[0].size if result else 0
        self.partial = bool(result and result.nodes[0].status == "partial")
        if result:
            # Los hijos ya están ordenados en el worker; no se reordena el inventario.
            folders = []
            for node_id in result.children.get(0, ())[:5]:
                node = result.nodes[node_id]
                if node.size > 0:
                    folders.append((node.name, node.size, node.path))
            other = self.total - sum(value for _, value, _ in folders)
            if other > 0:
                folders.append(("Otros archivos y carpetas", other, result.root_path))
            self.bars = tuple(folders)
        if self.bars:
            prefix = "Análisis parcial. " if self.partial else ""
            text = prefix + "; ".join(f"{name}: {value:,} bytes" for name, value, _ in self.bars)
        else:
            text = ("Sin tamaños disponibles en este análisis parcial." if self.partial else
                    "La carpeta analizada no contiene bytes lógicos.") if result else "Sin análisis de espacio. Analiza una carpeta para ver su distribución."
        self.setAccessibleDescription(text)
        self.setToolTip(text)
        self.update()

    def paintEvent(self, event):
        tokens = current_tokens(self.config.get_accent_color(), self.config.get_theme_mode())
        font = QFont(self.font())
        font.setPixelSize(typography_scale(self.config).body)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(font)
        if not self.bars:
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(QRectF(12, 0, max(0, self.width() - 24), self.height()),
                             Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             ("Sin tamaños disponibles en este análisis parcial" if self.partial else
                              "Carpeta sin contenido medible") if self.has_result else
                             "Sin análisis de espacio\nAnaliza una carpeta para encontrar qué ocupa más.")
            return
        width = max(0, self.width() - 8)
        for index, (name, value, _) in enumerate(self.bars):
            y = index * 31
            size_text = f"{format_bytes(value)} · {value / self.total * 100:.0f}%"
            right = painter.fontMetrics().horizontalAdvance(size_text) + 12
            label_width = max(0, width - right)
            painter.setPen(QColor(tokens.text_primary))
            painter.drawText(QRectF(0, y, label_width, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideMiddle, int(label_width)))
            painter.drawText(QRectF(label_width, y, right, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, size_text)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens.stroke))
            painter.drawRoundedRect(QRectF(0, y + 23, width, 5), 2.5, 2.5)
            painter.setBrush(QColor(tokens.accent if index < 5 else tokens.text_secondary))
            painter.drawRoundedRect(QRectF(0, y + 23, width * value / self.total, 5), 2.5, 2.5)
