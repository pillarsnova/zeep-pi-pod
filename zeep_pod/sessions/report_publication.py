"""Positive nested allowlists for the application-facing Session report.

Historical report rows are flexible JSON.  A top-level allowlist alone is not
safe because an unexpected timeline, identifier or private field could hide in
an approved section.  Each helper below publishes only documented aggregates.
"""

from __future__ import annotations

from typing import Any

from zeep_pod.sessions.publication_values import (
    SCALAR_TYPES,
    copy_scalars,
    mapping,
    scalar_map,
)
from zeep_pod.sessions.quality_publication import (
    public_cycle,
    public_environment_metric,
    public_safety_excursion,
)


def _public_sleep_summary(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(
        source,
        {
            "recording_s",
            "estimated_sleep_s",
            "wake_s",
            "sleep_onset_proxy_s",
            "waso_proxy_s",
            "sleep_efficiency_pct",
            "actual_scored_s",
            "wake_pct_recorded",
            "wake_entries",
            "awakenings",
            "movement_pct",
            "bed_exit_events",
            "transient_bed_exit_samples",
            "confirmed_bed_exit_samples",
            "weak_breathing_samples",
            "snoring_samples",
        },
    )
    if source.get("cycles") is None and "cycles" in source:
        public["cycles"] = None
    elif "cycles" in source:
        public["cycles"] = public_cycle(source["cycles"])
    return public


def _public_stage(value: Any) -> dict[str, Any]:
    return copy_scalars(
        value,
        {"state", "samples", "duration_s", "pct_scored", "pct_sleep"},
    )


def _public_environment_assessment(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(
        source,
        {
            "version",
            "aggregation_version",
            "aggregation_method",
            "mode",
            "mode_label",
            "acceptable_min_level",
            "acceptable_min_label",
            "overall_level",
            "overall_label",
            "meets_expected",
            "required_count",
            "advisory_count",
            "optimisation_count",
            "maintain_count",
            "available_count",
            "expected_count",
            "required_expected_count",
            "blocking_unavailable_count",
            "optional_unavailable_count",
            "assessment_quality",
            "safety_excursion_observed",
            "safety_review_required",
            "safety_excursion_count",
            "safety_excursions_change_sustained_assessment",
            "safety_excursions_change_score",
            "context_only",
            "sleep_stage_context_only",
            "contributes_to_primary_score",
            "primary_score",
            "max_score_points",
            "direct_stage_influence",
            "safety_thresholds_unchanged",
        },
    )
    if isinstance(source.get("safety_excursions"), (list, tuple)):
        public["safety_excursions"] = [
            public_safety_excursion(item) for item in source["safety_excursions"]
        ]
    return public


def _public_finding(value: Any) -> dict[str, Any]:
    return copy_scalars(
        value,
        {
            "key",
            "metric_key",
            "severity",
            "level_key",
            "decision",
            "title",
            "detail",
            "action",
            "context_only",
            "sleep_stage_context_only",
            "contributes_to_primary_score",
            "legacy_timeline_not_persisted",
            "blocks_overall",
            "aggregation_version",
            "peak_status_key",
            "transient_critical_observed",
            "changes_sustained_assessment",
            "changes_score",
            "threshold",
            "sample_count",
            "sample_pct",
        },
    )


def _public_report_data_quality(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(source, {"level", "label", "note"})
    if "coverage" in source:
        public["coverage"] = scalar_map(
            source["coverage"],
            {"recording_pct", "bcg_pct", "sleep_stage_pct", "environment_pct"},
        )
    if "confidence_pct" in source:
        public["confidence_pct"] = scalar_map(
            source["confidence_pct"], {"high", "medium", "low"}
        )
    return public


def _public_guidance(value: Any) -> dict[str, Any]:
    return copy_scalars(
        value,
        {
            "primary",
            "next_session",
            "self_check",
            "mode",
            "score_used",
            "score_released",
            "basis",
            "medical_diagnosis",
            "available",
            "reason",
            "score_derived_claims_suppressed",
        },
    )


def public_report_field(key: str, value: Any) -> Any:
    """Sanitize one approved report section with its positive nested schema."""
    scalar_fields = {
        "available",
        "version",
        "product_positioning",
        "intended_use",
        "timeline_schema_version",
        "estimator_version",
        "headline",
        "insight",
        "reason",
        "disclaimer",
    }
    if key in scalar_fields:
        return value if isinstance(value, SCALAR_TYPES) else None
    if key == "sleep":
        return _public_sleep_summary(value)
    if key == "stages":
        return (
            [_public_stage(item) for item in value] if isinstance(value, list) else []
        )
    if key == "environment":
        if not isinstance(value, list):
            return []
        return [public_environment_metric(item) for item in value]
    if key == "environment_assessment":
        return _public_environment_assessment(value)
    if key == "findings":
        return (
            [_public_finding(item) for item in value] if isinstance(value, list) else []
        )
    if key == "post_session_guidance":
        return _public_guidance(value)
    if key == "data_quality":
        return _public_report_data_quality(value)
    return None
