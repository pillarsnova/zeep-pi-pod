"""Transport adapter for Sensor Hub 1 USB JSONL telemetry.

The ESP32 shares one serial port between telemetry, boot messages and command
responses.  This adapter keeps those concerns outside the FastAPI composition
root and treats malformed input as a packet-local failure.  Sensor policy and
normalization remain injectable so this module is straightforward to test.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Callable, Mapping, MutableMapping, MutableSequence

from sensor_contracts import classify_hub_payload, decode_hub_payload


Payload = dict[str, Any]
EventLogger = Callable[..., None]


class SensorHub1StateStore:
    """Thread-safe bridge from the adapter to the shared process snapshot."""

    def __init__(
        self,
        *,
        sensor_state: MutableMapping[str, Any],
        state_lock: Any,
        sound_history: MutableSequence[Mapping[str, Any]],
        sound_history_lock: Any,
    ) -> None:
        self.sensor_state = sensor_state
        self.state_lock = state_lock
        self.sound_history = sound_history
        self.sound_history_lock = sound_history_lock

    def previous_payload(self) -> Payload:
        with self.state_lock:
            return dict(self.sensor_state.get("esp32", {}) or {})

    def publish_payload(self, payload: Payload) -> None:
        with self.state_lock:
            self.sensor_state["esp32"] = payload

    def publish_disconnect(self, exc: Exception) -> None:
        with self.state_lock:
            previous = dict(self.sensor_state.get("esp32", {}) or {})
            previous.update(connected=False, error=str(exc))
            self.sensor_state["esp32"] = previous

    def append_sound(self, sample: Mapping[str, Any]) -> None:
        with self.sound_history_lock:
            self.sound_history.append(sample)


class SensorHub1Reader:
    """Continuously ingest Sensor Hub 1 packets without coupling peer sensors."""

    def __init__(
        self,
        *,
        port: str,
        baud: int,
        serial_factory: Callable[..., Any],
        normalize: Callable[[Payload], Payload],
        hold_sound: Callable[[Payload, Payload], Payload],
        previous_payload: Callable[[], Payload],
        publish_payload: Callable[[Payload], None],
        publish_disconnect: Callable[[Exception], None],
        append_sound: Callable[[Mapping[str, Any]], None],
        log_event: EventLogger,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.port = port
        self.baud = baud
        self.serial_factory = serial_factory
        self.normalize = normalize
        self.hold_sound = hold_sound
        self.previous_payload = previous_payload
        self.publish_payload = publish_payload
        self.publish_disconnect = publish_disconnect
        self.append_sound = append_sound
        self.log_event = log_event
        self.clock = clock
        self.sleeper = sleeper
        self.last_sound_status: tuple[bool, Any] | None = None

    def run_forever(self) -> None:
        """Reconnect indefinitely while keeping parse failures packet-local."""
        last_error: str | None = None
        while True:
            try:
                with self.serial_factory(
                    self.port, self.baud, timeout=1,
                ) as connection:
                    self.log_event(
                        "esp32", "connected", port=self.port, baud=self.baud,
                    )
                    last_error = None
                    while True:
                        raw = connection.readline()
                        if raw:
                            self.process_line(raw)
            except Exception as exc:  # Transport failures require reconnect.
                if str(exc) != last_error:
                    self.log_event("esp32", "disconnected", error=str(exc))
                    last_error = str(exc)
                self.publish_disconnect(exc)
                self.sleeper(2)

    def process_line(self, raw: bytes) -> bool:
        """Validate and publish one JSONL packet; return whether it was used."""
        try:
            payload = json.loads(raw.decode("utf-8", errors="strict").strip())
        except (UnicodeError, json.JSONDecodeError) as exc:
            self.log_event(
                "esp32", "payload_rejected",
                reason="invalid_json", error=str(exc),
            )
            return False

        disposition, reason = classify_hub_payload(
            payload, expected_hub="sensorhub1",
        )
        if disposition == "ignored":
            self.log_event("esp32", "control_event_ignored", event=reason)
            return False
        if disposition == "rejected":
            self.log_event("esp32", "payload_rejected", reason=reason)
            return False

        try:
            normalized = decode_hub_payload(
                payload, expected_hub="sensorhub1",
            )
            normalized = self.normalize(normalized)
        except (TypeError, ValueError, OverflowError) as exc:
            self.log_event(
                "esp32", "payload_rejected",
                reason="contract_error", error=str(exc),
            )
            return False

        normalized["connected"] = True
        normalized["last_update"] = self.clock()
        normalized = self.hold_sound(normalized, self.previous_payload())
        self.publish_payload(normalized)
        self._publish_sound_state(normalized)
        return True

    def _publish_sound_state(self, payload: Mapping[str, Any]) -> None:
        status = (
            bool(payload.get("sound_measurement_valid")),
            payload.get("sound_invalid_reason"),
        )
        if status != self.last_sound_status:
            self.log_event(
                "sph0645",
                "measurement_valid" if status[0] else "measurement_invalid",
                reason=status[1],
            )
            self.last_sound_status = status

        sound = payload.get("sound_dba_est")
        sound_is_finite = False
        if isinstance(sound, (int, float)) and not isinstance(sound, bool):
            try:
                sound_is_finite = math.isfinite(float(sound))
            except OverflowError:
                sound_is_finite = False
        if payload.get("sound_measurement_valid") is True and sound_is_finite:
            self.append_sound({
                "t": payload["last_update"],
                "dba": float(sound),
                "dbfs": payload.get("sound_dbfs"),
            })
