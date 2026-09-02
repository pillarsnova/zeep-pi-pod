"""Guards for the finished-Session upload to the ZEEP account backend.

The account backend stores ``record`` verbatim in a jsonb column and returns it
from both the history list and detail endpoints, so these tests pin two things:
the payload stays small and free of raw Timeline/Profile data, and the numbers
inside it reconcile with each other and with what the Pod itself displays.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from testing_support import configure_app_test_environment

configure_app_test_environment()

import app  # noqa: E402  (must follow the environment setup)
from sleep_session_report import build_session_report, build_sleep_quality  # noqa: E402

# The upload is disabled unless both are configured. Another test module may
# already have imported app, so override the resolved values rather than the
# environment they were read from.
_INGEST_CONFIG = {
    "ZEEP_INGEST_API_KEY": "test-ingest-key",
    "ZEEP_INGEST_DEVICE_ID": "f65acc3e-6b12-43db-9c27-d9e462441589",
    "POD_TIMEZONE": "Asia/Bangkok",
}
_SAVED_CONFIG: Dict[str, Any] = {}


def setUpModule() -> None:
    for name, value in _INGEST_CONFIG.items():
        _SAVED_CONFIG[name] = getattr(app, name)
        setattr(app, name, value)


def tearDownModule() -> None:
    for name, value in _SAVED_CONFIG.items():
        setattr(app, name, value)


SLEEP_LIKE = {"n1", "n2", "n3", "rem", "nrem_light", "nrem_deep"}
START_EPOCH = datetime(2026, 8, 31, 15, 0, 0, tzinfo=timezone.utc).timestamp()


def build_record(
    stages: List[Optional[str]],
    interval_s: float = 5.0,
    *,
    awakenings: int = 0,
    zeep_public_id: Optional[str] = "11111111-2222-3333-4444-555555555555",
    persisted_interval_s: Any = "same",
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return (record, report_samples) shaped exactly as finalization builds them."""
    rows: List[Dict[str, Any]] = []
    for index, stage in enumerate(stages):
        rows.append({
            "t": START_EPOCH + index * interval_s, "sleep": stage, "bed": "On bed",
            "temp": 24.0, "hum": 50.0, "lux": 1.0, "dba": 33.0, "co2": 800.0,
            "pm2_5": None, "voc": None, "hr": 60.0, "rr": 14.0,
        })
    duration_s = len(stages) * interval_s
    counts: Dict[str, int] = {}
    for row in rows:
        if row["sleep"]:
            counts[row["sleep"]] = counts.get(row["sleep"], 0) + 1
    sleep_samples = sum(value for key, value in counts.items() if key in SLEEP_LIKE)
    scored = sleep_samples + counts.get("wake", 0)
    night = {
        "sleep_onset_proxy_s": None, "awakenings": awakenings, "waso_proxy_s": 0.0,
        "estimated_sleep_s": round(min(duration_s, sleep_samples * interval_s), 1),
        "sleep_efficiency": round(sleep_samples / scored, 3) if scored else None,
        "deep_ratio": None, "rem_ratio": None,
    }
    quality = build_sleep_quality(
        duration_s, night, counts, completed=True, rest_mode="sleep",
        stage_sequence=rows, sensor_samples=rows, sample_interval_s=interval_s)
    night["sleep_quality"] = quality
    report = build_session_report(
        duration_s, rows, night, counts, quality, rest_mode="sleep",
        sample_interval_s=interval_s, estimator_version="test", completed=True,
        timeline_schema_version=app.SESSION_TIMELINE_SCHEMA_VERSION)
    record = {
        "session_id": "s-20260831T150000Z-a1b2c3",
        "username": "tester", "username_key": "tester@example.com",
        "zeep_public_id": zeep_public_id,
        "identity_subject": f"zeep:{zeep_public_id}", "pod_id": "test-pod-01",
        "started_at_utc": datetime.fromtimestamp(START_EPOCH, timezone.utc).isoformat(),
        "ended_at_utc": datetime.fromtimestamp(START_EPOCH + duration_s, timezone.utc).isoformat(),
        "duration_s": duration_s,
        "sample_interval_s": interval_s if persisted_interval_s == "same" else persisted_interval_s,
        # Present on the real record and all of it must stay out of the upload.
        "samples": rows, "counters": {"led": 3, "steam": 1},
        "health_reference": {"height_cm": 175, "conditions": ["hypertension"]},
        "wellness_context": {"alcohol": True},
        "sample_cadence_segments": [{"from": 0}],
        "terminal_wake_transition": {"start_time": "x"},
        "summary": {
            "heart_rate_bpm": {"avg": 60.0, "min": 47.0, "max": 88.0, "n": len(rows)},
            "respiration_rate": {"avg": 14.2, "min": 9.0, "max": 21.0, "n": len(rows)},
            "sleep_state_counts": counts,
        },
        "sleep_quality": quality, "session_report": report,
    }
    return record, rows


