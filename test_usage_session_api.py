from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from zeep_pod.sessions.response_models import UsageSessionListResponse
from zeep_pod.sessions.usage_api import USAGE_LIST_EXAMPLE, create_usage_sessions_router


def _session(session_id: str, email: str, mode: str) -> dict:
    is_nap = mode == "nap_recovery"
    quality = {
        "available": True,
        "score": 78 if is_nap else 82,
        "quality_type": "rest_goal" if is_nap else "sleep",
        "score_title": "Recovery Score" if is_nap else "Sleep Score",
        "formula_version": "recovery-v-test" if is_nap else "sleep-v-test",
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
                "sleep_efficiency_pct": 92.9,
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
                    "series": ["N2", "N2"],
                }
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
    def setUp(self) -> None:
        self.history = FakeHistory()
        self.profiles = {
            "a@example.test": {"email": "a@example.test"},
            "b@example.test": {"email": "b@example.test"},
        }

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

        app = FastAPI()
        app.include_router(
            create_usage_sessions_router(
                require_user=require_user,
                history_service=lambda: self.history,
                profiles_snapshot=lambda: self.profiles,
                profiles_lock=threading.Lock(),
                timezone_name="Asia/Bangkok",
            )
        )
        self.client = TestClient(app)

    @staticmethod
    def _headers(account: str, role: str = "user") -> dict[str, str]:
        return {"x-test-account": account, "x-test-role": role}

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
        time_without_date = self.client.get(
            "/api/v1/usage-sessions",
            params={"time_from": "08:00"},
            headers=self._headers("service", "admin"),
        )
        self.assertEqual(time_without_date.status_code, 422)

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
            "sleep-v-test",
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
        self.assertEqual(payload["report"]["stages"][0]["state"], "N2")
        self.assertEqual(payload["report"]["environment"][0]["average"], 22.4)
        self.assertEqual(
            payload["report"]["environment_assessment"]["overall_level"],
            "good",
        )
        self.assertEqual(payload["report"]["findings"][0]["title"], "อุณหภูมิคงที่")
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

    def test_unavailable_score_never_releases_engineering_fallback(self) -> None:
        session = self.history.sessions["a-session"]
        quality = session["session_report"]["quality"]
        quality["available"] = False
        quality["score"] = 97
        quality["reason"] = "ข้อมูลยืนยันยังไม่พอ"
        session["sleep_quality"] = quality
        session["session_report"].update(
            {
                "headline": "ยอดเยี่ยม พร้อมเต็มที่",
                "insight": "ฟื้นตัวสมบูรณ์แบบ",
                "post_session_guidance": {"primary": "พร้อมแข่งขันเต็มกำลัง"},
                "environment_assessment": {"headline": "ยอดเยี่ยม"},
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
        self.assertEqual(payload["report"]["headline"], "ยังสรุปคะแนนไม่ได้")
        self.assertEqual(payload["report"]["insight"], "ข้อมูลยืนยันยังไม่พอ")
        self.assertEqual(payload["report"]["findings"], [])
        self.assertNotIn("environment_assessment", payload["report"])
        self.assertNotIn("ยอดเยี่ยม", rendered)
        self.assertNotIn("พร้อมแข่งขัน", rendered)

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
                    "ยังสรุปคะแนนไม่ได้",
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
        document = self.client.app.openapi()
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

        document = self.client.app.openapi()
        published_example = document["paths"]["/api/v1/usage-sessions"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["example"]
        if validate:
            validate(published_example)
        else:  # pragma: no cover - Pydantic v1 deployment compatibility
            UsageSessionListResponse.parse_obj(published_example)


if __name__ == "__main__":
    unittest.main()
