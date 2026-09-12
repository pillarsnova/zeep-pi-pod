"""Build the compact, privacy-bounded ZEEP account ingest payload.

This module is intentionally pure.  The composition root supplies deployment
configuration, while this code owns stage encoding and reconciliation rules.
"""

from __future__ import annotations

from typing import Any

from sleep_system_policy import (
    ZEEP_OFF_BED_DATA_STATUSES,
    ZEEP_OFF_BED_LABELS,
)

from .cadence import sample_interval_seconds

STAGE_INDEX = {
    "wake": 0,
    "n1": 1,
    "n2": 2,
    "nrem_light": 2,
    "n3": 3,
    "nrem_deep": 3,
    "rem": 4,
    "off_bed": 0,
}
STAGE_NAME = {
    "wake": "wake",
    "n1": "n1",
    "n2": "n2",
    "nrem_light": "n2",
    "n3": "n3",
    "nrem_deep": "n3",
    "rem": "rem",
    "off_bed": "off_bed",
}
ENVIRONMENT_KEYS = {
    "temperature": "temperature",
    "humidity": "humidity",
    "co2": "co2",
    "light": "lux",
    "sound": "noise",
    "pm25": "pm25",
    "voc": "voc",
}


def sample_off_bed(sample: dict[str, Any]) -> bool:
    """Recognise operational occupancy without creating Sleep Stage W."""
    data_status = str(sample.get("sleep_data_status") or "").lower()
    bed = str(sample.get("bed") or "").strip().lower()
    return bool(
        data_status in ZEEP_OFF_BED_DATA_STATUSES
        or bed in ZEEP_OFF_BED_LABELS
    )


def build_stage_runs(
    samples: list[dict[str, Any]],
    epoch_seconds: float,
) -> tuple[list[dict[str, Any]], list[dict[str, int]]]:
    """Run-length encode score-eligible stages and visible bed exits."""
    runs: list[tuple[str, int]] = []
    current: str | None = None
    length = 0
    for sample in samples:
        stage = "off_bed" if sample_off_bed(sample) else sample.get("sleep")
        if stage not in STAGE_INDEX:
            continue
        if stage != "off_bed" and (
            sample.get("sleep_score_eligible") is False
            or bool(sample.get("sleep_provisional"))
        ):
            continue
        if stage == current:
            length += 1
            continue
        if current is not None and length:
            runs.append((current, length))
        current, length = str(stage), 1
    if current is not None and length:
        runs.append((current, length))

    segments = [
        {
            "stage": STAGE_INDEX[state],
            "stage_name": STAGE_NAME[state],
            "epochs": count,
            "minutes": round(count * epoch_seconds / 60.0, 1),
        }
        for state, count in runs
    ]
    hypnogram = [
        {"s": STAGE_INDEX[state], "n": count} for state, count in runs
    ]
    return segments, hypnogram


def build_environment(report_environment: Any) -> dict[str, Any]:
    """Re-key report criteria to fields promoted by the account backend."""
    result: dict[str, Any] = {}
    for metric in report_environment or []:
        if not isinstance(metric, dict):
            continue
        target = ENVIRONMENT_KEYS.get(metric.get("key"))
        if target:
            result[target] = dict(metric, avg=metric.get("average"))
    return result


def _current_report_reconciles(
    report: dict[str, Any],
    quality: dict[str, Any],
    current_report_version: str,
) -> bool:
    if report.get("version") != current_report_version:
        return True
    sleep = report.get("sleep") or {}
    accounting = sleep.get("classification_accounting") or {}
    quality_seconds = quality.get("actual_scored_s")
    report_seconds = sleep.get("actual_scored_s")
    return bool(
        accounting.get("score_stage_total_reconciles") is True
        and isinstance(quality_seconds, (int, float))
        and isinstance(report_seconds, (int, float))
        and abs(float(quality_seconds) - float(report_seconds)) <= 0.11
    )


