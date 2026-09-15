"""Run independent, retry-safe identity migrations during Pod startup."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

Migration = Callable[[dict[str, str]], Any]


def _attempt(
    operation: Migration,
    mapping: dict[str, str],
) -> dict[str, Any]:
    try:
        return {"status": "ok", "result": operation(mapping)}
    except Exception as exc:  # pragma: no cover - exercised via injected fault
        return {"status": "error", "error": str(exc)}


def migrate_identity_stores(
    mapping: Mapping[str, str],
    *,
    session_migration: Migration,
    baseline_migration: Migration,
    auth_migration: Migration,
) -> dict[str, Any]:
    """Attempt every store even when another store is temporarily unavailable."""
    canonical_mapping = dict(mapping)
    return {
        "profiles": len(canonical_mapping),
        "sessions": _attempt(session_migration, canonical_mapping),
        "baselines": _attempt(baseline_migration, canonical_mapping),
        "browser_sessions": _attempt(auth_migration, canonical_mapping),
    }
