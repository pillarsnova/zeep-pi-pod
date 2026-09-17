"""Guardrails for the Admin-only Smart Ear level-only shadow."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime

from acoustics import (
    acoustic_contract_snapshot,
    build_acoustic_monitor_snapshot,
    build_acoustic_timeline_snapshot,
)


def live_snapshot(sound_dba: object = 43.2) -> dict:
    return {
        "sensor": {
            "esp32": {"firmware_version": "production-example"},
            "environment": {
                "sound_dba_est": sound_dba,
                "devices": {"sph0645": {"status": "live"}},
            },
        },
        "system": {
            "sound_transform": {"accepted_range_dba": [30, 130]},
            "sound_analysis": {
                "status": "valid",
                "sample_count": 1,
                "leq_dba": sound_dba,
                "min_dba": sound_dba,
                "max_dba": sound_dba,
                "span_db": 0,
                "window_s": 10,
                "window_end": "2026-09-17T00:00:00+00:00",
            },
        },
    }


class AcousticContractTests(unittest.TestCase):
    def test_contract_exposes_candidates_without_claiming_capability(self) -> None:
        contract = acoustic_contract_snapshot()
        encoded = json.dumps(contract, ensure_ascii=False)

        self.assertEqual(contract["mode"], "admin_shadow_level_only")
        self.assertTrue(contract["current_capability"]["sound_level"])
        self.assertFalse(contract["current_capability"]["acoustic_classification"])
        for label in ("speech_like", "snore_like", "cough_like"):
            self.assertIn(label, encoded)
        self.assertNotIn("apnea", encoded.casefold())
        self.assertEqual(
            contract["validation"]["protocol_id"],
            "ZEEP-ACOUSTIC-SHADOW-001",
        )
        self.assertFalse(any(contract["impact"].values()))
        self.assertFalse(contract["clinical_validated"])
        self.assertFalse(contract["automatic_actuation"])

    def test_scalar_level_never_manufactures_a_classification(self) -> None:
        result = build_acoustic_monitor_snapshot(
            live_snapshot(),
            generated_at=datetime(2026, 9, 17, tzinfo=UTC),
        )

        self.assertEqual(result["status"], "level_only")
        self.assertEqual(result["classification_state"], "not_evaluated")
        self.assertEqual(result["confidence_band"], "unavailable")
        self.assertEqual(result["level"]["sound_dba"], 43.2)
        self.assertFalse(result["level"]["certified_laeq"])
        self.assertEqual(result["results"]["shapes"], [])
        self.assertEqual(result["results"]["likely_sources"], [])
        self.assertEqual(result["results"]["human_sound_hypotheses"], [])
        self.assertIn("feature_telemetry_unavailable", result["reason_codes"])
        self.assertFalse(any(result["impact"].values()))

        encoded = json.dumps(result, ensure_ascii=False).casefold()
        for forbidden in ("raw_pcm", "base64", "transcript"):
            self.assertNotIn(forbidden, encoded)
        self.assertNotIn("candidate_label_groups", result)
        self.assertNotIn("validation", result)
        self.assertFalse(result["privacy"]["speaker_identity_processed"])

    def test_invalid_or_stale_level_fails_soft(self) -> None:
        snapshot = live_snapshot(-41.2)
        snapshot["sensor"]["environment"]["devices"]["sph0645"]["status"] = "stale"
        result = build_acoustic_monitor_snapshot(snapshot)

        self.assertEqual(result["status"], "stale")
        self.assertIsNone(result["level"]["sound_dba"])
        self.assertEqual(result["classification_state"], "not_evaluated")
        self.assertIn("sound_level_unavailable", result["reason_codes"])
        self.assertIn("microphone_not_live", result["reason_codes"])


class AcousticTimelineTests(unittest.TestCase):
    def test_level_timeline_marks_only_observed_patterns(self) -> None:
        samples = [
            {"t": 1_000.0, "dba": 40.0},
            {"t": 1_010.0, "dba": 51.0},
            {"t": 1_020.0, "dba": 52.0},
            {"t": 1_030.0, "dba": 53.0},
            {"t": 1_040.0, "dba": 54.0},
            {"t": 1_050.0, "dba": 41.0},
        ]

        result = build_acoustic_timeline_snapshot(
            samples,
            session_id="session-example",
            session_active=True,
            recording=True,
            generated_at=datetime(2026, 9, 17, tzinfo=UTC),
        )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["analysis_scope"], "sound_level_pattern_only")
        self.assertEqual(result["summary"]["coverage_pct"], 100.0)
        self.assertEqual(result["summary"]["peak_dba"], 54.0)
        keys = {event["key"] for event in result["events"]}
        self.assertIn("sustained_high", keys)
        self.assertIn("rapid_change", keys)
        self.assertEqual(result["classification"]["sound_source"], "unknown")
        self.assertEqual(result["classification"]["human_sound"], "not_evaluated")
        self.assertFalse(any(result["impact"].values()))
        self.assertEqual(result["detector"]["version"], "zeep-level-pattern-v1.0")
        self.assertFalse(result["detector"]["certified_laeq"])

        encoded = json.dumps(result, ensure_ascii=False).casefold()
        for unsupported in ("snore_like", "speech_like", "cough_like", "compressor"):
            self.assertNotIn(unsupported, encoded)

    def test_missing_sound_is_visible_without_becoming_a_sound_event(self) -> None:
        result = build_acoustic_timeline_snapshot(
            [
                {"t": 1_000.0, "dba": 40.0},
                {"t": 1_010.0, "dba": None},
                {"t": 1_020.0, "dba": None},
                {"t": 1_030.0, "dba": 41.0},
            ],
            session_id="session-gap",
            session_active=True,
            recording=True,
        )

        gaps = [
            event
            for event in result["events"]
            if event["key"] == "missing_data"
        ]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["category"], "sensor_quality")
        self.assertEqual(result["summary"]["observed_event_count"], 0)
        self.assertEqual(result["summary"]["missing_interval_count"], 1)

    def test_projection_is_bounded_for_an_overnight_session(self) -> None:
        samples = [
            {"t": 1_000.0 + index * 10.0, "dba": 38.0 + index % 4}
            for index in range(1_000)
        ]
        result = build_acoustic_timeline_snapshot(
            samples,
            session_id="session-long",
            session_active=True,
            recording=True,
            max_points=60,
        )

        self.assertLessEqual(len(result["timeline"]["points"]), 60)
        self.assertEqual(
            result["timeline"]["point_count_before_compaction"],
            1_000,
        )
        self.assertTrue(result["timeline"]["compacted"])

    def test_per_sample_cadence_exposes_legacy_restart_gap(self) -> None:
        result = build_acoustic_timeline_snapshot(
            [
                {"t": 1_000.0, "dba": 40.0, "sample_interval_s": 5.0},
                {"t": 1_005.0, "dba": 41.0, "sample_interval_s": 5.0},
                {"t": 1_025.0, "dba": 42.0, "sample_interval_s": 5.0},
            ],
            session_id="session-restored",
            session_active=True,
            recording=True,
            cadence_s=10.0,
        )

        self.assertEqual(result["timeline"]["cadences_s"], [5.0])
        self.assertEqual(result["summary"]["coverage_pct"], 50.0)
        self.assertEqual(result["event_summary"]["counts"]["missing_data"], 1)

    def test_compaction_never_joins_points_across_a_restart_gap(self) -> None:
        samples = [
            {"t": 1_000.0 + index * 10.0, "dba": 40.0}
            for index in range(130)
        ]
        samples.extend(
            {"t": 2_600.0 + index * 10.0, "dba": 42.0}
            for index in range(130)
        )
        result = build_acoustic_timeline_snapshot(
            samples,
            session_id="session-restart-gap",
            session_active=True,
            recording=True,
            max_points=24,
        )

        self.assertLessEqual(len(result["timeline"]["points"]), 24)
        self.assertTrue(
            any(point["gap_before"] for point in result["timeline"]["points"])
        )
        self.assertEqual(result["event_summary"]["counts"]["missing_data"], 1)

    def test_event_totals_survive_visible_event_cap(self) -> None:
        levels = [40.0, 50.0, 50.0, 50.0, 40.0, 40.0]
        samples = [
            {"t": 1_000.0 + index * 10.0, "dba": levels[index % len(levels)]}
            for index in range(240)
        ]
        result = build_acoustic_timeline_snapshot(
            samples,
            session_id="session-many-events",
            session_active=True,
            recording=True,
        )

        self.assertTrue(result["event_summary"]["truncated"])
        self.assertGreater(result["event_summary"]["total_count"], 24)
        self.assertEqual(len(result["events"]), 24)
        self.assertGreater(
            result["event_summary"]["counts"]["rapid_change"],
            sum(event["key"] == "rapid_change" for event in result["events"]),
        )

    def test_idle_projection_contains_no_previous_session_identity(self) -> None:
        result = build_acoustic_timeline_snapshot(
            [],
            session_id="must-not-leak",
            session_active=False,
            recording=False,
        )

        self.assertEqual(result["status"], "no_session")
        self.assertIsNone(result["session"]["session_id"])
        self.assertEqual(result["timeline"]["points"], [])
        self.assertEqual(result["events"], [])


if __name__ == "__main__":
    unittest.main()
