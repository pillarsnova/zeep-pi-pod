"""Regression cases for the extracted live finalization calculations."""

from __future__ import annotations

import unittest
from copy import deepcopy
from datetime import datetime

from sessions.finalization_summary import build_night_summary


class FinalizationSummaryTests(unittest.TestCase):
    def summary(self, states, counts, *, off_bed=None):
        start = "2026-09-19T00:00:00+00:00"
        epoch = datetime.fromisoformat(start).timestamp()
        samples = [
            {"t": epoch + (index + 1) * 30, "sleep": stage, "bed": 1}
            for index, stage in enumerate(states)
        ]
        for index in off_bed or []:
            samples[index]["bed"] = 0
        record = {
            "started_at_utc": start,
            "summary": {"sleep_score_state_counts": counts},
        }
        original = deepcopy((record, samples))
        result = build_night_summary(
            record, samples, duration=len(samples) * 30, sample_interval_s=30,
        )
        self.assertEqual((record, samples), original)
        return result

    def test_overnight_off_bed_bout_preserves_onset_and_waso(self):
        result = self.summary(
            ["wake", "n2", "n3", "wake", "wake", "n2", "rem"],
            {"wake": 3, "n2": 2, "n3": 1, "rem": 1},
            off_bed=[4],
        )
        self.assertEqual(result, {
            "sleep_onset_proxy_s": 30.0,
            "awakenings": 1,
            "waso_proxy_s": 60.0,
            "estimated_sleep_s": 120.0,
            "sleep_efficiency": 0.571,
            "deep_ratio": 0.25,
            "rem_ratio": 0.25,
        })

    def test_awake_nap_does_not_manufacture_sleep_or_awakenings(self):
        result = self.summary(["wake"] * 4, {"wake": 4})
        self.assertIsNone(result["sleep_onset_proxy_s"])
        self.assertEqual(result["awakenings"], 0)
        self.assertEqual(result["waso_proxy_s"], 0.0)
        self.assertEqual(result["estimated_sleep_s"], 0.0)
        self.assertIsNone(result["deep_ratio"])


if __name__ == "__main__":
    unittest.main()
