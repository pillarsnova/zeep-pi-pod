"""Pure acquisition and aggregation helpers for respiratory evidence."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from sleep_system_policy import ZEEP_ON_BED_LABELS, ZEEP_ON_BED_STATUS_CODES
from zeep_pod.sessions.sleep_occupancy import sample_confirms_off_bed

DEFAULT_SAMPLE_INTERVAL_SECONDS = 10.0
MAX_SAMPLE_INTERVAL_SECONDS = 60.0
_INVALID_DATA_STATUSES = {
    "no_data",
    "sensor_gap",
    "sensor_unavailable",
    "service_restart_hold",
    "restart_hold",
    "restored_waiting_live_frame",
    "stale",
    "waiting_for_sensor_frame",
    "waiting_for_vitals",
}
_MOTION_REASONS = {
    "movement_contamination",
    "weak_signal_contamination",
    "movement_or_weak_signal",
}


def finite_number(value: Any) -> float | None:
    """Return one finite numeric value while rejecting booleans."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def sample_interval(value: Any) -> float:
    seconds = finite_number(value)
    if seconds is None or not 0 < seconds <= MAX_SAMPLE_INTERVAL_SECONDS:
        return DEFAULT_SAMPLE_INTERVAL_SECONDS
    return seconds


def row_duration(row: Mapping[str, Any], fallback: float) -> float:
    value = finite_number(row.get("sample_interval_s"))
    if value is not None and 0 < value <= MAX_SAMPLE_INTERVAL_SECONDS:
        return value
    return sample_interval(fallback)


def bed_status_code(row: Mapping[str, Any]) -> int | None:
    for key in ("confirmed_status", "bed_status_code", "status_code"):
        value = finite_number(row.get(key))
        if value is not None:
            return int(value)
    return None


def occupied(row: Mapping[str, Any]) -> bool:
    """Require affirmative Bed evidence; Sleep State is never occupancy."""
    if sample_confirms_off_bed(row):
        return False
    bed = str(row.get("bed") or row.get("bed_status") or "").strip().lower()
    return bool(
        bed in ZEEP_ON_BED_LABELS
        or bed_status_code(row) in ZEEP_ON_BED_STATUS_CODES
    )


def motion_or_weak_signal(row: Mapping[str, Any]) -> bool:
    bed = str(row.get("bed") or row.get("bed_status") or "").strip().lower()
    return bool(
        row.get("motion_contaminated") is True
        or row.get("respiratory_evidence_reason") in _MOTION_REASONS
        or bed in {"moving", "weak breathing"}
        or bed_status_code(row) in {2, 3}
    )


def _invalid_data_status(row: Mapping[str, Any]) -> bool:
    status = str(
        row.get("sleep_data_status") or row.get("data_status") or ""
    ).strip().lower()
    return bool(
        status in _INVALID_DATA_STATUSES
        or status.startswith("invalid_or_missing_")
        or status.startswith("insufficient_")
        or status.startswith("missing_")
        or status.startswith("no_data_")
    )


def measured_quiet_rr(row: Mapping[str, Any]) -> float | None:
    """Return only fresh direct RR, never carried State or display-held RR."""
    if not occupied(row) or row.get("synthetic_sleep_gap") is True:
        return None
    if (
        motion_or_weak_signal(row)
        or _invalid_data_status(row)
        or row.get("respiration_held") is True
    ):
        return None
    persisted = row.get("respiratory_evidence_valid")
    if persisted is not None:
        if persisted is not True and persisted != 1:
            return None
    else:
        if (
            row.get("bcg_analysis_valid") is not True
            or row.get("respiration_current_valid") is not True
        ):
            return None
        packets = finite_number(row.get("paired_vital_packets"))
        coverage = finite_number(row.get("paired_vital_coverage"))
        if packets is None or packets < 8 or coverage is None or coverage < 0.8:
            return None
    value = finite_number(row.get("rr"))
    return value if value is not None and 4.0 <= value <= 60.0 else None


def measured_quiet_hr(row: Mapping[str, Any]) -> float | None:
    """Return current HR from the same direct, quiet evidence used for RR."""
    if measured_quiet_rr(row) is None:
        return None
    if row.get("heart_rate_held") is True or row.get("heart_rate_current_valid") is False:
        return None
    value = finite_number(row.get("hr"))
    return value if value is not None and 30.0 <= value <= 220.0 else None


def weighted_quantile(
    values: list[tuple[float, float]],
    quantile: float,
) -> float | None:
    if not values:
        return None
    ordered = sorted(values, key=lambda item: item[0])
    threshold = max(0.0, min(1.0, quantile)) * sum(
        weight for _, weight in ordered
    )
    elapsed = 0.0
    for value, weight in ordered:
        elapsed += weight
        if elapsed >= threshold:
            return value
    return ordered[-1][0]


