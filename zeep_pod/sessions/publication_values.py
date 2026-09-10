"""Shared value helpers for public Session-result projection.

The persisted report format is intentionally flexible for backward
compatibility.  Application responses are intentionally not: only scalar
aggregate values on these positive allowlists may leave the Pi API.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCALAR_TYPES = (str, int, float, bool, type(None))
COMPONENT_KEYS = {
    "sleep_opportunity",
    "sleep_stability",
    "restorative_architecture",
    "cycle_expression",
    "data_coverage",
    "goal_duration",
    "physiological_response",
    "body_stillness",
    "rest_continuity",
    "environment_support",
}
STAGE_KEYS = {"wake", "n1", "n2", "n3", "rem", "mode_adjusted_balance"}
ENVIRONMENT_LEVEL_KEYS = {"critical", "poor", "fair", "good", "excellent"}
SENSOR_VALUE_KEYS = {"temp", "hum", "lux", "dba", "co2", "pm2_5", "voc"}


def mapping(value: Any) -> dict[str, Any]:
    """Return a shallow mapping copy, or an empty mapping for invalid input."""
    return dict(value) if isinstance(value, Mapping) else {}


def copy_scalars(value: Any, fields: set[str]) -> dict[str, Any]:
    """Copy only named scalar fields from a possibly untrusted mapping."""
    source = mapping(value)
    return {
        key: source[key]
        for key in fields
        if key in source and isinstance(source[key], SCALAR_TYPES)
    }


def scalar_map(value: Any, keys: set[str]) -> dict[str, Any]:
    """Project a mapping to a known set of scalar keys."""
    return copy_scalars(value, keys)


def scalar_list(value: Any) -> list[Any]:
    """Return scalar list members only."""
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, SCALAR_TYPES)]
