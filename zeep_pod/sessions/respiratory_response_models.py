"""Strict public response models for respiratory Wellness summaries."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from zeep_pod.sessions._response_model_base import ContractModel


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
    status: Literal["not_ready", "below", "within", "above"]
    sessions_used: int = Field(ge=0)
    minimum_sessions: int = Field(ge=1)
    reason: str | None = None
    label: str | None = None
    median_rr_brpm: float | None = Field(default=None, ge=4, le=60)
    typical_range_rr_brpm: tuple[float, float] | None = None
    delta_rr_brpm: float | None = None
    same_mode_only: Literal[True] | None = None
    prior_sessions_only: Literal[True] | None = None
    affects_score: Literal[False]


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


class RespiratoryMeasurementRequirements(ContractModel):
    lung_function: str
    oxygenation: str
    whole_body_fitness: str


class RespiratoryCapabilities(ContractModel):
    breathing_pattern: Literal["estimated_from_direct_bcg_rr"]
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
    version: str
    available: bool
    label: str
    intended_use: Literal[
        "age_contextual_wellness_pattern_not_lung_function"
    ]
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
