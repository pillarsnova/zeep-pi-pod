"""Live Session sampling loop with explicit composition-root ports."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any


@dataclass(frozen=True)
class LiveSamplerPorts:
    """Runtime operations owned by the application composition root."""

    session_lock: RLock
    get_active: Callable[[], dict[str, Any] | None]
    bed_occupied_now: Callable[[], bool]
    vital_gate_now: Callable[[dict[str, Any]], dict[str, Any]]
    begin_recording: Callable[[dict[str, Any]], None]
    update_projection: Callable[[dict[str, Any]], None]
    log_event: Callable[..., None]
    take_sample: Callable[[], dict[str, Any]]
    sample_interval: Callable[[Any, float], float]
    enqueue_timeline: Callable[[dict[str, Any]], None]
    sleep: Callable[[float], None] = time.sleep


class LiveSessionSampler:
    """Promote waiting Sessions and persist one Sensor timeline."""

    def __init__(
        self,
        ports: LiveSamplerPorts,
        *,
        bed_start_seconds: float,
        default_interval_seconds: float,
        sample_limit: int,
    ) -> None:
        self.ports = ports
        self.bed_start_seconds = bed_start_seconds
        self.default_interval_seconds = default_interval_seconds
        self.sample_limit = sample_limit

    def run_forever(self) -> None:
        """Run the existing one-second lifecycle loop indefinitely."""
        while True:
            self.ports.sleep(1.0)
            with self.ports.session_lock:
                active = self.ports.get_active()
            if active is None:
                continue
            if active.get("phase") == "waiting_bed":
                self._advance_waiting(active)
                continue
            self._sample_recording(active)

    def _advance_waiting(self, active: dict[str, Any]) -> None:
        occupied = self.ports.bed_occupied_now()
        vital_gate = self.ports.vital_gate_now(active)
        promote = False
        wait_s = 0.0
        with self.ports.session_lock:
            if self.ports.get_active() is not active:
                return
            if active.get("phase") != "waiting_bed":
                return
            if occupied:
                if active.get("onbed_since") is None:
                    active["onbed_since"] = time.monotonic()
                wait_s = time.monotonic() - active["onbed_since"]
                promote = wait_s >= self.bed_start_seconds and vital_gate["ready"]
            else:
                active["onbed_since"] = None
        if promote:
            self._promote(active)
            return
        self.ports.update_projection(
            {
                "bed_wait_s": round(min(wait_s, self.bed_start_seconds), 1),
                "vital_gate": vital_gate,
            }
        )

    def _promote(self, active: dict[str, Any]) -> None:
        try:
            self.ports.begin_recording(active)
        except RuntimeError as exc:
            vital_gate = self.ports.vital_gate_now(active)
            self.ports.update_projection({"vital_gate": vital_gate})
            self.ports.log_event(
                "session",
                "vital_start_gate_changed",
                session_id=active["record"]["session_id"],
                error=str(exc),
            )

    def _sample_recording(self, active: dict[str, Any]) -> None:
        with self.ports.session_lock:
            if self.ports.get_active() is not active:
                return
            interval_s = self.ports.sample_interval(
                (active.get("record") or {}).get("sample_interval_s"),
                self.default_interval_seconds,
            )
            if time.monotonic() - active["last_sample"] < interval_s:
                return
            active["last_sample"] = time.monotonic()
        sample = self.ports.take_sample()
        sample["sample_interval_s"] = interval_s
        persisted = self._append_sample(active, sample)
        if persisted is None:
            return
        count, session_id = persisted
        self.ports.update_projection({"samples": count})
        self.ports.enqueue_timeline(self._timeline_row(session_id, sample))

    def _append_sample(
        self,
        active: dict[str, Any],
        sample: dict[str, Any],
    ) -> tuple[int, str] | None:
        with self.ports.session_lock:
            if self.ports.get_active() is not active:
                return None
            if len(active["samples"]) >= self.sample_limit:
                return None
            active["samples"].append(sample)
            return len(active["samples"]), active["record"]["session_id"]

    @staticmethod
    def _timeline_row(session_id: str, sample: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "timestamp": datetime.fromtimestamp(sample["t"], UTC).isoformat(),
            "temperature": sample["temp"],
            "humidity": sample["hum"],
            "co2": sample["co2"],
            "pm2_5": sample.get("pm2_5"),
            "voc_index": sample.get("voc"),
            "lux": sample["lux"],
            "sound": sample["dba"],
            "heart_rate": sample["hr"],
            "respiration_rate": sample["rr"],
            "bed_status": sample["bed"],
            "respiratory_evidence_valid": sample["respiratory_evidence_valid"],
            "respiratory_evidence_reason": sample["respiratory_evidence_reason"],
            "acoustic_label": sample.get("acoustic_label"),
            "acoustic_state": sample.get("acoustic_state"),
            "acoustic_confidence": sample.get("acoustic_confidence"),
            "acoustic_event_detected": sample.get("acoustic_event_detected"),
            "acoustic_classifier_version": sample.get("acoustic_classifier_version"),
            "acoustic_window_sequence": sample.get("acoustic_window_sequence"),
            "acoustic_features_json": json.dumps(
                sample.get("acoustic_features") or {},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
