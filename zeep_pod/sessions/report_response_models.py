"""Strict nested response contracts for public Session reports.

Historical reports evolved between v10.3 and v10.5, so every field is
optional.  When a section is present, however, undocumented nested keys are
rejected.  This keeps legacy summaries readable without turning their JSON
objects into an unbounded public API surface.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from zeep_pod.sessions._response_model_base import ContractModel


class PublicCycle(ContractModel):
    available: bool | None = None
    completed_nrem_rem_cycles: int | None = Field(default=None, ge=0)
    minimum_nrem_s: float | None = Field(default=None, ge=0)
    method: str | None = None
    clinical_equivalent: bool | None = None
    expected_for_score: int | None = Field(default=None, ge=0)
    score_note: str | None = None
    points: float | None = Field(default=None, ge=0)
    max_points: float | None = Field(default=None, ge=0)


class PublicSleepSummary(ContractModel):
    recording_s: float | None = Field(default=None, ge=0)
    estimated_sleep_s: float | None = Field(default=None, ge=0)
    wake_s: float | None = Field(default=None, ge=0)
    sleep_onset_proxy_s: float | None = Field(default=None, ge=0)
    waso_proxy_s: float | None = Field(default=None, ge=0)
    sleep_efficiency_pct: float | None = Field(default=None, ge=0, le=100)
    actual_scored_s: float | None = Field(default=None, ge=0)
    wake_pct_recorded: float | None = Field(default=None, ge=0, le=100)
    cycles: PublicCycle | None = None
    wake_entries: int | None = Field(default=None, ge=0)
    awakenings: int | None = Field(default=None, ge=0)
    movement_pct: float | None = Field(default=None, ge=0, le=100)
    bed_exit_events: int | None = Field(default=None, ge=0)
    transient_bed_exit_samples: int | None = Field(default=None, ge=0)
    confirmed_bed_exit_samples: int | None = Field(default=None, ge=0)
    weak_breathing_samples: int | None = Field(default=None, ge=0)
    snoring_samples: int | None = Field(default=None, ge=0)


class PublicStageSummary(ContractModel):
    # Older approved reports used display-case labels (for example ``N2``),
    # while current reports use lower-case canonical state keys.
    state: str | None = None
    samples: int | None = Field(default=None, ge=0)
    duration_s: float | None = Field(default=None, ge=0)
    pct_scored: float | None = Field(default=None, ge=0, le=100)
    pct_sleep: float | None = Field(default=None, ge=0, le=100)


class PublicEnvironmentLevelDistribution(ContractModel):
    critical: float | None = Field(default=None, ge=0, le=100)
    poor: float | None = Field(default=None, ge=0, le=100)
    fair: float | None = Field(default=None, ge=0, le=100)
    good: float | None = Field(default=None, ge=0, le=100)
    excellent: float | None = Field(default=None, ge=0, le=100)


class PublicEnvironmentLevelCounts(ContractModel):
    critical: int | None = Field(default=None, ge=0)
    poor: int | None = Field(default=None, ge=0)
    fair: int | None = Field(default=None, ge=0)
    good: int | None = Field(default=None, ge=0)
    excellent: int | None = Field(default=None, ge=0)


class PublicEnvironmentMetric(ContractModel):
    key: str | None = None
    sample_key: str | None = None
    label: str | None = None
    unit: str | None = None
    source: str | None = None
    mode: str | None = None
    target: str | None = None
    expected_floor: str | None = None
    bands: str | None = None
    available: bool | None = None
    required_for_overall: bool | None = None
    coverage_pct: float | None = Field(default=None, ge=0, le=100)
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    outside_target_pct: float | None = Field(default=None, ge=0, le=100)
    below_expected_pct: float | None = Field(default=None, ge=0, le=100)
    outside_direction: Literal["high", "low"] | None = None
    status_key: str | None = None
    status: str | None = None
    rank: int | None = Field(default=None, ge=0)
    decision: str | None = None
    meets_expected: bool | None = None
    level_distribution_pct: PublicEnvironmentLevelDistribution | None = None
    level_counts: PublicEnvironmentLevelCounts | None = None
    aggregation_version: str | None = None
    aggregation_method: str | None = None
    version: str | None = None
    method: str | None = None
    quantile: float | None = Field(default=None, ge=0, le=1)
    peak_status_key: str | None = None
    sample_count: int | None = Field(default=None, ge=0)
    critical_sample_count: int | None = Field(default=None, ge=0)
    critical_sample_pct: float | None = Field(default=None, ge=0, le=100)
    transient_critical_observed: bool | None = None
    safety_threshold: float | None = None
    safety_excursion_observed: bool | None = None
    safety_excursion_sample_count: int | None = Field(default=None, ge=0)
    safety_excursion_sample_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    action: str | None = None


class PublicSafetyExcursion(ContractModel):
    key: str | None = None
    label: str | None = None
    threshold: float | None = None
    maximum: float | None = None
    sample_count: int | None = Field(default=None, ge=0)
    sample_pct: float | None = Field(default=None, ge=0, le=100)


class PublicEnvironmentAssessment(ContractModel):
    version: str | None = None
    aggregation_version: str | None = None
    aggregation_method: str | None = None
    mode: str | None = None
    mode_label: str | None = None
    acceptable_min_level: str | None = None
    acceptable_min_label: str | None = None
    overall_level: str | None = None
    overall_label: str | None = None
    meets_expected: bool | None = None
    required_count: int | None = Field(default=None, ge=0)
    advisory_count: int | None = Field(default=None, ge=0)
    optimisation_count: int | None = Field(default=None, ge=0)
    maintain_count: int | None = Field(default=None, ge=0)
    available_count: int | None = Field(default=None, ge=0)
    expected_count: int | None = Field(default=None, ge=0)
    required_expected_count: int | None = Field(default=None, ge=0)
    blocking_unavailable_count: int | None = Field(default=None, ge=0)
    optional_unavailable_count: int | None = Field(default=None, ge=0)
    assessment_quality: str | None = None
    safety_excursion_observed: bool | None = None
    safety_review_required: bool | None = None
    safety_excursion_count: int | None = Field(default=None, ge=0)
    safety_excursions: list[PublicSafetyExcursion] | None = None
    safety_excursions_change_sustained_assessment: bool | None = None
    safety_excursions_change_score: bool | None = None
    context_only: bool | None = None
    sleep_stage_context_only: bool | None = None
    contributes_to_primary_score: bool | None = None
    primary_score: str | None = None
    max_score_points: float | None = Field(default=None, ge=0)
    direct_stage_influence: bool | None = None
    safety_thresholds_unchanged: bool | None = None


class PublicFinding(ContractModel):
    key: str | None = None
    metric_key: str | None = None
    severity: str | None = None
    level_key: str | None = None
    decision: str | None = None
    title: str | None = None
    detail: str | None = None
    action: str | None = None
    context_only: bool | None = None
    sleep_stage_context_only: bool | None = None
    contributes_to_primary_score: bool | None = None
    legacy_timeline_not_persisted: bool | None = None
    blocks_overall: bool | None = None
    aggregation_version: str | None = None
    peak_status_key: str | None = None
    transient_critical_observed: bool | None = None
    changes_sustained_assessment: bool | None = None
    changes_score: bool | None = None
    threshold: float | None = None
    sample_count: int | None = Field(default=None, ge=0)
    sample_pct: float | None = Field(default=None, ge=0, le=100)


class PublicPostSessionGuidance(ContractModel):
    primary: str | None = None
    next_session: str | None = None
    self_check: str | None = None
    mode: str | None = None
    score_used: float | None = Field(default=None, ge=0, le=100)
    score_released: bool | None = None
    basis: str | None = None
    medical_diagnosis: bool | None = None
    available: bool | None = None
    reason: str | None = None
    score_derived_claims_suppressed: bool | None = None


class PublicReportCoverage(ContractModel):
    recording_pct: float | None = Field(default=None, ge=0, le=100)
    bcg_pct: float | None = Field(default=None, ge=0, le=100)
    sleep_stage_pct: float | None = Field(default=None, ge=0, le=100)
    environment_pct: float | None = Field(default=None, ge=0, le=100)


class PublicConfidenceDistribution(ContractModel):
    high: float | None = Field(default=None, ge=0, le=100)
    medium: float | None = Field(default=None, ge=0, le=100)
    low: float | None = Field(default=None, ge=0, le=100)


class PublicReportDataQuality(ContractModel):
    level: str | None = None
    label: str | None = None
    coverage: PublicReportCoverage | None = None
    confidence_pct: PublicConfidenceDistribution | None = None
    note: str | None = None
