"""Application-facing read service for ZEEP usage Session results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from progressive_profile import admin_progress_summary
from sessions import score_summary
from sessions.history_service import HistoryWindow, SessionHistoryService
from sessions.quality_publication import public_result_data_quality
from sessions.result_contract import build_result_contract
from sessions.usage_development import build_usage_development
from sessions.usage_presentation import build_usage_presentation
from sessions.usage_publication import (
    build_public_report,
    public_estimator_versions,
    public_policy_versions,
    public_report_value,
)
from sessions.user_learning_profile import build_user_learning_profile

USAGE_SESSION_CONTRACT_VERSION = "zeep.usage-session.v1"
USAGE_USER_DIRECTORY_CONTRACT_VERSION = "zeep.usage-user-directory.v1"


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

    def user_directory_for_admin(
        self,
        profiles: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """Return one compact current-history row per Profile for Admin.

        Session history remains the source of truth for usage counts. Profiles
        with no completed Session are retained so the roster also makes cold
        starts and unused accounts visible without exposing health answers.
        """
        result = self.history.admin_history(
            profiles,
            window=None,
            account_key=None,
            query=None,
            limit=1,
            offset=0,
        )
        users = {
            str(participant.get("account_key") or "").strip().casefold(): (
                self._user_directory_item(participant)
            )
            for participant in result.get("participants") or []
            if participant.get("account_key")
        }
        self._add_profiles_without_history(users, profiles)
        ordered = self._ordered_directory_users(users)
        return {
            "contract_version": USAGE_USER_DIRECTORY_CONTRACT_VERSION,
            "users": ordered,
            "summary": self._directory_summary(ordered),
            "history_start_utc": result.get("history_start_utc"),
        }

    @classmethod
    def _add_profiles_without_history(
        cls,
        users: dict[str, dict[str, Any]],
        profiles: Mapping[str, Mapping[str, Any]],
    ) -> None:
        for stored_key, stored_profile in profiles.items():
            profile = dict(stored_profile or {})
            key = (
                str(
                    profile.get("account_key")
                    or profile.get("email")
                    or profile.get("zeep_email")
                    or stored_key
                    or ""
                )
                .strip()
                .casefold()
            )
            if not key or key in users:
                continue
            email = (
                str(
                    profile.get("email")
                    or profile.get("zeep_email")
                    or (key if "@" in key else "")
                )
                .strip()
                .casefold()
                or None
            )
            users[key] = cls._user_directory_item(
                {
                    "account_key": key,
                    "email": email,
                    "display_name": (
                        profile.get("display_name")
                        or profile.get("username")
                        or email
                        or key
                    ),
                }
            )

    @staticmethod
    def _ordered_directory_users(
        users: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ordered = sorted(
            users.values(),
            key=lambda item: str(
                item["user"].get("display_name")
                or item["user"].get("canonical_identifier")
                or ""
            ).casefold(),
        )
        ordered.sort(
            key=lambda item: str(item.get("last_used_at_utc") or ""),
            reverse=True,
        )
        return ordered

    @staticmethod
    def _directory_summary(ordered: list[dict[str, Any]]) -> dict[str, int]:
        users_with_sessions = sum(item["usage_count"] > 0 for item in ordered)
        return {
            "user_count": len(ordered),
            "users_with_sessions": users_with_sessions,
            "users_without_sessions": len(ordered) - users_with_sessions,
            "usage_count": sum(item["usage_count"] for item in ordered),
            "overnight_count": sum(
                item["modes"]["sleep"]["session_count"] for item in ordered
            ),
            "nap_recovery_count": sum(
                item["modes"]["nap_recovery"]["session_count"] for item in ordered
            ),
            "unresolved_count": sum(
                item["modes"]["unknown"]["session_count"] for item in ordered
            ),
        }

    @staticmethod
    def _user_directory_item(participant: Mapping[str, Any]) -> dict[str, Any]:
        key = str(participant.get("account_key") or "").strip().casefold()
        email = str(participant.get("email") or "").strip().casefold() or None
        raw_modes = participant.get("modes")
        modes = raw_modes if isinstance(raw_modes, Mapping) else {}

        def mode_item(mode_key: str) -> dict[str, Any]:
            source = modes.get(mode_key)
            source = source if isinstance(source, Mapping) else {}
            return {
                "session_count": int(source.get("session_count") or 0),
                "scored_count": int(source.get("scored_count") or 0),
                "latest_score": source.get("latest_score"),
                "latest_score_at_utc": source.get("latest_score_at_utc"),
            }

        return {
            "user": {
                "email": email,
                "display_name": participant.get("display_name") or email or key,
                "canonical_identifier": email or key or None,
                "identity_type": "email" if email else "legacy_account_key",
            },
            "usage_count": int(
                participant.get("usage_count") or participant.get("session_count") or 0
            ),
            "total_duration_s": max(
                0.0,
                float(participant.get("total_duration_s") or 0.0),
            ),
            "last_used_at_utc": participant.get("last_used_at_utc"),
            "without_sensor_data_count": int(
                participant.get("without_sensor_data_count") or 0
            ),
            "without_score_count": int(participant.get("without_score_count") or 0),
            "modes": {
                "sleep": mode_item("sleep"),
                "nap_recovery": mode_item("nap_recovery"),
                "unknown": mode_item("unknown"),
            },
        }

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
