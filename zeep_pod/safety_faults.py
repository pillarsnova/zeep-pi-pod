"""Pure evaluation rules for the Pi-local Safety Supervisor."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SafetyThresholds:
    """Versioned deployment settings consumed by fault evaluation."""

    basis_version: str
    basis_approved: bool
    require_co2: bool
    esp32_stale_seconds: float
    bcg_stale_seconds: float
    co2_warning_ppm: float
    co2_fair_max_ppm: float
    co2_critical_ppm: float
    temperature_warning_min_c: float
    temperature_warning_max_c: float
    temperature_critical_min_c: float
    temperature_critical_max_c: float


def evaluate_safety_faults(
    *,
    now: float,
    health: dict[str, Any],
    environment: dict[str, Any],
    esp32_last_update: Any,
    bcg_last_update: Any,
    occupied: bool,
    gpio_ok: bool,
    thresholds: SafetyThresholds,
) -> list[dict[str, str]]:
    """Return current faults without treating stale values as live."""
    faults: list[dict[str, str]] = []
    if not thresholds.basis_version or not thresholds.basis_approved:
        faults.append({
            "code": "safety_threshold_basis_unapproved",
            "severity": "blocking",
            "message": (
                "เกณฑ์ CO₂/อุณหภูมิยังไม่มี versioned approved basis — "
                "ใช้ดู telemetry ได้ แต่ห้าม Arm"
            ),
        })
    if not gpio_ok:
        faults.append({
            "code": "gpio_unavailable",
            "severity": "critical",
            "message": "GPIO ควบคุมอุปกรณ์ไม่ได้",
        })
    _append_esp32_fault(
        faults,
        now=now,
        last_update=esp32_last_update,
        occupied=occupied,
        stale_seconds=thresholds.esp32_stale_seconds,
    )
    _append_co2_fault(faults, environment, thresholds)
    _append_temperature_fault(faults, environment, occupied, thresholds)
    if occupied and (
        not isinstance(bcg_last_update, (int, float))
        or now - bcg_last_update > thresholds.bcg_stale_seconds
    ):
        faults.append({
            "code": "bcg_stale",
            "severity": "warning",
            "message": "BCG ไม่มีข้อมูลใหม่ (telemetry ไม่ใช่ life-safety)",
        })
    if not health.get("wifi_connected"):
        faults.append({
            "code": "network_degraded",
            "severity": "warning",
            "message": "Wi‑Fi/Network หลุด — Pi ยังควบคุม local ต่อ",
        })
    return faults


def _append_esp32_fault(
    faults: list[dict[str, str]],
    *,
    now: float,
    last_update: Any,
    occupied: bool,
    stale_seconds: float,
) -> None:
    severity = "critical" if occupied else "blocking"
    if not isinstance(last_update, (int, float)):
        faults.append({
            "code": "esp32_no_data",
            "severity": severity,
            "message": "ยังไม่มีข้อมูลจาก ESP32",
        })
        return
    age = now - last_update
    if age > stale_seconds:
        faults.append({
            "code": "esp32_stale",
            "severity": severity,
            "message": f"ESP32 ไม่มีข้อมูลใหม่ {age:.1f} วินาที",
        })


def _append_co2_fault(
    faults: list[dict[str, str]],
    environment: dict[str, Any],
    thresholds: SafetyThresholds,
) -> None:
    co2 = environment.get("co2_ppm")
    device = (environment.get("devices") or {}).get("mhz19c") or {}
    if device.get("status") != "live" or not isinstance(co2, (int, float)):
        if thresholds.require_co2:
            faults.append({
                "code": "co2_unavailable",
                "severity": "blocking",
                "message": (
                    "CO₂ sensor ไม่มีข้อมูลสดที่ valid — ห้าม Arm "
                    f"({device.get('status', 'offline')})"
                ),
            })
        return
    value = float(co2)
    if value >= thresholds.co2_critical_ppm:
        faults.append({
            "code": "co2_critical",
            "severity": "critical",
            "message": (
                f"CO₂ {value:.0f} ppm · ภาพรวมระดับวิกฤต "
                f"(≥{thresholds.co2_critical_ppm:.0f})"
            ),
        })
    elif value > thresholds.co2_warning_ppm:
        level = "พอใช้" if value <= thresholds.co2_fair_max_ppm else "แย่"
        faults.append({
            "code": "co2_warning",
            "severity": "warning",
            "message": (
                f"CO₂ {value:.0f} ppm · ภาพรวมระดับ{level} "
                "ควรเพิ่มการระบายอากาศ"
            ),
        })


def _append_temperature_fault(
    faults: list[dict[str, str]],
    environment: dict[str, Any],
    occupied: bool,
    thresholds: SafetyThresholds,
) -> None:
    value = environment.get("temperature_c")
    device = (environment.get("devices") or {}).get("sht3x_dis") or {}
    status = str(device.get("status") or "offline")
    numeric = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )
    if not numeric or status not in {"live", "degraded", "held"}:
        faults.append({
            "code": "temperature_unavailable",
            "severity": "critical" if occupied else "blocking",
            "message": f"เซนเซอร์อุณหภูมิไม่มีข้อมูลที่ใช้ได้ ({status})",
        })
        return
    temperature = float(value)
    if status != "live":
        faults.append({
            "code": "temperature_sensor_degraded",
            "severity": "warning",
            "message": f"เซนเซอร์อุณหภูมิใช้ค่าล่าสุดที่ยังสด ({status})",
        })
    if (
        temperature < thresholds.temperature_critical_min_c
        or temperature > thresholds.temperature_critical_max_c
    ):
        faults.append({
            "code": "temperature_critical",
            "severity": "critical",
            "message": (
                f"อุณหภูมิ {temperature:.1f}°C · ภาพรวมระดับวิกฤต "
                f"(ต้องอยู่ {thresholds.temperature_critical_min_c:g}–"
                f"{thresholds.temperature_critical_max_c:g}°C)"
            ),
        })
    elif (
        temperature < thresholds.temperature_warning_min_c
        or temperature > thresholds.temperature_warning_max_c
    ):
        level = "พอใช้" if 16 <= temperature <= 29 else "แย่"
        faults.append({
            "code": "temperature_warning",
            "severity": "warning",
            "message": (
                f"อุณหภูมิ {temperature:.1f}°C · "
                f"ภาพรวมระดับ{level} ควรปรับแอร์"
            ),
        })
