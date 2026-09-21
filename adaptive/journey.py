"""Read-only, versioned sensor/control timeline. No source inference or writes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from acoustics.label_events import detect_label_events
from common.numbers import number_in_range
from sessions.sleep_event_data import event_value, parse_timestamp

VERSION = "zeep.sensor-journey.v1"
# Display/event sensitivity, not health limits or score thresholds.
METRICS = {
    "temperature": ("อุณหภูมิ", "°C", -40, 125, 1.0),
    "humidity": ("ความชื้น", "%RH", 0, 100, 5.0),
    "co2": ("CO₂", "ppm", 400, 10000, 150.0),
    "pm2_5": ("PM2.5", "µg/m³", 0, 1000, 10.0),
    "voc_index": ("VOC Index", "", 1, 500, 30.0),
    "lux": ("แสง", "lux", 0, 83865.6, 5.0),
    "sound": ("เสียง", "dBA", 30, 130, 5.0),
    "heart_rate": ("ชีพจร", "ครั้ง/นาที", 25, 220, 10.0),
    "respiration_rate": ("การหายใจ", "ครั้ง/นาที", 2, 60, 3.0),
}
COMMAND_NAMES = {
    "aircon_command": "คำสั่งแอร์",
    "bed_command": "คำสั่งปรับเตียง",
    "output": "คำสั่งอุปกรณ์",
    "pulse": "คำสั่งกลิ่นหรือไอน้ำ",
    "door": "คำสั่งประตู",
    "music": "คำสั่งเสียงเพลง",
}
COMMAND_FIELDS = (
    "command",
    "requested_command",
    "action",
    "name",
    "on",
    "volume",
    "desired_temperature_c",
    "fan_level",
)


def normalize_samples(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep valid values, deduplicate timestamps and never impute missing data."""
    samples = {}
    for row in rows:
        epoch = parse_timestamp(row.get("timestamp"))
        if epoch is None:
            continue
        values = {
            key: number_in_range(row.get(key), spec[2], spec[3])
            for key, spec in METRICS.items()
        }
        samples[epoch] = {
            "t": epoch,
            **values,
            "bed_status": row.get("bed_status"),
            **{
                key: row.get(key)
                for key in (
                    "acoustic_label",
                    "acoustic_state",
                    "acoustic_confidence",
                    "acoustic_classifier_version",
                    "acoustic_window_sequence",
                    "acoustic_event_detected",
                )
            },
        }
    return [samples[key] for key in sorted(samples)]


def command_events(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project only known control types; legacy events have unknown actor."""
    result = []
    for row in rows:
        kind = row.get("type")
        epoch = parse_timestamp(row.get("timestamp"))
        if kind not in COMMAND_NAMES or epoch is None:
            continue
        value = event_value(row)
        result.append(
            {
                "id": f"command-{row.get('id', epoch)}",
                "t": epoch,
                "kind": "command",
                "source": kind,
                "label": COMMAND_NAMES[kind],
                "values": {key: value[key] for key in COMMAND_FIELDS if key in value},
                "actor": "unknown",
                "physical_confirmation": False,
                "meaning": "บันทึกคำสั่ง ไม่ใช่การยืนยันสถานะอุปกรณ์จริง",
            }
        )
    return sorted(result, key=lambda item: (item["t"], item["id"]))


def _changes(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for before, after in zip(samples, samples[1:], strict=False):
        if after["t"] - before["t"] > 30:
            result.append(
                {
                    "id": f"gap-{after['t']}",
                    "t": after["t"],
                    "kind": "gap",
                    "source": "sensor_frame",
                    "label": "ข้อมูลขาดช่วง",
                    "start_epoch_s": before["t"],
                    "end_epoch_s": after["t"],
                }
            )
            continue
        for key, spec in METRICS.items():
            left, right = before[key], after[key]
            if left is None or right is None or abs(right - left) < spec[4]:
                continue
            result.append(
                {
                    "id": f"sensor-{key}-{after['t']}",
                    "t": after["t"],
                    "kind": "sensor_change",
                    "source": key,
                    "label": f"{spec[0]}เปลี่ยน",
                    "before": left,
                    "after": right,
                    "delta": round(right - left, 2),
                    "unit": spec[1],
                }
            )
        if after.get("bed_status") != before.get("bed_status"):
            result.append(
                {
                    "id": f"bed-{after['t']}",
                    "t": after["t"],
                    "kind": "bed",
                    "source": "lsm800t",
                    "label": "สถานะเตียงเปลี่ยน",
                    "before": before.get("bed_status"),
                    "after": after.get("bed_status"),
                }
            )
    return result


def build_journey(
    rows: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    *,
    include_acoustic: bool = True,
) -> dict[str, Any]:
    """Merge all available sensor channels and commands on a UTC time axis."""
    samples = normalize_samples(rows)
    items = _changes(samples) + command_events(events)
    acoustic_events = (
        detect_label_events(samples, cadence_s=10) if include_acoustic else []
    )
    for event in acoustic_events:
        items.append(
            {
                **event,
                "t": event["start_epoch_s"],
                "kind": "acoustic",
                "source": "sph0645",
                "provisional": True,
            }
        )
    items.sort(key=lambda item: (item["t"], item["id"]))
    # Bound browser payload without changing event calculation or source rows.
    stride = max(1, (len(samples) + 719) // 720)
    return {
        "version": VERSION,
        "time_basis": "unix_utc",
        "channels": [
            {
                "key": key,
                "label": spec[0],
                "unit": spec[1],
                "available": any(row[key] is not None for row in samples),
            }
            for key, spec in METRICS.items()
        ],
        "points": samples[::stride],
        "point_stride": stride,
        "samples_used": len(samples),
        "events": items[-400:],
        "events_total": len(items),
        "events_truncated": len(items) > 400,
        "interpretation": "เหตุการณ์เกิดใกล้กันไม่ได้ยืนยันว่าเป็นสาเหตุของกันและกัน",
        "raw_modified": False,
    }
