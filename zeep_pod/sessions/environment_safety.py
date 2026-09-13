"""Shared report helpers for versioned environment safety excursions.

Wellness bands describe comfort and score context.  Safety limits are kept as
separate provenance so a short excursion remains visible even when the
sustained Session assessment is otherwise comfortable.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def summarize_safety_excursions(
    values: Iterable[float],
    criterion: Mapping[str, Any],
) -> dict[str, Any]:
    """Count values outside explicit Safety limits without changing scoring."""
    samples = [
        number for value in values if (number := _finite_number(value)) is not None
    ]
    threshold = _finite_number(criterion.get("critical_at_or_above"))
    lower = _finite_number(criterion.get("critical_below"))
    upper = _finite_number(criterion.get("critical_above"))

    def is_excursion(value: float) -> bool:
        return bool(
            (threshold is not None and value >= threshold)
            or (lower is not None and value < lower)
            or (upper is not None and value > upper)
        )

    excursion_count = sum(is_excursion(value) for value in samples)
    return {
        # ``threshold`` remains for backward compatibility with the CO2 report.
        "threshold": threshold,
        "critical_below": lower,
        "critical_above": upper,
        "excursion_observed": bool(excursion_count),
        "excursion_sample_count": excursion_count,
        "excursion_sample_pct": (
            round(100.0 * excursion_count / len(samples)) if samples else 0
        ),
    }


def safety_limit_text(summary: Mapping[str, Any], unit: str = "") -> str:
    """Return concise Admin provenance for one configured Safety limit."""
    lower = _finite_number(summary.get("critical_below"))
    upper = _finite_number(summary.get("critical_above"))
    threshold = _finite_number(summary.get("safety_threshold"))
    suffix = unit or ""
    if lower is not None and upper is not None:
        return f"อยู่นอกช่วง {lower:g}–{upper:g}{suffix}"
    if lower is not None:
        return f"ต่ำกว่า {lower:g}{suffix}"
    if upper is not None:
        return f"สูงกว่า {upper:g}{suffix}"
    if threshold is not None:
        return f"แตะหรือเกิน {threshold:g}{suffix}"
    return "อยู่นอกเกณฑ์ความปลอดภัยที่อนุมัติ"
