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


def interpret_baseline_fit(
    base_scores: Mapping[str, float],
    *,
    confirmed_state: str | None,
    evidence_candidate: str | None,
    n3_gate: bool,
    transition_meta: Mapping[str, Any],
    hr_weight: float,
    rr_weight: float,
) -> dict[str, Any]:
    """Explain HR/RR similarity without presenting it as a Sleep State.

    HR and RR ranges overlap between sleep stages. Their nearest range is
    supporting evidence, but it cannot independently establish EEG-defined
    N1/N2/N3/REM. The returned contract keeps this distinction explicit for
    Admin diagnostics and prevents a high N3 fit being shown as confirmed N3.
    """
    ordered = sorted(
        STAGES,
        key=lambda stage: _finite(base_scores.get(stage), 0.0),
        reverse=True,
    )
    winner, runner_up = ordered[:2]
    weight_total = max(0.0, _finite(hr_weight) + _finite(rr_weight))

    def as_percent(stage: str) -> float:
        if weight_total <= 0:
            return 0.0
        value = _finite(base_scores.get(stage), 0.0) / weight_total * 100
        return round(value, 1)

    winner_percent = as_percent(winner)
    runner_up_percent = as_percent(runner_up)
    agrees = confirmed_state == winner if confirmed_state else None
    if agrees:
        explanation_code = "supports_confirmed_state"
        explanation_th = (
            f"HR/RR ใกล้ {winner.upper()} และสนับสนุนสถานะที่ยืนยัน"
        )
    elif winner == "n3" and not n3_gate:
        explanation_code = "n3_fit_without_n3_gate"
        explanation_th = (
            "HR/RR ใกล้ N3 แต่หลักฐานความนิ่งของ BCG/การหายใจ "
            "และ N3 gate ยังไม่ครบ"
        )
    elif (
        winner == "n3"
        and confirmed_state == "n1"
        and transition_meta.get("blocked_candidate") == "n3"
    ):
        explanation_code = "n3_fit_waiting_for_n2_evidence"
        explanation_th = (
            "หลักฐานใกล้ N3 แต่ระบบไม่ข้าม N1 ไป N3 โดยตรง "
            "จึงรอหลักฐาน N2 ตามลำดับ"
        )
    elif evidence_candidate == winner and transition_meta.get("held"):
        explanation_code = "fit_matches_pending_evidence"
        explanation_th = (
            f"HR/RR สนับสนุน {winner.upper()} และกำลังรอยืนยันต่อเนื่อง"
        )
    else:
        explanation_code = "support_differs_from_confirmed_state"
        explanation_th = (
            f"HR/RR ใกล้ {winner.upper()} แต่สถานะยืนยันใช้ BCG, "
            "movement, เวลา และลำดับสถานะร่วมด้วย"
        )
    return {
        "winner": winner,
        "winner_percent": winner_percent,
        "runner_up": runner_up,
        "runner_up_percent": runner_up_percent,
        "margin_percent": round(winner_percent - runner_up_percent, 1),
        "confirmed_state": confirmed_state,
        "evidence_candidate": evidence_candidate,
        "agrees_with_confirmed_state": agrees,
        "role": "supporting_hr_rr_prior",
        "can_determine_stage_alone": False,
        "explanation_code": explanation_code,
        "explanation_th": explanation_th,
    }


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


