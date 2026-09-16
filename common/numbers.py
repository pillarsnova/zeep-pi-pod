"""Canonical numeric coercion helpers.

These helpers intentionally accept only already-decoded JSON numbers.  They do
not parse numeric strings because transport validation belongs at each API or
device boundary.
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
