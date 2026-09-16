"""Low-level numeric extraction shared by Sensor Hub projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def first_numeric(
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> float | None:
    """Return the first coercible numeric field while rejecting booleans."""
    for key in keys:
        value = payload.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return None
