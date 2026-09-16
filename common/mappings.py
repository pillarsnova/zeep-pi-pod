"""Canonical mapping projection helpers used by result publishers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def as_mapping(value: Any) -> dict[str, Any]:
    """Return a detached dictionary or an empty mapping for non-mappings."""
    return dict(value) if isinstance(value, Mapping) else {}
