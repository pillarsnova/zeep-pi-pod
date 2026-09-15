"""Strict response models for the longitudinal user-learning contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from zeep_pod.sessions._response_model_base import ContractModel
from zeep_pod.sessions.usage_response_models import ApiResponseBase


class LearningIdentity(ContractModel):
    email: str | None = Field(...)
    display_name: str | None = Field(...)
    canonical_identifier: str
    identity_type: Literal["email", "legacy_account_key"]


class LearningHistoryScope(ContractModel):
    starts_at_utc: datetime
    completed_sessions_only: Literal[True]
    sessions_without_sensor_data_included: Literal[True]
    raw_sensor_included: Literal[False]


class ObservedHistory(ContractModel):
    session_count: int = Field(ge=0)
    data_backed_session_count: int = Field(ge=0)
    without_sensor_data_count: int = Field(ge=0)
    scored_count: int = Field(ge=0)
    without_score_count: int = Field(ge=0)
    unresolved_mode_count: int = Field(ge=0)
    first_used_at_utc: datetime | None = Field(...)
    last_used_at_utc: datetime | None = Field(...)
    usage_minutes: float = Field(ge=0)
    modes_used: list[Literal["sleep", "nap_recovery"]]


class UserRecentScore(ContractModel):
    session_id: str
    ended_at_utc: datetime | None = Field(...)
    value: float = Field(ge=0, le=100)
    formula_version: str | None = Field(...)


class UserScoreTrend(ContractModel):
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
    label: str
    change_points: float | None = Field(...)
    formula_version: str | None = Field(...)
    comparable_scores: int = Field(ge=0)
    method: Literal["latest_vs_previous_same_formula"]


class UserModeBaseline(ContractModel):
    status: str
    sessions_used: int = Field(ge=0)
    minimum_sessions: int = Field(ge=1)
    typical_duration_minutes: float | None = Field(..., ge=0)
    typical_start_local_hour: float | None = Field(..., ge=0, le=24)
    typical_environment: dict[str, float]
    reference_scope: Literal[
        "prior_completed_same_mode_sessions_only",
        "prior_completed_same_mode_and_target_sessions_only",
    ]
    environment_role: Literal["observed_exposure_not_user_preference"]
    target_specific: bool
    target_key: str | None = Field(...)
    baseline_policy_version: str | None = Field(...)
    score_formula_version: str | None = Field(...)
    score_reference_status: str
    score_sessions_used: int = Field(ge=0)
    score_minimum_sessions: int = Field(ge=1)
    direct_device_control: Literal[False]


class UserTargetHistory(ContractModel):
    key: str
    minutes: float = Field(ge=0)
    session_count: int = Field(ge=1)
    scored_count: int = Field(ge=0)
    comparable_scored_count: int = Field(ge=0)
    without_score_count: int = Field(ge=0)
    latest_score: float | None = Field(..., ge=0, le=100)
    average_score: float | None = Field(..., ge=0, le=100)
    median_score: float | None = Field(..., ge=0, le=100)
    active_formula_version: str | None = Field(...)
    trend: UserScoreTrend
    baseline: UserModeBaseline
    recent_scores: list[UserRecentScore]


class UserModeHistory(ContractModel):
    key: Literal["sleep", "nap_recovery"]
    label: Literal["Overnight Recovery", "Nap & Refresh"]
    score_type: Literal["sleep_score", "recovery_score"]
    score_title: Literal["Sleep Score", "Recovery Score"]
    session_count: int = Field(ge=0)
    data_backed_session_count: int = Field(ge=0)
    without_sensor_data_count: int = Field(ge=0)
    scored_count: int = Field(ge=0)
    comparable_scored_count: int = Field(ge=0)
    without_score_count: int = Field(ge=0)
    first_used_at_utc: datetime | None = Field(...)
    last_used_at_utc: datetime | None = Field(...)
    usage_minutes: float = Field(ge=0)
    typical_duration_minutes: float | None = Field(..., ge=0)
    latest_score: float | None = Field(..., ge=0, le=100)
    average_score: float | None = Field(..., ge=0, le=100)
    median_score: float | None = Field(..., ge=0, le=100)
    active_formula_version: str | None = Field(...)
    trend: UserScoreTrend
    targets: list[UserTargetHistory]
    unresolved_target_session_count: int = Field(ge=0)
    baseline: UserModeBaseline
    recent_scores: list[UserRecentScore]


class UserModes(ContractModel):
    sleep: UserModeHistory
    nap_recovery: UserModeHistory


class QuestionnaireContext(ContractModel):
    consent_status: Literal["pending", "granted", "declined"]
    answered: int = Field(ge=0)
    total: int = Field(ge=0)
    percent: int = Field(ge=0, le=100)
    version: str | None = Field(...)
    answer_values_included: Literal[False]


class UserProfileContext(ContractModel):
    age_group: str | None = Field(...)
    gender: Literal["male", "female", "other", "unspecified"]
    available_fields: list[
        Literal["age", "gender", "height", "weight", "blood_group"]
    ]
    questionnaire: QuestionnaireContext
    role: Literal["wellness_context_only"]
    medical_diagnosis_input: Literal[False]


class UserLearningReadiness(ContractModel):
    status: Literal["no_data", "learning", "growing", "established"]
    label: str
    personal_comparison_ready_modes: list[Literal["sleep", "nap_recovery"]]
    personal_comparison_ready_targets: list[Literal["nap_30", "nap_90"]]
    multi_mode_context_ready: bool
    personalization_data_ready: bool
    personalization_inference_authorized: Literal[False]
    inference_authorization_status: Literal[
        "purpose_specific_consent_unavailable"
    ]
    recommendation_mode: Literal["not_authorized"]
    automatic_device_control: Literal[False]
    sleep_state_direct_control: Literal[False]
    data_gaps: list[str]


class UserAiContract(ContractModel):
    observations_are_facts: Literal[True]
    derived_trends_are_not_medical_findings: Literal[True]
    usage_frequency_is_not_preference: Literal[True]
    environment_history_is_exposure_not_preference: Literal[True]
    cross_mode_score_comparison_allowed: Literal[False]
    questionnaire_answers_used: Literal[False]
    model_training_consent_available: Literal[False]
    purpose_specific_ai_inference_consent_available: Literal[False]
    identity_input_allowed: Literal[False]
    personalized_inference_allowed: Literal[False]
    allowed_output: Literal["none_until_purpose_specific_consent"]
    automatic_actuation_allowed: Literal[False]


class UserLearningProfile(ContractModel):
    contract_version: Literal["zeep.user-learning-profile.v1"]
    policy_version: Literal["zeep.user-learning-policy.v1"]
    user: LearningIdentity
    history_scope: LearningHistoryScope
    observed_history: ObservedHistory
    modes: UserModes
    profile_context: UserProfileContext
    learning_readiness: UserLearningReadiness
    ai_contract: UserAiContract


class UserLearningProfileResponse(ApiResponseBase):
    kind: Literal["user_learning_profile"]
    data: UserLearningProfile


def _resolve_forward_references() -> None:
    """Build schemas eagerly under both supported Pydantic generations."""
    models = (
        LearningIdentity,
        LearningHistoryScope,
        ObservedHistory,
        UserRecentScore,
        UserScoreTrend,
        UserModeBaseline,
        UserTargetHistory,
        UserModeHistory,
        UserModes,
        QuestionnaireContext,
        UserProfileContext,
        UserLearningReadiness,
        UserAiContract,
        UserLearningProfile,
        UserLearningProfileResponse,
    )
    for model in models:
        rebuild = getattr(model, "model_rebuild", None)
        if rebuild is not None:
            rebuild()
        else:  # pragma: no cover - exercised on the Pi's Pydantic v1 image
            model.update_forward_refs(**globals())


_resolve_forward_references()
