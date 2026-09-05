"""Filtered, role-neutral read service for ZEEP Session history.

The service assigns a completed Session to the local calendar day on which it
ended.  That convention puts an Overnight result on the morning it is reviewed
and keeps same-day Nap & Refresh results on their natural day.  Authorization
remains at the FastAPI route boundary; this module only reads and shapes data.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import DatabaseManager


QualityRelease = Callable[[dict[str, Any], Any], dict[str, Any]]
HealthReference = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class HistoryWindow:
    """UTC query bounds plus the local values needed by the UI."""

    start_utc: str
    end_utc: str
    start_local: str
    end_local: str
    timezone_name: str

    def public_snapshot(self) -> dict[str, str]:
        return {
            "start_utc": self.start_utc,
            "end_utc": self.end_utc,
            "start_local": self.start_local,
            "end_local": self.end_local,
            "timezone": self.timezone_name,
            "day_assignment": "session_end_local_date",
        }


def _parse_day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} ต้องเป็น YYYY-MM-DD") from exc


def _parse_minute(value: str, field: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} ต้องเป็น HH:MM") from exc


def resolve_history_window(
    date_from: str | None,
    date_to: str | None,
    time_from: str = "00:00",
    time_to: str = "23:59",
    *,
    timezone_name: str = "Asia/Bangkok",
    maximum_days: int = 366,
) -> HistoryWindow | None:
    """Convert inclusive local minute filters into an exclusive UTC range.

    No dates means no range filter, preserving compatibility for API clients
    that request their latest Sessions.  The tablet always sends dates and
    therefore defaults to the current local day.
    """
    if not date_from and not date_to:
        return None
    first_day = _parse_day(date_from or str(date_to), "date_from")
    last_day = _parse_day(date_to or str(date_from), "date_to")
    first_time = _parse_minute(time_from, "time_from")
    last_time = _parse_minute(time_to, "time_to")
    try:
        local_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("ไม่รู้จัก Timezone ของตู้ ZEEP") from exc

    start = datetime.combine(first_day, first_time, local_zone)
    # Browser time inputs have minute precision. Add one minute so the chosen
    # ending minute is inclusive while the SQL bound stays safely exclusive.
    end = datetime.combine(last_day, last_time, local_zone) + timedelta(minutes=1)
    if end <= start:
        raise ValueError("ช่วงเวลาสิ้นสุดต้องอยู่หลังเวลาเริ่ม")
    if end - start > timedelta(days=maximum_days, minutes=1):
        raise ValueError(f"ช่วงเวลาต้องไม่เกิน {maximum_days} วัน")
    return HistoryWindow(
        start_utc=start.astimezone(timezone.utc).isoformat(),
        end_utc=end.astimezone(timezone.utc).isoformat(),
        start_local=start.isoformat(),
        end_local=end.isoformat(),
        timezone_name=timezone_name,
    )


def local_history_day(timezone_name: str = "Asia/Bangkok") -> str:
    """Return today's ISO date at the physical Pod location."""
    try:
        local_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("ไม่รู้จัก Timezone ของตู้ ZEEP") from exc
    return datetime.now(local_zone).date().isoformat()


def _identity(profile: dict[str, Any], account_key: str) -> dict[str, Any]:
    email = (
        profile.get("email")
        or profile.get("zeep_email")
        or (account_key if "@" in account_key else None)
    )
    return {
        "account_key": account_key,
        "email": email,
        "display_name": profile.get("display_name")
        or profile.get("username")
        or email
        or account_key,
    }


def _matches_identity(
    profile: dict[str, Any],
    account_key: str,
    query: str | None,
) -> bool:
    needle = str(query or "").strip().casefold()
    if not needle:
        return True
    fields = (
        account_key,
        profile.get("email"),
        profile.get("zeep_email"),
        profile.get("display_name"),
        profile.get("username"),
    )
    return any(needle in str(value or "").casefold() for value in fields)


