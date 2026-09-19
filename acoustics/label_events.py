"""Validate and group provisional firmware DSP labels into timeline events."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

LABELS = {
    "quiet": ("ค่อนข้างเงียบ", "quiet"),
    "steady_equipment_like": ("เสียงต่อเนื่องคล้ายอุปกรณ์", "equipment_like"),
    "speech_like": ("คล้ายเสียงพูด", "human_sound_like"),
    "snore_like": ("คล้ายเสียงกรน", "human_sound_like"),
    "impact_like": ("คล้ายเสียงกระแทก", "impact"),
}
MIN_CONFIDENCE = 0.35


def detect_label_events(
    samples: Sequence[Mapping[str, Any]],
    *,
    cadence_s: float,
) -> list[dict[str, Any]]:
    """Collapse consecutive labels without inventing labels from scalar dBA."""
    rows = _valid_rows(samples, cadence_s=cadence_s)
    groups: list[list[dict[str, Any]]] = []
    active: list[dict[str, Any]] = []
    for row in rows:
        contiguous = (
            not active
            or row["t"] - active[-1]["t"]
            <= max(row["cadence_s"], active[-1]["cadence_s"]) * 1.8
        )
        same_label = active and row["label"] == active[-1]["label"]
        if active and (not contiguous or not same_label):
            groups.append(active)
            active = []
        active.append(row)
    if active:
        groups.append(active)
    return [_event(group) for group in groups if group[0]["label"] != "quiet"]


def latest_classification(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the newest trusted shadow label for the Admin status card."""
    rows = _valid_rows(samples, cadence_s=10.0)
    if not rows:
        return {
            "state": "insufficient_input",
            "label": "unknown",
            "display_name": "ยังจำแนกเสียงไม่ได้",
            "confidence": None,
            "confidence_band": "unavailable",
            "sound_source": "unknown",
            "human_sound": "not_evaluated",
        }
    row = rows[-1]
    return {
        "state": "provisional",
        "label": row["label"],
        "display_name": LABELS[row["label"]][0],
        "confidence": round(row["confidence"], 3),
        "confidence_band": _confidence_band(row["confidence"]),
        "classifier_version": row["classifier_version"],
        "window_sequence": row["window_sequence"],
        "sound_source": (
            row["label"]
            if LABELS[row["label"]][1] in {"equipment_like", "impact"}
            else "unknown"
        ),
        "human_sound": (
            row["label"]
            if LABELS[row["label"]][1] == "human_sound_like"
            else "not_evaluated"
        ),
    }


def _valid_rows(
    samples: Sequence[Mapping[str, Any]],
    *,
    cadence_s: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_sequences: set[tuple[str, int]] = set()
    for sample in samples:
        timestamp = _number(sample.get("t"))
        confidence = _number(sample.get("acoustic_confidence"))
        label = str(sample.get("acoustic_label") or "").strip().lower()
        state = str(sample.get("acoustic_state") or "").strip().lower()
        version = str(sample.get("acoustic_classifier_version") or "").strip()
        sequence = _integer(sample.get("acoustic_window_sequence"))
        if (
            timestamp is None
            or label not in LABELS
            or state != "provisional"
            or confidence is None
            or confidence < MIN_CONFIDENCE
            or not version
        ):
            continue
        identity = (version, sequence) if sequence is not None else None
        if identity is not None and identity in seen_sequences:
            continue
        if identity is not None:
            seen_sequences.add(identity)
        interval = _number(sample.get("sample_interval_s")) or cadence_s
        rows.append(
            {
                "t": timestamp,
                "cadence_s": max(1.0, interval),
                "label": label,
                "confidence": min(1.0, confidence),
                "event_detected": bool(sample.get("acoustic_event_detected")),
                "classifier_version": version,
                "window_sequence": sequence,
            }
        )
    return sorted(rows, key=lambda row: row["t"])


def _event(group: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    first, last = group[0], group[-1]
    label = str(first["label"])
    confidence = sum(float(row["confidence"]) for row in group) / len(group)
    end = float(last["t"]) + float(last["cadence_s"])
    detected = any(bool(row["event_detected"]) for row in group)
    return {
        "id": f"dsp-{label}-{int(float(first['t']))}",
        "key": label,
        "category": "dsp_label",
        "label": LABELS[label][0],
        "label_group": LABELS[label][1],
        "start_epoch_s": round(float(first["t"]), 1),
        "end_epoch_s": round(end, 1),
        "duration_s": round(end - float(first["t"]), 1),
        "confidence": round(confidence, 3),
        "confidence_band": _confidence_band(confidence),
        "evidence_quality": "firmware_dsp_shadow",
        "event_detected": detected,
        "classifier_version": first["classifier_version"],
        "window_count": len(group),
        "contributes_to_primary_score": False,
    }


def _confidence_band(value: float) -> str:
    if value >= 0.8:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"


def _number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None and number >= 0 else None
