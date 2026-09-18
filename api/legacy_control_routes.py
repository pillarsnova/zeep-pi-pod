"""Compatibility HTTP routes for GPIO, door and accessory controls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.models import SwitchCommand


def create_legacy_control_router(
    *,
    require_pod_operator: Callable[..., Any],
    gpio,
    gpio_outputs: Collection[str],
    pulse_outputs: Collection[str],
    require_safety: Callable[[str], None],
    door_pulse: Callable[[str], Awaitable[None]],
    accessory_pulse: Callable[[str], Awaitable[None]],
    note_activity: Callable[[str, dict[str, Any]], None],
    log_event: Callable[..., None],
    door_pulse_seconds: float,
    accessory_pulse_seconds: float,
) -> APIRouter:
    """Build existing route paths without coupling the router to ``app``."""
    router = APIRouter(tags=["Legacy device controls"])
    operator_dependency = Depends(require_pod_operator)

    @router.post("/api/output/{name}")
    async def output(
        name: str,
        cmd: SwitchCommand,
        _: Any = operator_dependency,
    ):
        if name not in gpio_outputs:
            raise HTTPException(404, "Unknown output")
        if name in ("door_open", "door_close"):
            raise HTTPException(400, "Use /api/door/open or /api/door/close for door")
        if name in pulse_outputs:
            raise HTTPException(400, f"Use /api/pulse/{name} for momentary output")
        if not (name == "led" and cmd.on):
            require_safety(f"output {name}={cmd.on}")
        gpio.require_ready()
        try:
            gpio.set(name, cmd.on)
        except Exception as exc:
            log_event("gpio", "command_failed", target=name, error=str(exc))
            raise HTTPException(500, str(exc)) from exc
        note_activity("output", {"name": name, "on": cmd.on})
        log_event("gpio", "output", target=name, on=cmd.on)
        return {"ok": True, "name": name, "on": cmd.on}

    @router.post("/api/door/open")
    async def door_open(_: Any = operator_dependency):
        await door_pulse("door_open")
        note_activity("door", {"action": "open"})
        log_event("door", "open_pulse", pulse_s=door_pulse_seconds)
        return {"ok": True, "action": "open", "pulse_s": door_pulse_seconds}

    @router.post("/api/door/close")
    async def door_close(_: Any = operator_dependency):
        require_safety("ปิดประตู")
        await door_pulse("door_close")
        note_activity("door", {"action": "close"})
        log_event("door", "close_pulse", pulse_s=door_pulse_seconds)
        return {"ok": True, "action": "close", "pulse_s": door_pulse_seconds}

    @router.post("/api/pulse/{name}")
    async def pulse_output(
        name: str,
        _: Any = operator_dependency,
    ):
        require_safety(f"pulse {name}")
        await accessory_pulse(name)
        note_activity("pulse", {"name": name})
        log_event("gpio", "pulse", target=name, pulse_s=accessory_pulse_seconds)
        return {"ok": True, "name": name, "pulse_s": accessory_pulse_seconds}

    return router
