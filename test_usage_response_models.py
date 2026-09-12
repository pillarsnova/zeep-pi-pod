"""Unit tests for the Usage Session API response schemas."""

from __future__ import annotations

import importlib
import inspect
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from sleep_session_report import build_session_report, build_sleep_quality
from sleep_system_policy import SLEEP_SCORE_FORMULA_VERSION
from zeep_pod.sessions._response_model_base import ContractModel
from zeep_pod.sessions.quality_publication import public_quality_payload
from zeep_pod.sessions.response_models import (
    PublicQuality,
    PublicSessionReport,
    RestoreSummary,
    RestoreSummaryPayload,
    UsageSessionDetail,
    UsageSessionListResponse,
    UsageSessionSummaryResponse,
)
from zeep_pod.sessions.restore_summary import build_restore_summary
from zeep_pod.sessions.usage_response_models import UsageTarget
from zeep_pod.sessions.usage_service import UsageSessionService


def _validate(model, value):
    method = getattr(model, "model_validate", None)
    return method(value) if method else model.parse_obj(value)


def _schema(model):
    method = getattr(model, "model_json_schema", None)
    return method(by_alias=True) if method else model.schema(by_alias=True)


_RESPONSE_MODEL_MODULES = (
    "zeep_pod.sessions.quality_response_models",
    "zeep_pod.sessions.report_response_models",
    "zeep_pod.sessions.restore_response_models",
    "zeep_pod.sessions.usage_nested_response_models",
    "zeep_pod.sessions.usage_response_models",
)


def _required_field_sets() -> dict[str, list[str]]:
    required: dict[str, list[str]] = {}
    for module_name in _RESPONSE_MODEL_MODULES:
        module = importlib.import_module(module_name)
        for name, model in inspect.getmembers(module, inspect.isclass):
            if model.__module__ != module_name or not issubclass(model, ContractModel):
                continue
            required[f"{module_name}:{name}"] = sorted(
                _schema(model).get("required", [])
            )
    return required


def _sleep_quality(*, available: bool = True) -> dict:
    return {
        "available": available,
        "score": 82 if available else None,
        "quality_type": "sleep",
        "level": "ดี",
        "version": "quality-v-test",
        "formula_version": SLEEP_SCORE_FORMULA_VERSION,
        "rest_mode": {"group": "sleep", "requested": "sleep"},
        "component_points": {
            "sleep_opportunity": 17.0,
            "sleep_stability": 24.0,
            "restorative_architecture": 24.0,
            "cycle_expression": 12.0,
        },
        "component_max_points": {
            "sleep_opportunity": 20.0,
            "sleep_stability": 30.0,
            "restorative_architecture": 30.0,
            "cycle_expression": 15.0,
        },
        "score_confidence": {
            "level": "high",
            "label": "หลักฐานสูง",
            "session_coverage_pct": 98.0,
            "timeline_coverage_pct": 98.0,
            "state_attribution_coverage_pct": 98.0,
            "physiological_evidence_coverage_pct": 96.0,
            "paired_hr_rr_coverage_pct": 96.0,
        },
        "data_coverage": {
            "score_component": True,
            "points": 5,
            "max_points": 5,
            "state_attribution_ratio": 0.98,
            "state_attribution_pct": 98.0,
            "physiological_evidence_ratio": 0.96,
            "physiological_evidence_pct": 96.0,
        },
    }


def _stored_session() -> dict:
    quality = _sleep_quality()
    return {
        "session_id": "sleep-001",
        "account_key": "tester@example.test",
        "email": "tester@example.test",
        "display_name": "Tester",
        "started_at_utc": "2026-09-10T18:00:00+00:00",
        "ended_at_utc": "2026-09-11T01:00:00+00:00",
        "duration_s": 25200,
        "end_reason": "completed",
        "sample_count": 2520,
        "rest_mode": "sleep",
        "sleep_quality": quality,
        "session_report": {
            "available": True,
            "version": "report-v-test",
            "headline": "พักผ่อนได้ดี",
            "quality": quality,
            "rest_mode": quality["rest_mode"],
            "findings": [],
            "data_quality": {
                "level": "high",
                "label": "ข้อมูลครบ",
                "coverage": {"recording_pct": 100, "bcg_pct": 95},
            },
        },
        "sleep_policy_versions": {"evidence": "evidence-v-test"},
        "sleep_estimator_versions": {"estimator-v-test": 2520},
    }


