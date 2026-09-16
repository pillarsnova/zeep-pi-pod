"""Shared, traceable response envelopes for versioned ZEEP APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

API_VERSION = "1.0"
API_SCHEMA = "zeep.api.response"


def response_envelope(data: Any, *, kind: str) -> dict[str, Any]:
    """Wrap versioned API data in the canonical response envelope."""
    return {
        "schema": API_SCHEMA,
        "api_version": API_VERSION,
        "kind": kind,
        "generated_at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "request_id": str(uuid4()),
        "data": data,
    }
