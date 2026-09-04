#!/usr/bin/env python3
"""Re-score persisted ZEEP Sleep State rounds with the current baseline.

The current live estimator writes one Evidence and at most one confirmed State
every 30 seconds; older Sessions may contain 5- or 10-second decisions. Those
events retain the rolling-window HR/RR means, variability, movement and any
time-aligned BCG/audio/bed corroboration available at capture time. Environment
support remains explanatory metadata and never changes a replayed stage. This
tool replays the transition policy in timestamp order, creates an online SQLite
backup, and updates only rounds produced by an older estimator version.

It intentionally does not invent EEG/EOG/EMG evidence: the resulting W/N1/N2/
N3/REM labels remain ZEEP Wellness estimates rather than retrospective AASM
scores.  Run without ``--apply`` first to inspect the change matrix.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, deque
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sqlite3
from typing import Any, Optional

from sleep_signal_features import (
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    arousal_proxy_evidence,
    bed_exit_window_evidence,
    decode_bcg_samples,
    filter_vital_values,
    movement_window_metrics,
    summary_features,
    waveform_features,
)
from sleep_stage_scoring import (
    align_probabilities_to_emitted_stage,
    candidate_from_stage_evidence,
    score_sleep_evidence,
    smooth_stage_probabilities,
)
from sleep_system_policy import (
    SLEEP_ALLOWED_TRANSITIONS,
    SLEEP_CONFIRMATION_SECONDS,
    SLEEP_CONFIRM_EPOCHS,
    SLEEP_HISTORY_BACKFILL_VERSION,
    PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED,
    SLEEP_DISPLAY_WINNER_MARGIN,
    SLEEP_PROBABILITY_EMA_ALPHA,
    SLEEP_PROBABILITY_SWITCH_MARGIN,
    SLEEP_ONSET_INITIAL_WAKE_SUPPORT,
    SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN,
    SLEEP_ONSET_MAX_MOVEMENT_RATIO,
    SLEEP_ONSET_MAX_RR_RISE_PER_MIN,
    SLEEP_ONSET_MIN_DOWNWARD_TRANSITION,
    SLEEP_ONSET_MIN_OBSERVATION_SECONDS,
    SLEEP_PROHIBITED_TRANSITIONS,
    SLEEP_STAGE_CONFIRM_TICKS,
    SLEEP_STAGE_CONFIRMATION_SECONDS,
    SLEEP_STAGE_MIN_DWELL_SECONDS,
    ZEEP_SLEEP_STATES,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
)


MAINTENANCE_TOOL_NAME = "reclassify_sleep_history.py"
BACKFILL_VERSION = SLEEP_HISTORY_BACKFILL_VERSION
STAGES = ZEEP_SLEEP_STATES
PROHIBITED_TRANSITIONS = SLEEP_PROHIBITED_TRANSITIONS


def parse_timestamp(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def decision_interval_seconds(
    parsed: list[tuple[sqlite3.Row, dict[str, Any]]],
    fallback: float = 5.0,
) -> float:
    """Recover each Session's versioned decision cadence without rewriting it."""
    declared: list[float] = []
    for _, value in parsed:
        try:
            interval = float(value.get("sample_interval_s"))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(interval) and interval > 0:
            declared.append(interval)
    if declared:
        ordered = sorted(declared)
        return ordered[len(ordered) // 2]

    timestamps = [parse_timestamp(row["timestamp"]) for row, _ in parsed]
    deltas = sorted(
        later - earlier
        for earlier, later in zip(timestamps, timestamps[1:])
        if 0 < later - earlier <= 300
    )
    if deltas:
        return deltas[len(deltas) // 2]
    return fallback


class RawBcgWindow:
    """Rebuild versioned decision windows from persisted raw BCG packets."""

    def __init__(self, packets: list[sqlite3.Row], sample_seconds: float = 5.0) -> None:
        self.sample_seconds = sample_seconds
        ordered = sorted(packets, key=lambda row: row["timestamp"])
        self.packets = ordered
        self.timestamps = [parse_timestamp(row["timestamp"]) for row in ordered]
        # Decode once because adjacent decisions reuse most of the
        # same rolling 60-second window.
        self.packet_samples = [
            decode_bcg_samples(
                row["bcg_base64"]
                if "bcg_base64" in (row.keys() if hasattr(row, "keys") else row)
                else None
            )
            for row in ordered
        ]

    @staticmethod
    def _mean(values: list[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    def reconstruct(
        self,
        value: dict[str, Any],
        *,
        terminal_session_boundary: bool = False,
    ) -> Optional[dict[str, Any]]:
        start_raw = value.get("window_start")
        end_raw = value.get("window_end")
        if not start_raw or not end_raw:
            return None
        start = parse_timestamp(start_raw)
        end = parse_timestamp(end_raw)
        requested = max(1, int(value.get("sample_count") or round((end - start) / self.sample_seconds)))
        bucket_hrs: list[float] = []
        bucket_rrs: list[float] = []
        bucket_statuses: list[int] = []
        raw_samples: list[int] = []
        packets_used = 0
        invalid_hr_packets = 0
        invalid_rr_packets = 0
        latest_raw_exit_frames = 0
        latest_raw_total_frames = 0
        for index in range(requested):
            bucket_start = start + index * self.sample_seconds
            bucket_end = min(end, bucket_start + self.sample_seconds)
            left = bisect_right(self.timestamps, bucket_start)
            right = bisect_right(self.timestamps, bucket_end)
            rows = self.packets[left:right]
            if not rows:
                continue
            for packet_samples in self.packet_samples[left:right]:
                raw_samples.extend(packet_samples)
            packets_used += len(rows)
            raw_hrs = [row["heart_rate"] for row in rows if row["heart_rate"] is not None]
            raw_rrs = [row["respiration_rate"] for row in rows
                       if row["respiration_rate"] is not None]
            hrs = filter_vital_values(raw_hrs, HR_SANITY_RANGE_BPM)
            rrs = filter_vital_values(raw_rrs, RR_SANITY_RANGE_PER_MIN)
            invalid_hr_packets += len(raw_hrs) - len(hrs)
            invalid_rr_packets += len(raw_rrs) - len(rrs)
            statuses = [int(row["status_code"]) for row in rows if row["status_code"] is not None]
            latest_raw_exit_frames = sum(status == 1 for status in statuses)
            latest_raw_total_frames = len(statuses)
            hr = self._mean(hrs)
            rr = self._mean(rrs)
            if hr is not None:
                bucket_hrs.append(hr)
            if rr is not None:
                bucket_rrs.append(rr)
            if statuses:
                bucket_statuses.append(2 if 2 in statuses else statuses[-1])
        if not bucket_hrs or not bucket_rrs:
            return None
        mean_hr = self._mean(bucket_hrs) or 0.0
        mean_rr = self._mean(bucket_rrs) or 0.0
        hr_sd = math.sqrt(sum((item - mean_hr) ** 2 for item in bucket_hrs) / len(bucket_hrs))
        rr_sd = math.sqrt(sum((item - mean_rr) ** 2 for item in bucket_rrs) / len(bucket_rrs))
        trends = summary_features(bucket_hrs, bucket_rrs, self.sample_seconds)
        signal = waveform_features(raw_samples)
        movement_window = movement_window_metrics(bucket_statuses)
        bed_exit = bed_exit_window_evidence(
            bucket_statuses,
            latest_raw_exit_frames=latest_raw_exit_frames,
            latest_raw_total_frames=latest_raw_total_frames,
            terminal_session_boundary=terminal_session_boundary,
        )
        return {
            "mean_hr": round(mean_hr, 1),
            "mean_rr": round(mean_rr, 1),
            "hr_cv": round(hr_sd / mean_hr if mean_hr else 0.0, 4),
            "rr_cv": round(rr_sd / mean_rr if mean_rr else 0.0, 4),
            "movement_ratio": movement_window["movement_ratio"],
            "max_moving_run_frames": movement_window["max_moving_run_frames"],
            "movement_burst_count": movement_window["movement_burst_count"],
            "bed_status": (
                "Moving" if bucket_statuses and bucket_statuses[-1] == 2
                else "Get out of bed" if bed_exit["confirmed"]
                else "On bed"
            ),
            "bed_exit_evidence": bed_exit,
            "raw_packets_used": packets_used,
            "invalid_hr_packets": invalid_hr_packets,
            "invalid_rr_packets": invalid_rr_packets,
            "feature_buckets": max(len(bucket_hrs), len(bucket_rrs)),
            **trends,
            **signal,
        }


class HistoricalStagePath:
    """Offline equivalent of the live semi-Markov continuity guard."""

    confirm_ticks = SLEEP_STAGE_CONFIRM_TICKS
    minimum_dwell = SLEEP_STAGE_MIN_DWELL_SECONDS

    def __init__(self) -> None:
        self.seen: deque[str] = deque(maxlen=8)
        self.last: Optional[str] = None
        self.stage_since: Optional[float] = None
        self.candidate: Optional[str] = None
        self.candidate_ticks = 0
        self.cycle_has_n1 = False
        self.probability_ema: Optional[dict[str, float]] = None

    def _allowed(self, candidate: str, strong_wake: bool) -> bool:
        previous = self.last
        if previous is None:
            return candidate == "wake"
        if candidate == "wake" and strong_wake:
            return True
        if previous == "wake":
            return candidate in {"wake", "n1"}
        if candidate in {"n2", "n3", "rem"} and not self.cycle_has_n1:
            return False
        return candidate in SLEEP_ALLOWED_TRANSITIONS.get(
            previous, frozenset({"wake"}))

    def _fallback(self, blocked: str) -> str:
        previous = self.last
        if previous in STAGES:
            return previous
        return "wake"

    def stabilize(self, candidate: str, now: float, strong_wake: bool) -> tuple[str, dict[str, Any]]:
        allowed = self._allowed(candidate, strong_wake)
        target = candidate if allowed else self._fallback(candidate)
        meta: dict[str, Any] = {
            "raw_candidate": candidate,
            "bridge_state": None,
            "blocked_candidate": candidate if not allowed else None,
            "transition_allowed": allowed,
            "previous_state": self.last,
            "strong_wake_override": strong_wake,
            "policy": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        }
        if not allowed:
            self.candidate = None
            self.candidate_ticks = 0
            meta.update({
                "required_ticks": 0,
                "candidate_ticks": 0,
                "candidate_epochs": 0,
                "required_epochs": 0,
                "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                    target, SLEEP_CONFIRMATION_SECONDS),
                "held": True,
                "confirmation_complete": False,
                "confirmed_state": None,
                "decision": "blocked_transition_abstain",
            })
            return (self.last or "wake"), meta
        if self.last is None:
            if self.candidate == target:
                self.candidate_ticks += 1
            else:
                self.candidate = target
                self.candidate_ticks = 1
            required = int(self.confirm_ticks.get(target, SLEEP_CONFIRM_EPOCHS))
            held = self.candidate_ticks < required
            meta.update({
                "required_ticks": required,
                "candidate_ticks": self.candidate_ticks,
                "candidate_epochs": self.candidate_ticks,
                "required_epochs": required,
                "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                    target, SLEEP_CONFIRMATION_SECONDS),
                "held": held,
                "confirmation_complete": not held,
                "confirmed_state": None if held else target,
            })
            return target, meta
        if target == self.last:
            self.candidate = None
            self.candidate_ticks = 0
            meta.update({
                "required_ticks": SLEEP_CONFIRM_EPOCHS,
                "candidate_ticks": SLEEP_CONFIRM_EPOCHS,
                "candidate_epochs": SLEEP_CONFIRM_EPOCHS,
                "required_epochs": SLEEP_CONFIRM_EPOCHS,
                "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                    self.last, SLEEP_CONFIRMATION_SECONDS),
                "held": False,
                "confirmation_complete": True,
                "confirmed_state": self.last,
            })
            return self.last, meta

        dwell = max(0.0, now - self.stage_since) if self.stage_since is not None else 0.0
        if self.candidate == target:
            self.candidate_ticks += 1
        else:
            self.candidate = target
            self.candidate_ticks = 1
        required = self.confirm_ticks.get(target, 2)
        held = dwell < self.minimum_dwell.get(self.last, 0.0) or self.candidate_ticks < required
        meta.update({
            "required_ticks": required,
            "candidate_ticks": self.candidate_ticks,
            "candidate_epochs": self.candidate_ticks,
            "required_epochs": required,
            "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                target, SLEEP_CONFIRMATION_SECONDS),
            "dwell_s": round(dwell, 1),
            "minimum_dwell_s": self.minimum_dwell.get(self.last, 0.0),
            "held": held,
            "confirmation_complete": not held,
            "confirmed_state": self.last if held else target,
        })
        return (self.last if held else target), meta

    def commit(self, stage: str, now: float) -> tuple[bool, list[str]]:
        changed = self.last != stage
        if stage == "wake":
            self.seen.clear()
            self.cycle_has_n1 = False
        elif stage == "n1":
            self.cycle_has_n1 = True
        if changed:
            self.seen.append(stage)
            self.stage_since = now
            self.candidate = None
            self.candidate_ticks = 0
        self.last = stage
        return changed, list(self.seen)


def adjusted_probabilities(raw: dict[str, float], selected: str) -> dict[str, float]:
    result = align_probabilities_to_emitted_stage(
        raw, selected, winner_margin=SLEEP_DISPLAY_WINNER_MARGIN)
    rounded = {key: round(value, 4) for key, value in result.items()}
    rounded[selected] = round(rounded[selected] + round(1.0 - sum(rounded.values()), 4), 4)
    return rounded


def rescore_event(
    value: dict[str, Any],
    event_timestamp: str,
    session_start: float,
    baseline: dict[str, Any],
    rem_variability_weight: float,
    cv_deep_threshold: float,
    cv_rem_threshold: float,
    path: HistoricalStagePath,
    zeep: Any,
    reclassified_at: str,
) -> dict[str, Any]:
    metrics = dict(value.get("metrics") or {})
    mean_hr = float(metrics["mean_hr"])
    mean_rr = float(metrics["mean_rr"])
    hr_cv = float(metrics.get("hr_cv") or 0.0)
    rr_cv = float(metrics.get("rr_cv") or 0.0)
    movement = float(metrics.get("movement_ratio") or 0.0)
    bed_status = str(metrics.get("bed_status") or "")
    now = parse_timestamp(event_timestamp)
    elapsed_min = max(0.0, (now - session_start) / 60.0)

    base_scores: dict[str, float] = {}
    hr_fits: dict[str, float] = {}
    rr_fits: dict[str, float] = {}
    for stage in STAGES:
        hr_fit, _ = zeep._baseline_interval_proximity(mean_hr, baseline[stage]["hr"])
        rr_fit, _ = zeep._baseline_interval_proximity(mean_rr, baseline[stage]["rr"])
        base_scores[stage] = zeep._physiological_baseline_fit(hr_fit, rr_fit)
        hr_fits[stage] = hr_fit
        rr_fits[stage] = rr_fit
    scores, evidence = score_sleep_evidence(
        base_scores=base_scores,
        hr_fits=hr_fits,
        rr_fits=rr_fits,
        metrics=metrics,
        elapsed_min=elapsed_min,
        rem_variability_weight=rem_variability_weight,
        n3_rr_conflict_penalty=zeep.SLEEP_N3_RR_CONFLICT_PENALTY,
        n2_rr_conflict_support=zeep.SLEEP_N2_RR_CONFLICT_SUPPORT,
        move_wake_ratio=zeep.SLEEP_MOVE_WAKE_RATIO,
        move_deep_ratio=zeep.SLEEP_MOVE_DEEP_RATIO,
        onset_min_observation_minutes=SLEEP_ONSET_MIN_OBSERVATION_SECONDS / 60.0,
        onset_max_movement_ratio=SLEEP_ONSET_MAX_MOVEMENT_RATIO,
        onset_min_downward_transition=SLEEP_ONSET_MIN_DOWNWARD_TRANSITION,
        onset_max_hr_rise_bpm_per_min=SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN,
        onset_max_rr_rise_per_min=SLEEP_ONSET_MAX_RR_RISE_PER_MIN,
        onset_initial_wake_support=SLEEP_ONSET_INITIAL_WAKE_SUPPORT,
    )

    maximum = max(scores.values())
    weights = {stage: math.exp((score - maximum) * 1.8) for stage, score in scores.items()}
    total = sum(weights.values())
    raw = {stage: weight / total for stage, weight in weights.items()}
    instant_candidate = max(raw, key=raw.get)
    path.probability_ema = smooth_stage_probabilities(
        path.probability_ema,
        raw,
        alpha=SLEEP_PROBABILITY_EMA_ALPHA,
    )
    # Match live estimation: keep EMA continuity for every state except a
    # current N3 winner that has passed the strict physiology gate.
    candidate, probability_transition = candidate_from_stage_evidence(
        raw,
        path.probability_ema,
        path.last,
        switch_margin=SLEEP_PROBABILITY_SWITCH_MARGIN,
        n3_gate=bool(evidence["n3_gate"]),
        sleep_onset_gate_passed=bool(
            evidence["sleep_onset_gate"]["passed"]
        ),
        eligible_states={
            "wake": evidence["wake_gate"],
            "n1": evidence["n1_gate"],
            "n2": evidence["n2_gate"],
            "n3": evidence["n3_gate"],
            "rem": evidence["rem_gate"],
        },
    )
    strong_wake = bool(
        instant_candidate == "wake" and evidence["movement"]["strong_wake"]
    )
    if bed_status == "Get out of bed":
        candidate = "wake"
        strong_wake = True
        raw = {"wake": 0.99, "n1": 0.01, "n2": 0.0, "n3": 0.0, "rem": 0.0}
        path.probability_ema = dict(raw)
    elif strong_wake:
        candidate = "wake"

    selected, transition = path.stabilize(candidate, now, strong_wake)
    confirmed_state = transition.get("confirmed_state")
    if confirmed_state not in STAGES:
        confirmed_state = path.last if path.last in STAGES else "wake"
    probabilities = {
        key: round(value, 4) for key, value in path.probability_ema.items()
    }
    probabilities[candidate] = round(
        probabilities[candidate] + round(1.0 - sum(probabilities.values()), 4), 4)
    confirmed_probabilities = adjusted_probabilities(
        path.probability_ema, confirmed_state)
    selected = confirmed_state
    changed, progression = path.commit(selected, now)
    winner = probabilities[candidate]
    confidence = "high" if winner >= 0.72 else "medium" if winner >= 0.48 else "low"
    if transition.get("bridge_state") or transition.get("held") or int(value.get("sample_count") or 0) < 6:
        confidence = "low"
    if metrics.get("bcg_baseline_drift_flag"):
        confidence = "low"

    old_state = value.get("state")
    old_version = value.get("estimator_version")
    reason = (
        f"Historical replay · HR เฉลี่ย {mean_hr:.1f} · RR เฉลี่ย {mean_rr:.1f} · "
        f"movement {movement*100:.0f}%"
    )
    if evidence["n3_rr_conflict"] >= 0.05:
        reason += f" · RR ใกล้ N2 มากกว่า N3 {evidence['n3_rr_conflict']*100:.0f}%"
    if selected == "rem" and not evidence["rem_gate"]:
        reason += " · REM evidence gate ไม่ผ่าน"
    if evidence["movement"]["sleep_compatible"] and movement > 0:
        reason += " · การขยับบนเตียงไม่ยืนยัน Wake โดยลำพัง"
    arousal_proxy = arousal_proxy_evidence(metrics, zeep.SLEEP_MOVE_WAKE_RATIO)

    updated = dict(value)
    updated.update({
        "state": selected,
        "probabilities": probabilities,
        "evidence_probabilities": probabilities,
        "confirmed_probabilities": confirmed_probabilities,
        "confirmed_state": selected,
        "raw_probabilities": {key: round(item, 4) for key, item in raw.items()},
        "smoothed_probabilities": {
            key: round(item, 4) for key, item in path.probability_ema.items()
        },
        "instant_candidate": instant_candidate,
        "raw_candidate": candidate,
        "probability_winner": candidate,
        "probability_filter": {
            "method": "ema_after_60s_rolling_features",
            "alpha": SLEEP_PROBABILITY_EMA_ALPHA,
            "candidate_switch_margin": SLEEP_PROBABILITY_SWITCH_MARGIN,
            "candidate_source": "ema_with_gated_n3_current_evidence_override",
            "ema_role": "default_candidate_stability_and_display",
            "display_winner_margin": SLEEP_DISPLAY_WINNER_MARGIN,
            **probability_transition,
        },
        "confidence": confidence,
        "evidence": {
            "candidate": candidate,
            "probabilities": probabilities,
            "epoch_seconds": 30.0,
        },
        "confirmation": {
            "confirmed_state": selected,
            "pending_state": candidate if transition.get("held") else None,
            "candidate_epochs": transition.get("candidate_epochs", 0),
            "required_epochs": transition.get("required_epochs", SLEEP_CONFIRM_EPOCHS),
            "required_seconds": SLEEP_CONFIRMATION_SECONDS,
            "complete": bool(transition.get("confirmation_complete")),
        },
        "reason": reason,
        "progression": progression,
        "metrics": {
            **metrics,
            "rr_n2_fit": round(rr_fits["n2"], 4),
            "rr_n3_fit": round(rr_fits["n3"], 4),
            "rr_n3_conflict": evidence["n3_rr_conflict"],
            "arousal_proxy": arousal_proxy,
            "sleep_evidence": evidence,
        },
        **zeep._sleep_decision_provenance(),
        "state_changed": changed,
        "historical_reclassification": {
            "version": BACKFILL_VERSION,
            "reclassified_at": reclassified_at,
            "source": "raw_bcg_rebuilt_5s_buckets",
            "original_state": old_state,
            "original_estimator_version": old_version,
            "weights": {
                "hr_baseline": zeep.SLEEP_BASELINE_HR_WEIGHT,
                "rr_baseline": zeep.SLEEP_BASELINE_RR_WEIGHT,
            },
            "aasm_psg_equivalent": False,
        },
    })
    return updated


def count_states(values: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(value.get("state") for value in values)
    return {stage: counts.get(stage, 0) for stage in STAGES}


def audit_replayed_sequence(
    events: list[tuple[str, dict[str, Any]]],
    movement_threshold: float = 0.15,
) -> dict[str, Any]:
    """Build the mandatory read-only quality gate for a replay candidate.

    The transition matrix is the emitted state sequence, not the old-to-new
    reclassification matrix. A sleep-to-Wake transition passes its evidence
    check when the *same rolling window* contains a BCG amplitude shift,
    physiology-corroborated sustained movement, or bed exit. Brief position
    changes are sleep-compatible. Amplitude alone is never called a cortical
    arousal.
    """
    sequence = [
        (timestamp, str(value.get("state") or "").lower(), value)
        for timestamp, value in events
        if str(value.get("state") or "").lower() in STAGES
    ]
    matrix = {source: {target: 0 for target in STAGES} for source in STAGES}
    changes = {source: {target: 0 for target in STAGES} for source in STAGES}
    prohibited: list[dict[str, Any]] = []
    sleep_to_wake: list[dict[str, Any]] = []
    for previous, current in zip(sequence, sequence[1:]):
        previous_at, source, _ = previous
        current_at, target, value = current
        matrix[source][target] += 1
        if source != target:
            changes[source][target] += 1
        if (source, target) in PROHIBITED_TRANSITIONS:
            prohibited.append({
                "from": source, "to": target,
                "from_timestamp": previous_at, "to_timestamp": current_at,
            })
        if source in {"n2", "n3"} and target == "wake":
            metrics = dict(value.get("metrics") or {})
            proxy = metrics.get("arousal_proxy")
            if not isinstance(proxy, dict):
                proxy = arousal_proxy_evidence(metrics, movement_threshold)
            evidence = list(proxy.get("evidence") or [])
            sleep_to_wake.append({
                "from": source,
                "timestamp": current_at,
                "amplitude_shift_aligned": "bcg_amplitude_shift" in evidence,
                "movement_or_bed_exit_aligned": bool(
                    {"wake_compatible_motion", "bed_exit"}.intersection(evidence)
                ),
                "any_same_window_proxy": bool(proxy.get("present")),
                "evidence": evidence,
            })

    one_epoch: list[dict[str, Any]] = []
    two_epoch: list[dict[str, Any]] = []
    for index in range(len(sequence) - 2):
        first, middle, last = sequence[index:index + 3]
        if first[1] == last[1] and first[1] != middle[1]:
            one_epoch.append({
                "pattern": f"{first[1]}->{middle[1]}->{last[1]}",
                "timestamp": middle[0],
            })
    for index in range(len(sequence) - 3):
        first, middle_a, middle_b, last = sequence[index:index + 4]
        if (first[1] == last[1] and middle_a[1] == middle_b[1]
                and first[1] != middle_a[1]):
            two_epoch.append({
                "pattern": f"{first[1]}->{middle_a[1]}->{middle_b[1]}->{last[1]}",
                "timestamp": middle_a[0],
            })
    n2_rem_one = [item for item in one_epoch
                  if item["pattern"] in {"n2->rem->n2", "rem->n2->rem"}]
    n2_rem_two = [item for item in two_epoch
                  if item["pattern"] in {
                      "n2->rem->rem->n2", "rem->n2->n2->rem",
                  }]
    n3_rem_one = [item for item in one_epoch
                  if item["pattern"] in {"n3->rem->n3", "rem->n3->rem"}]
    n3_rem_two = [item for item in two_epoch
                  if item["pattern"] in {
                      "n3->rem->rem->n3", "rem->n3->n3->rem",
                  }]

    edge_counts = Counter()
    edge_examples: list[dict[str, Any]] = []
    for timestamp, _, value in sequence:
        metrics = dict(value.get("metrics") or {})
        hr_values = filter_vital_values([metrics.get("mean_hr")], HR_SANITY_RANGE_BPM)
        rr_values = filter_vital_values([metrics.get("mean_rr")], RR_SANITY_RANGE_PER_MIN)
        issues: list[str] = []
        if not hr_values:
            issues.append("invalid_or_missing_mean_hr")
        if not rr_values:
            issues.append("invalid_or_missing_mean_rr")
        for issue in issues:
            edge_counts[issue] += 1
        if issues and len(edge_examples) < 10:
            edge_examples.append({"timestamp": timestamp, "issues": issues})
        if not metrics.get("waveform_available"):
            edge_counts["waveform_unavailable"] += 1
        if metrics.get("bcg_baseline_drift_flag"):
            edge_counts["bcg_baseline_drift_flag"] += 1
        edge_counts["invalid_hr_packets"] += int(metrics.get("invalid_hr_packets") or 0)
        edge_counts["invalid_rr_packets"] += int(metrics.get("invalid_rr_packets") or 0)

    missing_wake_proxy = [item for item in sleep_to_wake
                          if not item["any_same_window_proxy"]]
    gate_failures: list[str] = []
    if not sequence or sequence[0][1] != "wake":
        gate_failures.append("first_emitted_state_must_be_wake")
    if prohibited:
        gate_failures.append("prohibited_state_transition")
    if n2_rem_one or n2_rem_two or n3_rem_one or n3_rem_two:
        gate_failures.append("rem_boundary_ping_pong")
    if missing_wake_proxy:
        gate_failures.append("sleep_to_wake_without_same_window_proxy")
    if (edge_counts["invalid_or_missing_mean_hr"]
            or edge_counts["invalid_or_missing_mean_rr"]):
        gate_failures.append("invalid_vitals_entered_state_machine")

    amplitude_missing = [item for item in sleep_to_wake
                         if not item["amplitude_shift_aligned"]]
    warnings: list[str] = []
    if amplitude_missing:
        warnings.append(
            "Some sleep-to-Wake transitions use movement/bed-exit evidence "
            "without a BCG amplitude shift; this is allowed because the BCG "
            "proxy is not an AASM cortical-arousal measurement."
        )
    if edge_counts["waveform_unavailable"]:
        warnings.append("Some rounds lack enough raw waveform; confidence remains low.")
    if edge_counts["bcg_baseline_drift_flag"]:
        warnings.append("Some detrended BCG windows carry a baseline-drift quality flag.")

    return {
        "rounds": len(sequence),
        "first_state": sequence[0][1] if sequence else None,
        "state_transition_matrix": matrix,
        "state_change_matrix": changes,
        "transition_verification": {
            "prohibited_count": len(prohibited),
            "n3_to_rem": changes["n3"]["rem"],
            "wake_to_n3": changes["wake"]["n3"],
            "examples": prohibited[:10],
        },
        "arousal_proxy_validation": {
            "sleep_to_wake_count": len(sleep_to_wake),
            "amplitude_shift_aligned": sum(
                item["amplitude_shift_aligned"] for item in sleep_to_wake
            ),
            "movement_or_bed_exit_aligned": sum(
                item["movement_or_bed_exit_aligned"] for item in sleep_to_wake
            ),
            "any_same_window_proxy": sum(
                item["any_same_window_proxy"] for item in sleep_to_wake
            ),
            "missing_proxy_count": len(missing_wake_proxy),
            "missing_examples": missing_wake_proxy[:10],
            "cortical_arousal_claim": False,
        },
        "boundary_packet_smoothness": {
            "all_one_epoch_aba": len(one_epoch),
            "n3_rem_one_epoch_ping_pong": len(n3_rem_one),
            "n3_rem_two_epoch_ping_pong": len(n3_rem_two),
            "all_two_epoch_abba": len(two_epoch),
            "n2_rem_one_epoch_ping_pong": len(n2_rem_one),
            "n2_rem_two_epoch_ping_pong": len(n2_rem_two),
            "examples": (n2_rem_one + n2_rem_two + n3_rem_one + n3_rem_two)[:10],
        },
        "edge_case_validation": {
            "invalid_or_missing_mean_hr": edge_counts["invalid_or_missing_mean_hr"],
            "invalid_or_missing_mean_rr": edge_counts["invalid_or_missing_mean_rr"],
            "waveform_unavailable": edge_counts["waveform_unavailable"],
            "bcg_baseline_drift_flag": edge_counts["bcg_baseline_drift_flag"],
            "invalid_hr_packets": edge_counts["invalid_hr_packets"],
            "invalid_rr_packets": edge_counts["invalid_rr_packets"],
            **dict(edge_counts),
            "examples": edge_examples,
            "invalid_stage_label": "held_previous_five_state_with_data_status",
        },
        "warnings": warnings,
        "apply_gate": {
            "passed": not gate_failures,
            "failures": gate_failures,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--session-id", help="Default: newest open session")
    parser.add_argument("--apply", action="store_true", help="Commit changes after backup")
    parser.add_argument(
        "--force", action="store_true",
        help="Replay every eligible round, including the current estimator version",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.apply:
        raise SystemExit(
            "Apply disabled: legacy event-driven replay cannot rebuild every "
            "30-second epoch from Raw BCG. Run audit_sleep_history_shadow.py "
            "and promote a versioned shadow run only after all gates pass."
        )
    data_dir = args.data_dir.resolve()
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.setdefault("ZEEP_GPIO_ENABLED", "0")
    # Importing the application gives this tool the exact versioned scoring
    # constants. Do not contend with the live service for the GPIO chip.
    os.environ.setdefault("GPIO_INIT_ATTEMPTS", "1")
    import app as zeep  # Imported after DATA_DIR is fixed for personal baseline parity.

    sessions_path = data_dir / "sessions.db"
    connection = sqlite3.connect(sessions_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=15000")
    if args.session_id:
        session = connection.execute(
            "SELECT * FROM sessions WHERE session_id=?", (args.session_id,)
        ).fetchone()
    else:
        session = connection.execute(
            "SELECT * FROM sessions ORDER BY (end_time IS NULL) DESC,start_time DESC LIMIT 1"
        ).fetchone()
    if session is None:
        raise SystemExit("Session not found")
    session = dict(session)

    rows = connection.execute(
        "SELECT id,timestamp,value FROM events WHERE session_id=? AND type='sleep_stage' ORDER BY timestamp,id",
        (session["session_id"],),
    ).fetchall()
    parsed: list[tuple[sqlite3.Row, dict[str, Any]]] = []
    for row in rows:
        try:
            value = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not args.force and value.get("estimator_version") == zeep.SLEEP_ESTIMATOR_VERSION:
            continue
        if str(value.get("state") or "").lower() not in STAGES:
            continue
        parsed.append((row, value))
    if not parsed:
        print(json.dumps({"status": "nothing_to_reclassify", "session_id": session["session_id"]}))
        return

    bcg_connection = sqlite3.connect(data_dir / "bcg.db", timeout=15)
    bcg_connection.row_factory = sqlite3.Row
    packet_rows = bcg_connection.execute(
        """SELECT p.timestamp,p.status_code,p.heart_rate,p.respiration_rate
           ,p.bcg_base64
           FROM bcg_packets p JOIN bcg_epochs e ON e.epoch_id=p.epoch_id
           WHERE e.session_id=? ORDER BY p.timestamp,p.id""",
        (session["session_id"],),
    ).fetchall()
    bcg_connection.close()
    # Never reinterpret legacy 5-second events as today's 10-second Sensor
    # cadence. New stable-30s events declare 30 s explicitly; old records keep
    # their own versioned/inferred interval for byte-compatible replay.
    replay_interval_s = decision_interval_seconds(parsed)
    raw_bcg = RawBcgWindow(packet_rows, replay_interval_s)

    try:
        profiles = json.loads((data_dir / "profiles.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        profiles = {}
    profile = profiles.get(session["username_key"], {})
    age = profile.get("age")
    age_group = profile.get("age_group") or zeep._age_group(age)
    baseline, gender_adjustment = zeep._gender_adjusted_baseline(age_group, session.get("gender"))
    personal_candidate, personal_meta = zeep.baselines.personalize_baseline(
        session["username_key"], baseline
    )
    if PERSONAL_BASELINE_STAGE_INFLUENCE_ENABLED:
        baseline = personal_candidate
        personal_thresholds = (
            zeep.baselines.thresholds_for(session["username_key"]) or {}
        )
    else:
        personal_thresholds = {}
        personal_meta = {
            **personal_meta,
            "direct_stage_influence": False,
            "candidate_available": personal_candidate != baseline,
        }
    cv_deep = float(personal_thresholds.get("cv_deep", zeep.SLEEP_HR_CV_DEEP))
    cv_rem = float(personal_thresholds.get("cv_rem", zeep.SLEEP_HR_CV_REM))

    path = HistoricalStagePath()
    reclassified_at = datetime.now(timezone.utc).isoformat()
    original_values = [value for _, value in parsed]
    updates: list[tuple[str, int]] = []
    new_values: list[dict[str, Any]] = []
    new_events: list[tuple[str, dict[str, Any]]] = []
    changes: Counter[tuple[str, str]] = Counter()
    mean_hr_deltas: list[float] = []
    mean_rr_deltas: list[float] = []
    reconstructed_rounds = 0
    skipped_without_raw = 0
    preserved_current_without_raw = 0
    session_start = parse_timestamp(session["start_time"])
    for event_index, (row, value) in enumerate(parsed):
        reconstructed = raw_bcg.reconstruct(
            value,
            terminal_session_boundary=event_index == len(parsed) - 1,
        )
        if reconstructed is None:
            metrics = value.get("metrics") or {}
            trusted_recent_estimate = bool(
                value.get("estimator_version") == zeep.SLEEP_ESTIMATOR_VERSION
                or (
                    str(value.get("estimator_version") or "").startswith(
                        "bcg-wellness-5state-v1."
                    )
                    and isinstance(metrics.get("sleep_evidence"), dict)
                )
            )
            if trusted_recent_estimate and value.get("state") in STAGES:
                # During a live full replay, the newest BCG packets may still
                # be in the service's 60-packet write buffer. Keep an already
                # current live decision rather than replacing it without its
                # evidence; a later replay can reconstruct it after flush.
                path.commit(value["state"], parse_timestamp(row["timestamp"]))
                new_values.append(value)
                new_events.append((row["timestamp"], value))
                changes[(str(value.get("state")), str(value.get("state")))] += 1
                skipped_without_raw += 1
                preserved_current_without_raw += 1
                continue
            # A reset can precede the first retained packet. Anchor that round
            # at Wake (or hold the already replayed stage later in a gap) and
            # mark it unproved instead of retaining a legacy REM/N3 label.
            selected = path.last if path.last in STAGES else "wake"
            changed, progression = path.commit(selected, parse_timestamp(row["timestamp"]))
            updated = {
                **value,
                "state": selected,
                "probabilities": {stage: 1.0 if stage == selected else 0.0 for stage in STAGES},
                "confidence": "low",
                "reason": "Historical replay · ไม่มี Raw BCG ในหน้าต่างนี้ · คงลำดับอย่างระมัดระวัง",
                "progression": progression,
                **zeep._sleep_decision_provenance(),
                "state_changed": changed,
                "historical_reclassification": {
                    "version": BACKFILL_VERSION,
                    "reclassified_at": reclassified_at,
                    "source": "missing_raw_bcg_guard",
                    "original_state": value.get("state"),
                    "original_estimator_version": value.get("estimator_version"),
                    "aasm_psg_equivalent": False,
                },
            }
            updates.append((json.dumps(updated, ensure_ascii=False, separators=(",", ":")), row["id"]))
            new_values.append(updated)
            new_events.append((row["timestamp"], updated))
            changes[(str(value.get("state")), selected)] += 1
            skipped_without_raw += 1
            continue
        score_value = dict(value)
        score_metrics = dict(value.get("metrics") or {})
        old_hr = score_metrics.get("mean_hr")
        old_rr = score_metrics.get("mean_rr")
        if isinstance(old_hr, (int, float)):
            mean_hr_deltas.append(abs(float(old_hr) - reconstructed["mean_hr"]))
        if isinstance(old_rr, (int, float)):
            mean_rr_deltas.append(abs(float(old_rr) - reconstructed["mean_rr"]))
        # Environment support came from the ESP/timeline window and is not in
        # bcg.db. Preserve it while replacing physiology with raw reconstruction.
        score_metrics.update(reconstructed)
        score_value["metrics"] = score_metrics
        score_value["sample_count"] = reconstructed["feature_buckets"]
        reconstructed_rounds += 1
        updated = rescore_event(
            score_value, row["timestamp"], session_start, baseline,
            float(gender_adjustment["rem_variability_weight"]), cv_deep, cv_rem,
            path, zeep, reclassified_at,
        )
        updates.append((json.dumps(updated, ensure_ascii=False, separators=(",", ":")), row["id"]))
        new_values.append(updated)
        new_events.append((row["timestamp"], updated))
        changes[(str(value.get("state")), str(updated.get("state")))] += 1

    old_counts = count_states(original_values)
    new_counts = count_states(new_values)
    sequence_audit = audit_replayed_sequence(
        new_events, movement_threshold=zeep.SLEEP_MOVE_WAKE_RATIO)
    manifest: dict[str, Any] = {
        "status": "applied" if args.apply else "dry_run",
        "version": BACKFILL_VERSION,
        "forced_full_replay": bool(args.force),
        "session_id": session["session_id"],
        "reclassified_at": reclassified_at,
        "rounds_considered": len(parsed),
        "rounds_updated": len(updates),
        "old_counts": old_counts,
        "new_counts": new_counts,
        "n3_reduction": old_counts["n3"] - new_counts["n3"],
        "changed_rounds": sum(count for (old, new), count in changes.items() if old != new),
        "raw_bcg_reconstruction": {
            "rounds": reconstructed_rounds,
            "skipped_without_raw": skipped_without_raw,
            "preserved_current_without_raw": preserved_current_without_raw,
            "packets_available": len(packet_rows),
            "mean_hr_absolute_delta_bpm": (
                round(sum(mean_hr_deltas) / len(mean_hr_deltas), 3) if mean_hr_deltas else None
            ),
            "mean_rr_absolute_delta_per_min": (
                round(sum(mean_rr_deltas) / len(mean_rr_deltas), 3) if mean_rr_deltas else None
            ),
        },
        "reclassification_matrix": {
            f"{old}->{new}": count for (old, new), count in sorted(changes.items())
        },
        # Backward-compatible alias. This is old-label -> new-label, while the
        # chronological transition matrix lives inside pre_apply_audit.
        "transition_matrix": {
            f"{old}->{new}": count for (old, new), count in sorted(changes.items())
        },
        "pre_apply_audit": sequence_audit,
        "weights": {
            "hr_baseline": zeep.SLEEP_BASELINE_HR_WEIGHT,
            "rr_baseline": zeep.SLEEP_BASELINE_RR_WEIGHT,
        },
        "age_group": age_group,
        "gender": session.get("gender"),
        "personal_baseline_source": personal_meta.get("source"),
        "backup": None,
    }

    if args.apply:
        if not sequence_audit["apply_gate"]["passed"]:
            manifest["status"] = "apply_rejected"
            connection.close()
            print(json.dumps(manifest, ensure_ascii=False, indent=2))
            raise SystemExit(2)
        backup_dir = data_dir.parent / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = backup_dir / f"sessions-pre-sleep-reclass-{stamp}.db"
        backup = sqlite3.connect(backup_path)
        try:
            connection.backup(backup)
        finally:
            backup.close()
        manifest["backup"] = str(backup_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany("UPDATE events SET value=? WHERE id=?", updates)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise SystemExit(f"Integrity check failed after update: {integrity}")
        manifest["integrity_check"] = integrity
        manifest_path = data_dir / "sleep-history-reclassification-latest.json"
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, manifest_path)

    connection.close()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
