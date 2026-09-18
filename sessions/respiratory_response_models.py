"""Strict public response models for respiratory Wellness summaries."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, root_validator

from sessions._response_model_base import ContractModel
from sessions.respiratory_policy import (
    RESPIRATORY_MINIMUM_CONTEXT_COVERAGE_PCT,
    RESPIRATORY_MINIMUM_PAIRED_RUN_SECONDS,
    RESPIRATORY_MINIMUM_VALID_SAMPLES,
    RESPIRATORY_MINIMUM_VALID_SECONDS,
)


class RespiratoryStatus(ContractModel):
    key: Literal["insufficient", "needs_recheck", "supportive", "observe"]
    label: str


class RespiratoryObservations(ContractModel):
    median_hr_bpm: float | None = Field(default=None, ge=30, le=220)
    median_paired_rr_brpm: float | None = Field(default=None, ge=4, le=60)
    median_rr_brpm: float | None = Field(default=None, ge=4, le=60)
    p10_rr_brpm: float | None = Field(default=None, ge=4, le=60)
    p90_rr_brpm: float | None = Field(default=None, ge=4, le=60)
    regularity_factor: float | None = Field(default=None, ge=0, le=1)
    regularity_key: Literal["stable", "mixed", "variable", "insufficient"]
    valid_samples: int = Field(ge=0)
    paired_hr_rr_samples: int = Field(ge=0)
    paired_hr_rr_minutes: float = Field(ge=0)
    paired_hr_rr_coverage_pct: float = Field(ge=0, le=100)
    longest_paired_hr_rr_run_seconds: float = Field(ge=0)
    paired_hr_rr_evidence_sufficient: bool
    longest_valid_run_samples: int = Field(ge=0)
    longest_valid_run_seconds: float = Field(ge=0)
    valid_minutes: float = Field(ge=0)
    occupied_minutes: float = Field(ge=0)
    coverage_pct: float = Field(ge=0, le=100)
    excluded_motion_or_weak_signal_minutes: float = Field(ge=0)
    excluded_invalid_or_held_minutes: float = Field(ge=0)

    @root_validator(skip_on_failure=True)
    def sufficient_evidence_requires_paired_values(cls, values: dict[str, Any]):
        sufficient = values.get("paired_hr_rr_evidence_sufficient") is True
        paired_values = bool(
            values.get("median_hr_bpm") is not None
            and values.get("median_paired_rr_brpm") is not None
        )
        if sufficient != paired_values:
            raise ValueError("paired medians must match the evidence gate")
        if sufficient:
            if (
                values.get("paired_hr_rr_samples", 0)
                < RESPIRATORY_MINIMUM_VALID_SAMPLES
                or values.get("paired_hr_rr_minutes", 0) * 60.0
                < RESPIRATORY_MINIMUM_VALID_SECONDS
                or values.get("longest_paired_hr_rr_run_seconds", 0)
                < RESPIRATORY_MINIMUM_PAIRED_RUN_SECONDS
                or values.get("paired_hr_rr_coverage_pct", 0)
                < RESPIRATORY_MINIMUM_CONTEXT_COVERAGE_PCT
            ):
                raise ValueError("paired evidence does not satisfy minimum quality")
            if (
                values.get("paired_hr_rr_samples", 0) > values.get("valid_samples", 0)
                or values.get("paired_hr_rr_minutes", 0)
                > values.get("valid_minutes", 0)
                or values.get("paired_hr_rr_minutes", 0)
                > values.get("occupied_minutes", 0)
            ):
                raise ValueError("paired evidence accounting is inconsistent")
        return values


class RespiratoryConfidence(ContractModel):
    level: Literal["high", "medium", "low"]
    label: str
    direct_measurements_only: Literal[True]
    carried_state_excluded: Literal[True]


class RespiratoryAgeContext(ContractModel):
    available: bool
    age_band: Literal["18-29", "30-44", "45-59", "60+"] | None
    label: str
    guidance: str
    role: Literal["context_only"]
    threshold_adjustment_applied: Literal[False]
    note: str


class RespiratoryPersonalBaseline(ContractModel):
    available: bool
    reference_ready: bool
    status: Literal["not_ready", "below", "within", "above"]
    sessions_used: int = Field(ge=0)
    minimum_sessions: int = Field(ge=1)
    reason: str | None = None
    label: str | None = None
    median_hr_bpm: float | None = Field(default=None, ge=30, le=220)
    typical_range_hr_bpm: tuple[float, float] | None = None
    delta_hr_bpm: float | None = None
    median_rr_brpm: float | None = Field(default=None, ge=4, le=60)
    typical_range_rr_brpm: tuple[float, float] | None = None
    delta_rr_brpm: float | None = None
    same_mode_only: Literal[True] | None = None
    prior_sessions_only: Literal[True] | None = None
    requires_paired_hr_rr: Literal[True]
    affects_score: Literal[False]

    @root_validator(skip_on_failure=True)
    def ready_reference_requires_complete_paired_contract(
        cls,
        values: dict[str, Any],
    ):
        ready = values.get("reference_ready") is True
        available = values.get("available") is True
        if available and not ready:
            raise ValueError("available comparison requires a ready reference")
        if not ready and values.get("sessions_used", 0) >= values.get(
            "minimum_sessions",
            1,
        ):
            raise ValueError("an incomplete reference cannot report full progress")
        if ready:
            if values.get("sessions_used", 0) < values.get("minimum_sessions", 1):
                raise ValueError("ready reference requires the minimum sessions")
            for field in (
                "median_hr_bpm",
                "typical_range_hr_bpm",
                "median_rr_brpm",
                "typical_range_rr_brpm",
                "same_mode_only",
                "prior_sessions_only",
            ):
                if values.get(field) is None:
                    raise ValueError(f"ready reference requires {field}")
            cls._validate_range(values["typical_range_hr_bpm"], 30.0, 220.0)
            cls._validate_range(values["typical_range_rr_brpm"], 4.0, 60.0)
        if available and values.get("status") == "not_ready":
            raise ValueError("available comparison requires a comparison status")
        return values

    @staticmethod
    def _validate_range(value: tuple[float, float], low: float, high: float) -> None:
        if not low <= value[0] <= value[1] <= high:
            raise ValueError("personal reference range must be ordered and bounded")


class RespiratoryReferenceContext(ContractModel):
    adult_orientation_range_brpm: tuple[float, float]
    recheck_range_brpm: tuple[float, float]
    ranges_are_diagnostic: Literal[False]
    age_specific_cutoff_applied: Literal[False]
    regularity_is_internal_wellness_policy: Literal[True]


class RespiratoryRecommendation(ContractModel):
    primary: str
    medical_advice: Literal[False]
    automatic_actuation: Literal[False]


class PairedVitalSummary(ContractModel):
    available: bool
    status: Literal["available", "needs_recheck", "insufficient"]
    status_label: str
    heart_rate_bpm: float | None = Field(default=None, ge=30, le=220)
    respiration_rate_brpm: float | None = Field(default=None, ge=4, le=60)
    summary: str
    recommendation: str
    basis: Literal["direct_paired_hr_rr"]
    aggregation: Literal["weighted_median"]
    wellness_only: Literal[True]
    medical_diagnosis: Literal[False]

    @root_validator(skip_on_failure=True)
    def availability_requires_both_vitals(cls, values: dict[str, Any]):
        available = values.get("available") is True
        complete = bool(
            values.get("heart_rate_bpm") is not None
            and values.get("respiration_rate_brpm") is not None
        )
        if available != complete:
            raise ValueError("paired vital availability must match HR/RR completeness")
        if available and values.get("status") == "insufficient":
            raise ValueError("available paired vitals cannot be insufficient")
        if not available and values.get("status") != "insufficient":
            raise ValueError("unavailable paired vitals must be insufficient")
        return values


class RespiratoryMeasurementRequirements(ContractModel):
    lung_function: str
    oxygenation: str
    whole_body_fitness: str


class RespiratoryCapabilities(ContractModel):
    breathing_pattern: Literal["estimated_from_direct_bcg_hr_rr"]
    lung_function: Literal["not_measured"]
    blood_oxygen: Literal["not_measured"]
    whole_body_fitness: Literal["not_measured"]


class RespiratoryClaimBoundary(ContractModel):
    wellness_estimate: Literal[True]
    lung_strength_assessed: Literal[False]
    oxygen_saturation_measured: Literal[False]
    sleep_apnea_screening: Literal[False]
    medical_diagnosis: Literal[False]
    changes_sleep_state: Literal[False]
    changes_sleep_score: Literal[False]
    changes_recovery_score: Literal[False]


class RespiratoryWellness(ContractModel):
    version: Literal["zeep-respiratory-wellness-v1.2-paired-hr-rr"]
    available: bool
    label: str
    intended_use: Literal["age_contextual_wellness_pattern_not_lung_function"]
    context: Literal["overnight_sleep", "nap_or_rest", "unknown"]
    status: RespiratoryStatus
    reason_codes: list[
        Literal[
            "no_sensor_samples",
            "no_confirmed_occupancy",
            "historical_provenance_unavailable",
            "insufficient_valid_duration",
            "low_valid_coverage",
            "needs_standard_recheck",
        ]
    ]
    interpretation: str
    observations: RespiratoryObservations
    vital_summary: PairedVitalSummary
    confidence: RespiratoryConfidence
    age_context: RespiratoryAgeContext
    personal_baseline: RespiratoryPersonalBaseline
    reference_context: RespiratoryReferenceContext
    recommendation: RespiratoryRecommendation
    measurement_requirements: RespiratoryMeasurementRequirements
    capabilities: RespiratoryCapabilities
    claim_boundary: RespiratoryClaimBoundary

    @root_validator(skip_on_failure=True)
    def root_availability_matches_paired_evidence(cls, values: dict[str, Any]):
        available = values.get("available") is True
        status = values.get("status")
        observations = values.get("observations")
        vital = values.get("vital_summary")
        status_key = getattr(status, "key", None)
        paired_ready = bool(
            getattr(observations, "paired_hr_rr_evidence_sufficient", False)
        )
        vital_available = getattr(vital, "available", False) is True
        if available != (paired_ready and vital_available):
            raise ValueError("root availability must match paired HR/RR evidence")
        if available != (status_key != "insufficient"):
            raise ValueError("root status must match paired HR/RR availability")
        if available and (
            getattr(vital, "heart_rate_bpm", None)
            != getattr(observations, "median_hr_bpm", None)
            or getattr(vital, "respiration_rate_brpm", None)
            != getattr(observations, "median_paired_rr_brpm", None)
        ):
            raise ValueError("published vital values must match paired observations")
        return values
