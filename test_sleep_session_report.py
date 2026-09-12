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

    def test_report_reconciles_continuity_and_operational_time(self):
        rows = [
            {
                "bed": "On bed", "hr": 65, "rr": 14,
                "sleep": None,
                "sleep_data_status": "confirming_initial_state",
            },
            {
                "bed": "On bed", "hr": 64, "rr": 14,
                "sleep": "wake", "sleep_score_eligible": True,
            },
            {
                "bed": "On bed", "hr": 63, "rr": 14,
                "sleep": "wake", "sleep_held_previous_state": True,
                "sleep_provisional": True,
                "sleep_score_eligible": False,
                "sleep_data_status": "provisional_hold",
            },
            {
                "bed": "On bed", "hr": 63, "rr": 14,
                "sleep": "wake", "sleep_held_previous_state": True,
                "sleep_provisional": True,
                "sleep_score_eligible": False,
                "sleep_data_status": "provisional_hold",
            },
            {
                "bed": "On bed", "hr": 62, "rr": 13,
                "sleep": "wake", "sleep_held_previous_state": True,
                "sleep_provisional": False,
                "sleep_score_eligible": True,
                "sleep_data_status": "continuity_hold",
            },
            {
                "bed": "On bed", "hr": None, "rr": None,
                "sleep": None,
                "sleep_data_status": "missing_vitals",
            },
            {
                "bed": "Get out of bed", "hr": None, "rr": None,
                "sleep": None,
                "sleep_data_status": "confirmed_off_bed",
            },
            {
                "bed": "On bed", "hr": None, "rr": None,
                "sleep": None,
                "sleep_data_status": "service_restart_hold",
            },
        ]
        report = build_session_report(
            240,
            rows,
            {"estimated_sleep_s": 0},
            {"wake": 4},
            self._quality(),
            sample_interval_s=30,
            sleep_score_state_counts={"wake": 2},
        )

        sleep = report["sleep"]
        accounting = sleep["classification_accounting"]
        self.assertEqual(sleep["direct_confirmed_s"], 30)
        self.assertEqual(sleep["continuity_carried_forward_s"], 90)
        self.assertEqual(sleep["provisional_hold_s"], 60)
        self.assertEqual(sleep["actual_scored_s"], 60)
        self.assertEqual(sleep["excluded_from_score_s"], 180)
        self.assertEqual(sleep["initial_wait_s"], 30)
        self.assertEqual(sleep["no_data_s"], 30)
        self.assertEqual(sleep["off_bed_s"], 30)
        self.assertEqual(sleep["restart_display_hold_s"], 30)
        self.assertEqual(sleep["sensor_gap_s"], 0)
        self.assertTrue(accounting["arithmetic_invariant"]["holds"])
        self.assertTrue(accounting["display_stage_total_reconciles"])
        self.assertTrue(accounting["score_stage_total_reconciles"])
        self.assertEqual(
            accounting["challenger_time_before_confirmation_s"],
            0,
        )

    def test_report_accounts_for_partial_tail_as_sensor_gap(self):
        rows = [
            {"bed": "On bed", "hr": 62, "rr": 13, "sleep": "n2"},
            {"bed": "On bed", "hr": 61, "rr": 13, "sleep": "n2"},
        ]
        report = build_session_report(
            65,
            rows,
            {"estimated_sleep_s": 60},
            {"n2": 2},
            self._quality(),
            sample_interval_s=30,
        )

        accounting = report["sleep"]["classification_accounting"]
        self.assertEqual(accounting["direct_confirmed_s"], 60)
        self.assertEqual(accounting["sensor_gap_s"], 5)
        self.assertEqual(accounting["accounted_s"], 65)
        self.assertTrue(accounting["arithmetic_invariant"]["holds"])

    def test_report_waso_and_coverage_use_duration_aware_occupied_state(self):
        rows = [
            {
                "bed": "On bed", "hr": 62, "rr": 13,
                "sleep": "n2", "sample_interval_s": 10,
            },
            {
                "bed": "On bed", "hr": 65, "rr": 14,
                "sleep": "wake", "sample_interval_s": 20,
            },
            {
                # A stale Stage label cannot turn confirmed OFF BED into
                # attributed or physiological time, but the interruption is
                # still part of post-onset WASO.
                "bed": "Get out of bed", "hr": 65, "rr": 14,
                "sleep": "wake", "sample_interval_s": 30,
                "sleep_data_status": "confirmed_off_bed",
            },
            {
                "bed": "On bed", "hr": 61, "rr": 13,
                "sleep": "n2", "sample_interval_s": 10,
            },
        ]
        report = build_session_report(
            70,
            rows,
            {
                "estimated_sleep_s": 20,
                "sleep_onset_proxy_s": 0,
                "awakenings": 1,
                "waso_proxy_s": 50,
            },
            {"wake": 2, "n2": 2},
            self._quality(),
            sample_interval_s=10,
            sleep_score_state_counts={"wake": 2, "n2": 2},
        )

        self.assertEqual(report["sleep"]["waso_proxy_s"], 50)
        self.assertEqual(report["sleep"]["score_waso_proxy_s"], 50)
        self.assertEqual(
            report["data_quality"]["coverage"]["state_attribution_pct"],
            57,
        )
        self.assertEqual(
            report["data_quality"]["coverage"][
                "physiological_evidence_pct"
            ],
            57,
        )

    def test_explicit_unscored_row_is_not_inferred_as_scoreable_carry(self):
        exclusion_variants = (
            {"sleep_score_eligible": False},
            {"sleep_excluded_from_score": True},
        )
        for exclusion in exclusion_variants:
            with self.subTest(exclusion=exclusion):
                rows = [
                    {
                        "bed": "On bed", "hr": 62, "rr": 13,
                        "sleep": "n2", "sleep_score_eligible": True,
                    },
                    {
                        "bed": "On bed", "hr": 61, "rr": 13,
                        "sleep": None,
                        "sleep_data_status": (
                            "insufficient_paired_vital_coverage"
                        ),
                        **exclusion,
                    },
                ]
                report = build_session_report(
                    60,
                    rows,
                    {"estimated_sleep_s": 30},
                    {"n2": 1},
                    self._quality(),
                    sample_interval_s=30,
                    sleep_score_state_counts={"n2": 1},
                )

                accounting = report["sleep"]["classification_accounting"]
                self.assertEqual(accounting["direct_confirmed_s"], 30)
                self.assertEqual(
                    accounting["continuity_carried_forward_s"], 0
                )
                self.assertEqual(accounting["no_data_s"], 30)
                self.assertEqual(accounting["score_eligible_s"], 30)
                self.assertEqual(accounting["excluded_from_score_s"], 30)
                self.assertTrue(accounting["arithmetic_invariant"]["holds"])
                self.assertTrue(accounting["display_stage_total_reconciles"])
                self.assertTrue(accounting["score_stage_total_reconciles"])

    def test_excluded_alias_keeps_held_stage_display_only(self):
        rows = [
            {
                "bed": "On bed", "hr": 62, "rr": 13,
                "sleep": "n2", "sleep_score_eligible": True,
            },
            {
                "bed": "On bed", "hr": 61, "rr": 13,
                "sleep": "n2", "sleep_held_previous_state": True,
                "sleep_data_status": "continuity_hold",
                "sleep_excluded_from_score": True,
            },
        ]
        report = build_session_report(
            60,
            rows,
            {"estimated_sleep_s": 30},
            {"n2": 2},
            self._quality(),
            sample_interval_s=30,
            sleep_score_state_counts={"n2": 1},
        )

        accounting = report["sleep"]["classification_accounting"]
        self.assertEqual(accounting["direct_confirmed_s"], 30)
        self.assertEqual(accounting["continuity_carried_forward_s"], 30)
        self.assertEqual(accounting["score_eligible_s"], 30)
        self.assertEqual(accounting["excluded_from_score_s"], 30)
        self.assertTrue(accounting["display_stage_total_reconciles"])
        self.assertTrue(accounting["score_stage_total_reconciles"])

    def test_sleep_quality_uses_score_eligible_counts(self):
        sequence = [
            {"state": "wake", "score_eligible": True},
            {"state": "wake", "provisional": True},
            {"state": "n2", "score_eligible": True},
            {"state": "n2", "provisional": True},
        ]
        quality = build_sleep_quality(
            120,
            {"sleep_onset_proxy_s": 60},
            {"wake": 2, "n2": 2},
            rest_mode="overnight",
            stage_sequence=sequence,
            sample_interval_s=30,
            score_state_counts={"wake": 1, "n2": 1},
        )

        self.assertEqual(quality["actual_scored_s"], 60)
        self.assertEqual(quality["estimated_sleep_s"], 30)

    def test_scoreable_provisional_state_remains_in_cycle_sequence(self):
        sequence = [
            {
                "state": "n2",
                "provisional": True,
                "score_eligible": True,
                "sample_interval_s": 30,
            }
            for _ in range(90)
        ]
        sequence.append({
            "state": "rem",
            "provisional": True,
            "score_eligible": True,
            "sample_interval_s": 30,
        })
        quality = build_sleep_quality(
            91 * 30,
            {"sleep_onset_proxy_s": 0},
            {"n2": 90, "rem": 1},
            rest_mode="overnight",
            stage_sequence=sequence,
            sensor_samples=[
                {"hr": 60, "rr": 14, "sample_interval_s": 30}
                for _ in range(91)
            ],
            sample_interval_s=30,
        )

        self.assertEqual(
            quality["cycles"]["completed_nrem_rem_cycles"],
            1,
        )

    def test_explicit_exclusion_still_removes_provisional_sequence_state(self):
        sequence = [
            {
                "state": "n2",
                "provisional": True,
                "score_eligible": False,
                "sample_interval_s": 30,
            }
            for _ in range(90)
        ]
        sequence.append({
            "state": "rem",
            "score_eligible": True,
            "sample_interval_s": 30,
        })
        quality = build_sleep_quality(
            91 * 30,
            {"sleep_onset_proxy_s": 0},
            {"rem": 1},
            rest_mode="overnight",
            stage_sequence=sequence,
            sensor_samples=[
                {"hr": 60, "rr": 14, "sample_interval_s": 30}
                for _ in range(91)
            ],
            sample_interval_s=30,
        )

        self.assertEqual(
            quality["cycles"]["completed_nrem_rem_cycles"],
            0,
        )

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
        self.assertEqual(report["environment_assessment"]["required_count"], 6)
        self.assertEqual(report["environment_assessment"]["advisory_count"], 1)
        self.assertFalse(report["environment_assessment"]["meets_expected"])
        self.assertEqual(report["data_quality"]["coverage"]["environment_pct"], 0)

    def test_missing_optional_sound_is_advisory_not_environment_failure(self):
        sample = {
            "bed": "On bed", "hr": 60, "rr": 13, "sleep": "n2",
            "temp": 24.0, "hum": 50.0, "co2": 700.0, "lux": 1.0,
            "pm2_5": 8.0, "voc": 100.0,
        }
        report = build_session_report(
            5,
            [sample],
            {"estimated_sleep_s": 5},
            {"n2": 1},
            self._quality(),
            rest_mode="sleep",
        )

        sound = next(
            item for item in report["findings"] if item["key"] == "sound"
        )
        assessment = report["environment_assessment"]
        self.assertEqual(sound["severity"], "unavailable")
        self.assertEqual(sound["decision"], "advisory")
        self.assertFalse(sound["blocks_overall"])
        self.assertTrue(assessment["meets_expected"])
        self.assertEqual(assessment["overall_level"], "excellent")
        self.assertEqual(assessment["required_count"], 0)
        self.assertEqual(assessment["advisory_count"], 1)
        self.assertEqual(assessment["optional_unavailable_count"], 1)
        self.assertEqual(assessment["assessment_quality"], "degraded_optional")

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
            rest_mode="nap_recovery",
            sensor_samples=samples,
            target_duration_s=30 * 60,
        )
        self.assertEqual(quality["rest_mode"]["resolved"], "short_nap")
        self.assertEqual(quality["score_title"], "Recovery Score")
        self.assertTrue(quality["sleep_detected"])
        self.assertGreaterEqual(quality["score"], 70)
        self.assertEqual(quality["component_max_points"], {
            "goal_duration": 25.0,
            "physiological_response": 35.0,
            "rest_continuity": 30.0,
            "environment_support": 10.0,
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

    def test_overnight_low_coverage_keeps_score_with_confidence(self):
        samples = [{"hr": 58.0, "rr": 13.0} for _ in range(400)]
        quality = build_sleep_quality(
            3600,
            {"sleep_onset_proxy_s": 600},
            {"n2": 400},
            rest_mode="overnight",
            sensor_samples=samples,
        )

        self.assertTrue(quality["available"])
        self.assertIsInstance(quality["score"], int)
        self.assertEqual(quality["score_confidence"]["level"], "medium")
        self.assertFalse(
            quality["release_requirements"][
                "confirmed_stage_coverage_blocks_score"
            ]
        )

    def test_continuity_attribution_does_not_inflate_evidence_coverage(self):
        measured = [{
            "hr": 58.0,
            "rr": 13.0,
            "_source_rows": 2,
            "_paired_hr_rr_rows": 2,
            "sample_interval_s": 5.0,
            "bcg_analysis_valid": True,
        } for _ in range(3)]
        projected_gaps = [{
            "hr": None,
            "rr": None,
            "synthetic_sleep_gap": True,
            "sample_interval_s": 5.0,
            "bcg_analysis_valid": False,
        } for _ in range(9)]

        quality = build_sleep_quality(
            60.0,
            {"sleep_onset_proxy_s": 0.0},
            {"n2": 12},
            rest_mode="overnight",
            sensor_samples=measured + projected_gaps,
            sample_interval_s=5.0,
        )

        coverage = quality["data_coverage"]
        self.assertTrue(quality["available"])
        self.assertEqual(coverage["state_attribution_pct"], 100.0)
        self.assertEqual(coverage["physiological_evidence_pct"], 25.0)
        self.assertEqual(coverage["paired_hr_rr_pct"], 40.0)
        self.assertEqual(coverage["points"], 1.2)
        self.assertEqual(quality["score_confidence"]["level"], "low")
        self.assertEqual(
            quality["score_confidence"][
                "physiological_evidence_coverage_pct"
            ],
            25.0,
        )

    def test_explicit_invalid_bcg_does_not_count_as_physiological_evidence(self):
        samples = [{
            "hr": 58.0,
            "rr": 13.0,
            "bcg_analysis_valid": False,
        } for _ in range(6)]
        quality = build_sleep_quality(
            30.0,
            {"sleep_onset_proxy_s": 0.0},
            {"n2": 6},
            rest_mode="overnight",
            sensor_samples=samples,
            sample_interval_s=5.0,
        )

        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        self.assertEqual(
            quality["release_requirements"]["paired_hr_rr_rows"],
            0,
        )
        self.assertEqual(
            quality["release_requirements"]["paired_hr_rr_coverage_pct"],
            0.0,
        )
        self.assertEqual(quality["data_coverage"]["state_attribution_pct"], 100.0)
        self.assertEqual(
            quality["data_coverage"]["physiological_evidence_pct"],
            0.0,
        )
        self.assertEqual(quality["component_points"]["data_coverage"], 0.0)
        self.assertEqual(quality["score_confidence"]["level"], "low")

    def test_stale_or_off_bed_vitals_cannot_release_sleep_score(self):
        invalid_markers = (
            {"heart_rate_held": True},
            {"respiration_held": True},
            {"heart_rate_current_valid": False},
            {"respiration_current_valid": False},
            {"sleep_data_status": "confirmed_off_bed"},
        )
        for marker in invalid_markers:
            with self.subTest(marker=marker):
                samples = [
                    {"hr": 58.0, "rr": 13.0, **marker}
                    for _ in range(6)
                ]
                quality = build_sleep_quality(
                    30.0,
                    {"sleep_onset_proxy_s": 0.0},
                    {"n2": 6},
                    rest_mode="overnight",
                    sensor_samples=samples,
                    sample_interval_s=5.0,
                )

                self.assertFalse(quality["available"])
                self.assertIsNone(quality["score"])
                self.assertEqual(
                    quality["release_requirements"]["paired_hr_rr_rows"],
                    0,
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
            for _ in range(20)
        ]
        quality = build_sleep_quality(
            600, {"estimated_sleep_s": 0}, {}, completed=True,
            rest_mode="nap_recovery", sensor_samples=samples,
            sample_interval_s=30,
        )
        self.assertTrue(quality["available"])
        self.assertIsInstance(quality["score"], int)
        self.assertEqual(quality["score_confidence"]["level"], "medium")
        self.assertEqual(
            quality["physiology"]["paired_hr_rr_coverage_pct"], 66.7,
        )
        self.assertEqual(quality["physiology"]["source_sensor_samples"], 60)

    def test_recovery_low_session_coverage_keeps_score_with_confidence(self):
        samples = [{
            "hr": 65.0,
            "rr": 14.0,
            "bed": "On bed",
            "temp": 24.0,
            "hum": 50.0,
            "co2": 750.0,
            "dba": 35.0,
            "lux": 2.0,
        } for _ in range(180)]
        quality = build_sleep_quality(
            30 * 60,
            {},
            {"wake": 180},
            rest_mode="nap_recovery",
            sensor_samples=samples,
        )

        self.assertTrue(quality["available"])
        self.assertIsInstance(quality["score"], int)
        self.assertEqual(quality["score_confidence"]["level"], "medium")
        self.assertFalse(
            quality["release_requirements"][
                "session_coverage_blocks_score"
            ]
        )

    def test_recovery_timing_guardrails_follow_persisted_target(self):
        def quality(minutes, target_minutes):
            sample_count = max(6, int(minutes * 2))
            samples = [{
                "hr": 65.0,
                "rr": 14.0,
                "bed": "On bed",
                "temp": 24.0,
                "hum": 50.0,
                "co2": 750.0,
                "dba": 35.0,
                "lux": 2.0,
                "pm2_5": 8.0,
                "voc": 100.0,
            } for _ in range(sample_count)]
            return build_sleep_quality(
                minutes * 60,
                {},
                {"wake": sample_count},
                rest_mode="nap_recovery",
                sensor_samples=samples,
                sample_interval_s=30,
                target_duration_s=target_minutes * 60,
            )

        cases = (
            (9, 30, "insufficient", False),
            (10, 30, "partial", True),
            (25, 30, "recommended", True),
            (35, 30, "recommended", True),
            (36, 30, "extended", True),
            (45, 30, "extended", True),
            (46, 30, "out_of_protocol", False),
            (90, 90, "recommended", True),
            (110, 90, "extended", True),
            (121, 90, "implausible_outlier", False),
        )
        for minutes, target, status, available in cases:
            with self.subTest(minutes=minutes, target=target):
                result = quality(minutes, target)
                self.assertEqual(
                    result["rest_mode"]["protocol_status"]["status"],
                    status,
                )
                self.assertEqual(result["available"], available)
                self.assertEqual(result["score"] is not None, available)

    def test_legacy_recovery_target_is_not_inferred_from_elapsed_time(self):
        samples = [{
            "hr": 65.0,
            "rr": 14.0,
            "bed": "On bed",
        } for _ in range(120)]
        quality = build_sleep_quality(
            60 * 60,
            {},
            {"wake": 120},
            rest_mode="nap_recovery",
            sensor_samples=samples,
            sample_interval_s=30,
            target_duration_s=None,
        )

        timing = quality["rest_mode"]["protocol_status"]
        self.assertFalse(quality["available"])
        self.assertEqual(timing["status"], "target_unknown")
        self.assertEqual(timing["display_status"], "TARGET_UNKNOWN/extended")
        self.assertTrue(timing["review_required"])

    def test_recovery_v2_keeps_coverage_out_of_health_score(self):
        samples = [{
            "hr": 65.0,
            "rr": 14.0,
            "bed": "On bed",
        } for _ in range(60)]
        quality = build_sleep_quality(
            30 * 60,
            {},
            {"wake": 60},
            rest_mode="nap_recovery",
            sensor_samples=samples,
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )

        self.assertTrue(quality["available"])
        self.assertEqual(sum(quality["component_max_points"].values()), 100)
        self.assertNotIn("data_coverage", quality["component_points"])
        self.assertFalse(quality["data_coverage"]["score_component"])
        self.assertEqual(quality["environment_support"]["coverage_pct"], 0.0)
        self.assertEqual(quality["scored_max_points"], 90.0)

    def test_transient_sound_spike_does_not_label_whole_session_critical(self):
        base = {
            "bed": "On bed",
            "hr": 62.0,
            "rr": 14.0,
            "temp": 24.0,
            "hum": 50.0,
            "co2": 750.0,
            "lux": 1.0,
            "pm2_5": 8.0,
            "voc": 100.0,
            "sleep": "wake",
        }
        samples = [{**base, "dba": 38.0} for _ in range(239)]
        samples.append({**base, "dba": 80.0})
        quality = build_sleep_quality(
            20 * 60,
            {},
            {"wake": 240},
            rest_mode="nap_recovery",
            sensor_samples=samples,
            target_duration_s=30 * 60,
        )
        report = build_session_report(
            20 * 60,
            samples,
            {},
            {"wake": 240},
            quality,
            rest_mode="nap_recovery",
            target_duration_s=30 * 60,
        )

        sound_metric = next(
            item for item in report["environment"] if item["key"] == "sound"
        )
        sound_finding = next(
            item for item in report["findings"] if item["key"] == "sound"
        )
        score_metric = next(
            item
            for item in quality["environment_support"]["metrics"]
            if item["key"] == "sound"
        )
        self.assertAlmostEqual(sound_metric["average"], 38.2, places=1)
        self.assertEqual(sound_metric["maximum"], 80.0)
        self.assertEqual(
            sound_metric["level_distribution_pct"]["critical"], 0
        )
        self.assertEqual(sound_metric["status_key"], "excellent")
        self.assertEqual(sound_finding["severity"], "excellent")
        self.assertTrue(sound_finding["transient_critical_observed"])
        self.assertEqual(score_metric["status_key"], "excellent")

    def test_transient_co2_safety_excursion_is_explicit_and_not_rescored(self):
        base = {
            "bed": "On bed", "hr": 62.0, "rr": 14.0,
            "temp": 24.0, "hum": 50.0, "co2": 750.0,
            "lux": 1.0, "dba": 38.0, "pm2_5": 8.0,
            "voc": 100.0, "sleep": "wake",
        }
        normal_samples = [dict(base) for _ in range(240)]
        excursion_samples = [dict(base) for _ in range(239)]
        excursion_samples.append({**base, "co2": 1300.0})
        normal_quality = build_sleep_quality(
            20 * 60,
            {},
            {"wake": 240},
            rest_mode="nap_recovery",
            sensor_samples=normal_samples,
            target_duration_s=30 * 60,
        )
        excursion_quality = build_sleep_quality(
            20 * 60,
            {},
            {"wake": 240},
            rest_mode="nap_recovery",
            sensor_samples=excursion_samples,
            target_duration_s=30 * 60,
        )
        report = build_session_report(
            20 * 60,
            excursion_samples,
            {},
            {"wake": 240},
            excursion_quality,
            rest_mode="nap_recovery",
            target_duration_s=30 * 60,
        )

        co2_metric = next(
            item for item in report["environment"] if item["key"] == "co2"
        )
        safety_finding = next(
            item
            for item in report["findings"]
            if item["key"] == "co2_safety_excursion"
        )
        assessment = report["environment_assessment"]
        self.assertEqual(normal_quality["score"], excursion_quality["score"])
        self.assertEqual(co2_metric["status_key"], "excellent")
        self.assertTrue(co2_metric["safety_excursion_observed"])
        self.assertEqual(co2_metric["safety_excursion_sample_count"], 1)
        self.assertEqual(safety_finding["decision"], "safety_review")
        self.assertEqual(safety_finding["threshold"], 1300.0)
        self.assertIn("ระบบ Safety", safety_finding["action"])
        self.assertTrue(assessment["meets_expected"])
        self.assertEqual(assessment["overall_level"], "excellent")
        self.assertEqual(assessment["required_count"], 0)
        self.assertTrue(assessment["safety_excursion_observed"])
        self.assertTrue(assessment["safety_review_required"])
        self.assertEqual(assessment["safety_excursion_count"], 1)
        self.assertFalse(assessment["safety_excursions_change_score"])
        self.assertIn("Timeline", report["post_session_guidance"]["next_session"])

    def test_two_mode_protocol_windows_are_reported(self):
        samples = [{
            "hr": 66.0, "rr": 14.0, "bed": "On bed", "temp": 24.0,
            "hum": 50.0, "co2": 750.0, "dba": 35.0, "lux": 2.0,
        } for _ in range(360)]
        over_limit = build_sleep_quality(
            46 * 60, {}, {"wake": 360}, rest_mode="nap_recovery",
            sensor_samples=samples,
        )
        self.assertEqual(
            over_limit["rest_mode"]["protocol_status"]["status"],
            "out_of_protocol",
        )
        self.assertFalse(over_limit["available"])
        self.assertTrue(
            over_limit["rest_mode"]["protocol_status"]["review_required"]
        )
        nap = build_sleep_quality(
            20 * 60, {}, {"wake": 240}, rest_mode="nap_recovery",
            sensor_samples=samples[:300],
        )
        self.assertEqual(
            nap["rest_mode"]["protocol_status"]["status"], "partial"
        )

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
        self.assertEqual(nap["duration_target"]["target_minutes"], 30.0)
        self.assertEqual(
            nap["duration_target"]["recommended_range_minutes"], [25, 35],
        )
        self.assertEqual(nap["rest_mode"]["protocol_status"]["status"], "recommended")

    def test_nap_duration_uses_occupied_rest_time_against_thirty_minute_goal(self):
        on_bed = {
            "hr": 65.0, "rr": 14.0, "bed": "On bed", "temp": 24.0,
            "hum": 50.0, "co2": 750.0, "dba": 35.0, "lux": 2.0,
        }
        off_bed = {
            **on_bed, "hr": None, "rr": None, "bed": "Get out of bed",
        }
        quality = build_sleep_quality(
            30 * 60, {}, {"wake": 360}, rest_mode="nap_recovery",
            sensor_samples=[dict(on_bed) for _ in range(180)]
            + [dict(off_bed) for _ in range(180)],
        )

        self.assertEqual(quality["component_points"]["goal_duration"], 12.5)
        self.assertEqual(quality["duration_target"]["eligible_rest_minutes"], 15.0)
        self.assertEqual(quality["duration_target"]["completion_pct"], 50.0)

    def test_nap_duration_counts_continuity_but_not_confirmed_off_bed(self):
        direct = {
            "hr": 65.0,
            "rr": 14.0,
            "bed": "On bed",
            "sleep": "wake",
            "sleep_score_eligible": True,
        }
        continuity = {
            "hr": None,
            "rr": None,
            "bed": None,
            "sleep": "wake",
            "sleep_score_eligible": True,
            "sleep_data_status": "continuity_hold",
            "synthetic_sleep_gap": True,
        }
        transient_exit = {
            **continuity,
            "bed": "Get out of bed",
            "bed_exit_evidence": {"confirmed": False},
        }
        confirmed_exit = {
            **continuity,
            "sleep_data_status": "confirmed_off_bed",
            "bed_exit_evidence": {"confirmed": True},
        }
        samples = (
            [dict(direct) for _ in range(20)]
            + [dict(continuity) for _ in range(20)]
            + [dict(transient_exit) for _ in range(10)]
            + [dict(confirmed_exit) for _ in range(10)]
        )

        quality = build_sleep_quality(
            30 * 60,
            {},
            {"wake": 50},
            rest_mode="nap_recovery",
            sensor_samples=samples,
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )

        self.assertEqual(
            quality["duration_target"]["eligible_rest_minutes"],
            25.0,
        )
        self.assertEqual(
            quality["duration_target"]["completion_pct"],
            83.3,
        )

    def test_recovery_requires_ten_minutes_of_eligible_rest_not_wall_time(self):
        present = {
            "hr": 65.0,
            "rr": 14.0,
            "bed": "On bed",
            "sleep": "wake",
            "sample_interval_s": 30,
        }
        off_bed = {
            **present,
            "sleep": None,
            "sleep_data_status": "confirmed_off_bed",
            "bed_exit_evidence": {"confirmed": True},
        }
        quality = build_sleep_quality(
            10 * 60,
            {},
            {"wake": 10},
            rest_mode="nap_recovery",
            sensor_samples=(
                [dict(present) for _ in range(10)]
                + [dict(off_bed) for _ in range(10)]
            ),
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )

        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        self.assertEqual(
            quality["duration_target"]["eligible_rest_minutes"],
            5.0,
        )
        self.assertFalse(
            quality["release_requirements"][
                "eligible_duration_releasable"
            ]
        )
        self.assertIn("ยังไม่ถึง 10 นาที", quality["reason"])

    def test_recovery_scopes_off_bed_vitals_and_environment_out_of_score(self):
        present = [{
            "hr": 65.0 + (0.1 if index % 2 else -0.1),
            "rr": 14.0,
            "bed": "On bed",
            "sleep": "wake",
            "temp": 24.0,
            "hum": 50.0,
            "co2": 750.0,
            "dba": 35.0,
            "lux": 2.0,
            "pm2_5": 8.0,
            "voc": 100.0,
            "sample_interval_s": 30,
        } for index in range(20)]
        absent = [{
            **present[0],
            "sleep": None,
            "sleep_data_status": "confirmed_off_bed",
            "bed_exit_evidence": {"confirmed": True},
            "hr": 190.0,
            "rr": 50.0,
            "temp": 40.0,
            "hum": 95.0,
            "co2": 5000.0,
            "dba": 100.0,
            "lux": 5000.0,
            "pm2_5": 500.0,
            "voc": 500.0,
        } for _ in range(20)]
        common = {
            "duration_s": 20 * 60,
            "night_summary": {},
            "sleep_state_counts": {"wake": 20},
            "rest_mode": "nap_recovery",
            "sample_interval_s": 30,
            "target_duration_s": 30 * 60,
        }
        baseline = build_sleep_quality(
            sensor_samples=present,
            **common,
        )
        with_absence = build_sleep_quality(
            sensor_samples=present + absent,
            **common,
        )
        report = build_session_report(
            common["duration_s"],
            present + absent,
            common["night_summary"],
            common["sleep_state_counts"],
            with_absence,
            rest_mode=common["rest_mode"],
            sample_interval_s=common["sample_interval_s"],
            target_duration_s=common["target_duration_s"],
        )

        self.assertTrue(with_absence["available"])
        self.assertEqual(
            with_absence["component_points"]["physiological_response"],
            baseline["component_points"]["physiological_response"],
        )
        self.assertEqual(
            with_absence["component_points"]["environment_support"],
            baseline["component_points"]["environment_support"],
        )
        self.assertLess(with_absence["score"], baseline["score"])
        self.assertEqual(
            with_absence["physiology"]["heart_rate_average"],
            baseline["physiology"]["heart_rate_average"],
        )
        self.assertEqual(
            with_absence["environment_support"]["quality_factor"],
            baseline["environment_support"]["quality_factor"],
        )
        self.assertEqual(
            with_absence["body_response"]["bed_exit_events"],
            1,
        )
        co2_qa = next(
            item for item in report["environment"]
            if item["key"] == "co2"
        )
        co2_finding = next(
            item for item in report["findings"]
            if item["key"] == "co2"
        )
        self.assertGreater(co2_qa["average"], 750.0)
        self.assertFalse(co2_finding["contributes_to_primary_score"])
        self.assertTrue(report["environment_assessment"]["context_only"])
        positive_keys = {
            item["key"]
            for item in report["restore_summary"]["drivers"]["positive"]
        }
        self.assertIn("environment_support", positive_keys)

    def test_raw_exit_label_does_not_create_recovery_exit_or_gap(self):
        samples = [{
            "hr": 65.0,
            "rr": 14.0,
            "bed": "Get out of bed" if index == 10 else "On bed",
            "bed_exit_evidence": {"confirmed": False},
            "sleep": "wake",
            "sample_interval_s": 30,
        } for index in range(20)]
        quality = build_sleep_quality(
            10 * 60,
            {},
            {"wake": 20},
            rest_mode="nap_recovery",
            sensor_samples=samples,
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )

        self.assertTrue(quality["available"])
        self.assertEqual(
            quality["duration_target"]["eligible_rest_minutes"],
            10.0,
        )
        self.assertEqual(quality["body_response"]["bed_exit_events"], 0)
        self.assertEqual(
            quality["body_response"]["transient_bed_exit_samples"],
            1,
        )

    def test_recovery_gap_carries_duration_but_not_body_evidence(self):
        measured = [{
            "hr": 65.0,
            "rr": 14.0,
            "bed": "On bed",
            "sleep": "wake",
            "sample_interval_s": 30,
        } for _ in range(20)]
        carried_gap = [{
            "hr": 65.0,
            "rr": 14.0,
            "bed": "Moving",
            "sleep": "wake",
            "synthetic_sleep_gap": True,
            "sample_interval_s": 30,
        } for _ in range(20)]
        quality = build_sleep_quality(
            20 * 60,
            {},
            {"wake": 40},
            rest_mode="nap_recovery",
            sensor_samples=measured + carried_gap,
            sample_interval_s=30,
            target_duration_s=30 * 60,
        )

        self.assertTrue(quality["available"])
        self.assertEqual(
            quality["duration_target"]["eligible_rest_minutes"],
            20.0,
        )
        self.assertEqual(quality["body_response"]["movement_pct"], 0.0)
        self.assertEqual(
            quality["component_points"]["rest_continuity"],
            30.0,
        )

    def test_nap_duration_reaches_full_credit_without_over_target_penalty(self):
        samples = [{
            "hr": 65.0, "rr": 14.0, "bed": "On bed", "temp": 24.0,
            "hum": 50.0, "co2": 750.0, "dba": 35.0, "lux": 2.0,
        } for _ in range(540)]
        quality = build_sleep_quality(
            45 * 60, {}, {"wake": 540}, rest_mode="nap_recovery",
            sensor_samples=samples,
        )

        self.assertEqual(quality["component_points"]["goal_duration"], 25.0)
        self.assertEqual(quality["duration_target"]["eligible_rest_minutes"], 45.0)
        self.assertEqual(quality["duration_target"]["completion_pct"], 100.0)

    def test_smart_mode_does_not_infer_goal_from_duration_or_sleep_state(self):
        short = build_sleep_quality(30 * 60, {}, {"n2": 360}, rest_mode="auto")
        cycle = build_sleep_quality(2 * 3600, {}, {"n2": 1440}, rest_mode="auto")
        main = build_sleep_quality(5 * 3600, {}, {"n2": 3600}, rest_mode="auto")
        for quality in (short, cycle, main):
            self.assertEqual(
                quality["rest_mode"]["resolved"], "unknown_legacy"
            )
            self.assertIsNone(quality["rest_mode"]["group"])
            self.assertFalse(quality["available"])
            self.assertTrue(quality["review_required"])
            self.assertEqual(
                quality["validation_status"], "legacy_mode_unresolved"
            )
        self.assertEqual(normalise_rest_mode("auto"), "auto")


if __name__ == "__main__":
    unittest.main()
