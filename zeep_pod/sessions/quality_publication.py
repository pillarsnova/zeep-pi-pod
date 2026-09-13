"""Positive nested allowlists for published Session quality results."""

from __future__ import annotations

from typing import Any

from zeep_pod.product_language import (
    USER_WELLNESS_DISCLAIMER,
    user_confidence_level,
    user_environment_level,
    user_score_component_label,
)
from zeep_pod.sessions.publication_values import (
    COMPONENT_KEYS,
    ENVIRONMENT_LEVEL_KEYS,
    SENSOR_VALUE_KEYS,
    STAGE_KEYS,
    copy_scalars,
    mapping,
    scalar_list,
    scalar_map,
)


def public_cycle(value: Any) -> dict[str, Any]:
    return copy_scalars(
        value,
        {
            "available",
            "completed_nrem_rem_cycles",
            "minimum_nrem_s",
            "method",
            "clinical_equivalent",
            "expected_for_score",
            "score_note",
            "points",
            "max_points",
        },
    )


def _public_duration_target(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(
        source,
        {
            "available",
            "group",
            "key",
            "label",
            "seconds",
            "minutes",
            "target_minutes",
            "hours",
            "review_required",
            "source",
            "valid",
            "eligible_rest_seconds",
            "eligible_rest_minutes",
            "completion_pct",
            "basis",
            "extended_max_seconds",
        },
    )
    for key in (
        "supported_seconds",
        "recommended_range_seconds",
        "recommended_range_minutes",
    ):
        if key in source:
            public[key] = scalar_list(source[key])
    return public


def public_environment_metric(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(
        source,
        {
            "key",
            "sample_key",
            "label",
            "unit",
            "source",
            "mode",
            "target",
            "expected_floor",
            "bands",
            "available",
            "required_for_overall",
            "coverage_pct",
            "average",
            "minimum",
            "maximum",
            "outside_target_pct",
            "below_expected_pct",
            "outside_direction",
            "status_key",
            "status",
            "rank",
            "decision",
            "meets_expected",
            "aggregation_version",
            "aggregation_method",
            "version",
            "method",
            "quantile",
            "peak_status_key",
            "sample_count",
            "critical_sample_count",
            "critical_sample_pct",
            "transient_critical_observed",
            "safety_threshold",
            "critical_below",
            "critical_above",
            "safety_excursion_observed",
            "safety_excursion_sample_count",
            "safety_excursion_sample_pct",
            "action",
        },
    )
    for key in ("level_distribution_pct", "level_counts"):
        if key in source:
            public[key] = scalar_map(source[key], ENVIRONMENT_LEVEL_KEYS)
    if "status_key" in source or "status" in source:
        public["status"] = user_environment_level(
            source.get("status_key"),
            source.get("status"),
        )
    return public


def public_safety_excursion(value: Any) -> dict[str, Any]:
    return copy_scalars(
        value,
        {
            "key",
            "label",
            "threshold",
            "critical_below",
            "critical_above",
            "minimum",
            "maximum",
            "sample_count",
            "sample_pct",
        },
    )


def _public_environment_support(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(
        source,
        {
            "available",
            "quality_factor",
            "coverage_pct",
            "available_factors",
            "expected_factors",
            "policy_version",
            "aggregation_version",
            "overall_level",
            "overall_label",
            "meets_expected",
            "context_only",
            "sleep_stage_context_only",
            "contributes_to_primary_score",
            "primary_score",
            "max_points",
            "points",
            "assessment_quality",
            "blocking_unavailable_count",
            "optional_unavailable_count",
            "safety_excursion_observed",
            "safety_review_required",
            "safety_excursions_change_score",
        },
    )
    if "averages" in source:
        public["averages"] = scalar_map(source["averages"], SENSOR_VALUE_KEYS)
    if "fit" in source:
        public["fit"] = scalar_map(source["fit"], SENSOR_VALUE_KEYS)
    if isinstance(source.get("metrics"), (list, tuple)):
        public["metrics"] = [
            public_environment_metric(item) for item in source["metrics"]
        ]
    if isinstance(source.get("safety_excursions"), (list, tuple)):
        public["safety_excursions"] = [
            public_safety_excursion(item) for item in source["safety_excursions"]
        ]
    if "overall_level" in source or "overall_label" in source:
        public["overall_label"] = user_environment_level(
            source.get("overall_level"),
            source.get("overall_label"),
        )
    return public


def _public_sleep_opportunity(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(source, {"duration_points", "duration_max_points"})
    if "latency" in source:
        public["latency"] = copy_scalars(
            source["latency"],
            {"available", "seconds", "points", "max_points", "basis"},
        )
    return public


def _public_architecture(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(source, {"total", "method", "mode_adjusted"})
    for key in ("points", "max_points"):
        if key in source:
            public[key] = scalar_map(source[key], STAGE_KEYS)
    return public


def _public_continuity(value: Any) -> dict[str, Any]:
    source = mapping(value)
    public = copy_scalars(
        source,
        {
            "wake_points",
            "wake_max_points",
            "efficiency_points",
            "efficiency_max_points",
            "balanced_arousal_penalty_points",
        },
    )
    proxy = mapping(source.get("arousal_proxy"))
    if not proxy:
        return public
    public_proxy = copy_scalars(
        proxy,
        {
            "available",
            "episodes",
            "index_per_hour",
            "evidence_windows",
            "available_windows",
            "penalty_points",
            "validated_cortical_arousal",
            "method",
        },
    )
    if "thresholds" in proxy:
        public_proxy["thresholds"] = scalar_map(
            proxy["thresholds"],
            {
                "bcg_amplitude_shift_ratio",
                "movement_ratio",
                "prior_sleep_s",
                "quiet_gap_s",
            },
        )
    public["arousal_proxy"] = public_proxy
    return public


def _public_scalar_maps(source: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    specifications = {
        "stage_pct_of_sleep": STAGE_KEYS,
        "component_points": COMPONENT_KEYS,
        "component_max_points": COMPONENT_KEYS,
        "data_coverage": {
            "ratio",
            "pct",
            "physiological_evidence_ratio",
            "physiological_evidence_pct",
            "state_attribution_ratio",
            "state_attribution_pct",
            "recording_ratio",
            "recording_pct",
            "paired_hr_rr_pct",
            "points",
            "max_points",
            "score_component",
            "environment_pct",
            "basis",
        },
        "score_confidence": {
            "level",
            "label",
            "session_coverage_pct",
            "timeline_coverage_pct",
            "state_attribution_coverage_pct",
            "physiological_evidence_coverage_pct",
            "paired_hr_rr_coverage_pct",
            "coverage_is_admin_qa_context",
            "coverage_can_hide_score",
        },
        "physiology": {
            "available",
            "heart_rate_average",
            "respiration_average",
            "regularity_factor",
            "heart_rate_regularity_factor",
            "respiration_regularity_factor",
            "settling_factor",
            "paired_hr_rr_samples",
            "source_sensor_samples",
            "paired_hr_rr_coverage_pct",
            "method",
        },
        "body_response": {
            "available",
            "movement_pct",
            "bed_exit_events",
            "transient_bed_exit_samples",
        },
    }
    for key, fields in specifications.items():
        if key in source:
            public[key] = scalar_map(source[key], fields)
    if "component_labels" in source:
        labels = mapping(source["component_labels"])
        public["component_labels"] = {
            key: user_score_component_label(key)
            for key in COMPONENT_KEYS
            if key in labels
        }
    confidence = mapping(public.get("score_confidence"))
    if confidence:
        confidence["label"] = user_confidence_level(confidence.get("level"))
        public["score_confidence"] = confidence
    return public


def public_quality_payload(value: Any) -> dict[str, Any]:
    """Return only documented aggregate fields from a quality result."""
    source = mapping(value)
    public = copy_scalars(
        source,
        {
            "available",
            "score",
            "reason",
            "score_title",
            "score_scope",
            "validation_status",
            "clinical_validated",
            "quality_type",
            "session_character",
            "sleep_detected",
            "level",
            "level_key",
            "insight",
            "estimated_sleep_s",
            "actual_scored_s",
            "wake_s",
            "wake_pct_recorded",
            "sleep_efficiency_pct",
            "awakenings",
            "wake_entries",
            "deep_pct",
            "rem_pct",
            "score_basis",
            "formula_version",
            "version",
            "outcome_interpretation",
            "disclaimer",
        },
    )
    public.update(_public_scalar_maps(source))
    if "disclaimer" in source:
        public["disclaimer"] = USER_WELLNESS_DISCLAIMER
    if "component_order" in source:
        public["component_order"] = [
            item
            for item in scalar_list(source["component_order"])
            if item in COMPONENT_KEYS
        ]
    nested = {
        "duration_target": _public_duration_target,
        "environment_support": _public_environment_support,
        "sleep_opportunity": _public_sleep_opportunity,
        "architecture": _public_architecture,
        "continuity": _public_continuity,
        "cycles": public_cycle,
    }
    for key, sanitizer in nested.items():
        if key in source:
            public[key] = sanitizer(source[key])
    return public


def public_result_data_quality(value: Any) -> dict[str, Any]:
    """Publish only aggregate QA fields from the canonical result contract."""
    source = mapping(value)
    public = copy_scalars(
        source,
        {
            "level",
            "label",
            "coverage_contributes_points",
            "coverage_points",
            "coverage_max_points",
            "coverage_can_hide_score",
        },
    )
    if "coverage" in source:
        public["coverage"] = scalar_map(
            source["coverage"],
            {
                "recording_pct",
                "bcg_pct",
                "sleep_stage_pct",
                "state_attribution_pct",
                "physiological_evidence_pct",
                "environment_pct",
                "ratio",
                "pct",
                "points",
                "max_points",
                "score_component",
            },
        )
    if "confidence" in source:
        public["confidence"] = scalar_map(
            source["confidence"],
            {
                "level",
                "label",
                "session_coverage_pct",
                "timeline_coverage_pct",
                "state_attribution_coverage_pct",
                "physiological_evidence_coverage_pct",
                "paired_hr_rr_coverage_pct",
                "coverage_is_admin_qa_context",
                "coverage_can_hide_score",
            },
        )
    distribution = source.get("confidence_distribution")
    public["confidence_distribution"] = (
        scalar_map(distribution, {"high", "medium", "low"})
        if distribution is not None
        else None
    )
    return public
