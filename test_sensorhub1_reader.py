"""Regression tests for the modular Sensor Hub 1 USB adapter."""

from __future__ import annotations

import json
import threading
import unittest

from zeep_pod.hardware.sensorhub1 import SensorHub1Reader, SensorHub1StateStore


def canonical_packet(*, sound_valid: bool = True) -> dict:
    return {
        "schema": "zeep.sensor.telemetry",
        "version": "1.0",
        "event": "environment",
        "hub_id": "sensorhub1",
        "firmware_version": "test-v1",
        "boot_id": 91,
        "sequence": 8,
        "sensors": {
            "sht3x_dis": {
                "status": "live",
                "values": {"temperature_c": 24.5, "humidity_rh": 52.0},
            },
            "opt3001": {
                "status": "live",
                "values": {"lux": 1.2},
            },
            "sph0645": {
                "status": "live" if sound_valid else "invalid",
                "reason": None if sound_valid else "pcm_all_zero",
                "values": {
                    "sound_dbfs": -55.0,
                    "sound_laeq_dba": 42.5 if sound_valid else None,
                    "sound_valid": sound_valid,
                    "sound_weighting": "A",
                    "sound_metric": "LAeq",
                    "sound_window_ms": 10_000,
                    "sound_window_sequence": 7,
                },
            },
        },
    }


class SensorHub1ReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.events: list[tuple[tuple, dict]] = []
        self.payloads: list[dict] = []
        self.sounds: list[dict] = []
        self.reader = SensorHub1Reader(
            port="test-port",
            baud=115_200,
            serial_factory=lambda *_args, **_kwargs: None,
            normalize=self.normalize,
            hold_sound=lambda current, _previous: current,
            previous_payload=lambda: {},
            publish_payload=self.payloads.append,
            publish_disconnect=lambda _exc: None,
            append_sound=self.sounds.append,
            log_event=lambda *args, **kwargs: self.events.append(
                (args, kwargs)),
            clock=lambda: 123.0,
            sleeper=lambda _seconds: None,
        )

    @staticmethod
    def normalize(payload: dict) -> dict:
        payload["sound_measurement_valid"] = bool(
            payload.get("sound_valid"))
        payload["sound_dba_est"] = payload.get("sound_laeq_dba")
        return payload

    @staticmethod
    def wire(payload: dict) -> bytes:
        return json.dumps(payload).encode("utf-8") + b"\n"

    def test_bad_and_control_packets_do_not_replace_live_state(self) -> None:
        self.assertFalse(self.reader.process_line(b"not-json\n"))
        self.assertFalse(self.reader.process_line(self.wire({
            "event": "boot", "hub_id": "sensorhub1",
        })))
        self.assertEqual(self.payloads, [])
        self.assertEqual(self.events[0][0][:2], ("esp32", "payload_rejected"))
        self.assertEqual(
            self.events[1][0][:2], ("esp32", "control_event_ignored"))

    def test_valid_packet_updates_state_and_sound_history(self) -> None:
        self.assertTrue(self.reader.process_line(self.wire(canonical_packet())))
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(self.payloads[0]["last_update"], 123.0)
        self.assertTrue(self.payloads[0]["connected"])
        self.assertEqual(self.payloads[0]["temperature_c"], 24.5)
        self.assertEqual(self.sounds, [{
            "t": 123.0, "dba": 42.5, "dbfs": -55.0,
        }])

    def test_released_golden_packet_without_hub_id_updates_state(self) -> None:
        packet = {
            "event": "environment",
            "temperature": 24.5,
            "humidity": 52.0,
            "light": 1.2,
            "sound_dbfs": -55.0,
        }

        self.assertTrue(self.reader.process_line(self.wire(packet)))
        self.assertEqual(len(self.payloads), 1)
        self.assertEqual(self.payloads[0]["last_update"], 123.0)
        self.assertTrue(self.payloads[0]["connected"])
        self.assertEqual(self.payloads[0]["temperature"], 24.5)
        self.assertEqual(self.payloads[0]["humidity"], 52.0)
        self.assertEqual(self.payloads[0]["light"], 1.2)

    def test_invalid_sound_does_not_hide_other_two_sensors(self) -> None:
        packet = canonical_packet(sound_valid=False)
        self.assertTrue(self.reader.process_line(self.wire(packet)))
        result = self.payloads[0]
        self.assertEqual(result["temperature_c"], 24.5)
        self.assertEqual(result["lux"], 1.2)
        self.assertFalse(result["sensor_status"]["sph0645"])
        self.assertEqual(result["sound_invalid_reason"], "pcm_all_zero")
        self.assertEqual(self.sounds, [])

    def test_reused_sound_window_is_recorded_only_once(self) -> None:
        packet = canonical_packet()
        self.assertTrue(self.reader.process_line(self.wire(packet)))
        self.assertTrue(self.reader.process_line(self.wire(packet)))
        self.assertEqual(len(self.payloads), 2)
        self.assertEqual(len(self.sounds), 1)

        packet["sensors"]["sph0645"]["values"][
            "sound_window_sequence"
        ] = 8
        self.assertTrue(self.reader.process_line(self.wire(packet)))
        self.assertEqual(len(self.sounds), 2)

    def test_state_store_preserves_last_payload_when_disconnected(self) -> None:
        sensors = {"esp32": {"temperature_c": 24.5, "connected": True}}
        history: list[dict] = []
        store = SensorHub1StateStore(
            sensor_state=sensors,
            state_lock=threading.Lock(),
            sound_history=history,
            sound_history_lock=threading.Lock(),
        )
        store.publish_disconnect(RuntimeError("USB lost"))
        store.append_sound({"dba": 42.5})
        self.assertEqual(sensors["esp32"]["temperature_c"], 24.5)
        self.assertFalse(sensors["esp32"]["connected"])
        self.assertEqual(sensors["esp32"]["error"], "USB lost")
        self.assertEqual(history, [{"dba": 42.5}])


if __name__ == "__main__":
    unittest.main()
