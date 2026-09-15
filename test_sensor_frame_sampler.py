"""Characterization tests for the canonical 10-second Sensor sampler."""

from __future__ import annotations

import threading
import unittest
from collections import deque
from dataclasses import replace
from typing import Any

from sleep_signal_features import bed_exit_window_evidence, filter_vital_values
from zeep_pod.sessions.sensor_frame_sampler import (
    SensorFramePolicy,
    SensorFrameRuntime,
    SensorFrameSampler,
)

POLICY = SensorFramePolicy(
    sample_seconds=10.0,
    minimum_bcg_packets=8,
    minimum_paired_vital_coverage=0.8,
    bed_exit_confirm_buckets=3,
    bed_exit_raw_min_frames=5,
    bed_exit_raw_min_ratio=0.8,
    bed_exit_raw_confirmation_enabled=False,
    on_bed_codes=frozenset({0, 2, 3, 5}),
    heart_rate_range=(35.0, 220.0),
    respiration_range=(5.0, 45.0),
)


class SamplerHarness:
    def __init__(self, policy: SensorFramePolicy = POLICY) -> None:
        self.state = {
            "sensor": {
                "bcg": {"connected": True, "packets": 42},
                "esp32": {"hub": "one"},
                "sensorhub2": {"hub": "two"},
            },
            "system": {},
        }
        self.state_lock = threading.Lock()
        self.history_lock = threading.Lock()
        self.bcg_history: deque[dict[str, Any]] = deque()
        self.feature_history: deque[dict[str, Any]] = deque()
        self.environment_calls: list[tuple[dict[str, Any], dict[str, Any], float]] = []
        self.sound_calls: list[tuple[float, float]] = []
        self.published: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        self.history_lengths_at_publish: list[int] = []
        self.environment = {
            "temperature_c": 23.5,
            "humidity_rh": 48.0,
            "co2_ppm": 712.0,
            "lux": 4.0,
            "sound_dba_est": 41.5,
            "pm2_5_ug_m3": 7.0,
            "voc_index": 88.0,
            "devices": {
                "sht3x_dis": {"status": "live"},
                "mhz19c": {"status": "stale"},
                "opt3001": {"status": "live"},
                "sph0645": {"status": "live"},
                "pms7003": {"status": "live"},
                "sgp40": {"status": "live"},
            },
        }
        self.sound_summary = {
            "leq_dba": 40.75,
            "sample_count": 9,
            "status": "valid",
            "span_db": 3.25,
            "large_step_detected": True,
        }
        self.runtime = SensorFrameRuntime(
            shared_state=self.state,
            state_lock=self.state_lock,
            history_lock=self.history_lock,
            bcg_history=self.bcg_history,
            feature_history=self.feature_history,
            build_environment=self.build_environment,
            summarize_sound_window=self.summarize_sound,
            filter_vital_values=filter_vital_values,
            bed_exit_window_evidence=bed_exit_window_evidence,
            publish_frame=self.publish,
        )
        self.sampler = SensorFrameSampler(policy, self.runtime)

    def build_environment(
        self,
        esp32: dict[str, Any],
        sensorhub2: dict[str, Any],
        now: float,
    ) -> dict[str, Any]:
        self.environment_calls.append((esp32, sensorhub2, now))
        return self.environment

    def summarize_sound(self, start: float, end: float) -> dict[str, Any]:
        self.sound_calls.append((start, end))
        return self.sound_summary

    def publish(
        self,
        feature: dict[str, Any],
        environment: dict[str, Any],
        bcg_state: dict[str, Any],
    ) -> None:
        self.history_lengths_at_publish.append(len(self.feature_history))
        self.published.append((feature, environment, bcg_state))