def _stage_minutes(stages: dict[str, Any], state: str) -> float | None:
    entry = stages.get(state) or {}
    value = entry.get("score_eligible_duration_s")
    if value is None:
        value = entry.get("duration_s")
    return round(value / 60.0, 1) if isinstance(value, (int, float)) else None


def _stage_percentage(stages: dict[str, Any], state: str) -> float | None:
    entry = stages.get(state) or {}
    value = entry.get("pct_score_eligible")
    if value is None:
        value = entry.get("pct_scored")
    return value if isinstance(value, (int, float)) else None


def _minutes(value: Any) -> float | None:
    return round(value / 60.0, 1) if isinstance(value, (int, float)) else None


def _vitals(record: dict[str, Any], key: str) -> dict[str, Any]:
    series = ((record.get("summary") or {}).get(key)) or {}
    return {name: series[name] for name in ("avg", "min", "max") if name in series}


def _compact_result(
    record: dict[str, Any],
    report: dict[str, Any],
    quality: dict[str, Any],
    stages: dict[str, Any],
    segments: list[dict[str, Any]],
    hypnogram: list[dict[str, int]],
    epoch_seconds: int,
) -> dict[str, Any]:
    sleep = report.get("sleep") or {}
    score_epochs = sum(
        int(segment["epochs"])
        for segment in segments
        if segment.get("stage_name") != "off_bed"
    )
    result: dict[str, Any] = {
        "sleep_score": quality.get("score"),
        "sleep_efficiency": quality.get("sleep_efficiency_pct"),
        "rest_mode": record.get("rest_mode"),
        "target_duration_s": record.get("target_duration_s"),
        "epoch_seconds": epoch_seconds,
        "total_epochs": score_epochs,
        "total_scored_minutes": _minutes(sleep.get("actual_scored_s")),
        "total_sleep_minutes": _minutes(sleep.get("estimated_sleep_s")),
        "heart_rate": _vitals(record, "heart_rate_bpm"),
        "respiration_rate": _vitals(record, "respiration_rate"),
        "start": record["started_at_utc"],
        "segments": segments,
        "total_segments": len(segments),
        "hypnogram": hypnogram,
        "environment": build_environment(report.get("environment")),
    }
    for state in ("wake", "n1", "n2", "n3", "rem"):
        result[f"{state}_minutes"] = _stage_minutes(stages, state)
        result[f"{state}_percent"] = _stage_percentage(stages, state)
    return result


def build_ingest_payload(
    record: dict[str, Any],
    report_samples: list[dict[str, Any]],
    *,
    api_key: str | None,
    device_id: str | None,
    timezone_name: str | None,
    current_report_version: str,
) -> dict[str, Any] | None:
    """Return a reconciled account-backend body, or ``None`` when ineligible."""
    public_id = record.get("zeep_public_id")
    report = record.get("session_report")
    quality = record.get("sleep_quality")
    if not (api_key and device_id and public_id):
        return None
    if not isinstance(report, dict) or not isinstance(quality, dict):
        return None
    if not record.get("started_at_utc") or not record.get("ended_at_utc"):
        return None
    stages = {
        str(entry.get("state")): entry
        for entry in report.get("stages") or []
        if isinstance(entry, dict)
    }
    if not stages or not _current_report_reconciles(
        report, quality, current_report_version
    ):
        return None

    interval = sample_interval_seconds(record.get("sample_interval_s"))
    sent_interval = max(1, int(round(interval)))
    segments, hypnogram = build_stage_runs(report_samples, interval)
    body: dict[str, Any] = {
        "userPublicId": public_id,
        "deviceId": device_id,
        "externalSessionId": record["session_id"],
        "startedAt": record["started_at_utc"],
        "endedAt": record["ended_at_utc"],
        "record": _compact_result(
            record,
            report,
            quality,
            stages,
            segments,
            hypnogram,
            sent_interval,
        ),
    }
    if timezone_name:
        body["timezone"] = timezone_name
    return body
