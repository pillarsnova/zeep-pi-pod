"""Tests for gap-free user-visible Sleep history periods."""

from __future__ import annotations

import unittest

from zeep_pod.sessions.history_sleep_timeline import (
    fill_history_sleep_timeline_continuity,
    history_sleep_state_counts,
    history_sleep_timeline,
)


class HistorySleepTimelineContinuityTests(unittest.TestCase):
    def test_initial_and_interior_gaps_receive_a_five_state_label(self) -> None:
        periods = [{
            "start_time": "1970-01-01T00:01:00+00:00",
            "end_time": "1970-01-01T00:02:00+00:00",
            "duration_s": 60.0,
            "state": "n2",
            "sleep_stage": True,
        }]

        completed = fill_history_sleep_timeline_continuity(
            periods,
            session_start="1970-01-01T00:00:00+00:00",
            classification_end="1970-01-01T00:03:00+00:00",
            fallback_estimator="test-v1",
        )

        self.assertEqual([row["state"] for row in completed], ["wake", "n2", "n2"])
        self.assertEqual(sum(row["duration_s"] for row in completed), 180.0)
        self.assertTrue(completed[0]["score_eligible"])
        self.assertTrue(completed[-1]["excluded_from_personal_baseline"])

    def test_off_bed_is_held_until_a_later_stage_proves_return(self) -> None:
        periods = [
            {
                "start_time": "1970-01-01T00:00:00+00:00",
                "end_time": "1970-01-01T00:01:00+00:00",
                "duration_s": 60.0,
                "state": "n2",
                "sleep_stage": True,
            },
            {
                "start_time": "1970-01-01T00:01:00+00:00",
                "end_time": "1970-01-01T00:01:30+00:00",
                "duration_s": 30.0,
                "state": "off_bed",
                "sleep_stage": False,
            },
            {
                "start_time": "1970-01-01T00:02:30+00:00",
                "end_time": "1970-01-01T00:03:00+00:00",
                "duration_s": 30.0,
                "state": "wake",
                "sleep_stage": True,
            },
        ]

        completed = fill_history_sleep_timeline_continuity(
            periods,
            session_start="1970-01-01T00:00:00+00:00",
            classification_end="1970-01-01T00:03:00+00:00",
        )

        self.assertEqual(
            [row["state"] for row in completed],
            ["n2", "off_bed", "off_bed", "wake"],
        )
        self.assertFalse(completed[2]["score_eligible"])
        self.assertEqual(sum(row["duration_s"] for row in completed), 180.0)

    def test_wait_and_no_data_status_do_not_replace_stage_time(self) -> None:
        stage = {
            "timestamp": "1970-01-01T00:00:30+00:00",
            "state": "wake",
            "sample_interval_s": 30.0,
        }
        no_data = {
            "timestamp": "1970-01-01T00:00:30+00:00",
            "state": "no_data",
            "data_status": "missing_vitals",
            "sample_interval_s": 30.0,
        }

        periods, _ = history_sleep_timeline(
            [stage],
            [no_data],
            report_end="1970-01-01T00:00:30+00:00",
            sample_interval_s=30.0,
            fallback_estimator=None,
        )

        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0]["state"], "wake")

    def test_report_counts_use_projected_rows_and_partial_duration(self) -> None:
        samples = [
            {
                "sleep": "wake",
                "sample_interval_s": 10.0,
                "sleep_score_eligible": True,
            },
            {
                "sleep": "n2",
                "sample_interval_s": 10.0,
                "sleep_score_eligible": False,
            },
            {
                "sleep": "n2",
                "sample_interval_s": 5.0,
                "sleep_score_eligible": True,
            },
            {
                "sleep": None,
                "sample_interval_s": 10.0,
                "sleep_data_status": "empty_bed",
                "sleep_score_eligible": False,
            },
        ]

        display, score = history_sleep_state_counts(
            samples,
            sample_interval_s=10.0,
        )

        self.assertEqual(display, {"wake": 1.0, "n2": 1.5})
        self.assertEqual(score, {"wake": 1.0, "n2": 0.5})


if __name__ == "__main__":
    unittest.main()
