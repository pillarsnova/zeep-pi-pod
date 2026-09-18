"""HTTP routing boundary for Aircon and Bed control handlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends

from api.models import (
    AirconCommand,
    AirconFanLevelReferenceCommand,
    BedControlCommand,
)


def create_control_router(
    *,
    require_pod_operator: Callable[..., Any],
    require_admin: Callable[..., Any],
    aircon_command: Callable[[AirconCommand, Any], dict[str, Any]],
    set_fan_reference: Callable[[AirconFanLevelReferenceCommand, Any], dict[str, Any]],
    bed_command: Callable[[BedControlCommand], dict[str, Any]],
) -> APIRouter:
    """Expose stable legacy paths while handlers migrate independently."""
    router = APIRouter(tags=["Pod controls"])
    operator_dependency = Depends(require_pod_operator)
    admin_dependency = Depends(require_admin)

    @router.post("/api/aircon/command")
    def aircon(
        cmd: AirconCommand,
        principal: Any = operator_dependency,
    ):
        return aircon_command(cmd, principal)

    @router.post("/api/admin/aircon/fan-level-reference")
    def fan_reference(
        cmd: AirconFanLevelReferenceCommand,
        principal: Any = admin_dependency,
    ):
        return set_fan_reference(cmd, principal)

    @router.post("/api/bed/command")
    def bed(
        cmd: BedControlCommand,
        _: Any = operator_dependency,
    ):
        return bed_command(cmd)

    return router
