"""Build fixed-size BCG epochs without retaining an overnight recording in RAM."""
from __future__ import annotations

import base64
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Optional

from database import DatabaseManager


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BCGStorage:
    """Session-aware packet window feeding tx-labelled SQLite epochs."""

    def __init__(self, database: DatabaseManager, epoch_packets: int = 60) -> None:
        self.database = database
        self.epoch_packets = epoch_packets
        self._packets: deque[dict[str, Any]] = deque(maxlen=epoch_packets)
        self._session_id: Optional[str] = None
        self._epoch_index = 0
        self._lock = Lock()

    def start_session(self, session_id: str) -> None:
        with self._lock:
            if self._session_id and self._packets:
                self._flush_locked()
            self._session_id = session_id
            rows = self.database.read_bcg(
                "SELECT COALESCE(MAX(epoch_index),0) AS n FROM bcg_epochs WHERE session_id=?",
                (session_id,),
            )
            self._epoch_index = int(rows[0]["n"]) if rows else 0
            self._packets.clear()

    def add_packet(
        self,
        frame: bytes,
        *,
        sensor_packet_id: int,
        status_code: int,
        heart_rate: Optional[float],
        respiration_rate: Optional[float],
        timestamp: Optional[str] = None,
    ) -> None:
        if len(frame) != 66:
            raise ValueError(f"BCG frame must be 66 bytes, got {len(frame)}")
        if frame[:5] != b"Odata" or frame[57:62] != b"Bdata":
            raise ValueError("BCG frame markers are invalid")
        packet = {
            "timestamp": timestamp or utc_now(),
            "sensor_packet_id": sensor_packet_id,
            "status_code": status_code,
            "heart_rate": heart_rate,
            "respiration_rate": respiration_rate,
            # Preserve the exact 25 little-endian int16 bytes and the complete frame.
            "bcg_base64": base64.b64encode(frame[5:55]).decode("ascii"),
            "raw_packet_base64": base64.b64encode(frame).decode("ascii"),
        }
        with self._lock:
            if not self._session_id:
                return
            self._packets.append(packet)
            if len(self._packets) == self.epoch_packets:
                self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked()

    def end_session(self, session_id: str) -> None:
        with self._lock:
            if self._session_id == session_id:
                self._flush_locked()
                self._session_id = None

    @staticmethod
    def _average(values: list[Optional[float]]) -> Optional[float]:
        valid = [float(v) for v in values if v is not None and v > 0]
        return round(sum(valid) / len(valid), 2) if valid else None

    def _flush_locked(self) -> None:
        if not self._session_id or not self._packets:
            return
        packets = list(self._packets)
        self._packets.clear()
        self._epoch_index += 1
        tx_label = f"tx{self._epoch_index}"
        if len(packets) < self.epoch_packets:
            tx_label += "_partial"
        for index, packet in enumerate(packets):
            packet["packet_index"] = index
        self.database.enqueue("bcg", "bcg_epoch", {
            "session_id": self._session_id,
            "epoch_index": self._epoch_index,
            "tx_label": tx_label,
            "start_time": packets[0]["timestamp"],
            "end_time": packets[-1]["timestamp"],
            "packet_count": len(packets),
            "sample_count": len(packets) * 25,
            "average_hr": self._average([p["heart_rate"] for p in packets]),
            "average_rr": self._average([p["respiration_rate"] for p in packets]),
            "packets": packets,
        })
