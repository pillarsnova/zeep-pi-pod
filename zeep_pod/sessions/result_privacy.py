"""Privacy projection shared by customer-facing Session result contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

PRIVATE_RESULT_FIELDS = {
    "access_token",
    "answers",
    "auth",
    "bcg_base64",
    "health_reference",
    "packet",
    "packets",
    "profile",
    "questionnaire",
    "raw",
    "raw_bcg",
    "raw_samples",
    "refresh_token",
    "samples",
    "wellness_context",
}
PRIVATE_RESULT_SEGMENTS = {
    "authorization",
    "cookie",
    "credential",
    "password",
    "raw",
    "samples",
    "secret",
    "token",
}


def _normalized_key(key: Any) -> str:
    """Normalize snake, kebab and camelCase names before privacy checks."""
    value = str(key).strip()
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _private_result_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    segments = set(normalized.split("_"))
    compact = normalized.replace("_", "")
    return (
        normalized in PRIVATE_RESULT_FIELDS
        or bool(segments & PRIVATE_RESULT_SEGMENTS)
        or compact.endswith(("apikey", "privatekey"))
    )


def public_result_value(value: Any) -> Any:
    """Recursively remove private fields from a display-safe result value."""
    if isinstance(value, Mapping):
        return {
            str(key): public_result_value(item)
            for key, item in value.items()
            if not _private_result_key(key)
        }
    if isinstance(value, list | tuple):
        return [public_result_value(item) for item in value]
    return value