def derive_architecture(segments: List[Dict[str, Any]]) -> Tuple[Optional[float], int]:
    """Replay the account backend's latency/awakenings derivation (stage 0 = Awake)."""
    first_sleep = next((i for i, s in enumerate(segments) if s["stage"] != 0), -1)
    if first_sleep == -1:
        return None, 0
    latency = round(sum(s["minutes"] for s in segments[:first_sleep]), 1)
    return latency, sum(1 for s in segments[first_sleep:] if s["stage"] == 0)


NIGHT = (["wake"] * 96 + ["n1"] * 60 + ["n2"] * 900 + ["n3"] * 600 + ["n2"] * 300
         + ["rem"] * 400 + ["wake"] * 24 + ["n2"] * 700 + ["n3"] * 400 + ["rem"] * 500
         + ["off_bed"] * 36 + ["n2"] * 600 + ["rem"] * 350 + ["wake"] * 12)


class IngestPayloadTests(unittest.TestCase):
    """A full night must upload as a small, self-consistent summary."""

    def setUp(self) -> None:
        self.record, self.rows = build_record(NIGHT, 5.0, awakenings=3)
        self.payload = app._build_ingest_payload(self.record, self.rows)
        self.assertIsNotNone(self.payload)
        self.result = self.payload["record"]

    def test_raw_timeline_and_profile_context_never_leave_the_pod(self) -> None:
        # scoring_result is echoed by every history request, so a leak here is
        # not just size: health_reference is frozen medical context.
        for key in ("samples", "counters", "health_reference", "wellness_context",
                    "identity_subject", "summary", "session_report", "sleep_quality",
                    "username", "username_key", "zeep_public_id",
                    "sample_cadence_segments", "terminal_wake_transition"):
            self.assertNotIn(key, self.result)
        self.assertLess(len(json.dumps(self.payload, ensure_ascii=False)), 64_000)

    def test_envelope_carries_only_the_documented_fields(self) -> None:
        self.assertEqual(
            set(self.payload),
            {"userPublicId", "deviceId", "externalSessionId", "startedAt",
             "endedAt", "timezone", "record"},
        )
        self.assertEqual(self.payload["externalSessionId"], self.record["session_id"])

    def test_epoch_totals_reconcile_with_scored_minutes(self) -> None:
        self.assertEqual(self.result["epoch_seconds"], 5)
        self.assertAlmostEqual(
            self.result["total_epochs"] * self.result["epoch_seconds"] / 60.0,
            self.result["total_scored_minutes"], delta=0.1)

    def test_segment_minutes_reconcile_with_stage_minutes(self) -> None:
        for state in ("wake", "n1", "n2", "n3", "rem"):
            got = sum(s["minutes"] for s in self.result["segments"]
                      if s["stage_name"] == state)
            self.assertAlmostEqual(got, self.result[f"{state}_minutes"], delta=0.6, msg=state)
        scored = sum(s["minutes"] for s in self.result["segments"]
                     if s["stage_name"] != "off_bed")
        self.assertAlmostEqual(scored, self.result["total_scored_minutes"], delta=0.6)

    def test_every_segment_carries_minutes(self) -> None:
        # Without minutes the backend falls back to a 30-second epoch this Pod
        # never uses, silently inflating latency and stage durations.
        self.assertTrue(all(isinstance(s.get("minutes"), float)
                            for s in self.result["segments"]))

    def test_hypnogram_runs_parallel_to_segments(self) -> None:
        self.assertEqual(len(self.result["hypnogram"]), self.result["total_segments"])
        for run, segment in zip(self.result["hypnogram"], self.result["segments"]):
            self.assertEqual((run["s"], run["n"]), (segment["stage"], segment["epochs"]))

    def test_backend_derives_the_pods_own_latency_and_awakenings(self) -> None:
        latency, awakenings = derive_architecture(self.result["segments"])
        self.assertAlmostEqual(latency, 8.0, delta=0.1)
        # Three wake bouts after onset, one of which is the bed exit.
        self.assertEqual(awakenings, self.record["session_report"]["sleep"]["awakenings"])
        self.assertEqual(awakenings, 3)

    def test_bed_exit_stays_visible_and_out_of_the_stage_totals(self) -> None:
        off_bed = [s for s in self.result["segments"] if s["stage_name"] == "off_bed"]
        self.assertEqual(len(off_bed), 1)
        # Index 0 makes the backend count it as an awakening; the name keeps it
        # distinguishable from scored Stage W, which owns wake_minutes.
        self.assertEqual(off_bed[0]["stage"], 0)
        self.assertAlmostEqual(off_bed[0]["minutes"], 3.0, delta=0.1)

    def test_score_is_present_so_history_statistics_include_the_night(self) -> None:
        # The backend skips a session with a null score in every aggregate.
        self.assertIsInstance(self.result["sleep_score"], int)
        self.assertEqual(self.result["sleep_score"],
                         self.record["sleep_quality"]["score"])

    def test_all_five_stage_percentages_are_sent_as_one_comparable_set(self) -> None:
        percentages = {}
        for state in ("wake", "n1", "n2", "n3", "rem"):
            value = self.result[f"{state}_percent"]
            self.assertIsInstance(value, int, state)
            percentages[state] = value
        # pct_scored is rounded to preserve an exact total, so the row's
        # percentages stay internally consistent instead of drifting.
        self.assertEqual(sum(percentages.values()), 100)

    def test_the_four_level_ontology_columns_are_left_empty(self) -> None:
        # N2 is not "Light" and N3 is not "Deep"; stage_n1/n2/n3_pct carries the
        # AASM detail, so nothing is lost by leaving these unset.
        for key in ("light_percent", "deep_percent", "light_minutes", "deep_minutes"):
            self.assertNotIn(key, self.result)

    def test_each_percentage_matches_its_own_stage_minutes(self) -> None:
        scored = self.result["total_scored_minutes"]
        for state in ("wake", "n1", "n2", "n3", "rem"):
            share = self.result[f"{state}_minutes"] * 100.0 / scored
            self.assertAlmostEqual(share, self.result[f"{state}_percent"],
                                   delta=0.6, msg=state)

    def test_heart_rate_is_reduced_to_the_fields_the_backend_reads(self) -> None:
        self.assertEqual(set(self.result["heart_rate"]), {"avg", "min", "max"})

    def test_respiration_rate_travels_in_the_raw_result_blob(self) -> None:
        # There is no respiration column, so this is only readable from
        # scoring_result. Same three statistics as heart rate, n dropped.
        self.assertEqual(set(self.result["respiration_rate"]), {"avg", "min", "max"})
        source = self.record["summary"]["respiration_rate"]
        for key in ("avg", "min", "max"):
            self.assertEqual(self.result["respiration_rate"][key], source[key])

    def test_a_missing_vital_series_becomes_an_empty_object(self) -> None:
        # _series_stats returns None when the sensor produced nothing usable.
        record, rows = build_record(NIGHT, 5.0)
        record["summary"]["respiration_rate"] = None
        record["summary"]["heart_rate_bpm"] = None
        result = app._build_ingest_payload(record, rows)["record"]
        self.assertEqual(result["respiration_rate"], {})
        self.assertEqual(result["heart_rate"], {})


