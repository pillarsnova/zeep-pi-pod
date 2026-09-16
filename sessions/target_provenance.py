"""Validate duration-target provenance for target-specific wellness scores."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from common.numbers import as_number as _number
from sleep_system_policy import (
    SLEEP_SCORE_FORMULA_VERSION,
    resolve_rest_target,
    rest_mode_group,
)


def _canonical_nap_key(value: Any) -> str | None:
    key = str(value or "").strip().casefold()
    return {
        "nap_30": "nap_30",
        "nap_30m": "nap_30",
        "nap_90": "nap_90",
        "nap_90m": "nap_90",
    }.get(key)


def _assess_sleep_target(
    session_target_seconds: Any,
    quality_target: Any,
    formula_version: Any,
) -> dict[str, Any]:
    target = resolve_rest_target("sleep")
    canonical_seconds = _number(target.get("seconds"))
    session_seconds = _number(session_target_seconds)
    quality = dict(quality_target) if isinstance(quality_target, Mapping) else {}
    quality_seconds = _number(quality.get("seconds"))
    session_valid = bool(
        session_seconds is None
        or (
            canonical_seconds is not None
            and abs(session_seconds - canonical_seconds) <= 1.0
        )
    )
    quality_valid = bool(
        quality_seconds is not None
        and canonical_seconds is not None
        and abs(quality_seconds - canonical_seconds) <= 1.0
    )
    missing_current_quality_target = bool(
        str(formula_version or "").strip() == SLEEP_SCORE_FORMULA_VERSION
        and quality_seconds is None
    )
    conflict = bool(
        not session_valid
        or (quality and not quality_valid)
        or missing_current_quality_target
    )
    return {
        "valid_for_score": not conflict,
        "verified": quality_valid and session_valid,
        "review_required": conflict or not quality_valid,
        "validation_status": (
            "target_metadata_conflict"
            if conflict
            else "target_metadata_confirmed"
            if quality_valid
            else "target_metadata_unverified"
        ),
        "target": target,
    }


def assess_target_provenance(
    group: Any,
    session_target_seconds: Any,
    quality_target: Any,
    formula_version: Any = None,
) -> dict[str, Any]:
    """Check that a Nap score was calculated for the Session's chosen target.

    ``target_duration_s`` on the Session is authoritative. Historical Nap
    records without that field remain readable, but are deliberately excluded
    from 30/90-minute comparison cohorts. A present but invalid target, or a
    released quality result calculated for another target, fails closed.
    """
    canonical_group = rest_mode_group(group)
    if canonical_group == "sleep":
        return _assess_sleep_target(
            session_target_seconds,
            quality_target,
            formula_version,
        )
    if canonical_group != "nap_recovery":
        return {
            "valid_for_score": True,
            "verified": False,
            "review_required": False,
            "validation_status": "target_not_required",
            "target": resolve_rest_target(canonical_group),
        }

    if session_target_seconds is None:
        return {
            "valid_for_score": True,
            "verified": False,
            "review_required": True,
            "validation_status": "target_metadata_unverified",
            "target": None,
        }

    target = resolve_rest_target(canonical_group, session_target_seconds)
    session_seconds = _number(session_target_seconds)
    canonical_seconds = _number(target.get("seconds"))
    session_valid = bool(
        target.get("available") is True
        and session_seconds is not None
        and canonical_seconds is not None
        and abs(session_seconds - canonical_seconds) <= 1.0
    )
    quality = dict(quality_target) if isinstance(quality_target, Mapping) else {}
    quality_seconds = _number(quality.get("seconds"))
    quality_key = _canonical_nap_key(quality.get("key"))
    quality_matches = bool(
        session_valid
        and quality_seconds is not None
        and abs(quality_seconds - canonical_seconds) <= 1.0
        and quality_key == target.get("key")
    )
    if session_valid and quality_matches:
        return {
            "valid_for_score": True,
            "verified": True,
            "review_required": False,
            "validation_status": "target_metadata_confirmed",
            "target": target,
        }
    return {
        "valid_for_score": False,
        "verified": False,
        "review_required": True,
        "validation_status": "target_metadata_conflict",
        "target": target if session_valid else None,
    }


def apply_target_review(
    session: Mapping[str, Any],
    mode: Mapping[str, Any],
    quality: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Return reviewed mode, target assessment and score-blocking conflict."""
    provenance = assess_target_provenance(
        mode.get("group"),
        session.get("target_duration_s"),
        quality.get("duration_target"),
        quality.get("formula_version"),
    )
    session_target = _number(session.get("target_duration_s"))
    resolved = resolve_rest_target(mode.get("group"), session_target)
    canonical_seconds = _number(resolved.get("seconds"))
    invalid_session_target = bool(
        session_target is not None
        and (
            resolved.get("available") is not True
            or canonical_seconds is None
            or abs(session_target - canonical_seconds) > 1.0
        )
    )
    review_required = bool(
        invalid_session_target or provenance.get("review_required") is True
    )
    reviewed_mode = dict(mode)
    if review_required:
        reviewed_mode.update(
            review_required=True,
            protocol_review_required=True,
        )
    return (
        reviewed_mode,
        provenance,
        provenance.get("valid_for_score") is False,
    )
