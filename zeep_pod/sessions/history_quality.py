"""Compatibility policy for displaying persisted historical quality scores."""

from __future__ import annotations

from typing import Any

from sleep_system_policy import (
    NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS,
    NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
    PRE_CONTINUITY_SESSION_REPORT_VERSION,
    PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
    PRE_RECOVERY_TIMING_SESSION_REPORT_VERSION,
    PRE_RECOVERY_TIMING_SLEEP_QUALITY_VERSION,
    PRE_RESPIRATORY_SESSION_REPORT_VERSION,
    PRE_RESTORE_SESSION_REPORT_VERSION,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_VERSION,
    is_approved_sleep_result_version,
)
from zeep_pod.sessions.score_identity import assess_score_identity, mode_groups


def _stored_mode(final_summary: dict[str, Any], report: Any) -> Any:
    value: Any = final_summary.get("rest_mode")
    if value is None or not str(value).strip():
        value = report.get("rest_mode") if isinstance(report, dict) else None
    return value or "auto"


def _stored_mode_group(value: Any) -> str | None:
    groups = mode_groups(value)
    return next(iter(groups)) if len(groups) == 1 else None


def _score_release_attempted(quality: Any) -> bool:
    return bool(
        isinstance(quality, dict)
        and (
            quality.get("available") is True
            or (
                not isinstance(quality.get("score"), bool)
                and isinstance(quality.get("score"), (int, float))
            )
        )
    )


def _identity_unavailable_quality(
    quality: Any,
    identity: dict[str, Any],
) -> dict[str, Any]:
    group = identity.get("group")
    sleep_mode = group == "sleep"
    recovery_mode = group == "nap_recovery"
    return {
        **(quality if isinstance(quality, dict) else {}),
        "available": False,
        "score": None,
        "score_releasable": False,
        "score_title": (
            "Sleep Score"
            if sleep_mode
            else "Recovery Score"
            if recovery_mode
            else "รูปแบบการพักยังไม่ยืนยัน"
        ),
        "score_scope": (
            "ค่าประเมินการนอนจาก Sensor"
            if sleep_mode
            else "Recovery Score จากช่วงพักและข้อมูล Sensor"
            if recovery_mode
            else "เลือกว่าเป็น Overnight หรือ Nap & Refresh เพื่อแสดงผล"
        ),
        "formula_version": None,
        "level": "กำลังเตรียมผลสรุป",
        "level_key": "unavailable",
        "reason": identity["reason"],
        "validation_status": identity["validation_status"],
        "clinical_validated": False,
        "legacy_result_hidden": True,
        "rest_mode_unresolved": group is None,
        "review_required": True,
    }


def _recording_seconds(report: Any) -> float | None:
    if not isinstance(report, dict):
        return None
    value = (report.get("sleep") or {}).get("recording_s")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _compatible_versioned_quality(
    report: Any,
    quality: Any,
) -> dict[str, Any] | None:
    """Return an explicitly compatible current or pre-Restore result."""
    if not isinstance(report, dict) or not isinstance(quality, dict):
        return None
    if (
        quality.get("version") == SLEEP_QUALITY_VERSION
        and report.get("version") == SESSION_REPORT_VERSION
    ):
        return quality
    if (
        quality.get("version") == PRE_RECOVERY_TIMING_SLEEP_QUALITY_VERSION
        and report.get("version")
        == PRE_RECOVERY_TIMING_SESSION_REPORT_VERSION
    ):
        return {
            **quality,
            "compatible_pre_recovery_timing_result": True,
        }
    if (
        quality.get("version") == PRE_RECOVERY_TIMING_SLEEP_QUALITY_VERSION
        and report.get("version") == PRE_RESPIRATORY_SESSION_REPORT_VERSION
    ):
        return {
            **quality,
            "compatible_pre_respiratory_result": True,
        }
    if (
        quality.get("version") == PRE_CONTINUITY_SLEEP_QUALITY_VERSION
        and report.get("version") == PRE_CONTINUITY_SESSION_REPORT_VERSION
    ):
        return {
            **quality,
            "compatible_pre_continuity_result": True,
        }
    if (
        quality.get("version") == PRE_CONTINUITY_SLEEP_QUALITY_VERSION
        and report.get("version") == PRE_RESTORE_SESSION_REPORT_VERSION
    ):
        return {
            **quality,
            "compatible_pre_restore_result": True,
        }
    return None


