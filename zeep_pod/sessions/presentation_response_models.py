"""Typed contracts for concise results and Admin development diagnostics.

The existing Usage Session v1 resources intentionally remain unchanged for
installed clients.  These additive views give new clients one canonical score
and one presentation hierarchy, rather than asking them to reconcile the same
facts from ``score``, ``restore_summary`` and ``report.quality``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from zeep_pod.sessions._response_model_base import ContractModel
from zeep_pod.sessions.report_response_models import (
    PublicClassificationAccounting,
    PublicEnvironmentAssessment,
    PublicEnvironmentMetric,
)
from zeep_pod.sessions.respiratory_response_models import RespiratoryWellness
from zeep_pod.sessions.restore_response_models import SessionMode
from zeep_pod.sessions.usage_nested_response_models import SleepPolicyVersions
from zeep_pod.sessions.usage_response_models import (
    ApiResponseBase,
    ResultProvenance,
    UsageDataQuality,
    UsageIdentity,
    UsageVersions,
)


class PresentationMode(ContractModel):
    key: SessionMode
    label: str
    sleep_required: bool


class PresentationTiming(ContractModel):
    started_at_utc: datetime | None = Field(...)
    ended_at_utc: datetime | None = Field(...)
    duration_s: float | None = Field(..., ge=0)
    target_duration_s: float | None = Field(..., ge=0)
    target_label: str | None = Field(...)


class PresentationPrimaryResult(ContractModel):
    type: Literal["sleep_score", "recovery_score", "unresolved_score"]
    title: Literal["Sleep Score", "Recovery Score", "Session Score"]
    available: bool
    value: float | None = Field(..., ge=0, le=100)
    status: str
    meaning: str
    reason_code: Literal[
        "available",
        "session_not_closed",
        "mode_unresolved",
        "mode_metadata_conflict",
        "session_too_short",
        "target_unknown",
        "duration_out_of_protocol",
        "insufficient_physiological_evidence",
        "result_unavailable",
    ]
    reason: str | None = Field(...)


class PresentationMetric(ContractModel):
    key: str
    label: str
    value: float | int | None = Field(...)
    unit: str | None = Field(...)
    display_value: str
    available: bool


class PresentationStage(ContractModel):
    key: Literal["wake", "n1", "n2", "n3", "rem"]
    label: str
    duration_s: float = Field(ge=0)
    percentage: float | None = Field(..., ge=0, le=100)


class PresentationSleepStages(ContractModel):
    available: bool
    basis: Literal["display_attributed_time"]
    wellness_estimate: Literal[True]
    medical_diagnosis: Literal[False]
    items: list[PresentationStage]


class PresentationDriver(ContractModel):
    key: str
    label: str
    message: str
    direction: Literal["positive", "attention"]


class PresentationRestProfileItem(ContractModel):
    key: Literal["awake_rest", "drowsy", "estimated_sleep"]
    label: str
    duration_s: float = Field(ge=0)
    percentage: float | None = Field(..., ge=0, le=100)


class PresentationRestProfile(ContractModel):
    available: bool
    basis: Literal["display_attributed_time"]
    sleep_not_required: Literal[True]
    items: list[PresentationRestProfileItem]


class PresentationBaseline(ContractModel):
    available: bool
    label: str
    maturity_label: str
    sessions_used: int = Field(ge=0)
    delta_points: float | None = Field(..., ge=-100, le=100)
    typical_range: tuple[float, float] | None = Field(...)


class PresentationTrendWindow(ContractModel):
    session_count: int = Field(ge=1)
    average: float = Field(ge=0, le=100)


class PresentationTrend(ContractModel):
    available: bool
    label: str
    windows: dict[str, PresentationTrendWindow]


class PresentationSubjectiveOutcome(ContractModel):
    status: Literal["measured", "not_measured"]
    label: str
    freshness_delta: float | None = Field(..., ge=-10, le=10)
    activity_readiness: float | None = Field(..., ge=0, le=10)
    sensor_inferred: Literal[False]


class PresentationEnvironmentMetric(ContractModel):
    key: str
    label: str
    average: float | None = Field(...)
    unit: str | None = Field(...)
    status: str
    available: bool


class PresentationEnvironment(ContractModel):
    available: bool
    status: str
    meets_expected: bool | None = Field(...)
    metrics: list[PresentationEnvironmentMetric]


class PresentationVitalSignals(ContractModel):
    available: bool
    status: str
    heart_rate_bpm: float | None = Field(..., ge=30, le=220)
    respiration_rate_brpm: float | None = Field(..., ge=4, le=60)
    summary: str
    wellness_only: Literal[True]


class UsageSessionPresentation(ContractModel):
    contract_version: Literal["zeep.usage-presentation.v1"]
    audience: Literal["user_summary"]
    session_id: str = Field(min_length=1, max_length=160)
    mode: PresentationMode
    timing: PresentationTiming
    primary_result: PresentationPrimaryResult
    overview_metrics: list[PresentationMetric]
    sleep_stages: PresentationSleepStages | None = Field(...)
    rest_profile: PresentationRestProfile | None = Field(...)
    positive_drivers: list[PresentationDriver]
    attention_drivers: list[PresentationDriver]
    personal_baseline: PresentationBaseline
    trend: PresentationTrend
    subjective_outcome: PresentationSubjectiveOutcome
    recommendation: str
    environment: PresentationEnvironment
    vital_signals: PresentationVitalSignals
    confidence_label: str
    disclaimer: str


class DevelopmentScoreRelease(ContractModel):
    score_available: bool
    validation_status: str | None = Field(...)
    review_required: bool
    formula_version: str | None = Field(...)
    quality_model_version: str | None = Field(...)


class DevelopmentScoreComponents(ContractModel):
    order: list[str]
    labels: dict[str, str]
    earned_points: dict[str, float]
    max_points: dict[str, float]


class DevelopmentReviewFlag(ContractModel):
    code: str
    severity: Literal["info", "review", "safety_review"]
    message: str


class UsageSessionDevelopment(ContractModel):
    contract_version: Literal["zeep.usage-development.v1"]
    audience: Literal["admin_development"]
    session_id: str = Field(min_length=1, max_length=160)
    user: UsageIdentity
    user_summary: UsageSessionPresentation
    score_release: DevelopmentScoreRelease
    data_quality: UsageDataQuality
    score_components: DevelopmentScoreComponents
    classification_accounting: PublicClassificationAccounting | None = None
    environment_assessment: PublicEnvironmentAssessment | None = None
    environment_metrics: list[PublicEnvironmentMetric]
    respiratory_wellness: RespiratoryWellness | None = None
    versions: UsageVersions
    sleep_policy_versions: SleepPolicyVersions
    sleep_estimator_versions: dict[str, int]
    result_provenance: ResultProvenance
    review_flags: list[DevelopmentReviewFlag]
    raw_data_included: Literal[False]


class UsageSessionPresentationResponse(ApiResponseBase):
    kind: Literal["usage_session_presentation"]
    data: UsageSessionPresentation


class UsageSessionDevelopmentResponse(ApiResponseBase):
    kind: Literal["usage_session_development"]
    data: UsageSessionDevelopment
