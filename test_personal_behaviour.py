from __future__ import annotations

import unittest

from sleep_system_policy import (
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
    PERSONAL_REST_WINDOW_BASELINE_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
    SLEEP_SCORE_FORMULA_VERSION,
)
from zeep_pod.sessions.personal_behaviour import aggregate_behaviour_by_mode
from zeep_pod.sessions.restore_summary_baseline import (
    build_baseline_summary,
    build_trend_summary,
)
from zeep_pod.sessions.user_baseline_context import (
    baseline_context,
    best_rest_window_context,
)


def row(
    session_id: str,
    *,
    group: str,
    score: float,
    formula: str,
    target_key: str | None = None,
    start_local_hour: float = 13.0,
    duration_s: float | None = None,
    confidence: str = "high",
    baseline_reference_eligible: bool = True,
    outcome_reference_eligible: bool | None = None,
    environment_reference_eligible: bool | None = None,
) -> dict:
    return {
        "session_id": session_id,
        "mode_group": group,
        "target_key": target_key,
        "duration_s": (
            duration_s
            if duration_s is not None
            else 1_800
            if target_key == "nap_30"
            else 5_400
        ),
        "start_local_hour": start_local_hour,
        "wellness_score": score,
        "score_formula_version": formula,
        "score_confidence_level": confidence,
        "baseline_reference_eligible": baseline_reference_eligible,
        "outcome_reference_eligible": (
            confidence in {"medium", "high"}
            if outcome_reference_eligible is None
            else outcome_reference_eligible
        ),
        "environment_reference_eligible": (
            confidence in {"medium", "high"}
            if environment_reference_eligible is None
            else environment_reference_eligible
        ),
        "temp_median": 23.0,
        "respiratory_rr_median": 14.0,
    }


def aggregate(rows: list[dict]) -> dict:
    return aggregate_behaviour_by_mode(
        rows,
        minimum_sessions=3,
        score_minimum_sessions=RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
        max_sessions=30,
    )


