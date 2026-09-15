"""Retry-safe orchestration for deleting one local ZEEP account boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from zeep_pod.identity.account_aliases import (
    account_boundary_keys as verified_account_boundary_keys,
)
from zeep_pod.identity.account_aliases import canonical_profile_key


class AccountErasureError(RuntimeError):
    """Raised when durable Session deletion could not be verified."""


def resolve_local_account_key(
    requested_key: str,
    profiles: Mapping[str, Any],
) -> str:
    """Resolve an explicit legacy alias to its canonical local Profile key."""
    resolved = canonical_profile_key(requested_key, profiles)
    if resolved is None:
        raise AccountErasureError("legacy account alias has multiple identity owners")
    return resolved


def account_boundary_keys(
    key: str,
    profile: Mapping[str, Any],
    profiles: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return aliases that demonstrably belong to the same local identity.

    A legacy alias can later become another Profile's canonical key.  Never
    cross that boundary unless both Profiles carry the same immutable ZEEP
    public id; missing identity evidence fails closed.
    """
    if profiles is None:
        aliases = {
            str(value or "").strip().casefold()
            for value in profile.get("legacy_account_keys") or []
            if str(value or "").strip()
        }
        aliases.add(key)
        return tuple(sorted(aliases))
    return verified_account_boundary_keys(key, profile, profiles)


def _flush_or_raise(database: Any, *, phase: str) -> None:
    """Require one destructive database phase to finish durably."""
    if database.flush(30):
        return
    error = database.health().get("last_error")
    raise AccountErasureError(
        f"{phase} deletion could not be verified: {error or 'flush timeout'}"
    )


def _delete_session_data(
    database: Any,
    account_keys: tuple[str, ...],
    clear_pending_ingest: Callable[[str], bool],
) -> tuple[list[str], int]:
    placeholders = ",".join("?" for _key in account_keys)
    records = database.read_sessions(
        f"SELECT session_id FROM sessions "
        f"WHERE lower(username_key) IN ({placeholders})",
        account_keys,
    )
    session_ids = [str(record["session_id"]) for record in records]
    outbox_removed = 0
    for session_id in session_ids:
        outbox_removed += int(clear_pending_ingest(session_id))
        database.enqueue(
            "bcg",
            "delete_bcg_session",
            {"session_id": session_id},
        )
    _flush_or_raise(database, phase="BCG")
    for session_id in session_ids:
        database.enqueue(
            "sessions",
            "delete_session",
            {"session_id": session_id},
        )
    _flush_or_raise(database, phase="Session")
    return session_ids, outbox_removed


def _remove_profiles(
    key: str,
    account_keys: tuple[str, ...],
    *,
    profiles_lock: Any,
    load_profiles: Callable[[], dict[str, Any]],
    save_profiles: Callable[[dict[str, Any]], None],
) -> Any:
    with profiles_lock:
        profiles = load_profiles()
        removed = profiles.pop(key, None)
        changed = removed is not None
        for alias in account_keys:
            if alias != key:
                changed = profiles.pop(alias, None) is not None or changed
        if changed:
            save_profiles(profiles)
    return removed


def _discard_checkpoint(
    callback: Callable[[set[str]], bool],
    account_keys: tuple[str, ...],
) -> bool:
    try:
        return bool(callback(set(account_keys)))
    except (OSError, TypeError, ValueError) as exc:
        raise AccountErasureError(
            "Session checkpoint could not be verified during account erasure"
        ) from exc


def _profile_boundary(
    account_key: str,
    profiles_lock: Any,
    load_profiles: Callable[[], dict[str, Any]],
) -> tuple[str, dict[str, Any], bool, dict[str, Any]]:
    requested = str(account_key or "").strip().casefold()
    with profiles_lock:
        profiles = load_profiles()
        key = resolve_local_account_key(requested, profiles)
        value = profiles.get(key)
    profile = dict(value) if isinstance(value, Mapping) else {}
    return key, profile, value is not None, profiles


def erase_local_user_account(
    account_key: str,
    *,
    database: Any,
    baseline_store: Any,
    auth_sessions: Any,
    profiles_lock: Any,
    load_profiles: Callable[[], dict[str, Any]],
    save_profiles: Callable[[dict[str, Any]], None],
    clear_pending_ingest: Callable[[str], bool],
    clear_report_shares: Callable[[str], int],
    clear_pending_profiles: Callable[[str], int],
    clear_session_checkpoint: Callable[[set[str]], bool],
) -> dict[str, Any]:
    """Erase durable rows first while keeping a failed attempt retryable."""
    key, profile, profile_present, profiles = _profile_boundary(
        account_key,
        profiles_lock,
        load_profiles,
    )
    account_keys = account_boundary_keys(key, profile, profiles)
    declared_keys = account_boundary_keys(key, profile)
    skipped_alias_collisions = sorted(set(declared_keys) - set(account_keys))
    session_ids, outbox_removed = _delete_session_data(
        database,
        account_keys,
        clear_pending_ingest,
    )

    checkpoint_removed = _discard_checkpoint(
        clear_session_checkpoint,
        account_keys,
    )

    report_shares_revoked = sum(
        max(0, int(clear_report_shares(alias))) for alias in account_keys
    )
    pending_profiles_revoked = sum(
        max(0, int(clear_pending_profiles(alias))) for alias in account_keys
    )

    baseline_removed = False
    for alias in account_keys:
        baseline_removed = baseline_store.delete_user(alias) or baseline_removed
    revoked_browser_sessions = sum(
        max(0, int(auth_sessions.revoke_user_account(alias))) for alias in account_keys
    )
    # A fallback ticket authenticates a prior connectivity attempt, while the
    # local account key arrives in a separate request field. Invalidate every
    # outstanding capability so none can recreate an erased identity.
    offline_tickets_revoked = max(0, int(auth_sessions.clear_offline_tickets()))
    removed_value = _remove_profiles(
        key,
        account_keys,
        profiles_lock=profiles_lock,
        load_profiles=load_profiles,
        save_profiles=save_profiles,
    )
    removed = dict(removed_value) if isinstance(removed_value, Mapping) else profile
    return {
        "account_key": key,
        "account_aliases": list(account_keys),
        "skipped_alias_collisions": skipped_alias_collisions,
        "username": removed.get("username"),
        "sessions_removed": len(session_ids),
        "baseline_removed": baseline_removed,
        "pending_uploads_removed": outbox_removed,
        "report_shares_revoked": report_shares_revoked,
        "pending_profiles_revoked": pending_profiles_revoked,
        "revoked_browser_sessions": revoked_browser_sessions,
        "offline_tickets_revoked": offline_tickets_revoked,
        "checkpoint_removed": checkpoint_removed,
        "already_absent": not bool(
            profile_present
            or session_ids
            or baseline_removed
            or outbox_removed
            or report_shares_revoked
            or pending_profiles_revoked
            or revoked_browser_sessions
            or offline_tickets_revoked
            or checkpoint_removed
        ),
    }
