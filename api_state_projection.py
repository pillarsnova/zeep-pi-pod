"""Compatibility facade for live API projections moved under ``api``."""

from api.state_projection import (
    CONSUMER_SYSTEM_FIELDS,
    LiveDeviceProjectionPolicy,
    project_aircon_status,
    project_consumer_snapshot,
    project_live_device_statuses,
    project_transport_status,
)

__all__ = (
    "CONSUMER_SYSTEM_FIELDS",
    "LiveDeviceProjectionPolicy",
    "project_aircon_status",
    "project_consumer_snapshot",
    "project_live_device_statuses",
    "project_transport_status",
)
