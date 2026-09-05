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
                    "hr_rr_fit_fusion": {
                        "evidence_epochs": 5,
                        "changed_evidence_winner_count": 2,
                        "agreed_with_confirmed_state_count": 3,
                        "overall_fit_winner_gate_closed_count": 1,
                        "overall_fit_winner_counts": {"n2": 4, "n3": 1},
                        "eligible_fit_winner_counts": {"n2": 5},
                    },
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
        fusion = result["result_change"]["hr_rr_fit_fusion"]
        self.assertEqual(fusion["evidence_epochs"], 5)
        self.assertEqual(fusion["changed_evidence_winner_count"], 2)
        self.assertEqual(fusion["overall_fit_winner_counts"], {
            "n2": 4,
            "n3": 1,
        })
        self.assertFalse(fusion["fit_can_bypass_state_gate"])

    def test_separates_model_delta_from_a_new_session(self):
        old = {
            "acceptance": {},
            "sessions": [{
                "session_id": "common",
                "replay": {"counts": {"wake": 2, "n1": 1}},
            }],
        }
        new = {
            "acceptance": {},
            "sessions": [
                {
                    "session_id": "common",
                    "replay": {"counts": {"wake": 1, "n2": 2}},
                },
                {
                    "session_id": "new",
                    "replay": {"counts": {"wake": 9, "n3": 3}},
                },
            ],
        }

        result = build_comparison(old, new)

        self.assertEqual(result["scope"]["common_sessions"], 1)
        self.assertEqual(result["scope"]["new_sessions"], 1)
        change = result["result_change"]
        self.assertEqual(change["common_cohort_stage_count_delta"], {
            "wake": -1,
            "n1": -1,
            "n2": 2,
            "n3": 0,
            "rem": 0,
        })
        self.assertEqual(change["new_session_stage_counts"], {
            "wake": 9,
            "n1": 0,
            "n2": 0,
            "n3": 3,
            "rem": 0,
        })

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
