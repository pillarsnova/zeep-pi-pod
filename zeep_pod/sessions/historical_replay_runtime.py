"""Composition-root-free runtime policy for legacy Sleep History replay.

The historical replay command must use the same versioned defaults and
environment overrides as the live estimator without importing the application
composition root.  Keeping this contract free of GPIO, serial, audio, database,
and web dependencies makes maintenance commands safe to inspect and test.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sleep_system_policy import (
    SLEEP_DEFAULT_BASELINE_HR_WEIGHT,
    SLEEP_DEFAULT_BASELINE_RR_WEIGHT,
    SLEEP_DEFAULT_HR_CV_DEEP,
    SLEEP_DEFAULT_HR_CV_REM,
    SLEEP_DEFAULT_MOVE_DEEP_RATIO,
    SLEEP_DEFAULT_MOVE_WAKE_RATIO,
    SLEEP_DEFAULT_N2_RR_CONFLICT_SUPPORT,
    SLEEP_DEFAULT_N3_RR_CONFLICT_PENALTY,
    SLEEP_ESTIMATOR_VERSION,
    SLEEP_EVIDENCE_VERSION,
    SLEEP_G2_ONTOLOGY_VERSION,
    ZEEP_SLEEP_BASELINE_VERSION,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
)


@dataclass(frozen=True)
class HistoricalReplayRuntime:
    """Effective estimator values needed by historical comparison only."""

    baseline_hr_weight: float
    baseline_rr_weight: float
    n3_rr_conflict_penalty: float
    n2_rr_conflict_support: float
    move_wake_ratio: float
    move_deep_ratio: float
    hr_cv_deep: float
    hr_cv_rem: float

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str],
    ) -> HistoricalReplayRuntime:
        """Resolve the live-compatible, versioned environment overrides."""
        runtime = cls(
            baseline_hr_weight=_environment_float(
                environment,
                "SLEEP_BASELINE_HR_WEIGHT",
                SLEEP_DEFAULT_BASELINE_HR_WEIGHT,
            ),
            baseline_rr_weight=_environment_float(
                environment,
                "SLEEP_BASELINE_RR_WEIGHT",
                SLEEP_DEFAULT_BASELINE_RR_WEIGHT,
            ),
            n3_rr_conflict_penalty=_environment_float(
                environment,
                "SLEEP_N3_RR_CONFLICT_PENALTY",
                SLEEP_DEFAULT_N3_RR_CONFLICT_PENALTY,
            ),
            n2_rr_conflict_support=_environment_float(
                environment,
                "SLEEP_N2_RR_CONFLICT_SUPPORT",
                SLEEP_DEFAULT_N2_RR_CONFLICT_SUPPORT,
            ),
            move_wake_ratio=_environment_float(
                environment,
                "SLEEP_MOVE_WAKE_RATIO",
                SLEEP_DEFAULT_MOVE_WAKE_RATIO,
            ),
            move_deep_ratio=_environment_float(
                environment,
                "SLEEP_MOVE_DEEP_RATIO",
                SLEEP_DEFAULT_MOVE_DEEP_RATIO,
            ),
            hr_cv_deep=_environment_float(
                environment,
                "SLEEP_HR_CV_DEEP",
                SLEEP_DEFAULT_HR_CV_DEEP,
            ),
            hr_cv_rem=_environment_float(
                environment,
                "SLEEP_HR_CV_REM",
                SLEEP_DEFAULT_HR_CV_REM,
            ),
        )
        runtime.validate()
        return runtime

    def validate(self) -> None:
        """Apply the same startup guards used by the live composition root."""
        if self.baseline_hr_weight < 0 or self.baseline_rr_weight < 0:
            raise RuntimeError("Sleep baseline weights must not be negative")
        if self.baseline_hr_weight + self.baseline_rr_weight <= 0:
            raise RuntimeError("At least one sleep baseline weight must be positive")
        if self.n3_rr_conflict_penalty < 0 or self.n2_rr_conflict_support < 0:
            raise RuntimeError("Sleep RR conflict weights must not be negative")

    def physiological_baseline_fit(self, hr_fit: float, rr_fit: float) -> float:
        """Combine HR/RR proximity with the effective versioned weights."""
        return self.baseline_hr_weight * hr_fit + self.baseline_rr_weight * rr_fit

    @staticmethod
    def decision_provenance() -> dict[str, str]:
        """Return versions persisted by both live and historical decisions."""
        return {
            "estimator_version": SLEEP_ESTIMATOR_VERSION,
            "evidence_version": SLEEP_EVIDENCE_VERSION,
            "baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
            "transition_policy_version": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "g2_ontology_version": SLEEP_G2_ONTOLOGY_VERSION,
        }


def _environment_float(
    environment: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    """Parse one override exactly as the live estimator does at startup."""
    return float(environment.get(name, str(default)))
