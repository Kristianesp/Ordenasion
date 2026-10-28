"""Renderer HTML puro (sin widgets) del panel de Discos.

Recibe datos ya calculados (DiskInfo, dict de salud, DiskReport) y una paleta
de colores; devuelve HTML de Qt Rich Text sencillo y sobrio. Al no depender de
Qt se prueba directamente.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict, Mapping, Optional

from src.core.health_service import UNKNOWN_LEVEL, HealthLevel, health_level
from src.utils.formatting import format_bytes

Palette = Mapping[str, str]

DEFAULT_PALETTE = {
    "primary": "#0078D4",
    "text_primary": "#1B1B1F",
    "text_secondary": "#5C6370",
    "border": "#D0D7E2",
    "surface": "#F4F7FB",
    "success": "#107C10",
    "warning": "#9D5D00",
    "error": "#C42B1C",
}

SEVERITY_ROLE = {"ok": "success", "info": "text_secondary", "warning": "warning", "critical": "error"}
LEVEL_ROLE = {"success": "success", "warning": "warning", "danger": "error", "neutral": "text_secondary"}

ATA_ATTRIBUTE_LABELS = {
    5: "Sectores reasignados",
    187: "Errores incorregibles informados",
    197: "Sectores pendientes",
    198: "Sectores incorregibles",
    199: "Errores CRC de interfaz",
}
NVME_ATTRIBUTE_LABELS = {
    "critical_warning": "Avisos críticos",
    "media_errors": "Errores de medio",
    "percentage_used": "Vida usada (%)",
    "available_spare": "Reserva disponible (%)",
    "available_spare_threshold": "Umbral de reserva (%)",
    "num_err_log_entries": "Entradas del registro de errores",
    "unsafe_shutdowns": "Apagados inesperados",
}

ERROR_HINTS = {
    "admin_required": "Windows sólo permite leer SMART con permisos de administrador. Pulsa "
                      "«Reintentar como administrador» (sólo se eleva smartctl) o abre Ordenasion como administrador.",
    "unavailable": "No se encontró smartctl. Coloca smartctl.exe en la carpeta bin/ de Ordenasion.",
    "unmapped": "No se pudo saber a qué disco físico pertenece esta unidad (RAID, volumen dinámico o virtual).",
    "not_applicable": "Las unidades de red, ópticas y RAM no exponen datos SMART.",
    "timeout": "El disco no respondió a tiempo; puede estar en reposo o detrás de un adaptador USB lento.",
    "open_failed": "smartctl no pudo abrir el dispositivo. Muchos adaptadores USB no transmiten SMART.",
    "cancelled": "Se canceló la consulta con permisos de administrador.",
}

DISCLAIMER = ("SMART recoge indicadores que informa el propio disco; esta valoración no garantiza "
              "que no vaya a fallar. Mantén copias de seguridad.")

SYSTEM_DRIVE_HELP = ("Unidad donde está instalado Windows. Ordenasion no toca carpetas del sistema, "
                     "pero conviene organizar sólo tus carpetas personales.")


def _color(palette: Optional[Palette], role: str) -> str:
    palette = palette or DEFAULT_PALETTE
    return palette.get(role) or DEFAULT_PALETTE.get(role, "#000000")


def rgba(color: str, alpha: float) -> str:
    """#RRGGBB → rgba(...) para Qt Rich Text (sin depender de QColor)."""
    value = (color or "").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return color
    try:
        red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return color
    return f"rgba({red}, {green}, {blue}, {max(0.0, min(1.0, alpha)):.2f})"