class IngestEnvironmentTests(unittest.TestCase):
    """Pod criterion keys must be re-keyed to what the backend reads."""

    def setUp(self) -> None:
        record, rows = build_record(NIGHT, 5.0)
        self.environment = app._build_ingest_payload(record, rows)["record"]["environment"]

    def test_keys_are_remapped_for_the_account_backend(self) -> None:
        self.assertEqual(set(self.environment),
                         {"temperature", "humidity", "co2", "noise", "lux", "pm25", "voc"})
        self.assertEqual(self.environment["noise"]["sample_key"], "dba")
        self.assertEqual(self.environment["lux"]["sample_key"], "lux")

    def test_avg_is_present_on_every_metric(self) -> None:
        # The backend promotes metric["avg"]; sending only the Pod's "average"
        # would leave avg_temp/avg_humidity/avg_co2/avg_noise_db/avg_lux null.
        for key, metric in self.environment.items():
            self.assertIn("avg", metric, key)
        for key in ("temperature", "humidity", "co2", "noise", "lux"):
            self.assertIsInstance(self.environment[key]["avg"], (int, float))

    def test_unavailable_sensor_sends_an_explicit_null(self) -> None:
        self.assertIsNone(self.environment["pm25"]["avg"])
        self.assertIsNone(self.environment["voc"]["avg"])

    def test_pod_explanations_survive_into_the_jsonb_column(self) -> None:
        temperature = self.environment["temperature"]
        for key in ("label", "target", "status", "action", "unit"):
            self.assertIn(key, temperature)


