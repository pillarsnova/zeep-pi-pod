"""Admin-only aggregate diagnostics for one finalized Usage Session."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zeep_pod.sessions.usage_presentation import build_usage_presentation

DEVELOPMENT_CONTRACT_VERSION = "zeep.usage-development.v1"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _score_components(report: Mapping[str, Any]) -> dict[str, Any]:
    quality = _mapping(report.get("quality"))
    points = {
        str(key): float(value)
        for key, value in _mapping(quality.get("component_points")).items()
        if _number(value) is not None
    }
    maxima = {
        str(key): float(value)
        for key, value in _mapping(quality.get("component_max_points")).items()
        if _number(value) is not None
    }
    labels = {
        str(key): str(value)
        for key, value in _mapping(quality.get("component_labels")).items()
        if value is not None
    }
    order = [
        str(key)
        for key in quality.get("component_order") or []
        if str(key) in points or str(key) in maxima
    ]
    if not order:
        order = list(dict.fromkeys((*points, *maxima)))
    return {
        "order": order,
        "labels": labels,
        "earned_points": points,
        "max_points": maxima,
    }


def _review_flags(detail: Mapping[str, Any]) -> list[dict[str, str]]:
    mode = _mapping(detail.get("mode"))
    score = _mapping(detail.get("score"))
    summary = _mapping(detail.get("restore_summary"))
    report = _mapping(detail.get("report"))
    sleep = _mapping(report.get("sleep"))
    accounting = _mapping(sleep.get("classification_accounting"))
    assessment = _mapping(report.get("environment_assessment"))
    quality = _mapping(detail.get("data_quality"))
    flags = []
    if mode.get("review_required"):
        flags.append(
            (
                "mode_review_required",
                "review",
                "ตรวจสอบรูปแบบการพักและเป้าหมายเวลา",
            )
        )
    if detail.get("session_closed") is not True:
        flags.append(
            (
                "session_not_closed",
                "review",
                "Session ยังไม่จบ จึงยังไม่เผยแพร่คะแนน",
            )
        )
    elif score.get("available") is not True:
        flags.append(
            (
                "score_unavailable",
                "review",
                str(score.get("reason") or "คะแนนยังไม่พร้อมเผยแพร่"),
            )
        )
    invariant = _mapping(accounting.get("arithmetic_invariant"))
    if accounting and invariant.get("holds") is False:
        flags.append(
            (
                "classification_accounting_failed",
                "review",
                "บัญชีเวลาไม่ผ่าน invariant",
            )
        )
    if assessment.get("safety_review_required") is True:
        flags.append(
            (
                "environment_safety_review",
                "safety_review",
                "ตรวจเหตุการณ์สภาพแวดล้อมที่แตะเกณฑ์ Safety",
            )
        )
    if quality.get("level") == "low":
        flags.append(
            (
                "data_quality_low",
                "info",
                "ข้อมูลครั้งนี้มีความครอบคลุมจำกัด",
            )
        )
    baseline = _mapping(summary.get("personal_baseline"))
    comparison = _mapping(baseline.get("comparison"))
    if comparison.get("available") is not True:
        flags.append(
            (
                "personal_baseline_learning",
                "info",
                "Personal Baseline ยังอยู่ระหว่างเรียนรู้",
            )
        )
    subjective = _mapping(summary.get("subjective_outcome"))
    if subjective.get("status") != "measured":
        flags.append(
            (
                "subjective_outcome_not_measured",
                "info",
                "ยังไม่มีแบบประเมินความรู้สึกก่อน–หลัง",
            )
        )
    return [
        {"code": code, "severity": severity, "message": message}
        for code, severity, message in flags
    ]


def build_usage_development(detail: Mapping[str, Any]) -> dict[str, Any]:
    """Create an aggregate QA view; Raw Sensor data remains on separate routes."""
    report = _mapping(detail.get("report"))
    score = _mapping(detail.get("score"))
    sleep = _mapping(report.get("sleep"))
    user_summary = build_usage_presentation(detail)
    score_available = bool(
        _mapping(user_summary.get("primary_result")).get("available")
    )
    return {
        "contract_version": DEVELOPMENT_CONTRACT_VERSION,
        "audience": "admin_development",
        "session_id": str(detail.get("session_id") or ""),
        "user": detail.get("user") or {},
        "user_summary": user_summary,
        "score_release": {
            "score_available": score_available,
            "validation_status": score.get("validation_status"),
            "review_required": bool(score.get("review_required")),
            "formula_version": score.get("formula_version"),
            "quality_model_version": score.get("quality_model_version"),
        },
        "data_quality": detail.get("data_quality") or {},
        "score_components": _score_components(report),
        "classification_accounting": sleep.get("classification_accounting"),
        "environment_assessment": report.get("environment_assessment"),
        "environment_metrics": report.get("environment") or [],
        "respiratory_wellness": report.get("respiratory_wellness"),
        "versions": detail.get("versions") or {},
        "sleep_policy_versions": detail.get("sleep_policy_versions") or {},
        "sleep_estimator_versions": detail.get("sleep_estimator_versions") or {},
        "result_provenance": detail.get("result_provenance") or {},
        "review_flags": _review_flags(detail),
        "raw_data_included": False,
    }
