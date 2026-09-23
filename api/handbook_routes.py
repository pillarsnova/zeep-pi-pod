"""Serve the internal documentation bundle only to authenticated Admins."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse


def create_handbook_router(
    *, bundle: Path, require_admin: Callable[..., Any]
) -> APIRouter:
    router = APIRouter(tags=["Internal handbook"])
    admin_dependency = Depends(require_admin)

    @router.get("/handbook", include_in_schema=False)
    def handbook(_: Any = admin_dependency) -> FileResponse:
        if not bundle.is_file():
            raise HTTPException(404, "Handbook bundle has not been built")
        return FileResponse(
            bundle,
            media_type="text/html",
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'unsafe-inline'; "
                    "style-src 'unsafe-inline'; img-src data:; "
                    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
                ),
            },
        )

    return router
