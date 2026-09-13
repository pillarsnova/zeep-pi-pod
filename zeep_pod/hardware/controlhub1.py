"""MQTT transport adapter for the Control Hub 1 air-conditioner bridge.

The FastAPI composition root owns process configuration and shared state.  It
injects those dependencies here once at startup so the transport can remain in
the hardware package without importing :mod:`app`.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, MutableMapping
from typing import Any

from fastapi import HTTPException

mqtt: Any
MQTT_AVAILABLE: bool
MQTT_HOST: str
MQTT_PORT: int
MQTT_KEEPALIVE: int
CONTROLHUB1_COMMAND_TOPIC: str
CONTROLHUB1_STATUS_TOPIC: str
CONTROLHUB1_EVENT_TOPIC: str
CONTROLHUB1_STALE_SECONDS: float
CONTROLHUB1_ACK_TIMEOUT_SECONDS: float
CONTROLHUB1_MIN_IR_GAP_SECONDS: float
state: MutableMapping[str, Any]
state_lock: Any
log_event: Callable[..., None]


def configure_controlhub1(
    *,
    mqtt_module: Any,
    mqtt_available: bool,
    mqtt_host: str,
    mqtt_port: int,
    mqtt_keepalive: int,
    command_topic: str,
    status_topic: str,
    event_topic: str,
    stale_seconds: float,
    ack_timeout_seconds: float,
    min_ir_gap_seconds: float,
    shared_state: MutableMapping[str, Any],
    shared_state_lock: Any,
    event_logger: Callable[..., None],
) -> None:
    """Install dependencies supplied by the process composition root."""
    global mqtt, MQTT_AVAILABLE, MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE
    global CONTROLHUB1_COMMAND_TOPIC, CONTROLHUB1_STATUS_TOPIC
    global CONTROLHUB1_EVENT_TOPIC, CONTROLHUB1_STALE_SECONDS
    global CONTROLHUB1_ACK_TIMEOUT_SECONDS, CONTROLHUB1_MIN_IR_GAP_SECONDS
    global state, state_lock, log_event

    mqtt = mqtt_module
    MQTT_AVAILABLE = mqtt_available
    MQTT_HOST = mqtt_host
    MQTT_PORT = mqtt_port
    MQTT_KEEPALIVE = mqtt_keepalive
    CONTROLHUB1_COMMAND_TOPIC = command_topic
    CONTROLHUB1_STATUS_TOPIC = status_topic
    CONTROLHUB1_EVENT_TOPIC = event_topic
    CONTROLHUB1_STALE_SECONDS = stale_seconds
    CONTROLHUB1_ACK_TIMEOUT_SECONDS = ack_timeout_seconds
    CONTROLHUB1_MIN_IR_GAP_SECONDS = min_ir_gap_seconds
    state = shared_state
    state_lock = shared_state_lock
    log_event = event_logger


class ControlHub1MQTT:
    """MQTT command/ack bridge for the ESP32-S3 air-conditioner IR hub.

    This uses a separate client from Sensor Hub 2 so a control regression cannot
    replace or interrupt the proven telemetry reader. Commands are serialized
    because the current ESP32 event schema has no unique command_id.
    """

    def __init__(self):
        self._client = None
        self._client_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._ack_condition = threading.Condition()
        self._ack_seq = 0
        self._last_ack = None
        # Monotonic time of the latest ESP acknowledgement for a command that
        # emits IR. Access is protected by _command_lock.
        self._last_ir_ack_monotonic = None

    def _set_client(self, client):
        with self._client_lock:
            self._client = client

    def _get_client(self):
        with self._client_lock:
            return self._client

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        if reason_code == 0:
            self._set_client(client)
            client.subscribe(
                [
                    (CONTROLHUB1_STATUS_TOPIC, 0),
                    (CONTROLHUB1_EVENT_TOPIC, 0),
                ]
            )
            with state_lock:
                state["aircon"]["mqtt_connected"] = True
                state["aircon"].pop("mqtt_error", None)
            log_event("controlhub1", "mqtt_connected", host=MQTT_HOST, port=MQTT_PORT)
        else:
            log_event("controlhub1", "mqtt_connect_failed", reason=str(reason_code))

    def _on_disconnect(self, client, _userdata, _disconnect_flags, reason_code, _properties=None):
        with self._client_lock:
            if self._client is client:
                self._client = None
        with state_lock:
            aircon = dict(state.get("aircon") or {})
            aircon["connected"] = False
            aircon["mqtt_connected"] = False
            aircon["error"] = f"MQTT disconnected: {reason_code}"
            aircon["command_pending"] = False
            aircon["pending_command"] = None
            state["aircon"] = aircon
        with self._ack_condition:
            self._ack_condition.notify_all()
        log_event("controlhub1", "mqtt_disconnected", reason=str(reason_code))

    def _on_message(self, _client, _userdata, message):
        try:
            obj = json.loads(message.payload.decode("utf-8"))
            if not isinstance(obj, dict):
                raise ValueError("payload is not a JSON object")
            now = time.time()
            with state_lock:
                aircon = dict(state.get("aircon") or {})
                if message.topic == CONTROLHUB1_STATUS_TOPIC:
                    aircon.update(obj)
                    aircon["connected"] = obj.get("online") is not False
                    aircon["transport"] = "mqtt"
                    aircon["status_last_update"] = now
                else:
                    aircon["connected"] = True
                    aircon["last_event"] = obj
                    aircon["last_command"] = obj.get("command")
                    aircon["last_command_ok"] = bool(obj.get("ok"))
                    aircon["event_last_update"] = now
                    if obj.get("tx_count") is not None:
                        aircon["tx_count"] = obj.get("tx_count")
                aircon["last_update"] = now
                aircon["stale"] = False
                aircon["mqtt_connected"] = True
                aircon.pop("error", None)
                state["aircon"] = aircon

            if message.topic == CONTROLHUB1_EVENT_TOPIC:
                with self._ack_condition:
                    self._ack_seq += 1
                    self._last_ack = (dict(obj), now)
                    self._ack_condition.notify_all()
        except Exception as exc:
            log_event(
                "controlhub1",
                "invalid_mqtt_payload",
                topic=message.topic,
                error=str(exc),
            )

    def run(self):
        if not MQTT_AVAILABLE:
            with state_lock:
                state["aircon"]["error"] = "paho-mqtt is not installed"
            log_event("controlhub1", "mqtt_library_missing", install="paho-mqtt")
            return

        while True:
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"zeep-pi5-controlhub1-{socket.gethostname()}",
                )
                client.on_connect = self._on_connect
                client.on_disconnect = self._on_disconnect
                client.on_message = self._on_message
                client.reconnect_delay_set(min_delay=1, max_delay=30)
                client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
                client.loop_forever(retry_first_connection=True)
            except Exception as exc:
                self._set_client(None)
                with state_lock:
                    aircon = dict(state.get("aircon") or {})
                    aircon["connected"] = False
                    aircon["mqtt_connected"] = False
                    aircon["error"] = str(exc)
                    state["aircon"] = aircon
                log_event("controlhub1", "mqtt_error", error=str(exc))
                time.sleep(5)

    @staticmethod
    def _emits_ir(command: str) -> bool:
        """STATUS reads state only; every other current command emits IR."""
        return command != "status"

    def _wait_for_ir_guard(self, command: str, minimum_gap_seconds: float | None) -> float:
        if not self._emits_ir(command) or self._last_ir_ack_monotonic is None:
            return 0.0
        required_gap = max(
            CONTROLHUB1_MIN_IR_GAP_SECONDS,
            float(minimum_gap_seconds or 0.0),
        )
        elapsed = time.monotonic() - self._last_ir_ack_monotonic
        wait_seconds = max(0.0, required_gap - elapsed)
        if wait_seconds > 0:
            log_event(
                "controlhub1",
                "ir_guard_wait",
                command=command,
                wait_seconds=round(wait_seconds, 3),
                required_gap_seconds=required_gap,
            )
            time.sleep(wait_seconds)
        return wait_seconds

    def _publish_and_wait_locked(
        self,
        command: str,
        minimum_gap_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Publish one command while the caller owns _command_lock."""
        self._wait_for_ir_guard(command, minimum_gap_seconds)
        now = time.time()
        with state_lock:
            aircon = dict(state.get("aircon") or {})
            last_update = aircon.get("last_update")
            fresh = isinstance(last_update, (int, float)) and (now - last_update <= CONTROLHUB1_STALE_SECONDS)
            online = bool(aircon.get("connected") and fresh)
        client = self._get_client()
        if client is None or not client.is_connected() or not online:
            raise HTTPException(503, "Control Hub 1 ไม่เชื่อมต่อ")

        with self._ack_condition:
            initial_ack_seq = self._ack_seq

        with state_lock:
            state["aircon"]["command_pending"] = True
            state["aircon"]["pending_command"] = command
            state["aircon"].pop("last_command_error", None)

        # retain=False is mandatory: an old command must never replay when
        # the ESP32 reconnects. QoS 0 matches the current firmware; changing
        # to QoS 1 could duplicate a toggle-style IR command.
        info = client.publish(CONTROLHUB1_COMMAND_TOPIC, command, qos=0, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise HTTPException(503, f"MQTT publish failed: {info.rc}")

        log_event("controlhub1", "command_published", command=command)
        deadline = time.monotonic() + CONTROLHUB1_ACK_TIMEOUT_SECONDS
        acknowledgement = None
        with self._ack_condition:
            while time.monotonic() < deadline:
                if self._ack_seq > initial_ack_seq and self._last_ack:
                    candidate, received_at = self._last_ack
                    if received_at >= now and candidate.get("command") == command:
                        acknowledgement = dict(candidate)
                        break
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._ack_condition.wait(remaining)

        if acknowledgement is None:
            with state_lock:
                state["aircon"]["last_command_error"] = "ack_timeout"
            log_event("controlhub1", "command_ack_timeout", command=command)
            raise HTTPException(
                504,
                "ส่ง MQTT แล้ว แต่ไม่ได้รับคำยืนยันจาก Control Hub 1",
            )
        if acknowledgement.get("ok") is not True:
            detail = acknowledgement.get("detail") or "command rejected"
            log_event("controlhub1", "command_rejected", command=command, detail=detail)
            raise HTTPException(502, f"Control Hub 1 ปฏิเสธคำสั่ง: {detail}")

        if self._emits_ir(command):
            self._last_ir_ack_monotonic = time.monotonic()
        # The current ESP event confirms that its IR send routine ran. There
        # is no feedback wire from the air conditioner, so this must never be
        # presented as proof that the appliance changed state.
        log_event(
            "controlhub1",
            "command_acknowledged",
            command=command,
            tx_count=acknowledgement.get("tx_count"),
            acknowledgement_scope="esp_ir_transmit_only",
        )
        return acknowledgement

    def publish_sequence_and_wait(
        self,
        commands: list[str],
        minimum_gaps_before: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """Run an atomic IR sequence so another request cannot interleave."""
        if not commands:
            return []
        if minimum_gaps_before is not None and (len(minimum_gaps_before) != len(commands)):
            raise ValueError("minimum_gaps_before must match commands")
        if not self._command_lock.acquire(blocking=False):
            raise HTTPException(429, "Air Con command already in progress")
        try:
            acknowledgements = []
            for index, command in enumerate(commands):
                minimum_gap = minimum_gaps_before[index] if minimum_gaps_before is not None else None
                acknowledgements.append(self._publish_and_wait_locked(command, minimum_gap))
            return acknowledgements
        finally:
            with state_lock:
                state["aircon"]["command_pending"] = False
                state["aircon"]["pending_command"] = None
            self._command_lock.release()

    def publish_and_wait(self, command: str) -> dict[str, Any]:
        return self.publish_sequence_and_wait([command])[0]
