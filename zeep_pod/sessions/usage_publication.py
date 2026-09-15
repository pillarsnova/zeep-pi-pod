"""Privacy-safe publication helpers for the Usage Session API."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from zeep_pod.sessions.quality_publication import public_quality_payload
from zeep_pod.sessions.report_publication import public_report_field

PUBLIC_REPORT_FIELDS = (
    "available",
    "version",
    "product_positioning",
    "intended_use",
    "timeline_schema_version",
    "estimator_version",
    "headline",
    "insight",
    "reason",
    "quality",
    "rest_mode",
    "sleep",
    "stages",
    "environment",
    "environment_assessment",
    "findings",
    "post_session_guidance",
    "restore_summary",
    "respiratory_wellness",
    "data_quality",
    "disclaimer",
)
BLOCKED_QUALITY_FIELDS = {
    "architecture",
    "component_labels",
    "component_max_points",
    "component_order",
    "component_points",
    "continuity",
    "cycles",
    "environment_support",
    "insight",
    "level_key",
    "outcome_interpretation",
    "score_basis",
    "sleep_opportunity",
}
PRIVATE_REPORT_FIELDS = {
    "access_token",
    "answers",
    "api_key",
    "auth",
    "authorization",
    "bcg_base64",
    "cookie",
    "credential",
    "credentials",
    "health_reference",
    "id_token",
    "packet",
    "packets",
    "password",
    "profile",
    "questionnaire",
    "raw",
    "raw_bcg",
    "raw_samples",
    "refresh_token",
    "samples",
    "secret",
    "sensor_timeline",
    "session_token",
    "wellness_context",
}
PRIVATE_REPORT_SEGMENTS = {
    "answer",
    "answers",
    "auth",
    "authorization",
    "base64",
    "blob",
    "bytes",
    "birth",
    "cookie",
    "credential",
    "credentials",
    "email",
    "packet",
    "packets",
    "participant",
    "password",
    "profile",
    "phone",
    "questionnaire",
    "raw",
    "samples",
    "secret",
    "token",
    "user",
    "waveform",
}
PRIVATE_REPORT_COMPACT_FIELDS = {
    "bcgbase64",
    "healthreference",
    "rawbcg",
    "rawsamples",
    "sensortimeline",
    "wellnesscontext",
}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _private_report_key(key: Any) -> bool:
    """Return whether a field name may contain private or Raw data."""
    snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key))
    normalized = re.sub(
        r"[^a-z0-9]+",
        "_",
        snake_case.casefold(),
    ).strip("_")
    segments = set(normalized.split("_"))
    compact = normalized.replace("_", "")
    return bool(
        normalized in PRIVATE_REPORT_FIELDS
        or segments & PRIVATE_REPORT_SEGMENTS
        or compact in PRIVATE_REPORT_COMPACT_FIELDS
        or compact.startswith("raw")
        or compact.endswith(("apikey", "password", "privatekey", "secret", "token"))
    )


def public_report_value(value: Any) -> Any:
    """Recursively reject Raw, Profile and credential fields from old rows."""
    if isinstance(value, Mapping):
        return {
            str(key): public_report_value(item)
            for key, item in value.items()
            if not _private_report_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [public_report_value(item) for item in value]
    return value


def public_policy_versions(value: Any) -> dict[str, str | None]:
    """Publish only known version strings from the Sleep policy snapshot."""
    source = _mapping(value)
    allowed = {
        "evidence",
        "baseline",
        "transition",
        "g2_ontology",
        "terminal_wake",
    }
    return {
        key: source[key]
        for key in allowed
        if key in source and (source[key] is None or isinstance(source[key], str))
    }


def public_estimator_versions(value: Any) -> dict[str, int]:
    """Publish valid estimator-version counters without private field names."""
    source = _mapping(value)
    public: dict[str, int] = {}
    for raw_key, count in source.items():
        key = str(raw_key)
        if _private_report_key(key):
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", key) is None:
            continue
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            continue
        public[key] = count
    return public


def _safety_only_environment_support(value: Any) -> dict[str, Any] | None:
    """Retain score-independent Safety provenance when score release is off."""
    source = _mapping(value)
    excursions = [
        dict(item)
        for item in source.get("safety_excursions") or []
        if isinstance(item, Mapping)
    ]
    metrics = [
        dict(item)
        for item in source.get("metrics") or []
        if isinstance(item, Mapping) and item.get("safety_excursion_observed") is True
    ]
    observed = bool(
        source.get("safety_excursion_observed")
        or source.get("safety_review_required")
        or excursions
        or metrics
    )
    if not observed:
        return None
    return {
        "safety_excursion_observed": True,
        "safety_review_required": True,
        "safety_excursions_change_score": False,
        "sleep_stage_context_only": True,
        "metrics": metrics,
        "safety_excursions": excursions,
    }


def _safety_only_environment_assessment(value: Any) -> dict[str, Any] | None:
    """Publish only Safety facts, never unavailable score-derived appraisal."""
    source = _mapping(value)
    excursions = [
        dict(item)
        for item in source.get("safety_excursions") or []
        if isinstance(item, Mapping)
    ]
    observed = bool(
        source.get("safety_excursion_observed")
        or source.get("safety_review_required")
        or excursions
    )
    if not observed:
        return None
    return {
        "safety_excursion_observed": True,
        "safety_review_required": True,
        "safety_excursion_count": int(
            source.get("safety_excursion_count") or len(excursions)
        ),
        "safety_excursions": excursions,
        "safety_excursions_change_sustained_assessment": False,
        "safety_excursions_change_score": False,
        "safety_thresholds_unchanged": True,
    }


def _safety_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        dict(item)
        for item in value
        if isinstance(item, Mapping) and item.get("decision") == "safety_review"
    ]


def _canonical_guidance(
    result: Mapping[str, Any],
    *,
    score_available: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    summary = _mapping(result.get("restore_summary"))
    recommendation = _mapping(summary.get("recommendation"))
    attention = _mapping(summary.get("drivers")).get("attention") or []
    has_safety_review = any(
        isinstance(item, Mapping) and item.get("priority") == "safety_review"
        for item in attention
    )
    public = {
        "available": score_available,
        "mode": _mapping(result.get("mode")).get("key"),
        "score_used": (
            _mapping(result.get("score")).get("value") if score_available else None
        ),
        "score_released": score_available,
        "basis": "zeep_restore_summary",
        "medical_diagnosis": False,
    }
    if score_available or has_safety_review:
        public["primary"] = recommendation.get("primary") or (
            "ดูผลสรุปครั้งนี้ แล้วเลือกหนึ่งสิ่งที่อยากปรับในครั้งถัดไป"
        )
    else:
        public["reason"] = reason
    if not score_available:
        public["score_derived_claims_suppressed"] = True
    return public


def _public_quality(
    source: Any,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the explicit application-safe Quality DTO."""
    if not isinstance(source, Mapping):
        return {}
    public = public_quality_payload(source)
    safety_support = _safety_only_environment_support(public.get("environment_support"))
    for key in ("insight", "outcome_interpretation", "score_scope"):
        public.pop(key, None)
    released_score = _mapping(result.get("score"))
    canonical_mode = _mapping(result.get("mode"))
    restore_status = _mapping(_mapping(result.get("restore_summary")).get("status"))
    available = released_score.get("available") is True
    if not available:
        for key in BLOCKED_QUALITY_FIELDS:
            public.pop(key, None)
        if safety_support is not None:
            public["environment_support"] = safety_support
    public.update(
        {
            "available": available,
            "score": released_score.get("value") if available else None,
            "score_title": released_score.get("title"),
            "formula_version": released_score.get("formula_version"),
            "validation_status": released_score.get("validation_status"),
            "clinical_validated": (released_score.get("clinical_validated") is True),
            "level": released_score.get("level"),
            "reason": released_score.get("reason"),
            "quality_type": (
                "sleep"
                if canonical_mode.get("key") == "sleep"
                else "rest_goal"
                if canonical_mode.get("key") == "nap_recovery"
                else None
            ),
            "rest_mode": canonical_mode,
        }
    )
    if restore_status.get("key") == "safety_review":
        public["safety_review_required"] = True
    return public


