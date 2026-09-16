"""Identity boundary helpers for Session history projections."""

from __future__ import annotations

from typing import Any

from identity.account_aliases import (
    canonical_profile_key,
    normalize_account_key,
    verified_legacy_account_keys,
)


def identity(profile: dict[str, Any], account_key: str) -> dict[str, Any]:
    """Build the display-safe identity attached to an authorized history row."""
    email = (
        profile.get("email")
        or profile.get("zeep_email")
        or (account_key if "@" in account_key else None)
    )
    return {
        "account_key": account_key,
        "email": email,
        "display_name": profile.get("display_name")
        or profile.get("username")
        or email
        or account_key,
    }


def account_boundary_keys(
    account_key: str,
    profile: dict[str, Any],
) -> list[str]:
    """Read canonical and pre-verified legacy rows as one account history."""
    keys = {
        normalize_account_key(value)
        for value in profile.get("verified_legacy_account_keys") or []
        if normalize_account_key(value)
    }
    keys.add(normalize_account_key(account_key))
    return sorted(keys - {""})


def safe_account_profile(
    account_key: str,
    profile: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Attach only aliases with unambiguous ownership to one Profile copy."""
    safe = dict(profile)
    safe["verified_legacy_account_keys"] = list(
        verified_legacy_account_keys(account_key, profile, profiles)
    )
    return safe


def profile_for_record(
    record_key: str,
    profiles: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Map a DB row to one canonical Profile, failing closed on disputes."""
    key = normalize_account_key(record_key)
    canonical = canonical_profile_key(key, profiles)
    if canonical is None:
        return key, {}
    for stored_key, value in profiles.items():
        if normalize_account_key(stored_key) != canonical:
            continue
        profile = dict(value or {})
        return canonical, safe_account_profile(canonical, profile, profiles)
    return key, {}


def canonicalize_identity(
    session: dict[str, Any],
    account_key: str,
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Keep a legacy database key out of the current public identity."""
    session.update(identity(profile, account_key))
    return session


def matches_identity(
    profile: dict[str, Any],
    account_key: str,
    query: str | None,
) -> bool:
    """Match an Admin search against current identity fields only."""
    needle = str(query or "").strip().casefold()
    if not needle:
        return True
    fields = (
        account_key,
        profile.get("email"),
        profile.get("zeep_email"),
        profile.get("display_name"),
        profile.get("username"),
    )
    return any(needle in str(value or "").casefold() for value in fields)
