#!/usr/bin/env python3
"""Deterministic, read-only Raw BCG replay for the ZEEP sleep estimator.

This tool never edits ``sessions.db`` or ``bcg.db``.  It rebuilds paired
10-second physiology frames, non-overlapping 30-second evidence epochs and
60/120-second confirmed states, then writes an auditable JSON manifest.  Old
Sleep State labels are used only for comparison and never as training truth.

The output is an engineering/wellness validation artefact, not AASM/PSG
ground truth and not a medical diagnosis.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from sleep_session_report import build_session_report, build_sleep_quality
from sleep_signal_features import (
    BCG_SAMPLE_RATE_HZ,
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    bed_exit_window_evidence,
    decode_bcg_samples,
    debounced_bed_status_labels,
    filter_vital_values,
    movement_window_metrics,
    summary_features,
    waveform_features,
)
from sleep_stage_scoring import (
    candidate_from_stage_evidence,
    evidence_candidate_with_abstention,
    fuse_hr_rr_fit_with_stage_probabilities,
    score_sleep_evidence,
    softmax_stage_evidence,
    smooth_stage_probabilities,
)
from sleep_history_policy import (
    promotion_ready,
    quality_tier,
    replay_integrity_blockers,
    replay_review_warnings,
    split_issue_codes,
)
from sleep_stage_annotations import apply_annotations, load_annotations
from sleep_system_policy import (
    AGE_SLEEP_BASELINES,
    PERSONAL_BASELINE_LEARNING_START_LOCAL_DATE,
    PERSONAL_BASELINE_LEARNING_START_TIMEZONE,
    SLEEP_ALLOWED_TRANSITIONS,
    SLEEP_CONFIRM_EPOCHS,
    SLEEP_CONTEXT_RESET_GAP_SECONDS,
    SLEEP_DEFAULT_ACOUSTIC_DISTURBANCE_DBA,
    SLEEP_DEFAULT_ACOUSTIC_MIN_COVERAGE,
    SLEEP_DEFAULT_ACOUSTIC_WAKE_SUPPORT_MAX,
    SLEEP_DEFAULT_BASELINE_HR_WEIGHT,
    SLEEP_DEFAULT_BASELINE_RR_WEIGHT,
    SLEEP_DEFAULT_HR_CV_DEEP,
    SLEEP_DEFAULT_HR_CV_REM,
    SLEEP_DEFAULT_MOVE_DEEP_RATIO,
    SLEEP_DEFAULT_MOVE_WAKE_RATIO,
    SLEEP_DEFAULT_N2_RR_CONFLICT_SUPPORT,
    SLEEP_DEFAULT_N3_RR_CONFLICT_PENALTY,
    SLEEP_BUCKET_MIN_BCG_PACKETS,
    SLEEP_CONFIRMATION_SECONDS,
    SLEEP_EVIDENCE_EPOCH_SECONDS,
    SLEEP_EVIDENCE_MIN_MARGIN,
    SLEEP_EVIDENCE_MIN_WINNER,
    SLEEP_ESTIMATOR_VERSION,
    SLEEP_EVIDENCE_VERSION,
    SLEEP_HISTORY_BACKFILL_VERSION,
    SLEEP_HR_RR_FIT_FUSION_AGREEMENT_WEIGHT,
    SLEEP_HR_RR_FIT_FUSION_WEIGHT,
    SLEEP_MIN_PAIRED_VITAL_COVERAGE,
    SLEEP_MIN_WAVEFORM_COVERAGE,
    SLEEP_N3_GATED_MIN_MARGIN,
    SLEEP_N3_GATED_MIN_WINNER,
    SLEEP_ONSET_INITIAL_WAKE_SUPPORT,
    SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN,
    SLEEP_ONSET_MAX_MOVEMENT_RATIO,
    SLEEP_ONSET_MAX_RR_RISE_PER_MIN,
    SLEEP_ONSET_MIN_DOWNWARD_TRANSITION,
    SLEEP_ONSET_MIN_RELATIVE_SLEEP_SUPPORT,
    SLEEP_ONSET_MIN_OBSERVATION_SECONDS,
    SLEEP_PROBABILITY_EMA_ALPHA,
    SLEEP_PROBABILITY_SWITCH_MARGIN,
    SLEEP_SCORE_SOFTMAX_TEMPERATURE,
    SLEEP_STAGE_CONFIRM_TICKS,
    SLEEP_STAGE_CONFIRMATION_SECONDS,
    SLEEP_STAGE_MIN_DWELL_SECONDS,
    ZEEP_SLEEP_BASELINE_VERSION,
    ZEEP_ON_BED_STATUS_CODES,
    ZEEP_SLEEP_STATES,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
    age_group,
    continuity_hold_contract,
    gender_adjusted_baseline,
    rest_mode_group,
)
from zeep_pod.sessions.cadence import materialise_report_sample_grid
from zeep_pod.sessions.sleep_decision_projection import (
    apply_sleep_decisions_to_samples,
)

def private_write_bytes(path: Path, payload: bytes) -> None:
    """Write health-data artifacts owner-only, including on overwrite."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


MAINTENANCE_TOOL_NAME = "audit_sleep_history_shadow.py"
REPLAY_SOURCE_FILES = (
    "audit_sleep_history_shadow.py",
    "promote_sleep_history.py",
    "sleep_history_policy.py",
    "rescore_session_reports.py",
    "app.py",
    "personal.py",
    "calibration.json",
    "sleep_signal_features.py",
    "sleep_stage_scoring.py",
    "sleep_system_policy.py",
    "sleep_session_report.py",
)
STAGES = tuple(ZEEP_SLEEP_STATES)
SLEEP_STAGES = {"n1", "n2", "n3", "rem"}
LOCAL_TIMEZONE = ZoneInfo(PERSONAL_BASELINE_LEARNING_START_TIMEZONE)


def confidence(evidence: dict[str, Any]) -> str:
    value = float((evidence.get("quality") or {}).get("winner_value") or 0.0)
    return "high" if value >= 0.72 else "medium" if value >= 0.48 else "low"


