from __future__ import annotations

import unittest

from sleep_system_policy import (
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    RESTORE_BASELINE_MIN_COMPARISON_SESSIONS,
    SLEEP_SCORE_FORMULA_VERSION,
)
from zeep_pod.sessions.personal_behaviour import aggregate_behaviour_by_mode
from zeep_pod.sessions.restore_summary_baseline import (
    build_baseline_summary,
    build_trend_summary,
)
from zeep_pod.sessions.user_baseline_context import baseline_context


def row(
    session_id: str,
    *,
    group: str,
    score: float,
    formula: str,
    target_key: str | None = None,
) -> dict:
    return {
        "session_id": session_id,
        "mode_group": group,
        "target_key": target_key,
        "duration_s": 1_800 if target_key == "nap_30" else 5_400,
        "start_local_hour": 13.0,
        "wellness_score": score,
        "score_formula_version": formula,
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
