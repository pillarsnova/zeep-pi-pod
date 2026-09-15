from __future__ import annotations

import json
import subprocess
import sys
import unittest
from typing import get_args

from sleep_system_policy import (
    APPROVED_SCORE_FORMULA_VERSIONS_BY_GROUP,
    RECOVERY_SCORE_FORMULA_VERSION,
)
from zeep_pod.sessions.user_ai_context import (
    build_user_ai_context,
    validated_user_ai_context,
)
from zeep_pod.sessions.user_ai_response_models import (
    ScoreFormulaVersion,
    UserAiContext,
)
from zeep_pod.sessions.user_learning_profile import build_user_learning_profile


class UserAiContextTests(unittest.TestCase):
    def test_projection_has_no_direct_identifier_and_is_allowlist_only(self) -> None:
        sentinel = "DO-NOT-SEND-TO-AI"
        profile = build_user_learning_profile(
            account_key="person@example.test",
            profile={
                "email": "person@example.test",
                "display_name": sentinel,
                "age_group": "30-44",
                "gender": "female",
                "progressive_profile": {"answers": {"private": sentinel}},
            },
            sessions=[{
                "session_id": sentinel,
                "ended_at_utc": "2026-09-14T06:00:00+00:00",
                "duration_s": 1_800,
                "sample_count": 180,
                "mode": {
                    "group": "nap_recovery",
                    "target": {"key": "nap_30", "minutes": 30},
                },
                "score": {
                    "available": True,
                    "value": 82,
                    "type": "recovery_score",
                    "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                },
            }],
            questionnaire={
                "consent_status": "granted",
                "answered": 3,
                "total": 5,
                "percent": 60,
                "questionnaire_version": sentinel,
            },
            history_start_utc="2026-09-01T00:00:00+00:00",
        )

        context = validated_user_ai_context(profile)
        serialized = json.dumps(context, ensure_ascii=False, sort_keys=True)

        self.assertEqual(
            set(context),
            {
                "contract_version",
                "source_profile_version",
                "source_policy_version",
                "observed_history",
                "modes",
                "learning_readiness",
                "guardrails",
            },
        )
        self.assertNotIn("person@example.test", serialized)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn("user", context)
        self.assertNotIn("profile_context", context)
        self.assertTrue(context["guardrails"]["wellness_advisory_only"])
        self.assertFalse(context["guardrails"]["direct_identifiers_included"])
        self.assertTrue(
            context["guardrails"]["linkable_personal_wellness_data"]
        )
        self.assertFalse(context["guardrails"]["anonymous_or_deidentified"])
        self.assertFalse(
            context["guardrails"]["exact_session_timestamps_included"]
        )
        self.assertFalse(context["guardrails"]["model_training_allowed"])
        self.assertFalse(
            context["learning_readiness"][
                "personalization_inference_authorized"
            ]
        )
        self.assertFalse(
            context["guardrails"]["automatic_device_control_allowed"]
        )

    def test_all_source_strings_are_filtered_before_ai_egress(self) -> None:
        sentinel = "DO-NOT-SEND-TO-AI"
        profile = build_user_learning_profile(
            account_key=sentinel,
            profile={
                "email": sentinel,
                "display_name": sentinel,
                "age_group": sentinel,
                "gender": sentinel,
            },
            sessions=[{
                "session_id": sentinel,
                "ended_at_utc": "2026-09-14T06:00:00+00:00",
                "duration_s": 1_800,
                "sample_count": 180,
                "mode": {
                    "group": "nap_recovery",
                    "target": {"key": "nap_30", "minutes": 30},
                },
                "score": {
                    "available": True,
                    "value": 82,
                    "type": "recovery_score",
                    "formula_version": RECOVERY_SCORE_FORMULA_VERSION,
                },
            }],
            questionnaire={
                "consent_status": "granted",
                "answered": 1,
                "total": 1,
                "percent": 100,
                "questionnaire_version": sentinel,
            },
            history_start_utc="2026-09-01T00:00:00+00:00",
        )
        profile["contract_version"] = sentinel
        profile["policy_version"] = sentinel
        profile["observed_history"]["modes_used"] = [sentinel]
        profile["learning_readiness"].update({
            "status": sentinel,
            "personal_comparison_ready_modes": [sentinel],
            "personal_comparison_ready_targets": [sentinel],
            "data_gaps": [sentinel],
        })
        for mode in profile["modes"].values():
            mode.update({
                "key": sentinel,
                "score_type": sentinel,
                "active_formula_version": sentinel,
            })
            mode["trend"].update({
                "direction": sentinel,
                "label": sentinel,
                "formula_version": sentinel,
            })
            mode["baseline"].update({
                "status": sentinel,
                "target_key": sentinel,
                "baseline_policy_version": sentinel,
                "score_formula_version": sentinel,
                "score_reference_status": sentinel,
            })
        target = profile["modes"]["nap_recovery"]["targets"][0]
        target.update({
            "key": "nap_30",
            "active_formula_version": sentinel,
        })
        target["trend"].update({
            "direction": sentinel,
            "label": sentinel,
            "formula_version": sentinel,
        })
        target["baseline"].update({
            "status": sentinel,
            "target_key": sentinel,
            "baseline_policy_version": sentinel,
            "score_formula_version": sentinel,
            "score_reference_status": sentinel,
        })

        context = build_user_ai_context(profile)
        serialized = json.dumps(context, ensure_ascii=False, sort_keys=True)

        self.assertNotIn(sentinel, serialized)
        self.assertEqual(
            context["source_profile_version"],
            "zeep.user-learning-profile.v1",
        )
        self.assertEqual(
            context["learning_readiness"]["data_sufficiency_status"],
            "no_data",
        )
        self.assertIsNone(
            context["modes"]["nap_recovery"]["active_formula_version"]
        )
        self.assertEqual(
            context["modes"]["nap_recovery"]["targets"][0]["key"],
            "nap_30",
        )
        validate = getattr(UserAiContext, "model_validate", None)
        if validate is not None:
            validate(context)
        else:  # pragma: no cover - exercised on Pydantic v1
            UserAiContext.parse_obj(context)

    def test_models_build_schema_under_pydantic_v1_compatibility(self) -> None:
        code = """
import sys
import pydantic.v1 as pydantic_v1
sys.modules['pydantic'] = pydantic_v1
from zeep_pod.sessions.user_ai_response_models import UserAiContext
from zeep_pod.sessions.user_profile_response_models import UserLearningProfile
from zeep_pod.sessions.user_ai_context import validated_user_ai_context
assert UserAiContext.schema()['title'] == 'UserAiContext'
assert UserLearningProfile.schema()['title'] == 'UserLearningProfile'
assert validated_user_ai_context({})['learning_readiness'][
    'personalization_inference_authorized'
] is False
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_formula_enum_matches_the_approved_policy_register(self) -> None:
        approved = set().union(
            *APPROVED_SCORE_FORMULA_VERSIONS_BY_GROUP.values()
        )

        self.assertEqual(set(get_args(ScoreFormulaVersion)), approved)

    def test_ai_schema_has_no_unconstrained_string_values(self) -> None:
        schema_method = getattr(UserAiContext, "model_json_schema", None)
        schema = schema_method() if schema_method else UserAiContext.schema()
        unconstrained = []

        def visit(value, path: str) -> None:
            if isinstance(value, dict):
                if value.get("type") == "string" and not (
                    "enum" in value or "const" in value
                ):
                    unconstrained.append(path)
                for key, item in value.items():
                    visit(item, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    visit(item, f"{path}[{index}]")

        visit(schema, "root")

        self.assertEqual(unconstrained, [])


if __name__ == "__main__":
    unittest.main()
