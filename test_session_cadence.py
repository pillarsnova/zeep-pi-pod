"""Regression tests for complete report-only Session sampling grids."""

from __future__ import annotations

import unittest

from zeep_pod.sessions.cadence import (
    materialise_report_sample_grid,
    normalise_samples_for_report,
)
from zeep_pod.sessions.sleep_decision_projection import (
    apply_sleep_decisions_to_samples,
)
from zeep_pod.sessions.report_projection import project_report_samples


def _utc_timestamp(seconds: int) -> str:
    return f"1970-01-01T00:00:{seconds:02d}+00:00"


class ReportSampleGridTests(unittest.TestCase):
    def test_long_service_gap_is_filled_without_copying_sensor_values(self) -> None:
        samples = [
            {"t": 10.0, "temp": 20.0, "hr": 60.0, "rr": 14.0},
            {"t": 20.0, "temp": 21.0, "hr": 61.0, "rr": 14.0},
            {"t": 600.0, "temp": 22.0, "hr": 62.0, "rr": 14.0},
        ]

        grid, summary = materialise_report_sample_grid(
            samples,
            start_at=0.0,
            end_at=600.0,
            fallback_interval_s=10.0,
        )

        self.assertEqual(len(grid), 60)
        self.assertEqual(summary["synthetic_rows"], 57)
        self.assertAlmostEqual(summary["covered_seconds"], 600.0)
        synthetic = [row for row in grid if row["synthetic_sleep_gap"]]
        self.assertTrue(all(row["temp"] is None for row in synthetic))
        self.assertTrue(all(row["hr"] is None for row in synthetic))
        self.assertEqual(
            [row["temp"] for row in grid if not row["synthetic_sleep_gap"]],
            [20.0, 21.0, 22.0],
        )

    def test_partial_tail_partitions_duration_exactly(self) -> None:
        grid, summary = materialise_report_sample_grid(
            [],
            start_at=0.0,
            end_at=65.5,
            fallback_interval_s=10.0,
        )

        self.assertEqual(len(grid), 7)
        self.assertAlmostEqual(
            sum(row["sample_interval_s"] for row in grid), 65.5
        )
        self.assertEqual(grid[-1]["sample_interval_s"], 5.5)
        self.assertEqual(summary["requested_seconds"], 65.5)

        apply_sleep_decisions_to_samples(
            grid,
            stage_events=[],
            fallback_interval_s=30.0,
        )
        self.assertTrue(all(row["sleep"] == "wake" for row in grid))
        self.assertTrue(all(row["sleep_score_eligible"] for row in grid))

        normalised, interval_s, _ = normalise_samples_for_report(grid, 10.0)
        self.assertEqual(interval_s, 10.0)
        self.assertAlmostEqual(
            sum(row["sample_interval_s"] for row in normalised),
            65.5,
        )
        self.assertEqual(normalised[-1]["sample_interval_s"], 5.5)

    def test_grid_splits_exactly_at_cadence_change(self) -> None:
        source = [{"t": value, "hr": 60.0, "rr": 14.0} for value in (
            10.0, 15.0, 20.0, 25.0, 30.0,
        )]
        segments = [
            {
                "start_at_utc": "1970-01-01T00:00:00+00:00",
                "sample_interval_s": 10.0,
            },
            {
                "start_at_utc": "1970-01-01T00:00:15+00:00",
                "sample_interval_s": 5.0,
            },
        ]

        grid, summary = materialise_report_sample_grid(
            source,
            start_at=0.0,
            end_at=30.0,
            cadence_segments=segments,
            fallback_interval_s=10.0,
        )

        self.assertEqual([row["t"] for row in grid], [10, 15, 20, 25, 30])
        self.assertEqual(summary["unmatched_source_rows"], 0)

    def test_grid_splits_at_explicit_decision_boundary(self) -> None:
        rows, summary = materialise_report_sample_grid(
            [
                {"t": 30.0, "sample_interval_s": 30.0, "hr": 70},
                {"t": 60.0, "sample_interval_s": 30.0, "hr": 68},
                {"t": 85.0, "sample_interval_s": 25.0, "hr": None},
            ],
            start_at=0.0,
            end_at=85.0,
            split_boundaries=[75.0],
            fallback_interval_s=30.0,
        )

        self.assertEqual([row["t"] for row in rows], [30.0, 60.0, 75.0, 85.0])
        self.assertEqual(
            [row["sample_interval_s"] for row in rows],
            [30.0, 30.0, 15.0, 10.0],
        )
        self.assertEqual(summary["covered_seconds"], 85.0)
        self.assertEqual(summary["requested_seconds"], 85.0)
        self.assertEqual(summary["synthetic_rows"], 1)
        self.assertTrue(rows[2]["synthetic_sleep_gap"])
        self.assertFalse(rows[3]["synthetic_sleep_gap"])

    def test_aligned_decision_boundary_keeps_normal_timestamp_jitter(
        self,
    ) -> None:
        rows, summary = materialise_report_sample_grid(
            [
                {"t": 10.25, "hr": 70.0, "rr": 15.0},
                {"t": 20.25, "hr": 69.0, "rr": 15.0},
                {"t": 30.25, "hr": 68.0, "rr": 14.0},
            ],
            start_at=0.0,
            end_at=30.0,
            split_boundaries=[30.0],
            fallback_interval_s=10.0,
        )

        self.assertEqual(summary["matched_source_rows"], 3)
        self.assertEqual(summary["unmatched_source_rows"], 0)
        self.assertEqual(summary["synthetic_rows"], 0)
        self.assertEqual(
            [row["source_t"] for row in rows],
            [10.25, 20.25, 30.25],
        )

    def test_off_grid_boundary_does_not_pull_future_sensor_row_backward(
        self,
    ) -> None:
        rows, summary = materialise_report_sample_grid(
            [{"t": 76.0, "hr": 68.0, "rr": 14.0}],
            start_at=60.0,
            end_at=85.0,
            split_boundaries=[75.0],
            fallback_interval_s=30.0,
        )

        self.assertTrue(rows[0]["synthetic_sleep_gap"])
        self.assertEqual(rows[0]["t"], 75.0)
        self.assertEqual(rows[1]["source_t"], 76.0)
        self.assertEqual(summary["matched_source_rows"], 1)

    def test_synthetic_gap_after_off_bed_cannot_turn_into_wake(self) -> None:
        source = [
            {
                "t": 10.0,
                "bed": "On bed",
                "hr": 60.0,
                "rr": 14.0,
                "bcg_analysis_valid": True,
            },
            {
                "t": 20.0,
                "bed": "Get out of bed",
                "bed_exit_evidence": {"confirmed": True},
                "hr": None,
                "rr": None,
                "bcg_analysis_valid": False,
            },
        ]
        grid, _ = materialise_report_sample_grid(
            source,
            start_at=0.0,
            end_at=60.0,
            fallback_interval_s=10.0,
        )

        apply_sleep_decisions_to_samples(
            grid,
            stage_events=[],
            fallback_interval_s=30.0,
        )

        self.assertEqual(grid[0]["sleep"], "wake")
        self.assertTrue(all(
            row["sleep"] is None
            and row["sleep_data_status"] == "empty_bed"
            for row in grid[1:]
        ))

    def test_report_pipeline_splits_exact_durable_decision_boundaries(self) -> None:
        stage_events = [
            {"timestamp": _utc_timestamp(15), "value": {
                "state": "wake", "attribution_start": _utc_timestamp(0),
                "attribution_end": _utc_timestamp(15),
            }},
            {"timestamp": _utc_timestamp(40), "value": {
                "state": "n1", "attribution_start": _utc_timestamp(25),
                "attribution_end": _utc_timestamp(40),
            }},
        ]
        status_events = [{"timestamp": _utc_timestamp(25), "value": {
            "state": "off_bed", "data_status": "confirmed_off_bed",
            "attribution_start": _utc_timestamp(15),
            "attribution_end": _utc_timestamp(25),
        }}]

        result = project_report_samples(
            [{"t": tick} for tick in (10.0, 20.0, 30.0, 40.0)],
            start_at=0.0,
            end_at=40.0,
            cadence_segments=[],
            sensor_interval_s=10.0,
            decision_interval_s=30.0,
            stage_events=stage_events,
            status_events=status_events,
        )

        self.assertEqual(
            [row["t"] for row in result["samples"]],
            [10.0, 15.0, 25.0, 35.0, 40.0],
        )
        self.assertEqual(result["grid_summary"]["unattributed_seconds"], 0.0)
        self.assertEqual(result["grid_summary"]["five_state_seconds"], 30.0)
        self.assertEqual(result["grid_summary"]["off_bed_seconds"], 10.0)


if __name__ == "__main__":
    unittest.main()
