"""Routes for the shared tablet shell and small live read endpoints."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse

from api.handbook_routes import create_handbook_router


def create_shell_router(
    *,
    static_dir: Path,
    require_admin: Callable[..., Any],
    require_pod_operator: Callable[..., Any],
    snapshot_for: Callable[[Any], dict[str, Any]],
    public_status: Callable[[], dict[str, Any]],
    smart_response: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["Pod shell"])
    router.include_router(
        create_handbook_router(
            bundle=static_dir.parent / "docs/portal/index.html",
            require_admin=require_admin,
        )
    )
    operator_dependency = Depends(require_pod_operator)

    @router.get("/")
    async def root():
        return RedirectResponse(url="/login", status_code=307)

    @router.get("/login")
    @router.get("/login/qr")
    @router.get("/admin/login")
    async def login_view():
        return _shell(static_dir)

    @router.get("/dashboard")
    @router.get("/control")
    @router.get("/control-debug")
    @router.get("/monitor")
    @router.get("/sessions")
    @router.get("/admin")
    async def ui_view():
        return _shell(static_dir)

    @router.get("/api/state")
    async def api_state(principal: Any = operator_dependency):
        return snapshot_for(principal)

    @router.get("/api/public/status")
    def pod_status():
        return public_status()

    @router.get("/api/smart-response")
    async def api_smart_response(_: Any = operator_dependency):
        return smart_response()

    return router


def _shell(static_dir: Path) -> FileResponse:
    return FileResponse(
        static_dir / "index.html",
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )
