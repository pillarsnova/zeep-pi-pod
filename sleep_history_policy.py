"""Promotion policy for historical ZEEP wellness-derived sleep results.

The policy deliberately separates three different questions:

* ``quality_tier`` describes whole-Session data completeness for Admin QA.
* ``review_warnings`` highlight unusual results that deserve human review.
* ``promotion_blockers`` identify integrity failures that make a derived write
  unsafe.

Quality Tier and review warnings never decide whether valid physiological
epochs may be promoted.  Raw BCG and Timeline rows remain immutable.
"""

from __future__ import annotations

from typing import Any, Mapping


QUALITY_TIER_A = "A"
QUALITY_TIER_B = "B"
QUALITY_TIER_BELOW_B = "below_B"

REVIEW_WARNING_CODES = frozenset({
    "wellness_score_not_releasable",
    "no_valid_epoch_evidence",
    "no_confirmed_sleep_state",
    "overnight_N2_over_85_percent",
    "overnight_N1_over_30_percent",
    "overnight_N3_over_35_percent",
    "overnight_REM_over_40_percent",
    "overnight_no_confirmed_sleep",
    "overnight_N3_zero",
    "overnight_confirmed_stage_coverage_below_80_percent",
    "nap_duration_over_90_minutes",
    "ping_pong_within_60s",
})

PROMOTION_BLOCKER_CODES = frozenset({
    "missing_raw_bcg_packets",
    "forbidden_transition",
    "confirmed_transition_without_current_gate",
})


def quality_tier(
    *,
    timeline_paired_hr_rr: float,
    raw_paired_hr_rr: float,
    raw_acquisition: float,
    raw_maximum_gap_s: float,
    context_reset_gap_s: float,
) -> str:
    """Return the whole-Session Admin QA tier.

    The thresholds retain continuity with earlier audit reports.  They are
    descriptors only and are not a write allowlist.
    """
    tier_a = bool(
        timeline_paired_hr_rr >= 0.90
        and raw_paired_hr_rr >= 0.90
        and raw_acquisition >= 0.95
        and raw_maximum_gap_s < context_reset_gap_s
    )
    if tier_a:
        return QUALITY_TIER_A
    tier_b = bool(
        timeline_paired_hr_rr >= 0.80
        and raw_paired_hr_rr >= 0.80
        and raw_acquisition >= 0.80
    )
    return QUALITY_TIER_B if tier_b else QUALITY_TIER_BELOW_B


def replay_integrity_blockers(
    replay: Mapping[str, Any] | None,
    *,
    raw_packet_count: int,
) -> list[str]:
    """Return hard blockers for a single historical replay result."""
    blockers: list[str] = []
    if raw_packet_count <= 0:
        blockers.append("missing_raw_bcg_packets")
    if replay and int(replay.get("forbidden_transition_count") or 0) > 0:
        blockers.append("forbidden_transition")
    if replay and int(
        replay.get("confirmed_transition_without_current_gate_count") or 0
    ) > 0:
        blockers.append("confirmed_transition_without_current_gate")
    return blockers


def replay_review_warnings(
    replay: Mapping[str, Any] | None,
) -> list[str]:
    """Return non-blocking review prompts for absent derived results.

    A completed Session can legitimately contain only WAIT/NO DATA/OFF BED
    epochs.  That result must remain writable and auditable; it must not be
    converted into a fabricated five-state classification.
    """
    warnings: list[str] = []
    if not replay or int(replay.get("evidence_count") or 0) <= 0:
        warnings.append("no_valid_epoch_evidence")
    if not replay or int(replay.get("confirmed_count") or 0) <= 0:
        warnings.append("no_confirmed_sleep_state")
    return warnings


def split_issue_codes(codes: list[str]) -> tuple[list[str], list[str]]:
    """Split known issue codes into warnings and hard blockers.

    Unknown codes fail closed as blockers so a new integrity condition cannot
    silently become promotable before this central policy is reviewed.
    """
    warnings: list[str] = []
    blockers: list[str] = []
    for code in dict.fromkeys(codes):
        if code in REVIEW_WARNING_CODES:
            warnings.append(code)
        elif code in PROMOTION_BLOCKER_CODES:
            blockers.append(code)
        else:
            blockers.append(f"unclassified_issue:{code}")
    return warnings, blockers


def promotion_ready(item: Mapping[str, Any]) -> bool:
    """Return whether reviewed derived rows are safe to write.

    This intentionally does not inspect ``quality_tier`` or warnings.
    """
    return bool(
        not (item.get("promotion_blockers") or [])
        and (
            (item.get("evidence_rows") or [])
            or (item.get("state_rows") or [])
            or (item.get("status_rows") or [])
        )
    )
