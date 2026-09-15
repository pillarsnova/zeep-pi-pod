"""MQTT reader for Sensor Hub 2 environment telemetry."""

from __future__ import annotations

import json
import socket
import time
from collections.abc import Callable, MutableMapping
from typing import Any


def run_sensorhub2_reader(
    *,
    mqtt_module: Any,
    mqtt_available: bool,
    mqtt_host: str,
    mqtt_port: int,
    mqtt_keepalive: int,
    telemetry_topic: str,
    status_topic: str,
    shared_state: MutableMapping[str, Any],
    shared_state_lock: Any,
    decode_payload: Callable[..., dict[str, Any]],
    event_logger: Callable[..., None],
) -> None:
    """Subscribe forever without coupling the reader to the FastAPI module."""
    if not mqtt_available:
        event_logger("sensorhub2", "mqtt_library_missing", install="paho-mqtt")
        with shared_state_lock:
            shared_state["sensor"]["sensorhub2"]["error"] = "paho-mqtt is not installed"
        return

    def on_connect(client, _userdata, _flags, reason_code, _properties=None):
        if reason_code == 0:
            client.subscribe([(telemetry_topic, 0), (status_topic, 0)])
            event_logger(
                "sensorhub2",
                "mqtt_connected",
                host=mqtt_host,
                port=mqtt_port,
            )
        else:
            event_logger(
                "sensorhub2",
                "mqtt_connect_failed",
                reason=str(reason_code),
            )

    def on_disconnect(
        _client,
        _userdata,
        _disconnect_flags,
        reason_code,
        _properties=None,
    ):
        with shared_state_lock:
            hub = dict(shared_state["sensor"].get("sensorhub2") or {})
            hub["connected"] = False
            hub["error"] = f"MQTT disconnected: {reason_code}"
            shared_state["sensor"]["sensorhub2"] = hub
        event_logger(
            "sensorhub2",
            "mqtt_disconnected",
            reason=str(reason_code),
        )

    def on_message(_client, _userdata, message):
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload is not a JSON object")
            _publish_payload(
                message.topic,
                payload,
                telemetry_topic=telemetry_topic,
                shared_state=shared_state,
                shared_state_lock=shared_state_lock,
                decode_payload=decode_payload,
            )
        except Exception as exc:
            event_logger(
                "sensorhub2",
                "invalid_mqtt_payload",
                topic=message.topic,
                error=str(exc),
            )

    _run_mqtt_loop(
        mqtt_module=mqtt_module,
        mqtt_host=mqtt_host,
        mqtt_port=mqtt_port,
        mqtt_keepalive=mqtt_keepalive,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        on_message=on_message,
        shared_state=shared_state,
        shared_state_lock=shared_state_lock,
        event_logger=event_logger,
    )


def _run_mqtt_loop(
    *,
    mqtt_module: Any,
    mqtt_host: str,
    mqtt_port: int,
    mqtt_keepalive: int,
    on_connect: Callable[..., None],
    on_disconnect: Callable[..., None],
    on_message: Callable[..., None],
    shared_state: MutableMapping[str, Any],
    shared_state_lock: Any,
    event_logger: Callable[..., None],
) -> None:
    while True:
        try:
            client = mqtt_module.Client(
                mqtt_module.CallbackAPIVersion.VERSION2,
                client_id=f"zeep-pi5-dashboard-{socket.gethostname()}",
            )
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.on_message = on_message
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            client.connect(mqtt_host, mqtt_port, mqtt_keepalive)
            client.loop_forever(retry_first_connection=True)
        except Exception as exc:
            event_logger("sensorhub2", "mqtt_error", error=str(exc))
            with shared_state_lock:
                hub = dict(shared_state["sensor"].get("sensorhub2") or {})
                hub["connected"] = False
                hub["error"] = str(exc)
                shared_state["sensor"]["sensorhub2"] = hub
            time.sleep(5)


def _publish_payload(
    topic: str,
    payload: dict[str, Any],
    *,
    telemetry_topic: str,
    shared_state: MutableMapping[str, Any],
    shared_state_lock: Any,
    decode_payload: Callable[..., dict[str, Any]],
) -> None:
    now = time.time()
    with shared_state_lock:
        previous = dict(shared_state["sensor"].get("sensorhub2") or {})
        if topic == telemetry_topic:
            projected = decode_payload(payload, expected_hub="sensorhub2")
            projected.update(
                {
                    "connected": True,
                    "transport": "mqtt",
                    "topic": topic,
                    "last_update": now,
                    "stale": False,
                }
            )
            projected.pop("error", None)
            shared_state["sensor"]["sensorhub2"] = projected
            return
        previous["mqtt_status"] = payload
        previous["status_last_update"] = now
        if payload.get("online") is False:
            previous["connected"] = False
        shared_state["sensor"]["sensorhub2"] = previous
