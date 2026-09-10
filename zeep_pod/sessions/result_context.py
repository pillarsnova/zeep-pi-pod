"""Canonical public context copied from a persisted Restore Summary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zeep_pod.sessions.restore_summary_baseline import build_baseline_summary


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def canonical_personal_baseline(
    source: Any,
    fallback: Mapping[str, Any],
    *,
    group: str,
    score: float | None,
) -> dict[str, Any]:
    """Rebuild a Baseline result from an explicit, same-mode allowlist."""
    persisted = _mapping(source)
    if persisted.get("mode") != group:
        return dict(fallback)
    maturity = _mapping(persisted.get("maturity"))
    comparison = _mapping(persisted.get("comparison"))
    sessions = _number(maturity.get("sessions_used"))
    if sessions is None:
        return dict(fallback)
    context: dict[str, Any] = {"sessions_used": max(0, int(sessions))}
    median = _number(comparison.get("baseline_median"))
    typical = comparison.get("typical_range")
    if median is not None and 0.0 <= median <= 100.0:
        context["score_median"] = median
    if isinstance(typical, list | tuple) and len(typical) == 2:
        low, high = _number(typical[0]), _number(typical[1])
        if low is not None and high is not None and 0.0 <= low <= high <= 100.0:
            context["score_typical_range"] = [low, high]
    return build_baseline_summary(context, score, group)


def canonical_trend(
    source: Any,
    fallback: Mapping[str, Any],
    *,
    score_available: bool,
) -> dict[str, Any]:
    """Allow only same-mode Session score windows, never day readiness."""
    persisted = _mapping(source)
    if not score_available or persisted.get("available") is not True:
        return dict(fallback)
    windows = _mapping(persisted.get("windows"))
    public_windows: dict[str, Any] = {}
    for key in ("7", "14", "30"):
        window = _mapping(windows.get(key))
        count = _number(window.get("session_count"))
        average = _number(window.get("average"))
        latest = _number(window.get("latest"))
        if (
            count is None
            or average is None
            or latest is None
            or count < 1
            or not 0.0 <= average <= 100.0
            or not 0.0 <= latest <= 100.0
        ):
            continue
        public_windows[key] = {
            "session_count": int(count),
            "average": round(average, 1),
            "latest": round(latest, 1),
        }
    if not public_windows:
        return dict(fallback)
    return {
        "available": True,
        "unit": "sessions",
        "windows": public_windows,
        "mode_specific": True,
        "whole_day_readiness_trend": False,
    }


def canonical_subjective_outcome(source: Any) -> dict[str, Any]:
    """Expose self-report values only with explicit questionnaire provenance."""
    persisted = _mapping(source)
    approved_sources = {
        "pre_post_questionnaire",
        "session_questionnaire",
        "zeep_pre_post_questionnaire",
    }
    provenance = str(persisted.get("source") or "").strip().casefold()
    freshness = _number(persisted.get("freshness_delta"))
    readiness = _number(persisted.get("activity_readiness"))
    has_measurement = (
        freshness is not None
        and -10.0 <= freshness <= 10.0
        or readiness is not None
        and 0.0 <= readiness <= 10.0
    )
    valid = bool(
        persisted.get("status") == "measured"
        and persisted.get("sensor_inferred") is False
        and provenance in approved_sources
        and has_measurement
    )
    if not valid:
        return {
            "status": "not_measured",
            "label": "ความรู้สึกหลังพัก · ไม่ได้วัด",
            "freshness_delta": None,
            "activity_readiness": None,
            "sensor_inferred": False,
        }
    return {
        "status": "measured",
        "label": "มีแบบประเมินก่อน–หลัง Session",
        "freshness_delta": freshness,
        "activity_readiness": readiness,
        "source": provenance,
        "sensor_inferred": False,
    }


def persisted_restore_matches(
    existing: Mapping[str, Any],
    canonical: Mapping[str, Any],
    group: str,
) -> bool:
    """Confirm that persisted context belongs to this score and mode."""
    persisted_source = _mapping(existing.get("source_score"))
    canonical_source = _mapping(canonical.get("source_score"))
    persisted_scope = _mapping(existing.get("session_scope"))
    return bool(
        existing
        and existing.get("version") == canonical.get("version")
        and persisted_source.get("type") == canonical_source.get("type")
        and _number(persisted_source.get("value"))
        == _number(canonical_source.get("value"))
        and persisted_source.get("formula_version")
        == canonical_source.get("formula_version")
        and persisted_scope.get("mode") == group
    )


def canonical_restore_contexts(
    summary: Mapping[str, Any],
    existing: Mapping[str, Any],
    canonical: Mapping[str, Any],
    *,
    group: str,
    score_value: float | None,
    score_available: bool,
) -> dict[str, Any]:
    """Return the three persisted context sections through strict adapters."""
    return {
        "personal_baseline": canonical_personal_baseline(
            summary.get("personal_baseline"),
            _mapping(canonical.get("personal_baseline")),
            group=group,
            score=score_value if score_available else None,
        ),
        "trend": canonical_trend(
            summary.get("trend"),
            _mapping(canonical.get("trend")),
            score_available=score_available,
        ),
        "subjective_outcome": canonical_subjective_outcome(
            existing.get("subjective_outcome")
        ),
    }
