"""Aggregate direct respiratory and paired vital evidence for publication."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from zeep_pod.sessions.respiratory_evidence import (
    finite_number,
    measured_quiet_hr,
    measured_quiet_rr,
    motion_or_weak_signal,
    occupied,
    regularity,
    row_duration,
    weighted_quantile,
)


def collect_metrics(
    rows: list[dict[str, Any]],
    fallback: float,
) -> dict[str, Any]:
    """Collect RR and strictly paired HR/RR evidence from occupied rows."""
    metrics: dict[str, Any] = {
        "occupied_seconds": 0.0,
        "valid_seconds": 0.0,
        "measured": [],
        "measured_hr": [],
        "measured_paired_rr": [],
        "paired_hr_rr_seconds": 0.0,
        "current_paired_run_samples": 0,
        "longest_paired_run_samples": 0,
        "current_paired_run_seconds": 0.0,
        "longest_paired_run_seconds": 0.0,
        "excluded_motion_seconds": 0.0,
        "excluded_invalid_seconds": 0.0,
        "current_valid_run_samples": 0,
        "longest_valid_run_samples": 0,
        "current_valid_run_seconds": 0.0,
        "longest_valid_run_seconds": 0.0,
        "legacy_rr_without_provenance": False,
    }
    for row in rows:
        if not occupied(row):
            _reset_runs(metrics)
            continue
        seconds = row_duration(row, fallback)
        metrics["occupied_seconds"] += seconds
        if _legacy_rr_without_provenance(row):
            metrics["legacy_rr_without_provenance"] = True
        motion_excluded = motion_or_weak_signal(row)
        if motion_excluded:
            metrics["excluded_motion_seconds"] += seconds
        respiration_rate = measured_quiet_rr(row)
        if respiration_rate is None:
            if not motion_excluded:
                metrics["excluded_invalid_seconds"] += seconds
            _reset_runs(metrics)
            continue
        metrics["measured"].append((respiration_rate, seconds))
        _collect_paired_vital(metrics, row, respiration_rate, seconds)
        _extend_valid_run(metrics, seconds)
    return metrics


def _legacy_rr_without_provenance(row: Mapping[str, Any]) -> bool:
    return bool(
        finite_number(row.get("rr")) is not None
        and row.get("respiratory_evidence_valid") is None
        and row.get("bcg_analysis_valid") is None
        and row.get("respiration_current_valid") is None
    )


def _reset_runs(metrics: dict[str, Any]) -> None:
    metrics["current_valid_run_samples"] = 0
    metrics["current_valid_run_seconds"] = 0.0
    metrics["current_paired_run_samples"] = 0
    metrics["current_paired_run_seconds"] = 0.0


def _collect_paired_vital(
    metrics: dict[str, Any],
    row: Mapping[str, Any],
    respiration_rate: float,
    seconds: float,
) -> None:
    heart_rate = measured_quiet_hr(row)
    if heart_rate is None:
        metrics["current_paired_run_samples"] = 0
        metrics["current_paired_run_seconds"] = 0.0
        return
    metrics["measured_hr"].append((heart_rate, seconds))
    metrics["measured_paired_rr"].append((respiration_rate, seconds))
    metrics["paired_hr_rr_seconds"] += seconds
    metrics["current_paired_run_samples"] += 1
    metrics["current_paired_run_seconds"] += seconds
    metrics["longest_paired_run_samples"] = max(
        metrics["longest_paired_run_samples"],
        metrics["current_paired_run_samples"],
    )
    metrics["longest_paired_run_seconds"] = max(
        metrics["longest_paired_run_seconds"],
        metrics["current_paired_run_seconds"],
    )


def _extend_valid_run(metrics: dict[str, Any], seconds: float) -> None:
    metrics["valid_seconds"] += seconds
    metrics["current_valid_run_samples"] += 1
    metrics["current_valid_run_seconds"] += seconds
    metrics["longest_valid_run_samples"] = max(
        metrics["longest_valid_run_samples"],
        metrics["current_valid_run_samples"],
    )
    metrics["longest_valid_run_seconds"] = max(
        metrics["longest_valid_run_seconds"],
        metrics["current_valid_run_seconds"],
    )


def build_observations(
    metrics: Mapping[str, Any],
    *,
    minimum_valid_samples: int,
    minimum_valid_seconds: float,
    minimum_context_coverage_pct: float,
) -> dict[str, Any]:
    """Build RR observations and release paired medians only after its gate."""
    measured = metrics["measured"]
    occupied_seconds = metrics["occupied_seconds"]
    valid_seconds = metrics["valid_seconds"]
    coverage_pct = _coverage_pct(valid_seconds, occupied_seconds)
    paired_coverage_pct = _coverage_pct(
        metrics["paired_hr_rr_seconds"],
        occupied_seconds,
    )
    paired_evidence_sufficient = bool(
        len(metrics["measured_hr"]) >= minimum_valid_samples
        and metrics["paired_hr_rr_seconds"] >= minimum_valid_seconds
        and metrics["longest_paired_run_seconds"] >= 30.0
        and paired_coverage_pct >= minimum_context_coverage_pct
    )
    median_hr = weighted_quantile(metrics["measured_hr"], 0.5)
    median_paired_rr = weighted_quantile(metrics["measured_paired_rr"], 0.5)
    median = weighted_quantile(measured, 0.5)
    p10 = weighted_quantile(measured, 0.1)
    p90 = weighted_quantile(measured, 0.9)
    regularity_factor, regularity_key = regularity(measured)
    return {
        "median_hr_bpm": _gated_round(median_hr, paired_evidence_sufficient),
        "median_paired_rr_brpm": _gated_round(
            median_paired_rr,
            paired_evidence_sufficient,
        ),
        "median_rr_brpm": _optional_round(median),
        "p10_rr_brpm": _optional_round(p10),
        "p90_rr_brpm": _optional_round(p90),
        "regularity_factor": regularity_factor,
        "regularity_key": regularity_key,
        "valid_samples": len(measured),
        "paired_hr_rr_samples": len(metrics["measured_hr"]),
        "paired_hr_rr_minutes": round(metrics["paired_hr_rr_seconds"] / 60.0, 1),
        "paired_hr_rr_coverage_pct": _bounded_round(paired_coverage_pct),
        "longest_paired_hr_rr_run_seconds": round(
            metrics["longest_paired_run_seconds"],
            1,
        ),
        "paired_hr_rr_evidence_sufficient": paired_evidence_sufficient,
        "longest_valid_run_samples": metrics["longest_valid_run_samples"],
        "longest_valid_run_seconds": round(
            metrics["longest_valid_run_seconds"],
            1,
        ),
        "valid_minutes": round(valid_seconds / 60.0, 1),
        "occupied_minutes": round(occupied_seconds / 60.0, 1),
        "coverage_pct": _bounded_round(coverage_pct),
        "excluded_motion_or_weak_signal_minutes": round(
            metrics["excluded_motion_seconds"] / 60.0,
            1,
        ),
        "excluded_invalid_or_held_minutes": round(
            metrics["excluded_invalid_seconds"] / 60.0,
            1,
        ),
    }


def _coverage_pct(numerator: float, denominator: float) -> float:
    return 100.0 * numerator / denominator if denominator else 0.0


def _bounded_round(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _optional_round(value: float | None) -> float | None:
    return round(value, 1) if value is not None else None


def _gated_round(value: float | None, gate_passed: bool) -> float | None:
    return _optional_round(value) if gate_passed else None
