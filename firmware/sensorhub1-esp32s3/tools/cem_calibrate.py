#!/usr/bin/env python3
"""Collect paired 10-second SPH0645/CEM readings and issue a gate result."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import statistics
import time
from datetime import datetime, timezone
from typing import Any


TARGET_LEVELS = (35, 45, 55, 65)


def read_firmware_window(port: Any) -> dict:
    deadline = time.monotonic() + 45.0
    last_invalid_reason = "no_packet"
    while time.monotonic() < deadline:
        raw = port.readline().decode("utf-8", errors="replace").strip()
        if not raw:
            continue
        try:
            packet = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if packet.get("event") != "environment":
            continue
        if packet.get("sound_window_ms") != 10_000:
            last_invalid_reason = "window_is_not_10_seconds"
            continue
        if packet.get("sound_valid") is not True:
            last_invalid_reason = str(
                packet.get("sound_invalid_reason", "firmware_invalid")
            )
            continue
        if packet.get("sound_weighting") != "A":
            last_invalid_reason = "weighting_is_not_A"
            continue
        if str(packet.get("sound_metric", "")).upper() != "LAEQ":
            last_invalid_reason = "metric_is_not_LAeq"
            continue
        if not isinstance(packet.get("sound_laeq_dba"), (int, float)):
            last_invalid_reason = "missing_LAeq"
            continue
        return packet
    raise TimeoutError(
        "no valid 10-second LAeq(A) packet within 45 seconds; "
        f"last reason: {last_invalid_reason}"
    )


def linear_fit(
    reference: list[float],
    measured: list[float],
) -> tuple[float, float, float]:
    ref_mean = statistics.fmean(reference)
    measured_mean = statistics.fmean(measured)
    covariance = sum(
        (x - ref_mean) * (y - measured_mean)
        for x, y in zip(reference, measured)
    )
    variance = sum((x - ref_mean) ** 2 for x in reference)
    slope = covariance / variance
    intercept = measured_mean - slope * ref_mean
    predictions = [slope * x + intercept for x in reference]
    residual = sum(
        (y - prediction) ** 2
        for y, prediction in zip(measured, predictions)
    )
    total = sum((y - measured_mean) ** 2 for y in measured)
    r_squared = 1.0 - residual / total if total else 0.0
    return slope, intercept, r_squared


def evaluate(pairs: list[dict], firmware_sha256: str) -> dict:
    reference = [row["cem_dba"] for row in pairs]
    measured = [row["firmware_dba"] for row in pairs]
    offsets = [expected - actual for expected, actual in zip(reference, measured)]
    offset_adjustment = statistics.median(offsets)
    existing_offsets = [
        float(row.get("firmware_offset_db", 0.0))
        for row in pairs
    ]
    existing_offset = statistics.median(existing_offsets)
    recommended_offset = existing_offset + offset_adjustment
    corrected_errors = [
        actual + offset_adjustment - expected
        for expected, actual in zip(reference, measured)
    ]
    slope, intercept, r_squared = linear_fit(reference, measured)
    median_absolute_error = statistics.median(
        abs(value) for value in corrected_errors
    )
    max_absolute_error = max(abs(value) for value in corrected_errors)
    reference_span = max(reference) - min(reference)
    checks = {
        "reference_span_at_least_20_db": reference_span >= 20.0,
        "monotonic_r_squared_at_least_0_95": r_squared >= 0.95,
        "slope_between_0_90_and_1_10": 0.90 <= slope <= 1.10,
        "median_absolute_error_at_most_1_5_db": median_absolute_error <= 1.5,
        "max_absolute_error_at_most_3_db": max_absolute_error <= 3.0,
        "firmware_offset_is_consistent": (
            max(existing_offsets) - min(existing_offsets) <= 0.01
        ),
    }
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decision": "PASS" if all(checks.values()) else "FAIL",
        "firmware_sha256": firmware_sha256,
        "meter": {
            "model": "CEM DT-8852",
            "weighting": "A",
            "time_weighting": "SLOW",
            "range": "30-130 dBA",
        },
        "placement": "capsules 2-5 cm apart, same orientation",
        "pairs": pairs,
        "starting_offset_db": round(existing_offset, 3),
        "offset_adjustment_db": round(offset_adjustment, 3),
        "recommended_offset_db": round(recommended_offset, 3),
        "metrics": {
            "reference_span_db": round(reference_span, 3),
            "slope": round(slope, 5),
            "intercept": round(intercept, 5),
            "r_squared": round(r_squared, 5),
            "median_absolute_error_db": round(median_absolute_error, 3),
            "max_absolute_error_db": round(max_absolute_error, 3),
        },
        "checks": checks,
    }


def main() -> None:
    try:
        import serial
    except ImportError as error:
        raise SystemExit(
            "pyserial is required for physical CEM collection: "
            "python3 -m pip install pyserial"
        ) from error

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--firmware", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    parser.add_argument("--pairs-per-level", type=int, default=3)
    args = parser.parse_args()
    if args.pairs_per_level < 3:
        raise SystemExit("at least 3 pairs per level are required")

    firmware_sha256 = hashlib.sha256(args.firmware.read_bytes()).hexdigest()
    pairs: list[dict] = []
    with serial.Serial(args.port, 115200, timeout=15) as port:
        port.reset_input_buffer()
        for target in TARGET_LEVELS:
            input(
                f"Set stable broadband/pink noise near {target} dBA, "
                "confirm CEM A/SLOW without UNDER/OVER, then press Enter: "
            )
            for index in range(args.pairs_per_level):
                packet = read_firmware_window(port)
                print(
                    "Firmware 10 s LAeq(A): "
                    f"{packet['sound_laeq_dba']:.2f} dBA"
                )
                raw = input(
                    f"Enter simultaneous CEM SLOW reading "
                    f"({target} dBA, pair {index + 1}): "
                )
                cem = float(raw)
                if not math.isfinite(cem) or not 30.0 <= cem <= 130.0:
                    raise SystemExit("CEM reading must be within 30-130 dBA")
                pairs.append({
                    "target_dba": target,
                    "cem_dba": cem,
                    "firmware_dba": float(packet["sound_laeq_dba"]),
                    "firmware_sequence": packet.get("sequence"),
                    "sound_dbfs": packet.get("sound_dbfs"),
                    "sound_samples": packet.get("sound_samples"),
                    "firmware_offset_db": packet.get(
                        "sound_calibration_offset_db", 0.0
                    ),
                })

    result = evaluate(pairs, firmware_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Result written to {args.output}")
    if result["decision"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
