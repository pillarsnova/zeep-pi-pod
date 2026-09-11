"""Compatibility policy for displaying persisted historical quality scores."""

from __future__ import annotations

from typing import Any

from sleep_session_report import normalise_rest_mode
from sleep_system_policy import (
    NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS,
    NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
    PRE_CONTINUITY_SESSION_REPORT_VERSION,
    PRE_CONTINUITY_SLEEP_QUALITY_VERSION,
    PRE_RESTORE_SESSION_REPORT_VERSION,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_VERSION,
    is_approved_sleep_result_version,
    rest_mode_group,
)


def _stored_mode(final_summary: dict[str, Any], report: Any) -> str:
    value: Any = final_summary.get("rest_mode")
    if not value and isinstance(report, dict):
        report_mode = report.get("rest_mode") or {}
        if isinstance(report_mode, dict):
            value = (
                report_mode.get("group")
                or report_mode.get("requested")
                or report_mode.get("resolved")
            )
        else:
            value = report_mode
    return normalise_rest_mode(value or "auto")


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
    compatible_quality = _compatible_versioned_quality(report, quality)
    if compatible_quality is not None:
        return compatible_quality
    requested = _stored_mode(final_summary, report)
    mode_group = rest_mode_group(requested)
    approved_untouched_sleep = (
        mode_group == "sleep"
        and isinstance(quality, dict)
        and isinstance(report, dict)
        and is_approved_sleep_result_version(
            report.get("version"), quality.get("version")
        )
    )
    if approved_untouched_sleep:
        return {
            **quality,
            "compatible_untouched_sleep_result": True,
        }
    legacy_recovery = _preserved_legacy_recovery(
        final_summary,
        report,
        quality,
        mode_group,
    )
    if legacy_recovery is not None:
        return legacy_recovery
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
            else "คะแนนสนับสนุนการฟื้นตัวจาก Sensor"
            if not unresolved_mode
            else "ต้องยืนยันว่าเป็น Overnight หรือ Nap & Refresh ก่อน"
        ),
        "level": "รอตรวจคุณภาพข้อมูล",
        "level_key": "unavailable",
        "reason": (
            "Session เดิมไม่ได้บันทึกรูปแบบการพัก จึงไม่อนุมานจากเวลา"
            if unresolved_mode
            else "ผลเดิมยังไม่ผ่าน Gate ของรุ่นปัจจุบัน จึงไม่เผยแพร่คะแนน"
        ),
        "version": SLEEP_QUALITY_VERSION,
        "validation_status": "pending_current_pipeline_review",
        "clinical_validated": False,
        "legacy_result_hidden": True,
        "rest_mode_unresolved": unresolved_mode,
    }
