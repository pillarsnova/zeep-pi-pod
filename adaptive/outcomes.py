"""Descriptive before/after windows, never a causal treatment-effect claim."""

from __future__ import annotations

import math
import statistics
from typing import Any

from adaptive.journey import METRICS

WINDOW_S = 300
SETTLE_S = 60
MIN_COVERAGE = 0.8


def comfort_direction(before: float | None, after: float | None, target: dict) -> str:
    """Describe distance to a reported comfort band, not a health benefit."""
    if before is None or after is None or not target:
        return "not_compared"
    low, high = target["low"], target["high"]
    before_distance = max(low - before, before - high, 0)
    after_distance = max(low - after, after - high, 0)
    if after_distance < before_distance:
        return "toward_reference"
    if after_distance > before_distance:
        return "away_from_reference"
    return "within_reference" if after_distance == 0 else "unchanged_distance"


def window_summary(
    samples: list[dict[str, Any]],
    key: str,
    start: float,
    end: float,
) -> dict[str, Any]:
    """Use occupied 10-second bins; duplicates cannot inflate coverage."""
    bins = {}
    for row in samples:
        if start <= row["t"] < end and row.get(key) is not None:
            bins[int((row["t"] - start) // 10)] = row[key]
    values = list(bins.values())
    if not values:
        value = None
    elif key == "sound":
        value = 10 * math.log10(statistics.mean(10 ** (v / 10) for v in values))
    else:
        value = statistics.median(values)
    expected = max(1, math.ceil((end - start) / 10))
    return {
        "value": round(value, 2) if value is not None else None,
        "coverage": min(1.0, len(values) / expected),
        "samples": len(values),
        "method": "energy_average" if key == "sound" else "median",
    }


def compare_commands(
    samples: list[dict[str, Any]],
    commands: list[dict[str, Any]],
    *,
    now: float,
    reference: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Compare all channels, flag incomplete/overlapping windows explicitly."""
    results = []
    for command in commands[-30:]:
        epoch = command["t"]
        start, after = epoch - WINDOW_S, epoch + SETTLE_S
        end = after + WINDOW_S
        overlaps = [
            other["id"]
            for other in commands
            if other["id"] != command["id"] and start <= other["t"] < end
        ]
        status = "waiting" if now < end else "confounded" if overlaps else "descriptive"
        pre_samples = [row for row in samples if start <= row["t"] < epoch]
        post_samples = [row for row in samples if after <= row["t"] < end]
        changes = []
        for key, spec in METRICS.items():
            pre = window_summary(pre_samples, key, start, epoch)
            post = window_summary(post_samples, key, after, end)
            usable = (
                status != "waiting"
                and min(pre["coverage"], post["coverage"]) >= MIN_COVERAGE
            )
            delta = round(post["value"] - pre["value"], 2) if usable else None
            changes.append(
                {
                    "metric": key,
                    "label": spec[0],
                    "unit": spec[1],
                    "before": pre,
                    "after": post,
                    "delta": delta,
                    "status": "observed_change" if usable else "insufficient_data",
                    "direction": (
                        "lower" if delta < 0 else "higher" if delta > 0 else "unchanged"
                    )
                    if delta is not None
                    else None,
                    "benefit_confirmed": False,
                    "comfort_direction": comfort_direction(
                        pre["value"] if usable else None,
                        post["value"] if usable else None,
                        ((reference or {}).get("ranges") or {}).get(key, {}),
                    ),
                }
            )
        results.append(
            {
                "command_id": command["id"],
                "label": command["label"],
                "t": epoch,
                "status": status,
                "pre_window_s": WINDOW_S,
                "settle_s": SETTLE_S,
                "post_window_s": WINDOW_S,
                "overlapping_commands": overlaps,
                "metrics": changes,
                "causal_claim": False,
                "message": (
                    "รอข้อมูลหลังคำสั่ง"
                    if status == "waiting"
                    else "มีคำสั่งอื่นในช่วงเดียวกัน แยกผลของคำสั่งนี้ไม่ได้"
                    if overlaps
                    else "เปรียบเทียบค่าก่อน–หลัง ยังไม่ยืนยันสาเหตุ"
                ),
            }
        )
    return results
