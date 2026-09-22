"""Canonical numeric coercion helpers.

Strict helpers accept only already-decoded JSON numbers. Legacy scoring can
explicitly opt into finite numeric coercion without changing strict callers.
"""

from __future__ import annotations

import math
from typing import Any


def as_number(value: Any) -> float | None:
    """Return an ``int``/``float`` as ``float`` while rejecting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def as_finite_number(value: Any) -> float | None:
    """Return a finite JSON number while rejecting booleans and NaN/Inf."""
    number = as_number(value)
    return number if number is not None and math.isfinite(number) else None


def coerce_finite_number(value: Any, default: float = 0.0) -> float:
    """Preserve legacy scoring coercion, including numeric strings and booleans."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def number_in_range(
    value: Any,
    minimum: float,
    maximum: float,
    *,
    finite: bool = True,
) -> float | None:
    """Return a number only when it lies inside an inclusive range."""
    number = as_finite_number(value) if finite else as_number(value)
    if number is None or not minimum <= number <= maximum:
        return None
    return number
