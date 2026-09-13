"""Shared conversion of persisted Timeline rows into report Sensor samples."""

from __future__ import annotations

import sqlite3
from typing import Any

from sleep_signal_features import debounced_bed_status_labels


def timeline_projection(connection: sqlite3.Connection) -> str:
    """Read current and legacy Timeline schemas without migrating Raw data."""
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(timeline)")
    }
    required = (
        "timestamp",
        "temperature",
        "humidity",
        "co2",
        "lux",
        "sound",
        "heart_rate",
        "respiration_rate",
        "bed_status",
    )
    missing = [column for column in required if column not in columns]
    if missing:
        raise ValueError(
            f"timeline schema missing required columns: {missing}"
        )
    optional = (
        "pm2_5" if "pm2_5" in columns else "NULL AS pm2_5",
        (
            "voc_index"
            if "voc_index" in columns
            else "NULL AS voc_index"
        ),
        (
            "respiratory_evidence_valid"
            if "respiratory_evidence_valid" in columns
            else "NULL AS respiratory_evidence_valid"
        ),
        (
            "respiratory_evidence_reason"
            if "respiratory_evidence_reason" in columns
            else "NULL AS respiratory_evidence_reason"
        ),
    )
    return ",".join((*required, *optional))


def sensor_samples(
    timeline: list[sqlite3.Row],
    *,
    timestamp_parser: Any,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    """Translate immutable rows once for Shadow, Rescore and reports."""
    canonical_labels = debounced_bed_status_labels(
        [row["bed_status"] for row in timeline]
    )
    raw_counts: dict[str, int] = {}
    canonical_counts: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    for row, canonical_bed in zip(
        timeline,
        canonical_labels,
    ):
        raw_bed = str(row["bed_status"] or "")
        if raw_bed:
            raw_counts[raw_bed] = raw_counts.get(raw_bed, 0) + 1
        if canonical_bed:
            canonical_counts[canonical_bed] = (
                canonical_counts.get(canonical_bed, 0) + 1
            )
        samples.append({
            "t": timestamp_parser(row["timestamp"]),
            "temp": row["temperature"],
            "hum": row["humidity"],
            "co2": row["co2"],
            "lux": row["lux"],
            "dba": row["sound"],
            "hr": row["heart_rate"],
            "rr": row["respiration_rate"],
            "bed": canonical_bed,
            "pm2_5": row["pm2_5"],
            "voc": row["voc_index"],
            "respiratory_evidence_valid": (
                row["respiratory_evidence_valid"] == 1
                if row["respiratory_evidence_valid"] is not None
                else None
            ),
            "respiratory_evidence_reason": row[
                "respiratory_evidence_reason"
            ],
        })
    return samples, raw_counts, canonical_counts