class _History:
    def __init__(self):
        self.session = _stored_session()

    def session_by_id(self, session_id, _profiles, *, account_key=None):
        if session_id != self.session["session_id"]:
            return None
        return self.session


class UsageResponseModelTests(unittest.TestCase):
    def setUp(self):
        self.detail = UsageSessionService(_History()).detail_by_id(
            "sleep-001",
            {},
            account_key=None,
        )
        assert self.detail is not None

    def test_real_service_detail_validates_without_losing_contract_fields(self):
        parsed = _validate(UsageSessionDetail, self.detail)

        self.assertEqual(parsed.score.type, "sleep_score")
        self.assertEqual(parsed.restore_summary.source_score.value, 82)
        self.assertEqual(parsed.report.quality.score, 82)

    def test_restore_summary_accepts_available_and_unavailable_payloads(self):
        available = build_restore_summary(_sleep_quality())
        unavailable = build_restore_summary(_sleep_quality(available=False))

        self.assertTrue(_validate(RestoreSummaryPayload, available).available)
        parsed_unavailable = _validate(RestoreSummaryPayload, unavailable)
        self.assertFalse(parsed_unavailable.available)
        self.assertIsNone(parsed_unavailable.source_score.value)

    def test_nap_summary_validates_other_union_branches(self):
        quality = {
            "available": True,
            "score": 74,
            "quality_type": "rest_goal",
            "formula_version": "recovery-v-test",
            "rest_mode": {
                "group": "nap_recovery",
                "requested": "nap_recovery",
            },
            "component_points": {"goal_duration": 20},
            "component_max_points": {"goal_duration": 25},
            "score_confidence": {"level": "medium"},
        }
        payload = build_restore_summary(
            quality,
            findings=[
                {
                    "key": "sound",
                    "severity": "poor",
                    "decision": "optimise",
                    "title": "เสียง",
                    "action": "ลดเสียงรบกวน",
                    "contributes_to_primary_score": True,
                }
            ],
            personal_context={
                "sessions_used": 7,
                "score_median": 72,
                "score_typical_range": [68, 78],
                "scores": [68, 70, 71, 72, 73, 75, 74],
            },
            trend_context={"scores": [68, 70, 71, 72, 73, 75, 74]},
            subjective_outcome={
                "status": "measured",
                "freshness_delta": 2,
                "activity_readiness": 8,
                "source": "session_questionnaire",
            },
        )

        parsed = _validate(RestoreSummaryPayload, payload)
        self.assertEqual(parsed.source_score.type, "recovery_score")
        self.assertTrue(parsed.personal_baseline.comparison.available)
        self.assertTrue(parsed.trend.available)
        self.assertEqual(parsed.subjective_outcome.status, "measured")
        self.assertEqual(parsed.drivers.attention[0].category, "environment")

    def test_restore_summary_rejects_score_availability_contradiction(self):
        payload = build_restore_summary(_sleep_quality())
        payload["available"] = False

        with self.assertRaises(ValidationError):
            _validate(RestoreSummaryPayload, payload)

    def test_restore_summary_rejects_more_than_two_drivers(self):
        payload = build_restore_summary(_sleep_quality())
        payload["drivers"]["positive"] *= 2

        with self.assertRaises(ValidationError):
            _validate(RestoreSummaryPayload, payload)

    def test_restore_summary_rejects_score_outside_declared_status_band(self):
        payload = build_restore_summary(_sleep_quality())
        payload["status"]["min_score"] = 90
        payload["status"]["max_score"] = 100

        with self.assertRaises(ValidationError):
            _validate(RestoreSummaryPayload, payload)

    def test_restore_summary_rejects_wrong_status_key_for_score(self):
        payload = build_restore_summary(_sleep_quality())
        payload["status"].update(
            key="sleep_restore_very_good",
            min_score=70,
            max_score=84,
        )

        with self.assertRaises(ValidationError):
            _validate(RestoreSummaryPayload, payload)

    def test_restore_summary_rejects_cross_mode_personal_baseline(self):
        payload = build_restore_summary(_sleep_quality())
        payload["personal_baseline"]["mode"] = "nap_recovery"

        with self.assertRaises(ValidationError):
            _validate(RestoreSummaryPayload, payload)

    def test_fractional_score_near_next_band_still_validates(self):
        quality = _sleep_quality()
        quality["score"] = 84.5
        payload = build_restore_summary(quality)

        parsed = _validate(RestoreSummaryPayload, payload)

        self.assertEqual(parsed.status.key, "sleep_restore_good")

    def test_adapter_fractional_scores_follow_display_rounding_at_boundaries(self):
        cases = (
            (49.6, "pace_morning"),
            (69.6, "sleep_restore_good"),
            (84.6, "sleep_restore_very_good"),
        )
        for score, expected_status in cases:
            with self.subTest(score=score):
                quality = _sleep_quality()
                quality["score"] = score
                payload = build_restore_summary(quality)
                payload["source_score"]["value"] = score

                parsed = _validate(RestoreSummaryPayload, payload)

                self.assertEqual(parsed.status.key, expected_status)

    def test_api_restore_summary_requires_readiness_boundary_and_provenance(self):
        payload = build_restore_summary(_sleep_quality())

        with self.assertRaises(ValidationError):
            _validate(RestoreSummary, payload)

    def test_legacy_available_score_without_formula_version_remains_readable(self):
        payload = deepcopy(self.detail)
        payload["score"]["formula_version"] = None
        payload["restore_summary"]["source_score"]["formula_version"] = None
        payload["report"]["quality"]["formula_version"] = None

        parsed = _validate(UsageSessionDetail, payload)

        self.assertTrue(parsed.score.available)
        self.assertIsNone(parsed.score.formula_version)

    def test_legacy_detail_without_an_approved_report_remains_readable(self):
        payload = deepcopy(self.detail)
        payload["report"] = {}

        parsed = _validate(UsageSessionDetail, payload)

        self.assertIsNone(parsed.report.rest_mode)

    def test_session_summary_rejects_mode_score_mismatch(self):
        payload = deepcopy(self.detail)
        payload["score"]["type"] = "recovery_score"
        payload["score"]["title"] = "Recovery Score"

        with self.assertRaises(ValidationError):
            _validate(UsageSessionDetail, payload)

    def test_session_summary_rejects_inconsistent_mode_policy(self):
        payload = deepcopy(self.detail)
        payload["mode"]["sleep_required"] = False

        with self.assertRaises(ValidationError):
            _validate(UsageSessionDetail, payload)

    def test_detail_rejects_report_mode_mismatch(self):
        payload = deepcopy(self.detail)
        payload["report"]["rest_mode"]["label"] = "Wrong mode label"

        with self.assertRaises(ValidationError):
            _validate(UsageSessionDetail, payload)

    def test_detail_rejects_each_report_quality_score_mismatch(self):
        mutations = {
            "available": False,
            "score": 81,
            "score_title": "Recovery Score",
            "formula_version": "wrong-formula",
            "validation_status": "wrong-status",
            "clinical_validated": True,
            "level": "ต่างจากคะแนนหลัก",
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                payload = deepcopy(self.detail)
                payload["report"]["quality"][field] = value
                with self.assertRaises(ValidationError):
                    _validate(UsageSessionDetail, payload)

    def test_detail_rejects_report_quality_mode_mismatch(self):
        payload = deepcopy(self.detail)
        payload["report"]["quality"]["rest_mode"]["label"] = "Wrong mode label"

        with self.assertRaises(ValidationError):
            _validate(UsageSessionDetail, payload)

    def test_detail_rejects_report_restore_summary_mismatch(self):
        payload = deepcopy(self.detail)
        payload["report"]["restore_summary"] = deepcopy(payload["restore_summary"])
        payload["report"]["restore_summary"]["personal_baseline"]["maturity"][
            "sessions_used"
        ] = 1

        with self.assertRaises(ValidationError):
            _validate(UsageSessionDetail, payload)

    def test_target_range_is_exactly_two_ordered_values_and_completion_is_bounded(self):
        target = {
            "key": "nap_30m",
            "label": "Nap & Refresh · 30 นาที",
            "seconds": 1800,
            "minutes": 30,
            "recommended_range_minutes": [20, 35],
            "completion_pct": 100,
            "protocol_status": {},
        }
        parsed = _validate(UsageTarget, target)
        self.assertEqual(parsed.recommended_range_minutes, (20, 35))

        for invalid_range in ([20], [35, 20], [-1, 20], [20, 35, 40]):
            with self.subTest(invalid_range=invalid_range):
                payload = deepcopy(target)
                payload["recommended_range_minutes"] = invalid_range
                with self.assertRaises(ValidationError):
                    _validate(UsageTarget, payload)

        target["completion_pct"] = 100.1
        with self.assertRaises(ValidationError):
            _validate(UsageTarget, target)

    def test_full_current_report_validates_through_usage_service(self):
        samples = [
            {
                "bed": "On bed",
                "hr": 60,
                "rr": 14,
                "sleep": "n2",
                "sleep_confidence": "high",
                "temp": 24,
                "hum": 50,
                "co2": 720,
                "lux": 1,
                "dba": 36,
                "pm2_5": 8,
                "voc": 100,
            }
        ]
        quality = _sleep_quality()
        report = build_session_report(
            5,
            samples,
            {"estimated_sleep_s": 5, "awakenings": 0},
            {"n2": 1},
            quality,
            rest_mode="sleep",
            estimator_version="stable-30s-test",
        )
        history = _History()
        history.session["sleep_quality"] = quality
        history.session["session_report"] = report
        detail = UsageSessionService(history).detail_by_id(
            "sleep-001",
            {},
            account_key=None,
        )
        parsed = _validate(UsageSessionDetail, detail)
        accounting = parsed.report.sleep.classification_accounting

        self.assertEqual(parsed.report.stages[2].state, "n2")
        self.assertEqual(
            parsed.report.stages[2].score_eligible_duration_s,
            5,
        )
        self.assertEqual(accounting.score_eligible_s, 5)
        self.assertTrue(accounting.arithmetic_invariant.holds)
        self.assertEqual(parsed.report.environment[0].key, "temperature")
        self.assertEqual(
            parsed.report.data_quality.coverage.state_attribution_pct,
            100,
        )
        self.assertEqual(
            parsed.report.data_quality.coverage.
            physiological_evidence_pct,
            100,
        )
        self.assertEqual(
            parsed.data_quality.coverage.state_attribution_pct,
            100,
        )
        self.assertEqual(
            parsed.data_quality.coverage.physiological_evidence_pct,
            100,
        )
        self.assertEqual(
            parsed.report.quality.score_confidence.
            state_attribution_coverage_pct,
            98,
        )
        self.assertEqual(
            parsed.report.quality.score_confidence.
            physiological_evidence_coverage_pct,
            96,
        )
        self.assertEqual(
            parsed.data_quality.confidence.
            state_attribution_coverage_pct,
            98,
        )
        self.assertEqual(
            parsed.data_quality.confidence.
            physiological_evidence_coverage_pct,
            96,
        )

    def test_current_sleep_and_recovery_quality_shapes_validate(self):
        samples = [
            {
                "hr": 60,
                "rr": 14,
                "bed": "On bed",
                "temp": 24,
                "hum": 50,
                "co2": 720,
                "lux": 1,
                "dba": 36,
                "pm2_5": 8,
                "voc": 100,
            }
            for _ in range(60)
        ]
        cases = (
            build_sleep_quality(
                300,
                {"sleep_onset_proxy_s": 60},
                {"n2": 60},
                rest_mode="sleep",
                sensor_samples=samples,
                stage_sequence=["n2"] * 60,
            ),
            build_sleep_quality(
                1800,
                {},
                {"wake": 60},
                rest_mode="nap_recovery",
                sensor_samples=samples,
            ),
        )

        for quality in cases:
            with self.subTest(quality_type=quality["quality_type"]):
                public = public_quality_payload(quality)
                parsed = _validate(PublicQuality, public)
                self.assertEqual(parsed.quality_type, quality["quality_type"])
                self.assertIsNotNone(parsed.score_confidence)
                self.assertEqual(
                    parsed.data_coverage.physiological_evidence_pct,
                    quality["data_coverage"][
                        "physiological_evidence_pct"
                    ],
                )
                self.assertEqual(
                    parsed.data_coverage.state_attribution_pct,
                    quality["data_coverage"]["state_attribution_pct"],
                )
                self.assertEqual(
                    parsed.score_confidence.
                    physiological_evidence_coverage_pct,
                    quality["score_confidence"][
                        "physiological_evidence_coverage_pct"
                    ],
                )
                self.assertEqual(
                    parsed.score_confidence.state_attribution_coverage_pct,
                    quality["score_confidence"][
                        "state_attribution_coverage_pct"
                    ],
                )

    def test_recovery_v83_nested_quality_shape_remains_readable(self):
        legacy = {
            "available": True,
            "score": 79,
            "quality_type": "rest_goal",
            "duration_target": {
                "seconds": 1800,
                "target_minutes": 30,
                "recommended_range_minutes": [25, 35],
                "eligible_rest_seconds": 1740,
                "eligible_rest_minutes": 29,
                "completion_pct": 96.7,
                "basis": "legacy target",
            },
            "physiology": {
                "available": True,
                "heart_rate_average": 61.2,
                "respiration_average": 14.4,
                "regularity_factor": 0.91,
                "paired_hr_rr_samples": 348,
                "source_sensor_samples": 360,
                "paired_hr_rr_coverage_pct": 96.7,
                "method": "legacy sample regularity",
            },
            "body_response": {
                "available": True,
                "movement_pct": 3.1,
                "bed_exit_events": 0,
                "transient_bed_exit_samples": 1,
            },
            "environment_support": {
                "available": True,
                "averages": {"temp": 23.8, "co2": 760, "dba": 37},
                "fit": {"temp": 1.0, "co2": 0.94, "dba": 0.88},
                "context_only": True,
            },
            "data_coverage": {
                "ratio": 0.97,
                "pct": 97,
                "points": 9.7,
                "max_points": 10,
            },
            "component_points": {
                "goal_duration": 19.3,
                "physiological_response": 27.5,
                "body_stillness": 18.0,
                "environment_support": 17.0,
                "data_coverage": 9.7,
            },
            "component_max_points": {
                "goal_duration": 20,
                "physiological_response": 30,
                "body_stillness": 20,
                "environment_support": 20,
                "data_coverage": 10,
            },
            "component_order": [
                "goal_duration",
                "physiological_response",
                "body_stillness",
                "environment_support",
                "data_coverage",
            ],
            "component_labels": {
                "body_stillness": "ความนิ่งระหว่างพัก",
            },
            "score_confidence": {
                "level": "high",
                "session_coverage_pct": 97,
                "paired_hr_rr_coverage_pct": 96.7,
                "coverage_is_admin_qa_context": True,
                "coverage_can_hide_score": False,
            },
        }

        parsed = _validate(PublicQuality, legacy)

        self.assertEqual(parsed.component_points.body_stillness, 18.0)
        self.assertEqual(parsed.environment_support.fit.dba, 0.88)

    def test_every_quality_section_rejects_undocumented_nested_keys(self):
        cases = {
            "stage_pct_of_sleep": {"n2": 60, "unknown": 1},
            "duration_target": {"seconds": 1800, "raw": [1]},
            "physiology": {"available": True, "hr_series": [60]},
            "body_response": {"movement_pct": 2, "participant": "x"},
            "environment_support": {"available": True, "token": "x"},
            "sleep_opportunity": {"duration_points": 10, "raw": [1]},
            "architecture": {"total": 20, "state_series": ["n2"]},
            "continuity": {"wake_points": 8, "raw_events": [1]},
            "data_coverage": {"pct": 90, "sensor_rows": [1]},
            "cycles": {"available": True, "stage_sequence": ["n2"]},
            "component_points": {"sleep_opportunity": 10, "secret": 1},
            "component_max_points": {"sleep_stability": 30, "secret": 1},
            "component_labels": {"sleep_stability": "ดี", "secret": "x"},
            "score_confidence": {"level": "high", "email": "x"},
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    _validate(PublicQuality, {field: value})

    def test_quality_service_projection_removes_nested_private_values(self):
        history = _History()
        quality = history.session["sleep_quality"]
        quality.update(
            {
                "duration_target": {"seconds": 25200, "raw_samples": [1]},
                "physiology": {
                    "available": True,
                    "heart_rate_average": 58.4,
                    "hr_series": [58.0, 59.0],
                },
                "environment_support": {
                    "available": True,
                    "averages": {"temp": 23.5, "participant_phone": "x"},
                    "metrics": [
                        {
                            "key": "temperature",
                            "average": 23.5,
                            "values": [23.4, 23.6],
                        }
                    ],
                },
                "component_points": {
                    "sleep_opportunity": 17,
                    "private_weight": 99,
                },
            }
        )
        history.session["session_report"]["quality"] = quality

        detail = UsageSessionService(history).detail_by_id(
            "sleep-001",
            {},
            account_key=None,
        )
        parsed = _validate(UsageSessionDetail, detail)
        rendered = json.dumps(detail)

        self.assertEqual(parsed.report.quality.physiology.heart_rate_average, 58.4)
        self.assertEqual(
            parsed.report.quality.environment_support.metrics[0].average,
            23.5,
        )
        for private_value in (
            "raw_samples",
            "hr_series",
            "participant_phone",
            "values",
            "private_weight",
        ):
            self.assertNotIn(private_value, rendered)

    def test_nested_report_sections_reject_undocumented_fields(self):
        cases = {
            "sleep": {"recording_s": 60, "hr_series": [60, 61]},
            "stages": [{"state": "n2", "raw_samples": [1, 2]}],
            "environment": [{"key": "sound", "values": [35, 36]}],
            "environment_assessment": {"overall_level": "good", "email": "x"},
            "findings": [{"key": "sound", "participant_id": "x"}],
            "post_session_guidance": {"primary": "พักต่อ", "token": "x"},
            "data_quality": {"level": "high", "waveform": [1, 2]},
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    _validate(PublicSessionReport, {field: value})

    def test_required_nullable_fields_match_pydantic_v1_and_v2(self):
        current = _required_field_sets()
        code = """
import importlib
import inspect
import json
import sys
import pydantic.v1 as pydantic_v1

sys.modules["pydantic"] = pydantic_v1
from zeep_pod.sessions._response_model_base import ContractModel

modules = (
    "zeep_pod.sessions.quality_response_models",
    "zeep_pod.sessions.report_response_models",
    "zeep_pod.sessions.restore_response_models",
    "zeep_pod.sessions.usage_nested_response_models",
    "zeep_pod.sessions.usage_response_models",
)
required = {}
for module_name in modules:
    module = importlib.import_module(module_name)
    for name, model in inspect.getmembers(module, inspect.isclass):
        if model.__module__ != module_name or not issubclass(model, ContractModel):
            continue
        required[f"{module_name}:{name}"] = sorted(
            model.schema(by_alias=True).get("required", [])
        )
print(json.dumps(required, sort_keys=True))
"""
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=".",
            check=True,
            capture_output=True,
            text=True,
        )
        legacy = json.loads(completed.stdout)

        self.assertEqual(current, legacy)
        summary_key = "zeep_pod.sessions.usage_response_models:UsageSessionSummary"
        for field in (
            "started_at_utc",
            "ended_at_utc",
            "duration_s",
            "end_reason",
            "sample_count",
        ):
            self.assertIn(field, current[summary_key])

    def test_list_and_summary_envelopes_validate(self):
        now = datetime.now(UTC).isoformat()
        envelope = {
            "schema": "zeep.api.response",
            "api_version": "1.0",
            "kind": "usage_session_summary",
            "generated_at": now,
            "request_id": str(uuid4()),
            "data": self.detail,
        }
        envelope["data"] = {
            key: value
            for key, value in self.detail.items()
            if key
            not in {"report", "sleep_policy_versions", "sleep_estimator_versions"}
        }
        parsed = _validate(UsageSessionSummaryResponse, envelope)
        self.assertEqual(parsed.schema_, "zeep.api.response")

        list_envelope = deepcopy(envelope)
        list_envelope["kind"] = "usage_session_list"
        list_envelope["data"] = {
            "contract_version": "zeep.usage-session.v1",
            "history_name": "usage_history",
            "items": [envelope["data"]],
            "summary": {
                "people_count": 1,
                "session_count": 1,
                "sleep_score_count": 1,
                "recovery_score_count": 0,
                "awaiting_score_count": 0,
                "average_sleep_score": 82,
                "average_recovery_score": None,
            },
            "pagination": {
                "limit": 50,
                "offset": 0,
                "returned": 1,
                "total": 1,
                "has_more": False,
            },
            "range": None,
            "history_start_utc": "2026-09-01T00:00:00+00:00",
        }
        self.assertEqual(
            len(_validate(UsageSessionListResponse, list_envelope).data.items),
            1,
        )

    def test_json_schema_uses_public_schema_alias_and_enum_values(self):
        schema = _schema(UsageSessionListResponse)
        rendered = str(schema)

        self.assertIn("schema", schema["properties"])
        self.assertIn("usage_session_list", rendered)
        self.assertIn("sleep_score", rendered)
        self.assertIn("nap_recovery", rendered)


if __name__ == "__main__":
    unittest.main()
