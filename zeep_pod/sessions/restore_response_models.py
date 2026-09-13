"""Pydantic response contract for ZEEP Restore Summary.

The module uses the Pydantic v1 API subset retained by Pydantic v2.  Its
available/unavailable unions make nullability and score-release boundaries
visible to OpenAPI clients instead of relying on prose alone.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, root_validator, validator

from zeep_pod.sessions._response_model_base import ContractModel

ScoreType = Literal["sleep_score", "recovery_score", "unresolved_score"]
SessionMode = Literal["sleep", "nap_recovery", "unknown"]
ScoreMode = Literal["sleep", "nap_recovery"]
DriverDirection = Literal["positive", "attention"]
ConfidenceLevel = Literal["high", "medium", "low", "unknown"]
EnvironmentSeverity = Literal[
    "excellent",
    "good",
    "fair",
    "poor",
    "critical",
    "unavailable",
]

_STATUS_BANDS = {
    "sleep_restore_very_good": (85, 100),
    "sleep_restore_good": (70, 84),
    "pace_morning": (50, 69),
    "prioritise_rest": (0, 49),
    "rest_goal_full": (85, 100),
    "rest_good": (70, 84),
    "rest_partial": (50, 69),
    "rest_more": (0, 49),
}


class AvailableRestoreSourceScore(ContractModel):
    type: Literal["sleep_score", "recovery_score"]
    title: Literal["Sleep Score", "Recovery Score"]
    value: float = Field(ge=0, le=100)
    available: Literal[True]
    formula_version: str | None = Field(...)
    copied_without_recalculation: Literal[True]

    @root_validator(skip_on_failure=True)
    def title_must_match_score_type(cls, values: dict[str, Any]):
        expected = {
            "sleep_score": "Sleep Score",
            "recovery_score": "Recovery Score",
        }
        if values.get("title") != expected.get(values.get("type")):
            raise ValueError("source score title must match source score type")
        return values


class UnavailableRestoreSourceScore(ContractModel):
    type: ScoreType
    title: Literal["Sleep Score", "Recovery Score", "Session Score"]
    value: None = Field(...)
    available: Literal[False]
    formula_version: str | None = Field(...)
    copied_without_recalculation: Literal[True]

    @root_validator(skip_on_failure=True)
    def title_must_match_score_type(cls, values: dict[str, Any]):
        expected = {
            "sleep_score": "Sleep Score",
            "recovery_score": "Recovery Score",
            "unresolved_score": "Session Score",
        }
        if values.get("title") != expected.get(values.get("type")):
            raise ValueError("source score title must match source score type")
        return values


RestoreSourceScore = AvailableRestoreSourceScore | UnavailableRestoreSourceScore


class AvailableRestoreStatus(ContractModel):
    key: Literal[
        "sleep_restore_very_good",
        "sleep_restore_good",
        "pace_morning",
        "prioritise_rest",
        "rest_goal_full",
        "rest_good",
        "rest_partial",
        "rest_more",
    ]
    label: str
    min_score: int = Field(ge=0, le=100)
    max_score: int = Field(ge=0, le=100)
    meaning: str
    version: str

    @root_validator(skip_on_failure=True)
    def maximum_must_not_precede_minimum(cls, values: dict[str, Any]):
        if values["max_score"] < values["min_score"]:
            raise ValueError("max_score must be greater than or equal to min_score")
        return values


class UnavailableRestoreStatus(ContractModel):
    key: Literal["unavailable"]
    label: str
    min_score: None = Field(...)
    max_score: None = Field(...)
    meaning: str
    version: str


RestoreStatus = AvailableRestoreStatus | UnavailableRestoreStatus


class RestoreSessionScope(ContractModel):
    mode: SessionMode
    label: str
    question: str
    whole_day_readiness: Literal[False]
    clinical_readiness: Literal[False]
    updates_during_day: Literal[False]


ScoreComponentKey = Literal[
    "sleep_opportunity",
    "sleep_stability",
    "restorative_architecture",
    "cycle_expression",
    "goal_duration",
    "physiological_response",
    "rest_continuity",
    "environment_support",
]


class ScoreComponentDriver(ContractModel):
    key: ScoreComponentKey
    category: Literal["score_component"]
    label: str
    message: str
    direction: DriverDirection
    earned_points: float = Field(ge=0)
    max_points: float = Field(gt=0)
    attainment_pct: float = Field(ge=0, le=100)
    affects_source_score: Literal[True]
    causal_claim: Literal[False]


class EnvironmentDriver(ContractModel):
    key: str
    category: Literal["environment"]
    label: str
    message: str
    direction: DriverDirection
    severity: EnvironmentSeverity
    decision: str
    action: str | None = Field(...)
    affects_source_score: bool
    relationship: Literal[
        "session_context_only",
        "recovery_score_component_and_session_context",
    ]
    causal_claim: Literal[False]
    priority: Literal["safety_review"] | None = None
    threshold: float | None = None
    critical_below: float | None = None
    critical_above: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    sample_count: int | None = Field(default=None, ge=0)
    sample_pct: float | None = Field(default=None, ge=0, le=100)

    @validator("key")
    def public_environment_key(cls, value: str):
        prefix = "environment_"
        suffix = value.removeprefix(prefix)
        if (
            not value.startswith(prefix)
            or not suffix
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_"
                for character in suffix
            )
        ):
            raise ValueError("environment driver key must use environment_<key>")
        return value


RestoreDriver = ScoreComponentDriver | EnvironmentDriver


class RestoreDrivers(ContractModel):
    positive: list[RestoreDriver]
    attention: list[RestoreDriver]
    explainability_available: bool
    selection: (
        Literal["highest_two_strengths_and_highest_two_attention_items"] | None
    ) = None
    policy_version: str | None = None
    environment_never_determines_sleep_state: Literal[True] | None = None
    events_are_associations_not_proven_causes: Literal[True] | None = None
    reason: str | None = None

    @validator("positive", "attention")
    def at_most_two_drivers(cls, value: list[RestoreDriver]):
        if len(value) > 2:
            raise ValueError("a Restore Summary exposes at most two drivers")
        return value

    @root_validator(skip_on_failure=True)
    def directions_match_buckets(cls, values: dict[str, Any]):
        for item in values.get("positive", []):
            if item.direction != "positive":
                raise ValueError("positive drivers must use direction='positive'")
        for item in values.get("attention", []):
            if item.direction != "attention":
                raise ValueError("attention drivers must use direction='attention'")
        return values


class BaselineMaturity(ContractModel):
    key: Literal["learning", "early", "active", "stable"]
    label: str
    confidence: Literal["insufficient", "low", "medium", "high"]
    sessions_used: int = Field(ge=0)
    comparison_minimum_sessions: int = Field(ge=1)
    stable_from_sessions: int = Field(ge=1)


class AvailableBaselineComparison(ContractModel):
    available: Literal[True]
    key: Literal[
        "below_typical",
        "near_typical",
        "within_typical",
        "above_typical",
    ]
    label: str
    current_score: float = Field(ge=0, le=100)
    baseline_median: float = Field(ge=0, le=100)
    delta_points: float = Field(ge=-100, le=100)
    typical_range: tuple[float, float] | None = Field(...)
    mode_specific: Literal[True]

    @validator("typical_range")
    def valid_typical_range(cls, value: tuple[float, float] | None):
        if value is not None and not (0 <= value[0] <= value[1] <= 100):
            raise ValueError("typical_range must be ordered and inside 0..100")
        return value


class UnavailableBaselineComparison(ContractModel):
    available: Literal[False]
    reason: str


BaselineComparison = AvailableBaselineComparison | UnavailableBaselineComparison


class PersonalBaseline(ContractModel):
    version: str
    mode: SessionMode
    maturity: BaselineMaturity
    comparison: BaselineComparison
    affects_source_score: Literal[False]
    population_prior_is_cold_start_only: Literal[True]
    must_not_mix_sleep_and_nap_sessions: Literal[True]


class TrendWindow(ContractModel):
    session_count: int = Field(ge=1)
    average: float = Field(ge=0, le=100)
    latest: float = Field(ge=0, le=100)


class TrendWindows(ContractModel):
    sessions_7: TrendWindow | None = Field(None, alias="7")
    sessions_14: TrendWindow | None = Field(None, alias="14")
    sessions_30: TrendWindow | None = Field(None, alias="30")


class AvailableTrend(ContractModel):
    available: Literal[True]
    unit: Literal["sessions"]
    windows: TrendWindows
    mode_specific: Literal[True]
    whole_day_readiness_trend: Literal[False]

    @validator("windows")
    def at_least_one_window(cls, value: TrendWindows):
        if not any((value.sessions_7, value.sessions_14, value.sessions_30)):
            raise ValueError("an available trend must contain at least one window")
        return value


class UnavailableTrend(ContractModel):
    available: Literal[False]
    reason: str
    windows: TrendWindows


RestoreTrend = AvailableTrend | UnavailableTrend


class RestoreRecommendation(ContractModel):
    primary: str
    source_driver_key: str | None = Field(...)
    version: str
    one_action_only: Literal[True]
    automatic_actuation: Literal[False]
    medical_advice: Literal[False]


class RestoreConfidence(ContractModel):
    level: ConfidenceLevel
    label: str
    session_coverage_pct: float | None = Field(..., ge=0, le=100)
    paired_hr_rr_coverage_pct: float | None = Field(..., ge=0, le=100)
    changes_source_score: Literal[False]
    admin_qa_context: Literal[True]


QuestionnaireSource = Literal[
    "pre_post_questionnaire",
    "session_questionnaire",
    "zeep_pre_post_questionnaire",
]


class MeasuredSubjectiveOutcome(ContractModel):
    status: Literal["measured"]
    label: str
    freshness_delta: float | None = Field(..., ge=-10, le=10)
    activity_readiness: float | None = Field(..., ge=0, le=10)
    source: QuestionnaireSource
    sensor_inferred: Literal[False]

    @root_validator(skip_on_failure=True)
    def at_least_one_measurement(cls, values: dict[str, Any]):
        if (
            values.get("freshness_delta") is None
            and values.get("activity_readiness") is None
        ):
            raise ValueError("a measured outcome requires at least one measurement")
        return values


class UnmeasuredSubjectiveOutcome(ContractModel):
    status: Literal["not_measured"]
    label: str
    freshness_delta: None = Field(...)
    activity_readiness: None = Field(...)
    sensor_inferred: Literal[False]


SubjectiveOutcome = MeasuredSubjectiveOutcome | UnmeasuredSubjectiveOutcome


class ClaimBoundary(ContractModel):
    wellness_estimate: Literal[True]
    medical_diagnosis: Literal[False]
    whole_day_readiness: Literal[False]
    training_load_included: Literal[False]
    daytime_activity_included: Literal[False]
    freshness_not_inferred_from_sensor: Literal[True]
    environment_association_is_not_causation: Literal[True]


class RestoreProvenance(ContractModel):
    source: Literal[
        "persisted_context_with_canonical_explanation",
        "derived_from_persisted_report_without_rescoring",
    ]
    score_changed: Literal[False]
    persisted_source_score_matched: bool
    causal_claims: Literal[False]


class RestoreSummaryPayload(ContractModel):
    """Shared Restore Summary fields before the public API adds provenance."""

    version: str
    available: bool
    name: Literal["ZEEP Restore Summary"]
    creates_independent_score: Literal[False]
    source_score: RestoreSourceScore
    status: RestoreStatus
    session_scope: RestoreSessionScope
    drivers: RestoreDrivers
    personal_baseline: PersonalBaseline
    trend: RestoreTrend
    recommendation: RestoreRecommendation
    confidence: RestoreConfidence
    subjective_outcome: SubjectiveOutcome
    claim_boundary: ClaimBoundary
    whole_day_readiness_available: Literal[False] | None = None
    provenance: RestoreProvenance | None = None

    @root_validator(skip_on_failure=True)
    def availability_must_match_source_score(cls, values: dict[str, Any]):
        if values.get("available") != values["source_score"].available:
            raise ValueError("available must match source_score.available")
        if values["source_score"].available:
            if values["status"].key == "unavailable":
                raise ValueError("an available score requires an available status")
            score_value = values["source_score"].value
            band_value = int(round(score_value))
            if not (
                values["status"].min_score <= band_value <= values["status"].max_score
            ):
                raise ValueError(
                    "source score must be inside the published status band"
                )
        elif values["status"].key != "unavailable":
            raise ValueError("an unavailable score requires status='unavailable'")

        mode = values["session_scope"].mode
        expected_score_type = {
            "sleep": "sleep_score",
            "nap_recovery": "recovery_score",
            "unknown": "unresolved_score",
        }[mode]
        if values["source_score"].type != expected_score_type:
            raise ValueError("source score type must match the Session mode")

        status_key = values["status"].key
        valid_statuses = {
            "sleep": {
                "sleep_restore_very_good",
                "sleep_restore_good",
                "pace_morning",
                "prioritise_rest",
            },
            "nap_recovery": {
                "rest_goal_full",
                "rest_good",
                "rest_partial",
                "rest_more",
            },
            "unknown": {"unavailable"},
        }[mode]
        if values["source_score"].available and status_key not in valid_statuses:
            raise ValueError("Restore status must match the Session mode")
        if values["source_score"].available:
            expected_band = _STATUS_BANDS[status_key]
            actual_band = (values["status"].min_score, values["status"].max_score)
            if actual_band != expected_band:
                raise ValueError("Restore status key must use its versioned score band")
        if values["personal_baseline"].mode != mode:
            raise ValueError("Personal Baseline mode must match the Session mode")
        return values


class RestoreSummary(RestoreSummaryPayload):
    """Exact Restore Summary published by the Usage Session API."""

    whole_day_readiness_available: Literal[False]
    provenance: RestoreProvenance
