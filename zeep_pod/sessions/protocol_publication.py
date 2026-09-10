"""Typed positive projection for public Session-mode protocol metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SESSION_MODES = {"sleep", "nap_recovery", "unknown"}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _copy_typed(
    source: Mapping[str, Any],
    fields: set[str],
    value_type: type,
) -> dict[str, Any]:
    return {
        key: source[key]
        for key in fields
        if key in source and isinstance(source[key], value_type)
    }


def _copy_numbers(source: Mapping[str, Any], fields: set[str]) -> dict[str, float]:
    return {
        key: float(source[key])
        for key in fields
        if key in source
        and not isinstance(source[key], bool)
        and isinstance(source[key], int | float)
        and source[key] >= 0
    }


def _number_list(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)):
        return None
    if any(
        isinstance(item, bool) or not isinstance(item, int | float) or item < 0
        for item in value
    ):
        return None
    return [float(item) for item in value]


def _ordered_range(value: Any) -> list[float] | None:
    values = _number_list(value)
    if values is None or len(values) != 2 or values[0] > values[1]:
        return None
    return values


def public_protocol_target(value: Any) -> dict[str, Any]:
    """Return the approved target snapshot without arbitrary persisted keys."""
    source = _mapping(value)
    public: dict[str, Any] = {}
    public.update(_copy_typed(source, {"available", "valid", "review_required"}, bool))
    public.update(_copy_typed(source, {"key", "label", "source"}, str))
    public.update(
        _copy_numbers(
            source,
            {"seconds", "minutes", "extended_max_seconds"},
        )
    )
    group = source.get("group")
    if group in SESSION_MODES:
        public["group"] = group
    supported = _number_list(source.get("supported_seconds"))
    if supported is not None:
        public["supported_seconds"] = supported
    recommended = _ordered_range(source.get("recommended_range_seconds"))
    if recommended is not None:
        public["recommended_range_seconds"] = recommended
    return public


def public_protocol_status(value: Any) -> dict[str, Any]:
    """Return documented protocol timing fields and a sanitized target."""
    source = _mapping(value)
    public: dict[str, Any] = {}
    public.update(
        _copy_typed(
            source,
            {
                "available",
                "within_operational_window",
                "within_recommended_range",
                "review_required",
                "score_releasable",
            },
            bool,
        )
    )
    public.update(
        _copy_typed(
            source,
            {"status", "display_status", "observed_timing_band", "reason"},
            str,
        )
    )
    public.update(
        _copy_numbers(
            source,
            {
                "observed_seconds",
                "minimum_seconds",
                "maximum_seconds",
                "minimum_score_seconds",
                "legacy_hard_max_seconds",
                "extended_max_seconds",
            },
        )
    )
    canonical_mode = source.get("canonical_mode")
    if canonical_mode in SESSION_MODES:
        public["canonical_mode"] = canonical_mode
    recommended = _ordered_range(source.get("recommended_range_seconds"))
    if recommended is not None:
        public["recommended_range_seconds"] = recommended
    if "target" in source:
        public["target"] = public_protocol_target(source["target"])
    return public