def _number(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{int(value):,}".replace(",", ".")
    return escape(str(value))


def _rows(rows, palette: Optional[Palette]) -> str:
    secondary = _color(palette, "text_secondary")
    primary = _color(palette, "text_primary")
    cells = "".join(
        f'<tr><td style="color:{secondary}; padding:2px 12px 2px 0;">{escape(label)}</td>'
        f'<td style="color:{primary}; padding:2px 0;">{value}</td></tr>'
        for label, value in rows
    )
    return f'<table cellspacing="0" cellpadding="0">{cells}</table>'


def _section(title: str, palette: Optional[Palette]) -> str:
    return (f'<p style="margin:10px 0 4px 0; color:{_color(palette, "text_secondary")}; '
            f'font-weight:600;">{escape(title)}</p>')


def _dot(role: str, palette: Optional[Palette]) -> str:
    return f'<span style="color:{_color(palette, role)};">●</span>'


def render_basic_html(disk, report=None, palette: Optional[Palette] = None, loading: bool = False) -> str:
    """Datos de la unidad y, si existen, identidad del disco físico."""
    if disk is None:
        return "Selecciona una unidad para ver su información."
    smart = getattr(report, "smart", None) or {}
    system = "Sí" if disk.is_system_drive else "No"
    rows = [
        ("Punto de montaje", escape(disk.mountpoint)),
        ("Sistema de archivos", escape(disk.filesystem or "Desconocido")),
        ("Tipo de unidad", escape(getattr(disk, "drive_type_label", "Disco fijo"))),
        ("Unidad del sistema", system),
        ("Dispositivo", escape(disk.device or "—")),
    ]
    physical = getattr(report, "physical_disk", None)
    if loading:
        rows.append(("Disco físico", "Consultando…"))
    elif report is not None:
        rows.append(("Disco físico", f"Disco {physical}" if physical is not None else "No asociado"))
    if smart:
        rows += [
            ("Modelo", escape(str(smart.get("disk_model") or "—"))),
            ("Interfaz", escape(str(smart.get("media_label") or "—"))),
            ("Nº de serie", escape(str(smart.get("serial_number") or "—"))),
            ("Firmware", escape(str(smart.get("firmware") or "—"))),
        ]
    html = _rows(rows, palette)
    if disk.is_system_drive:
        html += f'<p style="color:{_color(palette, "text_secondary")}; margin-top:8px;">{SYSTEM_DRIVE_HELP}</p>'
    return html


def health_level_for(health: Mapping[str, Any]) -> HealthLevel:
    level = health.get("level")
    if isinstance(level, HealthLevel):
        return level
    if health.get("available") is False:
        return UNKNOWN_LEVEL
    return health_level(health.get("score"))


def render_critical_attributes(smart: Mapping[str, Any], palette: Optional[Palette] = None) -> str:
    attributes = (smart or {}).get("critical_attributes") or {}
    if not attributes:
        return ""
    rows = []
    for key, value in attributes.items():
        if isinstance(key, int):
            label = f"{ATA_ATTRIBUTE_LABELS.get(key, value.get('name', key))} ({key})"
            raw = value.get("raw") if isinstance(value, Mapping) else value
            danger = isinstance(raw, int) and raw > 0 and key in (5, 187, 197, 198)
            text = _number(raw)
        else:
            label = NVME_ATTRIBUTE_LABELS.get(key, key)
            text = _number(value)
            danger = key in ("critical_warning", "media_errors") and isinstance(value, int) and value > 0
        if danger:
            text = f'<span style="color:{_color(palette, "error")}; font-weight:600;">{text}</span>'
        rows.append((label, text))
    return _section("Atributos críticos", palette) + _rows(rows, palette)


def render_history(report, palette: Optional[Palette] = None) -> str:
    from src.core.smart_history import SmartHistory

    rows_data = getattr(report, "history", None) or []
    if len(rows_data) < 2:
        return ""
    summary = SmartHistory.summarize(rows_data)
    rows = [("Periodo", f"{summary['days']} días desde {escape(summary['since'])}")]
    labels = (("reallocated_delta", "Reasignados"), ("pending_delta", "Pendientes"),
              ("uncorrectable_delta", "Incorregibles"), ("media_errors_delta", "Errores de medio"))
    for key, label in labels:
        if key in summary:
            delta = summary[key]
            text = f"+{delta}" if delta > 0 else str(delta)
            if delta > 0:
                text = f'<span style="color:{_color(palette, "error")}; font-weight:600;">{text}</span>'
            rows.append((label, text))
    if "temperature_max" in summary:
        rows.append(("Temperatura máxima", f"{summary['temperature_max']} °C"))
    if "write_bytes_per_day" in summary:
        rows.append(("Escrituras por día", format_bytes(summary["write_bytes_per_day"])))
    return _section("Tendencia (historial SMART)", palette) + _rows(rows, palette)


def render_health_html(disk, health: Optional[Mapping[str, Any]], palette: Optional[Palette] = None,
                       report=None, loading: bool = False) -> str:
    """Estado de salud: nivel, factores, atributos críticos y tendencia."""
    if loading:
        return (f'<p style="color:{_color(palette, "text_secondary")};">Leyendo datos SMART… '
                "puede tardar unos segundos; la interfaz sigue disponible.</p>")
    health = health or {}
    level = health_level_for(health)
    score = health.get("score")
    if health.get("available") is False or score is None:
        error = getattr(report, "error", None) or ("admin_required" if health.get("admin_required") else None)
        hint = ERROR_HINTS.get(error, "No se puede valorar la salud sin datos del dispositivo.")
        status = escape(str(health.get("status") or "Datos SMART no disponibles"))
        return (f'<p style="margin:0 0 6px 0;">{_dot("text_secondary", palette)} <b>Salud: sin datos</b></p>'
                f'<p style="margin:0 0 6px 0; color:{_color(palette, "text_primary")};">{status}</p>'
                f'<p style="margin:0; color:{_color(palette, "text_secondary")};">{escape(hint)}</p>')

    role = LEVEL_ROLE.get(level.role, "text_secondary")
    color = _color(palette, role)
    html = (f'<p style="margin:0 0 4px 0; font-size:large;">{_dot(role, palette)} '
            f'<b style="color:{color};">{escape(level.label)}</b> '
            f'<span style="color:{_color(palette, "text_secondary")};">· {int(score)}/100</span></p>'
            f'<p style="margin:0 0 6px 0; color:{_color(palette, "text_primary")};">{escape(level.advice)}</p>')
    if disk is not None:
        html += (f'<p style="margin:0 0 6px 0; color:{_color(palette, "text_secondary")};">'
                 f'Uso del espacio: {disk.usage_percent:.1f} %</p>')

    alerts = list(health.get("alerts") or [])
    if alerts:
        items = "".join(f"<li>{escape(alert)}</li>" for alert in dict.fromkeys(alerts))
        html += (f'<div style="margin:6px 0; padding:6px 8px; background-color:{rgba(_color(palette, "error"), 0.10)}; '
                 f'border-left:3px solid {_color(palette, "error")};">'
                 f'<b style="color:{_color(palette, "error")};">Alertas</b><ul style="margin:2px 0 0 -20px;">{items}</ul></div>')

    factors = health.get("factors") or []
    if factors:
        lines = []
        for item in factors:
            if isinstance(item, Mapping):
                severity, text = item.get("severity", "info"), item.get("text", "")
            else:
                severity, text = "info", str(item)
            lines.append(f'<tr><td style="padding:1px 6px 1px 0;">{_dot(SEVERITY_ROLE.get(severity, "text_secondary"), palette)}</td>'
                         f'<td style="color:{_color(palette, "text_primary")};">{escape(text)}</td></tr>')
        html += _section("Factores", palette) + f'<table cellspacing="0">{"".join(lines)}</table>'

    smart = getattr(report, "smart", None) or {}
    html += render_critical_attributes(smart, palette)
    html += render_history(report, palette)
    return html + f'<p style="margin-top:10px; color:{_color(palette, "text_secondary")};">{DISCLAIMER}</p>'


def render_content_html(summary: Optional[Mapping[str, Any]], palette: Optional[Palette] = None,
                        loading: bool = False) -> str:
    """Resumen del primer nivel de la unidad (no recorre subcarpetas)."""
    if loading:
        return f'<p style="color:{_color(palette, "text_secondary")};">Leyendo el contenido de la raíz…</p>'
    if not summary:
        return f'<p style="color:{_color(palette, "text_secondary")};">No se pudo leer el contenido de la unidad.</p>'
    html = _rows([
        ("Carpetas", _number(summary.get("total_dirs", 0))),
        ("Archivos", _number(summary.get("total_files", 0))),
        ("Tamaño de los archivos", format_bytes(summary.get("total_size", 0))),
        ("Recientes (< 7 días)", _number(summary.get("recent_files_count", 0))),
        ("Antiguos (> 30 días)", _number(summary.get("old_files_count", 0))),
    ], palette)
    large = summary.get("large_files") or []
    if large:
        html += _section("Archivos grandes (> 100 MB)", palette)
        html += _rows([(item["name"], format_bytes(item["size"])) for item in large[:5]], palette)
    types = sorted((summary.get("file_types") or {}).items(), key=lambda pair: pair[1], reverse=True)[:5]
    if types:
        html += _section("Extensiones más frecuentes", palette)
        html += _rows([("Sin extensión" if ext == "sin_extension" else ext, _number(count)) for ext, count in types], palette)
    note = "Sólo se cuenta el primer nivel de la unidad. Usa «Uso del espacio» para un análisis completo."
    if summary.get("analysis_limit_reached"):
        note = "Recuento limitado a 10.000 elementos del primer nivel. " + note
    return html + f'<p style="margin-top:8px; color:{_color(palette, "text_secondary")};">{note}</p>'


def smart_metric_texts(report) -> Dict[str, str]:
    """Textos de las tarjetas de métricas SMART (— cuando no hay dato)."""
    smart = getattr(report, "smart", None) or {}

    def size(key):
        value = smart.get(key)
        return format_bytes(value) if isinstance(value, (int, float)) else "—"

    hours = smart.get("power_on_hours")
    hours_text = "—"
    if isinstance(hours, (int, float)):
        hours = int(hours)
        hours_text = f"{_number(hours)} h ({_number(hours // 24)} d)"
    temperature = smart.get("temperature")
    return {
        "read_count": _number(smart.get("read_count")),
        "write_count": _number(smart.get("write_count")),
        "read_data": size("read_bytes"),
        "write_data": size("write_bytes"),
        "temperature": f"{int(temperature)} °C" if isinstance(temperature, (int, float)) else "—",
        "power_hours": hours_text,
        "power_cycles": _number(smart.get("power_cycles")),
    }
