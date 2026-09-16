from __future__ import annotations

import unittest

from pydantic import ValidationError

from sleep_system_policy import (
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
    PERSONAL_REST_WINDOW_BASELINE_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
)
from sessions.user_learning_profile import build_user_learning_profile
from sessions.user_profile_response_models import UserLearningProfile


def session(
    session_id: str,
    mode: str,
    score: float | None,
    ended_at: str,
    *,
    formula: str | None = "formula-v1",
    target_minutes: int | None = None,
) -> dict:
    score_type = "sleep_score" if mode == "sleep" else "recovery_score"
    target = None
    if target_minutes is not None:
        target = {
            "key": f"nap_{target_minutes}m",
            "minutes": target_minutes,
        }
    return {
        "session_id": session_id,
        "ended_at_utc": ended_at,
        "duration_s": target_minutes * 60 if target_minutes else 7 * 3600,
        "sample_count": 10,
        "mode": {"group": mode, "target": target},
        "score": {
            "available": score is not None,
            "value": score,
            "type": score_type,
            "formula_version": formula,
        },
    }


class UserLearningProfileTests(unittest.TestCase):
    def build(self, sessions: list[dict], **overrides):
        payload = build_user_learning_profile(
            account_key="person@example.com",
            profile={
                "email": "person@example.com",
                "display_name": "Person",
                "age_group": "30-44",
                "gender": "female",
                "weight_kg": 60,
                "progressive_profile": {
                    "answers": {"private": "must-not-leak"},
                },
            },
            sessions=sessions,
            baseline=overrides.get("baseline"),
            questionnaire=overrides.get(
                "questionnaire",
                {
                    "consent_status": "granted",
                    "answered": 2,
                    "total": 5,
                    "percent": 40,
                    "questionnaire_version": "questionnaire-v1",
                },
            ),
            history_start_utc="2026-09-01T00:00:00+00:00",
        )
        return payload

    def test_combines_all_sessions_without_mixing_score_types(self) -> None:
        rows = [
            session("nap-2", "nap_recovery", 82, "2026-09-14T06:00:00+00:00", target_minutes=30),
            session("sleep-2", "sleep", 88, "2026-09-13T23:00:00+00:00"),
            session("nap-1", "nap_recovery", 78, "2026-09-12T06:00:00+00:00", target_minutes=90),
            session("sleep-1", "sleep", 84, "2026-09-11T23:00:00+00:00"),
        ]
        result = self.build(rows)

        self.assertEqual(result["observed_history"]["session_count"], 4)
        self.assertEqual(result["observed_history"]["data_backed_session_count"], 4)
        self.assertEqual(result["observed_history"]["modes_used"], ["sleep", "nap_recovery"])
        sleep = result["modes"]["sleep"]
        nap = result["modes"]["nap_recovery"]
        self.assertEqual(sleep["average_score"], 86.0)
        self.assertIsNone(nap["average_score"])
        self.assertEqual(sleep["trend"]["change_points"], 4.0)
        self.assertEqual(nap["trend"]["direction"], "target_specific_only")
        self.assertEqual([item["minutes"] for item in nap["targets"]], [30.0, 90.0])
        self.assertEqual(nap["targets"][0]["average_score"], 82.0)
        self.assertEqual(nap["targets"][1]["average_score"], 78.0)

    def test_latest_use_can_have_no_score_without_becoming_zero(self) -> None:
        rows = [
            session(
                "latest",
                "nap_recovery",
                None,
                "2026-09-14T06:00:00+00:00",
                target_minutes=30,
            ),
            session("scored", "nap_recovery", 80, "2026-09-13T06:00:00+00:00", target_minutes=30),
        ]
        result = self.build(rows)
        nap = result["modes"]["nap_recovery"]

        self.assertEqual(result["observed_history"]["last_used_at_utc"], rows[0]["ended_at_utc"])
        self.assertIsNone(nap["latest_score"])
        self.assertEqual(nap["recent_scores"], [])
        target = nap["targets"][0]
        self.assertIsNone(target["latest_score"])
        self.assertEqual(target["recent_scores"][0]["value"], 80.0)
        self.assertEqual(nap["without_score_count"], 1)
        self.assertEqual(result["observed_history"]["without_score_count"], 1)

    def test_trend_never_compares_different_formula_versions(self) -> None:
        rows = [
            session("new", "sleep", 90, "2026-09-14T06:00:00+00:00", formula="v2"),
            session("old", "sleep", 60, "2026-09-13T06:00:00+00:00", formula="v1"),
        ]
        trend = self.build(rows)["modes"]["sleep"]["trend"]

        self.assertFalse(trend["available"])
        self.assertEqual(trend["direction"], "formula_changed")
        self.assertIsNone(trend["change_points"])

    def test_trend_never_compares_scores_without_formula_provenance(self) -> None:
        rows = [
            session(
                "new",
                "sleep",
                90,
                "2026-09-14T06:00:00+00:00",
                formula=None,
            ),
            session(
                "old",
                "sleep",
                50,
                "2026-09-13T06:00:00+00:00",
                formula=None,
            ),
        ]

        sleep = self.build(rows)["modes"]["sleep"]

        self.assertEqual(sleep["latest_score"], 90.0)
        self.assertIsNone(sleep["average_score"])
        self.assertEqual(sleep["trend"]["direction"], "formula_unverified")
        self.assertFalse(sleep["trend"]["available"])

    def test_context_excludes_questionnaire_answers_and_preference_claims(self) -> None:
        baseline = {
            "behaviour_by_mode": {
                "sleep": {
                    "status": "active",
                    "sessions_used": 3,
                    "minimum_sessions": 3,
                    "score_median": 65,
                    "score_typical_range": [60, 90],
                    "typical_environment": {
                        "temp_median": 22.5,
                        "future_private_metric": 123,
                    },
                }
            }
        }
        result = self.build(
            [session("sleep", "sleep", 84, "2026-09-13T06:00:00+00:00")],
            baseline=baseline,
        )

        self.assertFalse(result["profile_context"]["questionnaire"]["answer_values_included"])
        self.assertNotIn("answers", result["profile_context"]["questionnaire"])
        self.assertEqual(
            result["modes"]["sleep"]["baseline"]["environment_role"],
            "observed_exposure_not_user_preference",
        )
        self.assertNotIn(
            "future_private_metric",
            result["modes"]["sleep"]["baseline"]["typical_environment"],
        )
        self.assertNotIn("score_median", result["modes"]["sleep"]["baseline"])
        self.assertNotIn("score_typical_range", result["modes"]["sleep"]["baseline"])
        self.assertFalse(result["ai_contract"]["questionnaire_answers_used"])
        self.assertFalse(result["ai_contract"]["automatic_actuation_allowed"])

    def test_best_rest_window_is_a_prior_target_specific_observation(self) -> None:
        baseline = {
            "behaviour_policy_version": PERSONAL_BEHAVIOUR_BASELINE_VERSION,
            "behaviour_by_mode": {
                "nap_recovery": {
                    "by_target": {
                        "nap_30": {
                            "status": "learning",
                            "sessions_used": 1,
                            "minimum_sessions": 3,
                            "target_specific": True,
                            "target_key": "nap_30",
                            "score_reference": {
                                "status": "learning",
                                "sessions_used": 1,
                                "minimum_sessions": 7,
                                "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                            },
                            "best_rest_window": {
                                "version": PERSONAL_REST_WINDOW_BASELINE_VERSION,
                                "available": True,
                                "status": "observed_once",
                                "maturity_confidence": "low",
                                "sessions_compared": 1,
                                "same_target_only": True,
                                "mode_group": "nap_recovery",
                                "target_key": "nap_30",
                                "timezone": "Asia/Bangkok",
                                "start_local_minute": 780,
                                "end_local_minute": 810,
                                "duration_minutes": 30,
                                "crosses_midnight": False,
                                "start_tolerance_minutes": 15,
                                "score_type": "recovery_score",
                                "score_title": "Recovery Score",
                                "score_value": 82,
                                "score_formula_version": (
                                    RECOVERY_SCORE_FORMULA_VERSION
                                ),
                                "evidence_quality": "high",
                                "outcome_supported": True,
                                "environment_reference_available": True,
                                "environment": {"temp_median": 23.0},
                            },
                        }
                    }
                }
            },
        }
        rows = [
            session(
                "prior-nap",
                "nap_recovery",
                82,
                "2026-09-14T06:00:00+00:00",
                formula=RECOVERY_SCORE_FORMULA_VERSION,
                target_minutes=30,
            )
        ]

        result = self.build(rows, baseline=baseline)
        window = result["modes"]["nap_recovery"]["targets"][0]["baseline"][
            "best_rest_window"
        ]

        self.assertTrue(window["available"])
        self.assertEqual(window["sessions_compared"], 1)
        self.assertEqual(window["first_visible_visit"], 2)
        self.assertEqual(
            window["method"],
            "highest_current_formula_score_then_evidence_then_most_recent",
        )
        self.assertTrue(window["same_mode_only"])
        self.assertTrue(window["same_target_only"])
        self.assertEqual(window["target_key"], "nap_30")
        self.assertEqual(
            window["environment_role"],
            "observed_successful_session_not_confirmed_preference",
        )
        self.assertFalse(window["affects_score"])
        self.assertFalse(window["affects_sleep_state"])
        self.assertTrue(window["current_session_excluded"])
        self.assertFalse(window["automatic_device_control"])
        self.assertTrue(window["requires_user_confirmation"])
        self.assertNotIn("session_id", window)
        self.assertNotIn("ended_at_utc", window)
        self.assertNotIn("source_timestamp", window)

        validate = getattr(UserLearningProfile, "model_validate", None)
        if validate is not None:
            validate(result)
        else:  # pragma: no cover - exercised on the Pi's Pydantic v1 image
            UserLearningProfile.parse_obj(result)

    def test_best_rest_window_model_rejects_unapproved_fields(self) -> None:
        result = self.build([])
        window = result["modes"]["sleep"]["baseline"]["best_rest_window"]
        self.assertFalse(window["available"])
        self.assertEqual(window["first_visible_visit"], 2)
        window["source_session_id"] = "must-not-leak"
        window["source_started_at_utc"] = "2026-09-14T06:00:00+00:00"

        validate = getattr(UserLearningProfile, "model_validate", None)
        with self.assertRaises(ValidationError):
            if validate is not None:
                validate(result)
            else:  # pragma: no cover - exercised on the Pi's Pydantic v1 image
                UserLearningProfile.parse_obj(result)

        window.pop("source_session_id")
        window.pop("source_started_at_utc")
        window["environment"]["future_private_metric"] = 123
        with self.assertRaises(ValidationError):
            if validate is not None:
                validate(result)
            else:  # pragma: no cover - exercised on the Pi's Pydantic v1 image
                UserLearningProfile.parse_obj(result)

    def test_best_rest_window_model_rejects_incoherent_maturity(self) -> None:
        result = self.build([])
        window = result["modes"]["sleep"]["baseline"]["best_rest_window"]
        window["status"] = "stable"
        window["maturity_confidence"] = "high"
        window["sessions_compared"] = 99

        validate = getattr(UserLearningProfile, "model_validate", None)
        with self.assertRaises(ValidationError):
            if validate is not None:
                validate(result)
            else:  # pragma: no cover - exercised on the Pi's Pydantic v1 image
                UserLearningProfile.parse_obj(result)

    def test_empty_history_has_a_clear_cold_start(self) -> None:
        result = self.build([])

        self.assertEqual(result["learning_readiness"]["status"], "no_data")
        self.assertEqual(result["observed_history"]["session_count"], 0)
        self.assertFalse(
            result["learning_readiness"]["personalization_data_ready"]
        )
        self.assertFalse(
            result["learning_readiness"][
                "personalization_inference_authorized"
            ]
        )

    def test_stale_score_without_sensor_data_never_drives_learning(self) -> None:
        rows = [
            session(
                f"no-data-{index}",
                "sleep",
                80 + index,
                f"2026-09-{14 - index:02d}T06:00:00+00:00",
            )
            for index in range(7)
        ]
        for row in rows:
            row["sample_count"] = 0

        sleep = self.build(rows)["modes"]["sleep"]

        self.assertEqual(sleep["scored_count"], 0)
        self.assertIsNone(sleep["latest_score"])
        self.assertIsNone(sleep["typical_duration_minutes"])

    def test_nap_baseline_is_not_ready_without_target_specific_provenance(self) -> None:
        baseline = {
            "behaviour_by_mode": {
                "nap_recovery": {
                    "status": "active",
                    "sessions_used": 7,
                    "minimum_sessions": 3,
                }
            }
        }
        rows = [
            session(
                "nap-90",
                "nap_recovery",
                84,
                "2026-09-14T06:00:00+00:00",
                target_minutes=90,
            )
        ]

        readiness = self.build(rows, baseline=baseline)["learning_readiness"]

        self.assertNotIn(
            "nap_recovery",
            readiness["personal_comparison_ready_modes"],
        )
        self.assertFalse(readiness["personalization_data_ready"])
        self.assertFalse(readiness["personalization_inference_authorized"])
        self.assertTrue(
            any("90" in gap for gap in readiness["data_gaps"])
        )

    def test_nap_target_becomes_ready_only_with_matching_provenance(self) -> None:
        baseline = {
            "behaviour_policy_version": PERSONAL_BEHAVIOUR_BASELINE_VERSION,
            "behaviour_by_mode": {
                "nap_recovery": {
                    "by_target": {
                        "nap_30": {
                            "status": "active",
                            "sessions_used": 7,
                            "minimum_sessions": 3,
                            "target_specific": True,
                            "target_key": "nap_30",
                            "score_reference": {
                                "status": "active",
                                "sessions_used": 7,
                                "minimum_sessions": 7,
                                "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                            },
                        }
                    }
                }
            },
        }
        rows = [
            session(
                f"nap-{index}",
                "nap_recovery",
                80 + index,
                f"2026-09-{14 - index:02d}T06:00:00+00:00",
                formula=RECOVERY_SCORE_FORMULA_VERSION,
                target_minutes=30,
            )
            for index in range(7)
        ]

        result = self.build(rows, baseline=baseline)

        self.assertEqual(
            result["learning_readiness"]["personal_comparison_ready_targets"],
            ["nap_30"],
        )
        self.assertIn(
            "nap_recovery",
            result["learning_readiness"]["personal_comparison_ready_modes"],
        )
        self.assertTrue(
            result["learning_readiness"]["personalization_data_ready"]
        )
        self.assertFalse(
            result["learning_readiness"][
                "personalization_inference_authorized"
            ]
        )
        self.assertEqual(
            result["learning_readiness"]["recommendation_mode"],
            "not_authorized",
        )
        self.assertFalse(
            result["ai_contract"]["personalized_inference_allowed"]
        )
        self.assertFalse(
            result["ai_contract"][
                "purpose_specific_ai_inference_consent_available"
            ]
        )

    def test_legacy_account_key_is_not_published_as_an_email(self) -> None:
        result = build_user_learning_profile(
            account_key="local-user",
            profile={"username": "local-user"},
            sessions=[],
            history_start_utc="2026-09-01T00:00:00+00:00",
        )

        self.assertEqual(result["user"]["identity_type"], "legacy_account_key")
        self.assertIsNone(result["user"]["email"])

    def test_completed_session_without_sensor_data_stays_in_usage_ledger(self) -> None:
        row = session(
            "no-data",
            "nap_recovery",
            None,
            "2026-09-14T06:00:00+00:00",
            target_minutes=30,
        )
        row["sample_count"] = 0

        result = self.build([row])

        self.assertEqual(result["observed_history"]["session_count"], 1)
        self.assertEqual(result["observed_history"]["data_backed_session_count"], 0)
        self.assertEqual(result["observed_history"]["without_sensor_data_count"], 1)
        self.assertEqual(result["modes"]["nap_recovery"]["session_count"], 1)
        self.assertEqual(result["modes"]["nap_recovery"]["without_score_count"], 1)
        self.assertEqual(result["learning_readiness"]["status"], "no_data")


if __name__ == "__main__":
    unittest.main()
