"""Application-facing read service for ZEEP usage Session results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from progressive_profile import admin_progress_summary
from zeep_pod.sessions import score_summary
from zeep_pod.sessions.history_service import HistoryWindow, SessionHistoryService
from zeep_pod.sessions.quality_publication import public_result_data_quality
from zeep_pod.sessions.result_contract import build_result_contract
from zeep_pod.sessions.usage_development import build_usage_development
from zeep_pod.sessions.usage_presentation import build_usage_presentation
from zeep_pod.sessions.usage_publication import (
    build_public_report,
    public_estimator_versions,
    public_policy_versions,
    public_report_value,
)
from zeep_pod.sessions.user_learning_profile import build_user_learning_profile

USAGE_SESSION_CONTRACT_VERSION = "zeep.usage-session.v1"


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
        "mode": public_report_value(result["mode"]),
        "score": public_report_value(result["score"]),
        "restore_summary": public_report_value(result["restore_summary"]),
        "data_quality": public_result_data_quality(result["data_quality"]),
        "versions": public_report_value(result["versions"]),
        "result_provenance": public_report_value(result["provenance"]),
        "session_closed": result["session_closed"],
        "score_revision_policy": result["score_revision_policy"],
    }
    if include_report:
        item["report"] = build_public_report(
            session.get("session_report"),
            result,
        )
        if "restore_summary" in item["report"]:
            item["report"]["restore_summary"] = public_report_value(
                result["restore_summary"]
            )
        item["sleep_policy_versions"] = public_policy_versions(
            session.get("sleep_policy_versions") or {}
        )
        item["sleep_estimator_versions"] = public_estimator_versions(
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

    def learning_profile(
        self,
        account_key: str,
        profile: dict[str, Any],
        *,
        baseline: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Combine all completed Sessions into one longitudinal profile."""
        key = str(account_key or "").strip().casefold()
        rows = self.history.account_completed_sessions(key, profile)
        sessions = [_session_item(row, include_report=False) for row in rows]
        return build_user_learning_profile(
            account_key=key,
            profile=profile,
            sessions=sessions,
            baseline=baseline,
            questionnaire=admin_progress_summary(profile),
            history_start_utc=self.history.history_start_utc,
        )

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
