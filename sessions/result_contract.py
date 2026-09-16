"""Stable, display-safe result contract for completed ZEEP Sessions.

This module never calculates a Sleep Score or Recovery Score.  It adapts the
versioned values already frozen in ``session_report``/``sleep_quality`` into a
small contract for read-only Pi API clients.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common.mappings import as_mapping as _mapping
from common.numbers import as_number as _number
from presentation.language import (
    PRODUCT_LANGUAGE_VERSION,
    user_confidence_level,
    user_score_level,
)
from sessions.protocol_publication import public_protocol_status
from sessions.result_restore_contract import (
    build_result_restore_summary,
)
from sessions.score_identity import (
    assess_score_identity,
)
from sessions.score_identity import (
    mode_groups as _mode_groups,
)
from sessions.score_identity import (
    quality_type_group as _quality_type_group,
)
from sessions.target_provenance import apply_target_review
from sleep_system_policy import (
    REST_SESSION_GROUPS,
    resolve_rest_target,
    rest_mode_group,
)

RESULT_CONTRACT_VERSION = "zeep.session-result.v1"


def _safety_review_required(
    quality: Mapping[str, Any],
    report: Mapping[str, Any],
) -> bool:
    """Propagate a Safety review without changing or withholding the score."""
    environment_support = _mapping(quality.get("environment_support"))
    environment_assessment = _mapping(report.get("environment_assessment"))
    findings = report.get("findings") or []
    return bool(
        quality.get("safety_review_required") is True
        or str(quality.get("level_key") or "").strip().casefold() == "safety_review"
        or environment_support.get("safety_review_required") is True
        or environment_assessment.get("safety_review_required") is True
        or any(
            isinstance(item, Mapping)
            and str(item.get("decision") or "").strip().casefold() == "safety_review"
            for item in findings
        )
    )


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
    protocol_status = (
        public_protocol_status(quality_mode.get("protocol_status"))
        if not conflicts
        else {}
    )
    protocol_review_required = bool(protocol_status.get("review_required") is True)
    resolved = quality_mode.get("resolved")
    if rest_mode_group(resolved) != group:
        resolved = None
    return {
        "group": group,
        "label": policy.get("label") or "กำลังระบุรูปแบบการพัก",
        "requested": group if group != "unknown" else "unknown",
        "resolved": resolved,
        "sleep_required": bool(policy.get("sleep_required", False)),
        "protocol_status": protocol_status,
        "protocol_review_required": protocol_review_required,
        "review_required": bool(
            conflicts or group == "unknown" or protocol_review_required
        ),
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
    target_conflict: bool,
    session_closed: bool,
    safety_review_required: bool,
    quality_review_required: bool,
) -> dict[str, Any]:
    """Expose only a valid score released by the persisted quality result."""
    score_type = _score_type(group)
    score_value = _number(quality.get("score"))
    release_candidate = bool(
        quality.get("available") is True
        and score_value is not None
        and 0.0 <= score_value <= 100.0
        and score_type != "unresolved_score"
        and not mode_conflict
        and not target_conflict
    )
    score_identity = (
        assess_score_identity(quality, group) if release_candidate else None
    )
    provenance_issue = bool(
        score_identity is not None and not score_identity.get("valid")
    )
    available = bool(release_candidate and not provenance_issue)
    validation_status = quality.get("validation_status")
    if available:
        reason = None
    elif mode_conflict:
        reason = "พบข้อมูลรูปแบบการพักไม่ตรงกัน ระบบจึงพักการแสดงคะแนนไว้เพื่อตรวจสอบ"
        validation_status = "mode_metadata_conflict"
    elif target_conflict:
        reason = "เป้าหมายเวลาของรูปแบบการพักไม่ตรงกับสูตรคะแนน ระบบจึงพักคะแนนไว้เพื่อตรวจสอบ"
        validation_status = "target_metadata_conflict"
    elif provenance_issue and score_identity is not None:
        reason = score_identity.get("reason")
        validation_status = score_identity.get("validation_status")
    elif group == "unknown":
        reason = "เลือกรูปแบบการพักเพื่อให้ ZEEP แสดงผลได้เหมาะสม"
    elif session_closed:
        reason = "ครั้งนี้ยังไม่มีคะแนน เพราะข้อมูลสำคัญสำหรับสรุปผลยังไม่ครบ"
    else:
        reason = "ZEEP กำลังรวบรวมข้อมูลสำหรับสรุปผลการพักครั้งนี้"
    return {
        "type": score_type,
        "title": _score_title(score_type),
        "value": score_value if available else None,
        "available": available,
        "level": (
            user_score_level(
                "safety_review" if safety_review_required else quality.get("level_key"),
                quality.get("level"),
            )
            if available
            else None
        ),
        "formula_version": quality.get("formula_version"),
        "quality_model_version": quality.get("version"),
        "validation_status": validation_status,
        # ZEEP is released as a Wellness estimate.  A stale or malformed
        # persisted result must never promote itself into a clinical claim at
        # the public-contract boundary.
        "clinical_validated": False,
        "reason": reason,
        "review_required": bool(
            mode_conflict
            or target_conflict
            or group == "unknown"
            or provenance_issue
            or safety_review_required
            or quality_review_required
        ),
    }


def _target_contract(
    session: Mapping[str, Any],
    mode: Mapping[str, Any],
    quality: Mapping[str, Any],
    target_provenance: Mapping[str, Any],
) -> dict[str, Any] | None:
    target = (
        _mapping(quality.get("duration_target"))
        if mode.get("validation_status") != "mode_metadata_conflict"
        else {}
    )
    session_target = _number(session.get("target_duration_s"))
    if mode.get("group") == "nap_recovery" and session_target is None:
        return None
    persisted_target = _number(target.get("seconds"))
    resolved_session_target = (
        resolve_rest_target(mode.get("group"), session_target)
        if session_target is not None or mode.get("group") == "sleep"
        else {}
    )
    canonical_session_target = bool(resolved_session_target.get("available") is True)
    session_target_overrides = (
        target_provenance.get("verified") is not True
        if mode.get("group") == "nap_recovery"
        else target_provenance.get("valid_for_score") is False
        if mode.get("group") == "sleep"
        else bool(
            session_target is not None
            and (
                not canonical_session_target
                or persisted_target is None
                or abs(session_target - persisted_target) > 1.0
            )
        )
    )
    if session_target_overrides or canonical_session_target:
        resolved_target = resolved_session_target
        canonical_target = {
            "key": resolved_target.get("key"),
            "label": resolved_target.get("label"),
            "seconds": resolved_target.get("seconds"),
            "target_minutes": resolved_target.get("minutes"),
            "recommended_range_minutes": (
                [
                    round(float(value) / 60.0, 1)
                    for value in resolved_target.get(
                        "recommended_range_seconds",
                        [],
                    )
                ]
                or None
            ),
        }
        target = (
            canonical_target
            if session_target_overrides
            else {**target, **canonical_target}
        )
    if session_target is None:
        target_seconds = _number(target.get("seconds"))
    elif canonical_session_target:
        target_seconds = _number(resolved_session_target.get("seconds"))
    else:
        target_seconds = None
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
        "completion_pct": (
            None if session_target_overrides else target.get("completion_pct")
        ),
        "protocol_status": (
            {}
            if session_target_overrides
            else public_protocol_status(mode.get("protocol_status"))
        ),
    }


def _data_quality_contract(
    report: Mapping[str, Any],
    quality: Mapping[str, Any],
    group: str,
) -> dict[str, Any]:
    """Publish QA context without allowing coverage to hide a score."""
    score_confidence = _mapping(quality.get("score_confidence"))
    if score_confidence:
        confidence_level = score_confidence.get("level") or "unknown"
        score_confidence["label"] = user_confidence_level(confidence_level)
    report_quality = _mapping(report.get("data_quality"))
    data_quality_level = report_quality.get("level") or "unknown"
    coverage = _mapping(report_quality.get("coverage"))
    if not coverage:
        coverage = _mapping(quality.get("data_coverage"))
    score_coverage = _mapping(quality.get("data_coverage"))
    coverage_contributes = bool(
        score_coverage.get("score_component")
        if "score_component" in score_coverage
        else group == "sleep"
    )
    return {
        "level": data_quality_level,
        "label": user_confidence_level(data_quality_level),
        "coverage": coverage,
        "confidence": score_confidence,
        "confidence_distribution": report_quality.get("confidence_pct"),
        "coverage_contributes_points": coverage_contributes,
        "coverage_points": score_coverage.get("points"),
        "coverage_max_points": score_coverage.get("max_points"),
        "coverage_can_hide_score": False,
    }


def build_result_contract(session: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt one finalized report without changing its score or raw record."""
    report, quality, mode = _mode_and_quality(session)
    mode, target_provenance, target_conflict = apply_target_review(
        session,
        mode,
        quality,
    )
    group = str(mode.get("group") or "unknown")
    mode_conflict = mode.get("validation_status") == "mode_metadata_conflict"
    session_closed = bool(session.get("ended_at_utc"))
    safety_review_required = _safety_review_required(quality, report)
    quality_review_required = bool(
        quality.get("review_required") is True
        or mode.get("protocol_review_required") is True
    )
    if safety_review_required and quality.get("safety_review_required") is not True:
        quality = {**quality, "safety_review_required": True}
    score = _released_score(
        group,
        quality,
        mode_conflict=mode_conflict,
        target_conflict=target_conflict,
        session_closed=session_closed,
        safety_review_required=safety_review_required,
        quality_review_required=quality_review_required,
    )
    restore_summary = build_result_restore_summary(
        session,
        report,
        quality,
        mode,
        score,
    )
    return {
        "version": RESULT_CONTRACT_VERSION,
        "session_closed": session_closed,
        "score_revision_policy": "versioned_recalculation_with_audit",
        "raw_sensor_record_immutable": True,
        "mode": {
            "key": group,
            "label": mode.get("label"),
            "requested": mode.get("requested"),
            "resolved": mode.get("resolved"),
            "sleep_required": mode.get("sleep_required"),
            "target": _target_contract(
                session,
                mode,
                quality,
                target_provenance,
            ),
            "review_required": mode.get("review_required"),
            "protocol_review_required": mode.get("protocol_review_required"),
            "validation_status": mode.get("validation_status"),
            "conflicts": mode.get("conflicts") or [],
        },
        "score": score,
        "restore_summary": restore_summary,
        "data_quality": _data_quality_contract(report, quality, group),
        "versions": {
            "result_contract": RESULT_CONTRACT_VERSION,
            "session_report": report.get("version"),
            "score_formula": score["formula_version"],
            "score_quality_model": score["quality_model_version"],
            "restore_summary": restore_summary.get("version"),
            "product_language": PRODUCT_LANGUAGE_VERSION,
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
