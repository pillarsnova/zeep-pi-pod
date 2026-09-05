import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from compare_sleep_history_replay import build_comparison, main


class ReplayComparisonTests(unittest.TestCase):
    def test_reports_state_and_score_release_separately(self):
        old = {
            "acceptance": {
                "wellness_derived_promotion_eligible_session_ids": [],
            },
            "sessions": [{
                "session_id": "session-1",
                "email": "person@example.test",
                "old_score": 80,
                "shadow_score": None,
                "quality": {"tier": "exclude"},
                "replay": None,
                "manual_review_flags": ["wellness_score_not_releasable"],
            }],
        }
        new = {
            "acceptance": {
                "wellness_derived_promotion_eligible_session_ids": [
                    "session-1",
                ],
            },
            "sessions": [{
                "session_id": "session-1",
                "email": "person@example.test",
                "old_score": 80,
                "shadow_score": None,
                "shadow_engineering_score": 71,
                "shadow_score_releasable": False,
                "quality": {"tier": "below_B"},
                "review_warnings": ["wellness_score_not_releasable"],
                "promotion_blockers": [],
                "replay": {
                    "counts": {"wake": 4},
                    "confirmed_coverage_percent": 70.0,
                },
            }],
        }

        result = build_comparison(old, new)

        self.assertEqual(
            result["policy_change"]["new_promotion_eligible_sessions"],
            1,
        )
        self.assertEqual(result["result_change"]["scores_withheld"], 1)
        self.assertEqual(
            result["result_change"]["new_stage_counts"]["wake"],
            4,
        )
        self.assertEqual(
            result["result_change"]["confirmed_stage_coverage_percent"],
            100.0,
        )
        self.assertEqual(
            result["sessions"][0]["new_engineering_shadow_score"],
            71,
        )
        self.assertTrue(result["sessions"][0]["stage_counts_changed"])

    def test_cli_stdout_contains_aggregate_without_session_ids_or_emails(self):
        old = {
            "acceptance": {
                "wellness_derived_promotion_eligible_session_ids": [],
            },
            "sessions": [],
        }
        new = {
            "acceptance": {
                "wellness_derived_promotion_eligible_session_ids": ["private-id"],
            },
            "sessions": [{
                "session_id": "private-id",
                "email": "private@example.test",
                "quality": {"tier": "below_B"},
                "promotion_blockers": [],
                "replay": {},
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_path = root / "old.json"
            new_path = root / "new.json"
            old_path.write_text(json.dumps(old), encoding="utf-8")
            new_path.write_text(json.dumps(new), encoding="utf-8")
            output = io.StringIO()
            argv = [
                "compare_sleep_history_replay.py",
                "--old", str(old_path),
                "--new", str(new_path),
                "--json-output", str(root / "private.json"),
                "--markdown-output", str(root / "private.md"),
            ]
            with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                self.assertEqual(main(), 0)

        stdout = output.getvalue()
        self.assertNotIn("private-id", stdout)
        self.assertNotIn("private@example.test", stdout)
        self.assertEqual(json.loads(stdout)["sessions"], 1)


if __name__ == "__main__":
    unittest.main()
