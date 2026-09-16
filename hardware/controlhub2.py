"""MQTT adapter for the Control Hub 2 adjustable-bed bridge.

The composition root injects process configuration and callbacks once during
startup.  Keeping the transport here prevents MQTT acknowledgements, retries,
and shared-state projection from being mixed with HTTP route handling.
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
COMMAND_TOPIC: str
STATUS_TOPIC: str
EVENT_TOPIC: str
STALE_SECONDS: float
ACK_TIMEOUT_SECONDS: float
state: MutableMapping[str, Any]
state_lock: Any
log_event: Callable[..., None]
safety_allows: Callable[[str], None]


def configure_controlhub2(
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
    shared_state: MutableMapping[str, Any],
    shared_state_lock: Any,
    event_logger: Callable[..., None],
    safety_guard: Callable[[str], None],
) -> None:
    """Install dependencies owned by the process composition root."""
    global mqtt, MQTT_AVAILABLE, MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE
    global COMMAND_TOPIC, STATUS_TOPIC, EVENT_TOPIC
    global STALE_SECONDS, ACK_TIMEOUT_SECONDS
    global state, state_lock, log_event, safety_allows

    mqtt = mqtt_module
    MQTT_AVAILABLE = mqtt_available
    MQTT_HOST = mqtt_host
    MQTT_PORT = mqtt_port
    MQTT_KEEPALIVE = mqtt_keepalive
    COMMAND_TOPIC = command_topic
    STATUS_TOPIC = status_topic
    EVENT_TOPIC = event_topic
    STALE_SECONDS = stale_seconds
    ACK_TIMEOUT_SECONDS = ack_timeout_seconds
    state = shared_state
    state_lock = shared_state_lock
    log_event = event_logger
    safety_allows = safety_guard


class ControlHub2BedMQTT:
    """Serialize bed commands and wait for the matching ESP32 acknowledgement."""

    def __init__(self) -> None:
        self._client = None
        self._client_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._ack_condition = threading.Condition()
        self._ack_seq = 0
        self._last_ack = None

    def _set_client(self, client: Any) -> None:
        with self._client_lock:
            self._client = client

    def _get_client(self) -> Any:
        with self._client_lock:
            return self._client

    def _on_connect(
        self,
        client: Any,
        _userdata: Any,
        _flags: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        if reason_code != 0:
            log_event(
                "controlhub2_bed",
                "mqtt_connect_failed",
                reason=str(reason_code),
            )
            return
        self._set_client(client)
        client.subscribe([(STATUS_TOPIC, 0), (EVENT_TOPIC, 0)])
        with state_lock:
            state["bed_control"]["mqtt_connected"] = True
            state["bed_control"].pop("mqtt_error", None)
        log_event(
            "controlhub2_bed",
            "mqtt_connected",
            host=MQTT_HOST,
            port=MQTT_PORT,
        )

    def _on_disconnect(
        self,
        client: Any,
        _userdata: Any,
        _disconnect_flags: Any,
        reason_code: Any,
        _properties: Any = None,
    ) -> None:
        with self._client_lock:
            if self._client is client:
                self._client = None
        with state_lock:
            bed = dict(state.get("bed_control") or {})
            bed.update(
                {
                    "connected": False,
                    "mqtt_connected": False,
                    "error": f"MQTT disconnected: {reason_code}",
                    "command_pending": False,
                    "pending_command": None,
                }
            )
            state["bed_control"] = bed
        with self._ack_condition:
            self._ack_condition.notify_all()
        log_event(
            "controlhub2_bed",
            "mqtt_disconnected",
            reason=str(reason_code),
        )

    def _on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload is not a JSON object")
            self._publish_state(message.topic, payload)
            if message.topic == EVENT_TOPIC:
                with self._ack_condition:
                    self._ack_seq += 1
                    self._last_ack = (dict(payload), time.time())
                    self._ack_condition.notify_all()
        except Exception as exc:
            log_event(
                "controlhub2_bed",
                "invalid_mqtt_payload",
                topic=message.topic,
                error=str(exc),
            )

    def _publish_state(self, topic: str, payload: dict[str, Any]) -> None:
        now = time.time()
        with state_lock:
            bed = dict(state.get("bed_control") or {})
            if topic == STATUS_TOPIC:
                bed.update(payload)
                bed["connected"] = payload.get("online") is not False
                bed["transport"] = "mqtt"
                bed["status_last_update"] = now
            else:
                bed.update(self._event_state(payload, now))
            bed.update(
                {
                    "last_update": now,
                    "stale": False,
                    "mqtt_connected": True,
                }
            )
            bed.pop("error", None)
            state["bed_control"] = bed

    @staticmethod
    def _event_state(payload: dict[str, Any], now: float) -> dict[str, Any]:
        projected = {
            "connected": True,
            "last_event": payload,
            "last_command": payload.get("command"),
            "last_command_ok": bool(payload.get("ok")),
            "event_last_update": now,
        }
        for key in ("command_count", "active_command"):
            if key in payload and payload.get(key) is not None:
                projected[key] = payload.get(key)
        if "active_servo" in payload:
            projected["active_servo"] = payload.get("active_servo")
        return projected

    def run(self) -> None:
        """Maintain the dedicated MQTT connection for this hardware bridge."""
        if not MQTT_AVAILABLE:
            with state_lock:
                state["bed_control"]["error"] = "paho-mqtt is not installed"
            log_event(
                "controlhub2_bed",
                "mqtt_library_missing",
                install="paho-mqtt",
            )
            return
        while True:
            try:
                self._connect_forever()
            except Exception as exc:
                self._record_disconnect(exc)
                time.sleep(5)

    def _connect_forever(self) -> None:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"zeep-pi5-controlhub2-bed-{socket.gethostname()}",
        )
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        client.loop_forever(retry_first_connection=True)

    def _record_disconnect(self, exc: Exception) -> None:
        self._set_client(None)
        with state_lock:
            bed = dict(state.get("bed_control") or {})
            bed.update(
                {
                    "connected": False,
                    "mqtt_connected": False,
                    "error": str(exc),
                }
            )
            state["bed_control"] = bed
        log_event("controlhub2_bed", "mqtt_error", error=str(exc))

    def _publish(self, command: str) -> None:
        client = self._get_client()
        if client is None or not client.is_connected():
            raise HTTPException(503, "Control Hub 2 Bed ไม่เชื่อมต่อ")
        info = client.publish(COMMAND_TOPIC, command, qos=0, retain=False)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            raise HTTPException(503, f"MQTT publish failed: {info.rc}")

    def publish_stop_best_effort(self, reason: str = "safety") -> bool:
        """Publish a non-blocking safety stop and never raise."""
        try:
            self._publish("bed_stop")
            log_event("controlhub2_bed", "stop_published", reason=reason)
            return True
        except Exception as exc:
            log_event(
                "controlhub2_bed",
                "stop_failed",
                reason=reason,
                error=str(exc),
            )
            return False

    def publish_and_wait(
        self,
        requested_command: str,
        toggle_repeat: bool = False,
    ) -> tuple[dict[str, Any], str]:
        """Publish one command and return its acknowledgement and resolved command."""
        if not self._command_lock.acquire(blocking=False):
            raise HTTPException(429, "Bed command already in progress")
        try:
            command = self._prepare_command(requested_command, toggle_repeat)
            acknowledgement = self._await_acknowledgement(
                command,
                requested_command=requested_command,
            )
            if acknowledgement.get("ok") is not True:
                detail = acknowledgement.get("detail") or "command rejected"
                raise HTTPException(
                    502,
                    f"Control Hub 2 Bed ปฏิเสธคำสั่ง: {detail}",
                )
            log_event(
                "controlhub2_bed",
                "command_acknowledged",
                command=command,
                command_count=acknowledgement.get("command_count"),
            )
            return acknowledgement, command
        finally:
            with state_lock:
                state["bed_control"]["command_pending"] = False
                state["bed_control"]["pending_command"] = None
            self._command_lock.release()

    def _prepare_command(self, requested: str, toggle_repeat: bool) -> str:
        now = time.time()
        with state_lock:
            bed = dict(state.get("bed_control") or {})
        last_update = bed.get("last_update")
        fresh = isinstance(last_update, (int, float)) and (
            now - last_update <= STALE_SECONDS
        )
        if not bed.get("connected") or not fresh:
            raise HTTPException(503, "Control Hub 2 Bed ไม่เชื่อมต่อ")
        directional = {"head_up", "head_down", "foot_up", "foot_down"}
        command = requested
        if toggle_repeat and requested in directional:
            if bed.get("active_command") == requested:
                command = "bed_stop"
        if command not in {"bed_stop", "status"}:
            safety_allows(f"Bed {command}")
        return command

    def _await_acknowledgement(
        self,
        command: str,
        *,
        requested_command: str,
    ) -> dict[str, Any]:
        now = time.time()
        with self._ack_condition:
            initial_ack_seq = self._ack_seq
        with state_lock:
            state["bed_control"]["command_pending"] = True
            state["bed_control"]["pending_command"] = command
            state["bed_control"].pop("last_command_error", None)
        self._publish(command)
        log_event(
            "controlhub2_bed",
            "command_published",
            requested_command=requested_command,
            command=command,
        )
        deadline = time.monotonic() + ACK_TIMEOUT_SECONDS
        with self._ack_condition:
            while time.monotonic() < deadline:
                if self._ack_seq > initial_ack_seq and self._last_ack:
                    candidate, received_at = self._last_ack
                    if received_at >= now and candidate.get("command") == command:
                        return dict(candidate)
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    self._ack_condition.wait(remaining)
        with state_lock:
            state["bed_control"]["last_command_error"] = "ack_timeout"
        raise HTTPException(
            504,
            "ส่ง MQTT แล้ว แต่ไม่ได้รับคำยืนยันจาก Control Hub 2 Bed",
        )
