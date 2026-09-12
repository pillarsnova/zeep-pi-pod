"""Strict nested contracts reused by public Usage Session responses."""

from __future__ import annotations

from pydantic import Field, validator

from zeep_pod.sessions._response_model_base import ContractModel
from zeep_pod.sessions.restore_response_models import SessionMode


class ProtocolTargetSnapshot(ContractModel):
    available: bool | None = None
    valid: bool | None = None
    group: SessionMode | None = None
    key: str | None = None
    label: str | None = None
    seconds: float | None = Field(default=None, ge=0)
    minutes: float | None = Field(default=None, ge=0)
    source: str | None = None
    review_required: bool | None = None
    supported_seconds: list[float] | None = None
    recommended_range_seconds: tuple[float, float] | None = None
    extended_max_seconds: float | None = Field(default=None, ge=0)

    @validator("supported_seconds")
    def supported_values_must_be_nonnegative(cls, value: list[float] | None):
        if value is not None and any(item < 0 for item in value):
            raise ValueError("supported target durations must be nonnegative")
        return value

    @validator("recommended_range_seconds")
    def recommended_range_must_be_ordered(
        cls,
        value: tuple[float, float] | None,
    ):
        if value is not None and not 0 <= value[0] <= value[1]:
            raise ValueError("recommended target range must be ordered")
        return value


class UsageProtocolStatus(ContractModel):
    available: bool | None = None
    canonical_mode: SessionMode | None = None
    observed_seconds: float | None = Field(default=None, ge=0)
    minimum_seconds: float | None = Field(default=None, ge=0)
    maximum_seconds: float | None = Field(default=None, ge=0)
    recommended_range_seconds: tuple[float, float] | None = None
    within_operational_window: bool | None = None
    within_recommended_range: bool | None = None
    status: str | None = None
    display_status: str | None = None
    observed_timing_band: str | None = None
    review_required: bool | None = None
    score_releasable: bool | None = None
    minimum_score_seconds: float | None = Field(default=None, ge=0)
    legacy_hard_max_seconds: float | None = Field(default=None, ge=0)
    extended_max_seconds: float | None = Field(default=None, ge=0)
    target: ProtocolTargetSnapshot | None = None
    reason: str | None = None

    @validator("recommended_range_seconds")
    def recommended_range_must_be_ordered(
        cls,
        value: tuple[float, float] | None,
    ):
        if value is not None and not 0 <= value[0] <= value[1]:
            raise ValueError("recommended protocol range must be ordered")
        return value


class UsageCoverage(ContractModel):
    recording_pct: float | None = Field(default=None, ge=0, le=100)
    bcg_pct: float | None = Field(default=None, ge=0, le=100)
    sleep_stage_pct: float | None = Field(default=None, ge=0, le=100)
    state_attribution_pct: float | None = Field(default=None, ge=0, le=100)
    physiological_evidence_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    environment_pct: float | None = Field(default=None, ge=0, le=100)
    ratio: float | None = Field(default=None, ge=0, le=1)
    pct: float | None = Field(default=None, ge=0, le=100)
    points: float | None = Field(default=None, ge=0)
    max_points: float | None = Field(default=None, ge=0)
    score_component: bool | None = None


class UsageConfidence(ContractModel):
    level: str | None = None
    label: str | None = None
    session_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    timeline_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    state_attribution_coverage_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    physiological_evidence_coverage_pct: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )
    paired_hr_rr_coverage_pct: float | None = Field(default=None, ge=0, le=100)
    coverage_is_admin_qa_context: bool | None = None
    coverage_can_hide_score: bool | None = None


class UsageConfidenceDistribution(ContractModel):
    high: float | None = Field(default=None, ge=0, le=100)
    medium: float | None = Field(default=None, ge=0, le=100)
    low: float | None = Field(default=None, ge=0, le=100)


class SleepPolicyVersions(ContractModel):
    evidence: str | None = None
    baseline: str | None = None
    transition: str | None = None
    g2_ontology: str | None = None
    terminal_wake: str | None = None
