"""Regression tests for the read-only Adaptive Learning live contract."""

from __future__ import annotations

import copy
import unittest

from zeep_pod.adaptive_learning import build_adaptive_learning_snapshot
from zeep_pod.api_state_projection import project_consumer_snapshot


def live_snapshot() -> dict:
    devices = {
        key: {"status": "live"}
        for key in (
            "sht3x_dis",
            "opt3001",
            "sph0645",
            "mhz19c",
            "pms7003",
            "sgp40",
        )
    }
    return {
        "session": {
            "active": True,
            "recording": True,
            "session_id": "adaptive-test-session",
            "rest_mode": "sleep",
            "target_duration_s": 25_200,
        },
        "sensor": {
            "environment": {
                "devices": devices,
                "total_count": 6,
                "temperature_c": 23.5,
                "humidity_rh": 52.0,
                "co2_ppm": 810,
                "pm2_5_ug_m3": 8.0,
                "voc_index": 112,
                "lux": 0.2,
                "sound_dba_est": 37.5,
            },
            "bcg": {
                "connected": True,
                "stale": False,
                "analysis_valid": True,
                "heart_rate_bpm": 61.0,
                "respiration_rate": 14.5,
            },
        },
        "sensor_frame": {
            "sequence": 1234,
            "refresh_s": 10,
            "data_age_s": 1.2,
            "stale": False,
            "source": "pi_local_sensor_tick",
        },
        "sleep": {
            "state": "n2",
            "confirmed_state": "n2",
            "confidence": "medium",
            "provisional": False,
            "classification_active": True,
            "movement_ratio": 0.04,
            "version": "sleep-estimator-test",
            "evidence_version": "sleep-evidence-test",
            "evidence_epoch_s": 30,
            "confirmation_s": 60,
            "baseline_definition": {
                "version": "baseline-test",
                "transition_policy": "transition-test",
            },
        },
        "smart_response": {
            "phase": "sleep_session",
            "policy_version": "smart-response-test",
            "recommendations": [
                {
                    "domain": "sound",
                    "level": "attention",
                    "title": "เสียงสูงกว่าเป้าหมาย",
                    "detail": "วัดได้ 37.5 dBA",
                    "suggestion": "เสนอให้ลดระดับเสียง",
                }
            ],
            "blockers": [],
        },
        "aircon": {
            "connected": True,
            "power": True,
            "desired_temperature_c": 23,
            "fan_level": 2,
        },
        "music": {"playing": True, "paused": False, "volume": 60},
        "bed_control": {"connected": True, "active_command": "none"},
        "gpio": {"red_light": False},
        "safety": {"ready": True},
    }


