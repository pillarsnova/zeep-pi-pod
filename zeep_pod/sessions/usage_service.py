"""Application-facing read service for ZEEP usage Session results."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from zeep_pod.sessions import score_summary
from zeep_pod.sessions.history_service import HistoryWindow, SessionHistoryService
from zeep_pod.sessions.quality_publication import (
    public_quality_payload,
    public_result_data_quality,
)
from zeep_pod.sessions.report_publication import public_report_field
from zeep_pod.sessions.result_contract import build_result_contract
from zeep_pod.sessions.usage_development import build_usage_development
from zeep_pod.sessions.usage_presentation import build_usage_presentation

USAGE_SESSION_CONTRACT_VERSION = "zeep.usage-session.v1"
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


def _public_report_value(value: Any) -> Any:
    """Recursively reject raw, Profile and credential fields from old rows."""
    if isinstance(value, Mapping):
        return {str(key): _public_report_value(item) for key, item in value.items() if not _private_report_key(key)}
    if isinstance(value, (list, tuple)):
        return [_public_report_value(item) for item in value]
    return value


def _public_policy_versions(value: Any) -> dict[str, str | None]:
    source = _mapping(value)
    allowed = {"evidence", "baseline", "transition", "g2_ontology", "terminal_wake"}
    return {key: source[key] for key in allowed if key in source and (source[key] is None or isinstance(source[key], str))}


def _public_estimator_versions(value: Any) -> dict[str, int]:
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


def _private_report_key(key: Any) -> bool:
    # Normalize both snake_case and camelCase before applying the deny layer.
    # A compact comparison also catches initialisms such as ``BCGBase64``.
    snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key))
    normalized = re.sub(r"[^a-z0-9]+", "_", snake_case.casefold()).strip("_")
    segments = set(normalized.split("_"))
    compact = normalized.replace("_", "")
    return normalized in PRIVATE_REPORT_FIELDS or bool(segments & PRIVATE_REPORT_SEGMENTS) or compact in PRIVATE_REPORT_COMPACT_FIELDS or compact.startswith("raw") or compact.endswith(("apikey", "password", "privatekey", "secret", "token"))


def _safety_only_environment_support(value: Any) -> dict[str, Any] | None:
    """Retain score-independent Safety provenance when score release is off."""
    source = _mapping(value)
    excursions = [dict(item) for item in source.get("safety_excursions") or [] if isinstance(item, Mapping)]
    metrics = [dict(item) for item in source.get("metrics") or [] if isinstance(item, Mapping) and item.get("safety_excursion_observed") is True]
    observed = bool(source.get("safety_excursion_observed") or source.get("safety_review_required") or excursions or metrics)
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
    excursions = [dict(item) for item in source.get("safety_excursions") or [] if isinstance(item, Mapping)]
    if not (source.get("safety_excursion_observed") or source.get("safety_review_required") or excursions):
        return None
    return {
        "safety_excursion_observed": True,
        "safety_review_required": True,
        "safety_excursion_count": int(source.get("safety_excursion_count") or len(excursions)),
        "safety_excursions": excursions,
        "safety_excursions_change_sustained_assessment": False,
        "safety_excursions_change_score": False,
        "safety_thresholds_unchanged": True,
    }


def _safety_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping) and item.get("decision") == "safety_review"]


def _canonical_guidance(
    result: Mapping[str, Any],
    *,
    score_available: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    summary = _mapping(result.get("restore_summary"))
    recommendation = _mapping(summary.get("recommendation"))
    attention = _mapping(summary.get("drivers")).get("attention") or []
    has_safety_review = any(isinstance(item, Mapping) and item.get("priority") == "safety_review" for item in attention)
    public = {
        "available": score_available,
        "mode": _mapping(result.get("mode")).get("key"),
        "score_used": (_mapping(result.get("score")).get("value") if score_available else None),
        "score_released": score_available,
        "basis": "zeep_restore_summary",
        "medical_diagnosis": False,
    }
    if score_available or has_safety_review:
        public["primary"] = recommendation.get("primary") or ("ดูผลสรุปครั้งนี้ แล้วเลือกหนึ่งสิ่งที่อยากปรับในครั้งถัดไป")
    else:
        public["reason"] = reason
    if not score_available:
        public["score_derived_claims_suppressed"] = True
    return public


def _public_quality(
    source: Any,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the explicit application-safe Quality DTO.

    This is intentionally a positive allowlist.  Engineering-only fields such
    as ``engineering_shadow_score`` and ``score_unrounded`` therefore stay
    private even when a legacy record says the public score is unavailable.
    """
    if not isinstance(source, Mapping):
        return {}
    public = public_quality_payload(source)
    safety_support = _safety_only_environment_support(public.get("environment_support"))
    for key in ("insight", "outcome_interpretation", "score_scope"):
        public.pop(key, None)
    released_score = _mapping(result.get("score"))
    canonical_mode = _mapping(result.get("mode"))
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
            "clinical_validated": released_score.get("clinical_validated") is True,
            "level": released_score.get("level"),
            "reason": released_score.get("reason"),
            "quality_type": ("sleep" if canonical_mode.get("key") == "sleep" else "rest_goal" if canonical_mode.get("key") == "nap_recovery" else None),
            "rest_mode": canonical_mode,
        }
    )
    return public


