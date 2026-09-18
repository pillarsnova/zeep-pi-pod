"""Explain one released ZEEP Session score without creating another score.

``Sleep Score`` remains the primary result for Overnight Recovery and
``Recovery Score`` remains the primary result for Nap & Refresh.  This module
adds a versioned presentation layer: actionable status, score drivers,
personal-baseline context and one bounded recommendation.  It is deliberately
pure and never reads a database, changes Sleep State, or controls hardware.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from common.numbers import as_number as _number
from presentation.language import (
    user_confidence_level,
    user_environment_finding_copy,
)
from sessions.restore_summary_baseline import (
    build_baseline_summary,
    build_trend_summary,
)
from sessions.restore_summary_copy import (
    build_recommendation,
    build_status,
    claim_boundary,
    session_scope,
)
from sessions.restore_summary_policy import COMPONENT_COPY
from sessions.result_context import canonical_subjective_outcome
from sessions.score_identity import assess_score_identity, mode_groups
from sleep_system_policy import (
    RESTORE_DRIVER_POLICY_VERSION,
    RESTORE_SUMMARY_VERSION,
    resolve_rest_target,
)


def _mode_group(
    quality: Mapping[str, Any],
    mode: Any,
) -> str:
    source = mode if mode is not None else quality.get("rest_mode")
    groups = mode_groups(source)
    if len(groups) == 1:
        return next(iter(groups))
    return "unknown"


def _source_score(
    quality: Mapping[str, Any],
    group: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = assess_score_identity(quality, group)
    available = quality.get("available") is True
    score = _number(quality.get("score"))
    if (
        not available
        or score is None
        or not 0.0 <= score <= 100.0
        or not identity["valid"]
    ):
        score = None
    is_sleep = group == "sleep"
    is_recovery = group == "nap_recovery"
    source_score = {
        "type": (
            "sleep_score"
            if is_sleep
            else "recovery_score"
            if is_recovery
            else "unresolved_score"
        ),
        "title": (
            "Sleep Score"
            if is_sleep
            else "Recovery Score"
            if is_recovery
            else "Session Score"
        ),
        "value": int(round(score)) if score is not None else None,
        "available": bool(score is not None and group != "unknown"),
        "formula_version": (
            quality.get("formula_version") or identity.get("expected_formula_version")
        )
        if identity["valid"]
        else None,
        "copied_without_recalculation": True,
    }
    return source_score, identity


def _source_target_key(
    quality: Mapping[str, Any],
    group: str,
) -> str | None:
    target = quality.get("duration_target") or {}
    target = dict(target) if isinstance(target, Mapping) else {}
    seconds = _number(target.get("seconds"))
    resolved = resolve_rest_target(group, seconds)
    return resolved.get("key") if resolved.get("available") else None


def _component_drivers(
    quality: Mapping[str, Any],
    group: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points = quality.get("component_points") or {}
    maxima = quality.get("component_max_points") or {}
    imputed = set((quality.get("imputed_component_points") or {}).keys())
    copy = COMPONENT_COPY.get(group, {})
    drivers = []
    for key, text in copy.items():
        if key in imputed:
            continue
        earned = _number(points.get(key))
        maximum = _number(maxima.get(key))
        if earned is None or maximum is None or maximum <= 0:
            continue
        ratio = max(0.0, min(1.0, earned / maximum))
        drivers.append(
            {
                "key": key,
                "category": "score_component",
                "label": text[0],
                "message": text[1] if ratio >= 0.70 else text[2],
                "direction": "positive" if ratio >= 0.70 else "attention",
                "earned_points": round(earned, 1),
                "max_points": round(maximum, 1),
                "attainment_pct": round(ratio * 100.0, 1),
                "affects_source_score": True,
                "causal_claim": False,
            }
        )
    positive = sorted(
        (item for item in drivers if item["direction"] == "positive"),
        key=lambda item: item["attainment_pct"],
        reverse=True,
    )
    attention = sorted(
        (item for item in drivers if item["direction"] == "attention"),
        key=lambda item: item["attainment_pct"],
    )
    return positive, attention


def _environment_driver_copy(
    finding: Mapping[str, Any],
    severity: str,
    decision: str,
) -> tuple[str, str, str | None, bool]:
    return user_environment_finding_copy(
        finding.get("title"),
        severity,
        decision,
        finding.get("metric_key") or finding.get("key"),
    )


def _environment_drivers(
    findings: Iterable[Mapping[str, Any]],
    group: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive = []
    attention = []
    for finding in findings:
        severity = str(finding.get("severity") or "")
        decision = str(finding.get("decision") or "")
        if severity not in {
            "excellent",
            "good",
            "fair",
            "poor",
            "critical",
            "unavailable",
        }:
            continue
        if severity == "unavailable":
            # Missing channels remain visible in Admin QA, but they are not a
            # measured user outcome and cannot justify a specific adjustment.
            continue
        direction = (
            "attention"
            if severity == "unavailable"
            or decision
            in {
                "required",
                "optimise",
                "sensor_check",
                "safety_review",
                "investigate",
            }
            else "positive"
        )
        affects_source_score = bool(finding.get("contributes_to_primary_score"))
        label, message, action, safety_review = _environment_driver_copy(
            finding,
            severity,
            decision,
        )
        item = {
            "key": f"environment_{finding.get('key') or 'unknown'}",
            "category": "environment",
            "label": label,
            "message": message,
            "direction": direction,
            "severity": severity,
            "decision": decision,
            "action": action,
            "affects_source_score": affects_source_score,
            "relationship": (
                "recovery_score_component_and_session_context"
                if group == "nap_recovery" and affects_source_score
                else "session_context_only"
            ),
            "causal_claim": False,
        }
        if safety_review:
            item["priority"] = "safety_review"
            for field in (
                "threshold",
                "critical_below",
                "critical_above",
                "minimum",
                "maximum",
                "sample_count",
                "sample_pct",
            ):
                if finding.get(field) is not None:
                    item[field] = finding[field]
        (attention if direction == "attention" else positive).append(item)
    priority = {
        "safety_review": 0,
        "critical": 1,
        "poor": 2,
        "unavailable": 3,
        "fair": 4,
    }
    attention.sort(
        key=lambda item: (
            0
            if item.get("priority") == "safety_review"
            else priority.get(str(item.get("severity")), 5)
        )
    )
    return positive, attention


def _merge_drivers(
    quality: Mapping[str, Any],
    findings: Iterable[Mapping[str, Any]],
    group: str,
) -> dict[str, Any]:
    component_positive, component_attention = _component_drivers(quality, group)
    environment_positive, environment_attention = _environment_drivers(
        list(findings), group
    )

    # A concrete environmental issue is more useful than repeating the generic
    # Environment component. Keep the point-bearing generic component only when
    # there is no metric-level issue to show.
    if any(item.get("affects_source_score") for item in environment_attention):
        component_attention = [
            item for item in component_attention if item["key"] != "environment_support"
        ]
    attention = (environment_attention + component_attention)[:2]
    positive = (component_positive + environment_positive)[:2]
    return {
        "positive": positive,
        "attention": attention,
        "explainability_available": bool(positive or attention),
        "selection": "highest_two_strengths_and_highest_two_attention_items",
        "policy_version": RESTORE_DRIVER_POLICY_VERSION,
        "environment_never_determines_sleep_state": True,
        "events_are_associations_not_proven_causes": True,
    }


def _confidence(quality: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(quality.get("score_confidence") or {})
    level = source.get("level") or "unknown"
    return {
        "level": level,
        "label": user_confidence_level(level),
        "session_coverage_pct": source.get("session_coverage_pct"),
        "paired_hr_rr_coverage_pct": source.get("paired_hr_rr_coverage_pct"),
        "changes_source_score": False,
        "admin_qa_context": True,
    }


def build_restore_summary(
    quality: Mapping[str, Any] | None,
    *,
    mode: Mapping[str, Any] | None = None,
    findings: Iterable[Mapping[str, Any]] | None = None,
    personal_context: Mapping[str, Any] | None = None,
    trend_context: Mapping[str, Any] | None = None,
    subjective_outcome: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a user-facing explanation around an existing primary score.

    The caller must select mode-specific personal/trend data before passing it
    here.  This prevents accidental comparison of Nap & Refresh with Overnight
    Recovery and keeps storage concerns outside the scoring layer.
    """
    score_quality = dict(quality or {})
    mode_source = mode if mode is not None else score_quality.get("rest_mode")
    group = _mode_group(score_quality, mode_source)
    source_score, score_identity = _source_score(score_quality, group)
    score = _number(source_score["value"])
    source_target_key = _source_target_key(score_quality, group)
    limited_evidence = bool(score_quality.get("limited_evidence_neutral_score"))
    driver_summary = _merge_drivers(
        score_quality,
        list(findings or []),
        group,
    )
    safety_review = bool(score_quality.get("safety_review_required")) or any(
        driver.get("priority") == "safety_review"
        for driver in driver_summary.get("attention", [])
    )
    baseline_summary = build_baseline_summary(
        personal_context if score_identity["valid"] else None,
        score,
        group,
        source_formula_version=source_score.get("formula_version"),
        source_target_key=source_target_key,
    )
    subjective_summary = canonical_subjective_outcome(subjective_outcome)
    return {
        "version": RESTORE_SUMMARY_VERSION,
        "available": source_score["available"],
        "name": "ZEEP Restore Summary",
        "creates_independent_score": False,
        "source_score": source_score,
        "status": build_status(
            group,
            score,
            safety_review=safety_review,
            limited_evidence=limited_evidence,
        ),
        "session_scope": session_scope(group),
        "drivers": driver_summary,
        "personal_baseline": baseline_summary,
        "trend": build_trend_summary(
            trend_context if score_identity["valid"] else None,
            group=group,
            source_formula_version=source_score.get("formula_version"),
            source_target_key=source_target_key,
        ),
        "recommendation": build_recommendation(
            group,
            score,
            driver_summary,
            limited_evidence=limited_evidence,
            quality=score_quality,
            baseline=baseline_summary,
            subjective=subjective_summary,
        ),
        "confidence": _confidence(score_quality),
        "subjective_outcome": subjective_summary,
        "claim_boundary": claim_boundary(),
    }
