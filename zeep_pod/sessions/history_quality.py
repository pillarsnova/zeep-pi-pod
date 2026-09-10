"""Compatibility policy for displaying persisted historical quality scores."""

from __future__ import annotations

from typing import Any

from sleep_session_report import normalise_rest_mode
from sleep_system_policy import (
    NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS,
    NAP_RECOVERY_MINIMUM_SCORE_SECONDS,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_VERSION,
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


def released_historical_quality(
    final_summary: dict[str, Any],
    quality: Any,
) -> dict[str, Any]:
    """Return current quality or a narrowly preserved legacy Recovery score."""
    report = final_summary.get("session_report") or {}
    if (
        isinstance(quality, dict)
        and quality.get("version") == SLEEP_QUALITY_VERSION
        and isinstance(report, dict)
        and report.get("version") == SESSION_REPORT_VERSION
    ):
        return quality
    requested = _stored_mode(final_summary, report)
    duration = _recording_seconds(report)
    preserve_legacy_recovery = (
        rest_mode_group(requested) == "nap_recovery"
        and final_summary.get("target_duration_s") is None
        and duration is not None
        and NAP_RECOVERY_MINIMUM_SCORE_SECONDS
        <= duration
        <= NAP_RECOVERY_LEGACY_HARD_MAX_SECONDS
        and isinstance(quality, dict)
        and quality.get("score") is not None
    )
    if preserve_legacy_recovery:
        target_status = (
            "TARGET_UNKNOWN/extended"
            if duration > 45 * 60
            else "TARGET_UNKNOWN"
        )
        return {
            **quality,
            "legacy_score_preserved": True,
            "review_required": True,
            "target_status": target_status,
            "validation_status": "legacy_recovery_target_unknown_preserved",
            "preservation_reason": (
                "Session เดิมไม่มีเป้าหมาย 30/90 นาที; "
                "แสดงคะแนนเดิมโดยไม่เขียนทับ"
            ),
        }
    sleep_mode = requested in {"sleep", "overnight"}
    return {
        "available": False,
        "score": None,
        "score_releasable": False,
        "score_title": "Sleep Score" if sleep_mode else "Recovery Score",
        "score_scope": (
            "ค่าประเมินการนอนจาก Sensor"
            if sleep_mode
            else "คะแนนสนับสนุนการฟื้นตัวจาก Sensor"
        ),
        "level": "รอตรวจคุณภาพข้อมูล",
        "level_key": "unavailable",
        "reason": "ผลเดิมยังไม่ผ่าน Gate ของรุ่นปัจจุบัน จึงไม่เผยแพร่คะแนน",
        "version": SLEEP_QUALITY_VERSION,
        "validation_status": "pending_current_pipeline_review",
        "clinical_validated": False,
        "legacy_result_hidden": True,
    }
