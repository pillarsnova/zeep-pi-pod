from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from sleep_system_policy import (
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
    PERSONAL_REST_WINDOW_BASELINE_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
)
from zeep_pod.sessions.response_models import UsageSessionListResponse
from zeep_pod.sessions.usage_api import USAGE_LIST_EXAMPLE, create_usage_sessions_router
from zeep_pod.sessions.usage_service import UsageSessionService


def _session(session_id: str, email: str, mode: str) -> dict:
    is_nap = mode == "nap_recovery"
    quality = {
        "available": True,
        "score": 78 if is_nap else 82,
        "quality_type": "rest_goal" if is_nap else "sleep",
        "score_title": "Recovery Score" if is_nap else "Sleep Score",
        "formula_version": (
            RECOVERY_SCORE_FORMULA_VERSION if is_nap else SLEEP_SCORE_FORMULA_VERSION
        ),
        "version": "quality-v-test",
        "engineering_shadow_score": 99,
        "score_unrounded": 98.75,
        "release_requirements": {"internal_gate": "must-not-leak"},
        "future_unapproved_field": "must-not-leak",
        "component_points": {
            "goal_duration" if is_nap else "sleep_opportunity": 20,
        },
        "component_max_points": {
            "goal_duration" if is_nap else "sleep_opportunity": 25,
        },
        "score_confidence": {
            "level": "high",
            "session_coverage_pct": 95,
            "paired_hr_rr_coverage_pct": 92,
            "participant_email": "must-not-leak",
            "rr_series": [15.0, 15.2],
        },
        "physiology": {
            "available": True,
            "heart_rate_average": 58.4,
            "respiration_average": 15.2,
            "paired_hr_rr_samples": 220,
            "hr_series": [58.0, 59.0],
            "participant_phone": "must-not-leak",
        },
        "body_response": {
            "movement_pct": 12.5,
        },
        "data_coverage": {
            "pct": 95,
            "score_component": not is_nap,
            "points": 4.8 if not is_nap else None,
            "max_points": 5 if not is_nap else None,
        },
        "rest_mode": {
            "group": mode,
            "requested": mode,
            "label": "Nap & Refresh" if is_nap else "Overnight Recovery",
        },
    }
    if is_nap:
        quality["duration_target"] = {
            "available": True,
            "key": "nap_30m",
            "label": "Nap & Refresh · 30 นาที",
            "seconds": 1800,
            "target_minutes": 30,
            "completion_pct": 100,
            "recommended_range_minutes": [20, 35],
        }
        quality["rest_mode"]["protocol_status"] = {
            "available": True,
            "canonical_mode": "nap_recovery",
            "status": "recommended",
            "score_releasable": True,
        }
    else:
        quality["duration_target"] = {
            "key": "overnight_7h",
            "seconds": 25_200,
            "hours": 7,
        }
    return {
        "session_id": session_id,
        "account_key": email,
        "email": email,
        "display_name": "Tester",
        "started_at_utc": "2026-09-10T18:00:00+00:00",
        "ended_at_utc": "2026-09-11T01:00:00+00:00",
        "duration_s": 25200,
        "sample_count": 2520,
        "rest_mode": mode,
        "target_duration_s": 1_800 if is_nap else 25_200,
        "sleep_quality": quality,
        "sleep_policy_versions": {
            "evidence": "evidence-v-test",
            "participant_email": "must-not-leak",
        },
        "sleep_estimator_versions": {
            "bcg-audio-bed-test": 840,
            "participant_email": 1,
            "not-a-count": "must-not-leak",
        },
        "session_report": {
            "version": "report-v-test",
            "quality": quality,
            "rest_mode": quality["rest_mode"],
            "sleep": {
                "recording_s": 25200,
                "estimated_sleep_s": 23400,
                "actual_scored_s": 22800,
                "direct_confirmed_s": 18000,
                "continuity_carried_forward_s": 5400,
                "initial_wait_s": 60,
                "no_data_s": 300,
                "off_bed_s": 300,
                "restart_display_hold_s": 60,
                "sensor_gap_s": 1080,
                "provisional_hold_s": 600,
                "excluded_from_score_s": 2400,
                "sleep_efficiency_pct": 92.9,
                "classification_accounting": {
                    "version": "classification-accounting-v-test",
                    "method": "row_level_classification_metadata",
                    "direct_confirmed_s": 18000,
                    "continuity_carried_forward_s": 5400,
                    "initial_wait_s": 60,
                    "no_data_s": 300,
                    "off_bed_s": 300,
                    "restart_display_hold_s": 60,
                    "sensor_gap_s": 1080,
                    "provisional_hold_s": 600,
                    "classified_s": 23400,
                    "display_attributed_s": 23400,
                    "score_eligible_s": 22800,
                    "excluded_from_score_s": 2400,
                    "operational_unscored_s": 1800,
                    "accounted_s": 25200,
                    "recording_s": 25200,
                    "display_stage_total_s": 23400,
                    "display_stage_total_delta_s": 0,
                    "display_stage_total_reconciles": True,
                    "score_stage_total_s": 22800,
                    "score_stage_total_delta_s": 0,
                    "score_stage_total_reconciles": True,
                    "restart_display_hold_derived": True,
                    "challenger_time_before_confirmation_s": 0,
                    "legacy_carry_provenance_available": True,
                    "arithmetic_invariant": {
                        "expression": "classification buckets = recording_s",
                        "left_s": 25200,
                        "right_s": 25200,
                        "delta_s": 0,
                        "holds": True,
                        "raw_rows": ["must-not-leak"],
                    },
                    "participant_email": "must-not-leak",
                    "raw_epoch_ids": ["must-not-leak"],
                },
                "hr_series": [58.0, 59.0],
                "participant_phone": "must-not-leak",
            },
            "stages": [
                {
                    "state": "N2",
                    "samples": 400,
                    "duration_s": 12000,
                    "pct_scored": 51.3,
                    "pct_sleep": 55.1,
                    "score_eligible_samples": 380,
                    "score_eligible_duration_s": 11400,
                    "pct_score_eligible": 50.0,
                    "pct_score_eligible_sleep": 53.5,
                    "series": ["N2", "N2"],
                    "score_private_basis": "must-not-leak",
                },
                {
                    "state": "W",
                    "samples": 100,
                    "duration_s": 3000,
                    "pct_scored": 12.8,
                    "pct_sleep": None,
                    "score_eligible_samples": 100,
                    "score_eligible_duration_s": 3000,
                    "pct_score_eligible": 13.2,
                    "pct_score_eligible_sleep": None,
                },
                {
                    "state": "N1",
                    "samples": 60,
                    "duration_s": 1800,
                    "pct_scored": 7.7,
                    "pct_sleep": 8.8,
                    "score_eligible_samples": 60,
                    "score_eligible_duration_s": 1800,
                    "pct_score_eligible": 7.9,
                    "pct_score_eligible_sleep": 9.1,
                },
                {
                    "state": "N3",
                    "samples": 100,
                    "duration_s": 3000,
                    "pct_scored": 12.8,
                    "pct_sleep": 14.7,
                    "score_eligible_samples": 100,
                    "score_eligible_duration_s": 3000,
                    "pct_score_eligible": 13.2,
                    "pct_score_eligible_sleep": 15.2,
                },
                {
                    "state": "REM",
                    "samples": 120,
                    "duration_s": 3600,
                    "pct_scored": 15.4,
                    "pct_sleep": 17.6,
                    "score_eligible_samples": 120,
                    "score_eligible_duration_s": 3600,
                    "pct_score_eligible": 15.8,
                    "pct_score_eligible_sleep": 18.2,
                },
            ],
            "environment": [
                {
                    "key": "temp",
                    "label": "อุณหภูมิ",
                    "unit": "°C",
                    "available": True,
                    "average": 22.4,
                    "values": [22.3, 22.5],
                    "patient_name": "must-not-leak",
                }
            ],
            "environment_assessment": {
                "version": "environment-v-test",
                "overall_level": "good",
                "overall_label": "ดี",
                "patient_name": "must-not-leak",
            },
            "findings": [
                {
                    "key": "temperature",
                    "title": "อุณหภูมิคงที่",
                    "detail": "อยู่ในช่วงของโหมด",
                    "profile": {"medical_answer": "must-not-leak"},
                    "unexpected_raw_payload": "must-not-leak",
                    "nested": {
                        "access_token": "must-not-leak",
                        "accessToken": "must-not-leak",
                        "refreshToken": "must-not-leak",
                        "rawSamples": [{"value": "must-not-leak"}],
                        "BCGBase64": "must-not-leak",
                        "xApiKey": "must-not-leak",
                        "APIKey": "must-not-leak",
                        "clientApiKey": "must-not-leak",
                        "privateKey": "must-not-leak",
                        "samples": [{"raw": "must-not-leak"}],
                    },
                }
            ],
            "data_quality": {
                "level": "high",
                "coverage": {"recording_pct": 100, "bcg_pct": 95},
                "date_of_birth": "must-not-leak",
            },
            "samples": [{"raw": "must-not-leak"}],
        },
    }


