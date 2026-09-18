"""Build the Admin Smart Ear projection from versioned firmware DSP labels."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .contracts import (
    LIVE_SCHEMA,
    LIVE_SCHEMA_VERSION,
    acoustic_contract_snapshot,
)
from .label_events import LABELS


def _finite_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bounded_level(
    value: Any,
    accepted_range: Any,
) -> float | None:
    number = _finite_number(value)
    if number is None:
        return None
    low, high = 30.0, 130.0
    if isinstance(accepted_range, (list, tuple)) and len(accepted_range) == 2:
        candidate_low = _finite_number(accepted_range[0])
        candidate_high = _finite_number(accepted_range[1])
        if candidate_low is not None and candidate_high is not None:
            low, high = candidate_low, candidate_high
    return round(number, 2) if low <= number <= high else None


def _firmware_version(esp32: Mapping[str, Any]) -> str | None:
    for key in ("firmware_version", "fw_version", "version"):
        value = esp32.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _level_context(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    sensor = snapshot.get("sensor") or {}
    environment = sensor.get("environment") or {}
    esp32 = sensor.get("esp32") or {}
    system = snapshot.get("system") or {}
    analysis = system.get("sound_analysis") or {}
    accepted_range = (system.get("sound_transform") or {}).get("accepted_range_dba")
    device = (environment.get("devices") or {}).get("sph0645") or {}
    device_status = str(device.get("status") or "unavailable").strip().lower()
    sound_dba = _bounded_level(environment.get("sound_dba_est"), accepted_range)
    status = (
        "valid" if sound_dba is not None and device_status == "live" else device_status
    )
    allowed = {
        "valid",
        "stale",
        "invalid",
        "warming",
        "no_data",
        "offline",
        "unavailable",
    }
    sample_count = analysis.get("sample_count")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool):
        sample_count = 0
    return {
        "accepted_range": accepted_range or [30.0, 130.0],
        "analysis": analysis,
        "device_live": device_status == "live",
        "esp32": esp32,
        "sample_count": max(0, sample_count),
        "sound_dba": sound_dba,
        "status": status if status in allowed else "unavailable",
        "acoustic": (
            dict(environment.get("acoustic"))
            if isinstance(environment.get("acoustic"), Mapping)
            else {}
        ),
    }


def _aggregation(context: Mapping[str, Any]) -> dict[str, Any]:
    analysis = context["analysis"]
    accepted_range = context["accepted_range"]
    span_db = _finite_number(analysis.get("span_db"))
    return {
        "method": "packet_energy_average_db",
        "packet_energy_average_dba": _bounded_level(
            analysis.get("leq_dba"), accepted_range
        ),
        "sample_count": context["sample_count"],
        "window_s": _finite_number(analysis.get("window_s")),
        "min_dba": _bounded_level(analysis.get("min_dba"), accepted_range),
        "max_dba": _bounded_level(analysis.get("max_dba"), accepted_range),
        "span_db": round(span_db, 2) if span_db is not None else None,
        "status": str(analysis.get("status") or "waiting"),
        "metrology_note": "ไม่ใช่ certified LAeq(A)",
    }


def _reason_codes(context: Mapping[str, Any]) -> list[str]:
    acoustic = context.get("acoustic") or {}
    reasons = []
    if acoustic.get("state") != "provisional":
        reasons.extend(
            ["feature_telemetry_unavailable", "classification_input_unavailable"]
        )
    if context["sound_dba"] is None:
        reasons.append("sound_level_unavailable")
    if not context["device_live"]:
        reasons.append("microphone_not_live")
    return reasons


def _missing_features(
    features: Mapping[str, Any],
    required: list[str] | tuple[str, ...],
) -> list[str]:
    """Report absent classifier evidence without hiding available summaries."""
    aliases = {
        "spectral_centroid": "spectral_centroid_hz",
        "periodicity": "breathing_periodicity",
    }
    return [
        key
        for key in required
        if key not in features and aliases.get(key) not in features
    ]


def _observed_at(context: Mapping[str, Any], generated_at: datetime | None) -> str:
    observed_at = context["analysis"].get("window_end")
    if isinstance(observed_at, str) and observed_at.strip():
        return observed_at
    moment = generated_at or datetime.now(UTC)
    return moment.astimezone(UTC).isoformat(timespec="milliseconds")


def _confidence_band(confidence: float | None, active: bool) -> str:
    if confidence is not None and confidence >= 0.8:
        return "high"
    if confidence is not None and confidence >= 0.6:
        return "medium"
    return "low" if active else "unavailable"


def _hypothesis(label: str, display: str, confidence: float | None) -> list[dict[str, Any]]:
    return [{"key": label, "label": display, "confidence": confidence}]


def _classification_context(acoustic: Mapping[str, Any]) -> tuple[bool, str, float | None, str, str]:
    active = acoustic.get("state") == "provisional" and acoustic.get("label") in LABELS
    label = str(acoustic.get("label") or "unknown")
    confidence = _finite_number(acoustic.get("confidence"))
    display, group = LABELS.get(label, ("ยังไม่ทราบ", "unknown"))
    return active, label, confidence, display, group


def build_acoustic_monitor_snapshot(
    snapshot: Mapping[str, Any],
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return a fail-soft Admin projection without classifying scalar dBA."""
    contract = acoustic_contract_snapshot()
    context = _level_context(snapshot)
    level_status = context["status"]
    acoustic = context.get("acoustic") or {}
    features = dict(acoustic.get("features") or {})
    classification_active, label, confidence, display_name, group = (
        _classification_context(acoustic)
    )
    confidence_band = _confidence_band(confidence, classification_active)
    likely_sources = (
        _hypothesis(label, display_name, confidence)
        if classification_active and group in {"equipment_like", "impact"}
        else []
    )
    human = (
        _hypothesis(label, display_name, confidence)
        if classification_active and group == "human_sound_like"
        else []
    )

    return {
        "schema": LIVE_SCHEMA,
        "schema_version": LIVE_SCHEMA_VERSION,
        "contract_version": contract["contract_version"],
        "phase": "P1-shadow",
        "status": (
            "dsp_shadow" if classification_active
            else "level_only" if level_status == "valid"
            else level_status
        ),
        "classification_state": (
            "provisional" if classification_active else "not_evaluated"
        ),
        "monitoring_policy": {
            "live_without_session": True,
            "persistence": "recording_session_only",
            "off_session_recording": False,
        },
        "confidence_band": confidence_band,
        "observed_at": _observed_at(context, generated_at),
        "level": {
            "sound_dba": context["sound_dba"],
            "status": level_status,
            "source": "esp32_sound_dba_direct",
            "accepted_range_dba": context["accepted_range"],
            "certified_laeq": False,
        },
        "aggregation": _aggregation(context),
        "results": {
            "shapes": (
                _hypothesis(label, display_name, confidence)
                if classification_active
                else []
            ),
            "likely_sources": likely_sources,
            "human_sound_hypotheses": human,
            "mixed": False,
        },
        "reason_codes": _reason_codes(context),
        "evidence": {
            "quality": "firmware_dsp_shadow" if classification_active else "level_only",
            "feature_telemetry_available": bool(features),
            "classification_feature_set_complete": classification_active,
            "feature_source": acoustic.get("feature_source") or "unavailable",
            "missing": _missing_features(
                features,
                contract["required_features"],
            ),
            "features": features,
            "bcg_snoring_flag_is_microphone_evidence": False,
        },
        "provenance": {
            "sound_source": "esp32_sound_dba_direct",
            "feature_schema_version": "1.0" if classification_active else None,
            "classifier_version": acoustic.get("classifier_version"),
            "firmware_version": _firmware_version(context["esp32"]),
        },
        "privacy": contract["privacy"],
        "impact": contract["impact"],
        "clinical_validated": False,
        "automatic_actuation": False,
    }
