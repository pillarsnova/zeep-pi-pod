"""Stable, display-safe result contract for completed ZEEP Sessions.

This module never calculates a Sleep Score or Recovery Score.  It adapts the
versioned values already frozen in ``session_report``/``sleep_quality`` into a
small contract for read-only Pi API clients.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sleep_system_policy import REST_SESSION_GROUPS, rest_mode_group
from zeep_pod.sessions.restore_summary import build_restore_summary
from zeep_pod.sessions.result_context import (
    canonical_restore_contexts,
    persisted_restore_matches,
)

RESULT_CONTRACT_VERSION = "zeep.session-result.v1"
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
PRIVATE_RESULT_FIELDS = {
    "access_token",
    "answers",
    "auth",
    "bcg_base64",
    "health_reference",
    "packet",
    "packets",
    "profile",
    "questionnaire",
    "raw",
    "raw_bcg",
    "raw_samples",
    "refresh_token",
    "samples",
    "wellness_context",
}
PRIVATE_RESULT_SEGMENTS = {
    "authorization",
    "cookie",
    "credential",
    "password",
    "raw",
    "samples",
    "secret",
    "token",
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _normalized_key(key: Any) -> str:
    """Normalize snake, kebab and camelCase names before privacy checks."""
    value = str(key).strip()
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _private_result_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    segments = set(normalized.split("_"))
    compact = normalized.replace("_", "")
    return (
        normalized in PRIVATE_RESULT_FIELDS
        or bool(segments & PRIVATE_RESULT_SEGMENTS)
        or compact.endswith(("apikey", "privatekey"))
    )


def _public_result_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _public_result_value(item)
            for key, item in value.items()
            if not _private_result_key(key)
        }
    if isinstance(value, list | tuple):
        return [_public_result_value(item) for item in value]
    return value


def _mode_groups(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        values = (value.get("group"), value.get("requested"), value.get("resolved"))
    else:
        values = (value,)
    return {group for item in values if (group := rest_mode_group(item)) is not None}


def _quality_type_group(quality: Mapping[str, Any]) -> str | None:
    quality_type = str(quality.get("quality_type") or "").strip()
    if quality_type == "sleep":
        return "sleep"
    if quality_type == "rest_goal":
        return "nap_recovery"
    return None


def _canonical_mode(
    session: Mapping[str, Any],
    quality: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve product mode without allowing a stale report to choose it."""
    session_value = session.get("rest_mode")
    session_present = session_value is not None and str(session_value).strip() != ""
    session_groups = _mode_groups(session_value)
    quality_value = quality.get("rest_mode")
    quality_groups = _mode_groups(quality_value)
    quality_type_group = _quality_type_group(quality)
    if quality_type_group:
        quality_groups.add(quality_type_group)
    report_groups = _mode_groups(report.get("rest_mode"))

    if session_present:
        group = next(iter(session_groups)) if len(session_groups) == 1 else "unknown"
    else:
        group = next(iter(quality_groups)) if len(quality_groups) == 1 else "unknown"

    conflicts: list[dict[str, Any]] = []
    for source, groups in (
        ("session.rest_mode", session_groups),
        ("released_quality", quality_groups),
        ("session_report.rest_mode", report_groups),
    ):
        if len(groups) > 1 or (groups and (group == "unknown" or group not in groups)):
            conflicts.append(
                {
                    "source": source,
                    "reported_groups": sorted(groups),
                    "canonical_group": group,
                }
            )
    if session_present and not session_groups:
        conflicts.append(
            {
                "source": "session.rest_mode",
                "reported_groups": [],
                "canonical_group": "unknown",
            }
        )

    policy = REST_SESSION_GROUPS.get(group, {})
    quality_mode = _mapping(quality_value)
    resolved = quality_mode.get("resolved")
    if rest_mode_group(resolved) != group:
        resolved = None
    return {
        "group": group,
        "label": policy.get("label") or "ยังไม่ทราบรูปแบบการพัก",
        "requested": group if group != "unknown" else "unknown",
        "resolved": resolved,
        "sleep_required": bool(policy.get("sleep_required", False)),
        "protocol_status": (
            _mapping(quality_mode.get("protocol_status")) if not conflicts else {}
        ),
        "review_required": bool(conflicts or group == "unknown"),
        "validation_status": (
            "mode_metadata_conflict"
            if conflicts
            else "mode_unresolved"
            if group == "unknown"
            else "mode_confirmed"
        ),
        "conflicts": conflicts,
    }