class FakeHistory:
    history_start_utc = "2026-09-01T00:00:00+00:00"

    def __init__(self) -> None:
        self.sessions = {
            "a-session": _session("a-session", "a@example.test", "sleep"),
            "b-session": _session("b-session", "b@example.test", "nap_recovery"),
        }

    def account_history(self, account_key, _profile, *, window, limit, offset):
        rows = [
            row for row in self.sessions.values() if row["account_key"] == account_key
        ]
        return self._listing(rows, limit, offset)

    def account_sessions(self, account_key, _profile, *, window=None):
        return [
            row for row in self.sessions.values() if row["account_key"] == account_key
        ]

    def account_completed_sessions(self, account_key, profile):
        return self.account_sessions(account_key, profile)

    def admin_history(
        self,
        _profiles,
        *,
        window,
        account_key,
        query,
        limit,
        offset,
    ):
        rows = list(self.sessions.values())
        if account_key:
            rows = [row for row in rows if row["account_key"] == account_key]
        if query:
            rows = [row for row in rows if query.casefold() in row["email"]]
        return self._listing(rows, limit, offset)

    def session_by_id(self, session_id, _profiles, *, account_key=None):
        row = self.sessions.get(session_id)
        if row and (account_key is None or row["account_key"] == account_key):
            return row
        return None

    @staticmethod
    def _listing(rows, limit, offset):
        sleep_scores = [
            row["sleep_quality"]["score"]
            for row in rows
            if row["sleep_quality"]["quality_type"] == "sleep"
        ]
        recovery_scores = [
            row["sleep_quality"]["score"]
            for row in rows
            if row["sleep_quality"]["quality_type"] == "rest_goal"
        ]
        return {
            "sessions": rows[offset : offset + limit],
            "total": len(rows),
            "summary": {
                "people_count": len({row["account_key"] for row in rows}),
                "session_count": len(rows),
                "sleep_score_count": len(sleep_scores),
                "recovery_score_count": len(recovery_scores),
                "awaiting_score_count": 0,
                "average_sleep_score": (
                    sum(sleep_scores) / len(sleep_scores) if sleep_scores else None
                ),
                "average_recovery_score": (
                    sum(recovery_scores) / len(recovery_scores)
                    if recovery_scores
                    else None
                ),
            },
            "range": None,
            "history_start_utc": "2026-09-01T00:00:00+00:00",
        }


