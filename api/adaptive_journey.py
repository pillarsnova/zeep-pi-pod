"""Owner-scoped REST boundary for observational Adaptive Coach v1."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from adaptive.journey_repository import JourneyRepository
from adaptive.journey_service import JourneyService
from api.responses import response_envelope
from database import DatabaseManager


class ComfortRequest(BaseModel):
    """Optional personalization consent is explicit, never inferred."""

    model_config = ConfigDict(extra="forbid")
    response: Literal["comfortable", "too_cold", "too_warm", "not_comfortable"]
    use_for_personalization: Literal[True]
    request_id: UUID


class DecisionRequest(BaseModel):
    """A recorded decision cannot contain a command or actuator address."""

    model_config = ConfigDict(extra="forbid")
    recommendation_id: str
    decision: Literal["accept", "reject", "snooze"]
    request_id: UUID


def _call(response: Response, callback: Callable[[], dict[str, Any]]) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return response_envelope(callback(), kind="adaptive_journey")
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, "ยังยืนยันการบันทึกไม่ได้ กรุณาลองอีกครั้ง") from exc


def create_adaptive_journey_router(
    *,
    database: DatabaseManager,
    require_user: Callable[..., Any],
    snapshot_for: Callable[[Any], dict[str, Any]],
    clock: Callable[[], float] = time.time,
) -> APIRouter:
    """Reuse require_user, including its browser CSRF validation for POSTs."""
    router = APIRouter(prefix="/adaptive/sessions", tags=["Adaptive Journey"])
    service = JourneyService(JourneyRepository(database), snapshot_for, clock)
    user = Depends(require_user)

    @router.get("/{session_id}")
    def summary(session_id: str, response: Response, principal: Any = user):
        return _call(response, lambda: service.summary(session_id, principal))

    @router.post("/{session_id}/comfort")
    def comfort(
        session_id: str,
        payload: ComfortRequest,
        response: Response,
        principal: Any = user,
    ):
        return _call(
            response,
            lambda: service.feedback(
                session_id,
                principal,
                payload.response,
                str(payload.request_id),
            ),
        )

    @router.post("/{session_id}/decisions")
    def decision(
        session_id: str,
        payload: DecisionRequest,
        response: Response,
        principal: Any = user,
    ):
        return _call(
            response,
            lambda: service.decision(
                session_id,
                principal,
                payload.recommendation_id,
                payload.decision,
                str(payload.request_id),
            ),
        )

    return router
