"""Start an authenticated waiting Session without starting Sensor recording."""

from __future__ import annotations

from typing import Any

from pod_occupancy import CoordinatorUnavailable, OccupancyConflict
from sessions.live_projection import SessionPublicIdentity, active_session_projection
from sessions.start_contracts import (
    SessionStartRejected,
    StartPolicy,
    StartPorts,
    StartRequest,
    ValidatedStart,
)
from sessions.start_profile import prepare_start_profile


class SessionStarter:
    """Coordinate existing Login behavior; callers retain their lifecycle lock."""

    def __init__(self, ports: StartPorts, policy: StartPolicy) -> None:
        self.ports = ports
        self.policy = policy

    def start(self, request: StartRequest) -> dict[str, Any]:
        """Persist waiting ownership before returning the existing Login response."""
        p = self.ports
        with p.state_lock:
            safety = dict(p.state["safety"])
        start = self._validate(request)
        with p.session_lock:
            if p.get_active() is not None:
                raise SessionStartRejected(
                    409,
                    {"code": "pod_already_occupied", "message": "ตู้นี้กำลังมีผู้ใช้งาน"},
                )
        profile, health, wellness = self._save_profile(start, request)
        display_name = (request.auth or {}).get("display_name") or start.username
        baseline = p.rest_baseline(start.key, start.rest_mode, start.target_duration_s)
        session_id = f"s-{p.utc_now().strftime('%Y%m%dT%H%M%SZ')}-{p.session_suffix()}"
        lease = self._acquire_lease(start, request, session_id)
        active = self._waiting_session(
            start, request, profile, health, wellness, display_name, session_id, lease
        )
        self._claim_and_checkpoint(active, lease)
        p.reset_inference(session_id)
        # Access is independent from safety actuation. Do not add a new Login
        # gate: READY/ARMED/latch remain device-command policy responsibilities.
        p.log_event(
            "session",
            "login_waiting_bed",
            session_id=session_id,
            user=start.username,
            bed_start_s=self.policy.bed_start_seconds,
            monitor_only=False,
            safety_level=safety.get("level"),
            rest_mode=start.rest_mode,
            target_duration_s=start.target_duration_s,
            auth_source=active["record"]["auth_source"],
            pod_id=self.policy.pod_id,
        )
        self._publish(active, start, profile, health, wellness, baseline)
        return {
            "ok": True,
            "session": p.snapshot()["session"],
            "pod_id": self.policy.pod_id,
            "occupancy": {
                "mode": p.occupancy_mode(),
                "lease_expires_at": lease.expires_at,
            },
            "monitor_only": False,
            "warning": None,
        }

    def _validate(self, request: StartRequest) -> ValidatedStart:
        p = self.ports
        username = p.normalize_username(request.username)
        key = request.owner.account_key
        email = request.owner.email
        if request.auth:
            email = p.normalize_email(str(request.auth.get("email") or ""))
            if key != email:
                raise SessionStartRejected(
                    409, "Account identity ไม่ตรงกับ Email ที่ยืนยันแล้ว"
                )
        gender = (request.gender or "").strip().lower() or None
        group = (request.age_group or "").strip() or None
        incoming_health = dict(request.health_reference or {})
        try:
            mode = p.normalize_mode(request.rest_mode)
        except ValueError as exc:
            raise SessionStartRejected(422, "รูปแบบการพักไม่ถูกต้อง") from exc
        target = p.resolve_target(
            mode,
            request.target_duration_minutes * 60
            if request.target_duration_minutes is not None
            else None,
            use_mode_default=True,
        )
        if not target.get("available"):
            message = (
                "Nap & Refresh ต้องเลือกเวลาพัก 30 หรือ 90 นาที"
                if mode == "nap_recovery"
                else "เป้าหมายระยะเวลาของรูปแบบการพักไม่ถูกต้อง"
            )
            raise SessionStartRejected(422, message)
        if group is not None and group not in self.policy.age_groups:
            raise SessionStartRejected(422, "ช่วงอายุต้องเป็น 18-29, 30-44, 45-59 หรือ 60+")
        age = request.age
        if age is None:
            age = self.policy.default_ages.get(group)
        if age is not None and not 18 <= age <= 100:
            raise SessionStartRejected(422, "อายุต้องอยู่ระหว่าง 18–100 ปี")
        if gender is not None and gender not in self.policy.genders:
            raise SessionStartRejected(
                422, f"gender ต้องเป็นหนึ่งใน {', '.join(self.policy.genders)}"
            )
        return ValidatedStart(
            username,
            key,
            email,
            gender,
            age,
            group,
            incoming_health,
            mode,
            target["seconds"],
        )

    def _save_profile(
        self, start: ValidatedStart, request: StartRequest
    ) -> tuple[dict[str, Any], dict[str, Any], Any]:
        p = self.ports
        refreshed_at = p.utc_now().isoformat()
        with p.profile_lock:
            profiles = p.load_profiles()
            profile = prepare_start_profile(
                profiles.get(start.key), start, request, p, refreshed_at=refreshed_at
            )
            health = p.health_reference(profile)
            wellness = p.wellness_context(profile)
            profiles[start.key] = profile
            p.save_profiles(profiles)
        return profile, health, wellness

    def _acquire_lease(
        self, start: ValidatedStart, request: StartRequest, session_id: str
    ) -> Any:
        try:
            return self.ports.acquire_lease(
                subject=request.owner.subject,
                pod_id=self.policy.pod_id,
                pod_session_id=session_id,
                username=start.username,
            )
        except OccupancyConflict as exc:
            message = (
                "บัญชีนี้กำลังใช้งานตู้อื่นอยู่"
                if exc.reason == "account_already_in_use"
                else "ตู้นี้กำลังมีผู้ใช้งาน"
            )
            raise SessionStartRejected(
                409, {"code": exc.reason, "message": message, "pod_id": exc.pod_id}
            ) from exc
        except CoordinatorUnavailable as exc:
            raise SessionStartRejected(
                503,
                {
                    "code": "occupancy_coordinator_unavailable",
                    "message": "ยังตรวจสอบการใช้งานซ้ำระหว่างตู้ไม่ได้ จึงยังไม่เริ่ม Session ใหม่",
                },
            ) from exc

    def _waiting_session(
        self,
        start: ValidatedStart,
        request: StartRequest,
        profile: dict[str, Any],
        health: dict[str, Any],
        wellness: Any,
        display_name: str,
        session_id: str,
        lease: Any,
    ) -> dict[str, Any]:
        p = self.ports
        safety_context = p.current_safety()
        with p.state_lock:
            packets = int(p.state["sensor"]["bcg"].get("packets") or 0)
        return {
            "record": {
                "session_id": session_id,
                "username": start.username,
                "username_key": start.key,
                "display_name": display_name,
                "gender": profile["gender"],
                "age": profile.get("age"),
                "age_group": profile.get("age_group")
                or p.age_group(profile.get("age")),
                "health_reference": health,
                "wellness_context": wellness,
                "rest_mode": start.rest_mode,
                "target_duration_s": start.target_duration_s,
                "auth_source": "zeep" if request.auth else "local",
                "zeep_public_id": (request.auth or {}).get("public_id"),
                "identity_subject": request.owner.subject,
                "pod_id": self.policy.pod_id,
                "armed_at_utc": p.utc_now().isoformat(),
                "started_at_utc": None,
                "started_monotonic": None,
                "sample_interval_s": self.policy.sample_interval_s,
                "sample_cadence_segments": [],
            },
            # Preserve token ownership outside the persisted/public record.
            "auth": request.auth,
            "owner_auth_session_id": request.owner.session_id,
            "occupancy_lease": lease,
            "last_lease_renew": p.monotonic(),
            "samples": [],
            "counters": {},
            "last_sample": float("-inf"),
            "phase": "waiting_bed",
            "safety_context": safety_context,
            "onbed_since": None,
            "vital_gate_start_packet_count": packets,
        }

    def _claim_and_checkpoint(self, active: dict[str, Any], lease: Any) -> None:
        p = self.ports
        with p.session_lock:
            if p.get_active() is not None:
                p.release_lease(lease)
                raise SessionStartRejected(409, "มี session อื่นเพิ่งเริ่มพร้อมกัน — ลองใหม่")
            p.set_active(active)
        try:
            p.save_checkpoint(active)
        except Exception as exc:
            with p.session_lock:
                if p.get_active() is active:
                    p.set_active(None)
            try:
                p.release_lease(lease)
            except (CoordinatorUnavailable, OccupancyConflict):
                pass
            raise SessionStartRejected(500, "บันทึกสถานะ Login สำหรับกู้คืนไม่สำเร็จ") from exc

    def _publish(
        self,
        active: dict[str, Any],
        start: ValidatedStart,
        profile: dict[str, Any],
        health: dict[str, Any],
        wellness: Any,
        baseline: Any,
    ) -> None:
        p = self.ports
        vital_gate = p.vital_gate(active)
        with p.state_lock:
            p.replace_projection(
                active_session_projection(
                    SessionPublicIdentity(
                        username=start.username,
                        account_key=start.key,
                        email=start.email,
                        display_name=active["record"]["display_name"],
                        auth_source=active["record"]["auth_source"],
                        gender=profile["gender"],
                        age=profile.get("age"),
                        age_group=profile.get("age_group")
                        or p.age_group(profile.get("age")),
                        health_reference=health,
                    ),
                    session_id=active["record"]["session_id"],
                    rest_mode=start.rest_mode,
                    target_duration_s=start.target_duration_s,
                    started_at=p.clock(),
                    samples=0,
                    recording=False,
                    vital_gate=vital_gate,
                    wellness_context_available=bool(wellness),
                    personal_rest_baseline=baseline,
                )
            )
