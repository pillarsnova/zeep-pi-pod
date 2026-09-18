"""Admin Fleet Health API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Response

from api.responses import response_envelope


def create_fleet_router(
    *,
    require_admin: Callable[..., Any],
    fleet_snapshot: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin/fleet", tags=["Fleet health"])

    @router.get("/health")
    def health(response: Response, _: Any = Depends(require_admin)):
        response.headers["Cache-Control"] = "private, no-store"
        return response_envelope(fleet_snapshot(), kind="fleet_health")

    return router

