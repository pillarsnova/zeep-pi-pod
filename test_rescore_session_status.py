import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import rescore_session_reports
from rescore_session_reports import (
    _annotated_stage_events,
    _stage_cadence,
    rescore,
)
from sleep_session_report import analyse_sleep_cycles


class RescoreSessionStatusTests(unittest.TestCase):
    @staticmethod
    def _iso(start: datetime, seconds: int) -> str:
        return (start + timedelta(seconds=seconds)).isoformat()

    def _database(self, root: Path) -> None:
        connection = sqlite3.connect(root / "sessions.db")
        connection.executescript("""
            CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY,
                user TEXT,
                username_key TEXT,
                start_time TEXT,
                end_time TEXT,
                duration REAL,
                gender TEXT,
                rest_mode TEXT,
                target_duration_s REAL
            );
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp TEXT,
                type TEXT,
                value TEXT
            );
            CREATE TABLE timeline (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp TEXT,
                temperature REAL,
                humidity REAL,
                co2 REAL,
                lux REAL,
                sound REAL,
                heart_rate REAL,
                respiration_rate REAL,
                bed_status TEXT,
                pm2_5 REAL,
                voc_index REAL
            );
        """)
        start = datetime(2026, 9, 11, tzinfo=timezone.utc)
        connection.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "session-status-1",
                "Tester",
                "tester@example.com",
                start.isoformat(),
                self._iso(start, 120),
                120,
                None,
                "sleep",
                None,
            ),
        )
        final_summary = {
            "rest_mode": "sleep",
            "sample_interval_s": 30,
            "sensor_sample_interval_s": 10,
            "timeline_schema_version": 4,
            "night_summary": {},
            "session_report": {},
        }
        connection.execute(
            "INSERT INTO events(session_id,timestamp,type,value) "
            "VALUES (?,?,?,?)",
            (
                "session-status-1",
                self._iso(start, 120),
                "final_summary",
                json.dumps(final_summary),
            ),
        )

        for end_second, stage in ((30, "wake"), (120, "n1")):
            value = {
                "state": stage,
                "sample_interval_s": 30,
                "attribution_start": self._iso(start, end_second - 30),
                "attribution_end": self._iso(start, end_second),
                "score_eligible": True,
                "metrics": {},
            }
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) "
                "VALUES (?,?,?,?)",
                (
                    "session-status-1",
                    self._iso(start, end_second),
                    "sleep_stage",
                    json.dumps(value),
                ),
            )

        operational = (
            (60, "no_data", "missing_current_vitals"),
            (90, "off_bed", "confirmed_off_bed"),
        )
        for end_second, state, data_status in operational:
            value = {
                "state": state,
                "data_status": data_status,
                "attribution_start": self._iso(start, end_second - 30),
                "attribution_end": self._iso(start, end_second),
                "excluded_from_score": True,
                "excluded_from_personal_baseline": True,
            }
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) "
                "VALUES (?,?,?,?)",
                (
                    "session-status-1",
                    self._iso(start, end_second),
                    "sleep_stage_status",
                    json.dumps(value),
                ),
            )

        for second in range(5, 120, 10):
            bed_status = "Get out of bed" if 60 < second < 90 else "On bed"
            connection.execute(
                "INSERT INTO timeline VALUES "
                "(NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "session-status-1",
                    self._iso(start, second),
                    24.0,
                    50.0,
                    750.0,
                    1.0,
                    38.0,
                    64.0,
                    14.0,
                    bed_status,
                    8.0,
                    100.0,
                ),
            )
        connection.commit()
        connection.close()

    def test_status_interval_preserves_30_second_cadence_without_stages(self):
        value = {
            "state": "no_data",
            "window_start": "2026-09-11T00:00:30+00:00",
            "window_end": "2026-09-11T00:01:00+00:00",
        }

        self.assertEqual(_stage_cadence([value], 10), 30)

    def test_stage_sequence_keeps_decision_duration_on_ten_second_report(
        self,
    ):
        start = datetime(2026, 9, 11, tzinfo=timezone.utc)
        values = []
        rows = []
        for index in range(91):
            end_second = (index + 1) * 30
            values.append({
                "state": "n2" if index < 90 else "rem",
                "sample_interval_s": 30,
                "attribution_start": self._iso(start, end_second - 30),
                "attribution_end": self._iso(start, end_second),
                "metrics": {},
            })
            rows.append({"timestamp": self._iso(start, end_second)})

        _events, sequence, *_rest = _annotated_stage_events(
            rows,
            values,
            [],
            fallback_interval_s=30,
            fallback_estimator="test",
        )
        cycles = analyse_sleep_cycles(sequence, sample_interval_s=10)

        self.assertTrue(all(
            item["sample_interval_s"] == 30 for item in sequence
        ))
        self.assertEqual(cycles["completed_nrem_rem_cycles"], 1)

    def test_rescore_carries_legacy_no_data_but_preserves_off_bed(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            self._database(data_dir)

            with patch(
                "rescore_session_reports.build_session_report",
                wraps=rescore_session_reports.build_session_report,
            ) as build_report:
                result = rescore(
                    data_dir,
                    ["session-status-1"],
                    requested_mode="sleep",
                    apply=False,
                )

            samples = build_report.call_args.args[1]
            self.assertEqual(
                [sample.get("sleep") for sample in samples],
                ["wake"] * 6 + [None] * 3 + ["n1"] * 3,
            )
            self.assertEqual(
                {
                    sample.get("sleep_data_status")
                    for sample in samples[3:6]
                },
                {"continuity_hold"},
            )
            self.assertTrue(all(
                sample["sleep_score_eligible"] is False
                and sample["sleep_excluded_from_score"] is True
                for sample in samples[6:9]
            ))
            self.assertTrue(all(
                sample["sleep_score_eligible"] is True
                and sample["sleep"] == "wake"
                for sample in samples[3:6]
            ))

            item = result["sessions"][0]
            self.assertEqual(item["counts"], {
                "wake": 6, "n1": 3, "n2": 0, "n3": 0, "rem": 0,
            })
            accounting = item["report"]["sleep"][
                "classification_accounting"
            ]
            self.assertEqual(accounting["direct_confirmed_s"], 60)
            self.assertEqual(accounting["continuity_carried_forward_s"], 30)
            self.assertEqual(accounting["no_data_s"], 0)
            self.assertEqual(accounting["off_bed_s"], 30)
            self.assertEqual(accounting["score_eligible_s"], 90)
            self.assertEqual(accounting["accounted_s"], 120)
            self.assertTrue(accounting["arithmetic_invariant"]["holds"])
            self.assertTrue(accounting["display_stage_total_reconciles"])
            self.assertTrue(accounting["score_stage_total_reconciles"])


if __name__ == "__main__":
    unittest.main()