def build_public_report(
    source: Any,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the report subset safe for application clients."""
    if not isinstance(source, Mapping):
        return {}
    public: dict[str, Any] = {}
    for key in PUBLIC_REPORT_FIELDS:
        if key not in source:
            continue
        if key == "quality":
            public[key] = _public_quality(source[key], result)
        elif key == "rest_mode":
            public[key] = public_report_value(result.get("mode") or {})
        elif key == "restore_summary":
            public[key] = public_report_value(result.get("restore_summary") or {})
        else:
            public[key] = public_report_field(key, source[key])
    canonical_mode = _mapping(result.get("mode"))
    released_score = _mapping(result.get("score"))
    restore_status = _mapping(_mapping(result.get("restore_summary")).get("status"))
    if released_score.get("available") is True:
        public["headline"] = (
            restore_status.get("label")
            or released_score.get("level")
            or "ผลสรุปการพักครั้งนี้"
        )
        public["insight"] = restore_status.get("meaning") or (
            "ภาพรวมจากข้อมูลที่ ZEEP บันทึกได้ใน Session นี้"
        )
        public.pop("reason", None)
        public["post_session_guidance"] = _canonical_guidance(
            result,
            score_available=True,
        )
    public["rest_mode"] = canonical_mode
    if released_score.get("available") is not True:
        reason = released_score.get("reason") or (
            "ZEEP กำลังรวบรวมข้อมูลสำหรับสรุปคะแนนของการพักครั้งนี้"
        )
        public["headline"] = (
            "ครั้งนี้ยังไม่มีคะแนน"
            if result.get("session_closed") is True
            else "กำลังเตรียมผลสรุป"
        )
        public["insight"] = reason
        public["reason"] = reason
        public["findings"] = _safety_findings(public.get("findings"))
        safety_assessment = _safety_only_environment_assessment(
            public.get("environment_assessment")
        )
        if safety_assessment is None:
            public.pop("environment_assessment", None)
        else:
            public["environment_assessment"] = safety_assessment
        public["post_session_guidance"] = _canonical_guidance(
            result,
            score_available=False,
            reason=reason,
        )
    return public