class UsageSessionApiTests(unittest.TestCase):
    _openapi_document = None

    def setUp(self) -> None:
        self.history = FakeHistory()
        self.profiles = {
            "a@example.test": {"email": "a@example.test"},
            "b@example.test": {"email": "b@example.test"},
        }
        self.baselines: dict[str, dict] = {}

        def require_user(
            x_test_account: str | None = Header(default=None),
            x_test_role: str = Header(default="user"),
            x_api_token: str | None = Header(default=None),
        ):
            if x_api_token == "legacy-full-admin":
                return SimpleNamespace(
                    account_key="service",
                    is_admin=True,
                    auth_source="api_token",
                )
            if not x_test_account:
                raise HTTPException(401, "login required")
            return SimpleNamespace(
                account_key=x_test_account.casefold(),
                is_admin=x_test_role == "admin",
                auth_source="cookie",
            )

        def require_admin(
            x_test_account: str | None = Header(default=None),
            x_test_role: str = Header(default="user"),
            x_api_token: str | None = Header(default=None),
        ):
            principal = require_user(
                x_test_account=x_test_account,
                x_test_role=x_test_role,
                x_api_token=x_api_token,
            )
            if not principal.is_admin:
                raise HTTPException(403, "admin required")
            return principal

        app = FastAPI()
        app.include_router(
            create_usage_sessions_router(
                require_user=require_user,
                require_admin=require_admin,
                history_service=lambda: self.history,
                profiles_snapshot=lambda: self.profiles,
                profiles_lock=threading.Lock(),
                timezone_name="Asia/Bangkok",
                baseline_snapshot=lambda account_key: self.baselines.get(account_key),
            )
        )
        self.client = TestClient(app)

    @staticmethod
    def _headers(account: str, role: str = "user") -> dict[str, str]:
        return {"x-test-account": account, "x-test-role": role}

    def _openapi(self):
        cls = type(self)
        if cls._openapi_document is None:
            cls._openapi_document = self.client.app.openapi()
        return cls._openapi_document

    def test_user_lists_only_own_email_first_sessions(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions",
            headers=self._headers("a@example.test"),
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["pagination"]["total"], 1)
        self.assertEqual(data["items"][0]["user"]["email"], "a@example.test")
        self.assertNotIn("username", data["items"][0]["user"])

    def test_list_summary_uses_canonical_score_not_raw_quality_type(self) -> None:
        session = self.history.sessions["a-session"]
        session["sleep_quality"]["quality_type"] = "rest_goal"

        response = self.client.get(
            "/api/v1/usage-sessions",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["items"][0]["score"]["available"])
        self.assertEqual(data["summary"]["sleep_score_count"], 0)
        self.assertEqual(data["summary"]["recovery_score_count"], 0)
        self.assertEqual(data["summary"]["awaiting_score_count"], 1)
        self.assertEqual(
            data["summary"]["sleep_score_count"]
            + data["summary"]["recovery_score_count"]
            + data["summary"]["awaiting_score_count"],
            data["summary"]["session_count"],
        )

    def test_paginated_summary_fails_closed_when_count_invariant_is_invalid(
        self,
    ) -> None:
        result = UsageSessionService._list_contract(
            {
                "sessions": [],
                "total": 2,
                "summary": {
                    "people_count": 2,
                    "session_count": 2,
                    "sleep_score_count": 2,
                    "recovery_score_count": 1,
                    "awaiting_score_count": 0,
                    "average_sleep_score": 82,
                    "average_recovery_score": 78,
                },
                "range": None,
                "history_start_utc": "2026-09-01T00:00:00+00:00",
            },
            limit=1,
            offset=2,
        )

        self.assertEqual(result["summary"]["sleep_score_count"], 0)
        self.assertEqual(result["summary"]["recovery_score_count"], 0)
        self.assertEqual(result["summary"]["awaiting_score_count"], 2)
        self.assertIsNone(result["summary"]["average_sleep_score"])
        self.assertIsNone(result["summary"]["average_recovery_score"])

    def test_user_cannot_select_or_search_another_account(self) -> None:
        for params in (
            {"account_key": "b@example.test"},
            {"query": "b@example.test"},
        ):
            response = self.client.get(
                "/api/v1/usage-sessions",
                params=params,
                headers=self._headers("a@example.test"),
            )
            self.assertEqual(response.status_code, 403)

    def test_unauthorized_session_id_does_not_disclose_ownership(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/b-session/summary",
            headers=self._headers("a@example.test"),
        )
        self.assertEqual(response.status_code, 404)

    def test_admin_can_list_multiple_accounts(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions",
            headers=self._headers("service", "admin"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["pagination"]["total"], 2)

    def test_user_gets_own_longitudinal_profile(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/longitudinal",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.json()["kind"], "user_learning_profile")
        data = response.json()["data"]
        self.assertEqual(data["user"]["canonical_identifier"], "a@example.test")
        self.assertEqual(data["observed_history"]["session_count"], 1)
        self.assertEqual(data["modes"]["sleep"]["session_count"], 1)
        self.assertEqual(data["modes"]["nap_recovery"]["session_count"], 0)
        self.assertFalse(data["ai_contract"]["identity_input_allowed"])
        self.assertFalse(data["ai_contract"]["automatic_actuation_allowed"])

    def test_longitudinal_exposes_prior_best_rest_window_without_source_identity(
        self,
    ) -> None:
        self.baselines["b@example.test"] = {
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
                                "score_value": 78,
                                "score_formula_version": (
                                    RECOVERY_SCORE_FORMULA_VERSION
                                ),
                                "evidence_quality": "high",
                                "outcome_supported": True,
                                "environment_reference_available": True,
                                "environment": {"temp_median": 23.0},
                                "source_session_id": "must-not-leak",
                                "source_started_at_utc": (
                                    "2026-09-10T18:00:00+00:00"
                                ),
                            },
                        }
                    }
                }
            },
        }

        response = self.client.get(
            "/api/v1/usage-sessions/longitudinal",
            headers=self._headers("b@example.test"),
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        target = next(
            item
            for item in data["modes"]["nap_recovery"]["targets"]
            if item["minutes"] == 30
        )
        window = target["baseline"]["best_rest_window"]
        self.assertTrue(window["available"])
        self.assertEqual(window["sessions_compared"], 1)
        self.assertEqual(window["first_visible_visit"], 2)
        self.assertEqual(
            window["method"],
            "highest_current_formula_score_then_evidence_then_most_recent",
        )
        self.assertEqual(window["maturity_confidence"], "low")
        self.assertEqual(window["mode_group"], "nap_recovery")
        self.assertEqual(window["target_key"], "nap_30")
        self.assertEqual(window["timezone"], "Asia/Bangkok")
        self.assertTrue(window["outcome_supported"])
        self.assertFalse(window["affects_score"])
        self.assertFalse(window["affects_sleep_state"])
        self.assertTrue(window["current_session_excluded"])
        self.assertFalse(window["automatic_device_control"])
        self.assertTrue(window["requires_user_confirmation"])
        self.assertEqual(
            window["environment_role"],
            "observed_successful_session_not_confirmed_preference",
        )
        serialized = str(window)
        self.assertNotIn("source_session_id", serialized)
        self.assertNotIn("source_started_at_utc", serialized)
        self.assertNotIn("must-not-leak", serialized)
        self.assertFalse(data["ai_contract"]["personalized_inference_allowed"])

        ai_response = self.client.get(
            "/api/v1/usage-sessions/longitudinal/ai-context",
            headers=self._headers("b@example.test"),
        )
        self.assertEqual(ai_response.status_code, 200, ai_response.text)
        self.assertNotIn("best_rest_window", str(ai_response.json()["data"]))

    def test_openapi_best_rest_window_is_strict_and_source_anonymous(self) -> None:
        schema = self._openapi()["components"]["schemas"]["BestRestWindow"]
        properties = schema["properties"]

        first_visit_schema = properties["first_visible_visit"]
        first_visit = first_visit_schema.get(
            "const",
            (first_visit_schema.get("enum") or [None])[0],
        )
        method_schema = properties["method"]
        method = method_schema.get(
            "const",
            (method_schema.get("enum") or [None])[0],
        )
        self.assertEqual(first_visit, 2)
        self.assertEqual(
            method,
            "highest_current_formula_score_then_evidence_then_most_recent",
        )
        for field in (
            "maturity_confidence",
            "mode_group",
            "timezone",
            "outcome_supported",
            "affects_score",
            "affects_sleep_state",
            "current_session_excluded",
        ):
            self.assertIn(field, properties)
        for forbidden in (
            "session_id",
            "source_session_id",
            "started_at_utc",
            "source_started_at_utc",
            "source_timestamp",
        ):
            self.assertNotIn(forbidden, properties)
        self.assertFalse(schema.get("additionalProperties", True))
        environment_schema = self._openapi()["components"]["schemas"][
            "BestRestWindowEnvironment"
        ]
        self.assertEqual(
            set(environment_schema["properties"]),
            {
                "temp_median",
                "humidity_median",
                "co2_median",
                "lux_median",
                "sound_median",
            },
        )
        self.assertFalse(environment_schema.get("additionalProperties", True))

    def test_user_cannot_request_another_longitudinal_profile(self) -> None:
        headers = self._headers("a@example.test")
        headers["X-Zeep-Account-Key"] = "b@example.test"
        response = self.client.get(
            "/api/v1/usage-sessions/longitudinal",
            headers=headers,
        )

        self.assertEqual(response.status_code, 403)

    def test_ai_context_is_allowlisted_and_contains_no_identity(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/longitudinal/ai-context",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["kind"], "user_ai_context")
        data = response.json()["data"]
        serialized = str(data)
        self.assertEqual(data["contract_version"], "zeep.user-ai-context.v1")
        self.assertNotIn("user", data)
        self.assertNotIn("profile_context", data)
        self.assertNotIn("a@example.test", serialized)
        self.assertNotIn("a-session", serialized)
        self.assertEqual(
            data["guardrails"]["privacy_classification"],
            "direct_identifier_free_linkable_personal_wellness_data",
        )
        self.assertFalse(data["guardrails"]["direct_identifiers_included"])
        self.assertTrue(data["guardrails"]["linkable_personal_wellness_data"])
        self.assertFalse(data["guardrails"]["anonymous_or_deidentified"])
        self.assertFalse(data["guardrails"]["exact_session_timestamps_included"])
        self.assertFalse(data["guardrails"]["model_training_allowed"])
        self.assertFalse(
            data["learning_readiness"]["personalization_inference_authorized"]
        )

    def test_admin_selects_one_longitudinal_profile(self) -> None:
        missing = self.client.get(
            "/api/v1/usage-sessions/longitudinal",
            headers=self._headers("service", "admin"),
        )
        headers = self._headers("service", "admin")
        headers["X-Zeep-Account-Key"] = "b@example.test"
        selected = self.client.get(
            "/api/v1/usage-sessions/longitudinal",
            headers=headers,
        )

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(selected.status_code, 200)
        data = selected.json()["data"]
        self.assertEqual(data["user"]["canonical_identifier"], "b@example.test")
        self.assertEqual(data["modes"]["nap_recovery"]["session_count"], 1)

    def test_longitudinal_account_selector_is_a_header_not_a_query(self) -> None:
        operation = self._openapi()["paths"]["/api/v1/usage-sessions/longitudinal"][
            "get"
        ]
        parameters = operation.get("parameters") or []

        self.assertIn(
            ("x-zeep-account-key", "header"),
            {(item["name"].casefold(), item["in"]) for item in parameters},
        )
        self.assertNotIn(
            ("account_key", "query"),
            {(item["name"], item["in"]) for item in parameters},
        )
        for status in ("401", "403", "422"):
            self.assertIn(status, operation["responses"])

    def test_presentation_is_one_user_facing_hierarchy_without_duplicates(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/presentation",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.json()["kind"], "usage_session_presentation")
        data = response.json()["data"]
        self.assertEqual(data["contract_version"], "zeep.usage-presentation.v1")
        self.assertEqual(data["audience"], "user_summary")
        self.assertEqual(data["primary_result"]["type"], "sleep_score")
        self.assertEqual(data["primary_result"]["value"], 82)
        self.assertEqual(data["primary_result"]["reason_code"], "available")
        self.assertEqual(data["mode"]["key"], "sleep")
        self.assertTrue(data["sleep_stages"]["available"])
        self.assertEqual(data["sleep_stages"]["items"][0]["key"], "n2")
        self.assertIsNone(data["rest_profile"])
        self.assertNotIn("score", data)
        self.assertNotIn("restore_summary", data)
        self.assertNotIn("report", data)
        self.assertNotIn("user", data)
        self.assertNotIn("headline", data)
        self.assertNotIn("recommendation", data["vital_signals"])
        self.assertIsInstance(data["recommendation"], str)

    def test_presentation_uses_nap_content_without_sleep_stage_chart(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/b-session/presentation",
            headers=self._headers("b@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["primary_result"]["type"], "recovery_score")
        self.assertEqual(data["mode"]["key"], "nap_recovery")
        self.assertIsNone(data["sleep_stages"])
        self.assertTrue(data["rest_profile"]["available"])
        self.assertEqual(
            [item["key"] for item in data["rest_profile"]["items"]],
            ["awake_rest", "drowsy", "estimated_sleep"],
        )
        metrics = {item["key"]: item for item in data["overview_metrics"]}
        self.assertEqual(data["timing"]["target_duration_s"], 1800)
        self.assertEqual(metrics["target_completion"]["value"], 100)
        self.assertEqual(metrics["target_completion"]["label"], "ครบตามเวลาเป้าหมาย")
        self.assertEqual(metrics["body_stillness"]["value"], 87.5)
        self.assertEqual(metrics["body_stillness"]["label"], "ความนิ่งร่างกาย")
        self.assertNotIn("movement", metrics)
        self.assertIn("physiological_regularity", metrics)

    def test_unresolved_mode_never_falls_back_to_nap_metrics(self) -> None:
        self.history.sessions["a-session"]["rest_mode"] = "auto"
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/presentation",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["mode"]["key"], "unknown")
        self.assertEqual(
            [metric["key"] for metric in data["overview_metrics"]],
            [],
        )
        self.assertNotEqual(
            data["primary_result"]["type"],
            "recovery_score",
        )
        self.assertFalse(data["primary_result"]["available"])
        self.assertIsNone(data["rest_profile"])
        self.assertIsNone(data["sleep_stages"])

    def test_user_presentation_has_one_action_only(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/presentation",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertIsInstance(data["recommendation"], str)
        for driver in data["positive_drivers"] + data["attention_drivers"]:
            self.assertNotIn("action", driver)

    def test_open_session_cannot_publish_a_stale_score(self) -> None:
        self.history.sessions["a-session"]["ended_at_utc"] = None
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/presentation",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()["data"]["primary_result"]
        self.assertFalse(result["available"])
        self.assertIsNone(result["value"])
        self.assertEqual(result["reason_code"], "session_not_closed")
        data = response.json()["data"]
        self.assertEqual(data["positive_drivers"], [])
        self.assertEqual(data["attention_drivers"], [])
        self.assertFalse(data["personal_baseline"]["available"])
        self.assertFalse(data["trend"]["available"])
        self.assertEqual(
            data["recommendation"],
            "ดูผลสรุปหลังจบการพักครั้งนี้",
        )
        self.assertEqual(data["confidence_label"], "กำลังบันทึกข้อมูล")

    def test_open_session_is_not_released_by_admin_development_view(self) -> None:
        self.history.sessions["a-session"]["ended_at_utc"] = None
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/development",
            headers=self._headers("service", "admin"),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["score_release"]["score_available"])
        self.assertFalse(data["user_summary"]["primary_result"]["available"])
        self.assertIn(
            "session_not_closed",
            {flag["code"] for flag in data["review_flags"]},
        )

    def test_presentation_preserves_the_same_ownership_boundary(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/b-session/presentation",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 404)

    def test_completed_unavailable_result_has_final_reason_not_waiting_copy(
        self,
    ) -> None:
        quality = self.history.sessions["b-session"]["sleep_quality"]
        quality.update(available=False, score=None)
        quality["rest_mode"]["protocol_status"] = {
            "status": "insufficient",
            "score_releasable": False,
        }
        response = self.client.get(
            "/api/v1/usage-sessions/b-session/presentation",
            headers=self._headers("b@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()["data"]["primary_result"]
        self.assertFalse(result["available"])
        self.assertEqual(result["reason_code"], "session_too_short")
        self.assertEqual(result["status"], "ยังไม่มีคะแนนสำหรับครั้งนี้")
        self.assertNotIn("กำลังรวบรวม", result["reason"])

    def test_completed_presentation_uses_final_copy_when_optional_data_is_missing(
        self,
    ) -> None:
        report = self.history.sessions["a-session"]["session_report"]
        report["environment"] = [
            {
                "key": "temp",
                "label": "อุณหภูมิ",
                "available": False,
                "status": "ดี",
            }
        ]
        report["environment_assessment"] = {
            "overall_label": "ยอดเยี่ยม",
            "meets_expected": True,
        }
        report["respiratory_wellness"] = {
            "vital_summary": {
                "available": False,
                "status_label": "ยอดเยี่ยม",
                "summary": "กำลังรวบรวมข้อมูล",
            }
        }
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/presentation",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertFalse(data["environment"]["available"])
        self.assertEqual(
            data["environment"]["status"],
            "ไม่มีข้อมูลสภาพแวดล้อมสำหรับครั้งนี้",
        )
        self.assertIsNone(data["environment"]["meets_expected"])
        self.assertEqual(
            data["environment"]["metrics"][0]["status"],
            "ยังไม่มีข้อมูล",
        )
        self.assertFalse(data["vital_signals"]["available"])
        self.assertEqual(
            data["vital_signals"]["summary"],
            "ข้อมูลชีพจรและการหายใจยังไม่พอสรุป",
        )

    def test_zero_duration_sleep_stages_are_not_marked_available(self) -> None:
        report = self.history.sessions["a-session"]["session_report"]
        for stage in report["stages"]:
            stage["duration_s"] = 0
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/presentation",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        stages = response.json()["data"]["sleep_stages"]
        self.assertFalse(stages["available"])

    def test_development_view_is_admin_only_and_raw_free(self) -> None:
        forbidden = self.client.get(
            "/api/v1/usage-sessions/a-session/development",
            headers=self._headers("a@example.test"),
        )
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/development",
            headers=self._headers("service", "admin"),
        )

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        data = response.json()["data"]
        self.assertEqual(data["contract_version"], "zeep.usage-development.v1")
        self.assertEqual(data["audience"], "admin_development")
        self.assertEqual(data["user"]["email"], "a@example.test")
        self.assertEqual(
            data["score_components"]["earned_points"],
            {"sleep_opportunity": 20.0},
        )
        self.assertTrue(
            data["classification_accounting"]["arithmetic_invariant"]["holds"]
        )
        self.assertFalse(data["raw_data_included"])
        rendered = str(data).casefold()
        self.assertNotIn("must-not-leak", rendered)
        self.assertNotIn("rawsamples", rendered)
        self.assertNotIn("bcgbase64", rendered)

    def test_legacy_api_token_cannot_read_development_results(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/a-session/development",
            headers={"x-api-token": "legacy-full-admin"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"]["code"],
            "usage_api_scoped_credential_required",
        )

    def test_admin_pagination_and_date_validation_are_explicit(self) -> None:
        page = self.client.get(
            "/api/v1/usage-sessions",
            params={"limit": 1, "offset": 1},
            headers=self._headers("service", "admin"),
        ).json()["data"]
        self.assertEqual(page["pagination"]["returned"], 1)
        self.assertFalse(page["pagination"]["has_more"])
        invalid = self.client.get(
            "/api/v1/usage-sessions",
            params={"date_from": "11-09-2026"},
            headers=self._headers("service", "admin"),
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(
            invalid.json()["detail"]["code"],
            "usage_history_filter_invalid",
        )
        time_without_date = self.client.get(
            "/api/v1/usage-sessions",
            params={"time_from": "08:00"},
            headers=self._headers("service", "admin"),
        )
        self.assertEqual(time_without_date.status_code, 422)
        self.assertEqual(
            time_without_date.json()["detail"],
            {
                "code": "usage_history_filter_invalid",
                "message": "กรุณาเลือกวันที่ก่อนกำหนดช่วงเวลา",
            },
        )

    def test_usage_api_scope_and_not_found_errors_have_stable_shape(self) -> None:
        forbidden = self.client.get(
            "/api/v1/usage-sessions",
            params={"account_key": "b@example.test"},
            headers=self._headers("a@example.test"),
        )
        missing = self.client.get(
            "/api/v1/usage-sessions/missing-session",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(
            forbidden.json()["detail"],
            {
                "code": "usage_history_scope_forbidden",
                "message": "บัญชีนี้ดูได้เฉพาะประวัติการใช้งานของตนเอง",
            },
        )
        self.assertEqual(
            missing.json()["detail"],
            {
                "code": "usage_session_not_found",
                "message": "ไม่พบผลการใช้งานนี้ หรือบัญชีนี้ไม่มีสิทธิ์เข้าถึง",
            },
        )

    def test_detail_whitelists_report_and_never_returns_raw_samples(self) -> None:
        response = self.client.get(
            "/api/v1/usage-sessions/a-session",
            headers=self._headers("a@example.test"),
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertNotIn("samples", payload["report"])
        self.assertEqual(
            payload["report"]["quality"]["formula_version"],
            SLEEP_SCORE_FORMULA_VERSION,
        )
        self.assertEqual(
            payload["report"]["quality"]["component_points"],
            {"sleep_opportunity": 20},
        )
        self.assertEqual(
            payload["report"]["quality"]["physiology"]["heart_rate_average"],
            58.4,
        )
        self.assertEqual(payload["report"]["sleep"]["estimated_sleep_s"], 23400)
        accounting = payload["report"]["sleep"]["classification_accounting"]
        self.assertEqual(accounting["direct_confirmed_s"], 18000)
        self.assertEqual(accounting["continuity_carried_forward_s"], 5400)
        self.assertEqual(accounting["provisional_hold_s"], 600)
        self.assertEqual(accounting["score_eligible_s"], 22800)
        self.assertEqual(accounting["initial_wait_s"], 60)
        self.assertEqual(accounting["no_data_s"], 300)
        self.assertEqual(accounting["off_bed_s"], 300)
        self.assertEqual(accounting["restart_display_hold_s"], 60)
        self.assertEqual(accounting["sensor_gap_s"], 1080)
        self.assertTrue(accounting["arithmetic_invariant"]["holds"])
        self.assertEqual(payload["report"]["sleep"]["actual_scored_s"], 22800)
        self.assertEqual(payload["report"]["sleep"]["provisional_hold_s"], 600)
        self.assertEqual(payload["report"]["stages"][0]["state"], "N2")
        self.assertEqual(
            payload["report"]["stages"][0]["score_eligible_duration_s"],
            11400,
        )
        self.assertEqual(
            payload["report"]["stages"][0]["pct_score_eligible"],
            50.0,
        )
        self.assertEqual(
            sum(
                stage["score_eligible_duration_s"]
                for stage in payload["report"]["stages"]
            ),
            accounting["score_eligible_s"],
        )
        self.assertEqual(payload["report"]["environment"][0]["average"], 22.4)
        self.assertEqual(
            payload["report"]["environment_assessment"]["overall_level"],
            "good",
        )
        self.assertEqual(
            payload["report"]["findings"][0]["title"],
            "อุณหภูมิ · กำลังรวบรวมข้อมูล",
        )
        self.assertEqual(
            payload["sleep_policy_versions"], {"evidence": "evidence-v-test"}
        )
        self.assertEqual(
            payload["sleep_estimator_versions"], {"bcg-audio-bed-test": 840}
        )
        rendered = str(payload).casefold()
        self.assertNotIn("must-not-leak", rendered)
        self.assertNotIn("bcg_base64", rendered)
        self.assertNotIn("access_token", rendered)
        self.assertNotIn("medical_answer", rendered)
        self.assertNotIn("engineering_shadow_score", rendered)
        self.assertNotIn("score_unrounded", rendered)
        self.assertNotIn("release_requirements", rendered)
        self.assertNotIn("future_unapproved_field", rendered)
        self.assertNotIn("accesstoken", rendered)
        self.assertNotIn("refreshtoken", rendered)
        self.assertNotIn("rawsamples", rendered)
        self.assertNotIn("bcgbase64", rendered)
        self.assertNotIn("xapikey", rendered)
        self.assertNotIn("apikey", rendered)
        self.assertNotIn("clientapikey", rendered)
        self.assertNotIn("privatekey", rendered)
        self.assertNotIn("hr_series", rendered)
        self.assertNotIn("participant_phone", rendered)
        self.assertNotIn("series", rendered)
        self.assertNotIn("values", rendered)
        self.assertNotIn("patient_name", rendered)
        self.assertNotIn("date_of_birth", rendered)
        self.assertNotIn("raw_epoch_ids", rendered)
        self.assertNotIn("raw_rows", rendered)
        self.assertNotIn("score_private_basis", rendered)

    def test_unavailable_score_never_releases_engineering_fallback(self) -> None:
        session = self.history.sessions["a-session"]
        quality = session["session_report"]["quality"]
        quality["available"] = False
        quality["score"] = 97
        quality["reason"] = "ข้อมูลยืนยันยังไม่พอ"
        quality["environment_support"] = {
            "quality_factor": 0.99,
            "points": 15,
            "safety_excursion_observed": True,
            "safety_review_required": True,
            "safety_excursions_change_score": False,
            "metrics": [
                {
                    "key": "temperature",
                    "status_key": "critical",
                    "status": "วิกฤต",
                    "safety_excursion_observed": True,
                    "critical_below": 13.0,
                    "critical_above": 32.0,
                    "minimum": 12.0,
                    "maximum": 33.0,
                }
            ],
            "safety_excursions": [
                {
                    "key": "temperature",
                    "label": "อุณหภูมิ",
                    "critical_below": 13.0,
                    "critical_above": 32.0,
                    "minimum": 12.0,
                    "maximum": 33.0,
                    "sample_count": 2,
                    "sample_pct": 10.0,
                }
            ],
        }
        session["sleep_quality"] = quality
        session["session_report"].update(
            {
                "headline": "ยอดเยี่ยม พร้อมเต็มที่",
                "insight": "ฟื้นตัวสมบูรณ์แบบ",
                "post_session_guidance": {"primary": "พร้อมแข่งขันเต็มกำลัง"},
                "environment_assessment": {
                    "overall_label": "ยอดเยี่ยม",
                    "safety_excursion_observed": True,
                    "safety_review_required": True,
                    "safety_excursion_count": 1,
                    "safety_excursions": quality["environment_support"][
                        "safety_excursions"
                    ],
                },
                "findings": [
                    {
                        "key": "temperature_safety_excursion",
                        "metric_key": "temperature",
                        "severity": "critical",
                        "decision": "safety_review",
                        "title": "Temperature Gate · Safety excursion",
                        "detail": "Timeline firmware critical",
                        "action": "debug SHT3x-DIS",
                        "critical_below": 13.0,
                        "critical_above": 32.0,
                        "minimum": 12.0,
                        "maximum": 33.0,
                        "sample_count": 2,
                        "sample_pct": 10.0,
                    },
                    {
                        "key": "sound",
                        "severity": "poor",
                        "decision": "required",
                        "title": "เสียง · แย่",
                    },
                ],
            }
        )

        response = self.client.get(
            "/api/v1/usage-sessions/a-session",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertFalse(payload["score"]["available"])
        self.assertIsNone(payload["score"]["value"])
        self.assertFalse(payload["report"]["quality"]["available"])
        self.assertIsNone(payload["report"]["quality"]["score"])
        rendered = str(payload).casefold()
        self.assertNotIn("engineering_shadow_score", rendered)
        self.assertNotIn("score_unrounded", rendered)
        self.assertNotIn("must-not-leak", rendered)
        self.assertEqual(payload["report"]["headline"], "ครั้งนี้ยังไม่มีคะแนน")
        self.assertEqual(
            payload["report"]["insight"],
            "ครั้งนี้ยังไม่มีคะแนน เพราะข้อมูลสำคัญสำหรับสรุปผลยังไม่ครบ",
        )
        safety_finding = payload["report"]["findings"][0]
        self.assertEqual(safety_finding["decision"], "safety_review")
        self.assertEqual(safety_finding["title"], "อุณหภูมิ · ควรให้ทีมตรวจสอบ")
        self.assertEqual(safety_finding["critical_below"], 13.0)
        self.assertEqual(safety_finding["minimum"], 12.0)
        self.assertEqual(safety_finding["maximum"], 33.0)
        self.assertEqual(len(payload["report"]["findings"]), 1)
        assessment = payload["report"]["environment_assessment"]
        self.assertTrue(assessment["safety_review_required"])
        self.assertEqual(assessment["safety_excursions"][0]["minimum"], 12.0)
        support = payload["report"]["quality"]["environment_support"]
        self.assertTrue(support["safety_review_required"])
        self.assertNotIn("quality_factor", support)
        self.assertNotIn("points", support)
        summary_driver = payload["restore_summary"]["drivers"]["attention"][0]
        self.assertEqual(summary_driver["decision"], "safety_review")
        self.assertEqual(summary_driver["critical_above"], 32.0)
        self.assertEqual(summary_driver["sample_count"], 2)
        self.assertEqual(
            payload["report"]["post_session_guidance"]["primary"],
            "กรุณาแจ้งทีมงาน",
        )
        self.assertFalse(
            payload["report"]["post_session_guidance"]["medical_diagnosis"]
        )
        self.assertNotIn("ยอดเยี่ยม", rendered)
        self.assertNotIn("พร้อมแข่งขัน", rendered)
        self.assertNotIn("SHT3x", rendered)
        self.assertNotIn("Timeline", rendered)

    def test_available_high_score_keeps_safety_review_prominent(self) -> None:
        session = self.history.sessions["a-session"]
        quality = session["sleep_quality"]
        quality.update(
            {
                "score": 94,
                "level": "ดีมาก",
                "level_key": "very_good",
                "safety_review_required": True,
            }
        )

        detail_response = self.client.get(
            "/api/v1/usage-sessions/a-session",
            headers=self._headers("a@example.test"),
        )
        self.assertEqual(detail_response.status_code, 200)
        detail = detail_response.json()["data"]
        self.assertTrue(detail["score"]["available"])
        self.assertEqual(detail["score"]["value"], 94)
        self.assertEqual(detail["score"]["level"], "ควรให้ทีมตรวจสอบ")
        self.assertTrue(detail["score"]["review_required"])
        self.assertTrue(detail["report"]["quality"]["safety_review_required"])
        self.assertEqual(
            detail["restore_summary"]["status"]["key"],
            "safety_review",
        )
        self.assertIn(
            "ตรวจสอบก่อนใช้งานครั้งถัดไป",
            detail["report"]["headline"],
        )

        presentation_response = self.client.get(
            "/api/v1/usage-sessions/a-session/presentation",
            headers=self._headers("a@example.test"),
        )
        self.assertEqual(presentation_response.status_code, 200)
        primary = presentation_response.json()["data"]["primary_result"]
        self.assertEqual(primary["value"], 94)
        self.assertIn("ตรวจสอบก่อนใช้งานครั้งถัดไป", primary["status"])

    def test_available_score_rebuilds_all_user_copy_from_stable_keys(self) -> None:
        session = self.history.sessions["a-session"]
        quality = session["sleep_quality"]
        quality.update(
            {
                "level_key": "future_level",
                "level": "แย่มาก",
                "insight": "Gate ไม่ผ่าน",
                "outcome_interpretation": "ควรหยุดกิจกรรมทั้งหมด",
                "score_scope": "internal firmware result",
                "component_labels": {
                    "sleep_opportunity": "Sleep onset Gate",
                    "restorative_architecture": "N2/N3/REM architecture",
                    "data_coverage": "BCG paired coverage",
                },
                "disclaimer": "BCG Sensor result using AASM PSG proxy",
            }
        )
        quality["score_confidence"]["label"] = "ข้อมูลไม่พอ"
        session["session_report"].update(
            {
                "headline": "แย่มาก",
                "insight": "Gate ไม่ผ่าน",
                "reason": "Timeline SHT3x-DIS error",
                "disclaimer": "BCG/AASM/PSG internal report note",
                "environment_assessment": {
                    "mode": "sleep",
                    "mode_label": "BCG Overnight Gate",
                    "acceptable_min_level": "fair",
                    "acceptable_min_label": "firmware threshold",
                    "overall_level": "poor",
                    "overall_label": "แย่",
                },
                "findings": [
                    {
                        "key": "temperature",
                        "severity": "poor",
                        "decision": "required",
                        "title": "Timeline Gate SHT3x-DIS · แย่",
                        "detail": "firmware freshness fail",
                        "action": "debug sensor",
                    },
                    {
                        "key": "acoustic_corroborated",
                        "severity": "fair",
                        "decision": "investigate",
                        "title": "SPH0645 / BCG / Bed Status",
                        "detail": "Timeline Gate matched 4 Epochs",
                        "action": "debug firmware",
                    },
                    {
                        "key": "future_backend_finding",
                        "severity": "poor",
                        "decision": "investigate",
                        "title": "UNKNOWN GATE FAILED",
                        "detail": "raw backend wording",
                        "action": "inspect payload",
                    },
                ],
                "data_quality": {
                    "level": "future_level",
                    "label": "ข้อมูลไม่พอ",
                    "note": "BCG Gate firmware",
                },
                "post_session_guidance": {
                    "primary": "พร้อมแข่งขันเต็มกำลัง",
                    "medical_diagnosis": True,
                    "score_released": True,
                },
            }
        )

        response = self.client.get(
            "/api/v1/usage-sessions/a-session",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["score"]["level"], "ผลการพักครั้งนี้")
        self.assertEqual(
            payload["report"]["quality"]["score_confidence"]["label"],
            "ข้อมูลชัดเจน",
        )
        self.assertEqual(
            payload["report"]["data_quality"]["label"],
            "ข้อมูลยังไม่พอสรุป",
        )
        self.assertIn(
            "ความครบถ้วนของข้อมูล",
            payload["report"]["data_quality"]["note"],
        )
        self.assertEqual(
            payload["report"]["findings"][0]["title"],
            "อุณหภูมิ · ควรปรับ",
        )
        findings = {item["key"]: item for item in payload["report"]["findings"]}
        self.assertEqual(
            findings["acoustic_corroborated"]["title"],
            "เสียงและการขยับบนเตียง · ลองสังเกตเพิ่มเติม",
        )
        self.assertEqual(
            findings["future_backend_finding"]["title"],
            "ข้อมูลประกอบ · ลองสังเกตเพิ่มเติม",
        )
        assessment = payload["report"]["environment_assessment"]
        self.assertEqual(assessment["mode_label"], "Overnight Recovery")
        self.assertEqual(assessment["acceptable_min_label"], "พอใช้")
        labels = payload["report"]["quality"]["component_labels"]
        self.assertEqual(labels["sleep_opportunity"], "เวลาและการเข้าสู่การพัก")
        self.assertEqual(labels["restorative_architecture"], "รูปแบบการพัก")
        self.assertEqual(labels["data_coverage"], "ความครบถ้วนของข้อมูล")
        self.assertEqual(
            payload["report"]["quality"]["disclaimer"],
            "ผลประเมินเพื่อ Wellness · ไม่ใช่การวินิจฉัยหรือทดแทนผลตรวจทางการแพทย์",
        )
        self.assertEqual(
            payload["report"]["disclaimer"],
            "ผลประเมินเพื่อ Wellness · ไม่ใช่การวินิจฉัยหรือทดแทนผลตรวจทางการแพทย์",
        )
        self.assertFalse(
            payload["report"]["post_session_guidance"]["medical_diagnosis"]
        )
        rendered = str(payload)
        for internal_copy in (
            "แย่มาก",
            "Gate",
            "Timeline",
            "SHT3x",
            "SPH0645",
            "Bed Status",
            "Epochs",
            "AASM",
            "PSG",
            "UNKNOWN",
            "backend wording",
            "firmware",
            "พร้อมแข่งขันเต็มกำลัง",
        ):
            self.assertNotIn(internal_copy, rendered)

    def test_public_report_mode_is_canonical_and_mismatch_blocks_score(self) -> None:
        cases = (
            ("a-session", "sleep", "nap_recovery"),
            ("b-session", "nap_recovery", "sleep"),
        )
        for session_id, canonical, stale in cases:
            with self.subTest(session_id=session_id):
                session = self.history.sessions[session_id]
                session["session_report"]["rest_mode"] = {"group": stale}
                session["session_report"]["headline"] = "ยอดเยี่ยม"
                response = self.client.get(
                    f"/api/v1/usage-sessions/{session_id}",
                    headers=self._headers(session["account_key"]),
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()["data"]
                self.assertEqual(payload["mode"]["key"], canonical)
                self.assertEqual(payload["report"]["rest_mode"]["key"], canonical)
                self.assertEqual(
                    payload["report"]["quality"]["rest_mode"]["key"],
                    canonical,
                )
                self.assertTrue(payload["mode"]["review_required"])
                self.assertFalse(payload["score"]["available"])
                self.assertEqual(
                    payload["report"]["headline"],
                    "ครั้งนี้ยังไม่มีคะแนน",
                )
                self.assertNotIn("ยอดเยี่ยม", str(payload))

    def test_report_quality_uses_canonical_released_score(self) -> None:
        session = self.history.sessions["a-session"]
        quality = session["session_report"]["quality"]
        session["sleep_quality"] = dict(quality)
        quality.update(
            {
                "available": False,
                "score": 97,
                "score_title": "Internal Shadow Score",
                "formula_version": "unapproved-shadow-formula",
                "validation_status": "unapproved_shadow",
                "clinical_validated": True,
                "level": "shadow-level",
            }
        )

        response = self.client.get(
            "/api/v1/usage-sessions/a-session",
            headers=self._headers("a@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        canonical = payload["score"]
        public_quality = payload["report"]["quality"]
        self.assertTrue(canonical["available"])
        self.assertEqual(canonical["value"], 82.0)
        self.assertEqual(public_quality["available"], canonical["available"])
        self.assertEqual(public_quality["score"], canonical["value"])
        self.assertEqual(public_quality["score_title"], canonical["title"])
        self.assertEqual(
            public_quality["formula_version"],
            canonical["formula_version"],
        )
        self.assertEqual(
            public_quality["clinical_validated"],
            canonical["clinical_validated"],
        )
        self.assertEqual(public_quality["level"], canonical["level"])
        self.assertNotIn("shadow", str(public_quality).casefold())

    def test_all_usage_responses_are_private_and_not_cached(self) -> None:
        calls = (
            "/api/v1/usage-sessions",
            "/api/v1/usage-sessions/a-session/summary",
            "/api/v1/usage-sessions/a-session",
        )
        for path in calls:
            with self.subTest(path=path):
                response = self.client.get(
                    path,
                    headers=self._headers("a@example.test"),
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers.get("cache-control"),
                    "private, no-store",
                )

    def test_legacy_broad_api_token_is_rejected(self) -> None:
        for path in (
            "/api/v1/usage-sessions",
            "/api/v1/usage-sessions/a-session/summary",
            "/api/v1/usage-sessions/a-session",
        ):
            with self.subTest(path=path):
                response = self.client.get(
                    path,
                    headers={"X-API-Token": "legacy-full-admin"},
                )
                self.assertEqual(response.status_code, 403)
                self.assertEqual(
                    response.json()["detail"]["code"],
                    "usage_api_scoped_credential_required",
                )

    def test_score_contract_distinguishes_sleep_and_recovery(self) -> None:
        sleep = self.client.get(
            "/api/v1/usage-sessions/a-session/summary",
            headers=self._headers("a@example.test"),
        ).json()["data"]
        recovery = self.client.get(
            "/api/v1/usage-sessions/b-session/summary",
            headers=self._headers("b@example.test"),
        ).json()["data"]
        self.assertEqual(sleep["score"]["type"], "sleep_score")
        self.assertEqual(recovery["score"]["type"], "recovery_score")
        self.assertFalse(sleep["restore_summary"]["creates_independent_score"])
        self.assertFalse(recovery["restore_summary"]["whole_day_readiness_available"])

    def test_summary_quality_is_a_nested_positive_allowlist(self) -> None:
        payload = self.client.get(
            "/api/v1/usage-sessions/a-session/summary",
            headers=self._headers("a@example.test"),
        ).json()["data"]

        self.assertEqual(payload["data_quality"]["confidence"]["level"], "high")
        self.assertEqual(
            payload["data_quality"]["confidence"]["paired_hr_rr_coverage_pct"],
            92,
        )
        rendered = str(payload).casefold()
        self.assertNotIn("participant_email", rendered)
        self.assertNotIn("rr_series", rendered)
        self.assertNotIn("must-not-leak", rendered)

    def test_nap_protocol_status_is_a_nested_positive_allowlist(self) -> None:
        session = self.history.sessions["b-session"]
        quality = session["sleep_quality"]
        quality["duration_target"] = {
            "key": "nap_30m",
            "label": "Nap & Refresh · 30 นาที",
            "seconds": 1800,
            "recommended_range_minutes": [20, 35],
            "completion_pct": 100,
        }
        quality["rest_mode"]["protocol_status"] = {
            "available": True,
            "canonical_mode": "nap_recovery",
            "observed_seconds": 1800,
            "recommended_range_seconds": [1200, 2100],
            "within_operational_window": True,
            "within_recommended_range": True,
            "status": "recommended",
            "review_required": False,
            "score_releasable": True,
            "target": {
                "available": True,
                "group": "nap_recovery",
                "key": "nap_30m",
                "label": "Nap & Refresh · 30 นาที",
                "seconds": 1800,
                "participant_phone": "must-not-leak",
            },
            "participant_email": "must-not-leak",
            "co2_series": [700, 710],
            "future_protocol_field": "must-not-leak",
        }
        session["session_report"]["quality"] = quality
        session["session_report"]["rest_mode"] = quality["rest_mode"]

        response = self.client.get(
            "/api/v1/usage-sessions/b-session/summary",
            headers=self._headers("b@example.test"),
        )

        self.assertEqual(response.status_code, 200)
        target = response.json()["data"]["mode"]["target"]
        self.assertEqual(target["protocol_status"]["status"], "recommended")
        self.assertEqual(target["protocol_status"]["target"]["seconds"], 1800)
        rendered = str(target).casefold()
        self.assertNotIn("must-not-leak", rendered)
        self.assertNotIn("participant", rendered)
        self.assertNotIn("co2_series", rendered)
        self.assertNotIn("future_protocol_field", rendered)

    def test_openapi_publishes_typed_usage_response_contracts(self) -> None:
        document = self._openapi()
        paths = document["paths"]
        expected = {
            "/api/v1/usage-sessions": "UsageSessionListResponse",
            "/api/v1/usage-sessions/{session_id}/summary": (
                "UsageSessionSummaryResponse"
            ),
            "/api/v1/usage-sessions/{session_id}": "UsageSessionDetailResponse",
        }
        for path, schema_name in expected.items():
            with self.subTest(path=path):
                schema = paths[path]["get"]["responses"]["200"]["content"][
                    "application/json"
                ]["schema"]
                self.assertEqual(
                    schema["$ref"],
                    f"#/components/schemas/{schema_name}",
                )

        rendered = str(document["components"]["schemas"])
        for enum_value in (
            "sleep_score",
            "recovery_score",
            "unresolved_score",
            "sleep_restore_good",
            "rest_good",
            "not_measured",
        ):
            self.assertIn(enum_value, rendered)

    def test_openapi_list_example_matches_the_published_response_model(self) -> None:
        validate = getattr(UsageSessionListResponse, "model_validate", None)
        if validate:
            parsed = validate(USAGE_LIST_EXAMPLE)
        else:  # pragma: no cover - Pydantic v1 deployment compatibility
            parsed = UsageSessionListResponse.parse_obj(USAGE_LIST_EXAMPLE)

        self.assertEqual(parsed.kind, "usage_session_list")
        self.assertEqual(parsed.data.summary.session_count, 2)

        document = self._openapi()
        published_example = document["paths"]["/api/v1/usage-sessions"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["example"]
        if validate:
            validate(published_example)
        else:  # pragma: no cover - Pydantic v1 deployment compatibility
            UsageSessionListResponse.parse_obj(published_example)


if __name__ == "__main__":
    unittest.main()
