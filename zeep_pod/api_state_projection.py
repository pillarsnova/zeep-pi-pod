"""Role-specific projections for the live Pod state API."""

from __future__ import annotations

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
