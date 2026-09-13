"""Versioned, authenticated API routes for ZEEP usage Session results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response

from api_v1 import response_envelope
from zeep_pod.sessions.history_service import (
    SessionHistoryService,
    resolve_history_window,
)
from zeep_pod.sessions.response_models import (
    UsageSessionDevelopmentResponse,
    UsageSessionDetailResponse,
    UsageSessionListResponse,
    UsageSessionPresentationResponse,
    UsageSessionSummaryResponse,
)
from zeep_pod.sessions.usage_service import UsageSessionService

USAGE_LIST_EXAMPLE = {
    "schema": "zeep.api.response",
    "api_version": "1.0",
    "kind": "usage_session_list",
    "generated_at": "2026-09-11T03:00:00.000+00:00",
    "request_id": "96be6449-b4d9-4ee7-b803-c5b269dbd533",
    "data": {
        "contract_version": "zeep.usage-session.v1",
        "history_name": "usage_history",
        "items": [],
        "summary": {
            "people_count": 2,
            "session_count": 2,
            "sleep_score_count": 1,
            "recovery_score_count": 1,
            "awaiting_score_count": 0,
            "average_sleep_score": 82.0,
            "average_recovery_score": 78.0,
        },
        "pagination": {
            "limit": 50,
            "offset": 2,
            "returned": 0,
            "total": 2,
            "has_more": False,
        },
        "range": None,
        "history_start_utc": "2026-09-01T00:00:00+00:00",
    },
}

ERROR_RESPONSES = {
    401: {"description": "An authenticated browser Session is required"},
    403: {"description": "The authenticated identity cannot access this scope"},
    404: {"description": "Session was not found in the permitted scope"},
    422: {"description": "Date, time or pagination filter is invalid"},
}
PRIVATE_NO_STORE = "private, no-store"


def _usage_error(status_code: int, code: str, message: str) -> HTTPException:
    """Build the stable error detail used by Usage Session clients."""
    return HTTPException(
        status_code,
        {"code": code, "message": message},
    )


def _require_usage_browser_principal(principal: Any) -> Any:
    """Keep the broad legacy automation token outside health-result routes."""
    if getattr(principal, "auth_source", None) == "api_token":
        raise _usage_error(
            403,
            "usage_api_scoped_credential_required",
            "กรุณาเข้าสู่ระบบด้วยบัญชีผู้ใช้หรือผู้ดูแลเพื่อดูผลการใช้งาน",
        )
    return principal


def _history_window(
    date_from: str | None,
    date_to: str | None,
    time_from: str,
    time_to: str,
    timezone_name: str,
):
    if not date_from and not date_to and (time_from != "00:00" or time_to != "23:59"):
        raise _usage_error(
            422,
            "usage_history_filter_invalid",
            "กรุณาเลือกวันที่ก่อนกำหนดช่วงเวลา",
        )
    try:
        return resolve_history_window(
            date_from,
            date_to,
            time_from,
            time_to,
            timezone_name=timezone_name,
        )
    except ValueError as exc:
        raise _usage_error(
            422,
            "usage_history_filter_invalid",
            "ช่วงวันที่หรือเวลาไม่ถูกต้อง กรุณาตรวจสอบแล้วลองอีกครั้ง",
        ) from exc


@dataclass(frozen=True)
class _UsageApiContext:
    history_service: Callable[[], SessionHistoryService]
    profiles_snapshot: Callable[[], dict[str, dict[str, Any]]]
    profiles_lock: Any
    timezone_name: str

    def profiles(self) -> dict[str, dict[str, Any]]:
        with self.profiles_lock:
            return self.profiles_snapshot()

    def service(self) -> UsageSessionService:
        return UsageSessionService(self.history_service())


def _build_list_endpoint(context: _UsageApiContext, principal_dependency: Any):
    def list_usage_sessions(
        response: Response,
        date_from: str | None = Query(
            None,
            description="Inclusive local start date (YYYY-MM-DD)",
            examples=["2026-09-01"],
        ),
        date_to: str | None = Query(
            None,
            description="Inclusive local end date (YYYY-MM-DD)",
            examples=["2026-09-11"],
        ),
        time_from: str = Query(
            "00:00",
            description="Inclusive local start time (HH:MM)",
        ),
        time_to: str = Query(
            "23:59",
            description="Inclusive local end minute (HH:MM)",
        ),
        account_key: str | None = Query(
            None,
            description="Exact canonical email/account key; administrator only",
        ),
        query: str | None = Query(
            None,
            max_length=160,
            description="Email or display-name search; administrator only",
        ),
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
        principal: Any = principal_dependency,
    ):
        response.headers["Cache-Control"] = PRIVATE_NO_STORE
        principal = _require_usage_browser_principal(principal)
        window = _history_window(
            date_from,
            date_to,
            time_from,
            time_to,
            context.timezone_name,
        )
        profiles = context.profiles()
        service = context.service()
        if principal.is_admin:
            data = service.list_for_admin(
                profiles,
                window=window,
                account_key=account_key,
                query=query,
                limit=limit,
                offset=offset,
            )
        else:
            requested = str(account_key or "").strip().casefold()
            own_key = str(principal.account_key or "").strip().casefold()
            if (requested and requested != own_key) or query:
                raise _usage_error(
                    403,
                    "usage_history_scope_forbidden",
                    "บัญชีนี้ดูได้เฉพาะประวัติการใช้งานของตนเอง",
                )
            data = service.list_for_account(
                own_key,
                profiles.get(own_key) or {},
                window=window,
                limit=limit,
                offset=offset,
            )
        return response_envelope(data, kind="usage_session_list")

    return list_usage_sessions


def _build_detail_endpoint(
    context: _UsageApiContext,
    principal_dependency: Any,
    *,
    include_report: bool,
):
    def usage_session_result(
        response: Response,
        session_id: str = Path(
            ...,
            min_length=1,
            max_length=160,
            description="Immutable Pi external Session ID",
        ),
        principal: Any = principal_dependency,
    ):
        response.headers["Cache-Control"] = PRIVATE_NO_STORE
        principal = _require_usage_browser_principal(principal)
        account_key = None if principal.is_admin else principal.account_key
        method = (
            context.service().detail_by_id
            if include_report
            else context.service().summary_by_id
        )
        data = method(
            session_id,
            context.profiles(),
            account_key=account_key,
        )
        if data is None:
            raise _usage_error(
                404,
                "usage_session_not_found",
                "ไม่พบผลการใช้งานนี้ หรือบัญชีนี้ไม่มีสิทธิ์เข้าถึง",
            )
        kind = "usage_session_detail" if include_report else "usage_session_summary"
        return response_envelope(data, kind=kind)

    return usage_session_result


def _build_presentation_endpoint(
    context: _UsageApiContext,
    principal_dependency: Any,
):
    def usage_session_presentation(
        response: Response,
        session_id: str = Path(..., min_length=1, max_length=160),
        principal: Any = principal_dependency,
    ):
        response.headers["Cache-Control"] = PRIVATE_NO_STORE
        principal = _require_usage_browser_principal(principal)
        account_key = None if principal.is_admin else principal.account_key
        data = context.service().presentation_by_id(
            session_id,
            context.profiles(),
            account_key=account_key,
        )
        if data is None:
            raise _usage_error(
                404,
                "usage_session_not_found",
                "ไม่พบผลการใช้งานนี้ หรือบัญชีนี้ไม่มีสิทธิ์เข้าถึง",
            )
        return response_envelope(data, kind="usage_session_presentation")

    return usage_session_presentation


def _build_development_endpoint(
    context: _UsageApiContext,
    admin_dependency: Any,
):
    def usage_session_development(
        response: Response,
        session_id: str = Path(..., min_length=1, max_length=160),
        principal: Any = admin_dependency,
    ):
        response.headers["Cache-Control"] = PRIVATE_NO_STORE
        _require_usage_browser_principal(principal)
        data = context.service().development_by_id(
            session_id,
            context.profiles(),
        )
        if data is None:
            raise _usage_error(
                404,
                "usage_session_not_found",
                "ไม่พบผลการใช้งานนี้",
            )
        return response_envelope(data, kind="usage_session_development")

    return usage_session_development


def _add_presentation_routes(
    router: APIRouter,
    context: _UsageApiContext,
    principal: Any,
    admin: Any,
) -> None:
    router.add_api_route(
        "/{session_id}/presentation",
        _build_presentation_endpoint(context, principal),
        methods=["GET"],
        response_model=UsageSessionPresentationResponse,
        response_model_exclude_unset=True,
        summary="Get one concise user result",
        description=(
            "Canonical display hierarchy with one primary score, friendly "
            "summary, key metrics, Baseline context and one recommendation. "
            "It contains no repeated score block and no Raw Sensor data."
        ),
        responses=ERROR_RESPONSES,
    )
    router.add_api_route(
        "/{session_id}/development",
        _build_development_endpoint(context, admin),
        methods=["GET"],
        response_model=UsageSessionDevelopmentResponse,
        response_model_exclude_unset=True,
        summary="Get aggregate Admin development diagnostics",
        description=(
            "Administrator-only score release, accounting, environment, "
            "version and review context. Raw Sensor data remains available "
            "only through the separate protected research routes."
        ),
        responses=ERROR_RESPONSES,
    )


def create_usage_sessions_router(
    *,
    require_user: Callable[..., Any],
    require_admin: Callable[..., Any],
    history_service: Callable[[], SessionHistoryService],
    profiles_snapshot: Callable[[], dict[str, dict[str, Any]]],
    profiles_lock: Any,
    timezone_name: str,
) -> APIRouter:
    """Create the email-first, raw-free usage history API."""
    router = APIRouter(
        prefix="/api/v1/usage-sessions",
        tags=["Usage Sessions"],
    )
    context = _UsageApiContext(
        history_service,
        profiles_snapshot,
        profiles_lock,
        timezone_name,
    )
    principal = Depends(require_user)
    admin = Depends(require_admin)
    router.add_api_route(
        "",
        _build_list_endpoint(context, principal),
        methods=["GET"],
        response_model=UsageSessionListResponse,
        response_model_exclude_unset=True,
        summary="List finalized usage Sessions",
        description=(
            "Users receive only their own email-linked Sessions; authenticated "
            "browser Admins may filter participants. The legacy broad API token "
            "is deliberately rejected. Local end time assigns the history day."
        ),
        responses={
            200: {
                "description": "Paginated usage history",
                "content": {"application/json": {"example": USAGE_LIST_EXAMPLE}},
            },
            **ERROR_RESPONSES,
        },
    )
    router.add_api_route(
        "/{session_id}/summary",
        _build_detail_endpoint(context, principal, include_report=False),
        methods=["GET"],
        response_model=UsageSessionSummaryResponse,
        response_model_exclude_unset=True,
        summary="Get one finalized Session summary",
        description=(
            "Mode-specific score, Restore Summary and quality metadata; no raw "
            "Timeline, BCG packet or Profile answers."
        ),
        responses=ERROR_RESPONSES,
    )
    router.add_api_route(
        "/{session_id}",
        _build_detail_endpoint(context, principal, include_report=True),
        methods=["GET"],
        response_model=UsageSessionDetailResponse,
        response_model_exclude_unset=True,
        summary="Get one finalized Session report",
        description=(
            "Returns the compact versioned Session report without raw Sensor "
            "samples; raw research routes remain administrator-only."
        ),
        responses=ERROR_RESPONSES,
    )
    _add_presentation_routes(router, context, principal, admin)
    return router
