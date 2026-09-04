import unittest

from sleep_session_report import (
    analyse_sleep_cycles,
    build_session_report,
    build_sleep_quality,
    normalise_rest_mode,
)


class SleepSessionReportTests(unittest.TestCase):
    def _quality(self):
        return {
            "available": True,
            "score": 82,
            "level": "ดี",
            "level_key": "good",
            "insight": "ระยะเวลาและความต่อเนื่องโดยรวมอยู่ในเกณฑ์ดี",
            "sleep_efficiency_pct": 85,
        }

    def test_report_separates_stage_results_from_environment_context(self):
        samples = [
            {"bed": "On bed", "hr": 62, "rr": 14, "sleep": "n2",
             "sleep_confidence": "high", "dba": 48, "temp": 25,
             "hum": 52, "co2": 920, "lux": 1},
            {"bed": "Moving", "hr": 66, "rr": 15, "sleep": "wake",
             "sleep_confidence": "medium", "dba": 52, "temp": 25,
             "hum": 52, "co2": 920, "lux": 1,
             "acoustic_corroborated": True},
            {"bed": "On bed", "hr": 60, "rr": 13, "sleep": "n3",
             "sleep_confidence": "high", "dba": 38, "temp": 25,
             "hum": 52, "co2": 790, "lux": 1},
        ]
        counts = {"wake": 1, "n1": 0, "n2": 1, "n3": 1, "rem": 0}
        report = build_session_report(
            15, samples,
            {"estimated_sleep_s": 10, "sleep_onset_proxy_s": 5,
             "awakenings": 1},
            counts, self._quality(), estimator_version="test-model",
        )

        self.assertTrue(report["available"])
        self.assertEqual(sum(stage["pct_scored"] for stage in report["stages"]), 100)
        self.assertEqual([stage["samples"] for stage in report["stages"]], [1, 0, 1, 1, 0])
        self.assertEqual(report["estimator_version"], "test-model")
        self.assertEqual(report["sleep"]["wake_s"], 5)
        self.assertEqual(report["sleep"]["wake_entries"], 1)
        self.assertIn("บริบทเท่านั้น", report["data_quality"]["note"])
        corroborated = next(
            item for item in report["findings"] if item["key"] == "acoustic_corroborated")
        self.assertFalse(corroborated["context_only"])
        sound = next(item for item in report["environment"] if item["key"] == "sound")
        self.assertEqual(sound["outside_target_pct"], 67)

    def test_environment_changes_findings_not_sleep_stages_or_quality(self):
        base = {"bed": "On bed", "hr": 60, "rr": 13, "sleep": "n2"}
        good = [{**base, "dba": 35, "temp": 24, "hum": 50, "co2": 700,
                 "lux": 1, "pm2_5": 8, "voc": 100}]
        poor = [{**base, "dba": 60, "temp": 30, "hum": 75, "co2": 1500,
                 "lux": 40, "pm2_5": 60, "voc": 350}]
        counts = {"wake": 0, "n1": 0, "n2": 1, "n3": 0, "rem": 0}

        good_report = build_session_report(
            5, good, {"estimated_sleep_s": 5}, counts, self._quality())
        poor_report = build_session_report(
            5, poor, {"estimated_sleep_s": 5}, counts, self._quality())

        self.assertEqual(good_report["stages"], poor_report["stages"])
        self.assertEqual(good_report["quality"], poor_report["quality"])
        self.assertEqual(good_report["findings"][0]["severity"], "excellent")
        self.assertTrue(good_report["environment_assessment"]["meets_expected"])
        self.assertEqual(good_report["environment_assessment"]["required_count"], 0)
        self.assertEqual(poor_report["findings"][0]["severity"], "critical")
        self.assertFalse(poor_report["environment_assessment"]["meets_expected"])
        self.assertGreater(poor_report["environment_assessment"]["required_count"], 0)

    def test_missing_environment_is_reported_as_missing_not_good(self):
        report = build_session_report(
            5, [{"bed": "On bed", "hr": 60, "rr": 13, "sleep": "n1"}],
            {"estimated_sleep_s": 5}, {"n1": 1}, self._quality())
        self.assertEqual(report["findings"][0]["severity"], "unavailable")
        self.assertEqual(report["environment_assessment"]["required_count"], 7)
        self.assertFalse(report["environment_assessment"]["meets_expected"])
        self.assertEqual(report["data_quality"]["coverage"]["environment_pct"], 0)

    def test_legacy_timeline_explains_unstored_pm25_and_voc(self):
        report = build_session_report(
            5, [{"temp": 24, "hum": 50, "co2": 700, "lux": 1, "dba": 35}],
            {"estimated_sleep_s": 0}, {}, self._quality(),
            timeline_schema_version=3,
        )
        findings = {item["key"]: item for item in report["findings"]}
        self.assertTrue(findings["pm25"]["legacy_timeline_not_persisted"])
        self.assertTrue(findings["voc"]["legacy_timeline_not_persisted"])
        self.assertIn("Timeline รุ่นเดิมไม่ได้บันทึก", findings["pm25"]["title"])
        self.assertNotIn("legacy_timeline_not_persisted", findings["co2"])

    def test_fair_is_the_minimum_expected_level_not_a_required_fix(self):
        sample = {
            "bed": "On bed", "hr": 60, "rr": 13, "sleep": "n2",
            "temp": 28.5, "hum": 68.0, "co2": 1100.0, "lux": 25.0,
            "dba": 48.0, "pm2_5": 30.0, "voc": 180.0,
        }
        report = build_session_report(
            5, [sample], {"estimated_sleep_s": 5}, {"n2": 1},
            self._quality(), rest_mode="sleep",
        )
        assessment = report["environment_assessment"]
        self.assertEqual(assessment["overall_level"], "fair")
        self.assertTrue(assessment["meets_expected"])
        self.assertEqual(assessment["required_count"], 0)
        self.assertEqual(assessment["optimisation_count"], 7)
        self.assertTrue(all(item["decision"] == "optimise" for item in report["findings"]))

    def test_pilot_mode_changes_light_context_only(self):
        sample = {
            "bed": "On bed", "hr": 60, "rr": 13, "sleep": "n2",
            "temp": 24.0, "hum": 50.0, "co2": 700.0, "lux": 200.0,
            "dba": 48.0, "pm2_5": 8.0, "voc": 100.0,
        }
        counts = {"n2": 1}
        sleep = build_session_report(
            5, [sample], {"estimated_sleep_s": 5}, counts, self._quality(),
            rest_mode="sleep",
        )
        nap = build_session_report(
            5, [sample], {"estimated_sleep_s": 5}, counts, self._quality(),
            rest_mode="nap_recovery",
        )
        sleep_levels = {item["key"]: item["status_key"] for item in sleep["environment"]}
        nap_levels = {item["key"]: item["status_key"] for item in nap["environment"]}
        self.assertEqual(sleep_levels["light"], "critical")
        self.assertEqual(sleep_levels["sound"], "fair")
        self.assertEqual(nap_levels["light"], "poor")
        self.assertEqual(nap_levels["sound"], "fair")
        self.assertEqual(sleep["stages"], nap["stages"])
        self.assertTrue(sleep["environment_assessment"]["context_only"])
        self.assertFalse(sleep["environment_assessment"]["direct_stage_influence"])

    def test_report_preserves_only_confirmed_or_terminal_bed_exit(self):
        samples = [
            {"bed": "On bed", "hr": 60, "rr": 14, "sleep": "n2"},
            {"bed": "Get out of bed", "hr": 60, "rr": 14, "sleep": "n2"},
            {"bed": "On bed", "hr": 60, "rr": 14, "sleep": "n2"},
            {"bed": "Get out of bed", "hr": None, "rr": None, "sleep": "wake"},
        ]
        report = build_session_report(
            20, samples, {"estimated_sleep_s": 15},
            {"wake": 1, "n2": 3}, self._quality(),
        )
        self.assertEqual(report["sleep"]["bed_exit_events"], 1)
        self.assertEqual(report["sleep"]["transient_bed_exit_samples"], 1)
        self.assertEqual(report["sleep"]["confirmed_bed_exit_samples"], 1)

    def test_short_nap_is_not_penalised_for_missing_n3_or_rem(self):
        samples = [{
            "hr": 64.0, "rr": 14.0, "bed": "On bed", "temp": 24.0,
            "hum": 50.0, "co2": 750.0, "dba": 35.0, "lux": 2.0,
        } for _ in range(240)]
        quality = build_sleep_quality(
            20 * 60,
            {"awakenings": 0, "waso_proxy_s": 0, "sleep_onset_proxy_s": 180},
            {"wake": 12, "n1": 60, "n2": 168, "n3": 0, "rem": 0},
            rest_mode="auto",
            sensor_samples=samples,
        )
        self.assertEqual(quality["rest_mode"]["resolved"], "short_nap")
        self.assertEqual(quality["score_title"], "Recovery Score")
        self.assertTrue(quality["sleep_detected"])
        self.assertGreaterEqual(quality["score"], 70)
        self.assertEqual(quality["component_max_points"], {
            "goal_duration": 20.0,
            "physiological_response": 30.0,
            "body_stillness": 20.0,
            "environment_support": 20.0,
            "data_coverage": 10.0,
        })

    def test_overnight_uses_recorded_rounds_with_explicit_project_target(self):
        quality = build_sleep_quality(
            16_670,
            {"awakenings": 16, "waso_proxy_s": 980, "sleep_onset_proxy_s": 184.3},
            {"wake": 225, "n1": 182, "n2": 2309, "n3": 88, "rem": 497},
            rest_mode="sleep",
        )
        self.assertEqual(quality["rest_mode"]["resolved"], "overnight")
        self.assertEqual(quality["rest_mode"]["protocol_status"]["status"], "too_short")
        self.assertEqual(quality["actual_scored_s"], 16_505)
        self.assertEqual(quality["estimated_sleep_s"], 15_380)
        self.assertEqual(quality["duration_target"]["seconds"], 25_200)
        self.assertEqual(quality["sleep_opportunity"]["duration_points"], 9.2)
        self.assertEqual(quality["component_points"]["sleep_opportunity"], 14.2)
        self.assertEqual(quality["architecture"]["points"], {
            "n2": 10.0, "n3": 0.0, "rem": 8.0,
        })
        self.assertEqual(quality["deep_pct"], 2.9)
        self.assertEqual(quality["rem_pct"], 16.2)

    def test_overnight_ideal_formula_totals_one_hundred(self):
        counts = {"wake": 0, "n1": 250, "n2": 3025, "n3": 755, "rem": 1010}
        cycle = ["n1"] * 50 + ["n2"] * 605 + ["n3"] * 151 + ["rem"] * 202
        sequence = cycle * 5
        quality = build_sleep_quality(
            25_200, {"awakenings": 0, "sleep_onset_proxy_s": 600}, counts,
            rest_mode="overnight", stage_sequence=sequence,
            sensor_samples=[{"hr": 58.0, "rr": 13.0} for _ in sequence],
        )
        self.assertEqual(quality["estimated_sleep_s"], 25_200)
        self.assertEqual(quality["component_points"], {
            "sleep_opportunity": 20.0,
            "sleep_stability": 30.0,
            "restorative_architecture": 30.0,
            "cycle_expression": 15.0,
            "data_coverage": 5.0,
        })
        self.assertEqual(quality["score"], 100)

    def test_overnight_score_is_withheld_without_paired_hr_rr(self):
        quality = build_sleep_quality(
            25_200, {"sleep_onset_proxy_s": 600},
            {"n2": 5040}, rest_mode="overnight",
            sensor_samples=[{"hr": None, "rr": None} for _ in range(5040)],
        )
        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        self.assertFalse(quality["release_requirements"]["passed"])
        self.assertEqual(
            quality["release_requirements"]["paired_hr_rr_coverage_pct"], 0.0,
        )

    def test_n3_above_twenty_percent_keeps_full_recovery_credit(self):
        quality = build_sleep_quality(
            25_200,
            {"sleep_onset_proxy_s": 600},
            {"n2": 2520, "n3": 1512, "rem": 1008},
            rest_mode="overnight",
        )
        self.assertEqual(quality["stage_pct_of_sleep"]["n3"], 30.0)
        self.assertEqual(quality["architecture"]["points"]["n3"], 12.0)
        self.assertIn("N3 ≥10%", quality["architecture"]["method"])

    def test_legacy_recovery_modes_map_to_recovery_score_without_demanding_rem(self):
        counts = {"wake": 12, "n1": 60, "n2": 1008, "n3": 0, "rem": 0}
        sequence = ["n1"] * 60 + ["n2"] * 1008 + ["wake"] * 12
        samples = [{
            "hr": 64.0, "rr": 14.0, "bed": "On bed", "temp": 24.0,
            "hum": 50.0, "co2": 750.0, "dba": 35.0, "lux": 2.0,
        } for _ in range(1080)]
        for mode in ("cycle_nap", "shift_rest", "jet_lag"):
            with self.subTest(mode=mode):
                quality = build_sleep_quality(
                    90 * 60,
                    {"awakenings": 1, "sleep_onset_proxy_s": 8 * 60},
                    counts,
                    rest_mode=mode,
                    stage_sequence=sequence,
                    sensor_samples=samples,
                )
                self.assertEqual(quality["score_title"], "Recovery Score")
                self.assertEqual(quality["quality_type"], "rest_goal")
                self.assertNotIn("restorative_architecture", quality["component_points"])
                self.assertTrue(quality["sleep_detected"])

    def test_component_points_have_no_hidden_weight(self):
        quality = build_sleep_quality(
            16_670,
            {"sleep_onset_proxy_s": 184.3},
            {"wake": 225, "n1": 182, "n2": 2309, "n3": 88, "rem": 497},
            rest_mode="overnight",
            stage_sequence=["n2"] * 540 + ["rem"] + ["n2"] * 540 + ["rem"],
        )
        self.assertEqual(sum(quality["component_max_points"].values()), 100)
        self.assertEqual(
            quality["score_unrounded"], round(sum(quality["component_points"].values()), 1))
        self.assertEqual(quality["component_order"], list(quality["component_points"]))

    def test_arousal_proxy_is_debounced_into_episodes(self):
        sequence = []
        for index in range(720):
            shift = 0.15 if index in {5, 20} else 0.0
            sequence.append({
                "state": "n2",
                "metrics": {
                    "bcg_amplitude_shift_ratio": shift,
                    "movement_ratio": 0.0,
                    "bed_status": "On bed",
                },
            })
        quality = build_sleep_quality(
            3600, {}, {"n2": 720}, rest_mode="sleep", stage_sequence=sequence,
        )
        proxy = quality["continuity"]["arousal_proxy"]
        self.assertEqual(proxy["episodes"], 2)
        self.assertEqual(proxy["index_per_hour"], 2.0)
        self.assertEqual(proxy["penalty_points"], 1.0)
        self.assertEqual(quality["continuity"]["balanced_arousal_penalty_points"], 0.5)

    def test_rem_flicker_does_not_create_many_cycles(self):
        sequence = ["n2"] * 540 + ["rem", "n2", "rem", "n2", "rem"]
        cycles = analyse_sleep_cycles(sequence, sample_interval_s=5)
        self.assertTrue(cycles["available"])
        self.assertEqual(cycles["completed_nrem_rem_cycles"], 1)

    def test_all_wake_has_zero_rest_quality(self):
        # An explicitly selected Sleep Session with no observed sleep remains
        # zero; awake wellness goals are scored by their own evidence instead.
        quality = build_sleep_quality(600, {}, {"wake": 120}, rest_mode="sleep")
        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        self.assertEqual(quality["engineering_shadow_score"], 0)

    def test_legacy_meditation_maps_to_nap_refresh_without_inventing_sleep(self):
        samples = []
        for index in range(360):
            samples.append({
                "hr": 68 - 4 * index / 359,
                "rr": 15 - 2 * index / 359,
                "bed": "On bed",
                "temp": 24.0,
                "hum": 50.0,
                "co2": 700.0,
                "dba": 34.0,
                "lux": 2.0,
            })
        quality = build_sleep_quality(
            30 * 60, {}, {"wake": 360}, rest_mode="relax_meditation",
            sensor_samples=samples,
        )
        self.assertTrue(quality["available"])
        self.assertFalse(quality["sleep_detected"])
        self.assertEqual(quality["session_character"], "awake_rest")
        self.assertEqual(quality["score_title"], "Recovery Score")
        self.assertEqual(quality["rest_mode"]["group"], "nap_recovery")
        self.assertGreaterEqual(quality["score"], 80)
        self.assertNotIn("restorative_architecture", quality["component_points"])

    def test_legacy_readiness_maps_to_nap_refresh_and_rewards_stability(self):
        samples = [{
            "hr": 72.0 + (0.2 if index % 2 else -0.2),
            "rr": 15.0,
            "bed": "On bed",
            "temp": 25.0,
            "hum": 48.0,
            "co2": 780.0,
            "dba": 36.0,
            "lux": 35.0,
        } for index in range(180)]
        quality = build_sleep_quality(
            15 * 60, {}, {"wake": 180}, rest_mode="recovery_readiness",
            sensor_samples=samples,
        )
        self.assertEqual(quality["score_title"], "Recovery Score")
        self.assertGreaterEqual(quality["score"], 80)
        self.assertIn("physiological_response", quality["component_points"])

    def test_nap_recovery_without_sleep_uses_recovery_not_sleep_architecture(self):
        samples = [{
            "hr": 65.0, "rr": 14.0, "bed": "On bed", "temp": 24.0,
            "hum": 50.0, "co2": 750.0, "dba": 35.0, "lux": 2.0,
        } for _ in range(360)]
        quality = build_sleep_quality(
            30 * 60, {}, {"wake": 360}, rest_mode="nap_recovery",
            sensor_samples=samples,
        )
        self.assertEqual(quality["rest_mode"]["resolved"], "nap_recovery")
        self.assertEqual(quality["score_title"], "Recovery Score")
        self.assertEqual(quality["quality_type"], "rest_goal")
        self.assertIn("ไม่บังคับให้หลับ", quality["outcome_interpretation"])

    def test_recovery_score_requires_paired_hr_and_rr_coverage(self):
        rows = [{
            "hr": 65.0, "rr": None, "bed": "On bed", "temp": 24.0,
            "hum": 50.0, "co2": 750.0, "dba": 35.0, "lux": 2.0,
        } for _ in range(360)]
        quality = build_sleep_quality(
            30 * 60, {}, {"wake": 360}, rest_mode="nap_recovery",
            sensor_samples=rows,
        )
        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        self.assertEqual(
            quality["physiology"]["paired_hr_rr_coverage_pct"], 0.0,
        )

    def test_recovery_uses_source_coverage_after_30_second_aggregation(self):
        samples = [
            {
                "hr": 62, "rr": 14, "bed": "On bed",
                "temp": 24, "hum": 50, "co2": 700, "dba": 35, "lux": 1,
                "_source_rows": 3, "_paired_hr_rr_rows": 2,
            }
            for _ in range(10)
        ]
        quality = build_sleep_quality(
            300, {"estimated_sleep_s": 0}, {}, completed=True,
            rest_mode="nap_recovery", sensor_samples=samples,
            sample_interval_s=30,
        )
        self.assertFalse(quality["available"])
        self.assertEqual(
            quality["physiology"]["paired_hr_rr_coverage_pct"], 66.7,
        )
        self.assertEqual(quality["physiology"]["source_sensor_samples"], 30)

    def test_two_mode_protocol_windows_are_reported(self):
        samples = [{
            "hr": 66.0, "rr": 14.0, "bed": "On bed", "temp": 24.0,
            "hum": 50.0, "co2": 750.0, "dba": 35.0, "lux": 2.0,
        } for _ in range(360)]
        over_limit = build_sleep_quality(
            46 * 60, {}, {"wake": 360}, rest_mode="nap_recovery",
            sensor_samples=samples,
        )
        self.assertEqual(over_limit["rest_mode"]["protocol_status"]["status"], "over_limit")
        nap = build_sleep_quality(
            20 * 60, {}, {"wake": 240}, rest_mode="nap_recovery",
            sensor_samples=samples[:300],
        )
        self.assertEqual(nap["rest_mode"]["protocol_status"]["status"], "allowed")

    def test_legacy_awake_modes_normalise_to_nap_refresh(self):
        self.assertEqual(normalise_rest_mode("performance_prep"), "nap_recovery")
        self.assertEqual(normalise_rest_mode("physical_comfort"), "nap_recovery")
        self.assertEqual(normalise_rest_mode("relax_meditation"), "nap_recovery")

    def test_both_canonical_modes_follow_their_own_report_path(self):
        sleep = build_sleep_quality(
            5 * 3600, {"sleep_onset_proxy_s": 10 * 60}, {"n2": 3600},
            rest_mode="sleep",
        )
        self.assertEqual(sleep["quality_type"], "sleep")
        self.assertEqual(sleep["rest_mode"]["group"], "sleep")
        self.assertEqual(sleep["rest_mode"]["resolved"], "overnight")
        self.assertEqual(sleep["rest_mode"]["protocol_status"]["status"], "allowed")

        nap = build_sleep_quality(
            30 * 60, {"sleep_onset_proxy_s": 5 * 60}, {"n1": 60, "n2": 300},
            rest_mode="nap_recovery",
        )
        self.assertEqual(nap["quality_type"], "rest_goal")
        self.assertEqual(nap["rest_mode"]["group"], "nap_recovery")
        self.assertEqual(nap["rest_mode"]["resolved"], "short_nap")
        self.assertEqual(nap["score_title"], "Recovery Score")
        self.assertEqual(nap["duration_target"]["range_minutes"], [25, 35])
        self.assertEqual(nap["rest_mode"]["protocol_status"]["status"], "recommended")

    def test_smart_mode_classifies_observed_character_without_guessing_awake_goal(self):
        short = build_sleep_quality(30 * 60, {}, {"n2": 360}, rest_mode="auto")
        cycle = build_sleep_quality(2 * 3600, {}, {"n2": 1440}, rest_mode="auto")
        main = build_sleep_quality(5 * 3600, {}, {"n2": 3600}, rest_mode="auto")
        self.assertEqual(short["rest_mode"]["resolved"], "short_nap")
        self.assertEqual(cycle["rest_mode"]["resolved"], "cycle_nap")
        self.assertEqual(main["rest_mode"]["resolved"], "overnight")
        self.assertEqual(short["rest_mode"]["group"], "nap_recovery")
        self.assertEqual(short["score_title"], "Recovery Score")
        self.assertEqual(cycle["rest_mode"]["group"], "nap_recovery")
        self.assertEqual(cycle["score_title"], "Recovery Score")
        self.assertEqual(main["rest_mode"]["group"], "sleep")
        self.assertEqual(main["score_title"], "Sleep Score")
        self.assertEqual(normalise_rest_mode("auto"), "auto")


if __name__ == "__main__":
    unittest.main()
