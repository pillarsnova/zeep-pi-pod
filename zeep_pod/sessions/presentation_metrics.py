"""Mode-aware metric cards for the concise Usage Session presentation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _duration_display(seconds: float | None) -> str:
    if seconds is None:
        return "ยังไม่มีข้อมูล"
    rounded = max(0, int(round(seconds)))
    hours, remainder = divmod(rounded, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    if hours:
        return f"{hours} ชม. {minutes} นาที"
    if minutes:
        return f"{minutes} นาที {seconds_part} วินาที"
    return f"{seconds_part} วินาที"


def _metric(
    key: str,
    label: str,
    value: float | int | None,
    unit: str | None,
    display_value: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "display_value": display_value,
        "available": value is not None,
    }


def _percent_display(value: float | None) -> str:
    return f"{value:.1f}%" if value is not None else "ยังไม่มีข้อมูล"


def _sleep_metrics(
    sleep: Mapping[str, Any],
) -> list[dict[str, Any]]:
    estimated_sleep = _number(sleep.get("estimated_sleep_s"))
    efficiency = _number(sleep.get("sleep_efficiency_pct"))
    wake_entries = _number(sleep.get("wake_entries"))
    if wake_entries is None:
        wake_entries = _number(sleep.get("awakenings"))
    return [
        _metric(
            "estimated_sleep",
            "เวลานอนโดยประมาณ",
            estimated_sleep,
            "s",
            _duration_display(estimated_sleep),
        ),
        _metric(
            "sleep_efficiency",
            "เวลาที่ระบบประเมินว่าหลับ",
            efficiency,
            "%",
            _percent_display(efficiency),
        ),
        _metric(
            "wake_entries",
            "เข้าสู่ช่วงตื่น",
            int(wake_entries) if wake_entries is not None else None,
            "ครั้ง",
            (
                f"{int(wake_entries)} ครั้ง"
                if wake_entries is not None
                else "ยังไม่มีข้อมูล"
            ),
        ),
    ]


def _nap_metrics(
    target: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> list[dict[str, Any]]:
    completion = _number(target.get("completion_pct"))
    movement = _number(_mapping(quality.get("body_response")).get("movement_pct"))
    regularity = _number(
        _mapping(quality.get("physiology")).get("regularity_factor")
    )
    regularity_pct = regularity * 100.0 if regularity is not None else None
    return [
        _metric(
            "target_completion",
            "เวลาพักที่ทำได้",
            completion,
            "%",
            _percent_display(completion),
        ),
        _metric(
            "movement",
            "การเคลื่อนไหวระหว่างพัก",
            movement,
            "%",
            _percent_display(movement),
        ),
        _metric(
            "physiological_regularity",
            "ความนิ่งของสัญญาณชีพ",
            regularity_pct,
            "%",
            _percent_display(regularity_pct),
        ),
    ]


def overview_metrics(detail: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return non-duplicated cards chosen for the canonical Session mode."""
    mode = _mapping(detail.get("mode"))
    report = _mapping(detail.get("report"))
    mode_key = mode.get("key")
    if mode_key == "sleep":
        return _sleep_metrics(_mapping(report.get("sleep")))
    if mode_key == "nap_recovery":
        return _nap_metrics(
            _mapping(mode.get("target")),
            _mapping(report.get("quality")),
        )
    return []