class IngestStageEncodingTests(unittest.TestCase):
    """Run-length encoding of the scored stage series."""

    def test_legacy_aliases_fold_into_n2_and_n3(self) -> None:
        record, rows = build_record(
            ["wake"] * 12 + ["nrem_light"] * 600 + ["nrem_deep"] * 300 + ["rem"] * 200)
        result = app._build_ingest_payload(record, rows)["record"]
        self.assertEqual({s["stage_name"] for s in result["segments"]},
                         {"wake", "n2", "n3", "rem"})
        got = sum(s["minutes"] for s in result["segments"] if s["stage_name"] == "n2")
        self.assertAlmostEqual(got, result["n2_minutes"], delta=0.6)

    def test_a_sensor_gap_does_not_split_one_bout_into_two(self) -> None:
        # Splitting would report a single awakening as two, and the unscored
        # rows are absent from every stage total anyway.
        record, rows = build_record(
            ["wake"] * 12 + ["n2"] * 300 + [None] * 12 + ["n2"] * 300 + ["rem"] * 100)
        segments = app._build_ingest_payload(record, rows)["record"]["segments"]
        self.assertEqual([s["stage_name"] for s in segments], ["wake", "n2", "rem"])
        self.assertEqual(segments[1]["epochs"], 600)

    def test_a_night_without_sleep_reports_no_onset(self) -> None:
        record, rows = build_record(["wake"] * 200)
        result = app._build_ingest_payload(record, rows)["record"]
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(derive_architecture(result["segments"]), (None, 0))
        self.assertEqual(result["total_sleep_minutes"], 0.0)

    def test_a_session_with_nothing_scored_still_produces_a_valid_body(self) -> None:
        record, rows = build_record([None] * 50)
        result = app._build_ingest_payload(record, rows)["record"]
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["total_epochs"], 0)


class IngestCadenceTests(unittest.TestCase):
    """epoch_seconds comes from the Session, never from a hardcoded cadence."""

    def test_ten_second_cadence_is_reported_as_ten(self) -> None:
        record, rows = build_record(["wake"] * 30 + ["n2"] * 1000 + ["rem"] * 300, 10.0)
        result = app._build_ingest_payload(record, rows)["record"]
        self.assertEqual(result["epoch_seconds"], 10)
        self.assertAlmostEqual(
            result["total_epochs"] * 10 / 60.0, result["total_scored_minutes"], delta=0.1)

    def test_a_session_without_a_persisted_cadence_uses_the_configured_one(self) -> None:
        record, rows = build_record(["wake"] * 10 + ["n2"] * 100, 10.0,
                                    persisted_interval_s=None)
        self.assertEqual(app._build_ingest_payload(record, rows)["record"]["epoch_seconds"],
                         int(round(app.SESSION_SAMPLE_SECONDS)))

    def test_sub_second_metadata_cannot_send_a_zero_epoch(self) -> None:
        # A zero would make the backend fall back to 30 s and stretch the
        # hypnogram time base; _normalise_samples_for_report floors at 100 ms.
        record, rows = build_record(["wake"] * 10 + ["n2"] * 100, 0.1)
        self.assertGreaterEqual(
            app._build_ingest_payload(record, rows)["record"]["epoch_seconds"], 1)


