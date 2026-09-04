"""Shared physiological evidence scoring for live and historical replay.

This module keeps the rule weights in one place so a backfill cannot silently
use a different model from the live 30-second evidence estimator. All thresholds are
versioned ZEEP engineering values pending simultaneous PSG/ECG validation.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from sleep_signal_features import sleep_movement_evidence


STAGES = ("wake", "n1", "n2", "n3", "rem")


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


def _finite(value: Any, default: float = 0.0) -> float:
    """Convert untrusted telemetry to one finite number for score arithmetic."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _optional_finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def normalise_stage_probabilities(values: Mapping[str, Any]) -> dict[str, float]:
    """Return one finite five-state distribution without inventing a stage."""
    cleaned = {
        stage: max(0.0, _finite(values.get(stage), 0.0)) for stage in STAGES
    }
    total = sum(cleaned.values())
    if total <= 0.0:
        return {stage: 0.0 for stage in STAGES}
    return {stage: value / total for stage, value in cleaned.items()}


def smooth_stage_probabilities(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    *,
    alpha: float,
) -> dict[str, float]:
    """EMA-filter one 30-second evidence-epoch probability distribution.

    The estimator already derives ``current`` from a rolling feature window.
    This filter makes the published distribution and candidate selection obey
    the same continuity principle as the emitted Sleep State.
    """
    current_values = normalise_stage_probabilities(current)
    previous_values = normalise_stage_probabilities(previous or {})
    if not any(previous_values.values()):
        return current_values
    weight = _clamp(alpha)
    blended = {
        stage: previous_values[stage] * (1.0 - weight)
        + current_values[stage] * weight
        for stage in STAGES
    }
    return normalise_stage_probabilities(blended)


def stable_probability_candidate(
    probabilities: Mapping[str, Any],
    current_stage: str | None,
    *,
    switch_margin: float,
) -> tuple[str, dict[str, Any]]:
    """Keep the current state when a challenger wins by only a small margin."""
    values = normalise_stage_probabilities(probabilities)
    challenger = max(STAGES, key=values.get)
    current = current_stage if current_stage in STAGES else None
    margin = max(0.0, _finite(switch_margin, 0.0))
    held = bool(
        current
        and challenger != current
        and values[challenger] - values[current] < margin
    )
    candidate = current if held else challenger
    return candidate, {
        "filtered_winner": challenger,
        "current_stage": current,
        "winner_gap": round(
            values[challenger] - (values[current] if current else 0.0), 4
        ),
        "switch_margin": round(margin, 4),
        "margin_held": held,
    }


