"""Read-only rules for user-visible Session history.

The profile file stores identity and cached lifetime metadata.  SQLite remains
the source of truth for which completed Sessions actually contain Sensor data
and can therefore be opened from the current history view.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from zeep_pod.identity.account_aliases import account_boundary_keys

SessionReader = Callable[[str, tuple[Any, ...]], list[dict[str, Any]]]
ProgressSummary = Callable[[dict[str, Any]], dict[str, Any]]

USER_HISTORY_FILTER = """
    lower(trim(s.username_key))=?
    AND s.start_time>=?
    AND s.end_time IS NOT NULL
    AND EXISTS (
        SELECT 1 FROM timeline AS history_timeline
        WHERE history_timeline.session_id=s.session_id
    )
"""

SESSION_AVAILABILITY_SQL = """
    SELECT
        lower(trim(s.username_key)) AS username_key,
        SUM(CASE WHEN s.end_time IS NOT NULL AND EXISTS (
            SELECT 1 FROM timeline AS lifetime_timeline
            WHERE lifetime_timeline.session_id=s.session_id
        ) THEN 1 ELSE 0 END) AS lifetime_sessions,
        SUM(CASE WHEN s.end_time IS NOT NULL AND s.start_time>=? AND EXISTS (
            SELECT 1 FROM timeline AS available_timeline
            WHERE available_timeline.session_id=s.session_id
        ) THEN 1 ELSE 0 END) AS available_sessions,
        SUM(CASE WHEN s.end_time IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM timeline AS missing_timeline
            WHERE missing_timeline.session_id=s.session_id
        ) THEN 1 ELSE 0 END) AS sessions_without_data,
        SUM(CASE WHEN s.end_time IS NOT NULL AND s.start_time>=? AND NOT EXISTS (
            SELECT 1 FROM timeline AS current_missing_timeline
            WHERE current_missing_timeline.session_id=s.session_id
        ) THEN 1 ELSE 0 END) AS current_sessions_without_data,
        MAX(CASE WHEN s.end_time IS NOT NULL AND s.start_time>=? AND EXISTS (
            SELECT 1 FROM timeline AS recent_timeline
            WHERE recent_timeline.session_id=s.session_id
        ) THEN s.end_time ELSE NULL END) AS last_available_session_utc,
        MAX(CASE WHEN s.end_time IS NOT NULL AND s.start_time>=?
            THEN s.end_time ELSE NULL END) AS last_available_usage_session_utc,
        MAX(CASE WHEN s.end_time IS NOT NULL AND EXISTS (
            SELECT 1 FROM timeline AS latest_timeline
            WHERE latest_timeline.session_id=s.session_id
        ) THEN s.end_time ELSE NULL END) AS last_data_session_utc
    FROM sessions AS s
    GROUP BY lower(trim(s.username_key))