def _mode_and_quality(
    session: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    report = _mapping(session.get("session_report"))
    # HistoryService places the result that passed the version/release policy
    # at the Session level. Prefer it over the report's embedded historical
    # copy so an unapproved report cannot bypass the release gate.
    quality = _mapping(session.get("sleep_quality"))
    if not quality:
        quality = _mapping(report.get("quality"))
    return report, quality, _canonical_mode(session, quality, report)


def _score_type(group: str) -> str:
    """Map the already released canonical mode to exactly one score type."""
    if group == "nap_recovery":
        return "recovery_score"
    if group == "sleep":
        return "sleep_score"
    return "unresolved_score"


def _score_title(score_type: str) -> str:
    """Return the invariant public name instead of trusting stored copy."""
    if score_type == "recovery_score":
        return "Recovery Score"
    if score_type == "sleep_score":
        return "Sleep Score"
    return "Session Score"


def _released_score(
    group: str,
    quality: Mapping[str, Any],
    *,
    mode_conflict: bool,
) -> dict[str, Any]:
    """Expose only a valid score released by the persisted quality result."""
    score_type = _score_type(group)
    score_value = _number(quality.get("score"))
    available = bool(
        quality.get("available") is True
        and score_value is not None
        and 0.0 <= score_value <= 100.0
        and score_type != "unresolved_score"
        and not mode_conflict
    )
    reason = quality.get("reason")
    validation_status = quality.get("validation_status")
    if mode_conflict:
        reason = "ข้อมูลรูปแบบการพักขัดกัน ต้องตรวจสอบก่อนเผยแพร่คะแนน"
        validation_status = "mode_metadata_conflict"
    return {
        "type": score_type,
        "title": _score_title(score_type),
        "value": score_value if available else None,
        "available": available,
        "level": quality.get("level") if available else None,
        "formula_version": (quality.get("formula_version") or quality.get("version")),
        "quality_model_version": quality.get("version"),
        "validation_status": validation_status,
        "clinical_validated": bool(
            available and quality.get("clinical_validated") is True
        ),
        "reason": reason,
        "review_required": bool(mode_conflict or group == "unknown"),
    }


def _target_contract(
    session: Mapping[str, Any],
    mode: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> dict[str, Any] | None:
    target = (
        _mapping(quality.get("duration_target"))
        if mode.get("validation_status") != "mode_metadata_conflict"
        else {}
    )
    target_seconds = _number(
        target.get("seconds")
        if target.get("seconds") is not None
        else session.get("target_duration_s")
    )
    if not target and target_seconds is None:
        return None
    return {
        "key": target.get("key"),
        "label": target.get("label"),
        "seconds": target_seconds,
        "minutes": (
            round(target_seconds / 60.0, 1)
            if target_seconds is not None
            else target.get("target_minutes")
        ),
        "recommended_range_minutes": target.get("recommended_range_minutes"),
        "completion_pct": target.get("completion_pct"),
        "protocol_status": _mapping(mode.get("protocol_status")),
    }


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


def _restore_summary(
    session: Mapping[str, Any],
    report: Mapping[str, Any],
    quality: Mapping[str, Any],
    mode: Mapping[str, Any],
    score: Mapping[str, Any],
) -> dict[str, Any]:
    existing = _mapping(report.get("restore_summary"))
    if not existing:
        existing = _mapping(session.get("restore_summary"))
    canonical_quality = _canonical_quality(quality, mode, score)
    canonical = build_restore_summary(
        canonical_quality,
        mode=mode,
        findings=report.get("findings") or [],
    )
    persisted_matches = persisted_restore_matches(
        existing,
        canonical,
        str(mode.get("group") or "unknown"),
    )
    # Preserve Baseline/trend/questionnaire snapshots only when they belong to
    # this exact released score. Status, drivers and recommendation are always
    # rebuilt from the canonical score so the explanation cannot contradict it.
    context_matches = bool(persisted_matches and score.get("available"))
    summary = existing if context_matches else canonical
    public_summary = {
        key: _public_result_value(summary[key] if key in summary else canonical[key])
        for key in PUBLIC_RESTORE_SUMMARY_FIELDS
        if key in summary or key in canonical
    }
    canonical_source_score = {
        "type": score.get("type"),
        "title": score.get("title"),
        "value": score.get("value"),
        "available": bool(score.get("available")),
        "formula_version": score.get("formula_version"),
        "copied_without_recalculation": True,
    }
    contexts = canonical_restore_contexts(
        summary,
        existing,
        canonical,
        group=str(mode.get("group") or "unknown"),
        score_value=_number(score.get("value")),
        score_available=score.get("available") is True,
    )
    canonical_drivers = _public_result_value(canonical.get("drivers") or {})
    if not score.get("available"):
        canonical_drivers = {
            "positive": [],
            "attention": [],
            "explainability_available": False,
            "reason": "คะแนนหลักยังไม่พร้อม จึงไม่แสดงตัวขับคะแนน",
        }
    return {
        **public_summary,
        "version": canonical.get("version"),
        "available": bool(score.get("available")),
        "name": canonical.get("name"),
        "creates_independent_score": False,
        "source_score": canonical_source_score,
        "status": _public_result_value(canonical.get("status") or {}),
        "session_scope": _public_result_value(canonical.get("session_scope") or {}),
        "drivers": canonical_drivers,
        "personal_baseline": contexts["personal_baseline"],
        "trend": contexts["trend"],
        "recommendation": _public_result_value(canonical.get("recommendation") or {}),
        "confidence": _public_result_value(canonical.get("confidence") or {}),
        "subjective_outcome": contexts["subjective_outcome"],
        "claim_boundary": _public_result_value(canonical.get("claim_boundary") or {}),
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


def build_result_contract(session: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt one finalized report without changing its score or raw record."""
    report, quality, mode = _mode_and_quality(session)
    group = str(mode.get("group") or "unknown")
    mode_conflict = mode.get("validation_status") == "mode_metadata_conflict"
    score = _released_score(
        group,
        quality,
        mode_conflict=mode_conflict,
    )
    score_confidence = _mapping(quality.get("score_confidence"))
    report_quality = _mapping(report.get("data_quality"))
    coverage = _mapping(report_quality.get("coverage"))
    if not coverage:
        coverage = _mapping(quality.get("data_coverage"))
    score_coverage = _mapping(quality.get("data_coverage"))
    coverage_contributes = bool(
        score_coverage.get("score_component")
        if "score_component" in score_coverage
        else group == "sleep"
    )
    restore_summary = _restore_summary(
        session,
        report,
        quality,
        mode,
        score,
    )
    return {
        "version": RESULT_CONTRACT_VERSION,
        "session_closed": bool(session.get("ended_at_utc")),
        "score_revision_policy": "versioned_recalculation_with_audit",
        "raw_sensor_record_immutable": True,
        "mode": {
            "key": group,
            "label": mode.get("label"),
            "requested": mode.get("requested"),
            "resolved": mode.get("resolved"),
            "sleep_required": mode.get("sleep_required"),
            "target": _target_contract(session, mode, quality),
            "review_required": mode.get("review_required"),
            "validation_status": mode.get("validation_status"),
            "conflicts": mode.get("conflicts") or [],
        },
        "score": score,
        "restore_summary": restore_summary,
        "data_quality": {
            "level": report_quality.get("level"),
            "label": report_quality.get("label"),
            "coverage": coverage,
            "confidence": score_confidence,
            "confidence_distribution": report_quality.get("confidence_pct"),
            "coverage_contributes_points": coverage_contributes,
            "coverage_points": score_coverage.get("points"),
            "coverage_max_points": score_coverage.get("max_points"),
            "coverage_can_hide_score": False,
        },
        "versions": {
            "result_contract": RESULT_CONTRACT_VERSION,
            "session_report": report.get("version"),
            "score_formula": score["formula_version"],
            "score_quality_model": score["quality_model_version"],
            "restore_summary": restore_summary.get("version"),
        },
        "provenance": {
            "source": (
                "display_recomputed_report"
                if report.get("display_recomputed")
                else "persisted_final_summary"
            ),
            "display_recomputed": bool(report.get("display_recomputed")),
            "display_recomputed_from_version": report.get(
                "display_recomputed_from_version"
            ),
            "persisted_record_unchanged": bool(
                report.get("persisted_record_unchanged", True)
            ),
            "score_recalculated_by_adapter": False,
        },
    }
