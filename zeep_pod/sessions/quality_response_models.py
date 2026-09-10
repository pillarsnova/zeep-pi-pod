"""Strict nested contracts for published Sleep and Recovery quality data.

All fields remain optional because approved historical results can come from
different quality-model versions.  A present section is nevertheless closed:
unknown keys are rejected by :class:`ContractModel` rather than becoming an
accidental public API surface.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, validator

from zeep_pod.sessions._response_model_base import ContractModel
from zeep_pod.sessions.report_response_models import (
    PublicCycle,
    PublicEnvironmentMetric,
    PublicSafetyExcursion,
)

QualityComponentKey = Literal[
    "sleep_opportunity",
    "sleep_stability",
    "restorative_architecture",
    "cycle_expression",
    "data_coverage",
    "goal_duration",
    "physiological_response",
    "body_stillness",
    "rest_continuity",
    "environment_support",
]


class PublicStagePercentages(ContractModel):
    wake: float | None = Field(default=None, ge=0, le=100)
    n1: float | None = Field(default=None, ge=0, le=100)
    n2: float | None = Field(default=None, ge=0, le=100)
    n3: float | None = Field(default=None, ge=0, le=100)
    rem: float | None = Field(default=None, ge=0, le=100)
    mode_adjusted_balance: float | None = Field(default=None, ge=0, le=100)


class PublicDurationTarget(ContractModel):
    available: bool | None = None
    group: str | None = None
    key: str | None = None
    label: str | None = None
    seconds: float | None = Field(default=None, ge=0)
    minutes: float | None = Field(default=None, ge=0)
    target_minutes: float | None = Field(default=None, ge=0)
    hours: float | None = Field(default=None, ge=0)
    review_required: bool | None = None
    source: str | None = None
    valid: bool | None = None
    eligible_rest_seconds: float | None = Field(default=None, ge=0)
    eligible_rest_minutes: float | None = Field(default=None, ge=0)
    completion_pct: float | None = Field(default=None, ge=0, le=100)
    basis: str | None = None
    extended_max_seconds: float | None = Field(default=None, ge=0)
    supported_seconds: list[float] | None = None
    recommended_range_seconds: tuple[float, float] | None = None
    recommended_range_minutes: tuple[float, float] | None = None

    @validator("supported_seconds")
    def supported_seconds_must_be_nonnegative(cls, value: list[float] | None):
        if value is not None and any(item < 0 for item in value):
            raise ValueError("supported durations must be nonnegative")
        return value

    @validator("recommended_range_seconds", "recommended_range_minutes")
    def recommended_range_must_be_ordered(
        cls,
        value: tuple[float, float] | None,
    ):
        if value is not None and not 0 <= value[0] <= value[1]:
            raise ValueError("recommended range must be ordered and nonnegative")
        return value


class PublicPhysiology(ContractModel):
    available: bool | None = None
    heart_rate_average: float | None = Field(default=None, ge=0)
    respiration_average: float | None = Field(default=None, ge=0)
    regularity_factor: float | None = Field(default=None, ge=0, le=1)
    heart_rate_regularity_factor: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    respiration_regularity_factor: float | None = Field(
        default=None,
        ge=0,
        le=1,
    )
    settling_factor: float | None = Field(default=None, ge=0, le=1)
    paired_hr_rr_samples: int | None = Field(default=None, ge=0)
    source_sensor_samples: int | None = Field(default=None, ge=0)
    paired_hr_rr_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    method: str | None = None


class PublicBodyResponse(ContractModel):
    available: bool | None = None
    movement_pct: float | None = Field(default=None, ge=0, le=100)
    bed_exit_events: int | None = Field(default=None, ge=0)
    transient_bed_exit_samples: int | None = Field(default=None, ge=0)


class PublicSensorAverages(ContractModel):
    temp: float | None = None
    hum: float | None = None
    lux: float | None = None
    dba: float | None = None
    co2: float | None = None
    pm2_5: float | None = None
    voc: float | None = None


class PublicSensorFit(ContractModel):
    temp: float | None = Field(default=None, ge=0, le=1)
    hum: float | None = Field(default=None, ge=0, le=1)
    lux: float | None = Field(default=None, ge=0, le=1)
    dba: float | None = Field(default=None, ge=0, le=1)
    co2: float | None = Field(default=None, ge=0, le=1)
    pm2_5: float | None = Field(default=None, ge=0, le=1)
    voc: float | None = Field(default=None, ge=0, le=1)


class PublicEnvironmentSupport(ContractModel):
    available: bool | None = None
    quality_factor: float | None = Field(default=None, ge=0, le=1)
    coverage_pct: float | None = Field(default=None, ge=0, le=100)
    available_factors: int | None = Field(default=None, ge=0)
    expected_factors: int | None = Field(default=None, ge=0)
    policy_version: str | None = None
    aggregation_version: str | None = None
    aggregation_method: str | None = None
    overall_level: str | None = None
    overall_label: str | None = None
    meets_expected: bool | None = None
    context_only: bool | None = None
    sleep_stage_context_only: bool | None = None
    contributes_to_primary_score: bool | None = None
    primary_score: str | None = None
    max_points: float | None = Field(default=None, ge=0)
    points: float | None = Field(default=None, ge=0)
    assessment_quality: str | None = None
    blocking_unavailable_count: int | None = Field(default=None, ge=0)
    optional_unavailable_count: int | None = Field(default=None, ge=0)
    safety_excursion_observed: bool | None = None
    safety_review_required: bool | None = None
    safety_excursions_change_score: bool | None = None
    averages: PublicSensorAverages | None = None
    fit: PublicSensorFit | None = None
    metrics: list[PublicEnvironmentMetric] | None = None
    safety_excursions: list[PublicSafetyExcursion] | None = None


class PublicLatency(ContractModel):
    available: bool | None = None
    seconds: float | None = Field(default=None, ge=0)
    points: float | None = Field(default=None, ge=0)
    max_points: float | None = Field(default=None, ge=0)
    basis: str | None = None


class PublicSleepOpportunity(ContractModel):
    duration_points: float | None = Field(default=None, ge=0)
    duration_max_points: float | None = Field(default=None, ge=0)
    latency: PublicLatency | None = None


class PublicArchitecturePoints(ContractModel):
    wake: float | None = Field(default=None, ge=0)
    n1: float | None = Field(default=None, ge=0)
    n2: float | None = Field(default=None, ge=0)
    n3: float | None = Field(default=None, ge=0)
    rem: float | None = Field(default=None, ge=0)
    mode_adjusted_balance: float | None = Field(default=None, ge=0)


class PublicArchitecture(ContractModel):
    points: PublicArchitecturePoints | None = None
    max_points: PublicArchitecturePoints | None = None
    total: float | None = Field(default=None, ge=0)
    method: str | None = None
    mode_adjusted: bool | None = None


class PublicArousalThresholds(ContractModel):
    bcg_amplitude_shift_ratio: float | None = Field(default=None, ge=0)
    movement_ratio: float | None = Field(default=None, ge=0)
    prior_sleep_s: float | None = Field(default=None, ge=0)
    quiet_gap_s: float | None = Field(default=None, ge=0)


class PublicArousalProxy(ContractModel):
    available: bool | None = None
    episodes: int | None = Field(default=None, ge=0)
    index_per_hour: float | None = Field(default=None, ge=0)
    evidence_windows: int | None = Field(default=None, ge=0)
    available_windows: int | None = Field(default=None, ge=0)
    penalty_points: float | None = Field(default=None, ge=0)
    validated_cortical_arousal: bool | None = None
    method: str | None = None
    thresholds: PublicArousalThresholds | None = None


class PublicContinuity(ContractModel):
    wake_points: float | None = Field(default=None, ge=0)
    wake_max_points: float | None = Field(default=None, ge=0)
    efficiency_points: float | None = Field(default=None, ge=0)
    efficiency_max_points: float | None = Field(default=None, ge=0)
    balanced_arousal_penalty_points: float | None = Field(default=None, ge=0)
    arousal_proxy: PublicArousalProxy | None = None


class PublicQualityDataCoverage(ContractModel):
    ratio: float | None = Field(default=None, ge=0, le=1)
    pct: float | None = Field(default=None, ge=0, le=100)
    points: float | None = Field(default=None, ge=0)
    max_points: float | None = Field(default=None, ge=0)
    score_component: bool | None = None
    environment_pct: float | None = Field(default=None, ge=0, le=100)


class PublicComponentPoints(ContractModel):
    sleep_opportunity: float | None = Field(default=None, ge=0)
    sleep_stability: float | None = Field(default=None, ge=0)
    restorative_architecture: float | None = Field(default=None, ge=0)
    cycle_expression: float | None = Field(default=None, ge=0)
    data_coverage: float | None = Field(default=None, ge=0)
    goal_duration: float | None = Field(default=None, ge=0)
    physiological_response: float | None = Field(default=None, ge=0)
    body_stillness: float | None = Field(default=None, ge=0)
    rest_continuity: float | None = Field(default=None, ge=0)
    environment_support: float | None = Field(default=None, ge=0)


class PublicComponentLabels(ContractModel):
    sleep_opportunity: str | None = None
    sleep_stability: str | None = None
    restorative_architecture: str | None = None
    cycle_expression: str | None = None
    data_coverage: str | None = None
    goal_duration: str | None = None
    physiological_response: str | None = None
    body_stillness: str | None = None
    rest_continuity: str | None = None
    environment_support: str | None = None


class PublicScoreConfidence(ContractModel):
    level: str | None = None
    label: str | None = None
    session_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    paired_hr_rr_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    coverage_is_admin_qa_context: bool | None = None
    coverage_can_hide_score: bool | None = None


PublicQualityCycle = PublicCycle
