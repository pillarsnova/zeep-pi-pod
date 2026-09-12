"""History compatibility reports replay the complete projected State stream."""

from __future__ import annotations

import json
import time
import unittest
from unittest.mock import patch

from fastapi import Response

from testing_support import configure_app_test_environment


configure_app_test_environment()

import app as pod_app  # noqa: E402


class HistoryReportProjectionTests(unittest.TestCase):
    def test_legacy_report_rebuild_uses_materialized_continuity_counts(self) -> None:
        row = {
            "session_id": "history-continuity",
            "user": "Sleeper",
            "username_key": "sleeper@example.test",
            "gender": "female",
            "start_time": "1970-01-01T00:00:00+00:00",
            "end_time": "1970-01-01T00:02:00+00:00",
            "duration": 120.0,
            "end_reason": "logout",
            "rest_mode": "sleep",
            "target_duration_s": None,
        }
        timeline = [
            {
                "timestamp": "1970-01-01T00:00:10+00:00",
                "temperature": 22.0,
                "humidity": 50.0,
                "co2": 600.0,
                "pm2_5": 3.0,
                "voc_index": 80.0,
                "lux": 1.0,
                "sound": 35.0,
                "heart_rate": 62.0,
                "respiration_rate": 14.0,
                "bed_status": "On bed",
            },
            {
                "timestamp": "1970-01-01T00:01:55+00:00",
                "temperature": 22.0,
                "humidity": 50.0,
                "co2": 600.0,
                "pm2_5": 3.0,
                "voc_index": 80.0,
                "lux": 1.0,
                "sound": 35.0,
                "heart_rate": None,
                "respiration_rate": None,
                "bed_status": "Get out of bed",
            },
        ]

        def stage_event(end_second: int, state: str) -> dict[str, str]:
            start_second = end_second - 30
            value = {
                "state": state,
                "sample_interval_s": 30.0,
                "attribution_start": (
                    f"1970-01-01T00:{start_second // 60:02d}:"
                    f"{start_second % 60:02d}+00:00"
                ),
                "attribution_end": (
                    f"1970-01-01T00:{end_second // 60:02d}:"
                    f"{end_second % 60:02d}+00:00"
                ),
                "score_eligible": True,
            }
            return {
                "timestamp": value["attribution_end"],
                "type": "sleep_stage",
                "value": json.dumps(value),
            }

        final_summary = {
            "sample_interval_s": 10.0,
            "sensor_sample_interval_s": 10.0,
            "timeline_schema_version": 4,
            "rest_mode": "sleep",
            # These deliberately stale aggregates must not leak into the
            # display-only current report.
            "sleep_state_counts": {"wake": 1},
            "sleep_score_state_counts": {"wake": 1},
            "night_summary": {},
            "session_report": {"version": "legacy-report"},
        }
        events = [
            stage_event(30, "n2"),
            stage_event(120, "rem"),
            {
                "timestamp": row["end_time"],
                "type": "final_summary",
                "value": json.dumps(final_summary),
            },
        ]

        def read_sessions(query: str, _params: tuple[object, ...]):
            if "SELECT s.*" in query:
                return [row]
            if "FROM timeline" in query:
                return timeline
            if "FROM events" in query:
                return events
            raise AssertionError(query)

        principal = pod_app.Principal(
            session_id="history-test",
            subject="user:sleeper@example.test",
            username="sleeper@example.test",
            display_name="Sleeper",
            account_key="sleeper@example.test",
            email="sleeper@example.test",
            role="user",
            auth_source="zeep",
            csrf_token="history-test",
            expires_at=time.time() + 60,
        )
        with (
            patch.object(
                pod_app.database,
                "read_sessions",
                side_effect=read_sessions,
            ),
            patch.object(
                pod_app,
                "_load_profiles",
                return_value={
                    "sleeper@example.test": {"display_name": "Sleeper"}
                },
            ),
        ):
            detail = pod_app.history_detail(
                "sleeper@example.test",
                "history-continuity",
                Response(),
                principal,
            )

        report = detail["session_report"]
        stages = {item["state"]: item for item in report["stages"]}
        self.assertTrue(report["display_recomputed"])
        self.assertEqual(stages["wake"]["duration_s"], 0.0)
        self.assertEqual(stages["n2"]["duration_s"], 90.0)
        self.assertEqual(stages["rem"]["duration_s"], 15.0)
        self.assertEqual(
            detail["summary"]["sleep_state_counts"],
            {"n2": 9.0, "rem": 1.5},
        )
        accounting = report["sleep"]["classification_accounting"]
        self.assertEqual(accounting["display_attributed_s"], 105.0)
        self.assertEqual(accounting["score_eligible_s"], 105.0)
        self.assertEqual(accounting["off_bed_s"], 15.0)
        self.assertEqual(accounting["sensor_gap_s"], 0.0)
        self.assertEqual(
            sum(
                period["duration_s"]
                for period in detail["sleep_timeline"]
                if period["state"] in {"wake", "n1", "n2", "n3", "rem"}
            ),
            accounting["display_attributed_s"],
        )


if __name__ == "__main__":
    unittest.main()