"""


def session_availability_by_account(
    read_sessions: SessionReader,
    history_start_utc: str,
) -> dict[str, dict[str, Any]]:
    """Return current and lifetime data-backed counts per canonical account.

    ``available_sessions`` matches the User History query exactly: completed,
    within the current product cutover and containing at least one Timeline
    row.  Older data-backed Sessions remain discoverable to Admin tooling as
    ``archived_sessions`` but must not inflate the number beside a user whose
    current History page is empty.
    """
    rows = read_sessions(
        SESSION_AVAILABILITY_SQL,
        (
            history_start_utc,
            history_start_utc,
            history_start_utc,
            history_start_utc,
        ),
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("username_key") or "").strip().casefold()
        if not key:
            continue
        lifetime = int(row.get("lifetime_sessions") or 0)
        available = int(row.get("available_sessions") or 0)
        without_data = int(row.get("sessions_without_data") or 0)
        current_without_data = int(
            row.get("current_sessions_without_data") or 0
        )
        result[key] = {
            "available_sessions": available,
            "lifetime_sessions": lifetime,
            "archived_sessions": max(0, lifetime - available),
            "sessions_without_data": without_data,
            "current_sessions_without_data": current_without_data,
            "completed_sessions": lifetime + without_data,
            "available_usage_sessions": available + current_without_data,
            "last_available_session_utc": row.get("last_available_session_utc"),
            "last_available_usage_session_utc": row.get(
                "last_available_usage_session_utc"
            ),
            "last_data_session_utc": row.get("last_data_session_utc"),
        }
    return result


def apply_session_availability(
    profile: dict[str, Any],
    availability: dict[str, Any] | None,
) -> dict[str, Any]:
    """Overlay derived counts without mutating the persisted Profile."""
    result = dict(profile)
    if availability is None:
        result.setdefault("available_sessions", int(result.get("sessions") or 0))
        result.setdefault("lifetime_sessions", int(result.get("sessions") or 0))
        result.setdefault("archived_sessions", 0)
        result.setdefault("sessions_without_data", 0)
        result.setdefault("current_sessions_without_data", 0)
        result.setdefault(
            "completed_sessions",
            int(result.get("lifetime_sessions") or 0)
            + int(result.get("sessions_without_data") or 0),
        )
        result.setdefault(
            "available_usage_sessions",
            int(result.get("available_sessions") or 0)
            + int(result.get("current_sessions_without_data") or 0),
        )
        return result
    available = int(availability.get("available_sessions") or 0)
    result["sessions"] = available
    result["available_sessions"] = available
    result["lifetime_sessions"] = int(availability.get("lifetime_sessions") or 0)
    result["archived_sessions"] = int(availability.get("archived_sessions") or 0)
    result["sessions_without_data"] = int(
        availability.get("sessions_without_data") or 0
    )
    result["current_sessions_without_data"] = int(
        availability.get("current_sessions_without_data") or 0
    )
    result["completed_sessions"] = int(
        availability.get("completed_sessions")
        or result["lifetime_sessions"] + result["sessions_without_data"]
    )
    result["available_usage_sessions"] = int(
        availability.get("available_usage_sessions")
        or available + result["current_sessions_without_data"]
    )
    result["last_available_session_utc"] = availability.get(
        "last_available_session_utc"
    )
    result["last_available_usage_session_utc"] = availability.get(
        "last_available_usage_session_utc"
    )
    result["last_data_session_utc"] = availability.get("last_data_session_utc")
    return result


def _combined_session_availability(
    account_key: str,
    profile: dict[str, Any],
    profiles: dict[str, Any],
    availability_by_account: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Fold canonical and ownership-verified legacy rows into one usage total."""
    rows = [
        availability_by_account.get(key) or {}
        for key in account_boundary_keys(account_key, profile, profiles)
    ]
    count_fields = (
        "available_sessions",
        "lifetime_sessions",
        "sessions_without_data",
        "current_sessions_without_data",
    )
    merged = {
        field: sum(int(row.get(field) or 0) for row in rows)
        for field in count_fields
    }
    merged["archived_sessions"] = max(
        0,
        merged["lifetime_sessions"] - merged["available_sessions"],
    )
    merged["completed_sessions"] = (
        merged["lifetime_sessions"] + merged["sessions_without_data"]
    )
    merged["available_usage_sessions"] = (
        merged["available_sessions"]
        + merged["current_sessions_without_data"]
    )
    for field in (
        "last_available_session_utc",
        "last_available_usage_session_utc",
        "last_data_session_utc",
    ):
        values = [str(row.get(field) or "") for row in rows if row.get(field)]
        merged[field] = max(values, default=None)
    return merged


def _activity_epoch(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def users_ordered_by_latest_session(
    profiles: dict[str, Any],
    active_record: dict[str, Any] | None = None,
    availability_by_account: dict[str, dict[str, Any]] | None = None,
    *,
    progress_summary: ProgressSummary | None = None,
) -> list[dict[str, Any]]:
    """Build the Admin chooser from current, data-backed Session metadata."""
    active_record = active_record or {}
    active_key = str(active_record.get("username_key") or "").strip().casefold()
    users: list[dict[str, Any]] = []
    for stored_key, stored_profile in profiles.items():
        profile = dict(stored_profile or {})
        if progress_summary is not None:
            profile["progressive_profile_summary"] = progress_summary(profile)
        profile.pop("progressive_profile", None)
        account_key = (
            str(profile.get("account_key") or stored_key or profile.get("email") or "")
            .strip()
            .casefold()
        )
        profile = apply_session_availability(
            profile,
            _combined_session_availability(
                account_key,
                profile,
                profiles,
                availability_by_account,
            )
            if availability_by_account is not None
            else None,
        )
        is_active = bool(active_key and account_key == active_key)
        latest_utc = (
            (active_record.get("started_at_utc") or active_record.get("armed_at_utc"))
            if is_active
            else None
        )
        latest_utc = (
            latest_utc
            or profile.get("last_available_usage_session_utc")
            or profile.get("last_available_session_utc")
            or profile.get("last_session_utc")
        )
        profile["history_order_utc"] = latest_utc
        profile["has_active_session"] = is_active
        users.append(profile)

    users.sort(
        key=lambda profile: str(
            profile.get("display_name")
            or profile.get("username")
            or profile.get("email")
            or ""
        ).casefold()
    )
    users.sort(
        key=lambda profile: _activity_epoch(profile.get("history_order_utc")),
        reverse=True,
    )
    users.sort(
        key=lambda profile: bool(profile.get("has_active_session")),
        reverse=True,
    )
    return users
