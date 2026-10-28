#!/usr/bin/env python3
"""
Servicio de Salud de Discos
Calcula puntuaciones y factores de salud basados en datos SMART.

Los umbrales de puntuación viven en un único sitio (``health_level``) y los usan
el servicio, el renderer HTML y el visor de discos.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.utils.app_config import AppConfig, get_app_config


@dataclass(frozen=True)
class HealthLevel:
    """Nivel de salud derivado de la puntuación."""

    key: str          # excellent | healthy | attention | warning | critical | unknown
    label: str        # Texto visible
    role: str         # Rol de color: success | warning | danger | neutral
    advice: str


# Umbrales (puntuación mínima, nivel). Ordenados de mayor a menor.
HEALTH_THRESHOLDS = (
    (90, HealthLevel("excellent", "Excelente", "success", "Mantén el buen uso del disco")),
    (75, HealthLevel("healthy", "Saludable", "success", "Monitoriza regularmente")),
    (60, HealthLevel("attention", "Atención", "warning", "Revisa ventilación y uso; copias de seguridad al día")),
    (40, HealthLevel("warning", "Advertencia", "warning", "Considera un reemplazo preventivo y haz copias")),
    (0, HealthLevel("critical", "Crítico", "danger", "Haz copia de seguridad y planifica el reemplazo")),
)
UNKNOWN_LEVEL = HealthLevel("unknown", "Sin datos", "neutral", "No hay datos SMART suficientes para valorar la salud")


def health_level(score: Optional[float]) -> HealthLevel:
    """Único punto de verdad para traducir una puntuación a un nivel."""
    if score is None:
        return UNKNOWN_LEVEL
    for minimum, level in HEALTH_THRESHOLDS:
        if score >= minimum:
            return level
    return HEALTH_THRESHOLDS[-1][1]


def factor(severity: str, text: str) -> Dict[str, str]:
    """Factor de salud: severity es ok | info | warning | critical."""
    return {"severity": severity, "text": text}


@dataclass
class HealthResult:
    """Resultado del análisis de salud de un disco."""

    score: Optional[int]
    status: str
    factors: List[Dict[str, str]]
    temp_score: Optional[int]
    tbw_score: Optional[int]
    hours_score: Optional[int]
    cycles_score: Optional[int]
    device_type: str
    temperature: Optional[int]
    power_on_hours: Optional[int]
    power_cycles: Optional[int]
    tbw: Dict[str, Any]
    wear_score: Optional[int] = None
    sectors: Dict[str, Optional[int]] = field(default_factory=dict)
    alerts: List[str] = field(default_factory=list)

    @property
    def level(self) -> HealthLevel:
        return health_level(self.score)

    @property
    def available(self) -> bool:
        return self.score is not None


class HealthService:
    """Servicio para calcular salud de discos basado en datos SMART."""

    def __init__(self, app_config: Optional[AppConfig] = None):
        self.app_config = app_config or get_app_config()

    def calculate_health(self, smart_data: Dict[str, Any], disk_info: Any) -> HealthResult:
        """Calcula la salud con los factores disponibles.

        Cada componente (temperatura, desgaste, horas, ciclos) es opcional: los
        pesos se renormalizan sobre los disponibles, así un HDD sin atributos de
        escritura sigue teniendo una valoración. Las señales graves (sectores
        pendientes, fallo SMART, bits de smartctl) limitan la puntuación final.
        """
        factors: List[Dict[str, str]] = []
        caps: List[int] = []
        device_type = smart_data.get("device_type") or "unknown"

        health_cfg = self.app_config.get("health", {}) or {}
        temp_cfg = health_cfg.get("temperature", {})
        tbw_per_tb = float(health_cfg.get("tbw_per_tb", 150))
        tbw_bands = health_cfg.get("tbw_bands", {"medium": 0.5, "high": 0.8})
        hours_bands = health_cfg.get("hours_bands", {"moderate": 10000, "high": 30000, "very_high": 50000})
        cycles_bands = health_cfg.get("cycles_bands", {"moderate": 2000, "high": 10000})
        weights = health_cfg.get("weights", {"temp": 0.35, "tbw": 0.35, "hours": 0.20, "cycles": 0.10})
        tbw_by_type = health_cfg.get("tbw_by_type", {})
        degrade_on_smart_fail = bool(health_cfg.get("degrade_on_smart_fail", True))

        # 1) Temperatura
        temp = smart_data.get("temperature")
        temp_score = None
        if isinstance(temp, (int, float)):
            t_crit = int(temp_cfg.get("critical", 85))
            t_high = int(temp_cfg.get("high", 75))
            t_mod = int(temp_cfg.get("moderate", 65))
            t_cool = int(temp_cfg.get("cool_min", 40))
            if temp < 0 or temp >= t_crit:
                temp_score = 10
                factors.append(factor("critical", f"Temperatura fuera de rango: {temp} °C (≥{t_crit} °C o <0 °C)"))
            elif temp >= t_high:
                temp_score = 40
                factors.append(factor("warning", f"Temperatura alta: {temp} °C (reduce la vida útil)"))
            elif temp >= t_mod:
                temp_score = 70
                factors.append(factor("warning", f"Temperatura moderada: {temp} °C"))
            elif temp >= t_cool:
                temp_score = 95
                factors.append(factor("ok", f"Temperatura óptima: {temp} °C"))
            else:
                temp_score = 90
                factors.append(factor("ok", f"Temperatura baja: {temp} °C"))
        else:
            factors.append(factor("info", "Temperatura no reportada"))

        # 2) Desgaste: NVMe percentage_used o TBW (sólo escrituras)
        read_bytes = smart_data.get("read_bytes")
        write_bytes = smart_data.get("write_bytes")
        read_tb = (read_bytes or 0) / 1024 ** 4
        write_tb = (write_bytes or 0) / 1024 ** 4
        total_size = int(getattr(disk_info, "total_size", 0) or 0)
        capacity_tb = max(1.0, total_size / 1024 ** 4)
        rated_tbw = float(tbw_by_type.get(device_type, tbw_per_tb)) * capacity_tb
        if device_type == "hdd" and float(tbw_by_type.get("hdd", 0)) == 0:
            rated_tbw = 0.0

        tbw_score = None
        wear_score = None
        health_percentage = smart_data.get("health_percentage")
        if isinstance(health_percentage, (int, float)):
            wear_score = int(health_percentage)
            used = 100 - wear_score
            severity = "ok" if wear_score >= 70 else "warning" if wear_score >= 30 else "critical"
            factors.append(factor(severity, f"Vida útil consumida: {used} % (restante {wear_score} %)"))
        elif write_bytes is not None and rated_tbw > 0:
            usage_ratio = write_tb / rated_tbw
            if usage_ratio >= 1.0:
                tbw_score = 10
                factors.append(factor("critical", f"TBW excedido ({write_tb:.0f} de {rated_tbw:.0f} TB escritos)"))
            elif usage_ratio >= float(tbw_bands.get("high", 0.8)):
                tbw_score = 40
                factors.append(factor("warning", f"TBW alto ({write_tb:.0f}/{rated_tbw:.0f} TB escritos)"))
            elif usage_ratio >= float(tbw_bands.get("medium", 0.5)):
                tbw_score = 70
                factors.append(factor("warning", f"TBW medio ({write_tb:.0f}/{rated_tbw:.0f} TB escritos)"))
            else:
                tbw_score = 100
                factors.append(factor("ok", f"TBW bajo ({write_tb:.1f}/{rated_tbw:.0f} TB escritos)"))
        elif rated_tbw == 0 and device_type == "hdd":
            factors.append(factor("info", "El desgaste por escrituras (TBW) no aplica a discos mecánicos"))
        else:
            factors.append(factor("info", "El disco no informa de datos escritos"))
        wear_component = wear_score if wear_score is not None else tbw_score

        # 3) Horas de encendido
        hours = smart_data.get("power_on_hours")
        hours_score = None
        if isinstance(hours, (int, float)):
            h_vhigh = int(hours_bands.get("very_high", 50000))
            h_high = int(hours_bands.get("high", 30000))
            h_mod = int(hours_bands.get("moderate", 10000))
            if hours >= h_vhigh:
                hours_score = 40
                factors.append(factor("warning", f"Muy usado: {int(hours):,} h encendido".replace(",", ".")))
            elif hours >= h_high:
                hours_score = 70
                factors.append(factor("warning", f"Uso alto: {int(hours):,} h encendido".replace(",", ".")))
            elif hours >= h_mod:
                hours_score = 90
                factors.append(factor("ok", f"Uso moderado: {int(hours):,} h encendido".replace(",", ".")))
            else:
                hours_score = 100
                factors.append(factor("ok", f"Poco uso: {int(hours):,} h encendido".replace(",", ".")))

        # 4) Ciclos de encendido
        cycles = smart_data.get("power_cycles")
        cycles_score = None
        if isinstance(cycles, (int, float)):
            c_high = int(cycles_bands.get("high", 10000))
            c_mod = int(cycles_bands.get("moderate", 2000))
            if cycles >= c_high:
                cycles_score = 60
                factors.append(factor("warning", f"Ciclos de encendido muy altos ({int(cycles):,})".replace(",", ".")))
            elif cycles >= c_mod:
                cycles_score = 85
                factors.append(factor("ok", f"Ciclos de encendido moderados ({int(cycles):,})".replace(",", ".")))
            else:
                cycles_score = 100
                factors.append(factor("ok", f"Ciclos de encendido bajos ({int(cycles):,})".replace(",", ".")))

        # 5) Sectores y errores de medio (señales graves)
        sectors = {
            "reallocated": smart_data.get("reallocated_sectors"),
            "pending": smart_data.get("pending_sectors"),
            "uncorrectable": smart_data.get("uncorrectable_sectors"),
            "reported_uncorrect": smart_data.get("reported_uncorrect"),
            "crc_errors": smart_data.get("crc_errors"),
            "media_errors": smart_data.get("media_errors"),
        }
        pending = sectors["pending"] or 0
        uncorrectable = sectors["uncorrectable"] or 0
        reallocated = sectors["reallocated"] or 0
        if pending > 0 or uncorrectable > 0:
            caps.append(45)
            factors.append(factor("critical", f"Sectores pendientes ({pending}) o incorregibles ({uncorrectable}): riesgo de pérdida de datos"))
        if reallocated >= 100:
            caps.append(45)
            factors.append(factor("critical", f"Muchos sectores reasignados ({reallocated})"))
        elif reallocated > 0:
            caps.append(74)
            factors.append(factor("warning", f"Sectores reasignados: {reallocated}"))
        elif sectors["reallocated"] == 0:
            factors.append(factor("ok", "Sin sectores reasignados"))
        if (sectors["reported_uncorrect"] or 0) > 0:
            caps.append(74)
            factors.append(factor("warning", f"Errores incorregibles informados: {sectors['reported_uncorrect']}"))
        if (sectors["crc_errors"] or 0) > 0:
            factors.append(factor("info", f"Errores CRC de interfaz: {sectors['crc_errors']} (suele ser el cable o el puerto)"))
        if (sectors["media_errors"] or 0) > 0:
            caps.append(59)
            factors.append(factor("warning", f"Errores de medio NVMe: {sectors['media_errors']}"))
        critical_warning = smart_data.get("critical_warning")
        if isinstance(critical_warning, int) and critical_warning != 0:
            caps.append(39)
            factors.append(factor("critical", f"El NVMe tiene avisos críticos activos (critical_warning = {critical_warning:#x})"))

        # 6) Estado SMART y bits de smartctl
        smart_passed = smart_data.get("smart_status")
        flags = smart_data.get("smart_flags") or {}
        if smart_passed is False and degrade_on_smart_fail:
            caps.append(39)
            factors.append(factor("critical", "SMART informa de FALLO: prioriza copia de seguridad y reemplazo"))
        elif smart_passed is None:
            factors.append(factor("info", "Estado SMART global no disponible (habitual en adaptadores USB)"))
        if flags.get("failing") and degrade_on_smart_fail:
            caps.append(39)
            factors.append(factor("critical", "smartctl indica que el disco está fallando"))
        if flags.get("prefail_threshold"):
            caps.append(49)
            factors.append(factor("critical", "Atributos de prefallo por debajo del umbral del fabricante"))
        if flags.get("past_threshold"):
            caps.append(74)
            factors.append(factor("warning", "Algún atributo estuvo por debajo del umbral en el pasado"))
        if flags.get("selftest_errors"):
            caps.append(59)
            factors.append(factor("warning", "El registro de autodiagnósticos contiene errores"))
        if flags.get("error_log"):
            factors.append(factor("warning", "El registro de errores del disco contiene entradas"))
        for failing in smart_data.get("failing_attributes") or []:
            factors.append(factor("warning", f"Atributo {failing.get('id')} {failing.get('name', '')} falló ({failing.get('when_failed')})"))

        components = [
            (temp_score, float(weights.get("temp", 0.35))),
            (wear_component, float(weights.get("tbw", 0.35))),
            (hours_score, float(weights.get("hours", 0.20))),
            (cycles_score, float(weights.get("cycles", 0.10))),
        ]
        available = [(value, weight) for value, weight in components if value is not None and weight > 0]
        score: Optional[float] = None
        if available:
            total_weight = sum(weight for _, weight in available)
            score = sum(value * weight for value, weight in available) / total_weight
        elif caps or smart_passed is not None:
            # Sólo el estado global: aprobado no implica "excelente".
            score = 80.0 if smart_passed else 39.0
        if score is not None and caps:
            score = min(score, min(caps))

        final_score = int(round(score)) if score is not None else None
        level = health_level(final_score)
        status = f"{level.label} - {level.advice}"
        alerts = [item["text"] for item in factors if item["severity"] == "critical"]

        return HealthResult(
            score=final_score,
            status=status,
            factors=factors,
            temp_score=temp_score,
            tbw_score=tbw_score,
            hours_score=hours_score,
            cycles_score=cycles_score,
            device_type=device_type,
            temperature=int(temp) if isinstance(temp, (int, float)) else None,
            power_on_hours=int(hours) if isinstance(hours, (int, float)) else None,
            power_cycles=int(cycles) if isinstance(cycles, (int, float)) else None,
            tbw={
                "read_tb": round(read_tb, 1),
                "write_tb": round(write_tb, 1),
                "rated_tbw": int(rated_tbw),
                "write_bytes": write_bytes,
                "read_bytes": read_bytes,
            },
            wear_score=wear_score,
            sectors=sectors,
            alerts=alerts,
        )
