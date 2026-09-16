"""Small dependency-free helpers shared across ZEEP domains."""

from .mappings import as_mapping
from .numbers import as_finite_number, as_number, number_in_range

__all__ = (
    "as_finite_number",
    "as_mapping",
    "as_number",
    "number_in_range",
)
