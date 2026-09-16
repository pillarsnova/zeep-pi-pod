"""Build the public Restore Summary portion of a Session result contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common.mappings import as_mapping as _mapping
from common.numbers import as_number as _number
from sessions.restore_summary import build_restore_summary
from sessions.result_context import (
    canonical_restore_contexts,
    persisted_restore_matches,
)
from sessions.result_privacy import public_result_value

PUBLIC_RESTORE_SUMMARY_FIELDS = (
    "version",
    "available",
    "name",
    "creates_independent_score",
    "source_score",
    "status",
    "session_scope",
    "drivers",
    "personal_baseline",
    "trend",
    "recommendation",
    "confidence",
    "subjective_outcome",
    "claim_boundary",
)


def _canonical_quality(
    quality: Mapping[str, Any],
    mode: Mapping[str, Any],
    score: Mapping[str, Any],
) -> dict[str, Any]:
    quality_type = {
        "sleep": "sleep",
        "nap_recovery": "rest_goal",
    }.get(str(mode.get("group") or "unknown"))
    return {
        **quality,
        "available": score.get("available") is True,
        "score": score.get("value"),
        "quality_type": quality_type,
        "rest_mode": mode,
    }


def _public_summary_snapshot(
    existing: Mapping[str, Any],
    canonical: Mapping[str, Any],
    *,
    context_matches: bool,
) -> dict[str, Any]:
    source = existing if context_matches else canonical
    return {
        key: public_result_value(source[key] if key in source else canonical[key])
        for key in PUBLIC_RESTORE_SUMMARY_FIELDS
        if key in source or key in canonical
    }


def _public_drivers(
    canonical: Mapping[str, Any],
    *,
    score_available: bool,
    session_closed: bool,
) -> dict[str, Any]:
    drivers = public_result_value(canonical.get("drivers") or {})
    if score_available:
        return drivers
    safety_attention = [
        item
        for item in drivers.get("attention", [])
        if item.get("priority") == "safety_review"
    ]
    if safety_attention:
        reason = (
            "ครั้งนี้ยังไม่มีคะแนน; ข้อมูลที่ควรดูแลเพื่อความปลอดภัยยังแสดงตามปกติ"
            if session_closed
            else "คะแนนกำลังอยู่ระหว่างสรุป; ข้อมูลที่ควรดูแลเพื่อความปลอดภัยยังแสดงตามปกติ"
        )
    else:
        reason = (
            "ครั้งนี้ยังไม่มีคะแนน เพราะข้อมูลสำคัญสำหรับสรุปผลยังไม่ครบ"
            if session_closed
            else "กำลังรวบรวมข้อมูลสำหรับอธิบายคะแนนของการพักครั้งนี้"
        )
    return {
        "positive": [],
        "attention": safety_attention,
        "explainability_available": bool(safety_attention),
        "reason": reason,
        "selection": drivers.get("selection"),
        "policy_version": drivers.get("policy_version"),
        "environment_never_determines_sleep_state": True,
        "events_are_associations_not_proven_causes": True,
    }


def _public_status(
    canonical: Mapping[str, Any],
    score: Mapping[str, Any],
    *,
    session_closed: bool,
) -> dict[str, Any]:
    status = public_result_value(canonical.get("status") or {})
    if score.get("available") or not session_closed:
        return status
    return {
        **status,
        "key": "unavailable",
        "label": "ครั้งนี้ยังไม่มีคะแนน",
        "meaning": score.get("reason"),
    }


def build_result_restore_summary(
    session: Mapping[str, Any],
    report: Mapping[str, Any],
    quality: Mapping[str, Any],
    mode: Mapping[str, Any],
    score: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the explanatory result without recalculating its source score."""
    existing = _mapping(report.get("restore_summary"))
    if not existing:
        existing = _mapping(session.get("restore_summary"))
    canonical = build_restore_summary(
        _canonical_quality(quality, mode, score),
        mode=mode,
        findings=report.get("findings") or [],
    )
    group = str(mode.get("group") or "unknown")
    persisted_matches = persisted_restore_matches(existing, canonical, group)
    score_available = score.get("available") is True
    public_summary = _public_summary_snapshot(
        existing,
        canonical,
        context_matches=bool(persisted_matches and score_available),
    )
    contexts = canonical_restore_contexts(
        existing if persisted_matches and score_available else canonical,
        existing,
        canonical,
        group=group,
        score_value=_number(score.get("value")),
        score_available=score_available,
    )
    session_closed = bool(session.get("ended_at_utc"))
    return {
        **public_summary,
        "version": canonical.get("version"),
        "available": score_available,
        "name": canonical.get("name"),
        "creates_independent_score": False,
        "source_score": {
            "type": score.get("type"),
            "title": score.get("title"),
            "value": score.get("value"),
            "available": score_available,
            "formula_version": score.get("formula_version"),
            "copied_without_recalculation": True,
        },
        "status": _public_status(
            canonical,
            score,
            session_closed=session_closed,
        ),
        "session_scope": public_result_value(canonical.get("session_scope") or {}),
        "drivers": _public_drivers(
            canonical,
            score_available=score_available,
            session_closed=session_closed,
        ),
        "personal_baseline": contexts["personal_baseline"],
        "trend": contexts["trend"],
        "recommendation": public_result_value(canonical.get("recommendation") or {}),
        "confidence": public_result_value(canonical.get("confidence") or {}),
        "subjective_outcome": contexts["subjective_outcome"],
        "claim_boundary": public_result_value(canonical.get("claim_boundary") or {}),
        "whole_day_readiness_available": False,
        "provenance": {
            "source": (
                "persisted_context_with_canonical_explanation"
                if persisted_matches
                else "derived_from_persisted_report_without_rescoring"
            ),
            "score_changed": False,
            "persisted_source_score_matched": persisted_matches,
            "causal_claims": False,
        },
    }
