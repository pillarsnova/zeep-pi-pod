"""Compose the four advisory steps without hardware or score dependencies."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from adaptive.coach import one_recommendation
from adaptive.comfort import build_comfort_reference, feedback_evidence
from adaptive.journey import build_journey, command_events, normalize_samples
from adaptive.journey_repository import JourneyRepository
from adaptive.outcomes import compare_commands
from sessions.sleep_event_data import event_value, parse_timestamp


class JourneyService:
    """Authorize owner scope and orchestrate bounded, read-only projections."""

    def __init__(
        self,
        repository: JourneyRepository,
        snapshot_for: Callable[[Any], dict[str, Any]],
        clock: Callable[[], float],
    ) -> None:
        self.repository = repository
        self.snapshot_for = snapshot_for
        self.clock = clock
        self._write_lock = threading.Lock()

    def require_session(self, session_id: str, principal: Any) -> dict[str, Any]:
        """No shared API token and no cross-account access, including history."""
        if principal.auth_source == "api_token":
            raise PermissionError("กรุณาเข้าสู่ระบบด้วยบัญชีผู้ใช้หรือผู้ดูแล")
        record = self.repository.session(session_id)
        if record is None:
            raise LookupError("ไม่พบการพักครั้งนี้")
        owner_key = str(record.get("username_key") or "").strip().casefold()
        account_key = str(principal.account_key or "").strip().casefold()
        if not principal.is_admin and (
            not owner_key or not account_key or owner_key != account_key
        ):
            raise LookupError("ไม่พบการพักครั้งนี้")
        return record

    def summary(self, session_id: str, principal: Any) -> dict[str, Any]:
        """Expose sensors, commands, descriptive outcomes and one advisory."""
        session = self.require_session(session_id, principal)
        rows, truncated = self.repository.samples(session_id)
        events = self.repository.events(session_id)
        samples, commands = normalize_samples(rows), command_events(events)
        reference = build_comfort_reference(
            session,
            self.repository.prior_feedback(session),
        )
        now = self.clock()
        recommendation = one_recommendation(
            session_id,
            self.snapshot_for(principal),
            reference,
            samples,
            commands,
            now=now,
        )
        recent_decisions = [
            event
            for event in events
            if event["type"] == "adaptive_decision"
            and (parse_timestamp(event["timestamp"]) or 0) > now - 1800
        ]
        if recent_decisions or truncated:
            recommendation["item"] = None
            recommendation["message"] = (
                "พักคำแนะนำหลังการตอบครั้งล่าสุด"
                if recent_decisions
                else "ข้อมูลยาวเกินขอบเขตการวิเคราะห์ครั้งนี้"
            )
        journey = build_journey(rows, events, include_acoustic=principal.is_admin)
        if not principal.is_admin:
            # Keep experimental microphone labels Admin-only, as in Smart Ear.
            journey["events"] = [
                item for item in journey["events"] if item["kind"] != "acoustic"
            ]
            journey["points"] = [
                {
                    key: value
                    for key, value in point.items()
                    if not key.startswith("acoustic_")
                }
                for point in journey["points"]
            ]
        return {
            "version": "zeep.adaptive-journey.v1",
            "session_id": session_id,
            "journey": journey,
            "outcomes": compare_commands(
                samples, commands, now=now, reference=reference
            ),
            "comfort_reference": reference,
            "recommendation": recommendation,
            "data_truncated": truncated,
            "automatic_actuation": False,
            "score_modified": False,
        }

    def feedback(
        self,
        session_id: str,
        principal: Any,
        response: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Save optional feedback separately from scores and immutable raw rows."""
        with self._write_lock:
            session = self.require_session(session_id, principal)
            previous = self._existing(session_id, "adaptive_comfort", request_id)
            if previous:
                return {"saved": True, "duplicate": True, "evidence": previous}
            rows, _ = self.repository.samples(session_id)
            evidence = feedback_evidence(
                session,
                normalize_samples(rows),
                now=self.clock(),
                response=response,
                actor_role=principal.role,
            )
            evidence["request_id"] = request_id
            self.repository.append(
                session_id,
                "adaptive_comfort",
                evidence,
                now=self.clock(),
            )
            return {"saved": True, "duplicate": False, "evidence": evidence}

    def decision(
        self,
        session_id: str,
        principal: Any,
        recommendation_id: str,
        decision: str,
        request_id: str,
    ) -> dict[str, Any]:
        """Record intent only; the existing Control page remains authoritative."""
        with self._write_lock:
            self.require_session(session_id, principal)
            previous = self._existing(session_id, "adaptive_decision", request_id)
            if previous:
                return previous
            item = self.summary(session_id, principal)["recommendation"]["item"]
            if not item or item["id"] != recommendation_id:
                raise ValueError("ข้อมูลเปลี่ยนแล้ว กรุณาดูคำแนะนำล่าสุด")
            value = {
                "request_id": request_id,
                "recommendation": item,
                "decision": decision,
                "actor_role": principal.role,
                "command_executed": False,
                "next_step": "manual_control" if decision == "accept" else "observe",
            }
            self.repository.append(
                session_id,
                "adaptive_decision",
                value,
                now=self.clock(),
            )
            return value

    def _existing(
        self,
        session_id: str,
        kind: str,
        request_id: str,
    ) -> dict[str, Any] | None:
        for row in self.repository.events(session_id):
            value = event_value(row)
            if row["type"] == kind and value.get("request_id") == request_id:
                return value
        return None