def softmax_stage_evidence(
    scores: Mapping[str, Any], *, temperature: float = 4.0,
    eligible_states: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Convert comparable 0..1 evidence budgets to a five-state distribution.

    The result is engineering evidence, not a calibrated medical probability.
    Keeping this conversion here guarantees that live and replay use the same
    scale and avoids the old error where N2 had a larger bonus budget than the
    other four states.
    """
    comparable = {
        stage: _clamp(_finite(scores.get(stage), 0.0)) for stage in STAGES
    }
    eligible = {
        stage: bool((eligible_states or {}).get(stage, True)) for stage in STAGES
    }
    if not any(eligible.values()):
        return {stage: 0.0 for stage in STAGES}
    peak = max(value for stage, value in comparable.items() if eligible[stage])
    scale = max(0.1, _finite(temperature, 4.0))
    weights = {
        stage: (math.exp((value - peak) * scale) if eligible[stage] else 0.0)
        for stage, value in comparable.items()
    }
    return normalise_stage_probabilities(weights)


def fuse_hr_rr_fit_with_stage_probabilities(
    evidence_probabilities: Mapping[str, Any],
    baseline_fit_scores: Mapping[str, Any],
    *,
    eligible_states: Mapping[str, Any],
    confirmed_state: str | None,
    fit_weight: float,
    agreement_weight: float,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Fuse gated HR/RR proximity with the current physiology evidence.

    The fusion happens before EMA and semi-Markov confirmation.  HR/RR Fit
    therefore influences the winner while the independent physiology gates
    retain authority over which states may compete. When the overall Fit
    winner matches the previously confirmed state and that state is still
    gate-eligible, it receives the versioned continuity contribution. A
    mismatch remains free to challenge through the normal confirmation path
    instead of being copied directly into the output.
    """
    eligible = {
        stage: bool(eligible_states.get(stage, False)) for stage in STAGES
    }
    evidence = normalise_stage_probabilities({
        stage: (
            _finite(evidence_probabilities.get(stage), 0.0)
            if eligible[stage] else 0.0
        )
        for stage in STAGES
    })
    overall_fit = normalise_stage_probabilities(baseline_fit_scores)
    eligible_fit = normalise_stage_probabilities({
        stage: (
            _finite(baseline_fit_scores.get(stage), 0.0)
            if eligible[stage] else 0.0
        )
        for stage in STAGES
    })
    overall_winner = max(STAGES, key=overall_fit.get)
    eligible_winner = (
        max(STAGES, key=eligible_fit.get)
        if any(eligible_fit.values()) else None
    )
    agrees = bool(
        confirmed_state in STAGES
        and overall_winner == confirmed_state
        and eligible[confirmed_state]
    )
    requested_weight = agreement_weight if agrees else fit_weight
    applied_weight = _clamp(requested_weight)
    if not any(evidence.values()) or not any(eligible_fit.values()):
        applied_weight = 0.0
    fused = normalise_stage_probabilities({
        stage: (
            (1.0 - applied_weight) * evidence[stage]
            + applied_weight * eligible_fit[stage]
        )
        for stage in STAGES
    })
    ordered_fit = sorted(STAGES, key=overall_fit.get, reverse=True)
    fused_winner = max(STAGES, key=fused.get) if any(fused.values()) else None
    return fused, {
        "method": "gated_linear_pool_before_ema_and_semimarkov",
        "fit_weight": round(applied_weight, 4),
        "configured_fit_weight": round(_clamp(fit_weight), 4),
        "configured_agreement_weight": round(
            _clamp(agreement_weight), 4
        ),
        "overall_fit_winner": overall_winner,
        "overall_fit_runner_up": ordered_fit[1],
        "overall_fit_margin": round(
            overall_fit[overall_winner] - overall_fit[ordered_fit[1]], 4
        ),
        "overall_fit_winner_eligible": eligible[overall_winner],
        "eligible_fit_winner": eligible_winner,
        "confirmed_state_before_fusion": (
            confirmed_state if confirmed_state in STAGES else None
        ),
        "fit_agrees_with_confirmed_state": agrees,
        "evidence_winner_before_fusion": (
            max(STAGES, key=evidence.get) if any(evidence.values()) else None
        ),
        "fused_winner": fused_winner,
        "eligible_fit_probabilities": {
            stage: round(value, 6)
            for stage, value in eligible_fit.items()
        },
        "ineligible_state_can_receive_fit_mass": False,
        "fit_can_bypass_state_gate": False,
        "fit_can_bypass_confirmation": False,
        "aasm_psg_probability": False,
    }


def evidence_candidate_with_abstention(
    probabilities: Mapping[str, Any],
    *,
    minimum_winner: float,
    minimum_margin: float,
    gated_stage_thresholds: Mapping[str, tuple[float, float]] | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Return a candidate only when absolute evidence and separation pass.

    Ambiguous evidence remains visible in the Admin evidence stream but must
    not be converted into a W/N1/N2/N3/REM decision.  This is the explicit
    abstention boundary required for a non-EEG wellness estimator.
    """
    values = normalise_stage_probabilities(probabilities)
    ordered = sorted(STAGES, key=values.get, reverse=True)
    winner, runner_up = ordered[0], ordered[1]
    winner_value = values[winner]
    margin = winner_value - values[runner_up]
    threshold = _clamp(minimum_winner)
    margin_threshold = max(0.0, _finite(minimum_margin, 0.0))
    threshold_source = "general"
    gated_threshold = (gated_stage_thresholds or {}).get(winner)
    if gated_threshold is not None:
        threshold = _clamp(gated_threshold[0])
        margin_threshold = max(0.0, _finite(gated_threshold[1], 0.0))
        threshold_source = f"{winner}_independent_gate"
    passed = bool(winner_value >= threshold and margin >= margin_threshold)
    return (winner if passed else None), {
        "winner": winner,
        "runner_up": runner_up,
        "winner_value": round(winner_value, 4),
        "runner_up_value": round(values[runner_up], 4),
        "winner_margin": round(margin, 4),
        "minimum_winner": round(threshold, 4),
        "minimum_margin": round(margin_threshold, 4),
        "threshold_source": threshold_source,
        "passed": passed,
        "decision": "candidate" if passed else "abstain",
        "aasm_psg_probability": False,
    }


def stable_probability_candidate(
    probabilities: Mapping[str, Any],
    current_stage: str | None,
    *,
    switch_margin: float,
) -> tuple[str | None, dict[str, Any]]:
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
    eligible_states: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Select a stable candidate without starving gated N2/N3 progression.

    EMA remains the default candidate source. A current N2 winner may bypass a
    trailing N1 EMA only for the natural N1 -> N2 progression, after the N2
    physiology gate and normal winner margin pass. N3 keeps the equivalent
    strict-gate override. The caller's semi-Markov state machine still requires
    two consecutive evidence epochs/60 seconds, so neither override can create
    a stage from one noisy 30-second window.
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
    gated_n2_progression_override = bool(
        current_stage == "n1"
        and current_candidate == "n2"
        and (
            eligible_states is None
            or eligible_states.get("n2", False)
        )
    )
    gated_n3_override = bool(n3_gate and current_candidate == "n3")
    # Entry into N1 has already passed the explicit onset physiology gate.
    # Let that current 30-second evidence reach the two-epoch confirmer instead
    # of waiting for the Wake-heavy EMA to turn over. This fixes multi-hour
    # missed onset without allowing elapsed time or a baseline range alone to
    # create sleep.
    gated_n1_onset_override = bool(
        current_stage in {None, "wake"}
        and sleep_onset_gate_passed
        and current_candidate == "n1"
    )
    current_override = (
        gated_n2_progression_override
        or gated_n3_override
        or gated_n1_onset_override
    )
    candidate = current_candidate if current_override else ema_candidate
    onset_guard_held = bool(
        current_stage in {None, "wake"}
        and candidate != "wake"
        and not sleep_onset_gate_passed
    )
    if onset_guard_held:
        candidate = "wake"
    # EMA can retain a challenger after its current physiology gate closes.
    # It may hold an already-confirmed state for temporal continuity, but it
    # must never start a transition into a newly ineligible state.
    candidate_gate_open = bool(
        eligible_states is None or eligible_states.get(candidate, False)
    )
    closed_gate_transition_prevented = bool(
        candidate not in {None, current_stage} and not candidate_gate_open
    )
    if closed_gate_transition_prevented:
        candidate = current_stage if current_stage in STAGES else None
    metadata = dict(current_metadata if current_override else ema_metadata)
    metadata.update({
        "candidate_source": (
            "sleep_onset_guard"
            if onset_guard_held
            else (
                "gated_n1_current_30s_evidence_before_ema"
                if gated_n1_onset_override else
                "gated_n2_current_30s_evidence_before_ema"
                if gated_n2_progression_override else
                "gated_n3_current_30s_evidence_before_ema"
                if gated_n3_override else "ema_probability"
            )
        ),
        "ema_role": "default_candidate_stability_and_display",
        "gated_n3_current_evidence_override": gated_n3_override,
        "gated_n2_current_evidence_override": (
            gated_n2_progression_override
        ),
        "gated_n1_onset_current_evidence_override": gated_n1_onset_override,
        "current_candidate_gate_open": candidate_gate_open,
        "closed_gate_transition_prevented": closed_gate_transition_prevented,
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
    onset_min_relative_sleep_support: float = 0.20,
    onset_max_hr_rise_bpm_per_min: float = 0.50,
    onset_max_rr_rise_per_min: float = 0.50,
    onset_initial_wake_support: float = 0.75,
    deep_cv_threshold: float = 0.025,
    rem_cv_threshold: float = 0.060,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Return comparable five-state evidence budgets and an audit record.

    The hierarchy is deliberate: signal validity is handled by the caller,
    then sleep/wake physiology gates stage-specific evidence, and only then may
    the semi-Markov path confirm a label.  Population/personal ranges are weak
    priors.  They cannot create N2/N3/REM without session-relative physiology.
    ``hr_cv`` is fixed-cadence summary variation, not RMSSD/SDNN.
    """
    baseline_fit = {
        stage: _clamp(_finite(base_scores.get(stage), 0.0)) for stage in STAGES
    }
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
    mean_hr = _optional_finite(metrics.get("mean_hr"))
    mean_rr = _optional_finite(metrics.get("mean_rr"))
    awake_hr = _optional_finite(metrics.get("awake_hr_reference"))
    awake_rr = _optional_finite(metrics.get("awake_rr_reference"))
    current_stage = str(metrics.get("current_stage") or "").casefold()
    sleep_elapsed_min = max(
        0.0, _finite(metrics.get("sleep_elapsed_min"), elapsed_min)
    )
    sleep_onset_established = bool(metrics.get("sleep_onset_established"))
    # SPH0645 may only corroborate a Wake-compatible BCG/bed event.  The
    # upstream feature builder keeps this at zero when sound is loud by itself;
    # bounding it again here prevents malformed telemetry from dominating the
    # physiological score during live operation or historical replay.
    acoustic_wake_support = _clamp(
        _finite(metrics.get("corroborated_acoustic_wake_support"), 0.0),
        0.0,
        0.35,
    )

    # Stabilisation separates transitional N1 from sustained N2.  The BCG
    # envelope is a quality/stability proxy, never a K-complex/spindle claim.
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

    def proportional_drop(reference: float | None, current: float | None,
                          full_scale: float) -> float:
        if reference is None or current is None or reference <= 0:
            return 0.0
        return _clamp((reference - current) / (reference * full_scale))

    def proportional_rise(reference: float | None, current: float | None,
                          full_scale: float) -> float:
        if reference is None or current is None or reference <= 0:
            return 0.0
        return _clamp((current - reference) / (reference * full_scale))

    hr_drop = proportional_drop(awake_hr, mean_hr, 0.12)
    rr_drop = proportional_drop(awake_rr, mean_rr, 0.18)
    relative_sleep_support_weighted = 0.65 * hr_drop + 0.35 * rr_drop
    # RR rate does not have to decrease at sleep onset in every person. Keep
    # the concordant value for audit, but use HR transition plus respiratory
    # pattern quality for the candidate gate. This remains a wellness proxy.
    relative_sleep_support_concordant = min(hr_drop, rr_drop)
    relative_sleep_support = relative_sleep_support_weighted
    hr_rise = proportional_rise(awake_hr, mean_hr, 0.10)
    rr_rise = proportional_rise(awake_rr, mean_rr, 0.15)
    relative_wake_support = max(hr_rise, rr_rise)

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
    # Sleep-onset evidence has two supported shapes: HR is currently trending
    # down, or HR has reached a lower plateau. Both paths require a quiet bed,
    # waveform evidence and a regular respiratory pattern. RR-rate decrease is
    # retained as supporting evidence, never a mandatory gate.
    minimum_relative_support = _clamp(onset_min_relative_sleep_support)
    hr_downward_transition = _clamp(-hr_slope / 4.0)
    respiratory_onset_support = bool(
        waveform_available
        and regularity is not None
        and regularity >= 0.42
        and rr_stability >= 0.35
    )
    trend_onset_passed = bool(
        onset_evidence["observation_complete"]
        and onset_evidence["quiet_bed"]
        and onset_evidence["no_vital_rise"]
        and hr_downward_transition >= onset_min_downward_transition
        and respiratory_onset_support
    )
    level_shift_onset_passed = bool(
        onset_evidence["observation_complete"]
        and onset_evidence["quiet_bed"]
        and onset_evidence["no_vital_rise"]
        and hr_drop >= minimum_relative_support
        and respiratory_onset_support
    )
    onset_evidence.update({
        "trend_onset_passed": trend_onset_passed,
        "level_shift_onset_passed": level_shift_onset_passed,
        "relative_sleep_support": round(relative_sleep_support, 4),
        "relative_sleep_support_weighted": round(
            relative_sleep_support_weighted, 4
        ),
        "relative_sleep_support_concordant": round(
            relative_sleep_support_concordant, 4
        ),
        "hr_downward_transition": round(hr_downward_transition, 4),
        "respiratory_onset_support": respiratory_onset_support,
        "respiratory_regularity": (
            round(regularity, 4) if regularity is not None else None
        ),
        "rr_rate_drop_required": False,
        "minimum_relative_sleep_support": round(minimum_relative_support, 4),
        "passed": bool(trend_onset_passed or level_shift_onset_passed),
        "accepted_path": (
            "downward_trend" if trend_onset_passed
            else "sustained_relative_drop" if level_shift_onset_passed
            else None
        ),
    })
    initial_wake = (
        _clamp(onset_initial_wake_support)
        if not onset_evidence["observation_complete"] else 0.0
    )
    onset_transition_support = (
        max(
            hr_downward_transition,
            hr_drop * 0.80
            if level_shift_onset_passed else 0.0,
        )
        if onset_evidence["observation_complete"]
        and onset_evidence["quiet_bed"]
        and onset_evidence["no_vital_rise"]
        else 0.0
    )
    quiet_bed = bool(
        movement_evidence.get("sleep_compatible")
        and movement < move_wake_ratio
    )
    sleep_sequence_established = bool(
        sleep_onset_established
        or current_stage in {"n1", "n2", "n3", "rem"}
    )
    # A broad Wake baseline fit is not enough to wake a sleeping path: HR/RR
    # ranges overlap heavily between quiet wakefulness and sleep. Once onset is
    # established, require a relative autonomic rise or corroborated sustained
    # movement before Wake may compete. Quiet position changes remain sleep-
    # compatible and can transition through N1 instead.
    wake_transition_gate = bool(
        not sleep_sequence_established
        or current_stage == "wake"
        or movement_evidence.get("strong_wake")
        or (
            relative_wake_support >= 0.20
            and (
                hr_slope >= 0.15
                or rr_slope >= 0.15
                or amplitude_instability >= 0.60
            )
        )
    )
    n1_gate = bool(
        quiet_bed and (
            onset_evidence["passed"]
            or sleep_sequence_established
        )
    )
    n2_gate = bool(
        quiet_bed
        and waveform_available
        and sleep_sequence_established
        and current_stage in {"n1", "n2", "n3", "rem"}
        and max(relative_sleep_support, hr_drop) >= 0.18
    )

    # N3 is deliberately gated: low HR/RR proximity alone cannot create it.
    # The label needs quiet BCG, low summary variability and regular breathing.
    n3_hr_conflict = max(0.0, _finite(hr_fits.get("n2"), 0.0)
                         - _finite(hr_fits.get("n3"), 0.0))
    n3_rr_conflict = max(0.0, _finite(rr_fits.get("n2"), 0.0)
                         - _finite(rr_fits.get("n3"), 0.0))
    deep_cv_limit = max(0.010, _finite(deep_cv_threshold, 0.025))
    deep_rr_cv_limit = max(0.025, min(0.050, deep_cv_limit * 1.6))
    n3_gate = bool(
        waveform_available
        and not drift_flag
        and current_stage in {"n2", "n3"}
        and movement < move_deep_ratio
        and hr_cv <= deep_cv_limit
        and rr_cv <= deep_rr_cv_limit
        and regularity is not None
        and regularity >= 0.58
        and n3_hr_conflict < 0.08
        and max(relative_sleep_support, hr_drop) >= 0.40
    )

    # REM receives no standalone time boost.  Time acts only after the current
    # window shows irregular breathing on a quiet bed.  True IBI-HRV remains
    # unavailable, so summary-bucket HR-CV has intentionally small influence.
    rr_irregularity = _clamp((rr_cv - 0.035) / 0.045)
    hr_summary_irregularity = _clamp((hr_cv - 0.025) / 0.055)
    time_support = _clamp((sleep_elapsed_min - 45.0) / 45.0)
    respiratory_not_n3_like = (
        respiratory_entropy is not None and respiratory_entropy >= 0.40
    )
    rem_cv_limit = max(0.035, _finite(rem_cv_threshold, 0.060))
    rem_gate = bool(
        waveform_available
        and not drift_flag
        and sleep_sequence_established
        and current_stage in {"n1", "n2", "n3", "rem"}
        and sleep_elapsed_min >= 45.0
        and movement < move_deep_ratio
        and rr_cv >= max(0.040, rem_cv_limit * 0.75)
        # REM-like respiratory irregularity without any concurrent HR-summary
        # variability was frequently sensor noise/N2 in retrospective replay.
        # This is a fixed-cadence proxy, not RMSSD/SDNN.
        and hr_cv >= 0.015
        and respiratory_not_n3_like
        and shift_ratio is not None
        and shift_ratio <= 0.15
    )
    entropy_irregularity = (
        _clamp((respiratory_entropy - 0.35) / 0.40)
        if respiratory_entropy is not None else 0.0
    )

    # Every state receives the same 0..1 evidence budget.  A failed gate
    # leaves only weak telemetry for W/N1 and zero candidate evidence for
    # N2/N3/REM; it never receives a compensating default-stage bonus.
    wake_motion = _clamp(
        float(movement_evidence["wake_score_support"]) / 2.0
    )
    wake_score = (
        0.30 * baseline_fit["wake"]
        + 0.25 * wake_motion
        + 0.20 * relative_wake_support
        + 0.10 * (1.0 - flat_trend)
        + 0.10 * initial_wake
        + 0.05 * (acoustic_wake_support / 0.35 if acoustic_wake_support else 0.0)
    )
    n1_transition = max(
        onset_transition_support,
        relative_wake_support if current_stage in {"n2", "n3", "rem"} else 0.0,
    )
    if n1_gate and current_stage == "wake":
        # Entry N1: the sustained level drop prevents a missed descending
        # slope from trapping the path in Wake.
        n1_score = (
            0.25 * baseline_fit["n1"]
            + 0.20 * n1_transition
            + 0.25 * relative_sleep_support
            + 0.15 * (1.0 - flat_trend)
            + 0.15 * amplitude_instability
        )
        n1_phase = "entry_from_wake"
    elif n1_gate:
        # After onset, a low HR/RR plateau is evidence for sleep generally,
        # not evidence that the user remains in N1.  Keeping the entry bonus
        # active indefinitely was the source of N1-dominant overnight replay.
        # Persistent N1 now requires transition/instability evidence; stable
        # physiology can progress to the separately gated N2 candidate.
        n1_score = (
            0.25 * baseline_fit["n1"]
            + 0.30 * n1_transition
            + 0.25 * amplitude_instability
            + 0.20 * (1.0 - (hr_stability + rr_stability) / 2.0)
        )
        n1_phase = "post_onset_transition"
    else:
        n1_score = 0.05 * baseline_fit["n1"]
        n1_phase = "gate_closed"
    n2_score = (
        0.25 * baseline_fit["n2"]
        + 0.20 * hr_stability
        + 0.20 * rr_stability
        + 0.15 * flat_trend
        + 0.10 * respiratory_stability
        + 0.05 * amplitude_stability
        + 0.05 * relative_sleep_support
    ) if n2_gate else 0.0
    n3_score = (
        0.15 * baseline_fit["n3"]
        + 0.20 * hr_stability
        + 0.15 * rr_stability
        + 0.25 * respiratory_stability
        + 0.10 * amplitude_stability
        + 0.10 * relative_sleep_support
        + 0.15  # reward only after every independent N3 gate has passed
    ) if n3_gate else 0.0
    if n3_gate:
        n3_score -= min(
            0.20,
            n3_rr_conflict * n3_rr_conflict_penalty * 0.15
            + n3_hr_conflict * 0.15,
        )
    n2_score += (
        min(0.05, n3_rr_conflict * n2_rr_conflict_support * 0.10)
        if n2_gate else 0.0
    )
    rem_score = (
        0.20 * baseline_fit["rem"]
        + 0.35 * rr_irregularity
        + 0.10 * hr_summary_irregularity * rem_variability_weight
        + 0.20 * entropy_irregularity
        + 0.15 * time_support
    ) if rem_gate else 0.0
    scores = {
        "wake": _clamp(wake_score),
        "n1": _clamp(n1_score),
        "n2": _clamp(n2_score),
        "n3": _clamp(n3_score),
        "rem": _clamp(rem_score),
    }

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
        "sleep_onset_established": sleep_onset_established,
        "sleep_sequence_established": sleep_sequence_established,
        "wake_gate": wake_transition_gate,
        "n1_gate": n1_gate,
        "n2_gate": n2_gate,
        "n1_time_only_bonus_removed": True,
        "n1_transition_support": round(onset_transition_support, 4),
        "n1_phase": n1_phase,
        "n1_relative_drop_is_entry_only": True,
        "awake_hr_reference": round(awake_hr, 2) if awake_hr is not None else None,
        "awake_rr_reference": round(awake_rr, 2) if awake_rr is not None else None,
        "hr_drop_support": round(hr_drop, 4),
        "rr_drop_support": round(rr_drop, 4),
        "relative_sleep_support": round(relative_sleep_support, 4),
        "relative_sleep_support_weighted": round(
            relative_sleep_support_weighted, 4
        ),
        "relative_sleep_support_concordant": round(
            relative_sleep_support_concordant, 4
        ),
        "relative_wake_support": round(relative_wake_support, 4),
        "environment_direct_stage_influence": False,
        "n3_gate": n3_gate,
        "n3_hr_cv_limit": round(deep_cv_limit, 4),
        "n3_rr_cv_limit": round(deep_rr_cv_limit, 4),
        "n3_hr_conflict": round(n3_hr_conflict, 4),
        "n3_rr_conflict": round(n3_rr_conflict, 4),
        "rem_gate": rem_gate,
        "rem_hr_cv_reference": round(rem_cv_limit, 4),
        "rem_rr_irregularity": round(rr_irregularity, 4),
        "rem_hr_summary_irregularity": round(hr_summary_irregularity, 4),
        "rem_time_support": round(time_support, 4),
        "sleep_elapsed_min": round(sleep_elapsed_min, 2),
        "comparable_score_budget": "0..1_each_state",
        "ibi_hrv_available": False,
        "hrv_note": "HR-CV is a fixed-cadence summary proxy; RMSSD/SDNN are not calculated",
        "k_complex_available": False,
        "k_complex_note": "BCG amplitude shifts are not EEG K-complexes or spindles",
    }
    return scores, evidence
