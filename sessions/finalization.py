"""Ordered live Session closure; storage commit remains a separate boundary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pod_occupancy import CoordinatorUnavailable, OccupancyConflict
from sessions.cadence import sample_interval_seconds
from sessions.finalization_contracts import FinalizationPolicy, SessionFinalizationPorts
from sessions.finalization_report import build_recorded_report, prepare_record
from sessions.live_projection import inactive_session_projection


class SessionFinalizer:
    """Close one Session under the caller's existing lifecycle lock."""

    def __init__(
        self, ports: SessionFinalizationPorts, policy: FinalizationPolicy
    ) -> None:
        self.ports = ports
        self.policy = policy

    def finalize(self, reason: str = "logout") -> dict[str, Any] | None:
        """Persist before remote cleanup, share publication and baseline learning."""
        ports = self.ports
        with ports.session_lock:
            active = ports.get_active()
            ports.set_active(None)
        if active is None:
            return None
        record = active["record"]
        ports.reserve_share(
            record.get("identity_subject"), account_key=record.get("username_key")
        )
        interval_s = sample_interval_seconds(
            record.get("sample_interval_s"), self.policy.sample_interval_s
        )
        ended_at = ports.utc_now().isoformat()
        # Keep this origin until durable close succeeds, so retries never
        # become synthetic zero-duration / non-recorded Sessions.
        started = record.get("started_monotonic")
        duration = 0.0 if started is None else max(0.0, ports.monotonic() - started)
        start_epoch = (
            self._start_epoch(record, duration) if started is not None else None
        )
        self._flush_before_projection(active)
        stage_events = ports.read_sessions(
            "SELECT timestamp,value FROM events WHERE session_id=? AND type='sleep_stage' ORDER BY timestamp",
            (record["session_id"],),
        )
        status_events = ports.read_sessions(
            "SELECT timestamp,value FROM events WHERE session_id=? AND type='sleep_stage_status' ORDER BY timestamp",
            (record["session_id"],),
        )
        if started is None:
            return self._close_waiting(active, reason, ended_at)
        projection = self._project(
            active, start_epoch, duration, interval_s, stage_events, status_events
        )
        terminal_wake = prepare_record(
            active,
            projection,
            reason=reason,
            ended_at_utc=ended_at,
            duration=duration,
            acquisition_interval_s=interval_s,
            ports=ports,
            policy=self.policy,
        )
        self._drain_bcg(active)
        final_summary = build_recorded_report(
            record,
            projection,
            duration=duration,
            acquisition_interval_s=interval_s,
            terminal_wake=terminal_wake,
            ports=ports,
            policy=self.policy,
        )
        ports.commit(active, final_summary, terminal_wake)
        self._after_commit(active, projection["report_samples"], reason)
        return record

    def _start_epoch(self, record: dict[str, Any], duration: float) -> float:
        try:
            return datetime.fromisoformat(str(record.get("started_at_utc"))).timestamp()
        except (TypeError, ValueError):
            return self.ports.clock() - duration

    def _restore_ownership(self, active: dict[str, Any]) -> None:
        with self.ports.session_lock:
            if self.ports.get_active() is None:
                self.ports.set_active(active)
        self.ports.discard_share(active["record"].get("identity_subject"))

    def _flush_before_projection(self, active: dict[str, Any]) -> None:
        ports = self.ports
        # Durable right-closed evidence must be visible before sample counting;
        # forward-looking Dashboard snapshots cannot stand in for these rows.
        if ports.flush(30):
            return
        self._restore_ownership(active)
        writer_error = ports.writer_health().get("last_error")
        ports.log_event(
            "session",
            "sleep_attribution_projection_deferred",
            session_id=active["record"]["session_id"],
            reason="database_writer_error"
            if writer_error
            else "database_flush_timeout",
            error=writer_error,
        )
        raise ports.flush_failure("before Sleep attribution projection")

    def _project(
        self,
        active: dict[str, Any],
        start_epoch: float,
        duration: float,
        interval_s: float,
        stage_events: list[dict[str, Any]],
        status_events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        projection = self.ports.project_samples(
            active["samples"],
            start_at=start_epoch,
            end_at=float(start_epoch) + duration,
            cadence_segments=active["record"].get("sample_cadence_segments") or [],
            sensor_interval_s=interval_s,
            decision_interval_s=self.policy.evidence_interval_s,
            stage_events=stage_events,
            status_events=status_events,
            heart_rate_range=self.policy.heart_rate_range,
            respiration_rate_range=self.policy.respiration_rate_range,
        )
        if not projection["grid_summary"]["classification_complete"]:
            self._restore_ownership(active)
            raise RuntimeError(
                "report continuity invariant failed: unattributed recording time"
            )
        return projection

    def _drain_bcg(self, active: dict[str, Any]) -> None:
        try:
            self.ports.end_bcg(active["record"]["session_id"])
            if not self.ports.flush(30):
                raise self.ports.flush_failure("final BCG epoch")
        except Exception:
            self.ports.recover_active(active)
            raise

    def _close_waiting(
        self, active: dict[str, Any], reason: str, ended_at: str
    ) -> dict[str, Any]:
        # Login/occupancy alone never creates a report, timeline or baseline.
        ports = self.ports
        record = active["record"]
        gate = ports.vital_gate(active)
        record.update(
            {
                "ended_at_utc": ended_at,
                "end_reason": "not_recorded"
                if reason == "logout"
                else f"{reason}_not_recorded",
                "duration_s": 0.0,
                "samples": [],
                "recording_started": False,
                "start_gate": gate,
            }
        )
        ports.clear_checkpoint()
        ports.log_event(
            "session",
            "closed_without_recording",
            session_id=record["session_id"],
            user=record["username"],
            reason=record["end_reason"],
            gate_reason=gate["reason"],
        )
        self._release_lease(active, log_success=False)
        ports.logout_account(active)
        self._publish_idle()
        ports.discard_share(record.get("identity_subject"))
        return record

    def _release_lease(self, active: dict[str, Any], *, log_success: bool) -> None:
        lease = active.get("occupancy_lease")
        if lease is None:
            return
        ports = self.ports
        session_id = active["record"]["session_id"]
        try:
            ports.release_lease(lease)
            if log_success:
                ports.log_event(
                    "occupancy",
                    "lease_released",
                    session_id=session_id,
                    pod_id=self.policy.pod_id,
                )
        except (CoordinatorUnavailable, OccupancyConflict) as exc:
            # The lease expires automatically; coordinator failure cannot undo
            # a durable result or prevent a local exit.
            ports.log_event(
                "occupancy",
                "lease_release_deferred",
                session_id=session_id,
                pod_id=self.policy.pod_id,
                error=str(exc),
            )

    def _after_commit(
        self, active: dict[str, Any], report_samples: list[dict[str, Any]], reason: str
    ) -> None:
        ports = self.ports
        record = active["record"]
        ports.log_event(
            "session",
            "logout",
            session_id=record["session_id"],
            user=record["username"],
            duration_s=record["duration_s"],
            samples=len(record["samples"]),
            reason=reason,
        )
        self._release_lease(active, log_success=True)
        ports.logout_account(active)
        # The idempotent outbox survives network failure/restart after commit.
        ports.enqueue_ingest(record, report_samples)
        ports.fulfil_share(
            record, access_token=(active.get("auth") or {}).get("access_token")
        )
        self._update_learning(record)
        self._publish_idle()

    def _update_learning(self, record: dict[str, Any]) -> None:
        ports = self.ports
        try:
            baseline = ports.update_baseline(record["username_key"])
            ports.log_event(
                "ai",
                "baseline_updated",
                user=record["username"],
                status=baseline.get("status"),
                nights=baseline.get("nights_used"),
            )
        except Exception as exc:
            ports.log_event(
                "ai", "baseline_update_failed", user=record["username"], error=str(exc)
            )
        availability = ports.availability(
            ports.read_sessions, self.policy.baseline_start_utc
        ).get(record["username_key"], {})
        with ports.profile_lock:
            profiles = ports.load_profiles()
            profile = profiles.get(record["username_key"])
            if profile is not None:
                # SQLite, not an incremented JSON counter, owns usage counts.
                profile["sessions"] = int(availability.get("lifetime_sessions") or 0)
                profile["last_session_utc"] = (
                    availability.get("last_data_session_utc") or record["ended_at_utc"]
                )
                ports.save_profiles(profiles)

    def _publish_idle(self) -> None:
        with self.ports.state_lock:
            self.ports.replace_projection(
                inactive_session_projection(
                    required_packets=self.policy.required_packets, reason="no_session"
                )
            )
        self.ports.reset_inference(None)
