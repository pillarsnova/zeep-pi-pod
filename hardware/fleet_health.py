"""Fleet-ready health projection for the local ZEEP Pod."""

from __future__ import annotations

import time
from typing import Any

from hardware.device_contract import device_health_contract

FLEET_HEALTH_VERSION = "zeep.fleet-health.v1"


def local_pod_health(
    snapshot: dict[str, Any],
    *,
    pod_id: str,
    stale_seconds: dict[str, float],
    now: float | None = None,
) -> dict[str, Any]:
    """Build one Pod record that a future fleet aggregator can merge."""
    observed_at = float(now if now is not None else time.time())
    sensor = snapshot.get("sensor") or {}
    devices = [
        device_health_contract(
            sensor.get("esp32"),
            pod_id=pod_id,
            device_id="sensorhub1-pod1",
            device_type="sensor_hub",
            transport="usb_serial_jsonl",
            stale_seconds=stale_seconds["sensorhub1"],
            now=observed_at,
            board_model="ESP32-S3",
        ),
        device_health_contract(
            sensor.get("sensorhub2"),
            pod_id=pod_id,
            device_id="sensorhub2-pod1",
            device_type="sensor_hub",
            transport="mqtt",
            stale_seconds=stale_seconds["sensorhub2"],
            now=observed_at,
        ),
        device_health_contract(
            snapshot.get("aircon"),
            pod_id=pod_id,
            device_id="controlhub1-pod1",
            device_type="aircon_ir_bridge",
            transport="mqtt",
            stale_seconds=stale_seconds["controlhub1"],
            now=observed_at,
            board_model="ESP32-S3",
        ),
        device_health_contract(
            snapshot.get("bed_control"),
            pod_id=pod_id,
            device_id="controlhub2-bed-pod1",
            device_type="bed_remote_bridge",
            transport="mqtt",
            stale_seconds=stale_seconds["controlhub2"],
            now=observed_at,
        ),
        device_health_contract(
            sensor.get("bcg"),
            pod_id=pod_id,
            device_id="bcg-lsm800t-pod1",
            device_type="bcg_sensor",
            transport="usb_serial_binary",
            stale_seconds=stale_seconds["bcg"],
            now=observed_at,
            board_model="LSM-800-T",
        ),
    ]
    live = sum(bool(item["quality"]["valid"]) for item in devices)
    return {
        "schema_version": FLEET_HEALTH_VERSION,
        "generated_epoch_s": observed_at,
        "fleet": {"pod_count": 1, "source": "local_pod"},
        "pods": [
            {
                "pod_id": pod_id,
                "summary": {
                    "state": "healthy" if live == len(devices) else "attention",
                    "devices_live": live,
                    "devices_total": len(devices),
                },
                "devices": devices,
            }
        ],
    }
