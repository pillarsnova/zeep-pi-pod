"""Review-only adaptive guidance; never generates executable commands."""

from __future__ import annotations

from typing import Any

from adaptive.control_policy import enforce_advisory
from common.numbers import as_finite_number as finite_number


def _prioritize_recommendations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep urgent guidance visible when clients cap the number of cards."""
    priority = {
        "critical": 0,
        "blocked": 1,
        "attention": 2,
        "watch": 3,
        "personal_baseline": 4,
        "stable": 6,
    }
    # Stable sorting preserves source order for equally important observations.
    return sorted(items, key=lambda item: priority.get(str(item.get("level")), 5))


def _recommendations(
    snapshot: dict[str, Any],
    observation_id: str,
) -> list[dict[str, Any]]:
    smart = snapshot.get("smart_response") or {}
    return [
        {
            "decision_id": f"{observation_id}:{item.get('domain') or 'general'}",
            "domain": item.get("domain"),
            "level": item.get("level"),
            "title": item.get("title"),
            "evidence": item.get("detail"),
            "candidate": item.get("suggestion"),
            "executable": False,
        }
        for item in smart.get("recommendations") or []
        if isinstance(item, dict)
    ]


def _personal_reference_recommendations(
    metrics: list[dict[str, Any]],
    behaviour: dict[str, Any],
    observation_id: str,
) -> list[dict[str, Any]]:
    """Translate a qualified prior Session into review-only device guidance."""
    best_window = behaviour.get("best_rest_window") or {}
    if not (
        best_window.get("available") is True
        and best_window.get("outcome_supported") is True
        and best_window.get("environment_reference_available") is True
    ):
        return []

    settings = {
        "temperature": ("aircon", "อุณหภูมิ", True),
        "humidity": ("humidity", "ความชื้น", True),
        "co2": ("ventilation", "CO₂", False),
        "light": ("light", "แสง", False),
        "sound": ("sound", "เสียง", False),
    }
    recommendations = []
    for metric in metrics:
        key = metric.get("key")
        setting = settings.get(key)
        comparison = metric.get("comparison")
        if setting is None or comparison not in {"above_reference", "below_reference"}:
            continue
        domain, label, allow_both_directions = setting
        if not allow_both_directions and comparison == "below_reference":
            continue
        value = finite_number(metric.get("value"))
        reference = finite_number(metric.get("reference"))
        if value is None or reference is None:
            continue
        direction = "ลด" if value > reference else "เพิ่ม"
        unit = str(metric.get("unit") or "")
        recommendations.append(
            {
                "decision_id": f"{observation_id}:personal:{key}",
                "domain": domain,
                "level": "personal_baseline",
                "title": f"{label}ต่างจากช่วงที่เคยพักได้ดี",
                "evidence": (f"ปัจจุบัน {value:g} {unit} · ข้อมูลตั้งต้น {reference:g} {unit}"),
                "candidate": f"ลอง{direction}{label}ให้ใกล้ {reference:g} {unit}",
                "basis": "prior_completed_same_mode_best_rest_window",
                "baseline_status": best_window.get("status"),
                "requires_user_confirmation": True,
                "executable": False,
            }
        )
    return recommendations


def build_candidate_recommendations(
    snapshot: dict[str, Any],
    metrics: list[dict[str, Any]],
    behaviour: dict[str, Any],
    observation_id: str,
) -> list[dict[str, Any]]:
    """Combine sources under the existing advisory policy and stable priority."""
    return _prioritize_recommendations(
        enforce_advisory(
            [
                *_personal_reference_recommendations(
                    metrics, behaviour, observation_id
                ),
                *_recommendations(snapshot, observation_id),
            ]
        )
    )
