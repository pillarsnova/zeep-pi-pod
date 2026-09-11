"""Safety regression tests for the per-user Sleep Baseline learner."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from personal import BaselineStore, MIN_DETECTED_SLEEP_SECONDS
from sleep_system_policy import (
    PERSONAL_BASELINE_LEARNING_START_UTC,
    PREVIOUS_SESSION_REPORT_VERSION,
    PREVIOUS_SLEEP_QUALITY_VERSION,
)


class _DatabaseStub:
    def __init__(self, final_summary, timeline=None, stage_events=None):
        self.final_summary = final_summary
        self.timeline = timeline or []
        self.stage_events = stage_events or []

    def read_sessions(self, sql, params=()):
        if "type='final_summary'" in sql:
            if self.final_summary is None:
                return []
            return [{"value": json.dumps(self.final_summary)}]
        if "type='sleep_stage'" in sql:
            return list(self.stage_events)
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

    def test_previous_approved_overnight_still_trains_baseline(self):
        summary = {
            "night_summary": {
                "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                "sleep_quality": {
                    "available": True,
                    "quality_type": "sleep",
                    "sleep_detected": True,
                    "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                    "version": PREVIOUS_SLEEP_QUALITY_VERSION,
                },
            },
            "session_report": {
                "version": PREVIOUS_SESSION_REPORT_VERSION,
                "rest_mode": {"group": "sleep", "resolved": "overnight"},
            },
        }
        timeline = [{
            "timestamp": f"2026-09-01T00:{index:02d}:00+00:00",
            "temperature": 24.0,
            "humidity": 50.0,
            "co2": 700.0,
            "lux": 0.0,
            "sound": 38.0,
            "heart_rate": 62.0 + (index % 2),
            "respiration_rate": 14.0,
            "bed_status": "On bed",
        } for index in range(30)]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _DatabaseStub(summary, timeline), Path(temporary.name)
        )

        metrics = store._night_metrics("previous-overnight")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["mode_group"], "sleep")

    def test_current_baseline_excludes_provisional_and_continuity_rows(self):
        summary = {
            "night_summary": {
                "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                "sleep_quality": {
                    "available": True,
                    "quality_type": "sleep",
                    "sleep_detected": True,
                    "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                    "version": PREVIOUS_SLEEP_QUALITY_VERSION,
                },
            },
            "session_report": {
                "version": PREVIOUS_SESSION_REPORT_VERSION,
                "rest_mode": {"group": "sleep", "resolved": "overnight"},
            },
        }
        origin = datetime(2026, 9, 1, tzinfo=timezone.utc)
        timeline = []
        for index in range(36):
            timestamp = origin + timedelta(seconds=(index + 1) * 10)
            timeline.append({
                "timestamp": timestamp.isoformat(),
                "temperature": 24.0,
                "humidity": 50.0,
                "co2": 700.0,
                "lux": 0.0,
                "sound": 38.0,
                "heart_rate": 100.0 if index < 6 else 60.0,
                "respiration_rate": 20.0 if index < 6 else 14.0,
                "bed_status": "On bed",
            })
        stage_events = []
        for index in range(12):
            start = origin + timedelta(seconds=index * 30)
            end = start + timedelta(seconds=30)
            excluded = index < 2
            stage_events.append({
                "timestamp": end.isoformat(),
                "value": json.dumps({
                    "state": "n2",
                    "attribution_start": start.isoformat(),
                    "attribution_end": end.isoformat(),
                    "sample_interval_s": 30,
                    "provisional": excluded,
                    "score_eligible": not excluded,
                    "excluded_from_personal_baseline": excluded,
                }),
            })
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _DatabaseStub(summary, timeline, stage_events),
            Path(temporary.name),
        )

        metrics = store._night_metrics("current-overnight")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["hr_quiet_median"], 60.0)
        self.assertEqual(
            metrics["baseline_stage_filter"],
            "direct_score_eligible_stage_intervals",
        )

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
