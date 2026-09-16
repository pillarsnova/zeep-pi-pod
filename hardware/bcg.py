"""LSM-800-T serial transport and live-state publication.

The device emits a fixed 66-byte ``Odata``/``Bdata`` frame at its native
cadence.  This module owns serial synchronization and projection into the
process state, while the byte contract remains in :mod:`sensor_contracts` and
SQLite batching remains in :mod:`bcg_storage`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, MutableMapping, MutableSequence
from dataclasses import dataclass
from typing import Any, Protocol

ParsedFrame = Mapping[str, Any]
EventLogger = Callable[..., None]


class BCGPublisher(Protocol):
    """Minimal output boundary required by the transport loop."""

    def connected(self) -> None: ...

    def disconnected(self, exc: Exception) -> None: ...

    def publish(self, frame: bytes, parsed: ParsedFrame) -> None: ...


@dataclass(frozen=True)
class BCGPublicationPorts:
    """Mutable destinations used when publishing one decoded packet."""

    storage: Any
    shared_state: MutableMapping[str, Any]
    state_lock: Any
    history: MutableSequence[dict[str, Any]]
    raw_history: MutableSequence[dict[str, Any]]
    history_lock: Any


@dataclass(frozen=True)
class BCGReaderConfig:
    """Runtime settings and physiology-validity boundaries for one reader."""

    port: str
    baud: int
    status_text: Mapping[int, str]
    on_bed_codes: frozenset[int]
    heart_rate_range: tuple[float, float]
    respiration_range: tuple[float, float]
    vital_hold_seconds: float
    serial_timeout_seconds: float = 1.0
    reconnect_delay_seconds: float = 2.0


@dataclass(frozen=True)
class BCGReaderPorts:
    """Injected transport, parser and lifecycle ports for the reader loop."""

    serial_factory: Callable[..., Any]
    parse_frame: Callable[[bytes], ParsedFrame]
    publisher: BCGPublisher
    log_event: EventLogger
    sleeper: Callable[[float], None] = time.sleep
    stop_event: threading.Event | None = None


@dataclass(frozen=True)
class VitalProjectionSpec:
    """Shared-state fields for one live vital-sign projection."""

    field: str
    last_valid_field: str
    held_field: str


HEART_RATE_PROJECTION = VitalProjectionSpec(
    field="heart_rate_bpm",
    last_valid_field="heart_rate_last_valid",
    held_field="heart_rate_held",
)
RESPIRATION_PROJECTION = VitalProjectionSpec(
    field="respiration_rate",
    last_valid_field="respiration_last_valid",
    held_field="respiration_held",
)


class BCGPacketPublisher:
    """Publish decoded packets to storage, histories and shared live state."""

    def __init__(
        self,
        *,
        config: BCGReaderConfig,
        ports: BCGPublicationPorts,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.ports = ports
        self.clock = clock

    def connected(self) -> None:
        """Clear an earlier transport error after the port opens."""
        with self.ports.state_lock:
            self.ports.shared_state["sensor"]["bcg"].pop("error", None)

    def disconnected(self, exc: Exception) -> None:
        """Expose a transport failure without erasing the last measurement."""
        with self.ports.state_lock:
            bcg = self.ports.shared_state["sensor"]["bcg"]
            bcg["connected"] = False
            bcg["error"] = str(exc)

    def publish(self, frame: bytes, parsed: ParsedFrame) -> None:
        """Persist and project one byte-valid, decoded device frame."""
        status_code = int(parsed["status_code"])
        heart_rate = parsed.get("heart_rate_bpm")
        respiration = parsed.get("respiration_rate")
        self.ports.storage.add_packet(
            frame,
            sensor_packet_id=parsed["sensor_packet_id"],
            status_code=status_code,
            heart_rate=heart_rate,
            respiration_rate=respiration,
        )
        self._append_histories(frame, parsed)
        self._update_live_state(
            parsed,
            status_code=status_code,
            heart_rate=heart_rate,
            respiration=respiration,
            packet_time=self.clock(),
        )

    def _append_histories(self, frame: bytes, parsed: ParsedFrame) -> None:
        samples = parsed["samples"]
        with self.ports.history_lock:
            self.ports.history.append(
                {
                    "t": self.clock(),
                    "status": parsed["status_code"],
                    "hr": parsed.get("heart_rate_bpm"),
                    "rr": parsed.get("respiration_rate"),
                    "samples": samples,
                }
            )
            self.ports.raw_history.append(
                {
                    "t": self.clock(),
                    "packet_id": parsed["sensor_packet_id"],
                    "status_code": parsed["status_code"],
                    "heart_rate": parsed.get("heart_rate_bpm"),
                    "respiration_raw": parsed["respiration_raw"],
                    "respiration_rate": parsed.get("respiration_rate"),
                    "samples": samples,
                    "raw_hex": frame.hex(" "),
                }
            )

    def _update_live_state(
        self,
        parsed: ParsedFrame,
        *,
        status_code: int,
        heart_rate: Any,
        respiration: Any,
        packet_time: float,
    ) -> None:
        hr_valid = self._in_range(heart_rate, self.config.heart_rate_range)
        rr_valid = self._in_range(respiration, self.config.respiration_range)
        with self.ports.state_lock:
            bcg = self.ports.shared_state["sensor"]["bcg"]
            current_vitals_valid = bool(
                status_code in self.config.on_bed_codes and hr_valid and rr_valid
            )
            previous_streak = int(bcg.get("vital_valid_streak") or 0)
            bcg.update(
                {
                    "connected": True,
                    "samples": parsed["samples"],
                    "sensor_packet_id": parsed["sensor_packet_id"],
                    "status_code": status_code,
                    "status_text": self.config.status_text.get(
                        status_code,
                        "Unknown",
                    ),
                    "respiration_raw": parsed["respiration_raw"],
                    "heart_rate_current_valid": hr_valid,
                    "respiration_current_valid": rr_valid,
                    "vital_valid_streak": (
                        previous_streak + 1 if current_vitals_valid else 0
                    ),
                    "vital_valid_since": self._valid_since(
                        bcg,
                        current_vitals_valid=current_vitals_valid,
                        previous_streak=previous_streak,
                        packet_time=packet_time,
                    ),
                    "last_update": packet_time,
                    "packets": int(bcg.get("packets", 0)) + 1,
                }
            )
            self._update_vital(
                bcg,
                projection=HEART_RATE_PROJECTION,
                value=heart_rate,
                status_code=status_code,
                packet_time=packet_time,
            )
            self._update_vital(
                bcg,
                projection=RESPIRATION_PROJECTION,
                value=respiration,
                status_code=status_code,
                packet_time=packet_time,
            )

    def _update_vital(
        self,
        bcg: MutableMapping[str, Any],
        *,
        projection: VitalProjectionSpec,
        value: Any,
        status_code: int,
        packet_time: float,
    ) -> None:
        if value is not None:
            bcg[projection.field] = value
            bcg[projection.last_valid_field] = packet_time
            bcg[projection.held_field] = False
            return
        last_valid = bcg.get(projection.last_valid_field)
        can_hold = bool(
            status_code in self.config.on_bed_codes
            and isinstance(last_valid, (int, float))
            and packet_time - last_valid <= self.config.vital_hold_seconds
        )
        if not can_hold:
            bcg[projection.field] = None
        bcg[projection.held_field] = can_hold

    @staticmethod
    def _in_range(value: Any, boundaries: tuple[float, float]) -> bool:
        return bool(value is not None and boundaries[0] <= value <= boundaries[1])

    @staticmethod
    def _valid_since(
        bcg: Mapping[str, Any],
        *,
        current_vitals_valid: bool,
        previous_streak: int,
        packet_time: float,
    ) -> Any:
        if not current_vitals_valid:
            return None
        if previous_streak > 0:
            return bcg.get("vital_valid_since")
        return packet_time


class LSM800TReader:
    """Synchronize and decode the deployed LSM-800-T serial stream."""

    def __init__(
        self,
        *,
        config: BCGReaderConfig,
        ports: BCGReaderPorts,
    ) -> None:
        self.config = config
        self.ports = ports
        self.stop_event = ports.stop_event or threading.Event()

    def run_forever(self) -> None:
        """Reconnect on port failures; tolerate normal quiet inter-frame gaps."""
        last_error: str | None = None
        while not self.stop_event.is_set():
            try:
                with self.ports.serial_factory(
                    self.config.port,
                    self.config.baud,
                    timeout=self.config.serial_timeout_seconds,
                ) as connection:
                    self.ports.log_event(
                        "bcg",
                        "connected",
                        port=self.config.port,
                        baud=self.config.baud,
                    )
                    last_error = None
                    self.ports.publisher.connected()
                    self._consume(connection)
            except Exception as exc:
                if str(exc) != last_error:
                    self.ports.log_event("bcg", "disconnected", error=str(exc))
                    last_error = str(exc)
                self.ports.publisher.disconnected(exc)
                if not self.stop_event.is_set():
                    self.ports.sleeper(self.config.reconnect_delay_seconds)

    def _consume(self, connection: Any) -> None:
        sync = bytearray()
        while not self.stop_event.is_set():
            first = connection.read(1)
            if not first:
                continue
            sync += first
            if len(sync) > 5:
                del sync[0]
            if bytes(sync) != b"Odata":
                continue
            try:
                rest = read_exact(connection, 61)
            except TimeoutError:
                sync.clear()
                continue
            frame = b"Odata" + rest
            if frame[57:62] != b"Bdata":
                continue
            self.ports.publisher.publish(frame, self.ports.parse_frame(frame))


def read_exact(connection: Any, size: int) -> bytes:
    """Read one fixed-size remainder or reject the partial frame."""
    buffer = bytearray()
    while len(buffer) < size:
        chunk = connection.read(size - len(buffer))
        if not chunk:
            raise TimeoutError("serial timeout")
        buffer.extend(chunk)
    return bytes(buffer)