def _preserved_legacy_recovery(
    final_summary: dict[str, Any],
    report: Any,
    quality: Any,
    mode_group: str | None,
) -> dict[str, Any] | None:
    """Preserve a scored legacy Nap only inside the documented guardrail."""
    duration = _recording_seconds(report)
    if not (
        mode_group == "nap_recovery"
        and final_summary.get("target_duration_s") is None
        and duration is not None
        and NAP_RECOVERY_MINIMUM_SCORE_SECONDS
        <= duration
        <= NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS
        and isinstance(quality, dict)
        and quality.get("score") is not None
    ):
        return None
    target_status = (
        "TARGET_UNKNOWN/extended" if duration > 45 * 60 else "TARGET_UNKNOWN"
    )
    return {
        **quality,
        "legacy_score_preserved": True,
        "review_required": True,
        "target_status": target_status,
        "validation_status": "legacy_recovery_target_unknown_preserved",
        "preservation_reason": (
            "Session เดิมไม่มีเป้าหมาย 30/90 นาที; แสดงคะแนนเดิมโดยไม่เขียนทับ"
        ),
    }


def released_historical_quality(
    final_summary: dict[str, Any],
    quality: Any,
) -> dict[str, Any]:
    """Return current quality or a narrowly preserved legacy Recovery score."""
    report = final_summary.get("session_report") or {}
    requested = _stored_mode(final_summary, report)
    mode_group = _stored_mode_group(requested)
    related_modes = []
    if final_summary.get("rest_mode") is not None and isinstance(report, dict):
        related_modes.append(("session_report.rest_mode", report.get("rest_mode")))
    identity = assess_score_identity(
        quality,
        requested,
        related_modes=related_modes,
    )
    release_attempted = _score_release_attempted(quality)
    compatible_quality = _compatible_versioned_quality(report, quality)
    if compatible_quality is not None:
        if not release_attempted or identity["valid"]:
            return compatible_quality
        return _identity_unavailable_quality(compatible_quality, identity)
    approved_untouched_sleep = (
        mode_group == "sleep"
        and isinstance(quality, dict)
        and isinstance(report, dict)
        and is_approved_sleep_result_version(
            report.get("version"), quality.get("version")
        )
    )
    if approved_untouched_sleep:
        compatible_sleep = {
            **quality,
            "compatible_untouched_sleep_result": True,
        }
        if not release_attempted or identity["valid"]:
            return compatible_sleep
        return _identity_unavailable_quality(compatible_sleep, identity)
    legacy_recovery = _preserved_legacy_recovery(
        final_summary,
        report,
        quality,
        mode_group,
    )
    if legacy_recovery is not None:
        if not release_attempted or identity["valid"]:
            return legacy_recovery
        return _identity_unavailable_quality(legacy_recovery, identity)
    if release_attempted and not identity["valid"]:
        return _identity_unavailable_quality(quality, identity)
    sleep_mode = mode_group == "sleep"
    unresolved_mode = mode_group is None
    return {
        "available": False,
        "score": None,
        "score_releasable": False,
        "score_title": (
            "Sleep Score"
            if sleep_mode
            else "Recovery Score"
            if not unresolved_mode
            else "รูปแบบการพักยังไม่ยืนยัน"
        ),
        "score_scope": (
            "ค่าประเมินการนอนจาก Sensor"
            if sleep_mode
            else "Recovery Score จากช่วงพักและข้อมูล Sensor"
            if not unresolved_mode
            else "เลือกว่าเป็น Overnight หรือ Nap & Refresh เพื่อแสดงผล"
        ),
        "level": "กำลังเตรียมผลสรุป",
        "level_key": "unavailable",
        "reason": (
            "ข้อมูลเดิมยังไม่ได้ระบุรูปแบบการพัก จึงพักการแสดงคะแนนไว้"
            if unresolved_mode
            else "ZEEP กำลังตรวจความครบถ้วนของข้อมูลเดิมก่อนแสดงคะแนน"
        ),
        "version": SLEEP_QUALITY_VERSION,
        "validation_status": "pending_current_pipeline_review",
        "clinical_validated": False,
        "legacy_result_hidden": True,
        "rest_mode_unresolved": unresolved_mode,
    }