class PersonalBehaviourTests(unittest.TestCase):
    def test_cold_start_nap_baseline_keeps_requested_target_identity(self) -> None:
        for key in ("nap_30", "nap_90"):
            with self.subTest(key=key):
                context = baseline_context(
                    {"behaviour_by_mode": {}},
                    "nap_recovery",
                    key,
                )
                self.assertEqual(context["status"], "no_data")
                self.assertTrue(context["target_specific"])
                self.assertEqual(context["target_key"], key)
                window = context["best_rest_window"]
                self.assertEqual(
                    window["version"],
                    PERSONAL_REST_WINDOW_BASELINE_VERSION,
                )
                self.assertFalse(window["available"])
                self.assertEqual(window["first_visible_visit"], 2)

    def test_sleep_window_does_not_claim_nap_target_isolation(self) -> None:
        context = baseline_context(
            {"behaviour_by_mode": {}},
            "sleep",
            "overnight_7h",
        )

        self.assertFalse(context["best_rest_window"]["same_target_only"])

    def test_incoherent_stored_window_fails_closed(self) -> None:
        window = best_rest_window_context(
            {
                "version": PERSONAL_REST_WINDOW_BASELINE_VERSION,
                "available": True,
                "status": "stable",
                "maturity_confidence": "high",
                "sessions_compared": 99,
                "mode_group": "nap_recovery",
                "target_key": "overnight_7h",
                "start_local_minute": 780,
                "end_local_minute": 810,
                "duration_minutes": 30,
                "score_type": "sleep_score",
                "score_title": "Sleep Score",
                "score_value": 99,
                "score_formula_version": SLEEP_SCORE_FORMULA_VERSION,
                "outcome_supported": True,
            }
        )

        self.assertFalse(window["available"])
        self.assertEqual(window["status"], "no_data")
        self.assertEqual(window["sessions_compared"], 0)
        self.assertIsNone(window["score_value"])

    def test_one_prior_session_becomes_an_observational_second_visit_window(self):
        context = aggregate(
            [
                row(
                    "prior-night",
                    group="sleep",
                    score=86,
                    formula=SLEEP_SCORE_FORMULA_VERSION,
                    start_local_hour=22.5,
                    duration_s=8 * 3_600,
                )
            ]
        )["sleep"]
        window = context["best_rest_window"]

        self.assertTrue(window["available"])
        self.assertEqual(window["status"], "observed_once")
        self.assertEqual(window["maturity_confidence"], "low")
        self.assertEqual(window["sessions_compared"], 1)
        self.assertEqual(window["start_local_minute"], 22 * 60 + 30)
        self.assertEqual(window["end_local_minute"], 6 * 60 + 30)
        self.assertTrue(window["crosses_midnight"])
        self.assertEqual(window["score_type"], "sleep_score")
        self.assertFalse(window["affects_score"])
        self.assertFalse(window["affects_sleep_state"])
        self.assertFalse(window["automatic_device_control"])
        self.assertTrue(window["requires_user_confirmation"])
        self.assertNotIn("session_id", window)

    def test_best_window_prefers_score_then_evidence_then_recency(self):
        rows = [
            row(
                "new-low",
                group="sleep",
                score=90,
                formula=SLEEP_SCORE_FORMULA_VERSION,
                start_local_hour=23.0,
                confidence="low",
                baseline_reference_eligible=False,
            ),
            row(
                "older-high",
                group="sleep",
                score=90,
                formula=SLEEP_SCORE_FORMULA_VERSION,
                start_local_hour=22.0,
                confidence="high",
            ),
            row(
                "lower",
                group="sleep",
                score=89,
                formula=SLEEP_SCORE_FORMULA_VERSION,
                start_local_hour=21.0,
            ),
        ]
        window = aggregate(rows)["sleep"]["best_rest_window"]

        self.assertEqual(window["start_local_minute"], 22 * 60)
        self.assertEqual(window["evidence_quality"], "high")
        self.assertTrue(window["outcome_supported"])
        self.assertTrue(window["environment_reference_available"])

    def test_low_evidence_can_show_time_but_not_drive_environment(self):
        window = aggregate(
            [
                row(
                    "limited",
                    group="nap_recovery",
                    target_key="nap_30",
                    score=75,
                    formula=RECOVERY_SCORE_FORMULA_VERSION,
                    confidence="low",
                    baseline_reference_eligible=False,
                )
            ]
        )["nap_recovery"]["by_target"]["nap_30"]["best_rest_window"]

        self.assertTrue(window["available"])
        self.assertFalse(window["outcome_supported"])
        self.assertFalse(window["environment_reference_available"])
        self.assertEqual(window["environment"], {})

    def test_old_formulas_do_not_inflate_current_score_maturity(self) -> None:
        rows = [
            row(
                f"old-{index}",
                group="sleep",
                score=70 + index,
                formula="zeep-sleep-score-v1.0-reviewed",
            )
            for index in range(7)
        ]
        rows.insert(
            0,
            row(
                "current",
                group="sleep",
                score=88,
                formula=SLEEP_SCORE_FORMULA_VERSION,
            ),
        )
        context = aggregate(rows)["sleep"]
        context["baseline_policy_version"] = PERSONAL_BEHAVIOUR_BASELINE_VERSION

        self.assertEqual(context["sessions_used"], 8)
        self.assertEqual(context["score_reference"]["sessions_used"], 1)
        self.assertEqual(context["score_reference"]["status"], "learning")
        summary = build_baseline_summary(
            context,
            90,
            "sleep",
            source_formula_version=SLEEP_SCORE_FORMULA_VERSION,
            source_target_key="overnight_7h",
        )
        self.assertEqual(summary["maturity"]["sessions_used"], 1)
        self.assertFalse(summary["comparison"]["available"])

    def test_nap_30_and_90_are_independent_cohorts(self) -> None:
        rows = [
            row(
                f"nap-30-{index}",
                group="nap_recovery",
                score=80 + index,
                formula=RECOVERY_SCORE_FORMULA_VERSION,
                target_key="nap_30",
            )
            for index in range(4)
        ] + [
            row(
                f"nap-90-{index}",
                group="nap_recovery",
                score=60 + index,
                formula=RECOVERY_SCORE_FORMULA_VERSION,
                target_key="nap_90",
            )
            for index in range(4)
        ]

        context = aggregate(rows)["nap_recovery"]

        self.assertEqual(context["scores"], [])
        self.assertEqual(context["score_reference"]["status"], "target_required")
        self.assertFalse(context["best_rest_window"]["available"])
        self.assertEqual(
            context["by_target"]["nap_30"]["scores"],
            [83.0, 82.0, 81.0, 80.0],
        )
        self.assertEqual(
            context["by_target"]["nap_90"]["scores"],
            [63.0, 62.0, 61.0, 60.0],
        )

    def test_unknown_nap_target_is_never_inferred_from_duration(self) -> None:
        unresolved = row(
            "legacy-long",
            group="nap_recovery",
            score=85,
            formula=RECOVERY_SCORE_FORMULA_VERSION,
            target_key=None,
        )
        unresolved["duration_s"] = 90 * 60

        context = aggregate([unresolved])["nap_recovery"]

        self.assertEqual(context["unresolved_target_sessions"], 1)
        self.assertEqual(context["by_target"]["nap_30"]["sessions_used"], 0)
        self.assertEqual(context["by_target"]["nap_90"]["sessions_used"], 0)

    def test_zero_is_a_measured_score_not_missing_data(self) -> None:
        context = aggregate([
            row(
                "zero",
                group="sleep",
                score=0,
                formula=SLEEP_SCORE_FORMULA_VERSION,
            )
        ])["sleep"]

        self.assertEqual(context["scores"], [0.0])
        self.assertEqual(context["score_reference"]["sessions_used"], 1)

    def test_comparison_rejects_cross_formula_and_cross_target_context(self) -> None:
        rows = [
            row(
                f"nap-{index}",
                group="nap_recovery",
                score=80 + index,
                formula=RECOVERY_SCORE_FORMULA_VERSION,
                target_key="nap_30",
            )
            for index in range(7)
        ]
        context = aggregate(rows)["nap_recovery"]["by_target"]["nap_30"]
        context["baseline_policy_version"] = PERSONAL_BEHAVIOUR_BASELINE_VERSION

        wrong_formula = build_baseline_summary(
            context,
            90,
            "nap_recovery",
            source_formula_version="recovery-score-obsolete",
            source_target_key="nap_30",
        )
        wrong_target = build_trend_summary(
            context,
            group="nap_recovery",
            source_formula_version=RECOVERY_SCORE_FORMULA_VERSION,
            source_target_key="nap_90",
        )

        self.assertFalse(wrong_formula["comparison"]["available"])
        self.assertEqual(wrong_formula["maturity"]["sessions_used"], 0)
        self.assertFalse(wrong_target["available"])

    def test_target_cohorts_are_capped_independently(self) -> None:
        rows = [
            row(
                f"nap-30-{index}",
                group="nap_recovery",
                score=80,
                formula=RECOVERY_SCORE_FORMULA_VERSION,
                target_key="nap_30",
            )
            for index in range(30)
        ]
        rows.extend(
            row(
                f"nap-90-{index}",
                group="nap_recovery",
                score=75,
                formula=RECOVERY_SCORE_FORMULA_VERSION,
                target_key="nap_90",
            )
            for index in range(7)
        )

        context = aggregate(rows)["nap_recovery"]

        self.assertEqual(context["by_target"]["nap_30"]["sessions_used"], 30)
        self.assertEqual(context["by_target"]["nap_90"]["sessions_used"], 7)


if __name__ == "__main__":
    unittest.main()