def candidate_from_stage_evidence(
    current_probabilities: Mapping[str, Any],
    ema_probabilities: Mapping[str, Any],
    current_stage: str | None,
    *,
    switch_margin: float,
    n3_gate: bool,
    sleep_onset_gate_passed: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Select a stable candidate without starving physiologically gated N3.

    EMA remains the default candidate source for Wake/N1/N2/REM. A current N3
    winner may bypass EMA only after the independent N3 physiology gate passes
    and the normal winner margin is met. The caller's semi-Markov state machine
    still requires two consecutive evidence epochs/60 seconds, so this removes
    duplicate historical inertia without weakening N3 evidence requirements or
    making the other states more reactive.
    """
    ema_candidate, ema_metadata = stable_probability_candidate(
        ema_probabilities,
        current_stage,
        switch_margin=switch_margin,
    )
    current_candidate, current_metadata = stable_probability_candidate(
        current_probabilities,
        current_stage,
        switch_margin=switch_margin,
    )
    gated_n3_override = bool(n3_gate and current_candidate == "n3")
    candidate = current_candidate if gated_n3_override else ema_candidate
    onset_guard_held = bool(
        current_stage in {None, "wake"}
        and candidate != "wake"
        and not sleep_onset_gate_passed
    )
    if onset_guard_held:
        candidate = "wake"
    metadata = dict(current_metadata if gated_n3_override else ema_metadata)
    metadata.update({
        "candidate_source": (
            "sleep_onset_guard"
            if onset_guard_held
            else (
                "gated_n3_current_30s_evidence_before_ema"
                if gated_n3_override else "ema_probability"
            )
        ),
        "ema_role": "default_candidate_stability_and_display",
        "gated_n3_current_evidence_override": gated_n3_override,
        "n3_gate": bool(n3_gate),
        "sleep_onset_gate_passed": bool(sleep_onset_gate_passed),
        "sleep_onset_guard_held": onset_guard_held,
        "current_evidence_winner": current_metadata["filtered_winner"],
        "ema_winner": ema_metadata["filtered_winner"],
    })
    return candidate, metadata


def sleep_onset_evidence(
    *,
    elapsed_min: float,
    movement_evidence: Mapping[str, Any],
    hr_slope_bpm_per_min: float,
    rr_slope_per_min: float,
    downward_transition: float,
    minimum_observation_minutes: float,
    maximum_movement_ratio: float,
    minimum_downward_transition: float,
    maximum_hr_rise_bpm_per_min: float,
    maximum_rr_rise_per_min: float,
) -> dict[str, Any]:
    """Return conservative evidence required to leave Wake for the first time.

    BCG cannot distinguish quiet wake from EEG-defined N1 by a static HR/RR
    range.  The guard therefore requires elapsed observation, a quiet bed and
    a sustained autonomic downward trend.  The normal two-epoch state
    confirmation remains a separate requirement after this gate passes.
    """
    elapsed = max(0.0, _finite(elapsed_min, 0.0))
    movement_ratio = _clamp(
        _finite(movement_evidence.get("movement_ratio"), 0.0)
    )
    hr_slope = _finite(hr_slope_bpm_per_min, 0.0)
    rr_slope = _finite(rr_slope_per_min, 0.0)
    downward = _clamp(downward_transition)
    observation_complete = elapsed >= max(0.0, minimum_observation_minutes)
    quiet_bed = bool(
        movement_ratio < max(0.0, maximum_movement_ratio)
        and not movement_evidence.get("sustained_on_bed")
        and movement_evidence.get("category") != "bed_exit"
    )
    no_vital_rise = bool(
        hr_slope <= maximum_hr_rise_bpm_per_min
        and rr_slope <= maximum_rr_rise_per_min
    )
    downward_sustained = downward >= max(0.0, minimum_downward_transition)
    passed = bool(
        observation_complete and quiet_bed and no_vital_rise
        and downward_sustained
    )
    return {
        "passed": passed,
        "observation_complete": observation_complete,
        "elapsed_minutes": round(elapsed, 2),
        "minimum_observation_minutes": round(
            max(0.0, minimum_observation_minutes), 2
        ),
        "quiet_bed": quiet_bed,
        "movement_ratio": round(movement_ratio, 4),
        "maximum_movement_ratio": round(maximum_movement_ratio, 4),
        "no_vital_rise": no_vital_rise,
        "hr_slope_bpm_per_min": round(hr_slope, 4),
        "rr_slope_per_min": round(rr_slope, 4),
        "downward_transition": round(downward, 4),
        "minimum_downward_transition": round(
            minimum_downward_transition, 4
        ),
        "time_alone_can_create_n1": False,
        "aasm_sleep_onset_equivalent": False,
    }


def align_probabilities_to_emitted_stage(
    probabilities: Mapping[str, Any],
    selected: str,
    *,
    winner_margin: float,
) -> dict[str, float]:
    """Make the emitted state the visible winner without zeroing its rival.

    A transition guard may hold/bridge the state after the physiological winner
    changes.  The Dashboard contract requires the highest percentage to equal
    the current state, but preserving the runner-up is important for explaining
    uncertainty and avoids the large jumps caused by mass transfer.
    """
    result = normalise_stage_probabilities(probabilities)
    if selected not in STAGES or not any(result.values()):
        return result
    other = max(
        (value for stage, value in result.items() if stage != selected),
        default=0.0,
    )
    if result[selected] <= other:
        result[selected] = other + max(0.0001, _finite(winner_margin, 0.01))
    return normalise_stage_probabilities(result)


def score_sleep_evidence(
    *,
    base_scores: Mapping[str, float],
    hr_fits: Mapping[str, float],
    rr_fits: Mapping[str, float],
    metrics: Mapping[str, Any],
    elapsed_min: float,
    rem_variability_weight: float,
    n3_rr_conflict_penalty: float,
    n2_rr_conflict_support: float,
    move_wake_ratio: float,
    move_deep_ratio: float,
    onset_min_observation_minutes: float = 5.0,
    onset_max_movement_ratio: float = 0.15,
    onset_min_downward_transition: float = 0.20,
    onset_max_hr_rise_bpm_per_min: float = 0.50,
    onset_max_rr_rise_per_min: float = 0.50,
    onset_initial_wake_support: float = 0.75,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Return five class scores and an auditable evidence record.

    ``hr_cv`` remains variation across fixed-cadence module HR summaries, not
    RMSSD/SDNN.  It is therefore given only weak REM weight.  A REM candidate
    must instead pass a conservative quiet-bed + respiratory-variability gate.
    """
    scores = {stage: _finite(base_scores.get(stage), 0.0) for stage in STAGES}
    hr_cv = max(0.0, _finite(metrics.get("hr_cv"), 0.0))
    rr_cv = max(0.0, _finite(metrics.get("rr_cv"), 0.0))
    movement = _clamp(_finite(metrics.get("movement_ratio"), 0.0))
    bed_status = str(metrics.get("bed_status") or "")
    hr_slope = _finite(metrics.get("hr_slope_bpm_per_min"), 0.0)
    rr_slope = _finite(metrics.get("rr_slope_per_min"), 0.0)
    regularity_raw = _optional_finite(metrics.get("resp_regularity"))
    regularity = _clamp(regularity_raw) if regularity_raw is not None else None
    entropy_raw = _optional_finite(metrics.get("resp_spectral_entropy"))
    respiratory_entropy = _clamp(entropy_raw) if entropy_raw is not None else None
    amplitude_cv_raw = _optional_finite(metrics.get("bcg_fast_amplitude_cv"))
    amplitude_cv = max(0.0, amplitude_cv_raw) if amplitude_cv_raw is not None else None
    shift_raw = _optional_finite(metrics.get("bcg_amplitude_shift_ratio"))
    shift_ratio = _clamp(shift_raw) if shift_raw is not None else None
    waveform_available = bool(metrics.get("waveform_available"))
    drift_ratio = max(0.0, _finite(metrics.get("bcg_baseline_drift_ratio"), 0.0))
    drift_flag = bool(metrics.get("bcg_baseline_drift_flag"))
    # SPH0645 may only corroborate a Wake-compatible BCG/bed event.  The
    # upstream feature builder keeps this at zero when sound is loud by itself;
    # bounding it again here prevents malformed telemetry from dominating the
    # physiological score during live operation or historical replay.
    acoustic_wake_support = _clamp(
        _finite(metrics.get("corroborated_acoustic_wake_support"), 0.0),
        0.0,
        0.35,
    )

    # Stabilization features separate transitional N1 from sustained N2.  The
    # amplitude envelope is only a BCG quality/stability proxy; it is not a
    # K-complex or spindle surrogate.
    hr_stability = _clamp((0.045 - hr_cv) / 0.045)
    rr_stability = _clamp((0.060 - rr_cv) / 0.060)
    flat_hr_trend = _clamp(1.0 - abs(hr_slope) / 4.0)
    flat_rr_trend = _clamp(1.0 - abs(rr_slope) / 2.0)
    flat_trend = (flat_hr_trend + flat_rr_trend) / 2.0
    downward_transition = (
        _clamp(-hr_slope / 4.0) + _clamp(-rr_slope / 2.0)
    ) / 2.0
    respiratory_stability = (_clamp((regularity - 0.35) / 0.40)
                             if regularity is not None else 0.0)
    amplitude_stability = (_clamp((0.32 - amplitude_cv) / 0.22)
                           if amplitude_cv is not None else 0.0)
    amplitude_instability = (_clamp((shift_ratio or 0.0) / 0.12)
                             if shift_ratio is not None else 0.0)

    movement_evidence = sleep_movement_evidence(dict(metrics), move_wake_ratio)
    onset_evidence = sleep_onset_evidence(
        elapsed_min=elapsed_min,
        movement_evidence=movement_evidence,
        hr_slope_bpm_per_min=hr_slope,
        rr_slope_per_min=rr_slope,
        downward_transition=downward_transition,
        minimum_observation_minutes=onset_min_observation_minutes,
        maximum_movement_ratio=onset_max_movement_ratio,
        minimum_downward_transition=onset_min_downward_transition,
        maximum_hr_rise_bpm_per_min=onset_max_hr_rise_bpm_per_min,
        maximum_rr_rise_per_min=onset_max_rr_rise_per_min,
    )
    scores["wake"] += float(movement_evidence["wake_score_support"])
    if not onset_evidence["observation_complete"]:
        scores["wake"] += max(0.0, _finite(onset_initial_wake_support, 0.0))
    onset_transition_support = (
        downward_transition * 0.45
        if onset_evidence["observation_complete"]
        and onset_evidence["quiet_bed"]
        and onset_evidence["no_vital_rise"]
        else 0.0
    )
    scores["n1"] += (
        onset_transition_support
        + (1.0 - flat_trend) * 0.15
        + amplitude_instability * 0.10
    )
    scores["n2"] += (
        hr_stability * 0.30
        + rr_stability * 0.30
        + flat_trend * 0.20
        + respiratory_stability * 0.25
        + amplitude_stability * 0.15
    )

    # N3 is deliberately gated: low HR/RR proximity alone cannot create it.
    # The label needs quiet BCG, low summary variability and regular breathing.
    n3_hr_conflict = max(0.0, _finite(hr_fits.get("n2"), 0.0)
                         - _finite(hr_fits.get("n3"), 0.0))
    n3_rr_conflict = max(0.0, _finite(rr_fits.get("n2"), 0.0)
                         - _finite(rr_fits.get("n3"), 0.0))
    n3_gate = bool(
        movement < move_deep_ratio
        and hr_cv <= 0.020
        and rr_cv <= 0.035
        and regularity is not None
        and regularity >= 0.65
        and n3_hr_conflict < 0.08
    )
    scores["n3"] += (
        hr_stability * 0.20
        + rr_stability * 0.25
        + respiratory_stability * 0.40
        + amplitude_stability * 0.15
        + (0.20 if movement < move_deep_ratio else 0.0)
        + (0.15 if n3_gate else 0.0)
        + min(max(elapsed_min - 5.0, 0.0) / 25.0, 1.0)
          * max(0.0, 1.0 - elapsed_min / 180.0) * 0.20
    )
    # PSG evidence shows mean RR overlaps across NREM stages.  Keep the
    # configured N2-vs-N3 RR counterweight, but attenuate it when the raw
    # respiratory waveform is highly regular instead of making RR proximity a
    # hard exclusion criterion.
    scores["n3"] -= (
        n3_rr_conflict * n3_rr_conflict_penalty
        * (1.0 - 0.30 * respiratory_stability)
    )
    scores["n2"] += n3_rr_conflict * n2_rr_conflict_support
    scores["n3"] -= n3_hr_conflict * 1.0
    if not n3_gate:
        scores["n3"] -= 1.10
    if waveform_available and regularity is not None and regularity < 0.60:
        scores["n3"] -= (0.60 - regularity) * 1.5
    if shift_ratio is not None and shift_ratio > 0.12:
        scores["n3"] -= min(0.5, (shift_ratio - 0.12) * 2.0)

    # REM receives no standalone time boost.  Time acts only after the current
    # window shows irregular breathing on a quiet bed.  True IBI-HRV remains
    # unavailable, so summary-bucket HR-CV has intentionally small influence.
    rr_irregularity = _clamp((rr_cv - 0.035) / 0.045)
    hr_summary_irregularity = _clamp((hr_cv - 0.025) / 0.055)
    time_support = _clamp((elapsed_min - 45.0) / 45.0)
    respiratory_not_n3_like = (
        respiratory_entropy is None or respiratory_entropy >= 0.40
    )
    rem_gate = bool(
        elapsed_min >= 45.0
        and movement < move_deep_ratio
        and rr_cv >= 0.040
        and respiratory_not_n3_like
        and (shift_ratio is None or shift_ratio <= 0.15)
    )
    scores["rem"] += (
        rr_irregularity * 0.85
        + hr_summary_irregularity * 0.10 * rem_variability_weight
        + (time_support * 0.25 if rem_gate else 0.0)
    )
    if not rem_gate:
        scores["rem"] -= 1.35
    if elapsed_min < 45.0:
        scores["rem"] -= (45.0 - elapsed_min) / 45.0

    scores["wake"] += acoustic_wake_support

    evidence = {
        "hr_stability": round(hr_stability, 4),
        "rr_stability": round(rr_stability, 4),
        "flat_trend": round(flat_trend, 4),
        "downward_transition": round(downward_transition, 4),
        "respiratory_stability": round(respiratory_stability, 4),
        "amplitude_stability": round(amplitude_stability, 4),
        "amplitude_instability": round(amplitude_instability, 4),
        "bcg_baseline_drift_ratio": round(drift_ratio, 4),
        "bcg_baseline_drift_flag": drift_flag,
        "corroborated_acoustic_wake_support": round(acoustic_wake_support, 4),
        "movement": movement_evidence,
        "sleep_onset_gate": onset_evidence,
        "n1_time_only_bonus_removed": True,
        "n1_transition_support": round(onset_transition_support, 4),
        "environment_direct_stage_influence": False,
        "n3_gate": n3_gate,
        "n3_hr_conflict": round(n3_hr_conflict, 4),
        "n3_rr_conflict": round(n3_rr_conflict, 4),
        "rem_gate": rem_gate,
        "rem_rr_irregularity": round(rr_irregularity, 4),
        "rem_hr_summary_irregularity": round(hr_summary_irregularity, 4),
        "rem_time_support": round(time_support, 4),
        "ibi_hrv_available": False,
        "hrv_note": "HR-CV is a fixed-cadence summary proxy; RMSSD/SDNN are not calculated",
        "k_complex_available": False,
        "k_complex_note": "BCG amplitude shifts are not EEG K-complexes or spindles",
    }
    return scores, evidence
