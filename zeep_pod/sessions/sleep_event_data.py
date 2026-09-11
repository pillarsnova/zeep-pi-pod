"""Shared parsing helpers for durable Sleep decision events."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any


def finite_number(value: Any) -> bool:
    """Return whether ``value`` is a finite real number, excluding booleans."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def parse_timestamp(value: Any) -> float | None:
    """Parse an ISO-8601 value into Unix seconds."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def event_value(event: Mapping[str, Any]) -> dict[str, Any]:
    """Decode a durable event payload stored as either JSON or a mapping."""
    value = event.get("value")
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def event_epoch(
    event: Mapping[str, Any],
    value: Mapping[str, Any],
) -> float | None:
    """Read a decision endpoint from its payload or event timestamp."""
    for candidate in (value.get("window_end"), event.get("timestamp")):
        parsed = parse_timestamp(candidate)
        if parsed is not None:
            return parsed
    return None


def decision_interval(
    event: Mapping[str, Any],
    value: Mapping[str, Any],
    *,
    fallback_interval_s: float,
) -> tuple[float, float] | None:
    """Return the canonical right-closed attribution interval."""
    end_epoch = parse_timestamp(value.get("attribution_end"))
    if end_epoch is None:
        end_epoch = event_epoch(event, value)
    if end_epoch is None:
        return None
    start_epoch = parse_timestamp(value.get("attribution_start"))
    if start_epoch is None:
        interval = value.get("sample_interval_s")
        if not finite_number(interval) or float(interval) <= 0:
            interval = fallback_interval_s
        start_epoch = end_epoch - float(interval)
    if start_epoch >= end_epoch:
        return None
    return start_epoch, end_epoch