class IngestSkipTests(unittest.TestCase):
    """Sessions the account backend could never accept are never queued."""

    def test_a_local_or_offline_login_is_not_uploaded(self) -> None:
        record, rows = build_record(NIGHT, 5.0, zeep_public_id=None)
        self.assertIsNone(app._build_ingest_payload(record, rows))

    def test_an_unconfigured_pod_is_not_uploaded(self) -> None:
        record, rows = build_record(NIGHT, 5.0)
        for name in ("ZEEP_INGEST_API_KEY", "ZEEP_INGEST_DEVICE_ID"):
            original = getattr(app, name)
            setattr(app, name, "")
            try:
                self.assertIsNone(app._build_ingest_payload(record, rows), name)
            finally:
                setattr(app, name, original)

    def test_a_session_without_a_report_is_not_uploaded(self) -> None:
        record, rows = build_record(NIGHT, 5.0)
        record["session_report"] = None
        self.assertIsNone(app._build_ingest_payload(record, rows))


class IngestOutboxTests(unittest.TestCase):
    """A night must survive an unreachable backend, and stop retrying a rejection."""

    def setUp(self) -> None:
        self.record, self.rows = build_record(NIGHT, 5.0)
        self.calls = 0
        self._original = app._zeep_request
        for path in app.INGEST_OUTBOX_DIR.glob("*.json"):
            path.unlink()

    def tearDown(self) -> None:
        app._zeep_request = self._original

    def _respond(self, outcome):
        def handler(*_args, **_kwargs):
            self.calls += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        app._zeep_request = handler

    def _queued(self):
        return sorted(app.INGEST_OUTBOX_DIR.glob("*.json"))

    def _entry(self):
        with self._queued()[0].open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_offline_queues_the_finished_payload_and_keeps_retrying(self) -> None:
        self._respond(app.ZeepApiOffline("ConnectError: no route"))
        app._enqueue_session_ingest(self.record, self.rows)
        self.assertEqual(len(self._queued()), 1)
        entry = self._entry()
        # The marker holds the built payload so a retry never rebuilds it.
        self.assertEqual(entry["payload"]["externalSessionId"], self.record["session_id"])
        self.assertEqual((entry["attempts"], entry["parked"]), (1, False))
        app._sweep_ingest_outbox()
        self.assertEqual(self._entry()["attempts"], 2)

    def test_a_successful_upload_clears_the_queue(self) -> None:
        self._respond(app.ZeepApiOffline("offline"))
        app._enqueue_session_ingest(self.record, self.rows)
        self._respond({"status": "success", "message": "Sleep session ingested",
                       "data": {"id": "uuid-1", "type": "night", "score": 80}})
        app._sweep_ingest_outbox()
        self.assertEqual(self._queued(), [])

    def test_a_rejected_payload_is_parked_instead_of_retried_forever(self) -> None:
        # An unregistered ZEEP_DEVICE_ID answers 404 on every attempt.
        self._respond(app.HTTPException(404, "Device not found"))
        app._enqueue_session_ingest(self.record, self.rows)
        self.assertTrue(self._entry()["parked"])
        before = self.calls
        app._sweep_ingest_outbox()
        self.assertEqual(self.calls, before)

    def test_a_bad_credential_stays_queued_for_an_operator_fix(self) -> None:
        # Verified against the live backend: a wrong x-api-key answers 401.
        # Parking it would mean every night needs unparking by hand after the
        # key is corrected, so it stays queued and flushes on its own.
        for status in (401, 403):
            with self.subTest(status=status):
                for path in app.INGEST_OUTBOX_DIR.glob("*.json"):
                    path.unlink()
                self._respond(app.HTTPException(status, "Invalid API key"))
                app._enqueue_session_ingest(self.record, self.rows)
                self.assertFalse(self._entry()["parked"])

    def test_a_server_error_stays_queued(self) -> None:
        self._respond(app.HTTPException(503, "upstream down"))
        app._enqueue_session_ingest(self.record, self.rows)
        self.assertFalse(self._entry()["parked"])

    def test_an_upload_failure_never_breaks_finalization(self) -> None:
        self._respond(RuntimeError("unexpected"))
        app._enqueue_session_ingest(self.record, self.rows)  # must not raise
        self.assertEqual(len(self._queued()), 1)

    def test_a_session_that_is_not_uploaded_leaves_nothing_queued(self) -> None:
        record, rows = build_record(NIGHT, 5.0, zeep_public_id=None)
        self._respond(app.ZeepApiOffline("offline"))
        app._enqueue_session_ingest(record, rows)
        self.assertEqual(self._queued(), [])
        self.assertEqual(self.calls, 0)


if __name__ == "__main__":
    unittest.main()
