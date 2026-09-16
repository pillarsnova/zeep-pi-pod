"""Canonical Sleep/Recovery aggregation for history and usage lists."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from common.mappings import as_mapping as _mapping
from sessions.result_contract import build_result_contract


def canonical_results(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_result_contract(session) for session in sessions]


def _score_buckets(
    results: list[dict[str, Any]],
) -> tuple[list[float], list[float], int]:
    sleep_scores: list[float] = []
    recovery_scores: list[float] = []
    awaiting = 0
    for result in results:
        score = _mapping(result.get("score"))
        value = score.get("value")
        if (
            score.get("available") is not True
            or isinstance(value, bool)
            or not isinstance(value, int | float)
        ):
            awaiting += 1
        elif score.get("type") == "sleep_score":
            sleep_scores.append(float(value))
        elif score.get("type") == "recovery_score":
            recovery_scores.append(float(value))
        else:
            awaiting += 1
    return sleep_scores, recovery_scores, awaiting


def _formula_safe_average(
    results: list[dict[str, Any]],
    score_type: str,
) -> float | None:
    """Average only a complete cohort with one verified score formula."""
    values: list[float] = []
    formula: str | None = None
    recovery_target: str | None = None
    for result in results:
        score = _mapping(result.get("score"))
        value = score.get("value")
        if score.get("available") is not True or score.get("type") != score_type:
            continue
        if isinstance(value, bool) or not isinstance(value, int | float):
            continue
        current_formula = str(score.get("formula_version") or "").strip()
        if not current_formula:
            return None
        if formula is not None and current_formula != formula:
            return None
        formula = current_formula
        if score_type == "recovery_score":
            target = _mapping(_mapping(result.get("mode")).get("target"))
            current_target = str(target.get("key") or "").strip().casefold()
            current_target = {
                "nap_30m": "nap_30",
                "nap_90m": "nap_90",
            }.get(current_target, current_target)
            if current_target not in {"nap_30", "nap_90"}:
                return None
            if recovery_target is not None and recovery_target != current_target:
                return None
            recovery_target = current_target
        values.append(float(value))
    return round(sum(values) / len(values), 1) if values else None


def _summary_payload(
    *,
    people_count: int,
    session_count: int,
    sleep_scores: list[float],
    recovery_scores: list[float],
    awaiting: int,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    assert len(sleep_scores) + len(recovery_scores) + awaiting == session_count
    return {
        "people_count": people_count,
        "session_count": session_count,
        "sleep_score_count": len(sleep_scores),
        "recovery_score_count": len(recovery_scores),
        "without_score_count": awaiting,
        "awaiting_score_count": awaiting,
        "average_sleep_score": _formula_safe_average(results, "sleep_score"),
        "average_recovery_score": _formula_safe_average(
            results,
            "recovery_score",
        ),
    }


def history_summary(
    sessions: list[dict[str, Any]],
    *,
    canonical: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    results = canonical if canonical is not None else canonical_results(sessions)
    if len(results) != len(sessions):
        raise ValueError("canonical result count must match Session count")
    sleep_scores, recovery_scores, awaiting = _score_buckets(results)
    people = {
        session.get("account_key") for session in sessions if session.get("account_key")
    }
    return _summary_payload(
        people_count=len(people),
        session_count=len(sessions),
        sleep_scores=sleep_scores,
        recovery_scores=recovery_scores,
        awaiting=awaiting,
        results=results,
    )


def history_participants(
    sessions: list[dict[str, Any]],
    *,
    canonical: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    results = canonical if canonical is not None else canonical_results(sessions)
    if len(results) != len(sessions):
        raise ValueError("canonical result count must match Session count")
    grouped: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for session, result in zip(sessions, results, strict=True):
        key = str(session.get("account_key") or "")
        participant = grouped.setdefault(
            key,
            {
                "account_key": key,
                "email": session.get("email"),
                "display_name": session.get("display_name"),
                "session_count": 0,
                "usage_count": 0,
                "total_duration_s": 0.0,
                "last_used_at_utc": None,
                "without_sensor_data_count": 0,
                "without_score_count": 0,
                "modes": {
                    "sleep": _empty_participant_mode(),
                    "nap_recovery": _empty_participant_mode(),
                    "unknown": _empty_participant_mode(),
                },
                "scores": [],
            },
        )
        participant["session_count"] += 1
        participant["usage_count"] += 1
        duration = session.get("duration_s")
        if isinstance(duration, int | float) and not isinstance(duration, bool):
            participant["total_duration_s"] += max(0.0, float(duration))
        ended_at = session.get("ended_at_utc")
        if ended_at and (
            participant["last_used_at_utc"] is None
            or str(ended_at) > str(participant["last_used_at_utc"])
        ):
            participant["last_used_at_utc"] = ended_at
        if int(session.get("sample_count") or 0) <= 0:
            participant["without_sensor_data_count"] += 1

        mode = _mapping(result.get("mode"))
        mode_key = str(mode.get("key") or "unknown")
        if mode_key not in participant["modes"]:
            mode_key = "unknown"
        mode_summary = participant["modes"][mode_key]
        mode_summary["session_count"] += 1
        score = _mapping(result.get("score"))
        available = score.get("available") is True
        if available:
            mode_summary["scored_count"] += 1
            if mode_summary["latest_score"] is None:
                mode_summary["latest_score"] = score.get("value")
                mode_summary["latest_score_at_utc"] = ended_at
        else:
            participant["without_score_count"] += 1
        participant["scores"].append(
            {
                "session_id": session.get("session_id"),
                "ended_at_utc": session.get("ended_at_utc"),
                "score": score.get("value") if available else None,
                "score_type": score.get("type"),
                "score_title": score.get("title"),
                "level": score.get("level") if available else "ครั้งนี้ยังไม่มีคะแนน",
                "available": available,
            }
        )
    return list(grouped.values())


def _empty_participant_mode() -> dict[str, Any]:
    """Return one independent mode counter for a person-level report."""
    return {
        "session_count": 0,
        "scored_count": 0,
        "latest_score": None,
        "latest_score_at_utc": None,
    }


def email_first_identity(session: Mapping[str, Any]) -> dict[str, Any]:
    email = str(session.get("email") or "").strip().casefold() or None
    account_key = str(session.get("account_key") or "").strip().casefold()
    return {
        "email": email,
        "display_name": session.get("display_name") or email,
        "canonical_identifier": email or account_key or None,
        "identity_type": "email" if email else "legacy_account_key",
    }


def usage_page_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    sleep_scores, recovery_scores, awaiting = _score_buckets(items)
    identifiers = {
        _mapping(item.get("user")).get("canonical_identifier")
        for item in items
        if _mapping(item.get("user")).get("canonical_identifier")
    }
    return _summary_payload(
        people_count=len(identifiers),
        session_count=len(items),
        sleep_scores=sleep_scores,
        recovery_scores=recovery_scores,
        awaiting=awaiting,
        results=items,
    )


def _valid_count(summary: Mapping[str, Any], name: str) -> int | None:
    value = summary.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _valid_average(
    summary: Mapping[str, Any],
    name: str,
    score_count: int,
) -> float | None:
    value = summary.get(name)
    if score_count <= 0 or isinstance(value, bool):
        return None
    if not isinstance(value, int | float):
        return None
    value = float(value)
    return value if 0.0 <= value <= 100.0 else None


def validated_range_summary(
    source: Any,
    *,
    total: int,
    visible_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate the all-range summary when pagination hides Session rows."""
    summary = _mapping(source)
    people_count = _valid_count(summary, "people_count")
    session_count = _valid_count(summary, "session_count")
    sleep_count = _valid_count(summary, "sleep_score_count")
    recovery_count = _valid_count(summary, "recovery_score_count")
    awaiting_count = _valid_count(summary, "awaiting_score_count")
    visible_sleep, visible_recovery, visible_awaiting = _score_buckets(visible_items)
    valid = bool(
        session_count == total
        and sleep_count is not None
        and recovery_count is not None
        and awaiting_count is not None
        and sleep_count + recovery_count + awaiting_count == total
        and len(visible_sleep) <= sleep_count
        and len(visible_recovery) <= recovery_count
        and visible_awaiting <= awaiting_count
    )
    if not valid:
        sleep_count, recovery_count, awaiting_count = 0, 0, total
    return {
        "people_count": (
            people_count if people_count is not None and people_count <= total else 0
        ),
        "session_count": total,
        "sleep_score_count": sleep_count,
        "recovery_score_count": recovery_count,
        "without_score_count": awaiting_count,
        "awaiting_score_count": awaiting_count,
        "average_sleep_score": _valid_average(
            summary, "average_sleep_score", sleep_count
        ),
        "average_recovery_score": _valid_average(
            summary, "average_recovery_score", recovery_count
        ),
    }
