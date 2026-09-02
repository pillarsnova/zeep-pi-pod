"""Stable, versioned read API for the ZEEP Pod control plane.

Legacy ``/api/*`` routes remain unchanged for the installed tablet.  New
integrations should begin with this envelope so schema/version/time/request-id
metadata is never inferred from UI implementation details.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from fastapi import APIRouter, Depends


API_VERSION = "1.0"
API_SCHEMA = "zeep.api.response"


def _response(data: Any, *, kind: str) -> dict[str, Any]:
    return {
        "schema": API_SCHEMA,
        "api_version": API_VERSION,
        "kind": kind,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "request_id": str(uuid4()),
        "data": data,
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

    @router.get("")
    def index():
        return _response({
            "compatibility": "Existing /api routes remain supported",
            "resources": {
                "health": "/api/v1/public/health",
                "state": "/api/v1/state",
                "sensor_contracts": "/api/v1/admin/contracts/sensors",
                "sleep_policy": "/api/v1/admin/contracts/sleep",
                "maintenance": "/api/v1/admin/maintenance",
            },
            "mutation_policy": {
                "idempotent_set_commands_preferred": True,
                "csrf_required_for_browser_mutations": True,
                "device_ack_is_not_physical_state_proof": True,
                "legacy_control_routes_retained_until_v1_command_ack_contract_is_field_validated": True,
            },
        }, kind="api_index")

    @router.get("/public/health")
    def health():
        return _response(public_status(), kind="pod_health")

    @router.get("/state")
    def state(principal: Any = Depends(require_pod_operator)):
        return _response(snapshot_for(principal), kind="pod_state")

    @router.get("/admin/contracts/sensors")
    def sensor_contracts(_: Any = Depends(require_admin)):
        return _response(sensor_contract_snapshot(), kind="sensor_contracts")

    @router.get("/admin/contracts/sleep")
    def sleep_contract(_: Any = Depends(require_admin)):
        return _response(sleep_policy_snapshot(), kind="sleep_policy")

    @router.get("/admin/maintenance")
    def maintenance(_: Any = Depends(require_admin)):
        return _response(maintenance_contract_snapshot(), kind="maintenance_contract")

    return router
