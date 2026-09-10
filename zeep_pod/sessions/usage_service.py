"""Application-facing read service for ZEEP usage Session results."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from zeep_pod.sessions.history_service import HistoryWindow, SessionHistoryService
from zeep_pod.sessions.quality_publication import (
    public_quality_payload,
    public_result_data_quality,
)
from zeep_pod.sessions.report_publication import public_report_field
from zeep_pod.sessions.result_contract import build_result_contract

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


def _email_first_identity(session: Mapping[str, Any]) -> dict[str, Any]:
    email = str(session.get("email") or "").strip().casefold() or None
    account_key = str(session.get("account_key") or "").strip().casefold()
    return {
        "email": email,
        "display_name": session.get("display_name") or email,
        "canonical_identifier": email or account_key or None,
        "identity_type": "email" if email else "legacy_account_key",
    }


def _public_report_value(value: Any) -> Any:
    """Recursively reject raw, Profile and credential fields from old rows."""
    if isinstance(value, Mapping):
        return {
            str(key): _public_report_value(item)
            for key, item in value.items()
            if not _private_report_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [_public_report_value(item) for item in value]
    return value


def _public_policy_versions(value: Any) -> dict[str, str | None]:
    source = _mapping(value)
    allowed = {"evidence", "baseline", "transition", "g2_ontology", "terminal_wake"}
    return {
        key: source[key]
        for key in allowed
        if key in source and (source[key] is None or isinstance(source[key], str))
    }


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
    return (
        normalized in PRIVATE_REPORT_FIELDS
        or bool(segments & PRIVATE_REPORT_SEGMENTS)
        or compact in PRIVATE_REPORT_COMPACT_FIELDS
        or compact.startswith("raw")
        or compact.endswith(("apikey", "password", "privatekey", "secret", "token"))
    )


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
    released_score = _mapping(result.get("score"))
    canonical_mode = _mapping(result.get("mode"))
    available = released_score.get("available") is True
    if not available:
        for key in BLOCKED_QUALITY_FIELDS:
            public.pop(key, None)
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
    public["rest_mode"] = canonical_mode
    if released_score.get("available") is not True:
        reason = released_score.get("reason") or "คะแนนหลักของ Session นี้ยังไม่พร้อม"
        public["headline"] = "ยังสรุปคะแนนไม่ได้"
        public["insight"] = reason
        public["findings"] = []
        public.pop("environment_assessment", None)
        public["post_session_guidance"] = {
            "available": False,
            "reason": reason,
            "score_derived_claims_suppressed": True,
        }
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
        "user": _email_first_identity(session),
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
            item["report"]["restore_summary"] = _public_report_value(
                result["restore_summary"]
            )
        item["sleep_policy_versions"] = _public_policy_versions(
            session.get("sleep_policy_versions") or {}
        )
        item["sleep_estimator_versions"] = _public_estimator_versions(
            session.get("sleep_estimator_versions") or {}
        )
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

    @staticmethod
    def _list_contract(
        result: Mapping[str, Any],
        *,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        sessions = [
            _session_item(session, include_report=False)
            for session in result.get("sessions") or []
        ]
        total = int(result.get("total") or 0)
        return {
            "contract_version": USAGE_SESSION_CONTRACT_VERSION,
            "history_name": "usage_history",
            "items": sessions,
            "summary": result.get("summary") or {},
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
