"""Explicit dependency contract for the live Sleep estimator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class LiveSleepRuntime:
    """Snapshot references from the composition root for one inference call.

    Referenced state/locks retain their identity. Refreshing the contract per
    call also preserves runtime replacement and test monkeypatch semantics.
    """

    AGE_SLEEP_BASELINES: Any
    BCG_SAMPLE_RATE_HZ: Any
    HR_SANITY_RANGE_BPM: Any
    ON_BED_CODES: Any
    PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED: Any
    RR_SANITY_RANGE_PER_MIN: Any
    SLEEP_BASELINE_HR_WEIGHT: Any
    SLEEP_BASELINE_RR_WEIGHT: Any
    SLEEP_CONFIRMATION_SECONDS: Any
    SLEEP_CONFIRM_EPOCHS: Any
    SLEEP_CONTEXT_RESET_GAP_SECONDS: Any
    SLEEP_DISPLAY_WINNER_MARGIN: Any
    SLEEP_ESTIMATOR_VERSION: Any
    SLEEP_EVIDENCE_EPOCH_SECONDS: Any
    SLEEP_EVIDENCE_MIN_MARGIN: Any
    SLEEP_EVIDENCE_MIN_WINNER: Any
    SLEEP_EVIDENCE_VERSION: Any
    SLEEP_G2_ONTOLOGY_VERSION: Any
    SLEEP_HR_CV_DEEP: Any
    SLEEP_HR_CV_REM: Any
    SLEEP_HR_RR_FIT_FUSION_AGREEMENT_WEIGHT: Any
    SLEEP_HR_RR_FIT_FUSION_WEIGHT: Any
    SLEEP_LONG_CONTEXT_SECONDS: Any
    SLEEP_MIN_FRAMES: Any
    SLEEP_MIN_PAIRED_VITAL_COVERAGE: Any
    SLEEP_MIN_WAVEFORM_COVERAGE: Any
    SLEEP_MOVE_DEEP_RATIO: Any
    SLEEP_MOVE_WAKE_RATIO: Any
    SLEEP_N2_RR_CONFLICT_SUPPORT: Any
    SLEEP_N3_GATED_MIN_MARGIN: Any
    SLEEP_N3_GATED_MIN_WINNER: Any
    SLEEP_N3_RR_CONFLICT_PENALTY: Any
    SLEEP_ONSET_INITIAL_WAKE_SUPPORT: Any
    SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN: Any
    SLEEP_ONSET_MAX_MOVEMENT_RATIO: Any
    SLEEP_ONSET_MAX_RR_RISE_PER_MIN: Any
    SLEEP_ONSET_MIN_DOWNWARD_TRANSITION: Any
    SLEEP_ONSET_MIN_OBSERVATION_SECONDS: Any
    SLEEP_ONSET_MIN_RELATIVE_SLEEP_SUPPORT: Any
    SLEEP_PROBABILITY_EMA_ALPHA: Any
    SLEEP_PROBABILITY_SWITCH_MARGIN: Any
    SLEEP_PROVISIONAL_HOLD_EPOCHS: Any
    SLEEP_SAMPLE_SECONDS: Any
    SLEEP_SCORE_SOFTMAX_TEMPERATURE: Any
    SLEEP_SENSOR_FRAMES_PER_EPOCH: Any
    SLEEP_WINDOW_SECONDS: Any
    STATUS_TEXT: Any
    ZEEP_SLEEP_BASELINE_VERSION: Any
    ZEEP_SLEEP_STATES: Any
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION: Any
    _age_group: Any
    _baseline_interval_proximity: Any
    _commit_sleep_stage: Any
    _gender_adjusted_baseline: Any
    _latch_confirmed_bed_exit: Any
    _off_bed_remains_latched: Any
    _persist_sleep_stage_evidence: Any
    _physiological_baseline_fit: Any
    _reset_sleep_stage_path: Any
    _sleep_auxiliary_evidence: Any
    _sleep_environment_context: Any
    _sleep_stage_path: Any
    _stabilize_sleep_stage: Any
    _update_sleep_session_context: Any
    align_probabilities_to_emitted_stage: Any
    arousal_proxy_evidence: Any
    baselines: Any
    candidate_from_stage_evidence: Any
    continuity_hold_contract: Any
    evidence_candidate_with_abstention: Any
    filter_vital_values: Any
    fuse_hr_rr_fit_with_stage_probabilities: Any
    history_lock: Any
    interpret_baseline_fit: Any
    movement_window_metrics: Any
    score_sleep_evidence: Any
    sleep_feature_history: Any
    sleep_path_lock: Any
    smooth_stage_probabilities: Any
    softmax_stage_evidence: Any
    state: Any
    state_lock: Any
    summary_features: Any
    waveform_features: Any

    @classmethod
    def from_namespace(cls, namespace: Mapping[str, Any]) -> LiveSleepRuntime:
        """Validate the complete manifest before starting inference."""
        names = [field.name for field in fields(cls)]
        missing = [name for name in names if name not in namespace]
        if missing:
            raise RuntimeError(f"Live Sleep estimator missing runtime ports: {missing}")
        return cls(**{name: namespace[name] for name in names})
