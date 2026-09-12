"""Canonical occupancy evidence used by Sleep decision replay."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sleep_system_policy import (
    ZEEP_OFF_BED_DATA_STATUSES,
    ZEEP_ON_BED_LABELS,
    ZEEP_ON_BED_STATUS_CODES,
)

from .sleep_event_data import finite_number


SLEEP_STATES = frozenset({"wake", "n1", "n2", "n3", "rem"})
DEFAULT_HEART_RATE_RANGE = (25.0, 220.0)
DEFAULT_RESPIRATION_RATE_RANGE = (2.0, 60.0)

CONFIRMED_RETURN_PROVENANCE = frozenset({
    "durable_stage_event",
    "fresh_same_packet_hr_rr_bcg",
})


def confirmed_bed_exit_evidence(value: Mapping[str, Any]) -> bool:
    """Accept an explicit confirmed Bed Exit object, never a raw label."""
    evidence = value.get("bed_exit_evidence")
    return bool(
        isinstance(evidence, Mapping)
        and evidence.get("confirmed") is True
    )


def sample_confirms_off_bed(sample: Mapping[str, Any]) -> bool:
    """Recognise only canonical status or confirmed Bed Exit evidence."""
    data_status = str(
        sample.get("sleep_data_status") or ""
    ).strip().lower()
    return bool(
        data_status in ZEEP_OFF_BED_DATA_STATUSES
        or confirmed_bed_exit_evidence(sample)
    )


def _is_on_bed(sample: Mapping[str, Any]) -> bool:
    """Require affirmative Bed Status before releasing OFF BED."""
    status_code = sample.get("confirmed_status")
    if status_code is None:
        status_code = sample.get("bed_status_code")
    if status_code is None:
        status_code = sample.get("status_code")
    return bool(
        str(sample.get("bed") or "").strip().lower()
        in ZEEP_ON_BED_LABELS
        or status_code in ZEEP_ON_BED_STATUS_CODES
    )


def sample_confirms_fresh_on_bed_return(
    sample: Mapping[str, Any],
    *,
    heart_rate_range: tuple[float, float],
    respiration_rate_range: tuple[float, float],
) -> bool:
    """Require occupied Bed plus paired, current HR/RR/BCG evidence."""
    heart_rate = sample.get("hr")
    respiration_rate = sample.get("rr")
    return bool(
        _is_on_bed(sample)
        and sample.get("bcg_analysis_valid") is True
        and sample.get("heart_rate_held") is not True
        and sample.get("respiration_held") is not True
        and sample.get("heart_rate_current_valid") is not False
        and sample.get("respiration_current_valid") is not False
        and finite_number(heart_rate)
        and heart_rate_range[0] <= float(heart_rate) <= heart_rate_range[1]
        and finite_number(respiration_rate)
        and respiration_rate_range[0]
        <= float(respiration_rate)
        <= respiration_rate_range[1]
    )


def sample_has_confirmed_occupied_return(
    sample: Mapping[str, Any],
) -> bool:
    """Recognise return proof carried from an authoritative source."""
    return bool(
        sample.get("sleep") in SLEEP_STATES
        and sample.get("sleep_occupancy_provenance")
        in CONFIRMED_RETURN_PROVENANCE
    )
