"""Authenticated longitudinal Profile and AI-context API routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Response

from api.responses import response_envelope
from sessions.history_service import safe_account_profile
from sessions.user_ai_context import validated_user_ai_context
from sessions.user_ai_response_models import UserAiContextResponse
from sessions.user_profile_response_models import (
    UserLearningProfileResponse,
)

PRIVATE_NO_STORE = "private, no-store"
PROFILE_ERROR_RESPONSES = {
    401: {"description": "An authenticated browser Session is required"},
    403: {
        "description": (
            "The browser identity cannot access this account, or a broad "
            "legacy API token was supplied"
        )
    },
    422: {"description": "An administrator did not select one account"},
}
LONGITUDINAL_DESCRIPTION = (
    "A user receives only their own Profile. An Admin selects exactly one "
    "account with X-Zeep-Account-Key; the selector stays out of the URL and "
    "normal access logs. Broad X-API-Token credentials are rejected."
)
AI_CONTEXT_DESCRIPTION = (
    "Returns linkable personal Wellness data with direct identifiers removed. "
    "It is not anonymous. Purpose-specific authorization is reported "
    "fail-closed, and broad X-API-Token credentials are rejected."
)


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message})


def _account_key(principal: Any, requested: str) -> str:
    if getattr(principal, "auth_source", None) == "api_token":
        raise _error(
            403,
            "usage_api_scoped_credential_required",
            "กรุณาเข้าสู่ระบบด้วยบัญชีผู้ใช้หรือผู้ดูแลเพื่อดูผลการใช้งาน",
        )
    own_key = str(principal.account_key or "").strip().casefold()
    if principal.is_admin:
        if not requested:
            raise _error(
                422,
                "user_learning_account_required",
                "กรุณาเลือกผู้ใช้งานก่อนดูภาพรวมสะสม",
            )
        return requested
    if requested and requested != own_key:
        raise _error(
            403,
            "user_learning_scope_forbidden",
            "บัญชีนี้ดูได้เฉพาะภาพรวมการพักของตนเอง",
        )
    return own_key


def add_user_profile_routes(
    router: APIRouter,
    *,
    principal_dependency: Any,
    profiles_snapshot: Callable[[], dict[str, dict[str, Any]]],
    service_factory: Callable[[], Any],
    baseline_snapshot: Callable[[str], dict[str, Any] | None],
) -> None:
    """Attach full UI context and identity-free AI context side by side."""

    def profile_for(selected_account: str | None, principal: Any) -> dict[str, Any]:
        requested = str(selected_account or "").strip().casefold()
        key = _account_key(principal, requested)
        profiles = profiles_snapshot()
        profile = safe_account_profile(
            key,
            dict(profiles.get(key) or {}),
            profiles,
        )
        profile.setdefault("email", key if "@" in key else None)
        baseline = baseline_snapshot(key)
        if baseline is None:
            for alias in profile.get("verified_legacy_account_keys") or []:
                baseline = baseline_snapshot(str(alias).strip().casefold())
                if baseline is not None:
                    break
        return service_factory().learning_profile(
            key,
            profile,
            baseline=baseline,
        )

    @router.get(
        "/longitudinal",
        response_model=UserLearningProfileResponse,
        response_model_exclude_unset=True,
        summary="Get one user's longitudinal wellness profile",
        description=LONGITUDINAL_DESCRIPTION,
        responses=PROFILE_ERROR_RESPONSES,
    )
    def user_learning_profile(
        response: Response,
        selected_account: str | None = Header(
            None,
            alias="X-Zeep-Account-Key",
            max_length=320,
            description="Exact account key; administrator only",
        ),
        principal: Any = principal_dependency,
    ):
        response.headers["Cache-Control"] = PRIVATE_NO_STORE
        return response_envelope(
            profile_for(selected_account, principal),
            kind="user_learning_profile",
        )

    @router.get(
        "/longitudinal/ai-context",
        response_model=UserAiContextResponse,
        response_model_exclude_unset=True,
        summary="Get direct-identifier-free context for advisory AI",
        description=AI_CONTEXT_DESCRIPTION,
        responses=PROFILE_ERROR_RESPONSES,
    )
    def user_ai_context(
        response: Response,
        selected_account: str | None = Header(
            None,
            alias="X-Zeep-Account-Key",
            max_length=320,
            description="Exact account key; administrator only",
        ),
        principal: Any = principal_dependency,
    ):
        response.headers["Cache-Control"] = PRIVATE_NO_STORE
        return response_envelope(
            validated_user_ai_context(profile_for(selected_account, principal)),
            kind="user_ai_context",
        )