class SensorFrameSamplerTests(unittest.TestCase):
    def test_window_pairing_environment_sound_and_state_contract(self) -> None:
        harness = SamplerHarness()
        harness.bcg_history.extend(
            [
                {"t": 100.0, "status": 1, "hr": 200, "rr": 40, "samples": [9]},
                *[
                    {
                        "t": 101.0 + index,
                        "status": 2 if index == 6 else 5 if index == 5 else 0,
                        "hr": 60 + (2 * index) if index != 9 else None,
                        "rr": 12 + (0.2 * index) if index != 8 else None,
                        "samples": [-32768, 1] if index == 0 else [index],
                    }
                    for index in range(10)
                ],
                {"t": 110.1, "status": 1, "hr": 200, "rr": 40, "samples": [9]},
            ]
        )

        feature = harness.sampler.sample_window(100.0, 110.0)

        self.assertEqual(
            set(feature),
            {
                "t",
                "bucket_start",
                "status",
                "confirmed_status",
                "bed_exit_evidence",
                "status_codes_seen",
                "hr",
                "rr",
                "invalid_hr_count",
                "invalid_rr_count",
                "packet_count",
                "bcg_frames",
                "bcg_latest_t",
                "clip_ratio",
                "bcg_valid",
                "paired_vital_packets",
                "paired_vital_coverage",
                "minimum_bcg_packets",
                "bcg_samples",
                "temperature",
                "humidity",
                "co2",
                "lux",
                "sound_dba",
                "sound_leq_dba",
                "sound_sample_count",
                "sound_window_status",
                "sound_span_db",
                "sound_large_step",
                "pm2_5",
                "voc",
                "esp_fresh",
                "sensor_status",
            },
        )
        self.assertEqual(feature["bcg_frames"], 10)
        self.assertEqual(feature["bcg_latest_t"], 110.0)
        self.assertEqual(feature["status"], 2)
        self.assertEqual(feature["status_codes_seen"], [0, 2, 5])
        self.assertEqual(feature["paired_vital_packets"], 8)
        self.assertEqual(feature["paired_vital_coverage"], 0.8)
        self.assertEqual(feature["hr"], 67.0)
        self.assertEqual(feature["rr"], 12.7)
        self.assertEqual(feature["invalid_hr_count"], 1)
        self.assertEqual(feature["invalid_rr_count"], 1)
        self.assertTrue(feature["bcg_valid"])
        self.assertEqual(feature["clip_ratio"], 0.0909)
        self.assertEqual(feature["packet_count"], 42)
        self.assertEqual(feature["sound_dba"], 41.5)
        self.assertEqual(feature["sound_leq_dba"], 40.75)
        self.assertEqual(feature["sound_sample_count"], 9)
        self.assertEqual(feature["co2"], None)
        self.assertEqual(feature["voc"], 88.0)
        self.assertTrue(feature["esp_fresh"])
        self.assertEqual(
            harness.environment_calls,
            [({"hub": "one"}, {"hub": "two"}, 110.0)],
        )
        self.assertEqual(harness.sound_calls, [(100.0, 110.0)])
        self.assertIs(harness.published[0][0], feature)
        self.assertIs(harness.published[0][1], harness.environment)
        self.assertEqual(harness.published[0][2]["packets"], 42)
        self.assertEqual(harness.history_lengths_at_publish, [1])
        self.assertEqual(harness.feature_history[-1], feature)
        self.assertEqual(
            harness.state["system"]["sound_analysis"],
            {
                **harness.sound_summary,
                "window_start": "1970-01-01T00:01:40+00:00",
                "window_end": "1970-01-01T00:01:50+00:00",
            },
        )

    def test_hr_and_rr_are_never_paired_across_vendor_packets(self) -> None:
        harness = SamplerHarness(
            replace(
                POLICY,
                minimum_bcg_packets=2,
                minimum_paired_vital_coverage=0.5,
            )
        )
        harness.bcg_history.extend(
            [
                {"t": 1.0, "status": 0, "hr": 62, "rr": None, "samples": []},
                {"t": 2.0, "status": 0, "hr": None, "rr": 13, "samples": []},
            ]
        )

        feature = harness.sampler.sample_window(0.0, 10.0)

        self.assertEqual(feature["paired_vital_packets"], 0)
        self.assertEqual(feature["paired_vital_coverage"], 0.0)
        self.assertIsNone(feature["hr"])
        self.assertIsNone(feature["rr"])
        self.assertEqual(feature["invalid_hr_count"], 1)
        self.assertEqual(feature["invalid_rr_count"], 1)
        self.assertFalse(feature["bcg_valid"])

    def test_bed_exit_requires_three_consecutive_completed_buckets(self) -> None:
        harness = SamplerHarness(
            replace(
                POLICY,
                minimum_bcg_packets=1,
                minimum_paired_vital_coverage=1.0,
            )
        )
        harness.bcg_history.extend(
            {
                "t": float(timestamp),
                "status": 1,
                "hr": 64,
                "rr": 13,
                "samples": [],
            }
            for timestamp in (5, 15, 25)
        )

        features = [
            harness.sampler.sample_window(start, start + 10.0)
            for start in (0.0, 10.0, 20.0)
        ]

        self.assertEqual(
            [item["bed_exit_evidence"]["trailing_exit_buckets"] for item in features],
            [1, 2, 3],
        )
        self.assertEqual(
            [item["bed_exit_evidence"]["confirmed"] for item in features],
            [False, False, True],
        )
        self.assertEqual(
            [item["confirmed_status"] for item in features],
            [0, 0, 1],
        )
        self.assertEqual(
            features[-1]["bed_exit_evidence"]["confirmed_by"],
            "consecutive_buckets",
        )


class FakeClock:
    def __init__(self) -> None:
        self.wall = 100.0
        self.steady = 50.0
        self.requested_sleeps: list[float] = []
        self.actual_sleeps = iter((12.0, 8.0))

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.steady

    def sleep(self, requested: float) -> None:
        self.requested_sleeps.append(requested)
        actual = next(self.actual_sleeps)
        self.wall += actual
        self.steady += actual


class SensorFrameCadenceTests(unittest.TestCase):
    def test_loop_keeps_absolute_ten_second_cadence_after_oversleep(self) -> None:
        harness = SamplerHarness()
        fake_clock = FakeClock()
        runtime = replace(
            harness.runtime,
            clock=fake_clock.time,
            monotonic=fake_clock.monotonic,
            sleeper=fake_clock.sleep,
            stop_requested=lambda: len(harness.published) >= 2,
        )

        SensorFrameSampler(POLICY, runtime).run_forever()

        self.assertEqual(fake_clock.requested_sleeps, [10.0, 8.0])
        self.assertEqual(
            [(item[0]["bucket_start"], item[0]["t"]) for item in harness.published],
            [(100.0, 112.0), (112.0, 120.0)],
        )


if __name__ == "__main__":
    unittest.main()
