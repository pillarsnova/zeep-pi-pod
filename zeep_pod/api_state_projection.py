"""Role-specific projections for the live Pod state API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sound_observability import sanitize_consumer_sound
from zeep_pod.sessions.user_baseline_context import best_rest_window_context

CONSUMER_SYSTEM_FIELDS = (
    "uptime_s",
    "gpio_available",
    "gpio_error",
    "max_volume",
    "player",
    "session_sample_s",
    "bed_start_s",
    "pod_id",
    "occupancy",
)


@dataclass(frozen=True)
class LiveDeviceProjectionPolicy:
    """Display thresholds and public aircon bounds for one Pod process."""

    esp32_stale_s: float
    sensorhub2_stale_s: float
    bcg_stale_s: float
    controlhub1_stale_s: float
    controlhub2_stale_s: float
    aircon_power_on_default_c: int
    aircon_temperature_min_c: int
    aircon_temperature_max_c: int


def project_transport_status(
    device: dict[str, Any],
    *,
    now: float,
    stale_after_s: float,
    disconnected_reason: str | None = None,
) -> dict[str, Any]:
    """Add display-only freshness metadata to one detached device state.

    ``snapshot`` already owns a JSON-detached response tree, so updating this
    mapping preserves the established API shape without touching live reader
    state. A disconnected reason opts the device into fallback metadata; the
    Control Hubs intentionally expose freshness only.
    """
    last_update = device.get("last_update")
    device["data_age_s"] = (
        round(max(0.0, now - last_update), 1)
        if isinstance(last_update, (int, float))
        else None
    )
    if device.get("connected") and (
        last_update is None or now - last_update > stale_after_s
    ):
        device["connected"] = False
        device["stale"] = True

    if disconnected_reason is not None:
        fallback_active = bool(not device.get("connected") and last_update is not None)
        device["fallback_active"] = fallback_active
        if fallback_active:
            device["fallback_reason"] = (
                "stale" if device.get("stale") else disconnected_reason
            )
    return device


def project_aircon_status(
    aircon: dict[str, Any],
    *,
    now: float,
    policy: LiveDeviceProjectionPolicy,
) -> dict[str, Any]:
    """Publish the acknowledged aircon setpoint using the product contract."""
    project_transport_status(
        aircon,
        now=now,
        stale_after_s=policy.controlhub1_stale_s,
    )
    aircon.pop("temperature_bias_c", None)
    aircon["temperature_mapping"] = "direct_1_to_1"
    aircon["power_on_default_temperature_c"] = policy.aircon_power_on_default_c
    aircon["desired_temperature_min_c"] = policy.aircon_temperature_min_c
    aircon["desired_temperature_max_c"] = policy.aircon_temperature_max_c

    commanded_temperature = aircon.get("temperature_c")
    if isinstance(commanded_temperature, (int, float)) and not isinstance(
        commanded_temperature,
        bool,
    ):
        desired_temperature = int(commanded_temperature)
        within_product_range = (
            policy.aircon_temperature_min_c
            <= desired_temperature
            <= policy.aircon_temperature_max_c
        )
        aircon["desired_temperature_c"] = (
            desired_temperature if within_product_range else None
        )
    else:
        aircon["desired_temperature_c"] = None
    return aircon


def project_live_device_statuses(
    result: dict[str, Any],
    *,
    now: float,
    policy: LiveDeviceProjectionPolicy,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Project all Hub/BCG freshness fields on a detached API response."""
    sensor = result["sensor"]
    esp32 = sensor.get("esp32") or {}
    project_transport_status(
        esp32,
        now=now,
        stale_after_s=policy.esp32_stale_s,
        disconnected_reason="serial_disconnected",
    )
    sensorhub2 = sensor.get("sensorhub2") or {}
    project_transport_status(
        sensorhub2,
        now=now,
        stale_after_s=policy.sensorhub2_stale_s,
        disconnected_reason="mqtt_disconnected",
    )
    bcg = sensor.get("bcg") or {}
    project_transport_status(
        bcg,
        now=now,
        stale_after_s=policy.bcg_stale_s,
        disconnected_reason="serial_disconnected",
    )

    aircon = result.get("aircon") or {}
    project_aircon_status(
        aircon,
        now=now,
        policy=policy,
    )
    result["aircon"] = aircon

    bed_control = result.get("bed_control") or {}
    project_transport_status(
        bed_control,
        now=now,
        stale_after_s=policy.controlhub2_stale_s,
    )
    result["bed_control"] = bed_control
    return esp32, sensorhub2, bcg


def project_consumer_snapshot(
    result: dict[str, Any],
    principal: dict[str, Any],
) -> dict[str, Any]:
    """Remove infrastructure, raw waveform and Admin audit fields."""
    result.pop("events_tail", None)
    result.pop("adaptive_learning", None)
    system = result.get("system") or {}
    result["system"] = {key: system.get(key) for key in CONSUMER_SYSTEM_FIELDS}
    sanitize_consumer_sound(result.get("sensor") or {})
    sleep = result.get("sleep") or {}
    # The User Dashboard gets a bounded, source-field-minimized Session copy.
    # Keep internal cohort rows/Session IDs on the Admin surface only.
    behaviour = sleep.pop("personal_behaviour", None) or {}
    session = result.get("session") or {}
    if session.get("active"):
        window_source = session.get("personal_rest_baseline")
        if not isinstance(window_source, dict):
            window_source = behaviour.get("best_rest_window")
        bounded_window = best_rest_window_context(
            window_source,
            fallback_mode_group=(behaviour.get("mode_group") or None),
        )
        session["personal_rest_baseline"] = bounded_window
    else:
        session["personal_rest_baseline"] = best_rest_window_context(None)
    bcg = (result.get("sensor") or {}).get("bcg") or {}
    for key in (
        "samples",
        "raw_status_code",
        "raw_status_text",
        "bed_exit_evidence",
    ):
        bcg.pop(key, None)
    result["auth"] = {"principal": principal}
    return result