def regularity(
    values: list[tuple[float, float]],
) -> tuple[float | None, str]:
    total = sum(weight for _, weight in values)
    if total <= 0:
        return None, "insufficient"
    mean = sum(value * weight for value, weight in values) / total
    if mean <= 0:
        return None, "insufficient"
    variance = sum(
        weight * (value - mean) ** 2 for value, weight in values
    ) / total
    factor = max(0.0, min(1.0, 1.0 - math.sqrt(variance) / mean / 0.18))
    label = "stable" if factor >= 0.67 else "mixed" if factor >= 0.34 else "variable"
    return round(factor, 3), label


def live_sensor_frame_fields(feature: Mapping[str, Any]) -> dict[str, Any]:
    """Build freshness fields stored beside one 10-second Sensor frame."""
    valid = bool(feature.get("bcg_valid"))
    statuses = set(feature.get("status_codes_seen") or [])
    return {
        "heart_rate_current_valid": bool(valid and feature.get("hr") is not None),
        "respiration_current_valid": bool(valid and feature.get("rr") is not None),
        "heart_rate_held": False,
        "respiration_held": False,
        "paired_vital_packets": feature.get("paired_vital_packets"),
        "paired_vital_coverage": feature.get("paired_vital_coverage"),
        "motion_contaminated": 2 in statuses,
        "respiratory_signal_contaminated": bool({2, 3}.intersection(statuses)),
    }


def _live_evidence_verdict(
    bcg: Mapping[str, Any],
    sensor_frame: Mapping[str, Any],
    *,
    minimum_packets: int,
    minimum_coverage: float,
    rr_range: tuple[float, float],
) -> tuple[bool, str]:
    if not bcg.get("connected"):
        return False, "bcg_disconnected"
    if sensor_frame.get("restored_after_restart") is True:
        return False, "restart_display_hold"
    if bcg.get("stale") or bcg.get("analysis_stale"):
        return False, "stale_sensor_frame"
    status = bcg.get("status_code")
    if status == 1:
        return False, "confirmed_off_bed"
    if status in {2, 3} or any(
        bcg.get(key) is True
        for key in ("motion_contaminated", "respiratory_signal_contaminated")
    ):
        return False, "movement_or_weak_signal"
    if status not in {0, 5}:
        return False, "occupancy_not_confirmed"
    if bcg.get("analysis_valid") is not True:
        return False, "analysis_quality_gate_failed"
    if bcg.get("respiration_current_valid") is not True:
        return False, "rr_not_current"
    if bcg.get("respiration_held") is True:
        return False, "rr_display_hold"
    packets = bcg.get("paired_vital_packets")
    if not isinstance(packets, int) or packets < minimum_packets:
        return False, "insufficient_paired_packets"
    coverage = finite_number(bcg.get("paired_vital_coverage"))
    if coverage is None or coverage < minimum_coverage:
        return False, "insufficient_paired_coverage"
    rr = finite_number(bcg.get("respiration_rate"))
    if rr is None or not rr_range[0] <= rr <= rr_range[1]:
        return False, "rr_outside_sensor_sanity_range"
    return True, "eligible_direct_bcg_rr"


def live_session_sample_fields(
    bcg: Mapping[str, Any],
    sensor_frame: Mapping[str, Any],
    *,
    minimum_packets: int,
    minimum_coverage: float,
    rr_range: tuple[float, float],
) -> dict[str, Any]:
    """Return compact provenance persisted with a Session Timeline row."""
    eligible, reason = _live_evidence_verdict(
        bcg,
        sensor_frame,
        minimum_packets=minimum_packets,
        minimum_coverage=minimum_coverage,
        rr_range=rr_range,
    )
    connected = bool(bcg.get("connected"))
    return {
        "status_code": bcg.get("status_code") if connected else None,
        "heart_rate_current_valid": bool(
            connected and bcg.get("heart_rate_current_valid")
        ),
        "respiration_current_valid": bool(
            connected and bcg.get("respiration_current_valid")
        ),
        "heart_rate_held": bool(bcg.get("heart_rate_held")),
        "respiration_held": bool(bcg.get("respiration_held")),
        "paired_vital_packets": bcg.get("paired_vital_packets"),
        "paired_vital_coverage": bcg.get("paired_vital_coverage"),
        "motion_contaminated": bool(bcg.get("motion_contaminated")),
        "respiratory_signal_contaminated": bool(
            bcg.get("respiratory_signal_contaminated")
        ),
        "respiratory_evidence_valid": eligible,
        "respiratory_evidence_reason": reason,
    }


def persisted_evidence_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Restore nullable evidence fields from SQLite-compatible mappings."""
    value = row.get("respiratory_evidence_valid")
    return {
        "respiratory_evidence_valid": value == 1 if value is not None else None,
        "respiratory_evidence_reason": row.get("respiratory_evidence_reason"),
    }