class SessionHistoryService:
    """Read completed, data-backed Session summaries from SQLite."""

    def __init__(
        self,
        database: DatabaseManager,
        *,
        history_start_utc: str,
        report_version: str,
        release_quality: QualityRelease,
        health_reference: HealthReference,
    ) -> None:
        self.database = database
        self.history_start_utc = history_start_utc
        self.report_version = report_version
        self.release_quality = release_quality
        self.health_reference = health_reference

    def _records(
        self,
        account_keys: Iterable[str] | None,
        window: HistoryWindow | None,
    ) -> list[dict[str, Any]]:
        clauses = [
            "s.start_time>=?",
            "s.end_time IS NOT NULL",
            "EXISTS (SELECT 1 FROM timeline AS visible_timeline "
            "WHERE visible_timeline.session_id=s.session_id)",
        ]
        params: list[Any] = [self.history_start_utc]
        keys = [str(key).strip().casefold() for key in account_keys or [] if key]
        if account_keys is not None:
            if not keys:
                return []
            placeholders = ",".join("?" for _ in keys)
            clauses.append(f"s.username_key IN ({placeholders})")
            params.extend(keys)
        if window is not None:
            clauses.extend(("s.end_time>=?", "s.end_time<?"))
            params.extend((window.start_utc, window.end_utc))
        sql = f"""
            SELECT s.*,
                (SELECT COUNT(*) FROM timeline AS aggregate_timeline
                 WHERE aggregate_timeline.session_id=s.session_id) AS sample_count,
                (SELECT AVG(temperature) FROM timeline AS temperature_timeline
                 WHERE temperature_timeline.session_id=s.session_id) AS avg_temperature,
                (SELECT AVG(heart_rate) FROM timeline AS heart_timeline
                 WHERE heart_timeline.session_id=s.session_id) AS avg_heart_rate,
                (SELECT value FROM events AS summary_event
                 WHERE summary_event.session_id=s.session_id
                   AND summary_event.type='final_summary'
                 ORDER BY summary_event.timestamp DESC LIMIT 1) AS final_summary_json
            FROM sessions AS s
            WHERE {' AND '.join(clauses)}
            ORDER BY s.end_time DESC, s.start_time DESC
        """
        return self.database.read_sessions(sql, tuple(params))

    def _serialize(
        self,
        record: dict[str, Any],
        profile: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            final_summary = json.loads(record.get("final_summary_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            final_summary = {}
        if not isinstance(final_summary, dict):
            final_summary = {}
        night_summary = final_summary.get("night_summary") or {}
        quality = self.release_quality(
            final_summary,
            night_summary.get("sleep_quality"),
        )
        report = final_summary.get("session_report")
        if not (
            isinstance(report, dict)
            and report.get("version") == self.report_version
        ):
            report = None
        account_key = str(record.get("username_key") or "").strip().casefold()
        identity = _identity(profile, account_key)
        temperature = record.get("avg_temperature")
        heart_rate = record.get("avg_heart_rate")
        return {
            "session_id": record.get("session_id"),
            "username": record.get("user"),
            **identity,
            "gender": record.get("gender"),
            "started_at_utc": record.get("start_time"),
            "ended_at_utc": record.get("end_time"),
            "duration_s": record.get("duration"),
            "end_reason": record.get("end_reason"),
            "sample_count": int(record.get("sample_count") or 0),
            "sleep_estimator": final_summary.get("sleep_estimator"),
            "sleep_estimator_versions": final_summary.get(
                "sleep_estimator_versions"
            ) or {},
            "sleep_provenance_complete": final_summary.get(
                "sleep_provenance_complete"
            ),
            "sleep_policy_versions": {
                "evidence": final_summary.get("sleep_evidence_version"),
                "baseline": final_summary.get("sleep_baseline_version"),
                "transition": final_summary.get("sleep_transition_policy"),
                "g2_ontology": final_summary.get("sleep_g2_ontology"),
                "terminal_wake": final_summary.get("terminal_wake_policy"),
            },
            "sleep_quality": quality,
            "session_report": report,
            "health_reference": (
                final_summary.get("health_reference")
                if isinstance(final_summary.get("health_reference"), dict)
                else self.health_reference(profile)
            ),
            "wellness_context_available": bool(
                final_summary.get("wellness_context")
            ),
            "summary": {
                "temperature_c": (
                    {"avg": round(float(temperature), 1)}
                    if temperature is not None else None
                ),
                "heart_rate_bpm": (
                    {"avg": round(float(heart_rate), 1)}
                    if heart_rate is not None else None
                ),
            },
        }

    @staticmethod
    def _summary(sessions: list[dict[str, Any]]) -> dict[str, Any]:
        people = {
            session.get("account_key") for session in sessions
            if session.get("account_key")
        }
        sleep_scores: list[float] = []
        recovery_scores: list[float] = []
        awaiting_score = 0
        for session in sessions:
            quality = session.get("sleep_quality") or {}
            if not quality.get("available") or quality.get("score") is None:
                awaiting_score += 1
                continue
            score = float(quality["score"])
            if quality.get("quality_type") == "rest_goal":
                recovery_scores.append(score)
            else:
                sleep_scores.append(score)
        return {
            "people_count": len(people),
            "session_count": len(sessions),
            "sleep_score_count": len(sleep_scores),
            "recovery_score_count": len(recovery_scores),
            "awaiting_score_count": awaiting_score,
            "average_sleep_score": (
                round(sum(sleep_scores) / len(sleep_scores), 1)
                if sleep_scores else None
            ),
            "average_recovery_score": (
                round(sum(recovery_scores) / len(recovery_scores), 1)
                if recovery_scores else None
            ),
        }

    @staticmethod
    def _participants(
        sessions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
        for session in sessions:
            key = str(session.get("account_key") or "")
            participant = grouped.setdefault(key, {
                "account_key": key,
                "email": session.get("email"),
                "display_name": session.get("display_name"),
                "session_count": 0,
                "scores": [],
            })
            participant["session_count"] += 1
            quality = session.get("sleep_quality") or {}
            participant["scores"].append({
                "session_id": session.get("session_id"),
                "ended_at_utc": session.get("ended_at_utc"),
                "score": quality.get("score")
                if quality.get("available") else None,
                "score_title": quality.get("score_title") or (
                    "Recovery Score"
                    if quality.get("quality_type") == "rest_goal"
                    else "Sleep Score"
                ),
                "level": quality.get("level") or "ข้อมูลไม่พอ",
                "available": bool(quality.get("available")),
            })
        return list(grouped.values())

    def account_history(
        self,
        account_key: str,
        profile: dict[str, Any],
        *,
        window: HistoryWindow | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        key = str(account_key or "").strip().casefold()
        all_sessions = [
            self._serialize(record, profile)
            for record in self._records([key], window)
        ]
        sessions = all_sessions[: max(1, min(500, int(limit)))]
        return {
            **_identity(profile, key),
            "health_reference": self.health_reference(profile),
            "sessions": sessions,
            "participants": self._participants(all_sessions),
            "summary": self._summary(all_sessions),
            "total": len(all_sessions),
            "range": window.public_snapshot() if window else None,
            "history_start_utc": self.history_start_utc,
            "older_sessions_archived_from_product_results": True,
        }

    def admin_history(
        self,
        profiles: dict[str, dict[str, Any]],
        *,
        window: HistoryWindow,
        account_key: str | None = None,
        query: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        requested_key = str(account_key or "").strip().casefold()
        keys = [requested_key] if requested_key else None
        records = self._records(keys, window)
        sessions: list[dict[str, Any]] = []
        for record in records:
            key = str(record.get("username_key") or "").strip().casefold()
            profile = dict(profiles.get(key) or {})
            profile.setdefault("username", record.get("user"))
            if not _matches_identity(profile, key, query):
                continue
            sessions.append(self._serialize(record, profile))
        total = len(sessions)
        visible_sessions = sessions[: max(1, min(1000, int(limit)))]
        return {
            "sessions": visible_sessions,
            "participants": self._participants(sessions),
            "summary": self._summary(sessions),
            "total": total,
            "range": window.public_snapshot(),
            "history_start_utc": self.history_start_utc,
            "older_sessions_archived_from_product_results": True,
        }
