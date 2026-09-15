"""Safety regression tests for the per-user Sleep Baseline learner."""

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from personal import MIN_DETECTED_SLEEP_SECONDS, BaselineStore
from sleep_system_policy import (
    PERSONAL_BASELINE_LEARNING_START_UTC,
    PERSONAL_BEHAVIOUR_BASELINE_VERSION,
    PREVIOUS_SESSION_REPORT_VERSION,
    PREVIOUS_SLEEP_QUALITY_VERSION,
    RECOVERY_SCORE_FORMULA_VERSION,
    SESSION_REPORT_VERSION,
    SLEEP_QUALITY_VERSION,
    SLEEP_SCORE_FORMULA_VERSION,
    ZEEP_SLEEP_BASELINE_VERSION,
)


class _DatabaseStub:
    def __init__(self, final_summary, timeline=None, stage_events=None):
        self.final_summary = final_summary
        self.timeline = timeline or []
        self.stage_events = stage_events or []

    def read_sessions(self, sql, params=()):
        if "type='final_summary'" in sql:
            if self.final_summary is None:
                return []
            return [{"value": json.dumps(self.final_summary)}]
        if "type='sleep_stage'" in sql:
            return list(self.stage_events)
        if "FROM timeline" in sql:
            return list(self.timeline)
        return []


class _BehaviourDatabaseStub:
    def __init__(self, sessions, summaries, timelines):
        self.sessions = sessions
        self.summaries = summaries
        self.timelines = timelines

    def read_sessions(self, sql, params=()):
        if "FROM sessions " in sql:
            return list(self.sessions)
        session_id = params[0] if params else None
        if "type='final_summary'" in sql:
            summary = self.summaries.get(session_id)
            return ([{"value": json.dumps(summary)}] if summary else [])
        if "type='sleep_stage'" in sql:
            return []
        if "FROM timeline" in sql:
            return list(self.timelines.get(session_id, []))
        return []


class _AliasDatabaseStub(_BehaviourDatabaseStub):
    def __init__(self, sessions, summaries, timelines):
        super().__init__(sessions, summaries, timelines)
        self.requested_account_keys = ()

    def read_sessions(self, sql, params=()):
        if "FROM sessions " in sql:
            self.requested_account_keys = tuple(params[:-3])
            return [
                row
                for row in self.sessions
                if row["username_key"] in self.requested_account_keys
            ]
        return super().read_sessions(sql, params)


def _summary(*, quality_type, sleep_detected, estimated_sleep_s):
    return {
        "night_summary": {
            "estimated_sleep_s": estimated_sleep_s,
            "sleep_quality": {
                "quality_type": quality_type,
                "sleep_detected": sleep_detected,
                "estimated_sleep_s": estimated_sleep_s,
            },
        }
    }


def _behaviour_summary(*, mode_group, resolved, rr, confidence="high"):
    quality_type = "sleep" if mode_group == "sleep" else "rest_goal"
    quality = {
        "available": True,
        "version": SLEEP_QUALITY_VERSION,
        "quality_type": quality_type,
        "formula_version": (
            SLEEP_SCORE_FORMULA_VERSION
            if mode_group == "sleep"
            else RECOVERY_SCORE_FORMULA_VERSION
        ),
        "score": 80,
        "sleep_detected": False,
        "estimated_sleep_s": 0,
    }
    if mode_group == "nap_recovery":
        quality["duration_target"] = {
            "key": "nap_30",
            "seconds": 1_800,
        }
    else:
        quality["duration_target"] = {
            "key": "overnight_7h",
            "seconds": 25_200,
        }
    return {
        "night_summary": {},
        "session_report": {
            "version": SESSION_REPORT_VERSION,
            "rest_mode": {"group": mode_group, "resolved": resolved},
            "quality": quality,
            "respiratory_wellness": {
                "available": True,
                "status": {"key": "supportive"},
                "confidence": {
                    "level": confidence,
                    "direct_measurements_only": True,
                },
                "observations": {
                    "median_rr_brpm": rr,
                    "regularity_factor": 0.9,
                },
            },
        },
    }


