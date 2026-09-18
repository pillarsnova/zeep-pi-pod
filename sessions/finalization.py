"""Ordered live Session closure; storage commit remains a separate boundary."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pod_occupancy import CoordinatorUnavailable, OccupancyConflict
from sessions.cadence import sample_interval_seconds
from sessions.finalization_commit import FinalizationCommittedError
from sessions.finalization_contracts import FinalizationPolicy, SessionFinalizationPorts
from sessions.finalization_report import build_recorded_report, prepare_record
from sessions.live_projection import inactive_session_projection


@dataclass
class _FinalizationProgress:
    """Local failure boundary; never included in public Session/result payloads."""

    bcg_stop_attempted: bool = False
    closed: bool = False


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
        progress = _FinalizationProgress()
        original_record = dict(active["record"])
        try:
            return self._finalize_owned(active, reason, progress)
        except Exception:
            if not progress.closed:
                # Report preparation adds derived fields and may change the
                # report cadence. A failed attempt must restore the live input.
                active["record"].clear()
                active["record"].update(original_record)
                self._recover_before_commit(active, progress)
            raise

    def _recover_before_commit(
        self, active: dict[str, Any], progress: _FinalizationProgress
    ) -> None:
        current = self.ports.get_active()
        if current is active:
            return  # The lower persistence boundary has already recovered it.
        if current is not None:
            self._log_event(
                "session",
                "finalization_recovery_owner_conflict",
                session_id=active["record"]["session_id"],
            )
            return
        try:
            if progress.bcg_stop_attempted:
                self.ports.recover_active(active)
            else:
                self._restore_ownership(active)
        except Exception as exc:
            # Keep the original operation failure as the API exception; expose
            # recovery failure separately without dumping token/profile values.
            self._log_event(
                "session",
                "finalization_recovery_failed",
                session_id=active["record"]["session_id"],
                error_type=type(exc).__name__,
            )

    def _finalize_owned(
        self,
        active: dict[str, Any],
        reason: str,
        progress: _FinalizationProgress,
    ) -> dict[str, Any]:
        ports = self.ports
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
            return self._close_waiting(active, reason, ended_at, progress)
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
        self._drain_bcg(active, progress)
        final_summary = build_recorded_report(
            record,
            projection,
            duration=duration,
            acquisition_interval_s=interval_s,
            terminal_wake=terminal_wake,
            ports=ports,
            policy=self.policy,
        )
        cleanup_error = None
        try:
            ports.commit(active, final_summary, terminal_wake)
        except FinalizationCommittedError as exc:
            cleanup_error = exc.cleanup_error
        progress.closed = True
        try:
            if cleanup_error is not None:
                self._log_cleanup_failure(active, "clear_checkpoint", cleanup_error)
        finally:
            # Even an unavailable audit sink cannot leave a committed Session
            # displayed as active or block the remaining best-effort cleanup.
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
        writer_error = ports.writer_health().get("last_error")
        self._log_event(
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
            raise RuntimeError(
                "report continuity invariant failed: unattributed recording time"
            )
        return projection

    def _drain_bcg(
        self, active: dict[str, Any], progress: _FinalizationProgress
    ) -> None:
        progress.bcg_stop_attempted = True
        self.ports.end_bcg(active["record"]["session_id"])
        if not self.ports.flush(30):
            raise self.ports.flush_failure("final BCG epoch")

    def _close_waiting(
        self,
        active: dict[str, Any],
        reason: str,
        ended_at: str,
        progress: _FinalizationProgress,
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
        progress.closed = True
        try:
            self._log_event(
                "session",
                "closed_without_recording",
                session_id=record["session_id"],
                user=record["username"],
                reason=record["end_reason"],
                gate_reason=gate["reason"],
            )
            self._best_effort(
                active, "lease", self._release_lease, active, log_success=False
            )
            self._best_effort(active, "logout", ports.logout_account, active)
        finally:
            self._publish_idle()
            self._best_effort(
                active,
                "discard_share",
                ports.discard_share,
                record.get("identity_subject"),
            )
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
                self._log_event(
                    "occupancy",
                    "lease_released",
                    session_id=session_id,
                    pod_id=self.policy.pod_id,
                )
        except (CoordinatorUnavailable, OccupancyConflict) as exc:
            # The lease expires automatically; coordinator failure cannot undo
            # a durable result or prevent a local exit.
            self._log_event(
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
        try:
            self._log_event(
                "session",
                "logout",
                session_id=record["session_id"],
                user=record["username"],
                duration_s=record["duration_s"],
                samples=len(record["samples"]),
                reason=reason,
            )
            self._best_effort(
                active, "lease", self._release_lease, active, log_success=True
            )
            self._best_effort(active, "logout", ports.logout_account, active)
            # One optional side effect must not suppress the remaining ones.
            self._best_effort(
                active, "ingest", ports.enqueue_ingest, record, report_samples
            )
            shared = self._best_effort(
                active,
                "share",
                ports.fulfil_share,
                record,
                access_token=(active.get("auth") or {}).get("access_token"),
            )
            if not shared:
                self._best_effort(
                    active,
                    "discard_share",
                    ports.discard_share,
                    record.get("identity_subject"),
                )
            self._best_effort(active, "learning", self._update_learning, record)
        finally:
            self._publish_idle()

    def _best_effort(
        self,
        active: dict[str, Any],
        step: str,
        operation: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        try:
            operation(*args, **kwargs)
            return True
        except Exception as exc:
            self._log_cleanup_failure(active, step, exc)
            return False

    def _log_cleanup_failure(
        self, active: dict[str, Any], step: str, error: Exception
    ) -> None:
        self._log_event(
            "session",
            "finalization_cleanup_failed",
            session_id=active["record"]["session_id"],
            step=step,
            error_type=type(error).__name__,
        )

    def _log_event(self, component: str, event: str, **details: Any) -> None:
        """Audit failure cannot replace an operation error or strand ownership."""
        try:
            self.ports.log_event(component, event, **details)
        except Exception as exc:
            # The system journal is the fallback, without profile/token data or
            # arbitrary exception text from an external integration.
            logging.getLogger(__name__).error(
                "Session finalization audit unavailable: %s/%s (%s)",
                component,
                event,
                type(exc).__name__,
            )

    def _update_learning(self, record: dict[str, Any]) -> None:
        ports = self.ports
        try:
            baseline = ports.update_baseline(record["username_key"])
            self._log_event(
                "ai",
                "baseline_updated",
                user=record["username"],
                status=baseline.get("status"),
                nights=baseline.get("nights_used"),
            )
        except Exception as exc:
            self._log_event(
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
