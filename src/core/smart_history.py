"""Historial persistente de SMART (SQLite en el directorio de datos de usuario).

Una fila por disco y día con los indicadores que anticipan fallos:
sectores reasignados/pendientes/incorregibles (5/197/198), errores de medio
NVMe, porcentaje de vida usado, temperatura y datos escritos. Al registrar una
muestra se comparan con el día anterior y se devuelven alertas si aumentan.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Campo -> (texto de la alerta, umbral de aumento)
TRACKED_COUNTERS = {
    "reallocated": "Los sectores reasignados (5) han aumentado",
    "pending": "Los sectores pendientes (197) han aumentado",
    "uncorrectable": "Los sectores incorregibles (198) han aumentado",
    "media_errors": "Los errores de medio NVMe han aumentado",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS smart_daily (
    disk_key TEXT NOT NULL,
    day TEXT NOT NULL,
    updated_at REAL NOT NULL,
    model TEXT,
    temperature INTEGER,
    temperature_max INTEGER,
    reallocated INTEGER,
    pending INTEGER,
    uncorrectable INTEGER,
    media_errors INTEGER,
    percentage_used INTEGER,
    write_bytes INTEGER,
    power_on_hours INTEGER,
    PRIMARY KEY (disk_key, day)
)
"""

COLUMNS = ("day", "updated_at", "model", "temperature", "temperature_max", "reallocated", "pending",
           "uncorrectable", "media_errors", "percentage_used", "write_bytes", "power_on_hours")


def disk_key_for(smart: Dict[str, Any]) -> Optional[str]:
    """Clave estable del disco: modelo + número de serie."""
    serial = (smart or {}).get("serial_number")
    model = (smart or {}).get("disk_model") or ""
    if not serial or serial == "N/A":
        return None
    return f"{model.strip()}|{str(serial).strip()}"


class SmartHistory:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            from src.utils.paths import user_data_file
            db_path = user_data_file("smart_history.db")
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=5)
        if not self._initialized:
            connection.execute(_SCHEMA)
            connection.commit()
            self._initialized = True
        return connection

    def record(self, smart: Dict[str, Any], when: Optional[datetime] = None) -> List[str]:
        """Guarda la muestra del día y devuelve alertas si algo empeoró."""
        key = disk_key_for(smart)
        if not key:
            return []
        when = when or datetime.now()
        day = when.date().isoformat()
        sample = {
            "model": smart.get("disk_model"),
            "temperature": smart.get("temperature"),
            "reallocated": smart.get("reallocated_sectors"),
            "pending": smart.get("pending_sectors"),
            "uncorrectable": smart.get("uncorrectable_sectors"),
            "media_errors": smart.get("media_errors"),
            "percentage_used": smart.get("percentage_used"),
            "write_bytes": smart.get("write_bytes"),
            "power_on_hours": smart.get("power_on_hours"),
        }
        try:
            with self._lock, self._connect() as connection:
                previous = connection.execute(
                    "SELECT reallocated, pending, uncorrectable, media_errors, temperature_max "
                    "FROM smart_daily WHERE disk_key = ? AND day < ? ORDER BY day DESC LIMIT 1",
                    (key, day)).fetchone()
                today = connection.execute(
                    "SELECT temperature_max FROM smart_daily WHERE disk_key = ? AND day = ?",
                    (key, day)).fetchone()
                temp = sample["temperature"]
                known = [value for value in (temp, today[0] if today else None) if value is not None]
                temp_max = max(known) if known else None
                connection.execute(
                    "INSERT OR REPLACE INTO smart_daily (disk_key, day, updated_at, model, temperature, "
                    "temperature_max, reallocated, pending, uncorrectable, media_errors, percentage_used, "
                    "write_bytes, power_on_hours) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, day, time.time(), sample["model"], temp, temp_max, sample["reallocated"],
                     sample["pending"], sample["uncorrectable"], sample["media_errors"],
                     sample["percentage_used"], sample["write_bytes"], sample["power_on_hours"]))
        except sqlite3.Error as exc:
            logger.warning("No se pudo guardar el historial SMART: %s", exc)
            return []
        alerts = []
        if previous:
            for (column, text), old in zip(TRACKED_COUNTERS.items(), previous[:4]):
                new = sample[column]
                if new is not None and old is not None and new > old:
                    alerts.append(f"{text}: {old} → {new}")
        return alerts

    def trend(self, smart_or_key, days: int = 30) -> List[Dict[str, Any]]:
        """Filas diarias más recientes (ordenadas de antigua a reciente)."""
        key = smart_or_key if isinstance(smart_or_key, str) else disk_key_for(smart_or_key)
        if not key:
            return []
        try:
            with self._lock, self._connect() as connection:
                rows = connection.execute(
                    f"SELECT {', '.join(COLUMNS)} FROM smart_daily WHERE disk_key = ? "
                    "ORDER BY day DESC LIMIT ?", (key, int(days))).fetchall()
        except sqlite3.Error as exc:
            logger.warning("No se pudo leer el historial SMART: %s", exc)
            return []
        return [dict(zip(COLUMNS, row)) for row in reversed(rows)]

    @staticmethod
    def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Variación entre la primera y la última muestra del periodo."""
        if not rows:
            return {}
        first, last = rows[0], rows[-1]
        summary: Dict[str, Any] = {"days": len(rows), "since": first["day"]}
        for column in ("reallocated", "pending", "uncorrectable", "media_errors", "write_bytes"):
            if first.get(column) is not None and last.get(column) is not None:
                summary[f"{column}_delta"] = last[column] - first[column]
        temps = [row["temperature_max"] for row in rows if row.get("temperature_max") is not None]
        if temps:
            summary["temperature_max"] = max(temps)
        writes = [row for row in rows if row.get("write_bytes") is not None]
        if len(writes) >= 2:
            span = (date.fromisoformat(writes[-1]["day"]) - date.fromisoformat(writes[0]["day"])).days
            if span > 0:
                summary["write_bytes_per_day"] = (writes[-1]["write_bytes"] - writes[0]["write_bytes"]) / span
        return summary
