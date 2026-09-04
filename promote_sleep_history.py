#!/usr/bin/env python3
"""Promote a reviewed Raw-BCG replay into derived ZEEP wellness results.

The command replaces only ``sleep_stage``/``sleep_stage_evidence`` events and
the derived final report for completed Sessions at or after the approved pilot
cutover. It never updates Timeline rows or ``bcg.db``. Run without ``--apply``
first; apply requires exact input hashes from ``audit_sleep_history_shadow.py``.
"""

from __future__ import annotations

import argparse
import atexit
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any

from audit_sleep_history_shadow import (
    epoch, private_write_bytes, raw_packet_quality, raw_packets,
)
from personal import BaselineStore
from rescore_session_reports import rescore
from sleep_stage_scoring import align_probabilities_to_emitted_stage
from sleep_signal_features import (
    HR_SANITY_RANGE_BPM,
    RR_SANITY_RANGE_PER_MIN,
    filter_vital_values,
)
from sleep_system_policy import (
    PERSONAL_BASELINE_LEARNING_START_UTC,
    SLEEP_CONFIRMATION_SECONDS,
    SLEEP_CONTEXT_RESET_GAP_SECONDS,
    SLEEP_EVIDENCE_EPOCH_SECONDS,
    SLEEP_EVIDENCE_VERSION,
    SLEEP_ESTIMATOR_VERSION,
    SLEEP_G2_ONTOLOGY_VERSION,
    SLEEP_HISTORY_BACKFILL_VERSION,
    SLEEP_SENSOR_SAMPLE_SECONDS,
    SLEEP_STAGE_CONFIRMATION_SECONDS,
    ZEEP_SLEEP_BASELINE_VERSION,
    ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
)


