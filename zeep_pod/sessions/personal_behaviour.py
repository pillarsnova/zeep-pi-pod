"""Build formula-safe, target-specific personal behaviour baselines."""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from typing import Any

from sleep_system_policy import (
    RECOVERY_SCORE_FORMULA_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
)

ENVIRONMENT_KEYS = (
    "temp_median",
    "humidity_median",
    "co2_median",
    "lux_median",
    "sound_median",
)


def _numbers(rows: list[Mapping[str, Any]], key: str) -> list[float]:
    return [
        float(row[key])
        for row in rows
        if isinstance(row.get(key), (int, float))
        and not isinstance(row.get(key), bool)
    ]


def _percentile(values: list[float], q: float) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    index = (len(ordered) - 1) * q
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _typical_range(values: list[float]) -> list[float] | None:
    if not values:
        return None
    low = _percentile(values, 0.25)
    high = _percentile(values, 0.75)
    return [round(low, 1), round(high, 1)] if low is not None and high is not None else None


def _median(values: list[float], digits: int = 1) -> float | None:
    return round(statistics.median(values), digits) if values else None


def _formula_for(group: str) -> str:
    return (
        SLEEP_SCORE_FORMULA_VERSION
        if group == "sleep"
        else RECOVERY_SCORE_FORMULA_VERSION
    )


def _respiratory_reference(
    rows: list[Mapping[str, Any]],
    minimum_sessions: int,
) -> dict[str, Any]:
    rates = _numbers(rows, "respiratory_rr_median")
    regularity = _numbers(rows, "respiratory_regularity_factor")
    return {
        "status": "active" if len(rates) >= minimum_sessions else "learning",
        "sessions_used": len(rates),
        "minimum_sessions": minimum_sessions,
        "median_rr_brpm": _median(rates),
        "typical_range_rr_brpm": _typical_range(rates),
        "regularity_median": _median(regularity, 3),
        "method": "median_and_interquartile_range",
        "same_mode_only": True,
        "prior_completed_sessions_only": True,
        "direct_stage_influence": False,
        "affects_score": False,
    }


def _cohort(
    rows: list[Mapping[str, Any]],
    *,
    group: str,
    minimum_sessions: int,
    score_minimum_sessions: int,
    target_specific: bool,
    target_key: str | None = None,
) -> dict[str, Any]:
    formula = _formula_for(group)
    comparable = [
        row
        for row in rows
        if row.get("score_formula_version") == formula
        and isinstance(row.get("wellness_score"), (int, float))
        and not isinstance(row.get("wellness_score"), bool)
    ]
    scores = [float(row["wellness_score"]) for row in reversed(comparable)]
    score_range = _typical_range(scores)
    score_count = len(scores)
    durations = _numbers(rows, "duration_s")
    onset = _numbers(rows, "onset_proxy_s")
    start_hours = _numbers(rows, "start_local_hour")
    return {
        "status": "active" if len(rows) >= minimum_sessions else "learning",
        "sessions_used": len(rows),
        "minimum_sessions": minimum_sessions,
        "session_ids": [str(row["session_id"]) for row in rows],
        "target_specific": target_specific,
        "target_key": target_key,
        "scores": scores,
        "score_median": _median(scores),
        "score_typical_range": score_range,
        "score_reference": {
            "status": (
                "active"
                if score_count >= score_minimum_sessions
                else "learning"
            ),
            "sessions_used": score_count,
            "minimum_sessions": score_minimum_sessions,
            "median": _median(scores),
            "typical_range": score_range,
            "method": "median_and_interquartile_range",
            "same_mode_only": True,
            "same_target_only": target_specific,
            "prior_completed_sessions_only": True,
            "formula_version": formula,
        },
        "score_formula_versions": sorted({
            str(row["score_formula_version"])
            for row in rows
            if row.get("score_formula_version")
        }),
        "expected_onset_minutes": (
            round(statistics.median(onset) / 60.0, 1) if onset else None
        ),
        "typical_duration_minutes": (
            round(statistics.median(durations) / 60.0, 1)
            if durations
            else None
        ),
        "typical_start_local_hour": _median(start_hours, 2),
        "typical_environment": {
            key: _median(_numbers(rows, key)) for key in ENVIRONMENT_KEYS
        },
        "respiratory_reference": _respiratory_reference(
            rows,
            score_minimum_sessions,
        ),
        "direct_stage_influence": False,
        "role": "expectation_report_and_confidence_context_only",
    }


def aggregate_behaviour_by_mode(
    sessions: list[Mapping[str, Any]],
    *,
    minimum_sessions: int,
    score_minimum_sessions: int,
    max_sessions: int,
) -> dict[str, dict[str, Any]]:
    """Partition behaviour by mode, formula and persisted Nap target."""
    grouped: dict[str, dict[str, Any]] = {}
    groups = sorted({str(row.get("mode_group") or "unknown") for row in sessions})
    for group in groups:
        group_rows = [
            row
            for row in sessions
            if str(row.get("mode_group") or "unknown") == group
        ]
        rows = group_rows[:max_sessions]
        context = _cohort(
            rows,
            group=group,
            minimum_sessions=minimum_sessions,
            score_minimum_sessions=score_minimum_sessions,
            target_specific=group == "sleep",
            target_key="overnight_7h" if group == "sleep" else None,
        )
        if group == "nap_recovery":
            context["scores"] = []
            context["score_median"] = None
            context["score_typical_range"] = None
            context["score_reference"] = {
                **context["score_reference"],
                "status": "target_required",
                "sessions_used": 0,
                "median": None,
                "typical_range": None,
                "same_target_only": True,
            }
            context["by_target"] = {
                target_key: _cohort(
                    [
                        row
                        for row in group_rows
                        if row.get("target_key") == target_key
                    ][:max_sessions],
                    group=group,
                    minimum_sessions=minimum_sessions,
                    score_minimum_sessions=score_minimum_sessions,
                    target_specific=True,
                    target_key=target_key,
                )
                for target_key in ("nap_30", "nap_90")
            }
            context["unresolved_target_sessions"] = sum(
                row.get("target_key") not in {"nap_30", "nap_90"}
                for row in group_rows
            )
        grouped[group] = context
    return grouped
