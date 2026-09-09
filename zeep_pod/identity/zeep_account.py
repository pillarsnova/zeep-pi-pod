"""Bind a ZEEP account response to this pod's local identity.

Password login and QR login both receive the same ``{tokens, user}`` payload
from the ZEEP API, so the binding rules — which field is canonical, and when an
account is too incomplete to own local sleep history — live here once instead
of being re-implemented per login method.

``zeep_request``, ``log_event`` and ``offline_error`` are injected: the HTTP
client, the event log and the offline sentinel belong to the composition root,
and this module has to stay importable without it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from fastapi import HTTPException

from zeep_pod.identity.profile_fields import normalize_email


def identity_from_auth_data(
    data: Dict[str, Any],
    *,
    zeep_request: Callable[..., Dict[str, Any]],
    log_event: Callable[..., None],
    offline_error: type[BaseException],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Turn a verified ZEEP auth payload into local identity plus profile.

    ``/v1/auth/qr/poll`` hands back the same ``publicUser()`` object as
    ``/v1/auth/login``, so an approved QR login is bound exactly like a
    password login.
    """
    tokens = data.get("tokens") or {}
    user = data.get("user") or {}
    access_token = tokens.get("accessToken")
    zeep_username = str(user.get("username") or "").strip()
    public_id = str(user.get("publicId") or "").strip()
    if not access_token or not zeep_username or not public_id:
        raise HTTPException(502, "ZEEP API ตอบข้อมูลตัวตนไม่ครบ")

    me: Dict[str, Any] = {}
    profile_refreshed = False
    try:
        me = zeep_request("GET", "/v1/users/me", token=access_token).get("data") or {}
        if not isinstance(me, dict):
            me = {}
        profile_refreshed = True
    except (offline_error, HTTPException) as exc:
        log_event("auth", "zeep_profile_failed", user=zeep_username,
                  error=str(getattr(exc, "detail", exc)))

    # Email is the canonical local data identity. Prefer the Login contract and
    # accept /users/me as a fallback, then reject incomplete accounts instead
    # of silently creating a second history under a mutable display name.
    try:
        account_email = normalize_email(str(user.get("email") or me.get("email") or ""))
    except HTTPException as exc:
        raise HTTPException(502, "ZEEP API ตอบ Email สำหรับผูกประวัติไม่ครบ") from exc

    auth = {
        "public_id": public_id,
        "username": zeep_username,
        "email": account_email,
        "display_name": (user.get("displayName") or "").strip() or zeep_username,
        "role": user.get("role"),
        "plan": user.get("plan"),
        "access_token": access_token,
        "refresh_token": tokens.get("refreshToken"),
        # Internal freshness flag only; never returned by the public Login
        # response.  It prevents a failed profile fetch from looking current.
        "profile_refreshed": profile_refreshed,
    }
    return auth, me


def authenticate_password(
    identifier: str,
    password: str,
    *,
    zeep_request: Callable[..., Dict[str, Any]],
    log_event: Callable[..., None],
    offline_error: type[BaseException],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Verify a ZEEP account and return public identity plus profile metadata."""
    data = zeep_request(
        "POST", "/v1/auth/login", json_body={"identifier": identifier, "password": password}
    ).get("data") or {}
    return identity_from_auth_data(
        data, zeep_request=zeep_request, log_event=log_event, offline_error=offline_error
    )
