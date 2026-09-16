"""Characterization tests for the extracted LSM-800-T serial adapter."""

from __future__ import annotations

import struct
import threading
import unittest
from collections import deque
from typing import Any

from sensor_contracts import parse_lsm800t_frame
from hardware.bcg import (
    BCGPacketPublisher,
    BCGPublicationPorts,
    BCGReaderConfig,
    BCGReaderPorts,
    LSM800TReader,
    read_exact,
)


def make_frame(
    *,
    packet_id: int = 7,
    status: int = 2,
    heart_rate: int = 68,
    respiration_raw: int = 143,
) -> bytes:
    samples = list(range(-12, 13))
    return (
        b"Odata"
        + struct.pack("<25h", *samples)
        + b"\x00\x00"
        + b"Bdata"
        + bytes([packet_id, status, heart_rate, respiration_raw])
    )


class ScriptedSerial:
    """Small pyserial-compatible context manager for deterministic byte reads."""

    def __init__(self, events: list[bytes | None | Exception]) -> None:
        self.events = list(events)
        self.closed = False

    def __enter__(self) -> ScriptedSerial:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.closed = True

    def read(self, size: int) -> bytes:
        if not self.events:
            return b""
        event = self.events[0]
        if event is None:
            self.events.pop(0)
            return b""
        if isinstance(event, Exception):
            self.events.pop(0)
            raise event
        result = event[:size]
        remainder = event[size:]
        if remainder:
            self.events[0] = remainder
        else:
            self.events.pop(0)
        return result


class SerialFactory:
    def __init__(self, connections: list[ScriptedSerial]) -> None:
        self.connections = list(connections)
        self.calls: list[tuple[str, int, float]] = []

    def __call__(self, port: str, baud: int, *, timeout: float) -> ScriptedSerial:
        self.calls.append((port, baud, timeout))
        return self.connections.pop(0)


class RecordingPublisher:
    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        self.frames: list[tuple[bytes, dict[str, Any]]] = []
        self.connected_count = 0
        self.disconnects: list[str] = []

    def connected(self) -> None:
        self.connected_count += 1

    def disconnected(self, exc: Exception) -> None:
        self.disconnects.append(str(exc))

    def publish(self, frame: bytes, parsed: dict[str, Any]) -> None:
        self.frames.append((frame, parsed))
        self.stop_event.set()


def config() -> BCGReaderConfig:
    return BCGReaderConfig(
        port="/dev/fake-bcg",
        baud=115200,
        status_text={0: "On bed", 1: "Get out of bed", 2: "Moving"},
        on_bed_codes=frozenset({0, 2, 3, 5}),
        heart_rate_range=(35.0, 220.0),
        respiration_range=(5.0, 45.0),
        vital_hold_seconds=15.0,
    )


class LSM800TReaderTests(unittest.TestCase):
    def run_reader(
        self,
        connections: list[ScriptedSerial],
    ) -> tuple[RecordingPublisher, SerialFactory, list[tuple[Any, ...]], list[float]]:
        stop_event = threading.Event()
        publisher = RecordingPublisher(stop_event)
        factory = SerialFactory(connections)
        events: list[tuple[Any, ...]] = []
        sleeps: list[float] = []
        reader = LSM800TReader(
            config=config(),
            ports=BCGReaderPorts(
                serial_factory=factory,
                parse_frame=parse_lsm800t_frame,
                publisher=publisher,
                log_event=lambda *args, **kwargs: events.append((args, kwargs)),
                sleeper=sleeps.append,
                stop_event=stop_event,
            ),
        )
        reader.run_forever()
        return publisher, factory, events, sleeps

    def test_quiet_gap_and_noise_do_not_disconnect_before_valid_frame(self) -> None:
        frame = make_frame()
        publisher, factory, events, sleeps = self.run_reader(
            [ScriptedSerial([None, b"noise", frame])]
        )

        self.assertEqual(factory.calls, [("/dev/fake-bcg", 115200, 1.0)])
        self.assertEqual(publisher.frames[0][0], frame)
        self.assertEqual(publisher.frames[0][1]["heart_rate_bpm"], 68)
        self.assertEqual(publisher.disconnects, [])
        self.assertEqual(sleeps, [])
        self.assertEqual(events[0][0], ("bcg", "connected"))

    def test_partial_frame_is_dropped_then_reader_resynchronizes(self) -> None:
        frame = make_frame(packet_id=9)
        publisher, _factory, _events, _sleeps = self.run_reader(
            [ScriptedSerial([b"Odata", frame[5:20], None, b"junk", frame])]
        )

        self.assertEqual(len(publisher.frames), 1)
        self.assertEqual(publisher.frames[0][1]["sensor_packet_id"], 9)

    def test_wrong_summary_marker_is_ignored(self) -> None:
        invalid = bytearray(make_frame(packet_id=3))
        invalid[57:62] = b"Xdata"
        valid = make_frame(packet_id=4)
        publisher, _factory, _events, _sleeps = self.run_reader(
            [ScriptedSerial([bytes(invalid), valid])]
        )

        self.assertEqual(len(publisher.frames), 1)
        self.assertEqual(publisher.frames[0][1]["sensor_packet_id"], 4)

    def test_port_failure_reconnects_after_two_seconds(self) -> None:
        publisher, factory, events, sleeps = self.run_reader(
            [
                ScriptedSerial([OSError("port lost")]),
                ScriptedSerial([make_frame()]),
            ]
        )

        self.assertEqual(len(factory.calls), 2)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(publisher.disconnects, ["port lost"])
        self.assertIn((("bcg", "disconnected"), {"error": "port lost"}), events)

    def test_read_exact_rejects_a_partial_remainder(self) -> None:
        with self.assertRaisesRegex(TimeoutError, "serial timeout"):
            read_exact(ScriptedSerial([b"abc", None]), 4)


class FakeStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, dict[str, Any]]] = []

    def add_packet(self, frame: bytes, **metadata: Any) -> None:
        self.calls.append((frame, metadata))


class BCGPacketPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "sensor": {
                "bcg": {
                    "connected": False,
                    "heart_rate_bpm": None,
                    "heart_rate_last_valid": None,
                    "respiration_rate": None,
                    "respiration_last_valid": None,
                    "vital_valid_streak": 0,
                    "vital_valid_since": None,
                    "packets": 0,
                    "error": "old failure",
                }
            }
        }
        self.storage = FakeStorage()
        self.history: deque[dict[str, Any]] = deque()
        self.raw_history: deque[dict[str, Any]] = deque()
        self.times = iter([10.0, 11.0, 12.0, 20.0, 21.0, 22.0, 30.0, 31.0, 32.0])
        self.publisher = BCGPacketPublisher(
            config=config(),
            ports=BCGPublicationPorts(
                storage=self.storage,
                shared_state=self.state,
                state_lock=threading.Lock(),
                history=self.history,
                raw_history=self.raw_history,
                history_lock=threading.Lock(),
            ),
            clock=lambda: next(self.times),
        )

    def test_valid_packet_is_stored_byte_exact_and_published(self) -> None:
        frame = make_frame()
        parsed = parse_lsm800t_frame(frame)
        self.publisher.connected()
        self.publisher.publish(frame, parsed)

        self.assertNotIn("error", self.state["sensor"]["bcg"])
        self.assertEqual(self.storage.calls[0][0], frame)
        self.assertEqual(self.storage.calls[0][1]["heart_rate"], 68)
        self.assertEqual(self.history[0]["t"], 10.0)
        self.assertEqual(self.raw_history[0]["t"], 11.0)
        self.assertEqual(self.raw_history[0]["raw_hex"], frame.hex(" "))
        live = self.state["sensor"]["bcg"]
        self.assertTrue(live["connected"])
        self.assertEqual(live["status_text"], "Moving")
        self.assertEqual(live["heart_rate_bpm"], 68)
        self.assertEqual(live["respiration_rate"], 14.3)
        self.assertEqual(live["vital_valid_streak"], 1)
        self.assertEqual(live["vital_valid_since"], 12.0)
        self.assertEqual(live["last_update"], 12.0)

    def test_zero_vitals_hold_on_bed_then_clear_off_bed(self) -> None:
        self.publisher.publish(make_frame(), parse_lsm800t_frame(make_frame()))
        zero_on_bed = make_frame(packet_id=8, status=0, heart_rate=0, respiration_raw=0)
        self.publisher.publish(zero_on_bed, parse_lsm800t_frame(zero_on_bed))

        live = self.state["sensor"]["bcg"]
        self.assertEqual(live["heart_rate_bpm"], 68)
        self.assertEqual(live["respiration_rate"], 14.3)
        self.assertTrue(live["heart_rate_held"])
        self.assertTrue(live["respiration_held"])
        self.assertFalse(live["heart_rate_current_valid"])
        self.assertEqual(live["vital_valid_streak"], 0)

        zero_off_bed = make_frame(
            packet_id=9, status=1, heart_rate=0, respiration_raw=0
        )
        self.publisher.publish(zero_off_bed, parse_lsm800t_frame(zero_off_bed))
        self.assertIsNone(live["heart_rate_bpm"])
        self.assertIsNone(live["respiration_rate"])
        self.assertFalse(live["heart_rate_held"])
        self.assertFalse(live["respiration_held"])

    def test_disconnect_preserves_measurements_and_marks_transport(self) -> None:
        self.state["sensor"]["bcg"]["heart_rate_bpm"] = 62
        self.publisher.disconnected(OSError("unplugged"))

        live = self.state["sensor"]["bcg"]
        self.assertFalse(live["connected"])
        self.assertEqual(live["error"], "unplugged")
        self.assertEqual(live["heart_rate_bpm"], 62)


if __name__ == "__main__":
    unittest.main()
