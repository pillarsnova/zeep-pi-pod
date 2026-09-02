from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

import progressive_profile as profile_model


class ProgressiveProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
        self.profile = {"gender": "female", "sessions": 0}

    def test_consent_is_optional_and_first_prompt_is_low_burden(self):
        initial = profile_model.public_snapshot(self.profile, now=self.now)
        self.assertEqual(initial["consent"]["status"], "pending")
        self.assertIsNone(initial["prompt"])
        self.assertFalse(initial["guardrails"]["sleep_stage_direct_input"])

        profile_model.set_consent(self.profile, True, now=self.now)
        snapshot = profile_model.public_snapshot(self.profile, now=self.now)
        self.assertEqual(snapshot["prompt"]["id"], "primary_rest_goal")
        self.assertEqual(snapshot["progress"]["total"], 3)

    def test_answer_is_validated_and_next_automatic_prompt_waits_24_hours(self):
        profile_model.set_consent(self.profile, True, now=self.now)
        with self.assertRaises(ValueError):
            profile_model.apply_answer(
                self.profile, "primary_rest_goal", "diagnosis", now=self.now)
        profile_model.apply_answer(
            self.profile, "primary_rest_goal", "sleep", now=self.now)
        immediate = profile_model.public_snapshot(self.profile, now=self.now)
        self.assertIsNone(immediate["prompt"])
        self.assertEqual(immediate["available_question"]["id"], "usual_bedtime")
        tomorrow = profile_model.public_snapshot(
            self.profile, now=self.now + timedelta(hours=24, seconds=1))
        self.assertEqual(tomorrow["prompt"]["id"], "usual_bedtime")

    def test_question_tiers_unlock_with_completed_sessions(self):
        profile_model.set_consent(self.profile, True, now=self.now)
        for question_id, value in (
            ("primary_rest_goal", "sleep"),
            ("usual_bedtime", "22:30"),
            ("usual_wake_time", "06:30"),
        ):
            profile_model.apply_answer(
                self.profile, question_id, value, now=self.now)
            self.profile["progressive_profile"]["next_prompt_after_utc"] = None
        complete = profile_model.public_snapshot(self.profile, now=self.now)
        self.assertEqual(complete["progress"]["percent"], 100)
        self.assertIsNone(complete["available_question"])

        self.profile["sessions"] = 1
        unlocked = profile_model.public_snapshot(self.profile, now=self.now)
        self.assertEqual(unlocked["available_question"]["id"], "schedule_regularity")

    def test_defer_and_withdrawal_are_user_controlled(self):
        profile_model.set_consent(self.profile, True, now=self.now)
        profile_model.defer_question(
            self.profile, "primary_rest_goal", now=self.now)
        deferred = profile_model.public_snapshot(self.profile, now=self.now)
        self.assertIsNone(deferred["prompt"])
        # Another eligible question remains available only by deliberate action.
        self.assertEqual(deferred["available_question"]["id"], "usual_bedtime")

        profile_model.apply_answer(
            self.profile, "usual_bedtime", "23:00", now=self.now)
        profile_model.set_consent(self.profile, False, now=self.now)
        withdrawn = profile_model.public_snapshot(self.profile, now=self.now)
        self.assertEqual(withdrawn["consent"]["status"], "declined")
        self.assertEqual(withdrawn["answers"], {})
        self.assertIsNone(withdrawn["prompt"])

    def test_session_snapshot_is_versioned_context_not_stage_evidence(self):
        self.assertIsNone(profile_model.session_context_snapshot(self.profile))
        profile_model.set_consent(self.profile, True, now=self.now)
        profile_model.apply_answer(
            self.profile, "primary_rest_goal", "nap", now=self.now)
        context = profile_model.session_context_snapshot(self.profile)
        self.assertEqual(context["answers"], {"primary_rest_goal": "nap"})
        self.assertEqual(
            context["intended_use"], "session_context_not_sleep_stage_evidence")

    def test_admin_chooser_receives_completion_only(self):
        profile_model.set_consent(self.profile, True, now=self.now)
        profile_model.apply_answer(
            self.profile, "primary_rest_goal", "relax", now=self.now)
        summary = profile_model.admin_progress_summary(self.profile)
        self.assertEqual(summary["consent_status"], "granted")
        self.assertEqual(summary["answered"], 1)
        self.assertNotIn("answers", summary)


if __name__ == "__main__":
    unittest.main()
