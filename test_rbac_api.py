"""API-level regression tests for User/Admin separation.

The test uses temporary storage and never starts hardware reader threads.
"""
from __future__ import annotations

import asyncio
import copy
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from fastapi.testclient import TestClient

from testing_support import configure_app_test_environment


_test_root = configure_app_test_environment()

import app as pod_app  # noqa: E402  (environment must be set before import)


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("zeep_csrf") or ""}


class RbacApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pod_app.database.initialize()
        pod_app.database.start()

    @classmethod
    def tearDownClass(cls) -> None:
        if pod_app._active_session is not None:
            pod_app._finalize_active_session("test_cleanup")
        pod_app.database.stop()

    def test_public_boot_and_protected_state(self) -> None:
        client = TestClient(pod_app.app)
        self.assertEqual(client.get("/api/public/status").status_code, 200)
        # UI assets stay loadable before login; role checks protect the state
        # and commands shown behind the Admin-only Control Debug overlay.
        self.assertEqual(client.get("/control-debug").status_code, 200)
        self.assertEqual(client.get("/api/state").status_code, 401)

    def test_aroma_and_steam_outputs_use_a_five_second_pulse(self) -> None:
        """A tap must hold the real dispenser output HIGH for five seconds."""
        self.assertEqual(pod_app.AROMA_STEAM_PULSE_SECONDS, 5.0)
        pod_app.pulse_last_end["aroma1"] = 0.0
        sleep = AsyncMock()
        with (
            patch.object(pod_app.gpio, "require_ready") as require_ready,
            patch.object(pod_app.gpio, "set") as gpio_set,
            patch.object(pod_app.asyncio, "sleep", new=sleep),
        ):
            asyncio.run(pod_app.accessory_pulse("aroma1"))

        require_ready.assert_called_once_with()
        sleep.assert_awaited_once_with(5.0)
        self.assertEqual(
            gpio_set.call_args_list,
            [call("aroma1", True), call("aroma1", False)],
        )

    def test_user_and_admin_login_have_separate_stable_urls(self) -> None:
        client = TestClient(pod_app.app)
        root = client.get("/", follow_redirects=False)
        self.assertEqual(root.status_code, 307)
        self.assertEqual(root.headers["location"], "/login")
        for path in ("/login", "/admin/login"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn("no-store", response.headers.get("cache-control", ""))
        ui = (Path(__file__).resolve().parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("const USER_LOGIN_PATH='/login'", ui)
        self.assertIn("const ADMIN_LOGIN_PATH='/admin/login'", ui)
        self.assertIn("'/admin/login'", ui)
        self.assertNotIn('id="loginAudienceUser"', ui)
        self.assertNotIn('id="loginAudienceAdmin"', ui)
        self.assertIn("'/api/auth/login'", ui)
        self.assertIn("'/api/admin/auth/login'", ui)

    def test_admin_login_and_csrf(self) -> None:
        client = TestClient(pod_app.app)
        login = client.post(
            "/api/admin/auth/login",
            json={"identifier": "test-admin", "password": "test-admin-password"},
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get("/api/auth/me").json()["principal"]["role"], "admin")
        self.assertEqual(client.post("/api/safety/disarm").status_code, 403)
        self.assertEqual(client.post("/api/safety/disarm", headers=csrf(client)).status_code, 200)

    def test_brainwave_sound_lab_is_admin_only_and_plays_on_pi(self) -> None:
        anonymous = TestClient(pod_app.app)
        self.assertEqual(
            anonymous.get("/api/admin/brainwave/presets").status_code, 401
        )
        self.assertEqual(
            anonymous.post(
                "/api/admin/brainwave/preview",
                json={"preset_id": "control-pink"},
            ).status_code,
            401,
        )

        admin = TestClient(pod_app.app)
        login = admin.post(
            "/api/admin/auth/login",
            json={"identifier": "test-admin", "password": "test-admin-password"},
        )
        self.assertEqual(login.status_code, 200)
        catalog = admin.get("/api/admin/brainwave/presets")
        self.assertEqual(catalog.status_code, 200)
        self.assertIn(
            "control-pink", [item["id"] for item in catalog.json()["presets"]]
        )

        rendered = {
            "path": Path("/tmp/zeep-test-brainwave.wav"),
            "file": "zeep-test-brainwave.wav",
            "preset_id": "control-pink",
            "version": "zeep-speaker-sound-lab-v1.0",
            "duration_seconds": 30,
            "sample_rate_hz": 24000,
            "channels": 2,
            "peak": 0.2,
            "rms": 0.08,
            "pcm_sha256": "0" * 64,
        }
        with (
            patch.object(pod_app, "render_brainwave_preview", return_value=rendered),
            patch.object(pod_app.player, "set_volume") as set_volume,
            patch.object(pod_app.player, "play") as play,
        ):
            response = admin.post(
                "/api/admin/brainwave/preview",
                headers=csrf(admin),
                json={
                    "preset_id": "control-pink",
                    "duration_seconds": 30,
                    "volume": 35,
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        set_volume.assert_called_once_with(35)
        play.assert_called_once_with(rendered["path"], loop=False, queue=False)
        self.assertNotIn("path", response.json()["render"])

    def test_brainwave_preview_requires_consent_confirmation_when_occupied(self) -> None:
        admin = TestClient(pod_app.app)
        admin.post(
            "/api/admin/auth/login",
            json={"identifier": "test-admin", "password": "test-admin-password"},
        )
        occupied = {"record": {"session_id": "occupied-sound-lab-test"}}
        with patch.object(pod_app, "_active_session", occupied):
            response = admin.post(
                "/api/admin/brainwave/preview",
                headers=csrf(admin),
                json={"preset_id": "relax-alpha", "duration_seconds": 30},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"]["code"], "occupied_confirmation_required"
        )

    def test_versioned_api_contracts_are_admin_scoped_and_enveloped(self) -> None:
        anonymous = TestClient(pod_app.app)
        health = anonymous.get("/api/v1/public/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["schema"], "zeep.api.response")
        self.assertEqual(health.json()["api_version"], "1.0")
        self.assertEqual(
            anonymous.get("/api/v1/admin/contracts/sensors").status_code, 401
        )

        admin = TestClient(pod_app.app)
        login = admin.post(
            "/api/admin/auth/login",
            json={"identifier": "test-admin", "password": "test-admin-password"},
        )
        self.assertEqual(login.status_code, 200)
        sensors = admin.get("/api/v1/admin/contracts/sensors")
        self.assertEqual(sensors.status_code, 200)
        self.assertEqual(
            sensors.json()["data"]["contract_version"],
            "zeep-sensor-contract-v1.0",
        )
        maintenance = admin.get("/api/v1/admin/maintenance")
        self.assertEqual(maintenance.status_code, 200)
        self.assertFalse(maintenance.json()["data"]["browser_execution_enabled"])

    def test_session_start_gate_requires_fresh_hr_and_rr_packets(self) -> None:
        """Bed status or a display-held vital alone must never start recording."""
        with pod_app.state_lock:
            original = copy.deepcopy(pod_app.state["sensor"]["bcg"])
        active = {"vital_gate_start_packet_count": 100}
        try:
            with pod_app.state_lock:
                pod_app.state["sensor"]["bcg"].update({
                    "connected": True,
                    "last_update": time.time(),
                    "status_code": 0,
                    "packets": 100,
                    "heart_rate_bpm": 68,
                    "respiration_rate": 14.2,
                    "heart_rate_current_valid": True,
                    "respiration_current_valid": True,
                    "heart_rate_held": False,
                    "respiration_held": False,
                    # A streak from before Login cannot satisfy the new gate.
                    "vital_valid_streak": 50,
                })
            gate = pod_app.session_vital_gate_now(active)
            self.assertFalse(gate["ready"])
            self.assertEqual(gate["confirmed_packets"], 0)

            with pod_app.state_lock:
                bcg = pod_app.state["sensor"]["bcg"]
                bcg["packets"] = 102
                bcg["vital_valid_streak"] = 2
            gate = pod_app.session_vital_gate_now(active)
            self.assertFalse(gate["ready"])
            self.assertEqual(gate["reason"], "confirming_hr_rr")

            with pod_app.state_lock:
                bcg = pod_app.state["sensor"]["bcg"]
                bcg["packets"] = 103
                bcg["vital_valid_streak"] = 3
                bcg["respiration_held"] = True
            gate = pod_app.session_vital_gate_now(active)
            self.assertFalse(gate["ready"])
            self.assertEqual(gate["reason"], "waiting_for_rr")

            with pod_app.state_lock:
                pod_app.state["sensor"]["bcg"]["respiration_held"] = False
            gate = pod_app.session_vital_gate_now(active)
            self.assertTrue(gate["ready"])
            self.assertEqual(gate["confirmed_packets"], 3)
        finally:
            with pod_app.state_lock:
                pod_app.state["sensor"]["bcg"] = original

    def test_user_login_waiting_bed_survives_service_restart(self) -> None:
        """Restart restores the owner and phase even before a DB Session row exists."""
        original = pod_app._authenticate_zeep_account

        def fake_auth(_identifier: str, _password: str):
            return ({
                "public_id": "public-restart-waiting",
                "username": "restart-waiting",
                "email": "restart.waiting@example.test",
                "display_name": "Restart Waiting",
                "role": "user",
                "plan": "test",
                "access_token": "must-never-enter-checkpoint",
                "refresh_token": "must-never-enter-checkpoint-either",
            }, {
                "gender": "female", "dateOfBirth": "1990-01-01",
                "heightCm": 165.4, "weightKg": 56.2, "bloodGroup": "O+",
            })

        pod_app._authenticate_zeep_account = fake_auth
        user = TestClient(pod_app.app)
        try:
            login = user.post(
                "/api/auth/login",
                json={"identifier": "restart-waiting", "password": "valid"},
            )
            self.assertEqual(login.status_code, 200, login.text)
            session_id = login.json()["session"]["session_id"]
            health = login.json()["session"]["health_reference"]
            self.assertEqual(health["gender"], "female")
            self.assertEqual(health["height_cm"], 165.4)
            self.assertEqual(health["weight_kg"], 56.2)
            self.assertEqual(health["blood_group"], "O+")
            self.assertEqual(health["source"], "zeep_profile")
            self.assertEqual(health["intended_use"], "health_reference_only")
            checkpoint_text = pod_app.ACTIVE_SESSION_CHECKPOINT_PATH.read_text(
                encoding="utf-8"
            )
            self.assertNotIn("must-never-enter-checkpoint", checkpoint_text)
            self.assertEqual(
                pod_app.database.read_sessions(
                    "SELECT session_id FROM sessions WHERE session_id=?", (session_id,)
                ),
                [],
            )
            previous_db_error = pod_app.database.health()["last_error"]
            pod_app._commit_sleep_stage(
                "wake", {"wake": 1.0}, "waiting_bed_test"
            )
            pod_app.note_session_activity("door", {"action": "test"})
            self.assertTrue(pod_app.database.flush(5))
            self.assertEqual(pod_app.database.health()["last_error"], previous_db_error)
            self.assertEqual(
                pod_app.database.read_sessions(
                    "SELECT id FROM events WHERE session_id=?", (session_id,)
                ),
                [],
            )

            # Simulate process memory loss while keeping auth.db, occupancy.db
            # and the restart checkpoint exactly as a real code update does.
            with pod_app.session_lock:
                pod_app._active_session = None
            with pod_app.state_lock:
                pod_app.state["session"].update({
                    "active": False, "session_id": None, "recording": False,
                })
            self.assertEqual(pod_app._restore_interrupted_session(), session_id)
            with pod_app.session_lock:
                restored = pod_app._active_session
            self.assertIsNotNone(restored)
            self.assertEqual(restored["phase"], "waiting_bed")
            self.assertEqual(restored["record"]["session_id"], session_id)
            self.assertEqual(
                restored["record"]["health_reference"]["blood_group"], "O+"
            )
            me = user.get("/api/auth/me")
            self.assertEqual(me.status_code, 200, me.text)
            self.assertTrue(me.json()["pod"]["owns_active_session"])
            closed = pod_app._finalize_active_session(
                "restart_waiting_test_cleanup"
            )
            self.assertFalse(closed["recording_started"])
            self.assertEqual(
                pod_app.database.read_sessions(
                    "SELECT session_id FROM sessions WHERE session_id=?", (session_id,)
                ),
                [],
            )
        finally:
            if pod_app._active_session is not None:
                pod_app._finalize_active_session("restart_waiting_test_cleanup")
            user.post("/api/auth/logout", headers=csrf(user))
            pod_app._authenticate_zeep_account = original

    def test_health_reference_normalises_optional_profile_fields(self) -> None:
        ref = pod_app._zeep_health_reference({
            "profile": {
                "gender": "male", "date_of_birth": "1985-08-09",
                "height": 1.78, "weight": "72.5", "blood_type": "AB negative",
            }
        })
        self.assertEqual(ref["height_cm"], 178.0)
        self.assertEqual(ref["weight_kg"], 72.5)
        self.assertEqual(ref["blood_group"], "AB-")
        self.assertIsInstance(ref["age_years"], int)
        self.assertIsNone(
            pod_app._zeep_health_reference({"heightCm": 999})["height_cm"]
        )

    def test_each_login_refreshes_health_reference_without_stale_profile_fields(self) -> None:
        """Live /users/me replaces old facts; an unavailable profile keeps cache."""
        original = pod_app._authenticate_zeep_account
        profile_response = [{
            "gender": "female", "dateOfBirth": "1990-01-01",
            "heightCm": 165.4, "weightKg": 56.2, "bloodGroup": "O+",
        }]
        profile_refreshed = [True]

        def fake_auth(_identifier: str, _password: str):
            return ({
                "public_id": "public-health-refresh",
                "username": "health-refresh",
                "email": "health.refresh@example.test",
                "display_name": "Health Refresh",
                "role": "user", "plan": "test",
                "access_token": "not-persisted", "refresh_token": None,
                "profile_refreshed": profile_refreshed[0],
            }, dict(profile_response[0]))

        pod_app._authenticate_zeep_account = fake_auth
        user = TestClient(pod_app.app)
        try:
            first = user.post(
                "/api/auth/login",
                json={"identifier": "health-refresh", "password": "valid"},
            )
            self.assertEqual(first.status_code, 200, first.text)
            first_ref = first.json()["session"]["health_reference"]
            self.assertEqual(first_ref["refresh_status"], "live_login")
            self.assertEqual(first_ref["height_cm"], 165.4)
            self.assertEqual(first_ref["blood_group"], "O+")
            verified_at = first_ref["updated_at_utc"]
            user.post("/api/session/logout", headers=csrf(user))
            user.post("/api/auth/logout", headers=csrf(user))

            # Identity Login succeeded but /users/me failed.  Do not relabel
            # the default age/gender or blank the last verified facts.
            profile_refreshed[0] = False
            profile_response[0] = {}
            cached = user.post(
                "/api/auth/login",
                json={"identifier": "health-refresh", "password": "valid"},
            )
            self.assertEqual(cached.status_code, 200, cached.text)
            cached_ref = cached.json()["session"]["health_reference"]
            self.assertEqual(cached_ref["refresh_status"], "cached")
            self.assertEqual(cached_ref["gender"], "female")
            self.assertEqual(cached_ref["height_cm"], 165.4)
            self.assertEqual(cached_ref["updated_at_utc"], verified_at)
            user.post("/api/session/logout", headers=csrf(user))
            user.post("/api/auth/logout", headers=csrf(user))

            # The next successful profile fetch is authoritative.  Missing
            # fields are cleared and changed fields replace the old values.
            profile_refreshed[0] = True
            profile_response[0] = {
                "gender": "female", "weightKg": 58.0, "bloodGroup": "A+",
            }
            refreshed = user.post(
                "/api/auth/login",
                json={"identifier": "health-refresh", "password": "valid"},
            )
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            refreshed_ref = refreshed.json()["session"]["health_reference"]
            self.assertEqual(refreshed_ref["refresh_status"], "live_login")
            self.assertIsNone(refreshed_ref["height_cm"])
            self.assertEqual(refreshed_ref["weight_kg"], 58.0)
            self.assertEqual(refreshed_ref["blood_group"], "A+")
            self.assertIsNone(refreshed_ref["date_of_birth"])
        finally:
            if pod_app._active_session is not None:
                pod_app._finalize_active_session("health_refresh_test_cleanup")
            user.post("/api/auth/logout", headers=csrf(user))
            pod_app._authenticate_zeep_account = original

    def test_recording_session_and_owner_survive_service_restart(self) -> None:
        """An open recording resumes the same row, owner Login and Rest Mode."""
        original = pod_app._authenticate_zeep_account

        def fake_auth(_identifier: str, _password: str):
            return ({
                "public_id": "public-restart-recording",
                "username": "restart-recording",
                "email": "restart.recording@example.test",
                "display_name": "Restart Recording",
                "role": "user", "plan": "test",
                "access_token": "ephemeral", "refresh_token": None,
            }, {"gender": "male", "dateOfBirth": "1988-02-03"})

        pod_app._authenticate_zeep_account = fake_auth
        user = TestClient(pod_app.app)
        try:
            login = user.post(
                "/api/auth/login",
                json={
                    "identifier": "restart-recording", "password": "valid",
                    "rest_mode": "overnight",
                },
            )
            self.assertEqual(login.status_code, 200, login.text)
            session_id = login.json()["session"]["session_id"]
            with pod_app.session_lock:
                active = pod_app._active_session
            with pod_app.state_lock:
                bcg = pod_app.state["sensor"]["bcg"]
                bcg.update({
                    "connected": True,
                    "last_update": time.time(),
                    "status_code": 0,
                    "heart_rate_bpm": 67,
                    "respiration_rate": 13.8,
                    "heart_rate_current_valid": True,
                    "respiration_current_valid": True,
                    "heart_rate_held": False,
                    "respiration_held": False,
                    "packets": (
                        active["vital_gate_start_packet_count"]
                        + pod_app.SESSION_VITAL_START_PACKETS
                    ),
                    "vital_valid_streak": pod_app.SESSION_VITAL_START_PACKETS,
                })
            pod_app._begin_recording(active)
            self.assertEqual(
                pod_app._load_active_session_checkpoint()["phase"], "recording"
            )

            with pod_app.session_lock:
                pod_app._active_session = None
            with pod_app.state_lock:
                pod_app.state["session"].update({
                    "active": False, "session_id": None, "recording": False,
                })
            self.assertEqual(pod_app._restore_interrupted_session(), session_id)
            with pod_app.session_lock:
                restored = pod_app._active_session
            self.assertEqual(restored["phase"], "recording")
            self.assertEqual(restored["record"]["rest_mode"], "overnight")
            me = user.get("/api/auth/me")
            self.assertEqual(me.status_code, 200, me.text)
            self.assertTrue(me.json()["pod"]["owns_active_session"])
        finally:
            if pod_app._active_session is not None:
                pod_app._finalize_active_session("restart_recording_test_cleanup")
            user.post("/api/auth/logout", headers=csrf(user))
            pod_app._authenticate_zeep_account = original

    def test_restart_immediately_restores_last_sensor_values_as_stale(self) -> None:
        """Restart continuity shows values immediately without forging Live data."""
        now = time.time()
        session_id = "restart-sensor-frame-test"
        devices = {
            key: {
                "model": model, "status": "live", "source": "test",
                "source_label": "Test Sensor", "data_age_s": 0.0,
                "invalid_values": {},
            }
            for key, model in {
                "sht3x_dis": "SHT3x-DIS", "opt3001": "OPT3001",
                "sph0645": "SPH0645", "mhz19c": "MH-Z19C",
                "pms7003": "PMS7003", "sgp40": "SGP40",
            }.items()
        }
        frame = {
            "sequence": int(now // pod_app.SLEEP_SAMPLE_SECONDS),
            "timestamp": pod_app.datetime.fromtimestamp(
                now, pod_app.timezone.utc).isoformat(),
            "epoch_s": now,
            "refresh_s": pod_app.SLEEP_SAMPLE_SECONDS,
            "source": "pi_local_sensor_tick",
            "session_id": session_id,
            "environment": {
                "temperature_c": 23.4, "humidity_rh": 51.2, "lux": 0.0,
                "sound_dba_est": 37.5, "co2_ppm": 812.0,
                "pm2_5_ug_m3": 4.0, "voc_index": 103.0,
                "devices": devices, "live_count": 6, "total_count": 6,
                "status": "live",
            },
            "bcg": {
                "status_code": 0, "status_text": "On bed",
                "heart_rate_bpm": 61.0, "respiration_rate": 14.2,
                "analysis_valid": True,
            },
            # This label also exists as a durable sleep_stage event/path.  It
            # may bridge the UI after restart, but must never become a new row.
            "sleep": {"state": "n3", "confirmed_state": "n3",
                      "classification_active": True,
                      "probabilities": {
                          "wake": 0.02, "n1": 0.03, "n2": 0.15,
                          "n3": 0.75, "rem": 0.05,
                      }},
        }
        with pod_app.state_lock:
            original_session = copy.deepcopy(pod_app.state["session"])
        with pod_app.session_lock:
            original_active = pod_app._active_session
            pod_app._active_session = None
        with pod_app.analysis_frame_lock:
            original_frame = pod_app._analysis_frame
            pod_app._analysis_frame = None
        with pod_app.sleep_path_lock:
            original_path = copy.deepcopy(pod_app._sleep_stage_path)
            pod_app._reset_sleep_stage_path(session_id)
            pod_app._apply_stage_to_path("n3")
        original_sleep_cache = copy.deepcopy(pod_app._sleep_cache)
        try:
            with pod_app.state_lock:
                pod_app.state["session"].update({
                    "active": True, "recording": True,
                    "session_id": session_id,
                })
            self.assertTrue(pod_app._persist_last_sensor_frame(frame))
            # Session Timeline can be newer than the saved analysis frame but
            # carries no Sleep decision.  The display bridge must still use
            # the durable, matching N3 from the saved frame.
            newer_timeline = copy.deepcopy(frame)
            newer_timeline.update({
                "epoch_s": now + 1.0,
                "source": "session_timeline",
                "sleep": {},
            })
            with patch.object(
                pod_app, "_timeline_restart_frame",
                return_value=newer_timeline,
            ):
                self.assertTrue(pod_app._restore_latest_sensor_frame())
            with patch.object(pod_app, "system_health_cached", return_value={}):
                restored = pod_app.snapshot()
            environment = restored["sensor"]["environment"]
            self.assertEqual(environment["temperature_c"], 23.4)
            self.assertEqual(environment["co2_ppm"], 812.0)
            self.assertEqual(environment["devices"]["sht3x_dis"]["status"], "stale")
            self.assertEqual(environment["live_count"], 0)
            temp = next(
                item for item in environment["assessment"]["evaluations"]
                if item["key"] == "temperature"
            )
            self.assertEqual(temp["display"], "23.4 °C")
            self.assertEqual(temp["status"], "unavailable")
            self.assertTrue(restored["sensor_frame"]["restored_after_restart"])
            self.assertEqual(restored["sensor"]["bcg"]["heart_rate_bpm"], 61.0)
            self.assertFalse(restored["sensor"]["bcg"]["analysis_valid"])
            self.assertTrue(restored["sleep"]["classification_active"])
            self.assertEqual(restored["sleep"]["confirmed_state"], "n3")
            self.assertEqual(
                restored["sleep"]["data_status"], "restored_confirmed_state"
            )
            self.assertTrue(restored["sleep"]["held_previous_state"])
            self.assertTrue(restored["sleep"]["display_only_after_restart"])
            # UI continuity must not fabricate a current physiological sample.
            self.assertIsNone(pod_app.take_session_sample()["sleep"])
        finally:
            pod_app.LAST_SENSOR_FRAME_PATH.unlink(missing_ok=True)
            with pod_app.state_lock:
                pod_app.state["session"] = original_session
            with pod_app.session_lock:
                pod_app._active_session = original_active
            with pod_app.analysis_frame_lock:
                pod_app._analysis_frame = original_frame
            with pod_app.sleep_path_lock:
                pod_app._sleep_stage_path.clear()
                pod_app._sleep_stage_path.update(original_path)
            pod_app._sleep_cache.clear()
            pod_app._sleep_cache.update(original_sleep_cache)

    def test_admin_can_end_or_kick_current_occupant(self) -> None:
        """Both Admin actions persist first; kick uses the broader revocation scope."""
        original = pod_app._authenticate_zeep_account

        def fake_auth(identifier: str, password: str):
            self.assertEqual(password, "valid-password")
            return ({
                "public_id": "public-admin-action-user",
                "username": "admin-action-user",
                "email": "admin-action-user@example.test",
                "display_name": "Admin Action User",
                "role": "user",
                "plan": "test",
                "access_token": "not-persisted",
                "refresh_token": None,
            }, {"gender": "female", "dateOfBirth": "1992-04-03"})

        pod_app._authenticate_zeep_account = fake_auth
        try:
            user = TestClient(pod_app.app)
            login = user.post(
                "/api/auth/login",
                json={"identifier": "admin-action-user", "password": "valid-password"},
            )
            self.assertEqual(login.status_code, 200, login.text)

            admin = TestClient(pod_app.app)
            admin_login = admin.post(
                "/api/admin/auth/login",
                json={"identifier": "test-admin", "password": "test-admin-password"},
            )
            self.assertEqual(admin_login.status_code, 200, admin_login.text)

            denied = user.post(
                "/api/admin/session/end",
                headers=csrf(user),
                json={"reason": "not_allowed"},
            )
            self.assertEqual(denied.status_code, 403, denied.text)

            ended = admin.post(
                "/api/admin/session/end",
                headers=csrf(admin),
                json={"reason": "admin_end_session_test"},
            )
            self.assertEqual(ended.status_code, 200, ended.text)
            self.assertEqual(ended.json()["action"], "end")
            self.assertGreaterEqual(ended.json()["revoked_browser_sessions"], 1)
            self.assertFalse(pod_app.ACTIVE_SESSION_CHECKPOINT_PATH.exists())
            self.assertEqual(user.get("/api/auth/me").status_code, 401)
            self.assertFalse(admin.get("/api/public/status").json()["occupied"])

            # A fresh Login can acquire the released Pod. Force-kick then
            # revokes every local User cookie for this immutable identity.
            relogin = user.post(
                "/api/auth/login",
                json={"identifier": "admin-action-user", "password": "valid-password"},
            )
            self.assertEqual(relogin.status_code, 200, relogin.text)
            kicked = admin.post(
                "/api/admin/session/kick",
                headers=csrf(admin),
                json={"reason": "admin_kick_occupant_test"},
            )
            self.assertEqual(kicked.status_code, 200, kicked.text)
            self.assertEqual(kicked.json()["action"], "kick")
            self.assertGreaterEqual(kicked.json()["revoked_browser_sessions"], 1)
            self.assertFalse(pod_app.ACTIVE_SESSION_CHECKPOINT_PATH.exists())
            self.assertEqual(user.get("/api/auth/me").status_code, 401)
            self.assertEqual(
                admin.post(
                    "/api/admin/session/kick",
                    headers=csrf(admin),
                    json={"reason": "nothing_to_kick"},
                ).status_code,
                409,
            )
        finally:
            if pod_app._active_session is not None:
                pod_app._finalize_active_session("admin_action_test_cleanup")
            pod_app._authenticate_zeep_account = original

    def test_sensor_calibration_is_admin_only_validated_and_auditable(self) -> None:
        anonymous = TestClient(pod_app.app)
        self.assertEqual(anonymous.get("/api/admin/calibration").status_code, 401)

        admin = TestClient(pod_app.app)
        login = admin.post(
            "/api/admin/auth/login",
            json={"identifier": "test-admin", "password": "test-admin-password"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        inspector = admin.get("/api/admin/calibration")
        self.assertEqual(inspector.status_code, 200, inspector.text)
        models = {channel["device"] for channel in inspector.json()["channels"]}
        self.assertEqual(
            models,
            {"SHT3x-DIS", "OPT3001", "SPH0645", "MH-Z19C",
             "PMS7003", "SGP40", "LSM-800-T"},
        )
        sound = next(
            channel for channel in inspector.json()["channels"]
            if channel["metric"] == "sound_dba_est"
        )
        self.assertEqual(sound["raw_unit"], "dBFS")
        self.assertEqual(sound["unit"], "dBA est.")
        self.assertEqual(sound["parameter_unit"], "%")
        self.assertEqual(
            sound["formula"],
            "round(abs(raw dBFS), 1) × (1 - error_percent / 100)",
        )

        previous_biases = dict(pod_app.SENSOR_BIASES)
        previous_sources = dict(pod_app.SENSOR_BIAS_SOURCES)
        previous_calibration = copy.deepcopy(pod_app.CALIBRATION)
        try:
            with patch.object(pod_app, "_persist_calibration") as persist:
                changed = admin.post(
                    "/api/admin/calibration/bias",
                    headers=csrf(admin),
                    json={"metric": "temperature_c", "bias": -0.7,
                          "reference_value": 23.5},
                )
                self.assertEqual(changed.status_code, 200, changed.text)
                self.assertEqual(changed.json()["update"]["bias"], -0.7)
                persist.assert_called_once()
            rejected = admin.post(
                "/api/admin/calibration/bias",
                headers=csrf(admin),
                json={"metric": "voc_index", "bias": 10},
            )
            self.assertEqual(rejected.status_code, 422)
        finally:
            with pod_app.SENSOR_CALIBRATION_LOCK:
                pod_app.SENSOR_BIASES.clear()
                pod_app.SENSOR_BIASES.update(previous_biases)
                pod_app.SENSOR_BIAS_SOURCES.clear()
                pod_app.SENSOR_BIAS_SOURCES.update(previous_sources)
                pod_app.CALIBRATION.clear()
                pod_app.CALIBRATION.update(previous_calibration)

    def test_aircon_on_sends_default_temperature_and_biases_user_temperature(self) -> None:
        """Exercise the Pi command sequence without publishing to real MQTT."""
        original_publish = pod_app.controlhub1_mqtt.publish_and_wait
        original_publish_sequence = pod_app.controlhub1_mqtt.publish_sequence_and_wait
        commands: list[str] = []
        sequence_gaps: list[float] | None = None

        def fake_publish(command: str) -> dict[str, object]:
            commands.append(command)
            return {"ok": True, "command": command, "tx_count": len(commands)}

        def fake_publish_sequence(
            sequence: list[str], _minimum_gaps: list[float] | None = None
        ) -> list[dict[str, object]]:
            nonlocal sequence_gaps
            sequence_gaps = _minimum_gaps
            return [fake_publish(command) for command in sequence]

        pod_app.controlhub1_mqtt.publish_and_wait = fake_publish
        pod_app.controlhub1_mqtt.publish_sequence_and_wait = fake_publish_sequence
        try:
            with pod_app.state_lock:
                pod_app.state["safety"]["latched"] = False
            turned_on = pod_app.aircon_command(pod_app.AirconCommand(command="on"))
            self.assertEqual(commands, ["on", "temp 18", "swing_on"])
            self.assertEqual(
                sequence_gaps,
                [
                    0.0,
                    pod_app.CONTROLHUB1_POWER_ON_SETTLE_SECONDS,
                    pod_app.CONTROLHUB1_MIN_IR_GAP_SECONDS,
                ],
            )
            self.assertEqual(turned_on["followup_command"], "temp 18")
            self.assertEqual(turned_on["swing_command"], "swing_on")
            self.assertEqual(turned_on["power_on_default_temperature_c"], 18)
            self.assertEqual(turned_on["delivery_status"], "ir_transmitted_unverified")
            self.assertFalse(turned_on["physical_confirmation"])

            commands.clear()
            coldest = pod_app.aircon_command(pod_app.AirconCommand(command="temp 15"))
            self.assertEqual(commands, ["temp 12"])
            self.assertEqual(coldest["desired_temperature_c"], 15)
            self.assertEqual(coldest["commanded_temperature_c"], 12)

            commands.clear()
            changed = pod_app.aircon_command(pod_app.AirconCommand(command="temp 20"))
            self.assertEqual(commands, ["temp 17"])
            self.assertEqual(changed["desired_temperature_c"], 20)
            self.assertEqual(changed["commanded_temperature_c"], 17)
        finally:
            pod_app.controlhub1_mqtt.publish_and_wait = original_publish
            pod_app.controlhub1_mqtt.publish_sequence_and_wait = original_publish_sequence

    def test_audio_track_change_reuses_live_mpv_process(self) -> None:
        """Changing tracks must keep ALSA/MPV open to avoid a silent restart gap."""
        player = object.__new__(pod_app.AudioPlayer)
        player.proc = SimpleNamespace(poll=lambda: None)
        player.sock_path = "/tmp/test-zeep-mpv.sock"
        player.lock = threading.Lock()
        player.backend = "mpv"
        player.audio_device = None
        player.music_dir = pod_app.MUSIC_DIR
        player.max_volume = pod_app.MAX_VOLUME
        player.state = pod_app.state
        player.state_lock = pod_app.state_lock
        player.loop = False
        player.current_path = None
        player.queue_paths = []
        player.queue_index = 0
        player._send_commands = MagicMock(return_value=True)
        player._stop_locked = MagicMock()
        target = pod_app.MUSIC_DIR / "Sleep-02-WindDown-Theta-Mix.wav"
        previous_music = copy.deepcopy(pod_app.state["music"])
        try:
            player.play(target, loop=True, queue=False)
            player._stop_locked.assert_not_called()
            player._send_commands.assert_called_once_with([
                ["loadfile", str(target), "replace"],
                ["set_property", "loop-file", "inf"],
                ["set_property", "pause", False],
            ])
            self.assertEqual(player.current_path, target)
            self.assertEqual(pod_app.state["music"]["track"], target.name)
            self.assertTrue(pod_app.state["music"]["playing"])
        finally:
            with pod_app.state_lock:
                pod_app.state["music"].clear()
                pod_app.state["music"].update(previous_music)

    def test_music_stop_returns_authoritative_stopped_state(self) -> None:
        """Stop ACK must let every tablet render the idle state immediately."""
        previous_music = copy.deepcopy(pod_app.state["music"])
        original_stop = pod_app.player.stop
        original_guard = pod_app.music_stop_guard_until

        def fake_stop() -> None:
            with pod_app.state_lock:
                pod_app.state["music"].update({
                    "playing": False,
                    "paused": False,
                    "track": None,
                    "loop": False,
                    "queue_position": 0,
                    "queue_length": 0,
                })

        try:
            pod_app.player.stop = fake_stop
            with pod_app.state_lock:
                pod_app.state["music"].update({
                    "playing": True,
                    "paused": False,
                    "track": "Sleep-01-Night-Delta-Mix.wav",
                    "queue_position": 1,
                    "queue_length": 5,
                })
            result = pod_app.music_stop()
            self.assertTrue(result["ok"])
            self.assertFalse(result["state"]["playing"])
            self.assertFalse(result["state"]["paused"])
            self.assertIsNone(result["state"]["track"])
            self.assertEqual(result["state"]["queue_position"], 0)
            self.assertEqual(result["state"]["queue_length"], 0)
        finally:
            pod_app.player.stop = original_stop
            pod_app.music_stop_guard_until = original_guard
            with pod_app.state_lock:
                pod_app.state["music"].clear()
                pod_app.state["music"].update(previous_music)

    def test_music_stop_guard_blocks_legacy_restart_but_allows_touch(self) -> None:
        """A stale browser cannot undo Stop; a new explicit Play can."""
        track = pod_app.MUSIC_DIR / "guard-test.wav"
        track.parent.mkdir(parents=True, exist_ok=True)
        track.write_bytes(b"test")
        original_play = pod_app.player.play
        original_guard = pod_app.music_stop_guard_until
        previous_safety = copy.deepcopy(pod_app.state["safety"])
        calls: list[str] = []

        def fake_play(path: Path, loop: bool = False, queue: bool = False) -> None:
            calls.append(path.name)

        try:
            pod_app.player.play = fake_play
            pod_app.music_stop_guard_until = (
                pod_app.time.monotonic() + pod_app.MUSIC_STOP_GUARD_SECONDS)
            with pod_app.state_lock:
                pod_app.state["safety"]["latched"] = False
            with self.assertRaises(pod_app.HTTPException) as blocked:
                pod_app.music_play(pod_app.TrackCommand(track=track.name))
            self.assertEqual(blocked.exception.status_code, 409)
            self.assertEqual(calls, [])

            result = pod_app.music_play(pod_app.TrackCommand(
                track=track.name, user_initiated=True))
            self.assertTrue(result["ok"])
            self.assertEqual(calls, [track.name])
        finally:
            pod_app.player.play = original_play
            pod_app.music_stop_guard_until = original_guard
            with pod_app.state_lock:
                pod_app.state["safety"].clear()
                pod_app.state["safety"].update(previous_safety)
            track.unlink(missing_ok=True)

    def test_aircon_ir_guard_waits_without_repeating_commands(self) -> None:
        """The guard delays one frame; it never retries a toggle command."""
        hub = pod_app.ControlHub1MQTT()
        hub._last_ir_ack_monotonic = 100.0
        original_monotonic = pod_app.time.monotonic
        original_sleep = pod_app.time.sleep
        sleeps: list[float] = []
        try:
            pod_app.time.monotonic = lambda: 100.3
            pod_app.time.sleep = sleeps.append
            waited = hub._wait_for_ir_guard("temp 10", 2.0)
            self.assertAlmostEqual(waited, 1.7)
            self.assertEqual(len(sleeps), 1)
            self.assertAlmostEqual(sleeps[0], 1.7)

            sleeps.clear()
            self.assertEqual(hub._wait_for_ir_guard("status", 2.0), 0.0)
            self.assertEqual(sleeps, [])
        finally:
            pod_app.time.monotonic = original_monotonic
            pod_app.time.sleep = original_sleep

    def test_admin_direct_temperature_and_fan_level_cycle(self) -> None:
        """FAN wakes the ESP first and advances only after its final ACK."""
        commands: list[str] = []
        sequences: list[tuple[list[str], list[float] | None]] = []

        def fake_publish(command: str) -> dict[str, object]:
            commands.append(command)
            return {"ok": True, "command": command, "tx_count": len(commands)}

        def fake_publish_sequence(
            sequence: list[str], minimum_gaps: list[float] | None = None
        ) -> list[dict[str, object]]:
            sequences.append((list(sequence), minimum_gaps))
            return [fake_publish(command) for command in sequence]

        admin = SimpleNamespace(is_admin=True)
        user = SimpleNamespace(is_admin=False)
        original_publish = pod_app.controlhub1_mqtt.publish_and_wait
        original_publish_sequence = pod_app.controlhub1_mqtt.publish_sequence_and_wait
        with pod_app.state_lock:
            original_aircon = copy.deepcopy(pod_app.state["aircon"])
            pod_app.state["safety"]["latched"] = False
            pod_app.state["aircon"]["fan_level"] = None
        pod_app.controlhub1_mqtt.publish_and_wait = fake_publish
        pod_app.controlhub1_mqtt.publish_sequence_and_wait = fake_publish_sequence
        try:
            direct = pod_app.aircon_command(
                pod_app.AirconCommand(command="temp 5", direct=True), admin
            )
            self.assertEqual(commands, ["temp 5"])
            self.assertTrue(direct["direct"])
            self.assertIsNone(direct["desired_temperature_c"])
            self.assertEqual(direct["commanded_temperature_c"], 5)

            with self.assertRaises(pod_app.HTTPException) as denied:
                pod_app.aircon_command(
                    pod_app.AirconCommand(command="temp 10", direct=True), user
                )
            self.assertEqual(denied.exception.status_code, 403)

            with patch.object(pod_app, "_persist_aircon_fan_level") as persist_fan:
                levels = [
                    pod_app.aircon_command(
                        pod_app.AirconCommand(command="fan"), admin
                    )["fan_level"]
                    for _ in range(6)
                ]
            self.assertEqual(levels, [1, 2, 3, 4, 5, 1])
            self.assertEqual(persist_fan.call_count, 6)
            self.assertEqual(
                sequences,
                [(["status", "fan"], [0.0, pod_app.CONTROLHUB1_FAN_WAKE_SETTLE_SECONDS])]
                * 6,
            )
            self.assertEqual(commands[1:], ["status", "fan"] * 6)
        finally:
            pod_app.controlhub1_mqtt.publish_and_wait = original_publish
            pod_app.controlhub1_mqtt.publish_sequence_and_wait = original_publish_sequence
            with pod_app.state_lock:
                pod_app.state["aircon"] = original_aircon

    def test_fan_preflight_failure_does_not_send_fan_or_advance_level(self) -> None:
        """A failed STATUS wake-up must abort before the toggle-style FAN IR."""
        admin = SimpleNamespace(is_admin=True)
        sent: list[str] = []

        def fail_during_preflight(
            sequence: list[str], _minimum_gaps: list[float] | None = None
        ) -> list[dict[str, object]]:
            sent.append(sequence[0])
            raise pod_app.HTTPException(504, "status ack timeout")

        with pod_app.state_lock:
            original_aircon = copy.deepcopy(pod_app.state["aircon"])
            pod_app.state["safety"]["latched"] = False
            pod_app.state["aircon"]["fan_level"] = 3
        try:
            with (
                patch.object(
                    pod_app.controlhub1_mqtt,
                    "publish_sequence_and_wait",
                    side_effect=fail_during_preflight,
                ),
                patch.object(pod_app, "_persist_aircon_fan_level") as persist_fan,
            ):
                with self.assertRaises(pod_app.HTTPException) as failed:
                    pod_app.aircon_command(
                        pod_app.AirconCommand(command="fan"), admin
                    )
            self.assertEqual(failed.exception.status_code, 504)
            self.assertEqual(sent, ["status"])
            persist_fan.assert_not_called()
            with pod_app.state_lock:
                self.assertEqual(pod_app.state["aircon"]["fan_level"], 3)
        finally:
            with pod_app.state_lock:
                pod_app.state["aircon"] = original_aircon

    def test_admin_can_persist_fan_reference_without_sending_ir(self) -> None:
        """Admin correction is durable metadata and never emits an IR command."""
        admin = SimpleNamespace(
            is_admin=True,
            username="test-admin",
            subject="local:test-admin",
        )
        with pod_app.state_lock:
            original_aircon = copy.deepcopy(pod_app.state["aircon"])
        try:
            with (
                patch.object(pod_app, "_persist_aircon_fan_level", return_value={
                    "fan_level": 4,
                    "source": "admin_declared_reference",
                    "updated_at": "2026-08-27T00:00:00+00:00",
                }) as persist,
                patch.object(pod_app.controlhub1_mqtt, "publish_and_wait") as publish,
            ):
                result = pod_app.set_aircon_fan_level_reference(
                    pod_app.AirconFanLevelReferenceCommand(level=4), admin
                )
            self.assertEqual(result["fan_level"], 4)
            self.assertTrue(result["persisted"])
            self.assertFalse(result["ir_transmitted"])
            self.assertEqual(result["fan_level_source"], "admin_declared_reference")
            persist.assert_called_once()
            publish.assert_not_called()
            with pod_app.state_lock:
                self.assertEqual(pod_app.state["aircon"]["fan_level"], 4)
        finally:
            with pod_app.state_lock:
                pod_app.state["aircon"] = original_aircon

    def test_fan_reference_survives_reload(self) -> None:
        """The 1..5 logical fan reference is recoverable after a Pi restart."""
        reference_path = _test_root / "fan-reference-test.json"
        with patch.object(pod_app, "AIRCON_CONTROL_STATE_PATH", reference_path):
            pod_app._persist_aircon_fan_level(
                3, "admin_declared_reference", operator="test-admin"
            )
            loaded = pod_app._load_aircon_fan_level_reference()
        self.assertEqual(loaded["fan_level"], 3)
        self.assertEqual(loaded["fan_level_source"], "admin_declared_reference")

    def test_user_fan_control_never_claims_a_measured_level(self) -> None:
        """User copy stays generic because the AC has no speed feedback."""
        ui = (Path(__file__).resolve().parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("const showFanReference=currentPrincipal?.role==='admin'", ui)
        self.assertIn("'ส่งคำสั่งปรับแรงลมแล้ว · กรุณาสังเกตการตอบสนองของแอร์'", ui)
        self.assertIn("ไม่แสดงระดับเพราะแอร์ไม่มีสถานะตอบกลับ", ui)
        self.assertIn("ค่าอ้างอิงตามคำสั่งล่าสุด", ui)

    def test_user_aircon_power_control_is_one_ack_driven_toggle(self) -> None:
        """The touch UI toggles from the latest ESP32-acknowledged reference."""
        ui = (Path(__file__).resolve().parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="unifiedAirconPowerBtn"', ui)
        self.assertIn("function unifiedAirconPowerToggle", ui)
        self.assertIn("const command=aircon.power===true?'off':'on'", ui)
        self.assertIn("สถานะอ้างอิงคำสั่ง IR ที่ ESP32 ยืนยันล่าสุด", ui)
        self.assertNotIn('id="unifiedAirconOnBtn"', ui)
        self.assertNotIn('id="unifiedAirconOffBtn"', ui)
        self.assertIn("คำสั่งล่าสุด · ON", ui)

    def test_fullscreen_control_is_shared_by_every_primary_view(self) -> None:
        """One common dock control remains available across all app views."""
        ui = (Path(__file__).resolve().parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        shell = (Path(__file__).resolve().parent / "static" / "app-shell.js").read_text(
            encoding="utf-8"
        )
        css = (Path(__file__).resolve().parent / "static" / "theme-modern.css").read_text(
            encoding="utf-8"
        )
        self.assertEqual(ui.count('id="appFullscreenBtn"'), 1)
        self.assertIn('src="/static/app-shell.js?', ui)
        self.assertIn("function toggleFullscreen", shell)
        self.assertIn("'dashboard', 'control', 'monitor', 'sessions'", shell)
        self.assertIn(".main-nav > .app-fullscreen-button", css)
        self.assertIn("body.control-focus-mode .top", css)

    def test_dashboard_has_non_diagnostic_health_reference_fields(self) -> None:
        ui = (Path(__file__).resolve().parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        for element_id in (
            "dashProfileGender", "dashProfileAge", "dashProfileHeight",
            "dashProfileWeight", "dashProfileBlood",
        ):
            self.assertIn(f'id="{element_id}"', ui)
        self.assertIn("แสดงเฉพาะข้อมูลจริงจาก Profile", ui)
        self.assertIn("ไม่ใช่การวินิจฉัย", ui)
        self.assertIn("อัปเดตจากบัญชี ZEEP เมื่อ Login", ui)
        self.assertIn("Profile API ไม่พร้อม", ui)

    def test_admin_dashboard_adds_insight_without_repeating_every_live_value(self) -> None:
        """Admin gets actionable context while the current-value cards stay canonical."""
        ui = (Path(__file__).resolve().parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        css = (Path(__file__).resolve().parent / "static" / "theme-modern.css").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="adminLiveExplanation" data-admin-panel', ui)
        self.assertIn('id="adminBioExplanation"', ui)
        self.assertIn('id="adminEnvironmentExplanation"', ui)
        self.assertIn("function renderAdminLiveExplanation", ui)
        self.assertIn("adminBaselineComparison(hr,baseline.hr", ui)
        self.assertIn("adminBaselineComparison(rr,baseline.rr", ui)
        self.assertIn("rawHr!==null", ui)
        self.assertIn("rawRr!==null", ui)
        self.assertIn("Sleep Stage เป็นค่าประเมินจาก BCG/HR/RR ไม่ใช่ผลยืนยันจาก PSG", ui)
        self.assertIn("SGP40 เป็น Adaptive VOC Index แบบสัมพัทธ์", ui)
        self.assertIn("ไม่ใช่เครื่องวัดเสียง Class 1", ui)
        self.assertIn("ค่าจริง · เทียบ Baseline และเกณฑ์ของโหมด", ui)
        self.assertIn("admin-live-explanation-metric-icon", ui)
        self.assertIn("ADMIN_EXPLANATION_STATUS", ui)
        self.assertIn("INSIGHTS &amp; ACTIONS", ui)
        self.assertIn('value:\'\',status:\'ใน Baseline\'', ui)
        self.assertIn("environmentRoot.innerHTML=evaluations.length?adminExplanationRow", ui)
        self.assertIn('<details class="admin-atmosphere-reference">', ui)
        self.assertIn("const actionRows=optimisationActions.map", ui)
        self.assertIn(".admin-atmosphere-reference-grid", css)
        self.assertIn('body:not([data-role="admin"]) [data-admin-panel]', css)

    def test_sensor_integrity_displays_every_sensor_and_primary_reading(self) -> None:
        ui = (Path(__file__).resolve().parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        for device in (
            "SHT3x-DIS", "OPT3001", "SPH0645", "MH-Z19C",
            "PMS7003", "SGP40", "LSM-800-T · BCG",
        ):
            self.assertIn(device, ui)
        self.assertIn("PM1.0 ${fmt(e.pm1_0_ug_m3,0)}", ui)
        self.assertIn("PM10 ${fmt(e.pm10_ug_m3,0)}", ui)
        self.assertIn("SRAW ${fmt(e.sgp40_raw,0)}", ui)
        self.assertIn("HR ${fmt(b.heart_rate_bpm,0)} BPM", ui)
        self.assertIn("RR ${fmt(b.respiration_rate,1)} ครั้ง/นาที", ui)
        self.assertIn("renderSensorIntegrity(env,b)", ui)

    def test_each_control_scene_has_one_short_purpose_caption(self) -> None:
        ui = (Path(__file__).resolve().parent / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        captions = (
            "เลื่อนเปิด–ปิดทางเข้า ZEEP",
            "ทำความเย็นและกระจายลมทั่ว ZEEP",
            "ปรับหัว–ปลายเตียงเพื่อความสบาย",
            "เลือกแสงเพดาน ดาว และแสงแดง",
            "เลือกเสียงและโหมดเล่นเพื่อผ่อนคลาย",
            "พ่นกลิ่นหรือไอน้ำจากปลายเตียง",
        )
        self.assertEqual(ui.count('class="control-scene-caption"'), len(captions))
        for caption in captions:
            self.assertIn(caption, ui)

    def test_approved_atmosphere_basis_drives_co2_and_temperature_alerts(self) -> None:
        """Good is quiet, Fair/Poor warn, and Critical uses the frozen basis."""
        now = pod_app.time.time()
        with pod_app.state_lock:
            original_sensor = copy.deepcopy(pod_app.state["sensor"])
            original_system = copy.deepcopy(pod_app.state["system"])
            original_session = copy.deepcopy(pod_app.state["session"])
            pod_app.state["sensor"]["esp32"]["last_update"] = now
            pod_app.state["system"]["gpio_available"] = True
            pod_app.state["session"].update({"active": False, "recording": False})

        def faults_for(co2: float, temperature: float) -> list[dict[str, object]]:
            environment = {
                "co2_ppm": co2,
                "temperature_c": temperature,
                "devices": {"mhz19c": {"status": "live"}},
            }
            with (
                patch.object(pod_app, "SAFETY_THRESHOLD_BASIS_VERSION",
                             "ZEEP-ATMOSPHERE-OPS-v1.0"),
                patch.object(pod_app, "SAFETY_THRESHOLD_BASIS_APPROVED", True),
                patch.object(pod_app, "build_environment_snapshot",
                             return_value=environment),
                patch.object(pod_app, "system_health_cached",
                             return_value={"wifi_connected": True}),
            ):
                return pod_app._safety_faults()

        try:
            good_codes = {fault["code"] for fault in faults_for(1000, 28)}
            self.assertNotIn("co2_warning", good_codes)
            self.assertNotIn("temperature_warning", good_codes)

            warning_codes = {fault["code"] for fault in faults_for(1001, 28.1)}
            self.assertIn("co2_warning", warning_codes)
            self.assertIn("temperature_warning", warning_codes)

            critical_codes = {fault["code"] for fault in faults_for(1300, 32.1)}
            self.assertIn("co2_critical", critical_codes)
            self.assertIn("temperature_critical", critical_codes)
        finally:
            with pod_app.state_lock:
                pod_app.state["sensor"] = original_sensor
                pod_app.state["system"] = original_system
                pod_app.state["session"] = original_session

    def test_sleep_quality_is_explainable_and_never_fabricated(self) -> None:
        """Completed sleep data gets a score; missing/active data does not."""
        quality = pod_app._sleep_quality_summary(
            8 * 3600,
            {
                "estimated_sleep_s": 7.2 * 3600,
                "sleep_efficiency": 0.90,
                "awakenings": 1,
                "deep_ratio": 0.18,
                "rem_ratio": 0.22,
            },
            {"wake": 96, "n2": 480, "n3": 108, "rem": 132},
            rest_mode="sleep",
        )
        # This fixture contains only 816 five-second stage rounds (68 minutes)
        # across an eight-hour wall-clock Session and no paired HR/RR samples.
        # The current wellness release gate must retain the explainable shadow
        # score for audit while withholding the public Sleep Score.
        self.assertFalse(quality["available"])
        self.assertIsNone(quality["score"])
        # Counts are the source of truth: 720 sleep / 816 scored rounds = 88%,
        # even when a legacy night_summary says 90%. The 8-hour wall duration
        # must not fabricate unobserved Sleep State coverage.
        # The opportunity component uses the 720 recorded sleep rounds (1 h),
        # not the legacy 7.2-hour summary value, so the shadow score remains
        # explainable without publishing an under-covered result.
        self.assertGreaterEqual(quality["engineering_shadow_score"], 65)
        self.assertEqual(quality["sleep_efficiency_pct"], 88)
        self.assertEqual(quality["deep_pct"], 15)
        self.assertEqual(set(quality["component_points"]),
                         {"sleep_opportunity", "sleep_stability",
                          "restorative_architecture", "cycle_expression",
                          "data_coverage"})
        self.assertNotIn("7 ชั่วโมง", quality["insight"])

        missing = pod_app._sleep_quality_summary(3600, {}, {}, completed=True)
        self.assertFalse(missing["available"])
        self.assertIsNone(missing["score"])
        all_wake = pod_app._sleep_quality_summary(
            3600, {"sleep_efficiency": 0.0, "awakenings": 0},
            {"wake": 120}, rest_mode="sleep")
        self.assertFalse(all_wake["available"])
        self.assertIsNone(all_wake["score"])
        self.assertEqual(all_wake["engineering_shadow_score"], 0)
        active = pod_app._sleep_quality_summary(
            8 * 3600, {"sleep_efficiency": 0.9}, completed=False)
        self.assertFalse(active["available"])
        self.assertIn("ยังไม่สิ้นสุด", active["reason"])

    def test_session_timeline_compresses_states_and_splits_sensor_gaps(self) -> None:
        points = [
            {"timestamp": "2026-01-01T00:00:05+00:00", "window_end": "2026-01-01T00:00:05+00:00",
             "state": "n2", "confidence": "medium", "probabilities": {"n2": 0.8},
             "metrics": {"mean_hr": 60, "mean_rr": 14, "bed_status": "On bed"}},
            {"timestamp": "2026-01-01T00:00:10+00:00", "window_end": "2026-01-01T00:00:10+00:00",
             "state": "n2", "confidence": "high", "probabilities": {"n2": 0.9},
             "metrics": {"mean_hr": 58, "mean_rr": 13, "bed_status": "On bed"}},
            # Same state but a 20-second data gap must start a new period.
            {"timestamp": "2026-01-01T00:00:30+00:00", "window_end": "2026-01-01T00:00:30+00:00",
             "state": "n2", "confidence": "low", "probabilities": {"n2": 0.7},
             "metrics": {"mean_hr": 62, "mean_rr": 15, "bed_status": "Moving"}},
            {"timestamp": "2026-01-01T00:00:35+00:00", "window_end": "2026-01-01T00:00:35+00:00",
             "state": "rem", "confidence": "medium", "probabilities": {"rem": 0.75},
             "metrics": {"mean_hr": 64, "mean_rr": 16, "bed_status": "On bed"}},
        ]
        periods = pod_app._compress_sleep_stage_points(
            points, report_end="2026-01-01T00:00:35+00:00")
        self.assertEqual([item["state"] for item in periods], ["n2", "n2", "rem"])
        self.assertEqual([item["round_count"] for item in periods], [2, 1, 1])
        self.assertEqual([item["duration_s"] for item in periods], [10.0, 5.0, 5.0])
        self.assertEqual(periods[0]["metrics"]["mean_hr"], 59.0)
        self.assertAlmostEqual(periods[0]["probabilities"]["n2"], 0.85)

    def test_user_can_occupy_in_any_safety_state_admin_can_monitor(self) -> None:
        original = pod_app._authenticate_zeep_account

        def fake_auth(identifier: str, password: str):
            self.assertEqual(password, "valid-password")
            return ({
                "public_id": "public-user-1",
                "username": "sleeper",
                "email": "sleeper@example.test",
                "display_name": "Sleeper",
                "role": "user",
                "plan": "test",
                "access_token": "not-persisted",
                "refresh_token": None,
            }, {"gender": "male", "dateOfBirth": "1990-01-01"})

        pod_app._authenticate_zeep_account = fake_auth
        try:
            with pod_app.state_lock:
                pod_app.state["safety"].update({
                    "ready": False, "armed": False, "latched": True,
                    "level": "emergency",
                })
            user = TestClient(pod_app.app)
            login = user.post(
                "/api/auth/login",
                json={"identifier": "sleeper", "password": "valid-password"},
            )
            self.assertEqual(login.status_code, 200, login.text)
            self.assertEqual(login.json()["principal"]["account_key"], "sleeper@example.test")
            self.assertEqual(login.json()["principal"]["display_name"], "Sleeper")
            user_state = user.get("/api/state")
            self.assertEqual(user_state.status_code, 200)
            self.assertFalse(user_state.json()["safety"]["ready"])
            self.assertFalse(user_state.json()["safety"]["armed"])
            self.assertTrue(user_state.json()["safety"]["latched"])
            self.assertEqual(user.get("/api/logs").status_code, 403)
            blocked_command = user.post("/api/door/close", headers=csrf(user))
            self.assertEqual(blocked_command.status_code, 423, blocked_command.text)

            duplicate = TestClient(pod_app.app).post(
                "/api/auth/login",
                json={"identifier": "sleeper", "password": "valid-password"},
            )
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(duplicate.json()["detail"]["code"], "pod_already_occupied")

            admin = TestClient(pod_app.app)
            self.assertEqual(admin.post(
                "/api/admin/auth/login",
                json={"identifier": "test-admin", "password": "test-admin-password"},
            ).status_code, 200)
            self.assertEqual(admin.get("/api/state").status_code, 200)

            ended = user.post("/api/session/logout", headers=csrf(user))
            self.assertEqual(ended.status_code, 200, ended.text)
            self.assertTrue(ended.json()["auth_retained"])
            self.assertFalse(ended.json()["recording_started"])
            self.assertIsNone(ended.json()["sleep_quality"])
            self.assertIsNone(ended.json()["session_report"])
            history = user.get("/api/history/sleeper%40example.test")
            self.assertEqual(history.status_code, 200)
            self.assertEqual(history.json()["total"], 0)
            detail = user.get(
                f"/api/history/sleeper%40example.test/{ended.json()['session_id']}"
            )
            self.assertEqual(detail.status_code, 404, detail.text)
            self.assertEqual(user.get("/api/history/other-user").status_code, 403)
            self.assertEqual(admin.get("/api/sessions").status_code, 200)
            self.assertEqual(user.post("/api/auth/logout", headers=csrf(user)).status_code, 200)
        finally:
            with pod_app.state_lock:
                pod_app.state["safety"].update({
                    "ready": False, "armed": False, "latched": False,
                    "level": "not_ready",
                })
            pod_app._authenticate_zeep_account = original

    def test_email_identity_survives_display_name_change(self) -> None:
        """Email remains canonical even when pre-recording Logins create no history."""
        original = pod_app._authenticate_zeep_account
        display_name = ["ชื่อเดิม"]

        def fake_auth(identifier: str, password: str):
            return ({
                "public_id": "public-rename-user",
                "username": "rename-user",
                "email": "Rename.User@Example.Test",
                "display_name": display_name[0],
                "role": "user",
                "plan": "test",
                "access_token": "not-persisted",
                "refresh_token": None,
            }, {"gender": "female", "dateOfBirth": "1991-02-03"})

        pod_app._authenticate_zeep_account = fake_auth
        try:
            user = TestClient(pod_app.app)
            first = user.post(
                "/api/auth/login",
                json={"identifier": "rename-user", "password": "valid-password"},
            )
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(
                first.json()["principal"]["account_key"], "rename.user@example.test"
            )
            first_end = user.post("/api/session/logout", headers=csrf(user))
            self.assertEqual(first_end.status_code, 200, first_end.text)
            self.assertEqual(user.post("/api/auth/logout", headers=csrf(user)).status_code, 200)

            display_name[0] = "ชื่อใหม่จากแอป"
            second = user.post(
                "/api/auth/login",
                json={"identifier": "rename-user", "password": "valid-password"},
            )
            self.assertEqual(second.status_code, 200, second.text)
            self.assertEqual(second.json()["principal"]["display_name"], "ชื่อใหม่จากแอป")
            second_end = user.post("/api/session/logout", headers=csrf(user))
            self.assertEqual(second_end.status_code, 200, second_end.text)

            history = user.get("/api/history/rename.user%40example.test")
            self.assertEqual(history.status_code, 200, history.text)
            self.assertEqual(history.json()["total"], 0)
            self.assertEqual(history.json()["account_key"], "rename.user@example.test")
            # A legacy page already open before the upgrade may still request
            # the old username. It resolves only through this same Profile's
            # recorded alias and returns the canonical email-keyed history.
            legacy = user.get("/api/history/rename-user")
            self.assertEqual(legacy.status_code, 200)
            self.assertEqual(legacy.json()["account_key"], "rename.user@example.test")
            self.assertEqual(user.get("/api/history/other-user").status_code, 403)

            with pod_app.profile_lock:
                profiles = pod_app._load_profiles()
            profile = profiles["rename.user@example.test"]
            self.assertEqual(profile["display_name"], "ชื่อใหม่จากแอป")
            self.assertEqual(profile["sessions"], 0)
        finally:
            if pod_app._active_session is not None:
                pod_app._finalize_active_session("test_cleanup")
            pod_app._authenticate_zeep_account = original

    def test_admin_profile_correction_updates_active_and_future_sessions(self) -> None:
        """A Pod-local alias/gender correction must not change email identity."""
        original = pod_app._authenticate_zeep_account
        external_name = ["Anonymous-263999"]

        def fake_auth(identifier: str, password: str):
            return ({
                "public_id": "public-noi-user",
                "username": "noi-login",
                "email": "noi@example.test",
                "display_name": external_name[0],
                "role": "user",
                "plan": "test",
                "access_token": "not-persisted",
                "refresh_token": None,
            }, {"gender": "unspecified", "dateOfBirth": "1974-01-01"})

        pod_app._authenticate_zeep_account = fake_auth
        try:
            user = TestClient(pod_app.app)
            login = user.post(
                "/api/auth/login",
                json={"identifier": "noi-login", "password": "valid-password"},
            )
            self.assertEqual(login.status_code, 200, login.text)
            session_id = login.json()["session"]["session_id"]
            self.assertEqual(login.json()["principal"]["display_name"], "Anonymous-263999")

            admin = TestClient(pod_app.app)
            self.assertEqual(admin.post(
                "/api/admin/auth/login",
                json={"identifier": "test-admin", "password": "test-admin-password"},
            ).status_code, 200)
            payload = {
                "session_id": session_id,
                "display_name": "Noi",
                "gender": "female",
                "reason": "verified_by_test_lead",
            }
            self.assertEqual(
                admin.post("/api/admin/session/profile", json=payload).status_code,
                403,
            )
            corrected = admin.post(
                "/api/admin/session/profile", json=payload, headers=csrf(admin)
            )
            self.assertEqual(corrected.status_code, 200, corrected.text)
            self.assertTrue(corrected.json()["account_key_unchanged"])
            self.assertEqual(corrected.json()["display_name"], "Noi")
            self.assertEqual(corrected.json()["gender"], "female")

            state = user.get("/api/state").json()
            self.assertEqual(state["auth"]["principal"]["display_name"], "Noi")
            self.assertEqual(state["session"]["display_name"], "Noi")
            self.assertEqual(state["session"]["gender"], "female")
            self.assertEqual(state["session"]["health_reference"]["gender"], "female")

            ended = user.post("/api/session/logout", headers=csrf(user))
            self.assertEqual(ended.status_code, 200, ended.text)
            self.assertEqual(user.post(
                "/api/auth/logout", headers=csrf(user)
            ).status_code, 200)

            # A later external displayName/gender response does not erase the
            # explicitly verified Pod research Profile correction.
            external_name[0] = "Changed Outside"
            again = user.post(
                "/api/auth/login",
                json={"identifier": "noi-login", "password": "valid-password"},
            )
            self.assertEqual(again.status_code, 200, again.text)
            self.assertEqual(again.json()["principal"]["display_name"], "Noi")
            self.assertEqual(again.json()["session"]["gender"], "female")
            self.assertEqual(
                again.json()["principal"]["account_key"], "noi@example.test"
            )
            self.assertEqual(user.post(
                "/api/session/logout", headers=csrf(user)
            ).status_code, 200)
            self.assertEqual(user.post(
                "/api/auth/logout", headers=csrf(user)
            ).status_code, 200)

            with pod_app.profile_lock:
                profile = pod_app._load_profiles()["noi@example.test"]
            self.assertEqual(profile["display_name_override"], "Noi")
            self.assertEqual(profile["gender_override"], "female")
        finally:
            if pod_app._active_session is not None:
                pod_app._finalize_active_session("test_cleanup")
            pod_app._authenticate_zeep_account = original


if __name__ == "__main__":
    unittest.main()