def _public_report(
    source: Any,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(source, Mapping):
        return {}
    public: dict[str, Any] = {}
    for key in PUBLIC_REPORT_FIELDS:
        if key not in source:
            continue
        if key == "quality":
            public[key] = _public_quality(source[key], result)
        elif key == "rest_mode":
            public[key] = _public_report_value(result.get("mode") or {})
        elif key == "restore_summary":
            public[key] = _public_report_value(result.get("restore_summary") or {})
        else:
            public[key] = public_report_field(key, source[key])
    canonical_mode = _mapping(result.get("mode"))
    released_score = _mapping(result.get("score"))
    restore_status = _mapping(_mapping(result.get("restore_summary")).get("status"))
    if released_score.get("available") is True:
        public["headline"] = restore_status.get("label") or released_score.get("level") or "ผลสรุปการพักครั้งนี้"
        public["insight"] = restore_status.get("meaning") or "ภาพรวมจากข้อมูลที่ ZEEP บันทึกได้ใน Session นี้"
        public.pop("reason", None)
        public["post_session_guidance"] = _canonical_guidance(
            result,
            score_available=True,
        )
    public["rest_mode"] = canonical_mode
    if released_score.get("available") is not True:
        reason = released_score.get("reason") or ("ZEEP กำลังรวบรวมข้อมูลสำหรับสรุปคะแนนของการพักครั้งนี้")
        public["headline"] = "กำลังเตรียมผลสรุป"
        public["insight"] = reason
        public["reason"] = reason
        public["findings"] = _safety_findings(public.get("findings"))
        safety_assessment = _safety_only_environment_assessment(public.get("environment_assessment"))
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


def _session_item(
    session: Mapping[str, Any],
    *,
    include_report: bool,
) -> dict[str, Any]:
    result = build_result_contract(session)
    item = {
        "contract_version": USAGE_SESSION_CONTRACT_VERSION,
        "session_id": session.get("session_id"),
        "user": score_summary.email_first_identity(session),
        "started_at_utc": session.get("started_at_utc"),
        "ended_at_utc": session.get("ended_at_utc"),
        "duration_s": session.get("duration_s"),
        "end_reason": session.get("end_reason"),
        "sample_count": session.get("sample_count"),
        "mode": _public_report_value(result["mode"]),
        "score": _public_report_value(result["score"]),
        "restore_summary": _public_report_value(result["restore_summary"]),
        "data_quality": public_result_data_quality(result["data_quality"]),
        "versions": _public_report_value(result["versions"]),
        "result_provenance": _public_report_value(result["provenance"]),
        "session_closed": result["session_closed"],
        "score_revision_policy": result["score_revision_policy"],
    }
    if include_report:
        item["report"] = _public_report(
            session.get("session_report"),
            result,
        )
        if "restore_summary" in item["report"]:
            item["report"]["restore_summary"] = _public_report_value(result["restore_summary"])
        item["sleep_policy_versions"] = _public_policy_versions(session.get("sleep_policy_versions") or {})
        item["sleep_estimator_versions"] = _public_estimator_versions(session.get("sleep_estimator_versions") or {})
    return item


class UsageSessionService:
    """Shape history storage into a stable, raw-free integration contract."""

    def __init__(self, history: SessionHistoryService) -> None:
        self.history = history

    def list_for_account(
        self,
        account_key: str,
        profile: dict[str, Any],
        *,
        window: HistoryWindow | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        result = self.history.account_history(
            account_key,
            profile,
            window=window,
            limit=limit,
            offset=offset,
        )
        return self._list_contract(result, limit=limit, offset=offset)

    def list_for_admin(
        self,
        profiles: dict[str, dict[str, Any]],
        *,
        window: HistoryWindow | None,
        account_key: str | None,
        query: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        result = self.history.admin_history(
            profiles,
            window=window,
            account_key=account_key,
            query=query,
            limit=limit,
            offset=offset,
        )
        return self._list_contract(result, limit=limit, offset=offset)

    def summary_by_id(
        self,
        session_id: str,
        profiles: dict[str, dict[str, Any]],
        *,
        account_key: str | None,
    ) -> dict[str, Any] | None:
        session = self.history.session_by_id(
            session_id,
            profiles,
            account_key=account_key,
        )
        return _session_item(session, include_report=False) if session else None

    def detail_by_id(
        self,
        session_id: str,
        profiles: dict[str, dict[str, Any]],
        *,
        account_key: str | None,
    ) -> dict[str, Any] | None:
        session = self.history.session_by_id(
            session_id,
            profiles,
            account_key=account_key,
        )
        return _session_item(session, include_report=True) if session else None

    def presentation_by_id(
        self,
        session_id: str,
        profiles: dict[str, dict[str, Any]],
        *,
        account_key: str | None,
    ) -> dict[str, Any] | None:
        """Return one compact result with every display fact represented once."""
        detail = self.detail_by_id(
            session_id,
            profiles,
            account_key=account_key,
        )
        return build_usage_presentation(detail) if detail else None

    def development_by_id(
        self,
        session_id: str,
        profiles: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return aggregate Admin QA context without any Raw Sensor payload."""
        detail = self.detail_by_id(
            session_id,
            profiles,
            account_key=None,
        )
        return build_usage_development(detail) if detail else None

    @staticmethod
    def _list_contract(
        result: Mapping[str, Any],
        *,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        sessions = [_session_item(session, include_report=False) for session in result.get("sessions") or []]
        total = int(result.get("total") or 0)
        summary = (
            score_summary.usage_page_summary(sessions)
            if int(offset) == 0 and len(sessions) == total
            else score_summary.validated_range_summary(
                result.get("summary"),
                total=total,
                visible_items=sessions,
            )
        )
        return {
            "contract_version": USAGE_SESSION_CONTRACT_VERSION,
            "history_name": "usage_history",
            "items": sessions,
            "summary": summary,
            "pagination": {
                "limit": int(limit),
                "offset": int(offset),
                "returned": len(sessions),
                "total": total,
                "has_more": int(offset) + len(sessions) < total,
            },
            "range": result.get("range"),
            "history_start_utc": result.get("history_start_utc"),
        }
