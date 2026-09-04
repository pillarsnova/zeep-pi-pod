"""Safety regression tests for the per-user Sleep Baseline learner."""

import json
import tempfile
import unittest
from pathlib import Path

from personal import BaselineStore, MIN_DETECTED_SLEEP_SECONDS
from sleep_system_policy import PERSONAL_BASELINE_LEARNING_START_UTC


class _DatabaseStub:
    def __init__(self, final_summary, timeline=None):
        self.final_summary = final_summary
        self.timeline = timeline or []

    def read_sessions(self, sql, params=()):
        if "type='final_summary'" in sql:
            if self.final_summary is None:
                return []
            return [{"value": json.dumps(self.final_summary)}]
        if "FROM timeline" in sql:
            return list(self.timeline)
        return []


def _summary(*, quality_type, sleep_detected, estimated_sleep_s):
    return {
        "night_summary": {
            "estimated_sleep_s": estimated_sleep_s,
            "sleep_quality": {
                "quality_type": quality_type,
                "sleep_detected": sleep_detected,
                "estimated_sleep_s": estimated_sleep_s,
            },
        }
    }


class PersonalBaselineEligibilityTests(unittest.TestCase):
    def _store(self, summary):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return BaselineStore(_DatabaseStub(summary), Path(temporary.name))

    def test_awake_rest_session_never_trains_sleep_baseline(self):
        store = self._store(_summary(
            quality_type="rest_goal", sleep_detected=False,
            estimated_sleep_s=0,
        ))
        self.assertIsNone(store._night_metrics("rest-session"))

    def test_missing_final_report_never_trains_sleep_baseline(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(_DatabaseStub(None), Path(temporary.name))
        self.assertIsNone(store._night_metrics("unfinished-session"))

    def test_too_little_detected_sleep_is_not_a_learning_night(self):
        store = self._store(_summary(
            quality_type="sleep", sleep_detected=True,
            estimated_sleep_s=MIN_DETECTED_SLEEP_SECONDS - 5,
        ))
        self.assertIsNone(store._night_metrics("micro-sleep-session"))

    def test_behaviour_context_is_partitioned_by_mode_and_never_selects_stage(self):
        store = self._store(_summary(
            quality_type="sleep", sleep_detected=True,
            estimated_sleep_s=MIN_DETECTED_SLEEP_SECONDS,
        ))
        store.data["person@example.com"] = {
            "learning_cutoff": {"utc": PERSONAL_BASELINE_LEARNING_START_UTC},
            "behaviour_by_mode": {
                "sleep": {
                    "status": "active",
                    "sessions_used": 3,
                    "expected_onset_minutes": 14.0,
                    "direct_stage_influence": False,
                },
            },
        }

        sleep = store.behaviour_context("person@example.com", "overnight")
        nap = store.behaviour_context("person@example.com", "nap_recovery")

        self.assertEqual(sleep["expected_onset_minutes"], 14.0)
        self.assertFalse(sleep["direct_stage_influence"])
        self.assertEqual(nap["status"], "no_data")