def report_state_rows_with_annotations(
    state_rows: Iterable[dict[str, Any]],
    evidence_rows: Iterable[dict[str, Any]],
    annotations: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Overlay reviewed annotations for reports without changing model rows.

    Shadow replay remains the model output promoted as versioned derived
    events. A separately stored annotation may alter the user-facing report
    and score, so the reviewed artifact must calculate that same overlay before
    enforcing report parity during promotion.
    """
    evidence_by_time = {
        round(float(row["t"]), 3): row for row in evidence_rows
    }
    applied = 0
    report_rows: list[dict[str, Any]] = []
    for state_row in state_rows:
        when = float(state_row["t"])
        evidence = evidence_by_time.get(round(when, 3), {})
        model_value = {
            "state": state_row.get("state"),
            "probabilities": evidence.get("probabilities") or {},
            "confidence": confidence(evidence),
            "metrics": state_row.get("metrics") or {},
        }
        timestamp = datetime.fromtimestamp(
            when, ZoneInfo("UTC")
        ).isoformat()
        report_value, annotation = apply_annotations(
            model_value,
            timestamp,
            annotations,
            sample_interval_s=SLEEP_EVIDENCE_EPOCH_SECONDS,
        )
        if annotation is not None:
            applied += 1
        report_rows.append({
            **state_row,
            "state": report_value["state"],
            "model_state": state_row.get("state"),
            "probabilities": report_value.get("probabilities") or {},
            "confidence": report_value.get("confidence"),
            "stage_annotation": report_value.get("stage_annotation"),
        })
    return report_rows, applied


def load_profile_index(path: Optional[Path]) -> dict[str, dict[str, Any]]:
    """Index profile records by stable email/account key and legacy aliases."""
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("profiles file must be a JSON object")
    index: dict[str, dict[str, Any]] = {}
    for stored_key, raw_profile in payload.items():
        if not isinstance(raw_profile, dict):
            continue
        profile = dict(raw_profile)
        aliases = {
            stored_key,
            profile.get("account_key"),
            profile.get("email"),
            profile.get("zeep_email"),
            profile.get("username_key"),
            profile.get("username"),
            *(profile.get("legacy_account_keys") or []),
        }
        for alias in aliases:
            key = str(alias or "").strip().casefold()
            if key:
                index[key] = profile
    return index


def sound_by_bucket(
    connection: sqlite3.Connection, session_id: str, *, start: float, end: float,
) -> dict[int, float]:
    """Read canonical 10-second SPH0645 estimates for replay corroboration."""
    rows = connection.execute(
        "SELECT timestamp,sound FROM timeline WHERE session_id=? ORDER BY timestamp",
        (session_id,),
    ).fetchall()
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        position = epoch(row["timestamp"])
        value = row["sound"]
        if start <= position <= end and isinstance(value, (int, float)):
            number = float(value)
            if math.isfinite(number):
                grouped[int((position - start) // 10.0)].append(number)
    return {
        index: float(statistics.median(values))
        for index, values in grouped.items() if values
    }


def epoch(value: str) -> float:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.timestamp()


def median(values: Iterable[float]) -> Optional[float]:
    cleaned = [float(value) for value in values if math.isfinite(float(value))]
    return statistics.median(cleaned) if cleaned else None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def interval_fit(value: float, pair: tuple[float, float]) -> float:
    lo, hi = sorted((float(pair[0]), float(pair[1])))
    midpoint = (lo + hi) / 2.0
    half_span = max((hi - lo) / 2.0, 0.5)
    outside = max(lo - value, 0.0, value - hi)
    midpoint_distance = abs(value - midpoint)
    return math.exp(-1.2 * (outside / half_span + 0.35 * midpoint_distance / half_span) ** 2)


def mode_and_score(value: dict[str, Any]) -> tuple[str, str, Optional[int]]:
    report = value.get("session_report") or {}
    quality = report.get("quality") or (value.get("night_summary") or {}).get("sleep_quality") or {}
    mode = report.get("rest_mode") or quality.get("rest_mode") or {}
    resolved = str(mode.get("resolved") or mode.get("requested") or "auto")
    group = str(mode.get("group") or rest_mode_group(resolved) or "unresolved")
    score = quality.get("score")
    try:
        score = int(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    return resolved, group, score


def resolve_replay_mode_context(
    session: sqlite3.Row | dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Resolve scoring intent without guessing from elapsed time.

    The canonical Session columns are authoritative when populated. Legacy
    Final Summary values are used only when those columns were never recorded,
    and the fallback is exposed as provenance in the replay artifact. An
    invalid explicit canonical value stays unresolved instead of silently
    borrowing a different legacy value.
    """
    fields = set(session.keys())
    legacy_resolved, legacy_group, old_score = mode_and_score(summary)
    canonical_mode = (
        session["rest_mode"] if "rest_mode" in fields else None
    )
    canonical_text = str(canonical_mode or "").strip().lower()
    canonical_is_missing = canonical_text in {
        "", "auto", "unknown_legacy", "unresolved",
    }

    if not canonical_is_missing:
        resolved_mode = canonical_text
        group = rest_mode_group(canonical_text) or "unresolved"
        mode_source = "sessions.rest_mode"
    else:
        resolved_mode = legacy_resolved
        group = legacy_group
        mode_source = (
            "legacy_final_summary"
            if legacy_group in {"sleep", "nap_recovery"}
            else "unresolved"
        )

    report = summary.get("session_report") or {}
    quality = report.get("quality") or {}
    duration_target = quality.get("duration_target") or {}
    legacy_target = summary.get("target_duration_s")
    if legacy_target is None:
        legacy_target = duration_target.get("seconds")

    canonical_target_present = (
        "target_duration_s" in fields
        and session["target_duration_s"] is not None
    )
    if canonical_target_present:
        target_duration_s = session["target_duration_s"]
        target_source = "sessions.target_duration_s"
    else:
        target_duration_s = legacy_target
        target_source = (
            "legacy_final_summary_duration_target"
            if target_duration_s is not None
            else "unavailable"
        )

    return {
        "resolved": resolved_mode,
        "group": group,
        "scoring_mode": (
            group if group in {"sleep", "nap_recovery"} else "auto"
        ),
        "old_score": old_score,
        "mode_source": mode_source,
        "target_duration_s": target_duration_s,
        "target_duration_source": target_source,
    }


def percentile(values: Iterable[float], quantile: float) -> Optional[float]:
    cleaned = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not cleaned:
        return None
    position = (len(cleaned) - 1) * min(1.0, max(0.0, quantile))
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return cleaned[lower]
    fraction = position - lower
    return cleaned[lower] * (1.0 - fraction) + cleaned[upper] * fraction


def environment_summary(
    connection: sqlite3.Connection,
    session_id: str,
    *,
    start: float,
    sleep_onset: Optional[float],
) -> dict[str, Any]:
    """Describe exposure without using it to manufacture a Sleep State."""
    rows = connection.execute(
        "SELECT timestamp,temperature,humidity,co2,lux,sound,pm2_5,voc_index "
        "FROM timeline WHERE session_id=? ORDER BY timestamp",
        (session_id,),
    ).fetchall()
    fields = {
        "temperature_c": "temperature",
        "humidity_rh": "humidity",
        "co2_ppm": "co2",
        "lux": "lux",
        "sound_dba_est": "sound",
        "pm2_5_ug_m3": "pm2_5",
        "voc_index": "voc_index",
    }

    def summarise(selected: list[sqlite3.Row]) -> dict[str, Any]:
        result: dict[str, Any] = {"rows": len(selected)}
        for output_key, column in fields.items():
            values = [
                float(row[column]) for row in selected
                if isinstance(row[column], (int, float)) and math.isfinite(float(row[column]))
            ]
            result[output_key] = {
                "median": round(float(statistics.median(values)), 2) if values else None,
                "p10": round(float(percentile(values, 0.10)), 2) if values else None,
                "p90": round(float(percentile(values, 0.90)), 2) if values else None,
                "coverage_percent": round(len(values) * 100.0 / len(selected), 1) if selected else 0.0,
            }
        return result

    pre_sleep_end = sleep_onset if sleep_onset is not None else start + 30 * 60.0
    pre_sleep = [row for row in rows if epoch(row["timestamp"]) <= pre_sleep_end]
    return {
        "whole_session": summarise(rows),
        "before_first_sleep_or_first_30m": summarise(pre_sleep),
        "direct_stage_influence": False,
        "role": "disruption_explanation_and_personal_context_only",
    }


def timeline_sensor_rows(
    connection: sqlite3.Connection,
    session_id: str,
    *,
    start: float,
    end: float,
    interval_s: float = SLEEP_EVIDENCE_EPOCH_SECONDS,
) -> list[dict[str, Any]]:
    """Resample canonical Timeline values onto the report's 30-second clock."""
    rows = connection.execute(
        "SELECT timestamp,temperature,humidity,co2,lux,sound,heart_rate,"
        "respiration_rate,bed_status,pm2_5,voc_index FROM timeline "
        "WHERE session_id=? ORDER BY timestamp",
        (session_id,),
    ).fetchall()
    canonical_bed_labels = debounced_bed_status_labels(
        [row["bed_status"] for row in rows]
    )
    grouped: dict[int, list[tuple[sqlite3.Row, str]]] = defaultdict(list)
    for row, canonical_bed in zip(rows, canonical_bed_labels):
        position = epoch(row["timestamp"])
        if start <= position <= end:
            grouped[int((position - start) // interval_s)].append(
                (row, canonical_bed)
            )

    numeric = {
        "temp": "temperature", "hum": "humidity", "co2": "co2",
        "lux": "lux", "dba": "sound", "hr": "heart_rate",
        "rr": "respiration_rate", "pm2_5": "pm2_5", "voc": "voc_index",
    }
    output = []
    for index in sorted(grouped):
        selected = grouped[index]
        paired_rows = sum(
            bool(
                filter_vital_values(
                    [row["heart_rate"]], HR_SANITY_RANGE_BPM
                )
                and filter_vital_values(
                    [row["respiration_rate"]],
                    RR_SANITY_RANGE_PER_MIN,
                )
            )
            for row, _ in selected
        )
        item: dict[str, Any] = {
            "t": start + (index + 1) * interval_s,
            "_bucket_index": index,
            "_source_rows": len(selected),
            "_paired_hr_rr_rows": paired_rows,
            "bcg_analysis_valid": paired_rows > 0,
            "bed": next(
                (bed for _, bed in reversed(selected) if bed),
                None,
            ),
        }
        for target, source in numeric.items():
            values = [
                float(row[source]) for row, _ in selected
                if isinstance(row[source], (int, float))
                and math.isfinite(float(row[source]))
            ]
            item[target] = float(statistics.median(values)) if values else None
        output.append(item)
    return output


def project_replay_decisions_to_report_rows(
    sensor_rows: list[dict[str, Any]],
    state_rows: Iterable[dict[str, Any]],
    status_rows: Iterable[dict[str, Any]],
    *,
    session_start: float,
    session_end: float,
    interval_s: float = SLEEP_EVIDENCE_EPOCH_SECONDS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build the same complete decision stream used by live finalisation.

    Shadow replay used to join State and OFF BED by integer bucket number.
    That duplicated production logic, lost service gaps and rounded an exit
    occurring between two 30-second boundaries. The shared grid/projector now
    owns all three paths: live final report, History and read-only replay.
    """
    states = list(state_rows)
    statuses = list(status_rows)
    boundaries = {
        float(value)
        for row in [*states, *statuses]
        for value in (
            row.get("attribution_start"),
            row.get("attribution_end", row.get("t")),
        )
        if isinstance(value, (int, float))
        and math.isfinite(float(value))
    }
    grid, summary = materialise_report_sample_grid(
        sensor_rows,
        start_at=session_start,
        end_at=session_end,
        split_boundaries=boundaries,
        fallback_interval_s=interval_s,
    )

    def event(row: dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        for key in ("attribution_start", "attribution_end"):
            raw = value.get(key)
            if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
                value[key] = datetime.fromtimestamp(
                    float(raw), ZoneInfo("UTC")
                ).isoformat()
        timestamp = datetime.fromtimestamp(
            float(row.get("t") or session_start), ZoneInfo("UTC")
        ).isoformat()
        value.setdefault("estimator_version", SLEEP_ESTIMATOR_VERSION)
        value.setdefault("evidence_version", SLEEP_EVIDENCE_VERSION)
        value.setdefault("baseline_version", ZEEP_SLEEP_BASELINE_VERSION)
        value.setdefault(
            "transition_policy_version",
            ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        )
        return {"timestamp": timestamp, "value": value}

    apply_sleep_decisions_to_samples(
        grid,
        stage_events=[event(row) for row in states],
        status_events=[event(row) for row in statuses],
        fallback_interval_s=interval_s,
        heart_rate_range=HR_SANITY_RANGE_BPM,
        respiration_rate_range=RR_SANITY_RANGE_PER_MIN,
    )
    return grid, summary


def raw_packet_quality(packets: list[sqlite3.Row], start: float, end: float) -> dict[str, Any]:
    """Measure acquisition and paired-vital completeness without using labels."""
    paired = 0
    times = []
    for packet in packets:
        packet_t = epoch(packet["timestamp"])
        if start <= packet_t <= end:
            times.append(packet_t)
        hrs = filter_vital_values([packet["heart_rate"]], HR_SANITY_RANGE_BPM)
        rrs = filter_vital_values([packet["respiration_rate"]], RR_SANITY_RANGE_PER_MIN)
        paired += int(bool(hrs and rrs))
    gaps = [right - left for left, right in zip(times, times[1:])]
    duration = max(1.0, end - start)
    return {
        "packet_count": len(packets),
        "acquisition_coverage": min(1.0, len(packets) / duration),
        "paired_vital_coverage": paired / len(packets) if packets else 0.0,
        "maximum_packet_gap_s": max(gaps) if gaps else duration,
    }


class ShadowPath:
    """Small replay-only equivalent of the live no-bridge semi-Markov path."""

    def __init__(self) -> None:
        self.last: Optional[str] = None
        self.stage_since: Optional[float] = None
        self.candidate: Optional[str] = None
        self.candidate_ticks = 0
        self.continuity_hold_ticks = 0
        self.cycle_has_n1 = False
        self.sleep_onset_at: Optional[float] = None
        self.ema: Optional[dict[str, float]] = None
        self.segment = 0
        self.off_bed_latched = False

    def _start_new_segment(self) -> None:
        """Discard only unfinished evidence when continuity is interrupted."""
        self.segment += 1
        self.candidate = None
        self.candidate_ticks = 0
        self.continuity_hold_ticks = 0
        self.ema = None

    def observe_signal_gap(self) -> None:
        """Mirror Live handling of a telemetry gap within the same Session.

        A missing observation is not evidence that the occupant woke.  The
        confirmed stage, first sleep onset and frozen pre-onset references
        therefore survive while an incomplete challenger and its EMA do not.
        """
        self._start_new_segment()

    def interrupt_confirmation(self) -> None:
        """Discard non-consecutive challenger evidence for one invalid epoch.

        Live classification clears the pending candidate and probability EMA
        whenever a canonical 30-second epoch lacks valid Bed + HR + RR + BCG.
        A short invalid epoch is not necessarily a 60-second signal gap, so it
        must break confirmation without starting a new replay segment or
        forgetting the last confirmed State.
        """
        self.candidate = None
        self.candidate_ticks = 0
        self.continuity_hold_ticks = 0
        self.ema = None

    def observe_confirmed_off_bed(self, now: float) -> None:
        """Mirror Live Bed Exit handling without forgetting first onset.

        The operational OFF BED interval closes the current sleep cycle and a
        returning occupant must pass through N1 again.  Preserving the first
        onset prevents sleeping HR/RR after return from contaminating the
        within-Session awake reference.
        """
        self._start_new_segment()
        self.off_bed_latched = True
        self.cycle_has_n1 = False
        if self.last != "wake":
            self.last = "wake"
            self.stage_since = now

    def observe_confirmed_return(self) -> None:
        """Release OFF BED only after a fresh, valid on-bed bucket."""
        self.off_bed_latched = False

    def allowed(self, candidate: str, strong_wake: bool) -> bool:
        if self.last is None:
            return candidate == "wake"
        if candidate == "wake" and strong_wake:
            return True
        if self.last == "wake":
            return candidate in {"wake", "n1"}
        if candidate in {"n2", "n3", "rem"} and not self.cycle_has_n1:
            return False
        return candidate in SLEEP_ALLOWED_TRANSITIONS.get(self.last, frozenset())

    def step(
        self,
        candidate: Optional[str],
        now: float,
        strong_wake: bool,
    ) -> tuple[str, dict[str, Any]]:
        if self.last is None:
            self.last = "wake"
            self.stage_since = now
            self.candidate = None
            self.candidate_ticks = 0
            self.continuity_hold_ticks = 0
            contract = continuity_hold_contract(
                None,
                candidate=candidate,
                decision="initial_awake_anchor",
            )
            contract.update({
                "candidate_epochs": 1,
                "required_epochs": 1,
                "confirmation_seconds": 0.0,
                "confirmation_complete": True,
            })
            return "wake", contract
        if candidate is None or not self.allowed(candidate, strong_wake):
            self.candidate = None
            self.candidate_ticks = 0
            self.continuity_hold_ticks += 1
            contract = continuity_hold_contract(
                self.last,
                candidate=candidate,
                decision=(
                    "ambiguous_evidence_hold"
                    if candidate is None else "blocked_transition_hold"
                ),
                hold_epochs=self.continuity_hold_ticks,
            )
            required = int(
                SLEEP_STAGE_CONFIRM_TICKS.get(
                    candidate, SLEEP_CONFIRM_EPOCHS
                )
            ) if candidate in STAGES else 0
            contract.update({
                "candidate_epochs": 0,
                "required_epochs": required,
                "confirmation_seconds": (
                    SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                        candidate, SLEEP_CONFIRMATION_SECONDS
                    )
                    if candidate in STAGES else SLEEP_CONFIRMATION_SECONDS
                ),
                "confirmation_complete": False,
            })
            return contract["confirmed_state"], contract
        if candidate == self.last:
            self.candidate = None
            self.candidate_ticks = 0
            self.continuity_hold_ticks = 0
            return self.last, {
                "decision": "hold_confirmed",
                "decision_kind": "confirmed_state",
                "confirmed_state": self.last,
                "held_previous_state": False,
                "provisional": False,
                "challenger_counted_as_new_state": False,
                "score_eligible": True,
                "excluded_from_score": False,
                "excluded_from_personal_baseline": False,
                "candidate_epochs": SLEEP_STAGE_CONFIRM_TICKS.get(
                    self.last, SLEEP_CONFIRM_EPOCHS
                ),
                "required_epochs": SLEEP_STAGE_CONFIRM_TICKS.get(
                    self.last, SLEEP_CONFIRM_EPOCHS
                ),
                "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                    self.last, SLEEP_CONFIRMATION_SECONDS
                ),
                "confirmation_complete": True,
            }
        if self.candidate == candidate:
            self.candidate_ticks += 1
        else:
            self.candidate = candidate
            self.candidate_ticks = 1
        required = int(SLEEP_STAGE_CONFIRM_TICKS.get(candidate, SLEEP_CONFIRM_EPOCHS))
        dwell = now - self.stage_since if self.stage_since is not None else math.inf
        minimum_dwell = SLEEP_STAGE_MIN_DWELL_SECONDS.get(self.last or "wake", 0.0)
        if self.candidate_ticks < required or dwell < minimum_dwell:
            # Live persistence holds the preceding confirmed stage while an
            # allowed challenger is accumulating confirmation.  Returning the
            # old state here keeps duration, coverage and score parity.
            self.continuity_hold_ticks += 1
            contract = continuity_hold_contract(
                self.last,
                candidate=candidate,
                decision="confirming",
                hold_epochs=self.continuity_hold_ticks,
            )
            return self.last, {
                **contract,
                "decision": "confirming",
                "ticks": self.candidate_ticks,
                "required": required,
                "candidate_epochs": self.candidate_ticks,
                "required_epochs": required,
                "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                    candidate, SLEEP_CONFIRMATION_SECONDS
                ),
                "confirmation_complete": False,
                "confirmed_state": self.last,
            }
        self.last = candidate
        self.stage_since = now
        self.candidate = None
        self.candidate_ticks = 0
        self.continuity_hold_ticks = 0
        if candidate == "wake":
            self.cycle_has_n1 = False
            # Preserve first onset across Wake, Bed Exit and telemetry gaps.
            # A returning occupant still needs N1 before a deeper stage, while
            # the frozen pre-onset reference remains owned by this Session.
        elif candidate == "n1":
            self.cycle_has_n1 = True
            if self.sleep_onset_at is None:
                self.sleep_onset_at = now
        return candidate, {
            "decision": "confirmed",
            "decision_kind": "confirmed_state",
            "strong_wake_override": bool(
                candidate == "wake" and strong_wake
            ),
            "required": required,
            "candidate_epochs": required,
            "required_epochs": required,
            "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                candidate, SLEEP_CONFIRMATION_SECONDS
            ),
            "confirmation_complete": True,
            "confirmed_state": candidate,
            "held_previous_state": False,
            "provisional": False,
            "challenger_counted_as_new_state": True,
            "score_eligible": True,
            "excluded_from_score": False,
            "excluded_from_personal_baseline": False,
        }


def raw_packets(connection: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        "SELECT p.timestamp,p.status_code,p.heart_rate,p.respiration_rate,p.bcg_base64 "
        "FROM bcg_packets p JOIN bcg_epochs e ON e.epoch_id=p.epoch_id "
        "WHERE e.session_id=? ORDER BY p.timestamp,p.packet_index",
        (session_id,),
    ).fetchall()


def make_buckets(
    packets: list[sqlite3.Row], start: float, end: float,
    *, timeline_sound: Optional[dict[int, float]] = None,
) -> list[dict[str, Any]]:
    # Only complete 10-second acquisition buckets may enter a canonical
    # 30-second Evidence Epoch.  ``ceil`` used to create a synthetic endpoint
    # beyond ``end`` (for example 85 s -> a bucket ending at 90 s), which could
    # in turn persist a decision outside the Session.  The incomplete tail is
    # accounted explicitly after replay and is never padded into evidence.
    count = max(0, int(math.floor((end - start) / 10.0 + 1e-9)))
    buckets = [{"t": start + (index + 1) * 10.0, "packets": []} for index in range(count)]
    for packet in packets:
        packet_t = epoch(packet["timestamp"])
        index = int((packet_t - start) // 10.0)
        if 0 <= index < count:
            buckets[index]["packets"].append(packet)
    result = []
    for bucket_index, bucket in enumerate(buckets):
        pairs = []
        statuses = []
        samples = []
        for packet in bucket["packets"]:
            hrs = filter_vital_values([packet["heart_rate"]], HR_SANITY_RANGE_BPM)
            rrs = filter_vital_values([packet["respiration_rate"]], RR_SANITY_RANGE_PER_MIN)
            if hrs and rrs:
                pairs.append((hrs[0], rrs[0]))
            statuses.append(int(packet["status_code"]))
            samples.extend(decode_bcg_samples(packet["bcg_base64"]))
        exit_ratio = statuses.count(1) / len(statuses) if statuses else 0.0
        status = 1 if exit_ratio >= 0.8 else (2 if 2 in statuses else (statuses[-1] if statuses else None))
        paired_coverage = len(pairs) / len(bucket["packets"]) if bucket["packets"] else 0.0
        waveform_coverage = min(
            1.0,
            len(samples) / max(1.0, BCG_SAMPLE_RATE_HZ * 10.0),
        )
        valid = bool(
            len(bucket["packets"]) >= SLEEP_BUCKET_MIN_BCG_PACKETS
            and paired_coverage >= SLEEP_MIN_PAIRED_VITAL_COVERAGE
            and waveform_coverage >= SLEEP_MIN_WAVEFORM_COVERAGE
        )
        result.append({
            "t": bucket["t"],
            "hr": sum(item[0] for item in pairs) / len(pairs) if pairs else None,
            "rr": sum(item[1] for item in pairs) / len(pairs) if pairs else None,
            "valid": valid,
            "status": status,
            "samples": samples,
            "packet_count": len(bucket["packets"]),
            "paired_packets": len(pairs),
            "paired_vital_coverage": round(paired_coverage, 4),
            "waveform_sample_coverage": round(waveform_coverage, 4),
            "sound_leq_dba": (timeline_sound or {}).get(bucket_index),
            # Timeline stores the canonical 10-second estimate, not every
            # microphone sub-sample, so within-bucket 20 dB span detection is
            # unavailable in replay and is never fabricated.
            "sound_large_step": False,
        })
    return result


def operational_status_row(
    bucket: dict[str, Any],
    *,
    state: str,
    data_status: str,
    reason: str,
    segment: int,
    sample_interval_s: float = SLEEP_EVIDENCE_EPOCH_SECONDS,
) -> dict[str, Any]:
    """Describe operational time without inventing a Sleep Stage."""
    labels = {
        "wait": "WAIT · กำลังยืนยันสถานะ",
        "no_data": "NO DATA · หลักฐานไม่ครบ",
        "off_bed": (
            "OFF BED · ไม่มีผู้ใช้งาน"
            "บนเตียง"
        ),
    }
    timestamp = float(bucket["t"])
    interval_s = max(0.0, float(sample_interval_s))
    return {
        "t": bucket["t"],
        "attribution_start": timestamp - interval_s,
        "attribution_end": timestamp,
        "sample_interval_s": interval_s,
        "state": state,
        "label": labels[state],
        "data_status": data_status,
        "reason": reason,
        "segment": segment,
        "confidence": "unavailable",
        "sleep_stage": False,
        "excluded_from_stage_statistics": True,
        "excluded_from_score": True,
        "excluded_from_personal_baseline": True,
        "coverage": {
            "bcg_packets": int(bucket.get("packet_count") or 0),
            "paired_hr_rr_packets": int(bucket.get("paired_packets") or 0),
            "paired_hr_rr_ratio": float(
                bucket.get("paired_vital_coverage") or 0.0
            ),
            "bcg_waveform_ratio": float(
                bucket.get("waveform_sample_coverage") or 0.0
            ),
        },
    }


def _duration_weighted_state_counts(
    rows: Iterable[dict[str, Any]],
) -> Counter[str]:
    """Return 30-second Epoch equivalents, including a partial final Epoch."""
    counts: Counter[str] = Counter()
    for row in rows:
        state = row.get("state")
        if state in STAGES:
            duration_s = max(0.0, float(
                row.get("sample_interval_s") or SLEEP_EVIDENCE_EPOCH_SECONDS
            ))
            counts[str(state)] += duration_s / SLEEP_EVIDENCE_EPOCH_SECONDS
    return counts


def _duration_weighted_waso_seconds(
    rows: Iterable[dict[str, Any]],
) -> float:
    """Sum Wake after first sleep using each row's actual owned duration."""
    sleep_started = False
    waso_seconds = 0.0
    for row in rows:
        state = row.get("state")
        if state in SLEEP_STAGES:
            sleep_started = True
        elif sleep_started and state == "wake":
            waso_seconds += max(0.0, float(
                row.get("sample_interval_s")
                or SLEEP_EVIDENCE_EPOCH_SECONDS
            ))
    return waso_seconds


def replay_session(
    packets: list[sqlite3.Row], start: float, end: float,
    *, baseline: dict[str, dict[str, tuple[float, float]]],
    rem_variability_weight: float,
    timeline_sound: Optional[dict[int, float]] = None,
) -> dict[str, Any]:
    buckets = make_buckets(
        packets, start, end, timeline_sound=timeline_sound,
    )
    path = ShadowPath()
    context: deque[dict[str, Any]] = deque(maxlen=27)
    awake_pairs: list[tuple[float, float]] = []
    evidence_rows = []
    state_rows = []
    status_rows = []
    operational = Counter()
    last_valid_t: Optional[float] = None
    offbed_run = 0
    resume_attribution_start: Optional[float] = None

    def upsert_off_bed_epoch(bucket: dict[str, Any]) -> None:
        """Persist confirmed OFF BED on the canonical 30-second grid.

        Three consecutive 10-second exit buckets can complete between grid
        boundaries.  Backfill the immediately preceding epoch so a Session
        ending before the next boundary cannot lose the confirmed exit.
        """
        elapsed = max(0.0, float(bucket["t"]) - start)
        epoch_number = max(
            1,
            int(math.floor(elapsed / SLEEP_EVIDENCE_EPOCH_SECONDS)),
        )
        epoch_end = start + epoch_number * SLEEP_EVIDENCE_EPOCH_SECONDS
        if epoch_end > float(bucket["t"]):
            epoch_end -= SLEEP_EVIDENCE_EPOCH_SECONDS
        epoch_end = max(
            start + SLEEP_EVIDENCE_EPOCH_SECONDS,
            epoch_end,
        )
        epoch_bucket = {**bucket, "t": epoch_end}
        state_rows[:] = [
            row for row in state_rows
            if not math.isclose(float(row["t"]), epoch_end, abs_tol=0.01)
        ]
        status_rows[:] = [
            row for row in status_rows
            if not math.isclose(float(row["t"]), epoch_end, abs_tol=0.01)
        ]
        status_rows.append(operational_status_row(
            epoch_bucket,
            state="off_bed",
            data_status="confirmed_off_bed",
            reason=(
                "Bed Status ยืนยันว่าไม่มีผู้ใช้งานบนเตียง "
                "จึงไม่สร้าง Sleep State"
            ),
            segment=path.segment,
        ))

    def append_continuity_hold(
        bucket: dict[str, Any],
        *,
        decision: str,
        candidate: Optional[str] = None,
        metrics: Optional[dict[str, Any]] = None,
        reason: Optional[str] = None,
        sample_interval_s: float = SLEEP_EVIDENCE_EPOCH_SECONDS,
    ) -> None:
        """Attribute any occupied Epoch to prior State or initial Wake."""
        nonlocal resume_attribution_start
        attribution_interval_s = sample_interval_s
        if resume_attribution_start is not None:
            attribution_interval_s = min(
                sample_interval_s,
                max(0.0, float(bucket["t"]) - resume_attribution_start),
            )
            if attribution_interval_s <= 1e-6:
                return
            resume_attribution_start = None
        confirmed, transition = path.step(None, float(bucket["t"]), False)
        if candidate in STAGES and candidate != confirmed:
            transition["pending_state"] = candidate
        transition["decision"] = (
            decision if transition.get("held_previous_state") else
            "initial_awake_anchor"
        )
        if reason:
            transition["evidence_gap_reason"] = reason
        state_rows.append({
            "t": bucket["t"],
            "attribution_start": (
                float(bucket["t"]) - attribution_interval_s
            ),
            "attribution_end": float(bucket["t"]),
            "sample_interval_s": attribution_interval_s,
            "state": confirmed,
            "segment": path.segment,
            "metrics": metrics or {
                "mean_hr": bucket.get("hr"),
                "mean_rr": bucket.get("rr"),
                "bed_status": (
                    "Moving" if bucket.get("status") == 2 else "On bed"
                ),
                "evidence_gap_reason": reason,
            },
            "decision_kind": transition["decision_kind"],
            "decision": transition["decision"],
            "held_previous_state": bool(
                transition.get("held_previous_state")
            ),
            "provisional": transition["provisional"],
            "pending_state": transition.get("pending_state"),
            "score_attribution_state": confirmed,
            "challenger_counted_as_new_state": False,
            "score_eligible": bool(transition.get("score_eligible")),
            "excluded_from_score": bool(
                transition.get("excluded_from_score")
            ),
            "excluded_from_personal_baseline": True,
            "confirmation": transition,
        })

    for index, bucket in enumerate(buckets):
        epoch_boundary = (index + 1) % 3 == 0
        context.append(bucket)
        # Mirror the live pre-onset reference: continue learning while Wake is
        # the only confirmed state and use a robust upper quartile. This avoids
        # a low/sparse startup packet becoming the reference for the full night.
        if (
            bucket["valid"]
            and bucket.get("status") in ZEEP_ON_BED_STATUS_CODES
            and path.sleep_onset_at is None
        ):
            awake_pairs.append((bucket["hr"], bucket["rr"]))
            awake_pairs = awake_pairs[-720:]
        if bucket["status"] == 1:
            offbed_run += 1
        else:
            offbed_run = 0
        if offbed_run >= 3:
            operational["off_bed_10s"] += 1
            if offbed_run == 3:
                path.observe_confirmed_off_bed(bucket["t"])
                context.clear()
                last_valid_t = None
            if offbed_run == 3 or epoch_boundary:
                upsert_off_bed_epoch(bucket)
            continue
        if path.off_bed_latched:
            return_confirmed = bool(
                bucket.get("status") in ZEEP_ON_BED_STATUS_CODES
                and bucket["valid"]
            )
            if return_confirmed:
                attributed_through = max(
                    (
                        float(row.get("attribution_end", row["t"]))
                        for row in [*state_rows, *status_rows]
                    ),
                    default=start,
                )
                missing_off_bed_s = max(
                    0.0,
                    float(bucket["t"]) - attributed_through,
                )
                if missing_off_bed_s > 1e-6:
                    status_rows.append(operational_status_row(
                        bucket,
                        state="off_bed",
                        data_status="confirmed_off_bed",
                        reason=(
                            "คง OFF BED จนมี Bed Status และ HR/RR "
                            "ยืนยันว่าผู้ใช้งานกลับมา"
                        ),
                        segment=path.segment,
                        sample_interval_s=missing_off_bed_s,
                    ))
                path.observe_confirmed_return()
                resume_attribution_start = float(bucket["t"])
                context.clear()
                context.append(bucket)
                last_valid_t = bucket["t"]
            else:
                operational["off_bed_latched_10s"] += 1
                if epoch_boundary:
                    upsert_off_bed_epoch(bucket)
                continue
        if not bucket["valid"]:
            operational["invalid_10s"] += 1
            if epoch_boundary:
                path.interrupt_confirmation()
                no_packets = int(bucket.get("packet_count") or 0) <= 0
                append_continuity_hold(
                    bucket,
                    decision=(
                        "sensor_gap_hold" if no_packets
                        else "invalid_evidence_hold"
                    ),
                    reason=(
                        "ไม่มี Raw BCG packet ใน Epoch นี้"
                        if no_packets else
                        "BCG หรือคู่ HR/RR "
                        "ไม่ผ่านเกณฑ์ราย Epoch"
                    ),
                )
            if last_valid_t is not None and bucket["t"] - last_valid_t >= SLEEP_CONTEXT_RESET_GAP_SECONDS:
                path.observe_signal_gap()
                context.clear()
                last_valid_t = None
            continue
        last_valid_t = bucket["t"]
        if not epoch_boundary:
            continue
        current_epoch = list(context)[-3:]
        if len(current_epoch) < 3:
            operational["incomplete_current_epoch_30s"] += 1
            append_continuity_hold(
                bucket,
                decision="incomplete_current_epoch_hold",
                reason=(
                    "ข้อมูลสดหลังช่วงขาดหายยังไม่ครบ Epoch 30 วินาที"
                ),
            )
            continue
        if any(item["status"] == 1 for item in current_epoch):
            operational["possible_off_bed_epoch_30s"] += 1
            append_continuity_hold(
                bucket,
                decision="confirming_off_bed_hold",
            )
            continue
        if any(not item["valid"] for item in current_epoch):
            operational["invalid_current_epoch_30s"] += 1
            path.interrupt_confirmation()
            append_continuity_hold(
                bucket,
                decision="incomplete_current_epoch_evidence_hold",
                reason=(
                    "Bed + HR + RR + Raw BCG ไม่ครบทุก bucket "
                    "ของ Epoch 30 วินาที"
                ),
            )
            continue
        short = list(context)[-6:]
        valid_short = [item for item in short if item["valid"]]
        if len(short) < 6 or len(valid_short) / len(short) < 0.80:
            operational["insufficient_epoch_30s"] += 1
            append_continuity_hold(
                bucket,
                decision="rebuilding_confirmation_window_hold",
            )
            continue
        hrs = [item["hr"] for item in valid_short]
        rrs = [item["rr"] for item in valid_short]
        statuses = [item["status"] for item in valid_short if item["status"] is not None]
        movement = movement_window_metrics(statuses)
        waveform = waveform_features([sample for item in valid_short for sample in item["samples"]])
        waveform_sample_count = sum(len(item["samples"]) for item in valid_short)
        expected_waveform_samples = max(
            1.0, BCG_SAMPLE_RATE_HZ * len(short) * 10.0
        )
        waveform_coverage = min(
            1.0, waveform_sample_count / expected_waveform_samples
        )
        waveform["waveform_sample_coverage"] = round(waveform_coverage, 4)
        waveform["minimum_waveform_sample_coverage"] = SLEEP_MIN_WAVEFORM_COVERAGE
        if waveform_coverage < SLEEP_MIN_WAVEFORM_COVERAGE:
            waveform["waveform_available"] = False
            waveform["waveform_rejection_reason"] = "insufficient_sample_coverage"
        summary = summary_features(hrs, rrs, 10.0)
        long_valid = [item for item in context if item["valid"]]
        long_summary = summary_features(
            [item["hr"] for item in long_valid],
            [item["rr"] for item in long_valid],
            10.0,
        )
        mean_hr = sum(hrs) / len(hrs)
        mean_rr = sum(rrs) / len(rrs)
        awake_hr = percentile((item[0] for item in awake_pairs), 0.75) if len(awake_pairs) >= 6 else None
        awake_rr = percentile((item[1] for item in awake_pairs), 0.75) if len(awake_pairs) >= 6 else None
        base_scores = {}
        hr_fits = {}
        rr_fits = {}
        for stage in STAGES:
            hr_fit = interval_fit(mean_hr, baseline[stage]["hr"])
            rr_fit = interval_fit(mean_rr, baseline[stage]["rr"])
            hr_fits[stage] = hr_fit
            rr_fits[stage] = rr_fit
            base_scores[stage] = (
                SLEEP_DEFAULT_BASELINE_HR_WEIGHT * hr_fit
                + SLEEP_DEFAULT_BASELINE_RR_WEIGHT * rr_fit
            )
        elapsed_min = max(0.0, (bucket["t"] - start) / 60.0)
        metrics = {
            "mean_hr": mean_hr,
            "mean_rr": mean_rr,
            "awake_hr_reference": awake_hr,
            "awake_rr_reference": awake_rr,
            "current_stage": path.last or "wake",
            "sleep_onset_established": path.sleep_onset_at is not None,
            "sleep_elapsed_min": (
                (bucket["t"] - path.sleep_onset_at) / 60.0
                if path.sleep_onset_at is not None else 0.0
            ),
            "movement_ratio": movement["movement_ratio"],
            "max_moving_run_frames": movement["max_moving_run_frames"],
            "movement_burst_count": movement["movement_burst_count"],
            "bed_status": "Moving" if statuses and statuses[-1] == 2 else "On bed",
            **summary,
            **waveform,
            # Multi-scale context is used for transition direction only.
            "hr_slope_bpm_per_min": long_summary.get("hr_slope_bpm_per_min"),
            "rr_slope_per_min": long_summary.get("rr_slope_per_min"),
        }
        sound_values = [
            float(item["sound_leq_dba"]) for item in short
            if isinstance(item.get("sound_leq_dba"), (int, float))
            and math.isfinite(float(item["sound_leq_dba"]))
        ]
        sound_coverage = len(sound_values) / max(1, len(short))
        acoustic_event = bool(
            sound_coverage >= SLEEP_DEFAULT_ACOUSTIC_MIN_COVERAGE
            and (
                any(value >= SLEEP_DEFAULT_ACOUSTIC_DISTURBANCE_DBA
                    for value in sound_values)
                or any(bool(item.get("sound_large_step")) for item in short)
            )
        )
        shift_ratio = waveform.get("bcg_amplitude_shift_ratio")
        bcg_shift = bool(
            isinstance(shift_ratio, (int, float)) and float(shift_ratio) >= 0.12
        )
        bed_motion = bool(
            movement["movement_ratio"] >= SLEEP_DEFAULT_MOVE_WAKE_RATIO
            or (statuses and statuses[-1] == 2)
        )
        acoustic_corroborated = bool(acoustic_event and (bcg_shift or bed_motion))
        metrics["corroborated_acoustic_wake_support"] = (
            SLEEP_DEFAULT_ACOUSTIC_WAKE_SUPPORT_MAX if acoustic_corroborated else 0.0
        )
        scores, evidence = score_sleep_evidence(
            base_scores=base_scores,
            hr_fits=hr_fits,
            rr_fits=rr_fits,
            metrics=metrics,
            elapsed_min=elapsed_min,
            rem_variability_weight=rem_variability_weight,
            n3_rr_conflict_penalty=SLEEP_DEFAULT_N3_RR_CONFLICT_PENALTY,
            n2_rr_conflict_support=SLEEP_DEFAULT_N2_RR_CONFLICT_SUPPORT,
            move_wake_ratio=SLEEP_DEFAULT_MOVE_WAKE_RATIO,
            move_deep_ratio=SLEEP_DEFAULT_MOVE_DEEP_RATIO,
            onset_min_observation_minutes=SLEEP_ONSET_MIN_OBSERVATION_SECONDS / 60.0,
            onset_max_movement_ratio=SLEEP_ONSET_MAX_MOVEMENT_RATIO,
            onset_min_downward_transition=SLEEP_ONSET_MIN_DOWNWARD_TRANSITION,
            onset_min_relative_sleep_support=SLEEP_ONSET_MIN_RELATIVE_SLEEP_SUPPORT,
            onset_max_hr_rise_bpm_per_min=SLEEP_ONSET_MAX_HR_RISE_BPM_PER_MIN,
            onset_max_rr_rise_per_min=SLEEP_ONSET_MAX_RR_RISE_PER_MIN,
            onset_initial_wake_support=SLEEP_ONSET_INITIAL_WAKE_SUPPORT,
            deep_cv_threshold=SLEEP_DEFAULT_HR_CV_DEEP,
            rem_cv_threshold=SLEEP_DEFAULT_HR_CV_REM,
        )
        eligible_states = {
            "wake": evidence["wake_gate"],
            "n1": evidence["n1_gate"],
            "n2": evidence["n2_gate"],
            "n3": evidence["n3_gate"],
            "rem": evidence["rem_gate"],
        }
        stage_evidence_probabilities = softmax_stage_evidence(
            scores,
            temperature=SLEEP_SCORE_SOFTMAX_TEMPERATURE,
            eligible_states=eligible_states,
        )
        probabilities, fit_fusion = (
            fuse_hr_rr_fit_with_stage_probabilities(
                stage_evidence_probabilities,
                base_scores,
                eligible_states=eligible_states,
                confirmed_state=path.last,
                fit_weight=SLEEP_HR_RR_FIT_FUSION_WEIGHT,
                agreement_weight=(
                    SLEEP_HR_RR_FIT_FUSION_AGREEMENT_WEIGHT
                ),
            )
        )
        evidence["hr_rr_fit_fusion"] = fit_fusion
        accepted, quality = evidence_candidate_with_abstention(
            probabilities,
            minimum_winner=SLEEP_EVIDENCE_MIN_WINNER,
            minimum_margin=SLEEP_EVIDENCE_MIN_MARGIN,
            gated_stage_thresholds=(
                {"n3": (SLEEP_N3_GATED_MIN_WINNER, SLEEP_N3_GATED_MIN_MARGIN)}
                if evidence["n3_gate"] else None
            ),
        )
        path.ema = smooth_stage_probabilities(
            path.ema, probabilities, alpha=SLEEP_PROBABILITY_EMA_ALPHA,
        )
        candidate = None
        candidate_meta = {"candidate_source": "abstain"}
        if accepted is not None:
            candidate, candidate_meta = candidate_from_stage_evidence(
                probabilities,
                path.ema,
                path.last,
                switch_margin=SLEEP_PROBABILITY_SWITCH_MARGIN,
                n3_gate=bool(evidence["n3_gate"]),
                sleep_onset_gate_passed=bool(
                    evidence["sleep_onset_gate"]["passed"]
                    or evidence["sleep_onset_established"]
                ),
                eligible_states=eligible_states,
            )
        strong_wake = bool(
            max(probabilities, key=probabilities.get) == "wake"
            and evidence["movement"]["strong_wake"]
        )
        if strong_wake:
            candidate = "wake"
        if path.last is None and candidate != "wake":
            candidate_meta.update({
                "candidate_source": "initial_awake_anchor",
                "initial_awake_anchor": True,
                "initial_evidence_candidate": candidate,
            })
            candidate = "wake"
        confirmed, transition = path.step(candidate, bucket["t"], strong_wake)
        evidence_rows.append({
            "t": bucket["t"],
            "candidate": candidate,
            "winner": max(probabilities, key=probabilities.get),
            "probabilities": {key: round(value, 6) for key, value in probabilities.items()},
            "pre_fusion_probabilities": {
                key: round(value, 6)
                for key, value in stage_evidence_probabilities.items()
            },
            "hr_rr_fit_fusion": fit_fusion,
            "quality": quality,
            "candidate_policy": candidate_meta,
            "gates": {key: evidence[key] for key in ("wake_gate", "n1_gate", "n2_gate", "n3_gate", "rem_gate")},
            "diagnostics": {
                "current_stage": metrics["current_stage"],
                "mean_hr": metrics.get("mean_hr"),
                "mean_rr": metrics.get("mean_rr"),
                "awake_hr_reference": metrics.get("awake_hr_reference"),
                "awake_rr_reference": metrics.get("awake_rr_reference"),
                "hr_slope_bpm_per_min": metrics.get("hr_slope_bpm_per_min"),
                "rr_slope_per_min": metrics.get("rr_slope_per_min"),
                "hr_cv": metrics.get("hr_cv"),
                "rr_cv": metrics.get("rr_cv"),
                "resp_regularity": metrics.get("resp_regularity"),
                "relative_sleep_support": evidence["relative_sleep_support"],
                "hr_drop_support": evidence["hr_drop_support"],
                "rr_drop_support": evidence["rr_drop_support"],
                "sleep_onset_gate": evidence["sleep_onset_gate"],
                "waveform_available": metrics.get("waveform_available"),
                "drift": metrics.get("bcg_baseline_drift_flag"),
                "acoustic_event": acoustic_event,
                "acoustic_corroborated": acoustic_corroborated,
            },
            "transition": transition,
            "provenance": {
                "estimator": SLEEP_ESTIMATOR_VERSION,
                "evidence": SLEEP_EVIDENCE_VERSION,
                "baseline": ZEEP_SLEEP_BASELINE_VERSION,
                "transition": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            },
        })
        state_rows.append({
            "t": bucket["t"],
            "attribution_start": (
                float(bucket["t"]) - SLEEP_EVIDENCE_EPOCH_SECONDS
            ),
            "attribution_end": float(bucket["t"]),
            "sample_interval_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "state": confirmed,
            "segment": path.segment,
            "metrics": metrics,
            "decision_kind": transition.get(
                "decision_kind", "confirmed_state"
            ),
            "decision": transition.get("decision"),
            "held_previous_state": bool(
                transition.get("held_previous_state")
            ),
            "provisional": bool(transition.get("provisional")),
            "pending_state": transition.get("pending_state"),
            "score_attribution_state": (
                transition.get("score_attribution_state") or confirmed
            ),
            "challenger_counted_as_new_state": bool(
                transition.get("challenger_counted_as_new_state")
            ),
            "score_eligible": bool(
                transition.get("score_eligible", True)
            ),
            "excluded_from_score": bool(
                transition.get("excluded_from_score", False)
            ),
            "excluded_from_personal_baseline": bool(
                transition.get(
                    "excluded_from_personal_baseline", False
                )
            ),
            "confirmation": transition,
        })

    # A Session may end between canonical 30-second boundaries. The incomplete
    # tail cannot create a new State, but it is still real occupied time, so it
    # inherits the last State (or initial W) unless Raw Bed Status confirms the
    # occupant left. It remains excluded from Personal Baseline learning.
    complete_epoch_s = (
        math.floor((end - start) / SLEEP_EVIDENCE_EPOCH_SECONDS + 1e-9)
        * SLEEP_EVIDENCE_EPOCH_SECONDS
    )
    partial_tail_s = max(0.0, (end - start) - complete_epoch_s)
    if partial_tail_s > 1e-6:
        tail_packets = [
            packet for packet in packets
            if start + complete_epoch_s < epoch(packet["timestamp"]) <= end
        ]
        tail_pair_flags = [bool(
            filter_vital_values([packet["heart_rate"]], HR_SANITY_RANGE_BPM)
            and filter_vital_values(
                [packet["respiration_rate"]], RR_SANITY_RANGE_PER_MIN
            )
        ) for packet in tail_packets]
        tail_paired = sum(tail_pair_flags)
        tail_bucket = {
            "t": end,
            "packet_count": len(tail_packets),
            "paired_packets": tail_paired,
            "paired_vital_coverage": (
                tail_paired / len(tail_packets) if tail_packets else 0.0
            ),
            "waveform_sample_coverage": 0.0,
        }
        tail_statuses = [int(packet["status_code"]) for packet in tail_packets]
        exit_evidence = bed_exit_window_evidence(
            tail_statuses,
            latest_raw_exit_frames=tail_statuses.count(1),
            latest_raw_total_frames=len(tail_statuses),
            terminal_session_boundary=True,
        )
        trailing_exit = int(exit_evidence["trailing_exit_buckets"])
        exit_start = len(tail_packets) - trailing_exit
        no_vitals_after_exit = bool(
            trailing_exit and not any(tail_pair_flags[exit_start:])
        )
        terminal_exit_confirmed = bool(
            exit_evidence["confirmed"] and no_vitals_after_exit
        )
        return_indices = [
            index
            for index, (status, pair_valid) in enumerate(zip(
                tail_statuses,
                tail_pair_flags,
                strict=True,
            ))
            if status in ZEEP_ON_BED_STATUS_CODES and pair_valid
        ]
        return_confirmed = bool(return_indices)

        def append_tail_off_bed(
            period_start: float,
            period_end: float,
            reason: str,
        ) -> None:
            interval_s = max(0.0, period_end - period_start)
            if interval_s <= 1e-6:
                return
            status_bucket = {**tail_bucket, "t": period_end}
            status_rows.append(operational_status_row(
                status_bucket,
                state="off_bed",
                data_status="confirmed_off_bed",
                reason=reason,
                segment=path.segment,
                sample_interval_s=interval_s,
            ))

        tail_start = start + complete_epoch_s
        return_epoch = (
            epoch(tail_packets[return_indices[0]]["timestamp"])
            if return_confirmed else None
        )
        if terminal_exit_confirmed:
            first_exit_epoch = epoch(tail_packets[exit_start]["timestamp"])
            terminal_exit_start = max(
                tail_start,
                first_exit_epoch - min(10.0, partial_tail_s),
            )
            returned_before_exit = bool(
                return_epoch is not None
                and return_epoch < terminal_exit_start
            )
            if path.off_bed_latched and returned_before_exit:
                append_tail_off_bed(
                    tail_start,
                    return_epoch,
                    "คง OFF BED จนมี Bed Status และ HR/RR ยืนยันว่ากลับมา",
                )
                path.observe_confirmed_return()
                resume_attribution_start = return_epoch
            elif path.off_bed_latched:
                terminal_exit_start = tail_start
            if terminal_exit_start > tail_start and not path.off_bed_latched:
                prefix_bucket = {**tail_bucket, "t": terminal_exit_start}
                append_continuity_hold(
                    prefix_bucket,
                    decision="incomplete_final_epoch_hold",
                    reason=(
                        "Session จบก่อนครบ 30 วินาที · คง State ก่อนหน้า"
                    ),
                    sample_interval_s=terminal_exit_start - tail_start,
                )
            append_tail_off_bed(
                terminal_exit_start,
                end,
                "Raw Bed Status ยืนยันว่าออกจากเตียงก่อนจบ Session",
            )
            path.observe_confirmed_off_bed(end)
        elif path.off_bed_latched and return_epoch is None:
            append_tail_off_bed(
                tail_start,
                end,
                "คง OFF BED หลังการออกจากเตียงที่ยืนยันแล้ว",
            )
        else:
            if path.off_bed_latched and return_epoch is not None:
                append_tail_off_bed(
                    tail_start,
                    return_epoch,
                    "คง OFF BED จนมี Bed Status และ HR/RR ยืนยันว่ากลับมา",
                )
                resume_attribution_start = return_epoch
                path.observe_confirmed_return()
            append_continuity_hold(
                tail_bucket,
                decision="incomplete_final_epoch_hold",
                reason=(
                    "Session จบก่อนครบ 30 วินาที · คง State ก่อนหน้า"
                ),
                sample_interval_s=partial_tail_s,
            )
        operational["incomplete_final_epoch"] += 1

    counts = _duration_weighted_state_counts(state_rows)
    gate_pass_counts = Counter(
        gate
        for row in evidence_rows
        for gate, passed in row["gates"].items()
        if passed
    )
    winner_counts = Counter(row["winner"] for row in evidence_rows)
    fit_overall_winner_counts = Counter(
        winner
        for row in evidence_rows
        if (winner := row["hr_rr_fit_fusion"].get(
            "overall_fit_winner"
        ))
    )
    fit_eligible_winner_counts = Counter(
        winner
        for row in evidence_rows
        if (winner := row["hr_rr_fit_fusion"].get(
            "eligible_fit_winner"
        ))
    )
    fit_changed_winner_count = sum(
        row["hr_rr_fit_fusion"].get("evidence_winner_before_fusion")
        != row["hr_rr_fit_fusion"].get("fused_winner")
        for row in evidence_rows
    )
    fit_agreement_count = sum(
        bool(row["hr_rr_fit_fusion"].get(
            "fit_agrees_with_confirmed_state"
        ))
        for row in evidence_rows
    )
    fit_winner_gate_closed_count = sum(
        not bool(row["hr_rr_fit_fusion"].get(
            "overall_fit_winner_eligible"
        ))
        for row in evidence_rows
    )
    abstention_count = sum(not row["quality"]["passed"] for row in evidence_rows)
    confirmed_without_current_gate = sum(
        1 for row in evidence_rows
        if row["transition"].get("decision") == "confirmed"
        and row.get("candidate") in STAGES
        and not row["gates"].get(f"{row['candidate']}_gate", False)
    )
    n3_failure_counts = Counter()
    for row in evidence_rows:
        diagnostic = row["diagnostics"]
        checks = {
            "not_in_n2_or_n3": diagnostic["current_stage"] not in {"n2", "n3"},
            "missing_waveform": not diagnostic["waveform_available"],
            "drift": bool(diagnostic["drift"]),
            "movement_or_context": not row["gates"]["n2_gate"],
            "hr_cv_high": float(diagnostic["hr_cv"] or 0) > 0.025,
            "rr_cv_high": float(diagnostic["rr_cv"] or 0) > 0.040,
            "regularity_low": float(diagnostic["resp_regularity"] or 0) < 0.58,
            "relative_drop_low": diagnostic["relative_sleep_support"] < 0.45,
        }
        for reason, failed in checks.items():
            if failed:
                n3_failure_counts[reason] += 1
    transitions = Counter(
        (left["state"], right["state"])
        for left, right in zip(state_rows, state_rows[1:])
        if left["segment"] == right["segment"] and left["state"] != right["state"]
    )
    ping_pong = sum(
        1 for a, b, c in zip(state_rows, state_rows[1:], state_rows[2:])
        if a["segment"] == b["segment"] == c["segment"]
        and a["state"] == c["state"] != b["state"] and c["t"] - a["t"] <= 60.0
    )
    first_by_stage = {
        stage: next((row["t"] for row in state_rows if row["state"] == stage), None)
        for stage in STAGES
    }
    first_sleep_t = next(
        (row["t"] for row in state_rows if row["state"] in SLEEP_STAGES), None,
    )
    evaluation_epoch_count = len(state_rows) + len(status_rows)
    state_duration_s = sum(
        float(row.get("sample_interval_s") or SLEEP_EVIDENCE_EPOCH_SECONDS)
        for row in state_rows
    )
    status_duration_s = sum(
        float(row.get("sample_interval_s") or SLEEP_EVIDENCE_EPOCH_SECONDS)
        for row in status_rows
    )
    evaluation_duration_s = state_duration_s + status_duration_s
    evaluation_epoch_equivalents = (
        evaluation_duration_s / SLEEP_EVIDENCE_EPOCH_SECONDS
    )
    state_attribution_coverage = (
        state_duration_s * 100.0 / evaluation_duration_s
        if evaluation_duration_s else 0.0
    )
    physiological_evidence_duration_s = min(
        evaluation_duration_s,
        len(evidence_rows) * SLEEP_EVIDENCE_EPOCH_SECONDS,
    )
    physiological_evidence_coverage = (
        physiological_evidence_duration_s * 100.0 / evaluation_duration_s
        if evaluation_duration_s else 0.0
    )
    evidence_by_time = {
        round(float(row["t"]), 3): row for row in evidence_rows
    }
    confidence_counts = Counter(
        confidence(evidence_by_time.get(round(float(row["t"]), 3), {}))
        for row in state_rows
    )
    confidence_total = sum(confidence_counts.values())
    confidence_percent = {
        level: (
            round(confidence_counts[level] * 100.0 / confidence_total, 1)
            if confidence_total else 0.0
        )
        for level in ("high", "medium", "low")
    }
    def state_seconds(predicate: Any) -> float:
        return sum(
            float(
                row.get("sample_interval_s")
                or SLEEP_EVIDENCE_EPOCH_SECONDS
            )
            for row in state_rows
            if predicate(row)
        )

    direct_confirmed_s = state_seconds(
        lambda row: not bool(row.get("held_previous_state"))
    )
    continuity_carried_s = state_seconds(
        lambda row: bool(row.get("held_previous_state"))
    )
    provisional_hold_s = state_seconds(
        lambda row: bool(row.get("provisional"))
    )
    score_eligible_s = state_seconds(
        lambda row: bool(row.get("score_eligible", True))
    )
    direct_confirmed_count = sum(
        not bool(row.get("held_previous_state")) for row in state_rows
    )
    continuity_carried_count = sum(
        bool(row.get("held_previous_state")) for row in state_rows
    )
    off_bed_s = sum(
        float(row.get("sample_interval_s") or SLEEP_EVIDENCE_EPOCH_SECONDS)
        for row in status_rows if row["state"] == "off_bed"
    )
    occupied_gap_s = max(0.0, status_duration_s - off_bed_s)
    return {
        "bucket_count": len(buckets),
        "evaluation_epoch_count": evaluation_epoch_count,
        "evaluation_epoch_equivalents": round(
            evaluation_epoch_equivalents, 6
        ),
        "evaluation_duration_s": round(evaluation_duration_s, 3),
        "evidence_count": len(evidence_rows),
        "confirmed_count": len(state_rows),
        "direct_confirmed_count": direct_confirmed_count,
        "continuity_carried_count": continuity_carried_count,
        "classification_accounting": {
            "direct_confirmed_s": round(
                direct_confirmed_s, 1
            ),
            "continuity_carried_forward_s": round(
                continuity_carried_s, 1
            ),
            "provisional_hold_s": round(
                provisional_hold_s, 1
            ),
            "display_attributed_s": round(state_duration_s, 1),
            "actual_scored_s": round(score_eligible_s, 1),
            "initial_wait_s": round(
                sum(
                    float(row.get("sample_interval_s") or SLEEP_EVIDENCE_EPOCH_SECONDS)
                    for row in status_rows if row["state"] == "wait"
                ),
                1,
            ),
            "no_data_s": round(
                sum(
                    float(row.get("sample_interval_s") or SLEEP_EVIDENCE_EPOCH_SECONDS)
                    for row in status_rows if row["state"] == "no_data"
                ),
                1,
            ),
            "off_bed_s": round(off_bed_s, 1),
            "occupied_in_pod_state_gap_s": round(occupied_gap_s, 1),
            "occupied_state_invariant": {
                "gap_s": round(occupied_gap_s, 3),
                "holds": occupied_gap_s <= 0.001,
            },
            "recording_s": round(max(0.0, end - start), 1),
            "accounted_s": round(evaluation_duration_s, 1),
            "arithmetic_invariant": {
                "left_s": round(evaluation_duration_s, 3),
                "right_s": round(max(0.0, end - start), 3),
                "delta_s": round(
                    evaluation_duration_s - max(0.0, end - start), 3
                ),
                "holds": abs(
                    evaluation_duration_s - max(0.0, end - start)
                ) <= 0.001,
            },
        },
        "operational_status_count": len(status_rows),
        "operational_status_counts": dict(Counter(
            row["state"] for row in status_rows
        )),
        "counts": dict(counts),
        "gate_pass_counts": dict(gate_pass_counts),
        "evidence_winner_counts": dict(winner_counts),
        "hr_rr_fit_fusion": {
            "overall_fit_winner_counts": dict(fit_overall_winner_counts),
            "eligible_fit_winner_counts": dict(fit_eligible_winner_counts),
            "changed_evidence_winner_count": fit_changed_winner_count,
            "agreed_with_confirmed_state_count": fit_agreement_count,
            "overall_fit_winner_gate_closed_count": (
                fit_winner_gate_closed_count
            ),
            "evidence_epochs": len(evidence_rows),
            "fit_can_bypass_state_gate": False,
            "fit_can_bypass_confirmation": False,
        },
        "abstention_count": abstention_count,
        # Legacy alias retained for existing audit consumers. In v1.29 this is
        # State attribution coverage and can include continuity carry.
        "confirmed_coverage_percent": round(
            state_attribution_coverage, 1
        ),
        "state_attribution_coverage_percent": round(
            state_attribution_coverage, 1
        ),
        "physiological_evidence_duration_s": round(
            physiological_evidence_duration_s, 1
        ),
        "physiological_evidence_coverage_percent": round(
            physiological_evidence_coverage, 1
        ),
        "confidence_percent": confidence_percent,
        "sleep_onset_minutes": (
            round((first_sleep_t - start) / 60.0, 1)
            if first_sleep_t is not None else None
        ),
        "first_stage_minutes": {
            stage: (
                round((timestamp - start) / 60.0, 1)
                if timestamp is not None else None
            )
            for stage, timestamp in first_by_stage.items()
        },
        "n3_gate_failure_counts": dict(n3_failure_counts),
        "transitions": {f"{a}->{b}": value for (a, b), value in transitions.items()},
        "forbidden_transition_count": sum(
            1
            for left, right in zip(state_rows, state_rows[1:])
            if left["segment"] == right["segment"]
            and left["state"] != right["state"]
            and right["state"] not in SLEEP_ALLOWED_TRANSITIONS.get(
                left["state"], frozenset()
            )
            and not (
                right["state"] == "wake"
                and bool(
                    (right.get("confirmation") or {}).get(
                        "strong_wake_override"
                    )
                )
            )
        ),
        "ping_pong_count": ping_pong,
        "confirmed_transition_without_current_gate_count": (
            confirmed_without_current_gate
        ),
        "operational": dict(operational),
        "evidence_rows": evidence_rows,
        "state_rows": state_rows,
        "status_rows": status_rows,
        "sensor_rows": [
            {
                "hr": item["hr"], "rr": item["rr"],
                "bed": (
                    "Get out of bed" if item["status"] == 1
                    else "Moving" if item["status"] == 2 else "On bed"
                ),
            }
            for item in buckets if item["valid"]
        ],
    }


def latest_summary(connection: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT value FROM events WHERE session_id=? AND type='final_summary' "
        "ORDER BY timestamp DESC LIMIT 1", (session_id,),
    ).fetchone()
    if not row:
        return {}
    try:
        value = json.loads(row["value"] or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def normalize_session_allowlist(
    session_ids: Optional[Iterable[str]],
) -> list[str]:
    """Normalize a repeated CLI allowlist without widening its selection.

    Duplicate identifiers are collapsed in operator order.  An explicitly
    supplied blank identifier is rejected instead of being interpreted as an
    omitted filter, because silently falling back to the full cohort would be
    unsafe for a targeted historical replay.
    """
    if session_ids is None:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_session_id in session_ids:
        session_id = str(raw_session_id or "").strip()
        if not session_id:
            raise ValueError("--session-id cannot be blank")
        if session_id not in seen:
            normalized.append(session_id)
            seen.add(session_id)
    return normalized


def _explicit_session_ineligibility(
    row: sqlite3.Row,
    *,
    cutoff_utc: str,
    minimum_duration_seconds: float,
) -> Optional[str]:
    """Return why a requested Session cannot enter a targeted replay."""
    if row["end_time"] is None:
        return "session_not_completed"
    try:
        duration_seconds = float(row["duration"])
    except (TypeError, ValueError):
        return "invalid_session_duration"
    if not math.isfinite(duration_seconds):
        return "invalid_session_duration"
    if duration_seconds <= minimum_duration_seconds:
        return "session_duration_not_above_minimum"
    try:
        if epoch(row["start_time"]) < epoch(cutoff_utc):
            return "session_before_cutover"
    except (TypeError, ValueError):
        return "invalid_session_start_time"
    return None


def select_session_rows(
    connection: sqlite3.Connection,
    *,
    session_ids: Optional[Iterable[str]],
    cutoff_utc: str,
    minimum_minutes: float,
) -> tuple[list[sqlite3.Row], dict[str, Any]]:
    """Select the replay cohort, failing closed for an explicit allowlist.

    With no ``session_ids`` this deliberately retains the historical cohort
    query.  With an allowlist, every requested identifier must exist and pass
    the same completed/cutover/duration boundaries before any replay begins.
    """
    try:
        minimum_minutes_value = float(minimum_minutes)
    except (TypeError, ValueError) as exc:
        raise ValueError("minimum minutes must be a number") from exc
    if not math.isfinite(minimum_minutes_value) or minimum_minutes_value < 0:
        raise ValueError("minimum minutes must be finite and non-negative")
    minimum_duration_seconds = minimum_minutes_value * 60.0
    allowlist = normalize_session_allowlist(session_ids)

    if not allowlist:
        rows = connection.execute(
            "SELECT * FROM sessions WHERE end_time IS NOT NULL AND duration>? "
            "AND start_time>=? ORDER BY start_time",
            (minimum_duration_seconds, cutoff_utc),
        ).fetchall()
        return list(rows), {
            "mode": "eligible_cohort_query",
            "operator_supplied": False,
            "requested_session_count": 0,
            "selected_session_count": len(rows),
        }

    selected_by_id: dict[str, sqlite3.Row] = {}
    rejection_reasons: list[str] = []
    for session_id in allowlist:
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            rejection_reasons.append(f"{session_id}=session_not_found")
            continue
        reason = _explicit_session_ineligibility(
            row,
            cutoff_utc=cutoff_utc,
            minimum_duration_seconds=minimum_duration_seconds,
        )
        if reason:
            rejection_reasons.append(f"{session_id}={reason}")
            continue
        selected_by_id[session_id] = row

    if rejection_reasons:
        raise ValueError(
            "explicit Session allowlist rejected: "
            + "; ".join(rejection_reasons)
        )

    rows = sorted(
        selected_by_id.values(),
        key=lambda row: (epoch(row["start_time"]), row["session_id"]),
    )
    selected_ids = [str(row["session_id"]) for row in rows]
    allowlist_sha256 = hashlib.sha256(
        json.dumps(allowlist, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return rows, {
        "mode": "explicit_session_allowlist",
        "operator_supplied": True,
        "requested_session_count": len(allowlist),
        "requested_session_ids": allowlist,
        "selected_session_count": len(rows),
        "selected_session_ids": selected_ids,
        "allowlist_sha256": allowlist_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions-db", required=True, type=Path)
    parser.add_argument("--bcg-db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--minimum-minutes", type=float, default=25.0)
    parser.add_argument(
        "--start-local-date",
        default=PERSONAL_BASELINE_LEARNING_START_LOCAL_DATE,
        help="Inclusive local pilot cutover date (YYYY-MM-DD)",
    )
    parser.add_argument("--profiles-file", type=Path)
    parser.add_argument(
        "--details-output", type=Path,
        help="Optional derived evidence/state artifact for reviewed promotion",
    )
    parser.add_argument(
        "--session-id",
        action="append",
        dest="session_ids",
        metavar="SESSION_ID",
        help=(
            "Replay only this completed, cutover-eligible Session. Repeat the "
            "option to create an explicit targeted allowlist."
        ),
    )
    args = parser.parse_args()

    cutoff_local = datetime.fromisoformat(args.start_local_date).replace(
        tzinfo=LOCAL_TIMEZONE
    )
    cutoff_utc = cutoff_local.astimezone(ZoneInfo("UTC")).isoformat()

    sessions = sqlite3.connect(f"file:{args.sessions_db}?mode=ro", uri=True)
    sessions.row_factory = sqlite3.Row
    bcg = sqlite3.connect(f"file:{args.bcg_db}?mode=ro", uri=True)
    bcg.row_factory = sqlite3.Row
    try:
        rows, selection_provenance = select_session_rows(
            sessions,
            session_ids=args.session_ids,
            cutoff_utc=cutoff_utc,
            minimum_minutes=args.minimum_minutes,
        )
    except ValueError as exc:
        parser.error(str(exc))
    profiles = load_profile_index(args.profiles_file)
    results = []
    details: dict[str, Any] = {}
    prior_behaviour: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    mode_counts = Counter()
    email_counts = Counter()
    tier_counts = Counter()
    for row in rows:
        timeline = sessions.execute(
            "SELECT heart_rate,respiration_rate FROM timeline WHERE session_id=?",
            (row["session_id"],),
        ).fetchall()
        paired = sum(bool(
            filter_vital_values([item["heart_rate"]], HR_SANITY_RANGE_BPM)
            and filter_vital_values([item["respiration_rate"]], RR_SANITY_RANGE_PER_MIN)
        ) for item in timeline)
        paired_coverage = paired / len(timeline) if timeline else 0.0
        summary = latest_summary(sessions, row["session_id"])
        mode_context = resolve_replay_mode_context(row, summary)
        resolved_mode = str(mode_context["resolved"])
        group = str(mode_context["group"])
        old_score = mode_context["old_score"]
        scoring_mode = str(mode_context["scoring_mode"])
        target_duration_s = mode_context["target_duration_s"]
        mode_counts[group] += 1
        email_counts[row["username_key"]] += 1
        packets = raw_packets(bcg, row["session_id"])
        start, end = epoch(row["start_time"]), epoch(row["end_time"])
        account_key = str(row["username_key"] or "").strip().casefold()
        profile = profiles.get(account_key) or {}
        selected_age_group = str(profile.get("age_group") or "")
        if selected_age_group not in AGE_SLEEP_BASELINES:
            selected_age_group = age_group(profile.get("age"))
        baseline, gender_adjustment = gender_adjusted_baseline(
            selected_age_group, profile.get("gender"),
        )
        demographics = {
            "profile_found": bool(profile),
            "age": profile.get("age"),
            "age_group": selected_age_group,
            "gender": profile.get("gender") or "unspecified",
            "baseline_source": "shared_age_gender_population_prior",
            "rem_variability_weight": gender_adjustment["rem_variability_weight"],
        }
        raw_quality = raw_packet_quality(packets, start, end)
        raw_coverage = raw_quality["acquisition_coverage"]
        tier = quality_tier(
            timeline_paired_hr_rr=paired_coverage,
            raw_paired_hr_rr=raw_quality["paired_vital_coverage"],
            raw_acquisition=raw_coverage,
            raw_maximum_gap_s=raw_quality["maximum_packet_gap_s"],
            context_reset_gap_s=SLEEP_CONTEXT_RESET_GAP_SECONDS,
        )
        tier_counts[tier] += 1
        # Replay every Session in the operator-defined cohort.  Invalid or
        # missing 10-second buckets abstain inside replay_session; a whole-
        # Session QA tier must not discard otherwise valid physiological epochs.
        replay = replay_session(
            packets, start, end,
            baseline=baseline,
            rem_variability_weight=float(
                gender_adjustment["rem_variability_weight"]
            ),
            timeline_sound=sound_by_bucket(
                sessions, row["session_id"], start=start, end=end,
            ),
        )
        annotation_rows = sessions.execute(
            "SELECT value FROM events WHERE session_id=? "
            "AND type='sleep_stage_annotation' ORDER BY timestamp,id",
            (row["session_id"],),
        ).fetchall()
        annotations = load_annotations(annotation_rows)
        report_state_rows: list[dict[str, Any]] = []
        annotated_rounds = 0
        first_sleep_t = None
        new_score = None
        stage_pct = {}
        stage_pct_of_occupied_evidence = {}
        issue_codes = []
        behaviour_key = (str(row["username_key"]), group)
        prior = prior_behaviour[behaviour_key]
        behaviour_context = {
            "source": "prior_completed_replayable_sessions_same_mode_only",
            "prior_sessions": len(prior),
            "minimum_sessions": 3,
            "status": "active" if len(prior) >= 3 else "learning",
            "direct_stage_influence": False,
            "expected_onset_minutes": (
                round(float(median(item["onset_minutes"] for item in prior)), 1)
                if prior and median(item["onset_minutes"] for item in prior) is not None else None
            ),
            "typical_start_local_hour": (
                round(float(median(item["start_local_hour"] for item in prior)), 2)
                if prior and median(item["start_local_hour"] for item in prior) is not None else None
            ),
            "role": "expectation_and_report_context_only_until_validated",
        }
        if replay:
            report_state_rows, annotated_rounds = (
                report_state_rows_with_annotations(
                    replay["state_rows"], replay["evidence_rows"], annotations
                )
            )
            counts = _duration_weighted_state_counts(report_state_rows)
            score_rows = [
                item for item in report_state_rows
                if item.get("score_eligible", True)
            ]
            score_counts = _duration_weighted_state_counts(score_rows)
            total_sleep = sum(counts[stage] for stage in SLEEP_STAGES)
            stage_pct = {
                stage: round(counts[stage] * 100.0 / total_sleep, 1) if total_sleep else 0.0
                for stage in ("n1", "n2", "n3", "rem")
            }
            evidence_denominator = max(
                1.0,
                float(replay["evaluation_epoch_equivalents"]),
            )
            stage_pct_of_occupied_evidence = {
                stage: round(counts[stage] * 100.0 / evidence_denominator, 1)
                for stage in ("wake", "n1", "n2", "n3", "rem")
            }
            sequence = [
                {
                    "state": item["state"],
                    "timestamp": datetime.fromtimestamp(
                        item["t"]
                    ).isoformat(),
                    "metrics": item["metrics"],
                    "decision_kind": item.get("decision_kind"),
                    "held_previous_state": bool(
                        item.get("held_previous_state")
                    ),
                    "provisional": bool(item.get("provisional")),
                    "score_eligible": bool(
                        item.get("score_eligible", True)
                    ),
                }
                for item in report_state_rows
            ]
            first_sleep_t = next(
                (float(item.get("attribution_start", item["t"]))
                 for item in score_rows
                 if item["state"] in SLEEP_STAGES),
                None,
            )
            awakenings = sum(
                left["state"] in SLEEP_STAGES and right["state"] == "wake"
                for left, right in zip(
                    score_rows, score_rows[1:]
                )
            )
            waso_seconds = _duration_weighted_waso_seconds(score_rows)
            raw_report_sensor_rows = timeline_sensor_rows(
                sessions, row["session_id"], start=start, end=end,
            )
            report_sensor_rows, report_grid_summary = (
                project_replay_decisions_to_report_rows(
                    raw_report_sensor_rows,
                    report_state_rows,
                    replay["status_rows"],
                    session_start=start,
                    session_end=end,
                )
            )
            replay["report_sample_grid"] = report_grid_summary
            total_score_sleep = sum(
                score_counts[stage] for stage in SLEEP_STAGES
            )
            total_scored = sum(score_counts[stage] for stage in STAGES)
            night_summary = dict(summary.get("night_summary") or {})
            night_summary.update({
                "sleep_onset_proxy_s": (
                    round(first_sleep_t - start, 1)
                    if first_sleep_t is not None else None
                ),
                "awakenings": awakenings,
                "waso_proxy_s": round(waso_seconds, 1),
                "estimated_sleep_s": (
                    total_score_sleep * SLEEP_EVIDENCE_EPOCH_SECONDS
                ),
                "sleep_efficiency": (
                    round(total_score_sleep / total_scored, 3)
                    if total_scored else None
                ),
                "deep_ratio": (
                    round(score_counts["n3"] / total_score_sleep, 3)
                    if total_score_sleep else None
                ),
                "rem_ratio": (
                    round(score_counts["rem"] / total_score_sleep, 3)
                    if total_score_sleep else None
                ),
            })
            quality = build_sleep_quality(
                row["duration"], night_summary, counts, completed=True,
                rest_mode=scoring_mode, stage_sequence=sequence,
                sensor_samples=report_sensor_rows,
                sample_interval_s=SLEEP_EVIDENCE_EPOCH_SECONDS,
                target_duration_s=target_duration_s,
                score_state_counts=score_counts,
            )
            new_score = quality.get("score")
            shadow_mode = dict(quality.get("rest_mode") or {})
            report = build_session_report(
                row["duration"], report_sensor_rows, night_summary, counts, quality,
                rest_mode=scoring_mode,
                sample_interval_s=SLEEP_EVIDENCE_EPOCH_SECONDS,
                estimator_version=SLEEP_ESTIMATOR_VERSION,
                completed=True,
                timeline_schema_version=int(
                    summary.get("timeline_schema_version") or 3
                ),
                target_duration_s=target_duration_s,
                sleep_score_state_counts=score_counts,
            )
            if not quality.get("available"):
                issue_codes.append("wellness_score_not_releasable")
            details[row["session_id"]] = {
                "session_id": row["session_id"],
                "email": row["username_key"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "duration": row["duration"],
                "previous_mode": {
                    "resolved": resolved_mode,
                    "group": group,
                    "source": mode_context["mode_source"],
                },
                "target_duration_source": mode_context[
                    "target_duration_source"
                ],
                "mode": shadow_mode,
                "quality_tier": tier,
                "quality": quality,
                "report": report,
                "demographics": demographics,
                "review_warnings": [],
                "promotion_blockers": [],
                "evidence_rows": replay["evidence_rows"],
                "state_rows": replay["state_rows"],
                "report_state_rows": report_state_rows,
                "sleep_stage_annotations_used": len(annotations),
                "annotated_rounds": annotated_rounds,
                "status_rows": replay["status_rows"],
            }
            # Architecture-distribution flags are review prompts for the
            # overnight product only. Nap & Refresh explicitly allows awake
            # rest, brief N1/N2 or a short nap, so forcing adult overnight
            # proportions onto that mode would be a category error.
            if group == "unresolved":
                issue_codes.append("historical_rest_mode_unresolved")
            if group == "sleep" and stage_pct.get("n2", 0) > 85:
                issue_codes.append("overnight_N2_over_85_percent")
            if group == "sleep" and total_sleep and stage_pct.get("n1", 0) > 30:
                issue_codes.append("overnight_N1_over_30_percent")
            if group == "sleep" and total_sleep and stage_pct.get("n3", 0) > 35:
                issue_codes.append("overnight_N3_over_35_percent")
            if group == "sleep" and total_sleep and stage_pct.get("rem", 0) > 40:
                issue_codes.append("overnight_REM_over_40_percent")
            if group == "sleep" and not total_sleep:
                issue_codes.append("overnight_no_confirmed_sleep")
            if group == "sleep" and total_sleep and stage_pct.get("n3", 0) == 0:
                issue_codes.append("overnight_N3_zero")
            if (
                group == "sleep"
                and replay["physiological_evidence_coverage_percent"] < 80.0
            ):
                issue_codes.append(
                    "overnight_confirmed_stage_coverage_below_80_percent"
                )
            if group == "nap_recovery" and float(row["duration"]) > 90 * 60:
                issue_codes.append("nap_duration_over_90_minutes")
            if replay["forbidden_transition_count"]:
                issue_codes.append("forbidden_transition")
            if replay["ping_pong_count"]:
                issue_codes.append("ping_pong_within_60s")
            if replay["confirmed_transition_without_current_gate_count"]:
                issue_codes.append("confirmed_transition_without_current_gate")
            issue_codes.extend(replay_integrity_blockers(
                replay,
                raw_packet_count=int(raw_quality["packet_count"]),
            ))
            issue_codes.extend(replay_review_warnings(replay))
            review_warnings, promotion_blockers = split_issue_codes(issue_codes)
            details[row["session_id"]]["review_warnings"] = review_warnings
            details[row["session_id"]]["promotion_blockers"] = promotion_blockers
            first_sleep = next(
                (
                    item
                    for item in report_state_rows
                    if item["state"] in SLEEP_STAGES
                ),
                None,
            )
            if first_sleep is not None and not promotion_blockers:
                local_start = datetime.fromtimestamp(start, LOCAL_TIMEZONE)
                prior.append({
                    "session_id": row["session_id"],
                    "onset_minutes": max(0.0, (first_sleep["t"] - start) / 60.0),
                    "start_local_hour": local_start.hour + local_start.minute / 60.0,
                    "stage_pct": stage_pct,
                })
        sleep_onset_t = first_sleep_t
        environment = environment_summary(
            sessions, row["session_id"], start=start, sleep_onset=sleep_onset_t,
        )
        results.append({
            "session_id": row["session_id"],
            "email": row["username_key"],
            "start_time": row["start_time"],
            "duration_minutes": round(float(row["duration"]) / 60.0, 1),
            "previous_mode": {
                "resolved": resolved_mode,
                "group": group,
                "source": mode_context["mode_source"],
            },
            "target_duration_s": target_duration_s,
            "target_duration_source": mode_context[
                "target_duration_source"
            ],
            "shadow_mode": (
                dict((details.get(row["session_id"]) or {}).get("mode") or {})
                if replay else None
            ),
            "demographics": demographics,
            "quality": {
                "tier": tier,
                "timeline_paired_hr_rr_percent": round(paired_coverage * 100.0, 1),
                "raw_packet_coverage_percent": round(raw_coverage * 100.0, 1),
                "raw_paired_hr_rr_percent": round(
                    raw_quality["paired_vital_coverage"] * 100.0, 1
                ),
                "maximum_raw_packet_gap_s": round(
                    raw_quality["maximum_packet_gap_s"], 1
                ),
            },
            "old_score": old_score,
            "shadow_score": new_score,
            "shadow_engineering_score": (
                (details.get(row["session_id"], {}).get("quality") or {}).get(
                    "engineering_shadow_score"
                )
            ),
            "shadow_score_releasable": bool(
                (details.get(row["session_id"], {}).get("quality") or {}).get(
                    "score_releasable"
                )
            ),
            "shadow_confidence_percent": replay.get("confidence_percent") or {},
            "shadow_operational_status_counts": (
                replay.get("operational_status_counts") or {}
            ),
            "shadow_stage_pct_of_sleep": stage_pct,
            "shadow_stage_pct_of_occupied_evidence": (
                stage_pct_of_occupied_evidence
            ),
            "personal_behaviour_context": behaviour_context,
            "environment_context": environment,
            "review_warnings": (
                details.get(row["session_id"], {}).get("review_warnings") or []
            ),
            "promotion_blockers": (
                details.get(row["session_id"], {}).get("promotion_blockers") or []
            ),
            "replay": {
                key: value
                for key, value in replay.items()
                if key not in {
                    "evidence_rows", "state_rows", "status_rows", "sensor_rows",
                }
            },
        })

    promotion_eligible = [
        item for item in results
        if promotion_ready(details.get(item["session_id"], {}))
    ]
    score_releasable = [
        item for item in promotion_eligible
        if item["shadow_score_releasable"]
    ]
    score_withheld = [
        item for item in promotion_eligible
        if not item["shadow_score_releasable"]
    ]
    engineering_blockers = [] if promotion_eligible else [
        "no_sessions_with_promotable_derived_epochs"
    ]
    # Distribution/coverage flags stay visible for human review and public
    # score abstention, but they are not algorithm-invariant failures. Raw
    # replay cannot establish clinical/AASM accuracy against itself. It can,
    # however, support a separately labelled, versioned *wellness estimate*
    # promotion after explicit operator approval while preserving every raw
    # source row.
    clinical_replacement_blockers = list(engineering_blockers)
    clinical_replacement_blockers.append("no_independent_psg_or_aasm_reference_labels")
    source_root = Path(__file__).resolve().parent
    code_sha256 = {
        name: file_sha256(source_root / name) for name in REPLAY_SOURCE_FILES
    }
    combined_code_sha256 = hashlib.sha256(
        json.dumps(code_sha256, sort_keys=True).encode()
    ).hexdigest()
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=source_root,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        git_status = subprocess.run(
            ["git", "status", "--porcelain", "--", *REPLAY_SOURCE_FILES],
            cwd=source_root, check=True, capture_output=True, text=True,
        ).stdout.strip()
        code_worktree_dirty: bool | None = bool(git_status)
    except (OSError, subprocess.CalledProcessError):
        git_commit = None
        code_worktree_dirty = None
    input_sha256 = {
        "sessions_db": file_sha256(args.sessions_db),
        "bcg_db": file_sha256(args.bcg_db),
    }
    if args.profiles_file and args.profiles_file.exists():
        input_sha256["profiles_file"] = file_sha256(args.profiles_file)
    deterministic_result_sha256 = hashlib.sha256(
        json.dumps(results, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    promotion_payload_sha256 = hashlib.sha256(
        json.dumps(
            details, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    run_material = {
        "inputs": input_sha256,
        "code": combined_code_sha256,
        "parameters": {
            "minimum_minutes_exclusive": args.minimum_minutes,
            "start_local_date_inclusive": args.start_local_date,
            "timezone": str(LOCAL_TIMEZONE),
            "session_selection": selection_provenance,
        },
        "result": deterministic_result_sha256,
    }
    manifest = {
        "analysis_run_id": hashlib.sha256(
            json.dumps(run_material, sort_keys=True).encode()
        ).hexdigest()[:16],
        "generated_at": datetime.now().astimezone().isoformat(),
        "read_only": True,
        "historical_results_modified": False,
        "input_sha256": input_sha256,
        "code_provenance": {
            "source_sha256": code_sha256,
            "combined_sha256": combined_code_sha256,
            "git_commit": git_commit,
            "working_tree_dirty": code_worktree_dirty,
            "working_tree_state_verified": code_worktree_dirty is not None,
        },
        "intended_use": "ZEEP_wellness_engineering_validation_not_diagnosis",
        "versions": {
            "replay": SLEEP_HISTORY_BACKFILL_VERSION,
            "estimator": SLEEP_ESTIMATOR_VERSION,
            "evidence": SLEEP_EVIDENCE_VERSION,
            "baseline": ZEEP_SLEEP_BASELINE_VERSION,
            "transition": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
        },
        "cohort": {
            "minimum_minutes_exclusive": args.minimum_minutes,
            "start_local_date_inclusive": args.start_local_date,
            "start_utc_inclusive": cutoff_utc,
            "timezone": str(LOCAL_TIMEZONE),
            "older_sessions_excluded_from_learning": True,
            "raw_files_modified": False,
            "selection": selection_provenance,
            "sessions": len(results),
            "unique_emails": len(email_counts),
            "tier_counts": dict(tier_counts),
            "mode_counts": dict(mode_counts),
            "emails": dict(email_counts),
        },
        "acceptance": {
            "engineering_decision": (
                "NO_GO" if engineering_blockers else "PASS_WITH_LIMITATIONS"
            ),
            "engineering_blockers": engineering_blockers,
            "wellness_derived_promotion_decision": (
                "NO_GO" if engineering_blockers else "PASS_WITH_LIMITATIONS"
            ),
            "wellness_derived_promotion_blockers": engineering_blockers,
            "wellness_derived_promotion_eligible_sessions": len(
                promotion_eligible
            ),
            "wellness_derived_promotion_eligible_session_ids": [
                item["session_id"] for item in promotion_eligible
            ],
            "wellness_score_releasable_sessions": len(score_releasable),
            "wellness_score_releasable_session_ids": [
                item["session_id"] for item in score_releasable
            ],
            "wellness_score_withheld_sessions": len(score_withheld),
            "wellness_score_withheld_session_ids": [
                item["session_id"] for item in score_withheld
            ],
            "clinical_stage_replacement_decision": "NO_GO",
            "clinical_stage_replacement_blockers": clinical_replacement_blockers,
            "independent_reference_labels_available": False,
            "note": (
                "Engineering pass covers deterministic execution and invariants only. "
                "Approved promotion remains a versioned ZEEP Wellness estimate; "
                "clinical/AASM-equivalent replacement requires independent PSG labels."
            ),
            "quality_tier_is_advisory": True,
            "review_warnings_block_promotion": False,
            "quality_tier_A_definition": {
                "timeline_paired_hr_rr_min_percent": 90,
                "raw_paired_hr_rr_min_percent": 90,
                "raw_acquisition_min_percent": 95,
                "raw_packet_gap_must_be_less_than_s": SLEEP_CONTEXT_RESET_GAP_SECONDS,
            },
            "score_high_confidence_minimum_coverage_percent": 80,
            "coverage_is_admin_qa_context": True,
            "coverage_blocks_score": False,
        },
        "sessions": results,
    }
    manifest["deterministic_result_sha256"] = deterministic_result_sha256
    manifest["promotion_payload_sha256"] = promotion_payload_sha256
    if args.details_output:
        details_manifest = {
            "analysis_run_id": manifest["analysis_run_id"],
            "input_sha256": input_sha256,
            "code_provenance": manifest["code_provenance"],
            "versions": manifest["versions"],
            "cohort": manifest["cohort"],
            "acceptance": manifest["acceptance"],
            "deterministic_result_sha256": deterministic_result_sha256,
            "promotion_payload_sha256": promotion_payload_sha256,
            "sessions": details,
            "derived_only": True,
            "raw_files_modified": False,
        }
        args.details_output.parent.mkdir(parents=True, exist_ok=True)
        details_bytes = json.dumps(
            details_manifest, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        private_write_bytes(args.details_output, details_bytes)
        manifest["promotion_details_sha256"] = hashlib.sha256(details_bytes).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    private_write_bytes(
        args.output,
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    print(json.dumps({"output": str(args.output), **manifest["cohort"], **manifest["acceptance"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