class PersonalBaselineEligibilityTests(unittest.TestCase):
    def _store(self, summary):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return BaselineStore(_DatabaseStub(summary), Path(temporary.name))

    def _alias_store(self, profiles, account_keys):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        (data_dir / "profiles.json").write_text(
            json.dumps(profiles),
            encoding="utf-8",
        )
        sessions = []
        summaries = {}
        timelines = {}
        for index, account_key in enumerate(account_keys):
            session_id = f"alias-session-{index}"
            timestamp = datetime(
                2026,
                9,
                index + 1,
                tzinfo=UTC,
            ).isoformat()
            sessions.append({
                "session_id": session_id,
                "username_key": account_key,
                "duration": 1_800.0,
                "start_time": timestamp,
                "rest_mode": "short_nap",
                "target_duration_s": 1_800.0,
            })
            summaries[session_id] = _behaviour_summary(
                mode_group="nap_recovery",
                resolved="short_nap",
                rr=16.0,
            )
            timelines[session_id] = [{
                "timestamp": timestamp,
                "temperature": 24.0,
                "humidity": 50.0,
                "co2": 700.0,
                "lux": 0.0,
                "sound": 38.0,
                "heart_rate": 62.0,
                "respiration_rate": 16.0,
                "bed_status": "On bed",
            }]
        database = _AliasDatabaseStub(sessions, summaries, timelines)
        return BaselineStore(database, data_dir), database

    def test_awake_rest_session_never_trains_sleep_baseline(self):
        store = self._store(_summary(
            quality_type="rest_goal", sleep_detected=False,
            estimated_sleep_s=0,
        ))
        self.assertIsNone(store._night_metrics("rest-session"))

    def test_delete_user_removes_derived_baseline_from_disk(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(_DatabaseStub(None), Path(temporary.name))
        store.data["person@example.com"] = {"status": "active"}
        store._save_locked()

        self.assertTrue(store.delete_user("PERSON@example.com"))
        self.assertIsNone(store.get("person@example.com"))
        persisted = json.loads(store.path.read_text(encoding="utf-8"))
        self.assertNotIn("person@example.com", persisted)
        self.assertFalse(store.delete_user("person@example.com"))

    def test_mixed_case_baseline_key_is_normalized_on_load(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        data_dir = Path(temporary.name)
        record = {
            "policy_version": ZEEP_SLEEP_BASELINE_VERSION,
            "behaviour_policy_version": PERSONAL_BEHAVIOUR_BASELINE_VERSION,
            "learning_cutoff": {"utc": PERSONAL_BASELINE_LEARNING_START_UTC},
            "status": "learning",
        }
        (data_dir / "baselines.json").write_text(
            json.dumps({"Person@Example.COM": record}),
            encoding="utf-8",
        )

        store = BaselineStore(_DatabaseStub(None), data_dir)

        self.assertEqual(store.get("person@example.com"), record)

    def test_rekey_moves_only_an_ownership_verified_legacy_baseline(self):
        canonical = "person@example.com"
        legacy = "old-login"
        store, _database = self._alias_store(
            {canonical: {"legacy_account_keys": [legacy]}},
            [],
        )
        record = {"updated_at_utc": "2026-09-15T00:00:00+00:00"}
        store.data[legacy] = record

        changed = store.rekey_users({legacy: canonical})

        self.assertEqual(changed, 1)
        self.assertNotIn(legacy, store.data)
        self.assertNotIn(canonical, store.data)

    def test_rekey_rejects_an_alias_with_multiple_identity_owners(self):
        canonical = "person@example.com"
        legacy = "shared-login"
        store, _database = self._alias_store(
            {
                canonical: {
                    "zeep_public_id": "public-person",
                    "legacy_account_keys": [legacy],
                },
                "other@example.com": {
                    "zeep_public_id": "public-other",
                    "legacy_account_keys": [legacy],
                },
            },
            [],
        )
        record = {"updated_at_utc": "2026-09-15T00:00:00+00:00"}
        store.data[legacy] = record

        changed = store.rekey_users({legacy: canonical})

        self.assertEqual(changed, 0)
        self.assertIs(store.data[legacy], record)
        self.assertNotIn(canonical, store.data)

    def test_rekey_rebuild_uses_all_canonical_and_legacy_sessions(self):
        canonical = "person@example.com"
        legacy = "old-login"
        store, _database = self._alias_store(
            {canonical: {"legacy_account_keys": [legacy]}},
            [canonical, legacy],
        )
        store.data[canonical] = {"updated_at_utc": "2026-09-15T02:00:00Z"}
        store.data[legacy] = {"updated_at_utc": "2026-09-15T01:00:00Z"}

        outcome = store.rebuild_rekeyed_users({legacy: canonical})

        self.assertEqual(outcome["rebuilt"], 1)
        self.assertEqual(outcome["errors"], {})
        target = store.data[canonical]["behaviour_by_mode"]["nap_recovery"][
            "by_target"
        ]["nap_30"]
        self.assertEqual(target["sessions_used"], 2)
        self.assertNotIn(legacy, store.data)

    def test_rebuild_combines_canonical_and_uniquely_owned_legacy_rows(self):
        canonical = "person@example.com"
        legacy = "old-login"
        store, database = self._alias_store(
            {
                canonical: {
                    "zeep_public_id": "public-person",
                    "legacy_account_keys": [legacy],
                },
            },
            [canonical, legacy],
        )

        record = store.update_user(canonical.upper())

        self.assertEqual(
            set(database.requested_account_keys),
            {canonical, legacy},
        )
        target = record["behaviour_by_mode"]["nap_recovery"]["by_target"][
            "nap_30"
        ]
        self.assertEqual(target["sessions_used"], 2)
        self.assertIn(canonical, store.data)
        self.assertEqual(
            store.profile_for(canonical)["verified_legacy_account_keys"],
            [legacy],
        )

        store.data[legacy] = store.data.pop(canonical)
        self.assertIs(store.get(canonical), record)

    def test_duplicate_legacy_claim_fails_closed_for_rebuild_and_read(self):
        canonical = "person@example.com"
        legacy = "shared-old-login"
        profiles = {
            canonical: {
                "zeep_public_id": "public-person",
                "legacy_account_keys": [legacy],
            },
            "other@example.com": {
                "zeep_public_id": "public-other",
                "legacy_account_keys": [legacy],
            },
        }
        store, database = self._alias_store(
            profiles,
            [canonical, legacy],
        )

        record = store.update_user(canonical)

        self.assertEqual(database.requested_account_keys, (canonical,))
        target = record["behaviour_by_mode"]["nap_recovery"]["by_target"][
            "nap_30"
        ]
        self.assertEqual(target["sessions_used"], 1)
        self.assertEqual(
            store.profile_for(canonical)["verified_legacy_account_keys"],
            [],
        )
        store.data = {legacy: record}
        self.assertIsNone(store.get(canonical))

    def test_different_public_id_canonical_owner_is_never_mixed(self):
        canonical = "person@example.com"
        other = "other@example.com"
        store, database = self._alias_store(
            {
                canonical: {
                    "zeep_public_id": "public-person",
                    "legacy_account_keys": [other],
                },
                other: {"zeep_public_id": "public-other"},
            },
            [canonical, other],
        )

        record = store.update_user(canonical)

        self.assertEqual(database.requested_account_keys, (canonical,))
        target = record["behaviour_by_mode"]["nap_recovery"]["by_target"][
            "nap_30"
        ]
        self.assertEqual(target["sessions_used"], 1)

    def test_duplicate_claim_is_allowed_only_for_one_shared_public_id(self):
        canonical = "person@example.com"
        legacy = "shared-old-login"
        public_id = "public-person"
        store, database = self._alias_store(
            {
                canonical: {
                    "zeep_public_id": public_id,
                    "legacy_account_keys": [legacy],
                },
                "prior@example.com": {
                    "zeep_public_id": public_id,
                    "legacy_account_keys": [legacy],
                },
            },
            [canonical, legacy],
        )

        record = store.update_user(canonical)

        self.assertEqual(
            set(database.requested_account_keys),
            {canonical, legacy},
        )
        target = record["behaviour_by_mode"]["nap_recovery"]["by_target"][
            "nap_30"
        ]
        self.assertEqual(target["sessions_used"], 2)

    def test_missing_final_report_never_trains_sleep_baseline(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(_DatabaseStub(None), Path(temporary.name))
        self.assertIsNone(store._night_metrics("unfinished-session"))

    def test_too_little_detected_sleep_is_not_a_learning_night(self):
        store = self._store(_summary(
            quality_type="sleep", sleep_detected=True,
            estimated_sleep_s=MIN_DETECTED_SLEEP_SECONDS - 5,
        ))
        self.assertIsNone(store._night_metrics("micro-sleep-session"))

    def test_mode_conflict_never_trains_physiology_or_score_trend(self):
        summary = {
            "rest_mode": "sleep",
            "night_summary": {
                "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                "sleep_quality": {
                    "available": True,
                    "score": 88,
                    "quality_type": "sleep",
                    "sleep_detected": True,
                    "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "version": PREVIOUS_SLEEP_QUALITY_VERSION,
                    "rest_mode": {"group": "nap_recovery"},
                },
            },
            "session_report": {
                "version": PREVIOUS_SESSION_REPORT_VERSION,
                "rest_mode": {"group": "nap_recovery"},
            },
        }
        store = self._store(summary)

        self.assertIsNone(store._night_metrics("conflicting-session"))
        self.assertIsNone(
            store._behaviour_metrics(
                "conflicting-session",
                MIN_DETECTED_SLEEP_SECONDS,
            )
        )

    def test_previous_approved_overnight_still_trains_baseline(self):
        summary = {
            "night_summary": {
                "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                "sleep_quality": {
                    "available": True,
                    "quality_type": "sleep",
                    "sleep_detected": True,
                    "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "version": PREVIOUS_SLEEP_QUALITY_VERSION,
                },
            },
            "session_report": {
                "version": PREVIOUS_SESSION_REPORT_VERSION,
                "rest_mode": {"group": "sleep", "resolved": "overnight"},
            },
        }
        timeline = [{
            "timestamp": f"2026-09-01T00:{index:02d}:00+00:00",
            "temperature": 24.0,
            "humidity": 50.0,
            "co2": 700.0,
            "lux": 0.0,
            "sound": 38.0,
            "heart_rate": 62.0 + (index % 2),
            "respiration_rate": 14.0,
            "bed_status": "On bed",
        } for index in range(30)]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _DatabaseStub(summary, timeline), Path(temporary.name)
        )

        metrics = store._night_metrics("previous-overnight")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["mode_group"], "sleep")

    def test_current_baseline_excludes_provisional_and_continuity_rows(self):
        summary = {
            "night_summary": {
                "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                "sleep_quality": {
                    "available": True,
                    "quality_type": "sleep",
                    "sleep_detected": True,
                    "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                    "formula_version": SLEEP_SCORE_FORMULA_VERSION,
                    "version": PREVIOUS_SLEEP_QUALITY_VERSION,
                },
            },
            "session_report": {
                "version": PREVIOUS_SESSION_REPORT_VERSION,
                "rest_mode": {"group": "sleep", "resolved": "overnight"},
            },
        }
        origin = datetime(2026, 9, 1, tzinfo=UTC)
        timeline = []
        for index in range(36):
            timestamp = origin + timedelta(seconds=(index + 1) * 10)
            timeline.append({
                "timestamp": timestamp.isoformat(),
                "temperature": 24.0,
                "humidity": 50.0,
                "co2": 700.0,
                "lux": 0.0,
                "sound": 38.0,
                "heart_rate": 100.0 if index < 6 else 60.0,
                "respiration_rate": 20.0 if index < 6 else 14.0,
                "bed_status": "On bed",
            })
        stage_events = []
        for index in range(12):
            start = origin + timedelta(seconds=index * 30)
            end = start + timedelta(seconds=30)
            excluded = index < 2
            stage_events.append({
                "timestamp": end.isoformat(),
                "value": json.dumps({
                    "state": "n2",
                    "attribution_start": start.isoformat(),
                    "attribution_end": end.isoformat(),
                    "sample_interval_s": 30,
                    "provisional": excluded,
                    "score_eligible": not excluded,
                    "excluded_from_personal_baseline": excluded,
                }),
            })
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _DatabaseStub(summary, timeline, stage_events),
            Path(temporary.name),
        )

        metrics = store._night_metrics("current-overnight")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["hr_quiet_median"], 60.0)
        self.assertEqual(
            metrics["baseline_stage_filter"],
            "direct_score_eligible_stage_intervals",
        )

    def test_behaviour_context_is_partitioned_by_mode_and_never_selects_stage(self):
        store = self._store(_summary(
            quality_type="sleep", sleep_detected=True,
            estimated_sleep_s=MIN_DETECTED_SLEEP_SECONDS,
        ))
        store.data["person@example.com"] = {
            "policy_version": ZEEP_SLEEP_BASELINE_VERSION,
            "behaviour_policy_version": PERSONAL_BEHAVIOUR_BASELINE_VERSION,
            "learning_cutoff": {"utc": PERSONAL_BASELINE_LEARNING_START_UTC},
            "behaviour_by_mode": {
                "sleep": {
                    "status": "active",
                    "sessions_used": 3,
                    "expected_onset_minutes": 14.0,
                    "direct_stage_influence": False,
                },
            },
        }

        sleep = store.behaviour_context("person@example.com", "overnight")
        nap = store.behaviour_context("person@example.com", "nap_recovery")

        self.assertEqual(sleep["expected_onset_minutes"], 14.0)
        self.assertFalse(sleep["direct_stage_influence"])
        self.assertEqual(nap["status"], "no_data")

    def test_get_rejects_a_previous_baseline_policy(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(_DatabaseStub(None), Path(temporary.name))
        store.data["person@example.com"] = {
            "policy_version": "zeep-baseline-obsolete",
            "learning_cutoff": {"utc": PERSONAL_BASELINE_LEARNING_START_UTC},
            "status": "active",
        }

        self.assertIsNone(store.get("person@example.com"))

    def test_behaviour_metrics_preserve_the_stored_formula_version(self):
        summary = {
            "rest_mode": "sleep",
            "night_summary": {
                "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                "sleep_quality": {
                    "available": True,
                    "score": 82,
                    "quality_type": "sleep",
                    "sleep_detected": True,
                    "estimated_sleep_s": MIN_DETECTED_SLEEP_SECONDS,
                    "formula_version": "zeep-sleep-score-v1.0-reviewed",
                    "version": SLEEP_QUALITY_VERSION,
                },
            },
            "session_report": {
                "version": SESSION_REPORT_VERSION,
                "rest_mode": {"group": "sleep", "resolved": "overnight"},
            },
        }
        timeline = [{
            "timestamp": "2026-09-10T22:00:00+00:00",
            "temperature": 24.0,
            "humidity": 50.0,
            "co2": 700.0,
            "lux": 0.0,
            "sound": 38.0,
        }]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _DatabaseStub(summary, timeline),
            Path(temporary.name),
        )

        metrics = store._behaviour_metrics(
            "previous-formula",
            7 * 3600,
            "sleep",
        )

        self.assertIsNotNone(metrics)
        self.assertEqual(
            metrics["score_formula_version"],
            "zeep-sleep-score-v1.0-reviewed",
        )

    def test_nap_target_mismatch_never_trains_target_baseline(self):
        summary = _behaviour_summary(
            mode_group="nap_recovery",
            resolved="short_nap",
            rr=16.0,
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _DatabaseStub(
                summary,
                [{
                    "timestamp": "2026-09-10T06:00:00+00:00",
                    "temperature": 24.0,
                    "humidity": 50.0,
                    "co2": 700.0,
                    "lux": 0.0,
                    "sound": 38.0,
                }],
            ),
            Path(temporary.name),
        )

        self.assertIsNone(
            store._behaviour_metrics(
                "mismatched-target",
                5_400,
                "nap_recovery",
                5_400,
            )
        )

    def test_legacy_nap_target_is_not_inferred_from_quality_result(self):
        summary = _behaviour_summary(
            mode_group="nap_recovery",
            resolved="short_nap",
            rr=16.0,
        )
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _DatabaseStub(
                summary,
                [{
                    "timestamp": "2026-09-10T06:00:00+00:00",
                    "temperature": 24.0,
                    "humidity": 50.0,
                    "co2": 700.0,
                    "lux": 0.0,
                    "sound": 38.0,
                }],
            ),
            Path(temporary.name),
        )

        metrics = store._behaviour_metrics(
            "legacy-target",
            1_800,
            "nap_recovery",
            None,
        )

        self.assertIsNotNone(metrics)
        self.assertIsNone(metrics["target_key"])

    def test_respiratory_reference_uses_only_high_quality_same_mode_sessions(self):
        sessions = []
        summaries = {}
        timelines = {}
        start = datetime(2026, 9, 1, tzinfo=UTC)

        def add_session(session_id, index, mode_group, resolved, rr, confidence):
            sessions.append({
                "session_id": session_id,
                "duration": 1_800.0,
                "start_time": (start + timedelta(days=index)).isoformat(),
            })
            summaries[session_id] = _behaviour_summary(
                mode_group=mode_group,
                resolved=resolved,
                rr=rr,
                confidence=confidence,
            )
            timelines[session_id] = [{
                "timestamp": (start + timedelta(days=index)).isoformat(),
                "temperature": 24.0,
                "humidity": 50.0,
                "co2": 700.0,
                "lux": 0.0,
                "sound": 38.0,
                "heart_rate": 62.0,
                "respiration_rate": rr,
                "bed_status": "On bed",
            }]

        for index in range(7):
            add_session(
                f"nap-{index}", index, "nap_recovery", "short_nap",
                17.0, "high",
            )
            add_session(
                f"sleep-{index}", index + 10, "sleep", "overnight",
                13.0, "high",
            )
        add_session(
            "nap-low-quality", 20, "nap_recovery", "short_nap",
            30.0, "low",
        )

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = BaselineStore(
            _BehaviourDatabaseStub(sessions, summaries, timelines),
            Path(temporary.name),
        )

        record = store.update_user("person@example.com")
        nap = record["behaviour_by_mode"]["nap_recovery"]
        sleep = record["behaviour_by_mode"]["sleep"]

        self.assertEqual(nap["sessions_used"], 8)
        self.assertEqual(nap["respiratory_reference"]["sessions_used"], 7)
        self.assertEqual(nap["respiratory_reference"]["status"], "active")
        self.assertEqual(nap["respiratory_reference"]["median_rr_brpm"], 17.0)
        self.assertEqual(sleep["respiratory_reference"]["sessions_used"], 7)
        self.assertEqual(sleep["respiratory_reference"]["median_rr_brpm"], 13.0)
        self.assertTrue(nap["respiratory_reference"]["same_mode_only"])
        self.assertTrue(
            nap["respiratory_reference"]["prior_completed_sessions_only"]
        )
        self.assertFalse(nap["respiratory_reference"]["affects_score"])
        self.assertFalse(nap["respiratory_reference"]["direct_stage_influence"])
