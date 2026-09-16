"""Stable, versioned read API for the ZEEP Pod control plane.

Legacy ``/api/*`` routes remain unchanged for the installed tablet.  New
integrations should begin with this envelope so schema/version/time/request-id
metadata is never inferred from UI implementation details.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Response

from acoustics import acoustic_contract_snapshot
from api.responses import response_envelope

# Internal compatibility for the first v1 routes and their existing tests.
_response = response_envelope


def _api_index_data() -> dict[str, Any]:
    """Describe stable v1 resources without coupling them to route setup."""
    return {
        "compatibility": "Existing /api routes remain supported",
        "resources": {
            "health": "/api/v1/public/health",
            "state": "/api/v1/state",
            "sensor_contracts": "/api/v1/admin/contracts/sensors",
            "sleep_policy": "/api/v1/admin/contracts/sleep",
            "maintenance": "/api/v1/admin/maintenance",
            "adaptive_learning_live": "/api/v1/admin/adaptive/live",
            "acoustic_contract": "/api/v1/admin/contracts/acoustics",
            "acoustic_live": "/api/v1/admin/acoustics/live",
            "usage_sessions": "/api/v1/usage-sessions",
            "usage_users": "/api/v1/usage-sessions/users",
            "user_ai_context": "/api/v1/usage-sessions/longitudinal/ai-context",
        },
        "mutation_policy": {
            "idempotent_set_commands_preferred": True,
            "csrf_required_for_browser_mutations": True,
            "device_ack_is_not_physical_state_proof": True,
            "legacy_control_routes_retained_until_v1_command_ack_contract_is_field_validated": True,
        },
    }


def create_api_v1_router(
    *,
    require_pod_operator: Callable[..., Any],
    require_admin: Callable[..., Any],
    snapshot_for: Callable[[Any], dict[str, Any]],
    public_status: Callable[[], dict[str, Any]],
    sensor_contract_snapshot: Callable[[], dict[str, Any]],
    sleep_policy_snapshot: Callable[[], dict[str, Any]],
    maintenance_contract_snapshot: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["ZEEP API v1"])
    pod_operator = Depends(require_pod_operator)
    admin = Depends(require_admin)

    @router.get("")
    def index():
        return _response(_api_index_data(), kind="api_index")

    @router.get("/public/health")
    def health():
        return _response(public_status(), kind="pod_health")

    @router.get("/state")
    def state(principal: Any = pod_operator):
        return _response(snapshot_for(principal), kind="pod_state")

    @router.get("/admin/contracts/sensors")
    def sensor_contracts(_: Any = admin):
        return _response(sensor_contract_snapshot(), kind="sensor_contracts")

    @router.get("/admin/contracts/sleep")
    def sleep_contract(_: Any = admin):
        return _response(sleep_policy_snapshot(), kind="sleep_policy")

    @router.get("/admin/contracts/acoustics")
    def acoustic_contract(response: Response, _: Any = admin):
        response.headers["Cache-Control"] = "private, no-store"
        return _response(
            acoustic_contract_snapshot(),
            kind="acoustic_intelligence_contract",
        )

    @router.get("/admin/maintenance")
    def maintenance(_: Any = admin):
        return _response(maintenance_contract_snapshot(), kind="maintenance_contract")

    @router.get("/admin/adaptive/live")
    def adaptive_live(
        response: Response,
        principal: Any = admin,
    ):
        response.headers["Cache-Control"] = "private, no-store"
        data = snapshot_for(principal).get("adaptive_learning") or {}
        return _response(data, kind="adaptive_learning_live")

    @router.get("/admin/acoustics/live")
    def acoustic_live(
        response: Response,
        principal: Any = admin,
    ):
        response.headers["Cache-Control"] = "private, no-store"
        data = snapshot_for(principal).get("acoustic_intelligence") or {}
        return _response(data, kind="acoustic_intelligence_live")

    return router
