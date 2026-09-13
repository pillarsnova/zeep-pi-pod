"""Fail-closed identity checks for the two released Session scores.

The selected Session mode is authoritative. Quality metadata can corroborate
that choice, but it must never relabel a Recovery Score as a Sleep Score (or
the reverse). This module only validates identity/provenance; it does not
calculate or revise a score.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sleep_system_policy import (
    RECOVERY_SCORE_FORMULA_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
    rest_mode_group,
)

QUALITY_TYPE_BY_GROUP = {
    "sleep": "sleep",
    "nap_recovery": "rest_goal",
}
SCORE_TITLE_BY_GROUP = {
    "sleep": "Sleep Score",
    "nap_recovery": "Recovery Score",
}
SCORE_FORMULA_BY_GROUP = {
    "sleep": SLEEP_SCORE_FORMULA_VERSION,
    "nap_recovery": RECOVERY_SCORE_FORMULA_VERSION,
}
SCORE_FORMULA_PREFIX_BY_GROUP = {
    "sleep": "zeep-sleep-score-",
    "nap_recovery": "zeep-recovery-score-",
}


def mode_groups(value: Any) -> set[str]:
    """Return every canonical group asserted by one mode value."""
    if isinstance(value, Mapping):
        candidates = (
            value.get("group"),
            value.get("requested"),
            value.get("resolved"),
        )
    else:
        candidates = (value,)
    return {
        group
        for candidate in candidates
        if (group := rest_mode_group(candidate)) is not None
    }


def _mode_metadata_present(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            candidate is not None and str(candidate).strip()
            for candidate in (
                value.get("group"),
                value.get("requested"),
                value.get("resolved"),
            )
        )
    return value is not None and bool(str(value).strip())


def quality_type_group(quality: Mapping[str, Any]) -> str | None:
    quality_type = str(quality.get("quality_type") or "").strip()
    if quality_type == "sleep":
        return "sleep"
    if quality_type == "rest_goal":
        return "nap_recovery"
    return None


def _mode_conflicts(
    quality: Mapping[str, Any],
    authoritative_groups: set[str],
    group: str | None,
    related_modes: Iterable[tuple[str, Any]],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    if len(authoritative_groups) > 1:
        conflicts.append(
            {
                "source": "authoritative_mode",
                "reported_groups": sorted(authoritative_groups),
            }
        )
    embedded_sources = [
        ("quality.rest_mode", quality.get("rest_mode")),
        *list(related_modes),
    ]
    for source, value in embedded_sources:
        groups = mode_groups(value)
        if len(groups) > 1 or (groups and (group is None or group not in groups)):
            conflicts.append({"source": source, "reported_groups": sorted(groups)})
        elif _mode_metadata_present(value) and not groups:
            conflicts.append({"source": source, "reported_groups": []})
    return conflicts


def assess_score_identity(
    quality: Mapping[str, Any] | None,
    authoritative_mode: Any,
    *,
    related_modes: Iterable[tuple[str, Any]] = (),
) -> dict[str, Any]:
    """Validate a stored score against an authoritative Session mode.

    Approved historical results may retain an earlier formula in the same
    Sleep/Recovery family. Missing or cross-family formula provenance fails
    closed. Available scores must also carry a recognised ``quality_type``.
    """
    score_quality = dict(quality or {})
    authoritative_groups = mode_groups(authoritative_mode)
    group = next(iter(authoritative_groups)) if len(authoritative_groups) == 1 else None
    conflicts = _mode_conflicts(
        score_quality,
        authoritative_groups,
        group,
        related_modes,
    )

    expected_quality_type = QUALITY_TYPE_BY_GROUP.get(group)
    actual_quality_type_group = quality_type_group(score_quality)
    quality_type_present = bool(str(score_quality.get("quality_type") or "").strip())
    expected_formula = SCORE_FORMULA_BY_GROUP.get(group)
    expected_formula_prefix = SCORE_FORMULA_PREFIX_BY_GROUP.get(group)
    actual_formula = score_quality.get("formula_version")
    formula = str(actual_formula or "").strip().casefold()
    stored_title = str(score_quality.get("score_title") or "").strip()

    if group is None:
        status = "mode_metadata_conflict" if conflicts else "mode_unresolved"
        reason = (
            "ข้อมูลรูปแบบการพักขัดกัน ต้องตรวจสอบก่อนเผยแพร่คะแนน"
            if conflicts
            else "ยังไม่ทราบรูปแบบการพัก จึงไม่อนุมานชนิดคะแนน"
        )
    elif conflicts:
        status = "mode_metadata_conflict"
        reason = "ข้อมูลรูปแบบการพักขัดกัน ต้องตรวจสอบก่อนเผยแพร่คะแนน"
    elif actual_quality_type_group is None:
        status = "score_identity_untyped"
        reason = "ผลคะแนนไม่ได้ระบุชนิด Sleep/Recovery ที่ตรวจสอบได้"
    elif actual_quality_type_group != group:
        status = "score_identity_conflict"
        reason = "ชนิดผลคะแนนขัดกับรูปแบบการพักของ Session"
    elif stored_title and stored_title != SCORE_TITLE_BY_GROUP[group]:
        status = "score_identity_conflict"
        reason = "ชื่อคะแนนขัดกับรูปแบบการพักของ Session"
    elif not formula:
        status = "score_formula_untyped"
        reason = "ผลคะแนนไม่มีรุ่นสูตรที่ตรวจสอบได้"
    elif not formula.startswith(str(expected_formula_prefix)):
        status = "score_formula_mismatch"
        reason = "รุ่นสูตรคะแนนไม่ตรงกับรูปแบบการพักของ Session"
    else:
        status = "score_identity_confirmed"
        reason = None

    return {
        "valid": status == "score_identity_confirmed",
        "group": group,
        "validation_status": status,
        "reason": reason,
        "conflicts": conflicts,
        "quality_type_present": quality_type_present,
        "expected_quality_type": expected_quality_type,
        "expected_score_title": SCORE_TITLE_BY_GROUP.get(group),
        "expected_formula_version": expected_formula,
    }
