"""Canonical 10-second Sensor-frame sampling service.

Hardware readers keep their native, event-driven cadence.  This service owns
only the fixed-cadence join: it buckets the BCG packets that actually arrived,
adds the freshest environment projection and publishes one canonical frame.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, MutableMapping, MutableSequence, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

SensorValues = MutableMapping[str, Any]
Frame = dict[str, Any]


@dataclass(frozen=True)
class SensorFramePolicy:
    """Runtime thresholds that define one canonical Sensor frame."""

    sample_seconds: float
    minimum_bcg_packets: int
    minimum_paired_vital_coverage: float
    bed_exit_confirm_buckets: int
    bed_exit_raw_min_frames: int
    bed_exit_raw_min_ratio: float
    bed_exit_raw_confirmation_enabled: bool
    on_bed_codes: frozenset[int]
    heart_rate_range: tuple[float, float]
    respiration_range: tuple[float, float]


@dataclass(frozen=True)
class SensorFrameRuntime:
    """Injected state, synchronization and side-effect boundaries."""

    shared_state: SensorValues
    state_lock: Any
    history_lock: Any
    bcg_history: Sequence[Mapping[str, Any]]
    feature_history: MutableSequence[Frame]
    build_environment: Callable[[Frame, Frame, float], Frame]
    summarize_sound_window: Callable[[float, float], Frame]
    filter_vital_values: Callable[[Sequence[Any], tuple[float, float]], list[float]]
    bed_exit_window_evidence: Callable[..., Frame]
    publish_frame: Callable[[Frame, Frame, Frame], None]
    clock: Callable[[], float] = time.time
    monotonic: Callable[[], float] = time.monotonic
    sleeper: Callable[[float], None] = time.sleep
    stop_requested: Callable[[], bool] = lambda: False


@dataclass(frozen=True)
class SensorFrameInputs:
    """Values assembled for one immutable sampling decision."""

    bucket_start: float
    bucket_end: float
    bcg_state: Mapping[str, Any]
    bcg_window: Mapping[str, Any]
    bed_exit_evidence: Mapping[str, Any]
    confirmed_status: Any
    environment: Mapping[str, Any]
    sound_summary: Mapping[str, Any]


@dataclass(frozen=True)
class SensorFrameSampler:
    """Join native sensor streams into deterministic fixed-cadence frames."""

    policy: SensorFramePolicy
    runtime: SensorFrameRuntime

    def run_forever(self) -> None:
        """Publish on the original drift-resistant fixed cadence."""
        next_tick = self.runtime.monotonic()
        bucket_start = self.runtime.clock()
        while not self.runtime.stop_requested():
            next_tick += self.policy.sample_seconds
            self.runtime.sleeper(max(0.0, next_tick - self.runtime.monotonic()))
            bucket_end = self.runtime.clock()
            self.sample_window(bucket_start, bucket_end)
            bucket_start = bucket_end

    def sample_window(self, bucket_start: float, bucket_end: float) -> Frame:
        """Build and publish one frame for the half-open input window."""
        frames = self._bcg_frames(bucket_start, bucket_end)
        bcg_state, esp32, sensorhub2 = self._sensor_state_snapshot()
        bcg_window = self._summarize_bcg(frames)
        exit_evidence, confirmed_status = self._bed_exit_status(bcg_window)
        environment = self.runtime.build_environment(esp32, sensorhub2, bucket_end)
        sound_summary = self.runtime.summarize_sound_window(bucket_start, bucket_end)
        self._publish_sound_analysis(sound_summary, bucket_start, bucket_end)
        inputs = SensorFrameInputs(
            bucket_start=bucket_start,
            bucket_end=bucket_end,
            bcg_state=bcg_state,
            bcg_window=bcg_window,
            bed_exit_evidence=exit_evidence,
            confirmed_status=confirmed_status,
            environment=environment,
            sound_summary=sound_summary,
        )
        feature = self._build_feature(inputs)
        with self.runtime.history_lock:
            self.runtime.feature_history.append(feature)
        self.runtime.publish_frame(feature, environment, bcg_state)
        return feature

    def _bcg_frames(self, bucket_start: float, bucket_end: float) -> list[Frame]:
        with self.runtime.history_lock:
            return [
                frame
                for frame in self.runtime.bcg_history
                if bucket_start < frame["t"] <= bucket_end
            ]

    def _sensor_state_snapshot(self) -> tuple[Frame, Frame, Frame]:
        with self.runtime.state_lock:
            sensor = self.runtime.shared_state["sensor"]
            return (
                dict(sensor["bcg"]),
                dict(sensor.get("esp32") or {}),
                dict(sensor.get("sensorhub2") or {}),
            )

    def _summarize_bcg(self, frames: Sequence[Mapping[str, Any]]) -> Frame:
        raw_hr = [frame.get("hr") for frame in frames]
        raw_rr = [frame.get("rr") for frame in frames]
        paired_vitals: list[tuple[float, float]] = []
        for frame in frames:
            heart_rates = self.runtime.filter_vital_values(
                [frame.get("hr")], self.policy.heart_rate_range
            )
            respiration_rates = self.runtime.filter_vital_values(
                [frame.get("rr")], self.policy.respiration_range
            )
            if heart_rates and respiration_rates:
                paired_vitals.append((heart_rates[0], respiration_rates[0]))
        statuses = [
            frame.get("status") for frame in frames if frame.get("status") is not None
        ]
        raw_points = [
            value for frame in frames for value in (frame.get("samples") or [])
        ]
        clipped = sum(value in (-32768, 32767) for value in raw_points)
        coverage = len(paired_vitals) / len(frames) if frames else 0.0
        return {
            "frames": frames,
            "raw_hr": raw_hr,
            "raw_rr": raw_rr,
            "paired_vitals": paired_vitals,
            "statuses": statuses,
            "raw_points": raw_points,
            "clip_ratio": clipped / len(raw_points) if raw_points else None,
            "bucket_status": (
                2 if 2 in statuses else (statuses[-1] if statuses else None)
            ),
            "raw_exit_frames": sum(status == 1 for status in statuses),
            "paired_packet_coverage": coverage,
        }

    def _bed_exit_status(self, bcg_window: Mapping[str, Any]) -> tuple[Frame, Any]:
        count = max(0, self.policy.bed_exit_confirm_buckets - 1)
        with self.runtime.history_lock:
            previous_features = list(self.runtime.feature_history)[-count:]
        previous_feature = previous_features[-1] if previous_features else None
        recent_statuses = [
            previous.get("status")
            for previous in previous_features
            if previous.get("status") is not None
        ]
        bucket_status = bcg_window["bucket_status"]
        if bucket_status is not None:
            recent_statuses.append(bucket_status)
        evidence = self.runtime.bed_exit_window_evidence(
            recent_statuses,
            latest_raw_exit_frames=bcg_window["raw_exit_frames"],
            latest_raw_total_frames=len(bcg_window["statuses"]),
            minimum_consecutive_buckets=self.policy.bed_exit_confirm_buckets,
            minimum_raw_frames=self.policy.bed_exit_raw_min_frames,
            minimum_raw_ratio=self.policy.bed_exit_raw_min_ratio,
            raw_packet_confirmation_enabled=(
                self.policy.bed_exit_raw_confirmation_enabled
            ),
        )
        confirmed_status = bucket_status
        if bucket_status == 1 and not evidence["confirmed"]:
            previous_confirmed = (
                previous_feature.get(
                    "confirmed_status",
                    previous_feature.get("status"),
                )
                if previous_feature is not None
                else None
            )
            confirmed_status = (
                previous_confirmed
                if previous_confirmed in self.policy.on_bed_codes
                else 0
            )
        return evidence, confirmed_status

    def _publish_sound_analysis(
        self,
        summary: Mapping[str, Any],
        bucket_start: float,
        bucket_end: float,
    ) -> None:
        with self.runtime.state_lock:
            self.runtime.shared_state["system"]["sound_analysis"] = {
                **summary,
                "window_start": datetime.fromtimestamp(bucket_start, UTC).isoformat(),
                "window_end": datetime.fromtimestamp(bucket_end, UTC).isoformat(),
            }

    def _build_feature(self, inputs: SensorFrameInputs) -> Frame:
        bucket_start = inputs.bucket_start
        bucket_end = inputs.bucket_end
        bcg_state = inputs.bcg_state
        bcg_window = inputs.bcg_window
        bed_exit_evidence = inputs.bed_exit_evidence
        confirmed_status = inputs.confirmed_status
        environment = inputs.environment
        sound_summary = inputs.sound_summary
        frames = bcg_window["frames"]
        paired_vitals = bcg_window["paired_vitals"]
        valid_hr = [pair[0] for pair in paired_vitals]
        valid_rr = [pair[1] for pair in paired_vitals]
        device_status = {
            key: device.get("status") == "live"
            for key, device in (environment.get("devices") or {}).items()
        }
        coverage = bcg_window["paired_packet_coverage"]
        bucket_valid = bool(
            len(frames) >= self.policy.minimum_bcg_packets
            and coverage >= self.policy.minimum_paired_vital_coverage
        )
        return {
            "t": bucket_end,
            "bucket_start": bucket_start,
            "status": bcg_window["bucket_status"],
            "confirmed_status": confirmed_status,
            "bed_exit_evidence": bed_exit_evidence,
            "status_codes_seen": sorted(
                {int(value) for value in bcg_window["statuses"]}
            ),
            "hr": round(sum(valid_hr) / len(valid_hr), 2) if valid_hr else None,
            "rr": round(sum(valid_rr) / len(valid_rr), 2) if valid_rr else None,
            "invalid_hr_count": len(
                [value for value in bcg_window["raw_hr"] if value is not None]
            )
            - len(valid_hr),
            "invalid_rr_count": len(
                [value for value in bcg_window["raw_rr"] if value is not None]
            )
            - len(valid_rr),
            "packet_count": bcg_state.get("packets"),
            "bcg_frames": len(frames),
            "bcg_latest_t": frames[-1]["t"] if frames else None,
            "clip_ratio": (
                round(bcg_window["clip_ratio"], 4)
                if bcg_window["clip_ratio"] is not None
                else None
            ),
            "bcg_valid": bucket_valid,
            "paired_vital_packets": len(paired_vitals),
            "paired_vital_coverage": round(coverage, 4),
            "minimum_bcg_packets": self.policy.minimum_bcg_packets,
            "bcg_samples": bcg_window["raw_points"],
            **self._environment_fields(environment, device_status, sound_summary),
            "esp_fresh": any(device_status.values()),
            "sensor_status": device_status,
        }

    @staticmethod
    def _environment_fields(
        environment: Mapping[str, Any],
        device_status: Mapping[str, bool],
        sound_summary: Mapping[str, Any],
    ) -> Frame:
        live = device_status.get
        return {
            "temperature": (
                environment.get("temperature_c") if live("sht3x_dis") else None
            ),
            "humidity": environment.get("humidity_rh") if live("sht3x_dis") else None,
            "co2": environment.get("co2_ppm") if live("mhz19c") else None,
            "lux": environment.get("lux") if live("opt3001") else None,
            "sound_dba": environment.get("sound_dba_est") if live("sph0645") else None,
            "sound_leq_dba": sound_summary.get("leq_dba") if live("sph0645") else None,
            "sound_sample_count": int(sound_summary.get("sample_count") or 0),
            "sound_window_status": sound_summary.get("status"),
            "sound_span_db": sound_summary.get("span_db"),
            "sound_large_step": bool(sound_summary.get("large_step_detected")),
            "pm2_5": environment.get("pm2_5_ug_m3") if live("pms7003") else None,
            "voc": environment.get("voc_index") if live("sgp40") else None,
        }