class AdaptiveLearningTests(unittest.TestCase):
    def test_contract_compares_live_values_without_actuation(self) -> None:
        baseline = {
            "status": "active",
            "nights_used": 4,
            "min_nights": 3,
            "hr_sleep_median": 60.0,
            "rr_sleep_median": 14.0,
            "move_ratio_median": 0.03,
            "policy_version": "baseline-test",
        }
        behaviour = {
            "status": "active",
            "sessions_used": 4,
            "minimum_sessions": 3,
            "typical_environment": {
                "temp_median": 23.0,
                "humidity_median": 50.0,
                "co2_median": 760.0,
                "lux_median": 0.1,
                "sound_median": 35.0,
            },
            "respiratory_reference": {"median_rr_brpm": 14.0},
        }
        now = 1_800_000_000
        samples = [
            {
                "t": now - (29 - index) * 10,
                "analysis_epoch_s": now - (29 - index) * 10,
                "hr": 60 + index % 3,
                "rr": 14.0,
                "temp": 23.0,
                "bcg_analysis_valid": True,
            }
            for index in range(30)
        ]
        result = build_adaptive_learning_snapshot(
            live_snapshot(),
            baseline=baseline,
            behaviour=behaviour,
            recent_samples=samples,
            now=now,
        )

        self.assertEqual(result["mode"], "shadow")
        self.assertFalse(result["control_policy"]["automatic_actuation"])
        self.assertIsNone(result["control_policy"]["command_endpoint"])
        self.assertTrue(result["baseline"]["comparison_ready"])
        self.assertFalse(result["baseline"]["personal_direct_stage_influence"])
        self.assertEqual(result["data_quality"]["window_coverage_pct"], 100.0)
        heart_rate = next(
            item for item in result["live_features"] if item["key"] == "heart_rate"
        )
        self.assertEqual(heart_rate["reference"], 60.0)
        self.assertEqual(heart_rate["comparison"], "near_reference")
        self.assertFalse(result["candidate_recommendations"][0]["executable"])
        self.assertEqual(
            result["candidate_recommendations"][0]["decision_id"],
            "adaptive-test-session:1234:sound",
        )

    def test_second_visit_window_can_propose_but_never_execute_adjustments(self):
        behaviour = {
            "status": "learning",
            "sessions_used": 1,
            "minimum_sessions": 3,
            "best_rest_window": {
                "available": True,
                "status": "observed_once",
                "outcome_supported": True,
                "environment_reference_available": True,
                "environment": {
                    "temp_median": 22.0,
                    "humidity_median": 50.0,
                    "co2_median": 700.0,
                    "lux_median": 0.1,
                    "sound_median": 34.0,
                },
            },
        }

        result = build_adaptive_learning_snapshot(
            live_snapshot(),
            behaviour=behaviour,
        )

        self.assertTrue(result["baseline"]["provisional_recommendation_ready"])
        temperature = next(
            item for item in result["live_features"] if item["key"] == "temperature"
        )
        self.assertEqual(temperature["reference"], 22.0)
        personal = [
            item
            for item in result["candidate_recommendations"]
            if item.get("level") == "personal_baseline"
        ]
        self.assertTrue(personal)
        self.assertTrue(all(item["executable"] is False for item in personal))
        self.assertTrue(
            all(item["requires_user_confirmation"] is True for item in personal)
        )
        self.assertFalse(result["control_policy"]["automatic_actuation"])

    def test_unsupported_window_never_drives_adaptive_reference(self) -> None:
        behaviour = {
            "typical_environment": {"temp_median": 24.0},
            "best_rest_window": {
                "available": True,
                "outcome_supported": False,
                "environment_reference_available": True,
                "environment": {"temp_median": 19.0},
            },
        }

        result = build_adaptive_learning_snapshot(
            live_snapshot(),
            behaviour=behaviour,
        )

        temperature = next(
            item for item in result["live_features"] if item["key"] == "temperature"
        )
        self.assertEqual(temperature["reference"], 24.0)
        self.assertFalse(result["baseline"]["provisional_recommendation_ready"])
        self.assertFalse(
            any(
                item.get("level") == "personal_baseline"
                for item in result["candidate_recommendations"]
            )
        )

    def test_stale_or_missing_values_are_not_converted_to_zero(self) -> None:
        snapshot = live_snapshot()
        snapshot["sensor_frame"]["stale"] = True
        snapshot["sensor"]["bcg"]["analysis_valid"] = False
        snapshot["sensor"]["bcg"]["heart_rate_bpm"] = None
        snapshot["sensor"]["environment"]["devices"]["sht3x_dis"]["status"] = "stale"
        result = build_adaptive_learning_snapshot(snapshot)
        heart_rate = next(
            item for item in result["live_features"] if item["key"] == "heart_rate"
        )
        self.assertIsNone(heart_rate["value"])
        self.assertEqual(heart_rate["comparison"], "no_live_value")
        self.assertFalse(result["data_quality"]["vital_pair_live"])
        temperature = next(
            item for item in result["live_features"] if item["key"] == "temperature"
        )
        self.assertIsNone(temperature["value"])
        self.assertIn(
            "sensor_frame_stale",
            {item["code"] for item in result["blockers"]},
        )

    def test_window_uses_unique_recent_canonical_frames(self) -> None:
        now = 1_800_000_000
        current = {
            "t": now,
            "analysis_epoch_s": now,
            "hr": 61,
            "bcg_analysis_valid": True,
        }
        duplicate = {**current, "hr": 62}
        old = {
            "t": now - 600,
            "analysis_epoch_s": now - 600,
            "hr": 80,
            "bcg_analysis_valid": True,
        }
        invalid = {
            "t": now - 10,
            "analysis_epoch_s": now - 10,
            "hr": 90,
            "bcg_analysis_valid": False,
        }
        result = build_adaptive_learning_snapshot(
            live_snapshot(),
            recent_samples=[current, duplicate, old, invalid],
            now=now,
        )
        self.assertEqual(result["data_quality"]["window_samples"], 2)
        self.assertEqual(result["data_quality"]["window_coverage_pct"], 6.7)
        heart_rate = next(
            item for item in result["live_features"] if item["key"] == "heart_rate"
        )
        self.assertEqual(heart_rate["window"]["samples"], 1)
        self.assertEqual(heart_rate["window"]["mean"], 62.0)
        self.assertEqual(heart_rate["window"]["coverage_pct"], 3.3)

    def test_nap_provenance_does_not_claim_all_references_are_same_mode(self) -> None:
        snapshot = live_snapshot()
        snapshot["session"]["rest_mode"] = "nap_recovery"
        result = build_adaptive_learning_snapshot(
            snapshot,
            baseline={
                "status": "active",
                "source": "personal",
                "hr_sleep_median": 60,
                "direct_stage_influence": False,
            },
            behaviour={"status": "active", "sessions_used": 3},
        )
        heart_rate = next(
            item for item in result["live_features"] if item["key"] == "heart_rate"
        )
        self.assertEqual(
            heart_rate["reference_scope"],
            "qualified_overnight_reference",
        )
        self.assertEqual(
            result["baseline"]["physiology_reference_scope"],
            "qualified_overnight_reference",
        )

    def test_sound_window_uses_energy_domain_average(self) -> None:
        now = 1_800_000_000
        samples = [
            {"t": now - 10, "analysis_epoch_s": now - 10, "dba": 30.0},
            {"t": now, "analysis_epoch_s": now, "dba": 50.0},
        ]
        result = build_adaptive_learning_snapshot(
            live_snapshot(),
            recent_samples=samples,
            now=now,
        )
        sound = next(item for item in result["live_features"] if item["key"] == "sound")
        self.assertEqual(sound["window"]["method"], "energy_average_leq")
        self.assertAlmostEqual(sound["window"]["mean"], 47.03, places=2)

    def test_consumer_projection_removes_adaptive_and_raw_fields(self) -> None:
        snapshot = live_snapshot()
        snapshot["adaptive_learning"] = {"private": True}
        snapshot["events_tail"] = [{"internal": True}]
        snapshot["system"] = {"uptime_s": 2, "gpio_pins": {"door": 1}}
        snapshot["sleep"]["personal_behaviour"] = {
            "session_ids": ["private-source-session"],
        }
        snapshot["session"]["personal_rest_baseline"] = {
            "available": False,
            "current_session_excluded": True,
            "source_session_id": "must-not-leak",
        }
        snapshot["sensor"]["bcg"].update(
            {
                "samples": [1, 2],
                "raw_status_code": 2,
                "bed_exit_evidence": {"confirmed": False},
            }
        )
        result = project_consumer_snapshot(
            copy.deepcopy(snapshot),
            {"role": "user"},
        )
        self.assertNotIn("adaptive_learning", result)
        self.assertNotIn("events_tail", result)
        self.assertNotIn("gpio_pins", result["system"])
        self.assertNotIn("samples", result["sensor"]["bcg"])
        self.assertNotIn("personal_behaviour", result["sleep"])
        self.assertIn("personal_rest_baseline", result["session"])
        self.assertNotIn(
            "source_session_id",
            result["session"]["personal_rest_baseline"],
        )

    def test_idle_consumer_never_receives_the_previous_occupants_window(self) -> None:
        snapshot = live_snapshot()
        snapshot["session"]["active"] = False
        snapshot["session"]["personal_rest_baseline"] = {
            "available": True,
            "score_value": 99,
        }
        snapshot["sleep"]["personal_behaviour"] = {
            "best_rest_window": {
                "available": True,
                "score_value": 99,
            }
        }

        result = project_consumer_snapshot(
            snapshot,
            {"role": "user"},
        )

        window = result["session"]["personal_rest_baseline"]
        self.assertFalse(window["available"])
        self.assertIsNone(window["score_value"])


if __name__ == "__main__":
    unittest.main()
