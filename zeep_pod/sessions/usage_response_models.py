"""Pydantic response contracts for the public Usage Session endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, root_validator, validator

from zeep_pod.sessions._response_model_base import ContractModel
from zeep_pod.sessions.quality_response_models import (
    PublicArchitecture,
    PublicBodyResponse,
    PublicComponentLabels,
    PublicComponentPoints,
    PublicContinuity,
    PublicDurationTarget,
    PublicEnvironmentSupport,
    PublicPhysiology,
    PublicQualityCycle,
    PublicQualityDataCoverage,
    PublicScoreConfidence,
    PublicSleepOpportunity,
    PublicStagePercentages,
    QualityComponentKey,
)
from zeep_pod.sessions.report_response_models import (
    PublicEnvironmentAssessment,
    PublicEnvironmentMetric,
    PublicFinding,
    PublicPostSessionGuidance,
    PublicReportDataQuality,
    PublicSleepSummary,
    PublicStageSummary,
)
from zeep_pod.sessions.respiratory_response_models import RespiratoryWellness
from zeep_pod.sessions.restore_response_models import (
    RestoreSummary,
    ScoreMode,
    ScoreType,
    SessionMode,
)
from zeep_pod.sessions.usage_nested_response_models import (
    SleepPolicyVersions,
    UsageConfidence,
    UsageConfidenceDistribution,
    UsageCoverage,
    UsageProtocolStatus,
)


def _model_dump(value: ContractModel) -> dict[str, Any]:
    method = getattr(value, "model_dump", None)
    if method:
        return method(by_alias=True)
    return value.dict(by_alias=True)


def _fields_set(value: ContractModel) -> set[str]:
    fields = getattr(value, "model_fields_set", None)
    if fields is not None:
        return set(fields)
    return set(value.__fields_set__)


class UsageIdentity(ContractModel):
    email: str | None = Field(...)
    display_name: str | None = Field(...)
    canonical_identifier: str | None = Field(...)
    identity_type: Literal["email", "legacy_account_key"]


class ModeConflict(ContractModel):
    source: Literal[
        "session.rest_mode",
        "released_quality",
        "session_report.rest_mode",
    ]
    reported_groups: list[ScoreMode]
    canonical_group: SessionMode


class UsageTarget(ContractModel):
    key: str | None = Field(...)
    label: str | None = Field(...)
    seconds: float | None = Field(..., ge=0)
    minutes: float | None = Field(..., ge=0)
    recommended_range_minutes: tuple[float, float] | None = Field(...)
    completion_pct: float | None = Field(..., ge=0, le=100)
    protocol_status: UsageProtocolStatus

    @validator("recommended_range_minutes")
    def recommended_range_must_be_ordered(
        cls,
        value: tuple[float, float] | None,
    ):
        if value is not None and not 0 <= value[0] <= value[1]:
            raise ValueError("recommended range must be ordered and nonnegative")
        return value


class UsageMode(ContractModel):
    key: SessionMode
    label: str
    requested: SessionMode
    resolved: str | None = Field(...)
    sleep_required: bool
    target: UsageTarget | None = Field(...)
    review_required: bool
    validation_status: Literal[
        "mode_confirmed",
        "mode_unresolved",
        "mode_metadata_conflict",
    ]
    conflicts: list[ModeConflict]

    @root_validator(skip_on_failure=True)
    def canonical_mode_policy_must_be_consistent(cls, values: dict[str, Any]):
        key = values["key"]
        status = values["validation_status"]
        if values["requested"] != key:
            raise ValueError("requested mode must match the canonical mode key")
        if values["sleep_required"] != (key == "sleep"):
            raise ValueError("sleep_required must match the canonical mode")
        if values["review_required"] != (status != "mode_confirmed"):
            raise ValueError("review_required must match mode validation status")
        if status == "mode_confirmed" and (key == "unknown" or values["conflicts"]):
            raise ValueError("a confirmed mode cannot be unknown or have conflicts")
        if status == "mode_unresolved" and key != "unknown":
            raise ValueError("mode_unresolved requires key='unknown'")
        if status == "mode_metadata_conflict" and not values["conflicts"]:
            raise ValueError("mode_metadata_conflict requires conflict details")
        return values


class AvailableUsageScore(ContractModel):
    type: Literal["sleep_score", "recovery_score"]
    title: Literal["Sleep Score", "Recovery Score"]
    value: float = Field(ge=0, le=100)
    available: Literal[True]
    level: str | None = Field(...)
    formula_version: str | None = Field(...)
    quality_model_version: str | None = Field(...)
    validation_status: str | None = Field(...)
    clinical_validated: bool
    reason: str | None = Field(...)
    review_required: bool

    @root_validator(skip_on_failure=True)
    def title_must_match_score_type(cls, values: dict[str, Any]):
        expected = {
            "sleep_score": "Sleep Score",
            "recovery_score": "Recovery Score",
        }
        if values.get("title") != expected.get(values.get("type")):
            raise ValueError("score title must match score type")
        return values


class UnavailableUsageScore(ContractModel):
    type: ScoreType
    title: Literal["Sleep Score", "Recovery Score", "Session Score"]
    value: None = Field(...)
    available: Literal[False]
    level: None = Field(...)
    formula_version: str | None = Field(...)
    quality_model_version: str | None = Field(...)
    validation_status: str | None = Field(...)
    clinical_validated: Literal[False]
    reason: str | None = Field(...)
    review_required: bool

    @root_validator(skip_on_failure=True)
    def title_must_match_score_type(cls, values: dict[str, Any]):
        expected = {
            "sleep_score": "Sleep Score",
            "recovery_score": "Recovery Score",
            "unresolved_score": "Session Score",
        }
        if values.get("title") != expected.get(values.get("type")):
            raise ValueError("score title must match score type")
        return values


UsageScore = AvailableUsageScore | UnavailableUsageScore


class UsageDataQuality(ContractModel):
    level: str | None = Field(...)
    label: str | None = Field(...)
    coverage: UsageCoverage
    confidence: UsageConfidence
    confidence_distribution: UsageConfidenceDistribution | None = Field(...)
    coverage_contributes_points: bool
    coverage_points: float | None = Field(...)
    coverage_max_points: float | None = Field(...)
    coverage_can_hide_score: Literal[False]


class UsageVersions(ContractModel):
    result_contract: str
    session_report: str | None = Field(...)
    score_formula: str | None = Field(...)
    score_quality_model: str | None = Field(...)
    restore_summary: str
    product_language: str


class ResultProvenance(ContractModel):
    source: Literal["display_recomputed_report", "persisted_final_summary"]
    display_recomputed: bool
    display_recomputed_from_version: str | None = Field(...)
    persisted_record_unchanged: bool
    score_recalculated_by_adapter: Literal[False]


class PublicQuality(ContractModel):
    """Exact top-level allowlist for the embedded, versioned quality result."""

    available: bool | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    reason: str | None = None
    score_title: str | None = None
    score_scope: str | None = None
    validation_status: str | None = None
    clinical_validated: bool | None = None
    quality_type: Literal["sleep", "rest_goal"] | None = None
    session_character: str | None = None
    sleep_detected: bool | None = None
    level: str | None = None
    level_key: str | None = None
    insight: str | None = None
    estimated_sleep_s: float | None = Field(default=None, ge=0)
    actual_scored_s: float | None = Field(default=None, ge=0)
    wake_s: float | None = Field(default=None, ge=0)
    wake_pct_recorded: float | None = Field(default=None, ge=0, le=100)
    sleep_efficiency_pct: float | None = Field(default=None, ge=0, le=100)
    awakenings: int | None = Field(default=None, ge=0)
    wake_entries: int | None = Field(default=None, ge=0)
    deep_pct: float | None = Field(default=None, ge=0, le=100)
    rem_pct: float | None = Field(default=None, ge=0, le=100)
    stage_pct_of_sleep: PublicStagePercentages | None = None
    rest_mode: UsageMode | None = None
    duration_target: PublicDurationTarget | None = None
    physiology: PublicPhysiology | None = None
    body_response: PublicBodyResponse | None = None
    environment_support: PublicEnvironmentSupport | None = None
    sleep_opportunity: PublicSleepOpportunity | None = None
    architecture: PublicArchitecture | None = None
    continuity: PublicContinuity | None = None
    data_coverage: PublicQualityDataCoverage | None = None
    cycles: PublicQualityCycle | None = None
    component_points: PublicComponentPoints | None = None
    component_max_points: PublicComponentPoints | None = None
    component_order: list[QualityComponentKey] | None = None
    component_labels: PublicComponentLabels | None = None
    score_confidence: PublicScoreConfidence | None = None
    score_basis: str | None = None
    formula_version: str | None = None
    version: str | None = None
    outcome_interpretation: str | None = None
    disclaimer: str | None = None


class PublicSessionReport(ContractModel):
    """Exact top-level allowlist for the embedded, versioned report."""

    available: bool | None = None
    reason: str | None = None
    version: str | None = None
    product_positioning: str | None = None
    intended_use: str | None = None
    timeline_schema_version: int | str | None = None
    estimator_version: str | None = None
    headline: str | None = None
    insight: str | None = None
    quality: PublicQuality | None = None
    rest_mode: UsageMode | None = None
    sleep: PublicSleepSummary | None = None
    stages: list[PublicStageSummary] | None = None
    environment: list[PublicEnvironmentMetric] | None = None
    environment_assessment: PublicEnvironmentAssessment | None = None
    findings: list[PublicFinding] | None = None
    post_session_guidance: PublicPostSessionGuidance | None = None
    restore_summary: RestoreSummary | None = None
    respiratory_wellness: RespiratoryWellness | None = None
    data_quality: PublicReportDataQuality | None = None
    disclaimer: str | None = None


class UsageSessionSummary(ContractModel):
    contract_version: Literal["zeep.usage-session.v1"]
    session_id: str = Field(min_length=1, max_length=160)
    user: UsageIdentity
    started_at_utc: datetime | None = Field(...)
    ended_at_utc: datetime | None = Field(...)
    duration_s: float | None = Field(..., ge=0)
    end_reason: str | None = Field(...)
    sample_count: int | None = Field(..., ge=0)
    mode: UsageMode
    score: UsageScore
    restore_summary: RestoreSummary
    data_quality: UsageDataQuality
    versions: UsageVersions
    result_provenance: ResultProvenance
    session_closed: bool
    score_revision_policy: Literal["versioned_recalculation_with_audit"]

    @root_validator(skip_on_failure=True)
    def mode_score_and_restore_summary_must_agree(cls, values: dict[str, Any]):
        mode = values["mode"].key
        score = values["score"]
        restore = values["restore_summary"]
        expected_score_type = {
            "sleep": "sleep_score",
            "nap_recovery": "recovery_score",
            "unknown": "unresolved_score",
        }[mode]
        if score.type != expected_score_type:
            raise ValueError("score type must match the canonical Session mode")
        if restore.session_scope.mode != mode:
            raise ValueError("Restore Summary mode must match the Session mode")
        if restore.personal_baseline.mode != mode:
            raise ValueError("Personal Baseline mode must match the Session mode")
        if restore.source_score.type != score.type:
            raise ValueError("Restore Summary must reference the released score type")
        if restore.source_score.available != score.available:
            raise ValueError(
                "Restore Summary availability must match the released score"
            )
        if restore.source_score.value != score.value:
            raise ValueError("Restore Summary must copy the released score value")
        if restore.source_score.formula_version != score.formula_version:
            raise ValueError("Restore Summary must copy the score formula version")
        return values


class UsageSessionDetail(UsageSessionSummary):
    report: PublicSessionReport
    sleep_policy_versions: SleepPolicyVersions
    sleep_estimator_versions: dict[str, int]

    @validator("sleep_estimator_versions")
    def estimator_counts_must_be_nonnegative(cls, value: dict[str, int]):
        if any(not key.strip() or count < 0 for key, count in value.items()):
            raise ValueError("estimator versions need named, nonnegative counts")
        return value

    @root_validator(skip_on_failure=True)
    def embedded_report_must_match_canonical_result(cls, values: dict[str, Any]):
        report = values["report"]
        mode = values["mode"]
        score = values["score"]
        restore = values["restore_summary"]
        if report.rest_mode is not None and _model_dump(
            report.rest_mode
        ) != _model_dump(mode):
            raise ValueError("report mode must match the canonical Session mode")
        if report.quality is not None:
            cls._validate_report_quality(report.quality, mode, score)
        if report.restore_summary is not None and _model_dump(
            report.restore_summary
        ) != _model_dump(restore):
            raise ValueError("report Restore Summary must match the canonical summary")
        return values

    @staticmethod
    def _validate_report_quality(
        quality: PublicQuality,
        mode: UsageMode,
        score: UsageScore,
    ) -> None:
        comparisons = {
            "available": score.available,
            "score": score.value,
            "score_title": score.title,
            "formula_version": score.formula_version,
            "validation_status": score.validation_status,
            "clinical_validated": score.clinical_validated,
            "level": score.level,
        }
        present = _fields_set(quality)
        for field, expected in comparisons.items():
            if field in present and getattr(quality, field) != expected:
                raise ValueError(f"report quality {field} must match released score")
        if quality.rest_mode is not None and _model_dump(
            quality.rest_mode
        ) != _model_dump(mode):
            raise ValueError("report quality mode must match canonical Session mode")


class UsageHistorySummary(ContractModel):
    people_count: int = Field(ge=0)
    session_count: int = Field(ge=0)
    sleep_score_count: int = Field(ge=0)
    recovery_score_count: int = Field(ge=0)
    awaiting_score_count: int = Field(ge=0)
    average_sleep_score: float | None = Field(..., ge=0, le=100)
    average_recovery_score: float | None = Field(..., ge=0, le=100)


class UsagePagination(ContractModel):
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)
    returned: int = Field(ge=0)
    total: int = Field(ge=0)
    has_more: bool


class UsageHistoryRange(ContractModel):
    start_utc: datetime
    end_utc: datetime
    start_local: datetime
    end_local: datetime
    timezone: str
    day_assignment: Literal["session_end_local_date"]


class UsageSessionList(ContractModel):
    contract_version: Literal["zeep.usage-session.v1"]
    history_name: Literal["usage_history"]
    items: list[UsageSessionSummary]
    summary: UsageHistorySummary
    pagination: UsagePagination
    range: UsageHistoryRange | None = None
    history_start_utc: datetime


class ApiResponseBase(ContractModel):
    # ``schema`` shadows a BaseModel method under Pydantic v1.
    schema_: Literal["zeep.api.response"] = Field(alias="schema")
    api_version: Literal["1.0"]
    generated_at: datetime
    request_id: UUID


class UsageSessionListResponse(ApiResponseBase):
    kind: Literal["usage_session_list"]
    data: UsageSessionList


class UsageSessionSummaryResponse(ApiResponseBase):
    kind: Literal["usage_session_summary"]
    data: UsageSessionSummary


class UsageSessionDetailResponse(ApiResponseBase):
    kind: Literal["usage_session_detail"]
    data: UsageSessionDetail
