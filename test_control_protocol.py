"""Side-effect-free contracts for device command normalization."""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from control_protocol import (
    AIRCON_TEMPERATURE_MAX_C,
    AIRCON_TEMPERATURE_MIN_C,
    normalize_aircon_command,
    normalize_bed_command,
    resolve_aircon_temperature_command,
)
from zeep_pod.hardware import controlhub2


class AirconProtocolTests(unittest.TestCase):
    def test_normalizes_fixed_and_temperature_commands(self) -> None:
        self.assertEqual(normalize_aircon_command("  SWING_ON  "), "swing_on")
        self.assertEqual(normalize_aircon_command("temp   18"), "temp 18")
        self.assertEqual(normalize_aircon_command("temp 15"), "temp 15")
        self.assertEqual(normalize_aircon_command("temp 28"), "temp 28")
        for temperature_c in (14, 29):
            with self.assertRaises(ValueError):
                normalize_aircon_command(f"temp {temperature_c}")

    def test_temperature_mapping_is_direct_and_bounded(self) -> None:
        self.assertEqual(
            resolve_aircon_temperature_command("temp 20"),
            ("temp 20", 20, 20),
        )
        self.assertEqual(
            resolve_aircon_temperature_command("swing_on"),
            ("swing_on", None, None),
        )
        self.assertEqual(AIRCON_TEMPERATURE_MIN_C, 15)
        self.assertEqual(AIRCON_TEMPERATURE_MAX_C, 28)
        for temperature_c in (14, 29):
            with self.assertRaises(ValueError):
                resolve_aircon_temperature_command(f"temp {temperature_c}")


class BedProtocolTests(unittest.TestCase):
    def test_only_bounded_one_shot_and_reference_commands_are_accepted(self) -> None:
        self.assertEqual(normalize_bed_command(" HEAD_UP "), "head_up")
        self.assertEqual(normalize_bed_command("bed_stop"), "bed_stop")
        with self.assertRaises(ValueError):
            normalize_bed_command("run_forever")


class ControlHub2AdapterTests(unittest.TestCase):
    def _adapter_context(self, bed_state):
        state = {"bed_control": dict(bed_state)}
        return (
            controlhub2.ControlHub2BedMQTT(),
            state,
            patch.multiple(
                controlhub2,
                create=True,
                state=state,
                state_lock=threading.Lock(),
                STALE_SECONDS=10.0,
                ACK_TIMEOUT_SECONDS=0.001,
                COMMAND_TOPIC="zeep/bed/command",
                STATUS_TOPIC="zeep/bed/status",
                EVENT_TOPIC="zeep/bed/event",
                mqtt=SimpleNamespace(MQTT_ERR_SUCCESS=0),
                log_event=Mock(),
                safety_allows=Mock(),
            ),
        )

    def test_repeated_active_direction_resolves_to_stop(self) -> None:
        adapter, _state, context = self._adapter_context(
            {
                "connected": True,
                "last_update": time.time(),
                "active_command": "head_up",
            }
        )
        with context:
            self.assertEqual(adapter._prepare_command("head_up", True), "bed_stop")
            controlhub2.safety_allows.assert_not_called()

    def test_motion_requires_fresh_status_and_safety_approval(self) -> None:
        adapter, _state, context = self._adapter_context(
            {"connected": True, "last_update": time.time()}
        )
        with context:
            self.assertEqual(adapter._prepare_command("foot_down", False), "foot_down")
            controlhub2.safety_allows.assert_called_once_with("Bed foot_down")

        adapter, _state, context = self._adapter_context(
            {"connected": True, "last_update": time.time() - 11.0}
        )
        with context, self.assertRaises(HTTPException) as raised:
            adapter._prepare_command("foot_down", False)
        self.assertEqual(raised.exception.status_code, 503)

    def test_publish_uses_non_retained_command_message(self) -> None:
        adapter, _state, context = self._adapter_context({})
        client = Mock()
        client.is_connected.return_value = True
        client.publish.return_value = SimpleNamespace(rc=0)
        adapter._set_client(client)

        with context:
            adapter._publish("bed_stop")

        client.publish.assert_called_once_with(
            "zeep/bed/command",
            "bed_stop",
            qos=0,
            retain=False,
        )

    def test_event_updates_state_and_releases_matching_ack(self) -> None:
        adapter, state, context = self._adapter_context({})
        message = SimpleNamespace(
            topic="zeep/bed/event",
            payload=b'{"command":"head_up","ok":true,"active_servo":false}',
        )

        with context:
            adapter._on_message(None, None, message)

        self.assertEqual(adapter._ack_seq, 1)
        self.assertEqual(state["bed_control"]["last_command"], "head_up")
        self.assertFalse(state["bed_control"]["active_servo"])
        self.assertTrue(state["bed_control"]["connected"])

    def test_ack_matching_and_timeout_are_explicit(self) -> None:
        adapter, state, context = self._adapter_context({})

        def acknowledge(command):
            with adapter._ack_condition:
                adapter._ack_seq += 1
                adapter._last_ack = (
                    {"command": command, "ok": True},
                    time.time(),
                )

        with context, patch.object(adapter, "_publish", side_effect=acknowledge):
            acknowledgement = adapter._await_acknowledgement(
                "head_up",
                requested_command="head_up",
            )
        self.assertTrue(acknowledgement["ok"])
        self.assertTrue(state["bed_control"]["command_pending"])

        adapter, state, context = self._adapter_context({})
        with (
            context,
            patch.object(adapter, "_publish"),
            self.assertRaises(HTTPException) as raised,
        ):
            adapter._await_acknowledgement(
                "head_up",
                requested_command="head_up",
            )
        self.assertEqual(raised.exception.status_code, 504)
        self.assertEqual(state["bed_control"]["last_command_error"], "ack_timeout")

    def test_public_command_releases_lock_and_pending_state_after_error(self) -> None:
        adapter, state, context = self._adapter_context({})
        acknowledgements = [
            HTTPException(504, "timeout"),
            {"command": "head_up", "ok": True},
        ]
        with (
            context,
            patch.object(adapter, "_prepare_command", return_value="head_up"),
            patch.object(
                adapter,
                "_await_acknowledgement",
                side_effect=acknowledgements,
            ),
        ):
            with self.assertRaises(HTTPException):
                adapter.publish_and_wait("head_up")
            acknowledgement, command = adapter.publish_and_wait("head_up")

        self.assertTrue(acknowledgement["ok"])
        self.assertEqual(command, "head_up")
        self.assertFalse(state["bed_control"]["command_pending"])
        self.assertIsNone(state["bed_control"]["pending_command"])


if __name__ == "__main__":
    unittest.main()
