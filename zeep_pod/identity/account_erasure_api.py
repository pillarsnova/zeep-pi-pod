"""Admin API boundary for retry-safe local account erasure."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from zeep_pod.identity.account_erasure import (
    AccountErasureError,
    account_boundary_keys,
    erase_local_user_account,
    resolve_local_account_key,
)
from zeep_pod.identity.lifecycle_lock import synchronized_by
from zeep_pod.sessions._response_model_base import ContractModel


class AccountErasureScope(ContractModel):
    """Make the local/remote retention boundary machine-readable."""

    local_active_store_deleted: Literal[True]
    remote_uploaded_objects_deleted: Literal[False]
    daily_backup_archives_deleted: Literal[False]
    daily_backup_archives_retained: int = Field(ge=0)


class AccountErasureResponse(ContractModel):
    ok: Literal[True]
    account_key: str
    account_aliases: list[str]
    skipped_alias_collisions: list[str]
    username: str | None
    sessions_removed: int = Field(ge=0)
    baseline_removed: bool
    pending_uploads_removed: int = Field(ge=0)
    report_shares_revoked: int = Field(ge=0)
    pending_profiles_revoked: int = Field(ge=0)
    revoked_browser_sessions: int = Field(ge=0)
    offline_tickets_revoked: int = Field(ge=0)
    checkpoint_removed: bool
    already_absent: bool
    deletion_scope: AccountErasureScope


def create_account_erasure_router(
    *,
    require_admin: Callable[..., Any],
    lifecycle_lock: Any,
    normalize_account_key: Callable[[str], str],
    active_account_key: Callable[[], str | None],
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
    log_event: Callable[..., None],
    backup_retention_count: Callable[[], int],
) -> APIRouter:
    """Build the Admin-only erasure route from explicit dependencies."""
    router = APIRouter()

    @router.delete(
        "/api/users/{username}",
        dependencies=[Depends(require_admin)],
        response_model=AccountErasureResponse,
    )
    @synchronized_by(lifecycle_lock)
    def user_delete(username: str) -> dict[str, Any]:
        requested_key = normalize_account_key(username)
        with profiles_lock:
            profiles = load_profiles()
            key = resolve_local_account_key(requested_key, profiles)
            profile = profiles.get(key)
        profile = profile if isinstance(profile, dict) else {}
        aliases = set(account_boundary_keys(key, profile, profiles))
        active_key = str(active_account_key() or "").strip().casefold()
        if active_key in aliases:
            raise HTTPException(
                409,
                "ผู้ใช้นี้กำลังอยู่ใน session — ออกจากระบบก่อนลบ",
            )
        try:
            result = erase_local_user_account(
                key,
                database=database,
                baseline_store=baseline_store,
                auth_sessions=auth_sessions,
                profiles_lock=profiles_lock,
                load_profiles=load_profiles,
                save_profiles=save_profiles,
                clear_pending_ingest=clear_pending_ingest,
                clear_report_shares=clear_report_shares,
                clear_pending_profiles=clear_pending_profiles,
                clear_session_checkpoint=clear_session_checkpoint,
            )
        except AccountErasureError as exc:
            raise HTTPException(503, str(exc)) from exc
        log_event(
            "session",
            "user_deleted",
            sessions_removed=result["sessions_removed"],
            baseline_removed=result["baseline_removed"],
            pending_uploads_removed=result["pending_uploads_removed"],
            report_shares_revoked=result["report_shares_revoked"],
            pending_profiles_revoked=result["pending_profiles_revoked"],
            revoked_browser_sessions=result["revoked_browser_sessions"],
            offline_tickets_revoked=result["offline_tickets_revoked"],
            checkpoint_removed=result["checkpoint_removed"],
        )
        retained_archives = backup_retention_count()
        return {
            "ok": True,
            **result,
            "deletion_scope": {
                "local_active_store_deleted": True,
                "remote_uploaded_objects_deleted": False,
                "daily_backup_archives_deleted": False,
                "daily_backup_archives_retained": retained_archives,
            },
        }

    return router
