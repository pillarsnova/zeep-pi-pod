"""Resume waiting/recording Sessions without changing sleep or score policy."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pod_occupancy import CoordinatorUnavailable, OccupancyConflict
from sessions.cadence import sample_interval_seconds
from sessions.lifecycle import service_resume_event
from sessions.live_projection import SessionPublicIdentity, active_session_projection
from sessions.restart_contracts import RestartPolicy, RestartPorts
from sessions.restart_timeline import RestartTimeline, restore_timeline


class SessionRestarter:
    """Coordinate existing checkpoint/DB recovery through injected runtime ports."""

    def __init__(self, ports: RestartPorts, policy: RestartPolicy) -> None:
        self.ports = ports
        self.policy = policy

    def restore(self) -> str | None:
        """Resume the latest open Session, including legacy server-shutdown rows."""
        checkpoint, row = self._select_candidate()
        if checkpoint is not None and row is None:
            return self.restore_waiting(checkpoint)
        if row is None:
            return None
        return self._restore_recording(row, checkpoint)

    def _select_candidate(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        p = self.ports
        checkpoint = p.load_checkpoint()
        if checkpoint is not None:
            record = checkpoint["record"]
            rows = p.read_sessions(
                "SELECT * FROM sessions WHERE session_id=? LIMIT 1",
                (record["session_id"],),
            )
            row = rows[0] if rows else None
            explicitly_ended = bool(
                row
                and row.get("end_time") is not None
                and row.get("end_reason") != "server_shutdown"
            )
            if explicitly_ended:
                # A crash between final commit and checkpoint unlink cannot
                # reopen a Session explicitly completed by its User/Admin.
                p.clear_checkpoint()
                p.log_event(
                    "session",
                    "stale_restart_checkpoint_removed",
                    session_id=record["session_id"],
                    end_reason=row.get("end_reason"),
                )
                checkpoint = None
            elif checkpoint.get("phase") == "waiting_bed" and row is None:
                return checkpoint, None
            elif row is not None:
                # DB start may commit just before a waiting checkpoint updates.
                checkpoint["phase"] = "recording"
                record["started_at_utc"] = row["start_time"]
                return checkpoint, row
            else:
                p.clear_checkpoint()
                checkpoint = None
        rows = p.read_sessions(
            """SELECT * FROM sessions
               WHERE end_time IS NULL OR end_reason='server_shutdown'
               ORDER BY start_time DESC LIMIT 1"""
        )
        return checkpoint, rows[0] if rows else None

    def restore_waiting(self, checkpoint: dict[str, Any]) -> str | None:
        """Restore Login ownership, rechecking the full fresh Bed/HR/RR gate."""
        p = self.ports
        safety = p.restore_safety(checkpoint)
        record = dict(checkpoint["record"])
        session_id = record["session_id"]
        with p.profile_lock:
            profile = p.load_profiles().get(record["username_key"], {})
        record.update(self._profile_fields(record, profile))
        mode = record.get("rest_mode") or "auto"
        target = p.resolve_target(mode, record.get("target_duration_s"))
        record["display_name"] = (
            record.get("display_name")
            or profile.get("display_name")
            or record["username"]
        )
        baseline = p.rest_baseline(record["username_key"], mode, target.get("seconds"))
        auth_source = record.get("auth_source") or (
            "zeep" if record.get("zeep_public_id") else "local"
        )
        lease, error = self._acquire_lease(
            record["identity_subject"],
            record.get("pod_id"),
            session_id,
            record["username"],
        )
        record.update(
            {
                "rest_mode": mode,
                "target_duration_s": target.get("seconds"),
                "sample_interval_s": sample_interval_seconds(
                    record.get("sample_interval_s"), self.policy.sample_interval_s
                ),
                "started_at_utc": None,
                "started_monotonic": None,
            }
        )
        with p.state_lock:
            packets = int(p.state["sensor"]["bcg"].get("packets") or 0)
        active = {
            "record": record,
            "auth": None,
            "owner_auth_session_id": checkpoint.get("owner_auth_session_id"),
            "occupancy_lease": lease,
            "occupancy_error": error,
            "last_lease_renew": p.monotonic(),
            "samples": [],
            "counters": {},
            "last_sample": float("-inf"),
            "phase": "waiting_bed",
            "safety_context": safety,
            "onbed_since": None,
            "vital_gate_start_packet_count": packets,
        }
        with p.session_lock:
            if p.get_active() is not None:
                return None
            p.set_active(active)
        p.reset_inference(session_id)
        self._refresh_checkpoint(active)
        armed_at = record.get("armed_at_utc")
        try:
            armed_epoch = (
                datetime.fromisoformat(armed_at).timestamp() if armed_at else p.clock()
            )
        except (TypeError, ValueError):
            armed_epoch = p.clock()
        self._publish(
            active,
            profile,
            auth_source=auth_source,
            started_at=armed_epoch,
            vital_gate=p.vital_gate(active),
            baseline=baseline,
        )
        p.log_event(
            "session",
            "login_restored_after_restart",
            session_id=session_id,
            user=record["username"],
            phase="waiting_bed",
            owner_login_restored=bool(checkpoint.get("owner_auth_session_id")),
            occupancy_error=error,
        )
        return session_id

    def _restore_recording(
        self, row: dict[str, Any], checkpoint: dict[str, Any] | None
    ) -> str:
        p = self.ports
        session_id = row["session_id"]
        checkpoint_record = checkpoint["record"] if checkpoint is not None else {}
        timeline, counters, sleep_context = self._restore_evidence(row, checkpoint)
        started_dt = datetime.fromisoformat(row["start_time"])
        elapsed_s = max(0.0, p.clock() - started_dt.timestamp())
        with p.profile_lock:
            profile = p.load_profiles().get(row["username_key"], {})
            health = self._profile_fields(checkpoint_record, profile)
        record = self._recording_record(row, checkpoint_record, profile, health)
        baseline = p.rest_baseline(
            row["username_key"], record["rest_mode"], record["target_duration_s"]
        )
        lease, error = self._acquire_lease(
            record["identity_subject"], row.get("pod_id"), session_id, row["user"]
        )
        safety = (
            p.restore_safety(checkpoint)
            if checkpoint is not None
            else p.current_safety()
        )
        record.update(
            {
                "started_monotonic": p.monotonic() - elapsed_s,
                "sample_interval_s": self.policy.sample_interval_s,
                "sample_cadence_segments": timeline.cadence_segments,
            }
        )
        active = {
            "record": record,
            "auth": None,
            "owner_auth_session_id": checkpoint.get("owner_auth_session_id")
            if checkpoint is not None
            else None,
            "occupancy_lease": lease,
            "occupancy_error": error,
            "last_lease_renew": p.monotonic(),
            "samples": timeline.samples,
            "counters": counters,
            "last_sample": float("-inf"),
            "phase": "recording",
            "onbed_since": None,
            "safety_context": safety,
        }
        p.set_active(active)
        legacy_closed = row.get("end_reason") == "server_shutdown"
        if legacy_closed:
            self._reopen_legacy(row)
        p.start_bcg(session_id)
        self._publish(
            active,
            profile,
            auth_source=record["auth_source"],
            started_at=started_dt.timestamp(),
            baseline=baseline,
            vital_gate={
                "ready": True,
                "heart_rate_valid": None,
                "respiration_rate_valid": None,
                "confirmed_packets": self.policy.required_packets,
                "required_packets": self.policy.required_packets,
                "reason": "recording_resumed",
            },
        )
        p.enqueue(
            "sessions",
            "event",
            service_resume_event(session_id, timeline.resumed_at_utc),
        )
        p.log_event(
            "session",
            "resumed_after_restart",
            session_id=session_id,
            user=row["user"],
            samples=len(timeline.samples),
            legacy_closed=legacy_closed,
            owner_login_restored=bool(
                checkpoint and checkpoint.get("owner_auth_session_id")
            ),
            occupancy_error=error,
            sleep_context=sleep_context,
        )
        self._log_cadence(session_id, timeline)
        self._refresh_checkpoint(active)
        return session_id

    def _restore_evidence(
        self, row: dict[str, Any], checkpoint: dict[str, Any] | None
    ) -> tuple[RestartTimeline, dict[str, int], dict[str, Any]]:
        p = self.ports
        session_id = row["session_id"]
        rows = p.read_sessions(
            """SELECT * FROM timeline WHERE session_id=? ORDER BY timestamp
               LIMIT ?""",
            (session_id, self.policy.sample_limit),
        )
        timeline = restore_timeline(
            rows,
            checkpoint["record"] if checkpoint is not None else {},
            start_at_utc=row["start_time"],
            resumed_at_utc=p.utc_now().isoformat(),
            live_interval_s=self.policy.sample_interval_s,
        )
        events = p.read_sessions(
            "SELECT type,COUNT(*) AS n FROM events WHERE session_id=? "
            "AND type!='final_summary' GROUP BY type",
            (session_id,),
        )
        counters = {event["type"]: int(event["n"]) for event in events}
        restored = p.restore_sleep_context(
            p.read_sessions,
            session_id,
            samples=timeline.samples,
            checkpoint_context=checkpoint.get("sleep_context")
            if isinstance(checkpoint, dict)
            else None,
            heart_rate_range=self.policy.heart_rate_range,
            respiration_rate_range=self.policy.respiration_rate_range,
            fallback_interval_s=self.policy.evidence_interval_s,
        )
        with p.sleep_path_lock:
            p.reset_sleep_path(session_id)
            p.sleep_path.update(restored["path"])
        return timeline, counters, restored["provenance"]

    def _recording_record(
        self,
        row: dict[str, Any],
        checkpoint: dict[str, Any],
        profile: dict[str, Any],
        health: dict[str, Any],
    ) -> dict[str, Any]:
        subject = (
            checkpoint.get("identity_subject")
            or row.get("identity_subject")
            or (
                f"zeep:{row['zeep_public_id']}"
                if row.get("zeep_public_id")
                else f"legacy:{row['username_key']}"
            )
        )
        # Elapsed time and model output cannot invent an old Session's intent.
        mode = checkpoint.get("rest_mode") or row.get("rest_mode") or "auto"
        persisted_target = checkpoint.get("target_duration_s")
        if persisted_target is None:
            persisted_target = row.get("target_duration_s")
        target = self.ports.resolve_target(mode, persisted_target)
        return {
            "session_id": row["session_id"],
            "username": row["user"],
            "username_key": row["username_key"],
            "gender": row.get("gender"),
            **health,
            "display_name": checkpoint.get("display_name")
            or profile.get("display_name")
            or row["user"],
            "wellness_context": checkpoint.get("wellness_context"),
            "armed_at_utc": checkpoint.get("armed_at_utc") or row["created_at"],
            "rest_mode": mode,
            "target_duration_s": target.get("seconds"),
            "auth_source": checkpoint.get("auth_source")
            or ("zeep" if row.get("zeep_public_id") else "local"),
            "started_at_utc": row["start_time"],
            "identity_subject": subject,
            "pod_id": row.get("pod_id") or self.policy.pod_id,
            "zeep_public_id": row.get("zeep_public_id"),
        }

    def _profile_fields(
        self, record: dict[str, Any], profile: dict[str, Any]
    ) -> dict[str, Any]:
        age = record.get("age") if record.get("age") is not None else profile.get("age")
        group = (
            record.get("age_group")
            or profile.get("age_group")
            or self.ports.age_group(age)
        )
        health = record.get("health_reference")
        if not isinstance(health, dict) or health.get("schema_version") != 1:
            health = self.ports.health_reference(profile)
        return {"age": age, "age_group": group, "health_reference": health}

    def _acquire_lease(
        self, subject: str, pod_id: str | None, session_id: str, username: str
    ) -> tuple[Any, str | None]:
        try:
            return self.ports.acquire_lease(
                subject=subject,
                pod_id=pod_id or self.policy.pod_id,
                pod_session_id=session_id,
                username=username,
            ), None
        except (CoordinatorUnavailable, OccupancyConflict) as exc:
            # Restart is occupant-first: a coordinator outage must not evict
            # the authenticated occupant or stop local monitoring/recording.
            return None, getattr(exc, "reason", None) or str(exc)

    def _reopen_legacy(self, row: dict[str, Any]) -> None:
        p = self.ports
        p.enqueue("sessions", "session_resume", {"session_id": row["session_id"]})
        if not p.flush(30):
            raise RuntimeError("database writer did not flush session resume")
        availability = p.availability(
            p.read_sessions, self.policy.baseline_start_utc
        ).get(row["username_key"], {})
        with p.profile_lock:
            profiles = p.load_profiles()
            profile = profiles.get(row["username_key"])
            if profile is not None:
                profile["sessions"] = int(availability.get("lifetime_sessions") or 0)
                profile["last_session_utc"] = availability.get("last_data_session_utc")
                p.save_profiles(profiles)

    def _publish(
        self,
        active: dict[str, Any],
        profile: dict[str, Any],
        *,
        auth_source: str,
        started_at: float,
        vital_gate: dict[str, Any],
        baseline: Any,
    ) -> None:
        p = self.ports
        record = active["record"]
        with p.state_lock:
            p.replace_projection(
                active_session_projection(
                    SessionPublicIdentity(
                        username=record["username"],
                        account_key=record["username_key"],
                        email=profile.get("email") or profile.get("zeep_email"),
                        display_name=record["display_name"],
                        auth_source=auth_source,
                        gender=record.get("gender"),
                        age=record["age"],
                        age_group=record["age_group"],
                        health_reference=record["health_reference"],
                    ),
                    session_id=record["session_id"],
                    rest_mode=record["rest_mode"],
                    target_duration_s=record["target_duration_s"],
                    started_at=started_at,
                    samples=len(active["samples"]),
                    recording=active["phase"] == "recording",
                    vital_gate=vital_gate,
                    wellness_context_available=bool(record.get("wellness_context")),
                    personal_rest_baseline=baseline,
                )
            )

    def _log_cadence(self, session_id: str, timeline: RestartTimeline) -> None:
        if timeline.upgraded:
            self.ports.log_event(
                "session",
                "sample_cadence_upgraded",
                session_id=session_id,
                previous_sample_interval_s=timeline.previous_interval_s,
                sample_interval_s=self.policy.sample_interval_s,
                historical_samples=len(timeline.samples),
                effective_at_utc=timeline.resumed_at_utc,
            )

    def _refresh_checkpoint(self, active: dict[str, Any]) -> None:
        try:
            self.ports.save_checkpoint(active)
        except Exception as exc:
            self.ports.log_event(
                "session", "restart_checkpoint_refresh_failed", error=str(exc)
            )
