"""Authenticated live-state WebSocket transport.

The receive side must stay active even when the browser normally sends no
messages.  ASGI delivers disconnect and server-shutdown notifications through
``receive``; a send-only loop prevents Uvicorn from draining cleanly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


def create_live_websocket_router(
    *,
    cookie_name: str,
    resolve_principal: Callable[[str | None], Any],
    active_session: Callable[[], Any],
    principal_owns_active: Callable[[Any, Any], bool],
    snapshot_for: Callable[[Any], dict[str, Any]],
    await_end_notice: Callable[[str], Any],
    interval_seconds: float = 0.5,
) -> APIRouter:
    """Create the live router without importing the composition root."""
    router = APIRouter(tags=["Live state"])

    @router.websocket("/ws")
    async def live_state(ws: WebSocket) -> None:
        principal = resolve_principal(ws.cookies.get(cookie_name))
        if principal is None:
            await ws.close(code=4401, reason="login required")
            return
        if not principal.is_admin and not principal_owns_active(
            active_session(), principal
        ):
            await ws.close(code=4403, reason="not pod session owner")
            return
        await ws.accept()
        try:
            while True:
                if not principal.is_admin and not principal_owns_active(
                    active_session(), principal
                ):
                    notice = await await_end_notice(principal.subject)
                    if notice is not None:
                        await ws.send_json({"type": "session_ended", **notice})
                    await ws.close(code=4403, reason="pod session ended")
                    return
                disconnected = await _wait_for_client_event(ws, interval_seconds)
                if disconnected:
                    return
                await ws.send_json(snapshot_for(principal))
        except (WebSocketDisconnect, RuntimeError):
            return
        except asyncio.CancelledError:
            # A service stop is not an application error.  End the ASGI call
            # instead of leaking a cancellation traceback into Production logs.
            await _close_best_effort(ws, code=1012, reason="service restart")
            return

    return router


async def _wait_for_client_event(ws: WebSocket, timeout: float) -> bool:
    """Receive disconnect notifications while retaining a bounded cadence."""
    try:
        message = await asyncio.wait_for(ws.receive(), timeout=timeout)
    except TimeoutError:
        return False
    return message.get("type") == "websocket.disconnect"


async def _close_best_effort(ws: WebSocket, *, code: int, reason: str) -> None:
    try:
        await ws.close(code=code, reason=reason)
    except (RuntimeError, WebSocketDisconnect):
        pass

