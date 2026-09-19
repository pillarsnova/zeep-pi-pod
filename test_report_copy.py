"""Presentation refresh must not recalculate or mutate historical scores."""

import copy
import unittest

from sessions.report_copy import refresh_report_copy
from sessions.result_contract import build_result_contract
from test_restore_summary import _sleep_quality


class ReportCopyTests(unittest.TestCase):
    def test_refreshes_old_words_without_changing_any_other_report_field(self):
        quality = _sleep_quality(82)
        report = {
            "quality": quality,
            "findings": [],
            "sleep_timeline": [{"state": "N2", "duration_s": 30}],
            "restore_summary": {"recommendation": {"primary": "old copy"}},
        }
        session = {
            "rest_mode": "sleep",
            "ended_at_utc": "2026-09-19T00:00:00Z",
            "sleep_quality": quality,
            "session_report": report,
        }
        original = copy.deepcopy(session)
        updated = refresh_report_copy(session)
        self.assertEqual(session, original)
        for key in report.keys() - {"restore_summary"}:
            self.assertEqual(updated[key], report[key])
        self.assertEqual(updated["quality"]["score"], 82)
        self.assertNotEqual(
            updated["restore_summary"]["recommendation"]["primary"], "old copy"
        )
        self.assertEqual(
            updated["restore_summary"],
            build_result_contract(session)["restore_summary"],
        )

    def test_missing_report_does_not_invent_results(self):
        self.assertEqual(refresh_report_copy({}), {})


if __name__ == "__main__":
    unittest.main()
