"""Role-specific projections for the live Pod state API."""

from __future__ import annotations

from typing import Any

from sound_observability import sanitize_consumer_sound

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
