"""Read-only quality audit for historical Sleep State replay candidates."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sleep_signal_features import (
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    arousal_proxy_evidence,
    filter_vital_values,
)
from sleep_system_policy import (
    SLEEP_PROHIBITED_TRANSITIONS,
    ZEEP_SLEEP_STATES,
)

STAGES = ZEEP_SLEEP_STATES


def count_states(values: list[dict[str, Any]]) -> dict[str, int]:
    """Count canonical Sleep State labels in detached replay values."""
    counts = Counter(value.get("state") for value in values)
    return {stage: counts.get(stage, 0) for stage in STAGES}


def audit_replayed_sequence(
    events: list[tuple[str, dict[str, Any]]],
    movement_threshold: float = 0.15,
) -> dict[str, Any]:
    """Build the mandatory read-only quality gate for a replay candidate."""
    sequence = [
        (timestamp, str(value.get("state") or "").lower(), value)
        for timestamp, value in events
        if str(value.get("state") or "").lower() in STAGES
    ]
    transitions = _audit_transitions(sequence, movement_threshold)
    boundaries = _audit_boundaries(sequence)
    edge_counts, edge_examples = _audit_edge_cases(sequence)
    missing_wake_proxy = [
        item
        for item in transitions["sleep_to_wake"]
        if not item["any_same_window_proxy"]
    ]
    failures = _gate_failures(
        sequence,
        transitions["prohibited"],
        boundaries,
        missing_wake_proxy,
        edge_counts,
    )
    warnings = _audit_warnings(transitions["sleep_to_wake"], edge_counts)
    return _audit_report(
        sequence=sequence,
        transitions=transitions,
        boundaries=boundaries,
        edge_counts=edge_counts,
        edge_examples=edge_examples,
        missing_wake_proxy=missing_wake_proxy,
        warnings=warnings,
        failures=failures,
    )


def _audit_transitions(
    sequence: list[tuple[str, str, dict[str, Any]]],
    movement_threshold: float,
) -> dict[str, Any]:
    matrix = {source: {target: 0 for target in STAGES} for source in STAGES}
    changes = {source: {target: 0 for target in STAGES} for source in STAGES}
    prohibited: list[dict[str, Any]] = []
    sleep_to_wake: list[dict[str, Any]] = []
    for previous, current in zip(sequence, sequence[1:], strict=False):
        previous_at, source, _ = previous
        current_at, target, value = current
        matrix[source][target] += 1
        if source != target:
            changes[source][target] += 1
        if (source, target) in SLEEP_PROHIBITED_TRANSITIONS:
            prohibited.append(
                {
                    "from": source,
                    "to": target,
                    "from_timestamp": previous_at,
                    "to_timestamp": current_at,
                }
            )
        if source in {"n2", "n3"} and target == "wake":
            sleep_to_wake.append(
                _wake_evidence(source, current_at, value, movement_threshold)
            )
    return {
        "matrix": matrix,
        "changes": changes,
        "prohibited": prohibited,
        "sleep_to_wake": sleep_to_wake,
    }


def _wake_evidence(
    source: str,
    timestamp: str,
    value: dict[str, Any],
    movement_threshold: float,
) -> dict[str, Any]:
    metrics = dict(value.get("metrics") or {})
    proxy = metrics.get("arousal_proxy")
    if not isinstance(proxy, dict):
        proxy = arousal_proxy_evidence(metrics, movement_threshold)
    evidence = list(proxy.get("evidence") or [])
    return {
        "from": source,
        "timestamp": timestamp,
        "amplitude_shift_aligned": "bcg_amplitude_shift" in evidence,
        "wake_motion_aligned": "wake_compatible_motion" in evidence,
        "any_same_window_proxy": bool(proxy.get("present")),
        "evidence": evidence,
    }


def _audit_boundaries(
    sequence: list[tuple[str, str, dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    one_epoch = []
    for index in range(len(sequence) - 2):
        first, middle, last = sequence[index : index + 3]
        if first[1] == last[1] and first[1] != middle[1]:
            one_epoch.append(
                {
                    "pattern": f"{first[1]}->{middle[1]}->{last[1]}",
                    "timestamp": middle[0],
                }
            )
    two_epoch = []
    for index in range(len(sequence) - 3):
        first, middle_a, middle_b, last = sequence[index : index + 4]
        if (
            first[1] == last[1]
            and middle_a[1] == middle_b[1]
            and first[1] != middle_a[1]
        ):
            two_epoch.append(
                {
                    "pattern": (f"{first[1]}->{middle_a[1]}->{middle_b[1]}->{last[1]}"),
                    "timestamp": middle_a[0],
                }
            )
    return {
        "one_epoch": one_epoch,
        "two_epoch": two_epoch,
        "n2_rem_one": _matching(one_epoch, "n2->rem->n2", "rem->n2->rem"),
        "n2_rem_two": _matching(two_epoch, "n2->rem->rem->n2", "rem->n2->n2->rem"),
        "n3_rem_one": _matching(one_epoch, "n3->rem->n3", "rem->n3->rem"),
        "n3_rem_two": _matching(two_epoch, "n3->rem->rem->n3", "rem->n3->n3->rem"),
    }


def _matching(
    patterns: list[dict[str, Any]],
    *accepted: str,
) -> list[dict[str, Any]]:
    return [item for item in patterns if item["pattern"] in accepted]


def _audit_edge_cases(
    sequence: list[tuple[str, str, dict[str, Any]]],
) -> tuple[Counter[str], list[dict[str, Any]]]:
    counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for timestamp, _, value in sequence:
        metrics = dict(value.get("metrics") or {})
        issues = []
        if not filter_vital_values([metrics.get("mean_hr")], HR_SANITY_RANGE_BPM):
            issues.append("invalid_or_missing_mean_hr")
        if not filter_vital_values([metrics.get("mean_rr")], RR_SANITY_RANGE_PER_MIN):
            issues.append("invalid_or_missing_mean_rr")
        counts.update(issues)
        if issues and len(examples) < 10:
            examples.append({"timestamp": timestamp, "issues": issues})
        if not metrics.get("waveform_available"):
            counts["waveform_unavailable"] += 1
        if metrics.get("bcg_baseline_drift_flag"):
            counts["bcg_baseline_drift_flag"] += 1
        counts["invalid_hr_packets"] += int(metrics.get("invalid_hr_packets") or 0)
        counts["invalid_rr_packets"] += int(metrics.get("invalid_rr_packets") or 0)
    return counts, examples


def _gate_failures(
    sequence: list[tuple[str, str, dict[str, Any]]],
    prohibited: list[dict[str, Any]],
    boundaries: dict[str, list[dict[str, Any]]],
    missing_wake_proxy: list[dict[str, Any]],
    edge_counts: Counter[str],
) -> list[str]:
    failures = []
    if not sequence or sequence[0][1] != "wake":
        failures.append("first_emitted_state_must_be_wake")
    if prohibited:
        failures.append("prohibited_state_transition")
    if any(boundaries[key] for key in _REM_BOUNDARY_KEYS):
        failures.append("rem_boundary_ping_pong")
    if missing_wake_proxy:
        failures.append("sleep_to_wake_without_same_window_proxy")
    if (
        edge_counts["invalid_or_missing_mean_hr"]
        or edge_counts["invalid_or_missing_mean_rr"]
    ):
        failures.append("invalid_vitals_entered_state_machine")
    return failures


_REM_BOUNDARY_KEYS = ("n2_rem_one", "n2_rem_two", "n3_rem_one", "n3_rem_two")


def _audit_warnings(
    sleep_to_wake: list[dict[str, Any]],
    edge_counts: Counter[str],
) -> list[str]:
    warnings = []
    if any(not item["amplitude_shift_aligned"] for item in sleep_to_wake):
        warnings.append(
            "Some sleep-to-Wake transitions use corroborated movement evidence "
            "without a BCG amplitude shift; this is allowed because the BCG "
            "proxy is not an AASM cortical-arousal measurement."
        )
    if edge_counts["waveform_unavailable"]:
        warnings.append("Some rounds lack enough raw waveform; confidence remains low.")
    if edge_counts["bcg_baseline_drift_flag"]:
        warnings.append(
            "Some detrended BCG windows carry a baseline-drift quality flag."
        )
    return warnings


def _audit_report(
    *,
    sequence: list[tuple[str, str, dict[str, Any]]],
    transitions: dict[str, Any],
    boundaries: dict[str, list[dict[str, Any]]],
    edge_counts: Counter[str],
    edge_examples: list[dict[str, Any]],
    missing_wake_proxy: list[dict[str, Any]],
    warnings: list[str],
    failures: list[str],
) -> dict[str, Any]:
    changes = transitions["changes"]
    sleep_to_wake = transitions["sleep_to_wake"]
    boundary_examples = sum(
        (boundaries[key] for key in _REM_BOUNDARY_KEYS),
        [],
    )
    return {
        "rounds": len(sequence),
        "first_state": sequence[0][1] if sequence else None,
        "state_transition_matrix": transitions["matrix"],
        "state_change_matrix": changes,
        "transition_verification": {
            "prohibited_count": len(transitions["prohibited"]),
            "n3_to_rem": changes["n3"]["rem"],
            "wake_to_n3": changes["wake"]["n3"],
            "examples": transitions["prohibited"][:10],
        },
        "arousal_proxy_validation": {
            "sleep_to_wake_count": len(sleep_to_wake),
            "amplitude_shift_aligned": _count_true(
                sleep_to_wake, "amplitude_shift_aligned"
            ),
            "wake_motion_aligned": _count_true(sleep_to_wake, "wake_motion_aligned"),
            "any_same_window_proxy": _count_true(
                sleep_to_wake, "any_same_window_proxy"
            ),
            "missing_proxy_count": len(missing_wake_proxy),
            "missing_examples": missing_wake_proxy[:10],
            "cortical_arousal_claim": False,
        },
        "boundary_packet_smoothness": {
            "all_one_epoch_aba": len(boundaries["one_epoch"]),
            "n3_rem_one_epoch_ping_pong": len(boundaries["n3_rem_one"]),
            "n3_rem_two_epoch_ping_pong": len(boundaries["n3_rem_two"]),
            "all_two_epoch_abba": len(boundaries["two_epoch"]),
            "n2_rem_one_epoch_ping_pong": len(boundaries["n2_rem_one"]),
            "n2_rem_two_epoch_ping_pong": len(boundaries["n2_rem_two"]),
            "examples": boundary_examples[:10],
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
        "apply_gate": {"passed": not failures, "failures": failures},
    }


def _count_true(values: list[dict[str, Any]], key: str) -> int:
    return sum(bool(item[key]) for item in values)
