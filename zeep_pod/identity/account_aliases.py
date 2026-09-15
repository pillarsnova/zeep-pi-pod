"""Fail-closed ownership checks for local legacy account aliases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def normalize_account_key(value: Any) -> str:
    """Return the case-insensitive key format used by local identity stores."""
    return str(value or "").strip().casefold()


def _profile(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _legacy_aliases(profile: Mapping[str, Any]) -> set[str]:
    values = profile.get("legacy_account_keys")
    if not isinstance(values, (list, tuple, set, frozenset)):
        return set()
    return {
        alias
        for value in values
        if (alias := normalize_account_key(value))
    }


def _claimants(
    alias: str,
    account_key: str,
    owner_profile: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    claimants = {}
    for stored_key, value in profiles.items():
        key = normalize_account_key(stored_key)
        candidate = _profile(value)
        if key == alias or alias in _legacy_aliases(candidate):
            claimants[key] = candidate
    # The caller's Profile is authoritative even when it came from an atomic
    # snapshot that has not yet been persisted to profiles.json.
    claimants[account_key] = owner_profile
    return claimants


def _claimants_share_public_id(
    claimants: Mapping[str, Mapping[str, Any]],
) -> bool:
    public_ids = {
        str(profile.get("zeep_public_id") or "").strip()
        for profile in claimants.values()
    }
    return len(public_ids) == 1 and "" not in public_ids


def verified_legacy_account_keys(
    account_key: str,
    profile: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return aliases uniquely attributable to the requested Profile.

    One Profile may claim an unused legacy key without a remote public id.
    Multiple claimants fail closed unless every claimant carries the same
    non-empty immutable ZEEP public id.
    """
    key = normalize_account_key(account_key)
    verified = []
    for alias in sorted(_legacy_aliases(profile) - {key}):
        claimants = _claimants(alias, key, profile, profiles)
        if len(claimants) == 1 or _claimants_share_public_id(claimants):
            verified.append(alias)
    return tuple(verified)


def canonical_profile_key(
    requested_key: str,
    profiles: Mapping[str, Any],
) -> str | None:
    """Resolve an alias only when its canonical owner is unambiguous."""
    requested = normalize_account_key(requested_key)
    normalized_profiles = {
        normalize_account_key(key): _profile(value)
        for key, value in profiles.items()
        if normalize_account_key(key)
    }
    if requested in normalized_profiles:
        return requested
    claimants = {
        key: profile
        for key, profile in normalized_profiles.items()
        if requested in _legacy_aliases(profile)
    }
    if not claimants:
        return requested
    if len(claimants) == 1 or _claimants_share_public_id(claimants):
        return sorted(claimants)[0]
    return None


def verified_alias_mapping(profiles: Mapping[str, Any]) -> dict[str, str]:
    """Return deterministic alias migrations without last-writer-wins claims."""
    normalized_profiles = {
        normalize_account_key(key): _profile(value)
        for key, value in profiles.items()
        if normalize_account_key(key)
    }
    aliases = {
        alias
        for profile in normalized_profiles.values()
        for alias in _legacy_aliases(profile)
    }
    mapping = {}
    for alias in sorted(aliases):
        owner = canonical_profile_key(alias, normalized_profiles)
        if owner is None or owner == alias:
            continue
        profile = normalized_profiles.get(owner, {})
        if alias in verified_legacy_account_keys(
            owner,
            profile,
            normalized_profiles,
        ):
            mapping[alias] = owner
    return mapping


def account_boundary_keys(
    account_key: str,
    profile: Mapping[str, Any],
    profiles: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return one canonical key plus only ownership-verified aliases."""
    key = normalize_account_key(account_key)
    return tuple(sorted({
        key,
        *verified_legacy_account_keys(key, profile, profiles),
    } - {""}))