MAINTENANCE_TOOL_NAME = "promote_sleep_history.py"
# Historical result promotion is intentionally stricter than Admin review.
# Tier B remains visible in the replay artifact, but only Tier A (>=90% paired
# Timeline HR/RR, >=90% paired raw HR/RR and >=95% raw acquisition) may update
# derived wellness events/reports.
ALLOWED_TIERS = {"A"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timeline_sha256(
    path: Path,
    connection: sqlite3.Connection | None = None,
) -> str:
    """Hash every immutable Timeline value in primary-key order."""
    digest = hashlib.sha256()
    own_connection = connection is None
    connection = connection or sqlite3.connect(path)
    try:
        cursor = connection.execute(
            "SELECT id,session_id,timestamp,temperature,humidity,co2,lux,sound,"
            "heart_rate,respiration_rate,bed_status,pm2_5,voc_index "
            "FROM timeline ORDER BY id"
        )
        for row in cursor:
            digest.update(json.dumps(
                list(row), ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8"))
            digest.update(b"\n")
    finally:
        if own_connection:
            connection.close()
    return digest.hexdigest()


def object_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _quality_tier(
    sessions: sqlite3.Connection,
    bcg: sqlite3.Connection,
    session_id: str,
) -> tuple[str, dict[str, float]]:
    """Recompute Tier from immutable DB rows; never trust the artifact label."""
    row = sessions.execute(
        "SELECT start_time,end_time,duration FROM sessions WHERE session_id=?",
        (session_id,),
    ).fetchone()
    if row is None or row[1] is None:
        return "exclude", {}
    timeline = sessions.execute(
        "SELECT heart_rate,respiration_rate FROM timeline WHERE session_id=?",
        (session_id,),
    ).fetchall()
    paired = sum(bool(
        filter_vital_values([item[0]], HR_SANITY_RANGE_BPM)
        and filter_vital_values([item[1]], RR_SANITY_RANGE_PER_MIN)
    ) for item in timeline)
    timeline_ratio = paired / len(timeline) if timeline else 0.0
    packets = raw_packets(bcg, session_id)
    raw = raw_packet_quality(packets, epoch(row[0]), epoch(row[1]))
    tier_a = bool(
        timeline_ratio >= 0.90
        and raw["paired_vital_coverage"] >= 0.90
        and raw["acquisition_coverage"] >= 0.95
        and raw["maximum_packet_gap_s"] < SLEEP_CONTEXT_RESET_GAP_SECONDS
    )
    tier_b = bool(
        timeline_ratio >= 0.80
        and raw["paired_vital_coverage"] >= 0.80
        and raw["acquisition_coverage"] >= 0.80
    )
    return ("A" if tier_a else "B" if tier_b else "exclude"), {
        "timeline_paired_hr_rr": timeline_ratio,
        "raw_paired_hr_rr": raw["paired_vital_coverage"],
        "raw_acquisition": raw["acquisition_coverage"],
        "raw_maximum_gap_s": raw["maximum_packet_gap_s"],
    }


def iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(float(timestamp), timezone.utc).isoformat()


def confidence(evidence: dict[str, Any]) -> str:
    value = float((evidence.get("quality") or {}).get("winner_value") or 0.0)
    return "high" if value >= 0.72 else "medium" if value >= 0.48 else "low"


class _DatabaseReader:
    """Minimal adapter used by BaselineStore during an offline rebuild."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_sessions(self, query: str, params: tuple[Any, ...] = ()):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute(query, params).fetchall()
        finally:
            connection.close()


def _event_values(session: dict[str, Any]) -> list[tuple[str, str, str]]:
    evidence_by_time = {
        round(float(row["t"]), 3): row for row in session.get("evidence_rows") or []
    }
    values: list[tuple[str, str, str]] = []
    for evidence in session.get("evidence_rows") or []:
        when = float(evidence["t"])
        payload = {
            "candidate": evidence.get("candidate"),
            "probabilities": evidence.get("probabilities") or {},
            "confidence": confidence(evidence),
            "reason": "replayed_from_preserved_raw_bcg",
            "metrics": evidence.get("diagnostics") or {},
            "estimator_version": SLEEP_ESTIMATOR_VERSION,
            "evidence_version": SLEEP_EVIDENCE_VERSION,
            "baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
            "transition_policy_version": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "g2_ontology_version": SLEEP_G2_ONTOLOGY_VERSION,
            "window_start": iso_utc(when - 60.0),
            "window_end": iso_utc(when),
            "sample_count": 6,
            "sensor_sample_interval_s": SLEEP_SENSOR_SAMPLE_SECONDS,
            "evidence_epoch_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "confirmation": evidence.get("transition") or {},
            "decision_kind": "historical_physiological_evidence",
            "historical_replay_version": SLEEP_HISTORY_BACKFILL_VERSION,
        }
        values.append((iso_utc(when), "sleep_stage_evidence", json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))))

    previous = None
    progression: list[str] = []
    for state_row in session.get("state_rows") or []:
        when = float(state_row["t"])
        stage = str(state_row["state"])
        evidence = evidence_by_time.get(round(when, 3), {})
        probabilities = align_probabilities_to_emitted_stage(
            evidence.get("probabilities") or {}, stage, winner_margin=0.01,
        )
        changed = stage != previous
        if changed:
            if stage == "wake":
                progression = ["wake"]
            else:
                progression.append(stage)
                progression = progression[-8:]
        payload = {
            "state": stage,
            "probabilities": {key: round(value, 4) for key, value in probabilities.items()},
            "confidence": confidence(evidence),
            "reason": "confirmed_from_preserved_raw_bcg_replay",
            "progression": progression,
            "metrics": state_row.get("metrics") or {},
            "estimator_version": SLEEP_ESTIMATOR_VERSION,
            "evidence_version": SLEEP_EVIDENCE_VERSION,
            "baseline_version": ZEEP_SLEEP_BASELINE_VERSION,
            "transition_policy_version": ZEEP_SLEEP_TRANSITION_POLICY_VERSION,
            "g2_ontology_version": SLEEP_G2_ONTOLOGY_VERSION,
            "window_start": iso_utc(when - 60.0),
            "window_end": iso_utc(when),
            "sample_count": 6,
            "sensor_sample_interval_s": SLEEP_SENSOR_SAMPLE_SECONDS,
            "sample_interval_s": SLEEP_EVIDENCE_EPOCH_SECONDS,
            "confirmation_seconds": SLEEP_STAGE_CONFIRMATION_SECONDS.get(
                stage, SLEEP_CONFIRMATION_SECONDS),
            "confirmation": evidence.get("transition") or {},
            "decision_kind": "historical_confirmed_state",
            "state_changed": changed,
            "historical_replay_version": SLEEP_HISTORY_BACKFILL_VERSION,
            "raw_source_modified": False,
        }
        values.append((iso_utc(when), "sleep_stage", json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))))
        previous = stage
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument(
        "--summary-manifest", type=Path,
        help="Summary manifest that cryptographically pins the details artifact",
    )
    parser.add_argument(
        "--offline-confirmed", action="store_true",
        help="Operator confirms the Pod service/writers are stopped",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
    if args.apply and not args.offline_confirmed:
        raise SystemExit("--apply requires --offline-confirmed after stopping the Pod service")
    summary_manifest = None
    summary_manifest_sha256 = None
    if args.summary_manifest:
        summary_manifest_sha256 = file_sha256(args.summary_manifest)
        summary_manifest = json.loads(args.summary_manifest.read_text(encoding="utf-8"))
        if summary_manifest.get("promotion_details_sha256") != file_sha256(args.artifact):
            raise SystemExit("details artifact SHA does not match the reviewed summary manifest")
        for key in ("analysis_run_id", "promotion_payload_sha256"):
            if summary_manifest.get(key) != artifact.get(key):
                raise SystemExit(f"details artifact {key} does not match summary manifest")
    elif args.apply:
        raise SystemExit("--apply requires --summary-manifest")
    if artifact.get("promotion_payload_sha256") != object_sha256(
        artifact.get("sessions") or {}
    ):
        raise SystemExit("details artifact promotion payload hash is invalid")
    sessions_db = args.data_dir / "sessions.db"
    bcg_db = args.data_dir / "bcg.db"
    session_guard = sqlite3.connect(sessions_db, timeout=2)
    bcg_guard = sqlite3.connect(bcg_db, timeout=2)
    session_guard.row_factory = sqlite3.Row
    bcg_guard.row_factory = sqlite3.Row

    def close_guards() -> None:
        for connection in (session_guard, bcg_guard):
            try:
                connection.rollback()
            except sqlite3.Error:
                pass
            try:
                connection.close()
            except sqlite3.Error:
                pass

    atexit.register(close_guards)
    if args.apply:
        # The operator stops the service first. SQLite then proves there is no
        # remaining writer, checkpoints both WALs, and holds exclusive locks
        # through the atomic swap so a stale sidecar cannot split generations.
        for label, connection in (
            ("sessions.db", session_guard), ("bcg.db", bcg_guard),
        ):
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and int(checkpoint[0]) != 0:
                raise SystemExit(f"{label} WAL is busy; a writer is still active")
            connection.execute("PRAGMA locking_mode=EXCLUSIVE")
            try:
                connection.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as exc:
                raise SystemExit(f"{label} cannot obtain exclusive lock: {exc}") from exc
    expected = artifact.get("input_sha256") or {}
    actual = {"sessions_db": file_sha256(sessions_db), "bcg_db": file_sha256(bcg_db)}
    if expected.get("sessions_db") != actual["sessions_db"]:
        raise SystemExit("sessions.db changed after replay; create a fresh artifact")
    if expected.get("bcg_db") != actual["bcg_db"]:
        raise SystemExit("bcg.db changed after replay; create a fresh artifact")
    profiles_path = args.data_dir / "profiles.json"
    if expected.get("profiles_file"):
        if not profiles_path.exists():
            raise SystemExit("profiles.json missing after replay; create a fresh artifact")
        actual["profiles_file"] = file_sha256(profiles_path)
        if expected["profiles_file"] != actual["profiles_file"]:
            raise SystemExit("profiles.json changed after replay; create a fresh artifact")
    source_hashes = ((artifact.get("code_provenance") or {}).get("source_sha256") or {})
    source_root = Path(__file__).resolve().parent
    for source_name, expected_hash in source_hashes.items():
        source_path = source_root / source_name
        if not source_path.exists() or file_sha256(source_path) != expected_hash:
            raise SystemExit(
                f"replay source changed after audit ({source_name}); create a fresh artifact"
            )
    if (artifact.get("cohort") or {}).get("start_utc_inclusive") != PERSONAL_BASELINE_LEARNING_START_UTC:
        raise SystemExit("artifact cutover does not match current policy")
    versions = artifact.get("versions") or {}
    if versions.get("replay") != SLEEP_HISTORY_BACKFILL_VERSION:
        raise SystemExit("artifact replay version does not match current policy")
    if versions.get("estimator") != SLEEP_ESTIMATOR_VERSION:
        raise SystemExit("artifact estimator version does not match current policy")
    acceptance = artifact.get("acceptance") or {}
    if acceptance.get("wellness_derived_promotion_decision") != "PASS_WITH_LIMITATIONS":
        raise SystemExit("artifact is not approved for wellness-derived promotion")

    artifact_sessions = artifact.get("sessions") or {}
    if not isinstance(artifact_sessions, dict):
        raise SystemExit("promotion requires the replay details artifact, not the summary")
    selected = []
    for session_id, item in artifact_sessions.items():
        if item.get("quality_tier") not in ALLOWED_TIERS:
            continue
        if item.get("manual_review_flags"):
            continue
        if not (item.get("state_rows") or item.get("evidence_rows")):
            continue
        db_row = session_guard.execute(
            "SELECT username_key,start_time,end_time,duration FROM sessions "
            "WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if (
            db_row is None
            or db_row[2] is None
            or str(db_row[1]) < PERSONAL_BASELINE_LEARNING_START_UTC
            or float(db_row[3] or 0.0) <= 25 * 60.0
        ):
            raise SystemExit(f"artifact selected ineligible Session: {session_id}")
        identity = {
            "email": db_row[0], "start_time": db_row[1],
            "end_time": db_row[2], "duration": db_row[3],
        }
        mismatched_identity = {
            key: {"artifact": item.get(key), "database": value}
            for key, value in identity.items() if item.get(key) != value
        }
        if mismatched_identity:
            raise SystemExit(
                f"artifact/DB Session identity mismatch for {session_id}: "
                f"{mismatched_identity}"
            )
        recomputed_tier, tier_evidence = _quality_tier(
            session_guard, bcg_guard, session_id,
        )
        if recomputed_tier != "A" or item.get("quality_tier") != recomputed_tier:
            raise SystemExit(
                f"recomputed quality tier is not A for {session_id}: "
                f"{recomputed_tier} {tier_evidence}"
            )
        selected.append((session_id, item, _event_values(item)))

    selected_ids = [item[0] for item in selected]
    reviewed_ids = (
        ((summary_manifest or {}).get("acceptance") or {}).get(
            "wellness_derived_promotion_eligible_session_ids"
        )
        if summary_manifest else
        (acceptance.get("wellness_derived_promotion_eligible_session_ids") or [])
    )
    if sorted(selected_ids) != sorted(reviewed_ids or []):
        raise SystemExit(
            "selected Session allowlist does not match reviewed summary manifest"
        )

    timeline_before = timeline_sha256(sessions_db, session_guard)
    preview = {
        "applied": False,
        "analysis_run_id": artifact.get("analysis_run_id"),
        "cutover_utc": PERSONAL_BASELINE_LEARNING_START_UTC,
        "selected_sessions": len(selected),
        "selected_ids": selected_ids,
        "derived_events": sum(len(item[2]) for item in selected),
        "raw_timeline_modified": False,
        "raw_bcg_modified": False,
        "raw_timeline_sha256_before": timeline_before,
    }
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    backup_dir = args.data_dir.parent / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"sessions-pre-wellness-replay-{stamp}.db"
    # WAL has been checkpointed and an exclusive read transaction now freezes
    # the main DB file, so this filesystem copy is a consistent rollback image.
    shutil.copy2(sessions_db, backup_path)
    baseline_path = args.data_dir / "baselines.json"
    baseline_backup = None
    if baseline_path.exists():
        baseline_backup = backup_dir / f"baselines-pre-wellness-replay-{stamp}.json"
        shutil.copy2(baseline_path, baseline_backup)

    def restore_live_from_backup() -> None:
        """Restore derived DB/baseline if install or final audit persistence fails."""
        session_guard.rollback()
        restore_source = sqlite3.connect(backup_path)
        try:
            restore_source.backup(session_guard)
        finally:
            restore_source.close()
        if baseline_backup is not None:
            shutil.copy2(baseline_backup, baseline_path)
        elif baseline_path.exists():
            baseline_path.unlink()

    staging_dir = Path(tempfile.mkdtemp(
        prefix=f".wellness-replay-stage-{stamp}-",
        dir=args.data_dir.parent,
    ))
    staged_sessions_db = staging_dir / "sessions.db"
    staged_baseline_path = staging_dir / "baselines.json"
    shutil.copy2(backup_path, staged_sessions_db)
    if baseline_path.exists():
        shutil.copy2(baseline_path, staged_baseline_path)

    # All derived changes are built and checked on a private staging copy.
    # The live database is replaced only after reports, baselines, integrity
    # and immutable-Raw hashes have all passed.
    connection = sqlite3.connect(staged_sessions_db, timeout=30)
    connection.execute("PRAGMA busy_timeout=30000")
    now = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        for session_id, item, events in selected:
            row = connection.execute(
                "SELECT start_time,end_time FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if not row or row[1] is None or str(row[0]) < PERSONAL_BASELINE_LEARNING_START_UTC:
                raise RuntimeError(f"ineligible Session: {session_id}")
            old_counts = dict(connection.execute(
                "SELECT type,COUNT(*) FROM events WHERE session_id=? "
                "AND type IN ('sleep_stage','sleep_stage_evidence') GROUP BY type",
                (session_id,),
            ).fetchall())
            connection.execute(
                "DELETE FROM events WHERE session_id=? "
                "AND type IN ('sleep_stage','sleep_stage_evidence')",
                (session_id,),
            )
            connection.executemany(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                [(session_id, timestamp, kind, value) for timestamp, kind, value in events],
            )
            audit = {
                "analysis_run_id": artifact.get("analysis_run_id"),
                "version": SLEEP_HISTORY_BACKFILL_VERSION,
                "promoted_at_utc": now,
                "quality_tier": item.get("quality_tier"),
                "old_derived_event_counts": old_counts,
                "new_derived_event_count": len(events),
                "raw_timeline_modified": False,
                "raw_bcg_modified": False,
            }
            connection.execute(
                "INSERT INTO events(session_id,timestamp,type,value) VALUES (?,?,?,?)",
                (session_id, now, "sleep_history_reprocessed", json.dumps(
                    audit, ensure_ascii=False, separators=(",", ":"))),
            )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check failed: {integrity}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    try:
        report_sessions = []
        for session_id, item, _ in selected:
            reviewed_mode = str((item.get("mode") or {}).get("group") or "")
            if reviewed_mode not in {"sleep", "nap_recovery"}:
                raise RuntimeError(f"invalid reviewed Mode for {session_id}")
            one_result = rescore(
                staging_dir, [session_id], requested_mode=reviewed_mode, apply=True,
            )
            report_sessions.extend(one_result.get("sessions") or [])
        report_result = {
            "applied": True,
            "sessions": report_sessions,
            "count": len(report_sessions),
        }
        # The promoted DB must reproduce the reviewed shadow artifact exactly
        # for score identity and stage-time accounting.  This guard catches
        # cadence regressions (for example treating a 30-second state as a
        # 10-second Sensor sample) before the live database is replaced.
        reviewed = {session_id: item for session_id, item, _ in selected}
        parity = []
        for rebuilt in report_result.get("sessions") or []:
            session_id = rebuilt["session_id"]
            expected_item = reviewed[session_id]
            expected_quality = expected_item.get("quality") or {}
            expected_report = expected_item.get("report") or {}
            expected_counts = Counter(
                str(row.get("state")) for row in expected_item.get("state_rows") or []
            )
            checks = {
                "quality": (expected_quality, rebuilt.get("quality") or {}),
                "report": (expected_report, rebuilt.get("report") or {}),
                "rest_mode": (
                    expected_item.get("mode") or {}, rebuilt.get("rest_mode") or {},
                ),
                "state_counts": (
                    {stage: int(expected_counts.get(stage, 0))
                     for stage in ("wake", "n1", "n2", "n3", "rem")},
                    rebuilt.get("counts") or {},
                ),
            }
            failures = {
                key: {"reviewed": pair[0], "rebuilt": pair[1]}
                for key, pair in checks.items()
                if pair[0] != pair[1]
            }
            if failures:
                raise RuntimeError(
                    f"reviewed/rebuilt report mismatch for {session_id}: {failures}"
                )
            parity.append({
                "session_id": session_id,
                "status": "exact_full_quality_mode_counts_report",
            })

        # Rebuild learned context only from current-version reports at/after
        # the cutover. Historical Raw Sensor/BCG files are not involved.
        reader = _DatabaseReader(staged_sessions_db)
        store = BaselineStore(reader, staging_dir)
        store.data = {}
        connection = sqlite3.connect(staged_sessions_db)
        emails = [row[0] for row in connection.execute(
            "SELECT DISTINCT username_key FROM sessions WHERE end_time IS NOT NULL "
            "AND start_time>=? ORDER BY username_key",
            (PERSONAL_BASELINE_LEARNING_START_UTC,),
        )]
        connection.close()
        for email in emails:
            store.update_user(email)

        check = sqlite3.connect(staged_sessions_db)
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if integrity != "ok":
            raise RuntimeError(f"staged integrity_check failed: {integrity}")
        timeline_after = timeline_sha256(staged_sessions_db)
        bcg_after = file_sha256(bcg_db)
        if timeline_after != timeline_before:
            raise RuntimeError("immutable timeline changed during derived promotion")
        if bcg_after != actual["bcg_db"]:
            raise RuntimeError("immutable raw BCG changed during derived promotion")

        # Install through SQLite's online-backup API rather than replacing the
        # main DB inode. This keeps WAL/SHM generation coherent. The service is
        # already offline and the guard proved no writer survived checkpoint.
        try:
            session_guard.rollback()
            staged_source = sqlite3.connect(staged_sessions_db)
            try:
                staged_source.backup(session_guard)
            finally:
                staged_source.close()
            if staged_baseline_path.exists():
                os.replace(staged_baseline_path, baseline_path)
        except Exception:
            restore_live_from_backup()
            raise
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)

    # Verify the installed copy too. If any post-install invariant fails,
    # restore the rollback image before returning an error; the backup remains
    # available for a second, operator-led verification as well.
    try:
        if session_guard.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("installed sessions.db integrity_check failed")
        if timeline_sha256(sessions_db, session_guard) != timeline_before:
            raise RuntimeError("immutable timeline changed after derived promotion")
        if file_sha256(bcg_db) != actual["bcg_db"]:
            raise RuntimeError("immutable raw BCG changed after derived promotion")
    except Exception:
        restore_live_from_backup()
        raise

    result = {
        **preview,
        "applied": True,
        "sessions_backup": str(backup_path),
        "baselines_backup": str(baseline_backup) if baseline_backup else None,
        "report_rescore": report_result,
        "reviewed_report_parity": parity,
        "baselines_rebuilt": len(emails),
        "sessions_integrity_check": "ok",
        "raw_timeline_sha256_after": timeline_after,
        "raw_bcg_sha256_before": actual["bcg_db"],
        "raw_bcg_sha256_after": bcg_after,
        "reviewed_artifacts": {
            "summary_manifest_sha256": summary_manifest_sha256,
            "details_artifact_sha256": file_sha256(args.artifact),
            "promotion_payload_sha256": artifact.get("promotion_payload_sha256"),
            "input_sha256": expected,
            "code_provenance": artifact.get("code_provenance") or {},
        },
    }
    manifest_path = args.data_dir / "wellness-history-promotion-latest.json"
    try:
        private_write_bytes(
            manifest_path,
            json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    except Exception:
        restore_live_from_backup()
        raise
    close_guards()
    atexit.unregister(close_guards)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
