"""Durable repository for the air-conditioner fan-cycle reference.

The installed air conditioner acknowledges an IR transmission but does not
report its physical fan speed. This repository therefore stores operator
intent, not measured telemetry. Construction is deliberately free of I/O so
the composition root can initialize it during the application lifespan.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AIRCON_REFERENCE_SCHEMA_VERSION = 1
AIRCON_FAN_LEVEL_MIN = 1
AIRCON_FAN_LEVEL_MAX = 5

InvalidReferenceHandler = Callable[[Exception], None]
Clock = Callable[[], datetime]


class AirconFanReferenceStore:
    """Persist the last acknowledged or operator-declared fan step.

    ``initialize`` is the explicit lifecycle boundary. ``__init__`` only
    records dependencies and must never read or create files.
    """

    def __init__(
        self,
        path: Path,
        default_level: int,
        *,
        lock: threading.Lock | None = None,
        clock: Clock | None = None,
        on_invalid: InvalidReferenceHandler | None = None,
    ) -> None:
        self._validate_level(default_level)
        self.path = path
        self.default_level = default_level
        self.lock = lock or threading.Lock()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.on_invalid = on_invalid

    def initialize(self) -> dict[str, Any]:
        """Load a valid reference or atomically establish a safe default."""
        try:
            return self.load()
        except FileNotFoundError:
            return self.save(self.default_level, "pod_default_reference")
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if self.on_invalid is not None:
                self.on_invalid(exc)
            return self.save(self.default_level, "recovered_default_reference")

    def load(self) -> dict[str, Any]:
        """Read and validate one persisted reference without repairing it."""
        with self.lock, self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("aircon fan reference is not an object")
        level = payload.get("fan_level")
        self._validate_level(level)
        source = payload.get("source")
        updated_at = payload.get("updated_at")
        normalized = dict(payload)
        normalized["schema_version"] = AIRCON_REFERENCE_SCHEMA_VERSION
        normalized["source"] = (
            source.strip()
            if isinstance(source, str) and source.strip()
            else "persisted_reference"
        )
        normalized["updated_at"] = (
            updated_at.strip()
            if isinstance(updated_at, str) and updated_at.strip()
            else None
        )
        return normalized

    def save(
        self,
        level: int,
        source: str,
        *,
        operator: str | None = None,
    ) -> dict[str, Any]:
        """Atomically persist a validated logical fan step."""
        self._validate_level(level)
        normalized_source = str(source or "unknown").strip() or "unknown"
        payload: dict[str, Any] = {
            "schema_version": AIRCON_REFERENCE_SCHEMA_VERSION,
            "fan_level": level,
            "source": normalized_source,
            "updated_at": self.clock().isoformat(),
        }
        if operator:
            payload["operator"] = str(operator)[:120]
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        return payload

    @staticmethod
    def _validate_level(level: Any) -> None:
        if (
            not isinstance(level, int)
            or isinstance(level, bool)
            or not AIRCON_FAN_LEVEL_MIN <= level <= AIRCON_FAN_LEVEL_MAX
        ):
            raise ValueError("aircon fan level reference must be between 1 and 5")
