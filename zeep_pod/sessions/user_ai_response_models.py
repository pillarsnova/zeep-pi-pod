"""Strict response model for linkable, direct-identifier-free AI context."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from zeep_pod.sessions._response_model_base import ContractModel
from zeep_pod.sessions.usage_response_models import ApiResponseBase

ScoreFormulaVersion = Literal[
    "zeep-sleep-score-v1.0-reviewed",
    "zeep-sleep-score-v2.0-wellness-25-35-20-10-10",
    "zeep-recovery-score-v2.0-reviewed",
    "zeep-recovery-score-v2.1-complete-rest-25-35-30-10",
    "zeep-recovery-score-v3.0-wellness-soft-25-35-30-10",
]
BaselinePolicyVersion = Literal[
    "zeep-personal-behaviour-baseline-v1.1-formula-target-specific"
]
BaselineStatus = Literal["no_data", "learning", "active", "target_required"]
BaselineTargetKey = Literal["overnight_7h", "nap_30", "nap_90"]
NapTargetKey = Literal["nap_30", "nap_90"]
DataGapCode = Literal[
    "no_completed_session_history",
    "sleep_personal_baseline_insufficient",
    "nap_30_personal_baseline_insufficient",
    "nap_90_personal_baseline_insufficient",
    "nap_target_unresolved",
    "sensor_data_missing",
    "score_missing",
    "lifestyle_context_consent_unavailable",
]


class AiObservedHistory(ContractModel):
    session_count: int = Field(ge=0)
    data_backed_session_count: int = Field(ge=0)
    without_sensor_data_count: int = Field(ge=0)
    scored_count: int = Field(ge=0)
    without_score_count: int = Field(ge=0)
    usage_minutes: float = Field(ge=0)
    modes_used: list[Literal["sleep", "nap_recovery"]]


class AiTrend(ContractModel):
    available: bool
    direction: Literal[
        "higher",
        "lower",
        "stable",
        "insufficient_history",
        "formula_changed",
        "formula_unverified",
        "target_specific_only",
    ]
    change_points: float | None = Field(...)
    formula_version: ScoreFormulaVersion | None = Field(...)
    comparable_scores: int = Field(ge=0)


class AiTypicalEnvironment(ContractModel):
    temp_median: float | None = Field(...)
    humidity_median: float | None = Field(...)
    co2_median: float | None = Field(...)
    lux_median: float | None = Field(...)
    sound_median: float | None = Field(...)


class AiBaseline(ContractModel):
    status: BaselineStatus
    sessions_used: int = Field(ge=0)
    minimum_sessions: int = Field(ge=1)
    typical_duration_minutes: float | None = Field(..., ge=0)
    typical_environment: AiTypicalEnvironment
    target_specific: bool
    target_key: BaselineTargetKey | None = Field(...)
    baseline_policy_version: BaselinePolicyVersion | None = Field(...)
    score_formula_version: ScoreFormulaVersion | None = Field(...)
    score_reference_status: BaselineStatus
    score_sessions_used: int = Field(ge=0)
    score_minimum_sessions: int = Field(ge=1)
    environment_is_observed_exposure: Literal[True]


class AiTarget(ContractModel):
    key: NapTargetKey
    minutes: Literal[30.0, 90.0]
    session_count: int = Field(ge=1)
    scored_count: int = Field(ge=0)
    comparable_scored_count: int = Field(ge=0)
    without_score_count: int = Field(ge=0)
    latest_score: float | None = Field(..., ge=0, le=100)
    average_score: float | None = Field(..., ge=0, le=100)
    median_score: float | None = Field(..., ge=0, le=100)
    active_formula_version: ScoreFormulaVersion | None = Field(...)
    trend: AiTrend
    baseline: AiBaseline


class AiMode(ContractModel):
    key: Literal["sleep", "nap_recovery"]
    score_type: Literal["sleep_score", "recovery_score"]
    session_count: int = Field(ge=0)
    data_backed_session_count: int = Field(ge=0)
    without_sensor_data_count: int = Field(ge=0)
    scored_count: int = Field(ge=0)
    latest_score: float | None = Field(..., ge=0, le=100)
    average_score: float | None = Field(..., ge=0, le=100)
    median_score: float | None = Field(..., ge=0, le=100)
    active_formula_version: ScoreFormulaVersion | None = Field(...)
    trend: AiTrend
    targets: list[AiTarget]
    unresolved_target_session_count: int = Field(ge=0)
    baseline: AiBaseline


class AiModes(ContractModel):
    sleep: AiMode
    nap_recovery: AiMode


class AiLearningReadiness(ContractModel):
    data_sufficiency_status: Literal[
        "no_data",
        "learning",
        "growing",
        "established",
    ]
    personal_comparison_ready_modes: list[Literal["sleep", "nap_recovery"]]
    personal_comparison_ready_targets: list[NapTargetKey]
    multi_mode_context_ready: bool
    personalization_data_ready: bool
    personalization_inference_authorized: Literal[False]
    inference_authorization_status: Literal[
        "purpose_specific_consent_unavailable"
    ]
    data_gap_codes: list[DataGapCode]


class AiGuardrails(ContractModel):
    wellness_advisory_only: Literal[True]
    privacy_classification: Literal[
        "direct_identifier_free_linkable_personal_wellness_data"
    ]
    direct_identifiers_included: Literal[False]
    linkable_personal_wellness_data: Literal[True]
    anonymous_or_deidentified: Literal[False]
    session_identifiers_included: Literal[False]
    exact_session_timestamps_included: Literal[False]
    questionnaire_answers_included: Literal[False]
    demographics_included: Literal[False]
    medical_inference_allowed: Literal[False]
    personalized_inference_allowed: Literal[False]
    model_training_allowed: Literal[False]
    cross_user_learning_allowed: Literal[False]
    automatic_device_control_allowed: Literal[False]
    recommendation_requires_user_confirmation: Literal[True]


class UserAiContext(ContractModel):
    contract_version: Literal["zeep.user-ai-context.v1"]
    source_profile_version: Literal["zeep.user-learning-profile.v1"]
    source_policy_version: Literal["zeep.user-learning-policy.v1"]
    observed_history: AiObservedHistory
    modes: AiModes
    learning_readiness: AiLearningReadiness
    guardrails: AiGuardrails


class UserAiContextResponse(ApiResponseBase):
    kind: Literal["user_ai_context"]
    data: UserAiContext


def _resolve_forward_references() -> None:
    """Build schemas eagerly under both supported Pydantic generations."""
    models = (
        AiObservedHistory,
        AiTrend,
        AiTypicalEnvironment,
        AiBaseline,
        AiTarget,
        AiMode,
        AiModes,
        AiLearningReadiness,
        AiGuardrails,
        UserAiContext,
        UserAiContextResponse,
    )
    for model in models:
        rebuild = getattr(model, "model_rebuild", None)
        if rebuild is not None:
            rebuild()
        else:  # pragma: no cover - exercised on the Pi's Pydantic v1 image
            model.update_forward_refs(**globals())


_resolve_forward_references()
