"""Versioned hardware and telemetry contracts for ZEEP Pod sensors.

The module deliberately separates three kinds of facts:

* ``manufacturer``: values published by the component manufacturer;
* ``zeep_transport``: the wiring/transport currently deployed in the Pod;
* ``health_use``: how the Pi may use the value without turning a wellness
  sensor into an unsupported medical claim.

Existing flat USB-serial and MQTT JSON payloads remain valid.  Firmware can
migrate to the v1 envelope one hub at a time; :func:`decode_hub_payload`
normalises either form to the same internal flat dictionary.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from sensors.bcg import parse_lsm800t_frame
from sensors.catalog import ENVIRONMENT_DEVICE_SPECS, SENSOR_CATALOG
from sensors.constants import (
    ENVIRONMENT_EVENT,
    LEGACY_HUB1_MEASUREMENT_FIELDS,
    SENSOR_CONTRACT_VERSION,
    SOUND_DBA_DISPLAY_MAX,
    SOUND_DBA_DISPLAY_MIN,
    SOUND_SENSOR_MODEL,
    TELEMETRY_SCHEMA,
    TELEMETRY_SCHEMA_VERSION,
)

__all__ = (
    "ENVIRONMENT_DEVICE_SPECS",
    "ENVIRONMENT_EVENT",
    "LEGACY_HUB1_MEASUREMENT_FIELDS",
    "SENSOR_CATALOG",
    "SENSOR_CONTRACT_VERSION",
    "SENSOR_VALUE_FIELDS",
    "SOUND_DBA_DISPLAY_MAX",
    "SOUND_DBA_DISPLAY_MIN",
    "SOUND_SENSOR_MODEL",
    "TELEMETRY_SCHEMA",
    "TELEMETRY_SCHEMA_VERSION",
    "classify_hub_payload",
    "decode_hub_payload",
    "parse_lsm800t_frame",
    "sensor_contract_snapshot",
)

# The nested telemetry schema binds every value to its physical owner. This
# prevents an unrelated sensor block from injecting or overwriting sound_dba
# (and applies the same isolation rule to every other Hub value).
SENSOR_VALUE_FIELDS: dict[str, frozenset[str]] = {
    "sht3x_dis": frozenset({"temperature_c", "humidity_rh"}),
    "opt3001": frozenset({"lux"}),
    "sph0645": frozenset(
        {
            "sound_dba",
            "sound_dbfs",
            "sound_class",
            "sound_class_state",
            "sound_class_confidence",
            "sound_event_detected",
            "sound_classifier_version",
            "sound_low_band_ratio",
            "sound_mid_band_ratio",
            "sound_high_band_ratio",
            "sound_spectral_centroid_hz",
            "sound_spectral_flatness",
            "sound_spectral_flux",
            "sound_crest_factor",
            "sound_syllabic_modulation",
            "sound_breathing_periodicity",
            "sound_breathing_period_s",
            "sound_spectral_frames",
            "sound_envelope_frames",
            "sound_window_sequence",
        }
    ),
    "mhz19c": frozenset({"co2_ppm"}),
    "pms7003": frozenset(
        {
            "pm1_0_ug_m3",
            "pm2_5_ug_m3",
            "pm10_ug_m3",
        }
    ),
    "sgp40": frozenset({"sgp40_raw", "voc_index"}),
}


def sensor_contract_snapshot() -> dict[str, Any]:
    """Return a JSON-safe immutable-by-convention contract snapshot."""
    return {
        "contract_version": SENSOR_CONTRACT_VERSION,
        "telemetry_schema": TELEMETRY_SCHEMA,
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "accepted_measurement_event": ENVIRONMENT_EVENT,
        "backward_compatible_flat_payloads": True,
        "devices": {key: dict(value) for key, value in SENSOR_CATALOG.items()},
    }


def _finite(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    try:
        return value if math.isfinite(float(value)) else None
    except OverflowError:
        return None


def classify_hub_payload(
    payload: Mapping[str, Any],
    *,
    expected_hub: str,
) -> tuple[str, str]:
    """Classify a raw hub frame before it can mutate live sensor state.

    Canonical packets require an environment event from the expected physical
    hub. A narrowly allowlisted event-less flat packet is retained only as a
    rollback bridge for released legacy firmware. Other well-formed events are
    ignored because INFO/calibration replies use the same serial transport. A
    malformed object or wrong hub is rejected without reconnecting USB.
    """
    if not isinstance(payload, Mapping):
        return "rejected", "payload_not_object"
    event = str(payload.get("event") or "").strip()
    if not event:
        hub_id = str(payload.get("hub_id") or "").strip()
        if hub_id and hub_id != expected_hub:
            return "rejected", f"unexpected_hub:{hub_id}"
        if LEGACY_HUB1_MEASUREMENT_FIELDS.intersection(payload):
            return "telemetry", "legacy_environment"
        return "ignored", "missing_event"
    if event != ENVIRONMENT_EVENT:
        return "ignored", event
    hub_id = str(payload.get("hub_id") or "").strip()
    if hub_id == expected_hub:
        return "telemetry", ENVIRONMENT_EVENT
    if (
        not hub_id
        and not isinstance(payload.get("sensors"), Mapping)
        and LEGACY_HUB1_MEASUREMENT_FIELDS.intersection(payload)
    ):
        # Released Golden firmware already labels frames as ``environment``
        # but predates hub_id and the nested envelope. Keep this bridge narrow:
        # it must be flat measurement telemetry, never a canonical or control
        # packet with an omitted identity.
        return "telemetry", "legacy_environment"
    return "rejected", f"unexpected_hub:{hub_id or 'missing'}"


def _decode_sensor_entries(
    sensors: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, bool], dict[str, dict[str, Any]]]:
    flat: dict[str, Any] = {}
    sensor_status: dict[str, bool] = {}
    sensor_diagnostics: dict[str, dict[str, Any]] = {}
    accepted_statuses = {"ok", "live", "ready", "degraded", "held"}

    for sensor_id, raw in sensors.items():
        if not isinstance(raw, Mapping):
            continue
        sensor_key = str(sensor_id)
        status = str(raw.get("status") or "ok").lower()
        reason = str(raw.get("reason") or raw.get("invalid_reason") or "").strip()
        sensor_status[sensor_key] = status in accepted_statuses
        values = raw.get("values") if isinstance(raw.get("values"), Mapping) else raw
        owned_fields = SENSOR_VALUE_FIELDS.get(sensor_key, frozenset())
        for key, value in values.items():
            if key in owned_fields:
                flat[str(key)] = _finite(value)
        details = {
            "status": status,
            "reason": reason or None,
            "quality": _finite(raw.get("quality")),
            "age_ms": _finite(raw.get("age_ms")),
            "diagnostics": (
                dict(raw["diagnostics"])
                if isinstance(raw.get("diagnostics"), Mapping)
                else None
            ),
        }
        sensor_diagnostics[sensor_key] = {
            key: value for key, value in details.items() if value is not None
        }
        if sensor_key == "sph0645" and reason and not sensor_status[sensor_key]:
            flat.setdefault("sound_invalid_reason", reason)

    return flat, sensor_status, sensor_diagnostics


def _telemetry_metadata(
    source: Mapping[str, Any],
    *,
    hub_id: str,
    sensor_status: Mapping[str, bool],
    sensor_diagnostics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "sensor_status": dict(sensor_status),
        "sensor_diagnostics": {
            key: dict(value) for key, value in sensor_diagnostics.items()
        },
        "event": source.get("event"),
        "source": source.get("source"),
        "hub_id": hub_id,
        "firmware_version": source.get("firmware_version"),
        "boot_id": source.get("boot_id"),
        "sound_firmware_version": source.get(
            "sound_firmware_version", source.get("firmware_version")
        ),
        "sequence": source.get("sequence"),
        "captured_at": source.get("captured_at"),
        "monotonic_ms": source.get("monotonic_ms"),
        "hub_diagnostics": (
            dict(source["diagnostics"])
            if isinstance(source.get("diagnostics"), Mapping)
            else {}
        ),
        "contract": {
            "schema": TELEMETRY_SCHEMA,
            "version": TELEMETRY_SCHEMA_VERSION,
            "hub_id": hub_id,
        },
    }


def decode_hub_payload(
    payload: Mapping[str, Any],
    *,
    expected_hub: str,
) -> dict[str, Any]:
    """Adapt a legacy flat object or the v1 envelope to the legacy internal view.

    No calibration or range clipping happens here.  The existing Pi validation
    remains the single place that converts source telemetry into health-facing
    values.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("sensor payload must be a JSON object")
    source = dict(payload)
    if source.get("schema") != TELEMETRY_SCHEMA:
        source.setdefault(
            "contract",
            {
                "schema": "legacy.flat",
                "adapter": SENSOR_CONTRACT_VERSION,
                "hub_id": expected_hub,
            },
        )
        return source
    if str(source.get("version")) != TELEMETRY_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported telemetry schema version: {source.get('version')}"
        )
    hub_id = str(source.get("hub_id") or "")
    if hub_id != expected_hub:
        raise ValueError(f"telemetry hub_id {hub_id!r} does not match {expected_hub!r}")
    sensors = source.get("sensors")
    if not isinstance(sensors, Mapping):
        raise ValueError("telemetry envelope sensors must be an object")
    flat, sensor_status, sensor_diagnostics = _decode_sensor_entries(sensors)
    flat.update(
        _telemetry_metadata(
            source,
            hub_id=hub_id,
            sensor_status=sensor_status,
            sensor_diagnostics=sensor_diagnostics,
        )
    )
    return flat
