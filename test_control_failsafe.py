"""Synthetic regressions for physical command deadlines and safety races."""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException

from hardware import controlhub1, controlhub2
from hardware.bed_motion import BedMotionService


class FakeTimer:
    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.cancelled = False
        self.started = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def join(self, timeout=None):
        pass


class ControlFailsafeTests(unittest.TestCase):
    def test_emergency_latches_before_stop_or_other_device_effects(self):
        from testing_support import configure_app_test_environment

        configure_app_test_environment()
        import app

        previous_safety = dict(app.state["safety"])
        effects = []

        def observe_effect(*args):
            try:
                app._require_safety_allows("Bed head_up")
            except HTTPException as exc:
                effects.append(exc.status_code)
            else:
                effects.append(None)
            return True

        try:
            with app.state_lock:
                app.state["safety"]["latched"] = False
            with (
                patch.object(app.player, "stop", side_effect=observe_effect),
                patch.object(app.gpio, "set", side_effect=observe_effect),
                patch.object(
                    app.controlhub2_bed_mqtt,
                    "publish_stop_best_effort",
                    side_effect=observe_effect,
                ),
                patch.object(app, "_refresh_active_session_safety_checkpoint"),
            ):
                app.apply_safety_profile("synthetic-race-test")
            self.assertTrue(effects)
            self.assertEqual(set(effects), {423})
        finally:
            with app.state_lock:
                app.state["safety"].clear()
                app.state["safety"].update(previous_safety)

    def test_published_movement_has_stop_deadline_even_when_ack_is_lost(self):
        state = {"bed_control": {"connected": True, "last_update": time.time()}}
        hub = controlhub2.ControlHub2BedMQTT()
        hub.motion._timer_factory = FakeTimer
        client = Mock()
        client.is_connected.return_value = True
        client.publish.return_value = SimpleNamespace(rc=0)
        hub._set_client(client)
        with patch.multiple(
            controlhub2,
            create=True,
            state=state,
            state_lock=threading.Lock(),
            STALE_SECONDS=10.0,
            ACK_TIMEOUT_SECONDS=0.001,
            COMMAND_TOPIC="synthetic/bed/command",
            mqtt=SimpleNamespace(MQTT_ERR_SUCCESS=0),
            log_event=Mock(),
            safety_allows=Mock(),
        ):
            try:
                with self.assertRaises(HTTPException) as raised:
                    hub.publish_and_wait("head_up")
                self.assertEqual(raised.exception.status_code, 504)
                self.assertTrue(state["bed_control"].get("auto_stop_pending"))
                self.assertIsNotNone(state["bed_control"].get("auto_stop_at"))
                hub.motion._timer.callback()
                self.assertEqual(
                    [call.args[1] for call in client.publish.call_args_list],
                    ["head_up", "bed_stop"],
                )
                self.assertFalse(state["bed_control"]["auto_stop_pending"])
            finally:
                if hasattr(hub, "motion"):
                    hub.motion.close()

    def test_aircon_rechecks_safety_after_ir_delay_before_publish(self):
        state = {"aircon": {"connected": True, "last_update": time.time()}}
        hub = controlhub1.ControlHub1MQTT()
        client = Mock()
        client.is_connected.return_value = True
        client.publish.return_value = SimpleNamespace(rc=0)
        hub._set_client(client)
        safety = Mock(side_effect=HTTPException(423, "Safety latched"))
        with (
            patch.multiple(
                controlhub1,
                create=True,
                state=state,
                state_lock=threading.Lock(),
                CONTROLHUB1_STALE_SECONDS=10.0,
                CONTROLHUB1_ACK_TIMEOUT_SECONDS=0.001,
                CONTROLHUB1_COMMAND_TOPIC="synthetic/aircon/command",
                mqtt=SimpleNamespace(MQTT_ERR_SUCCESS=0),
                log_event=Mock(),
                safety_allows=safety,
            ),
            patch.object(hub, "_wait_for_ir_guard"),
        ):
            with self.assertRaises(HTTPException) as raised:
                hub.publish_and_wait("temp 18")
            self.assertEqual(raised.exception.status_code, 423)
            client.publish.assert_not_called()
            safety.assert_called_once_with("Air Con temp 18")

    def test_aircon_sequence_stops_at_latch_but_off_and_status_stay_available(self):
        state = {"aircon": {"connected": True, "last_update": time.time()}}
        hub = controlhub1.ControlHub1MQTT()
        client = Mock()
        client.is_connected.return_value = True
        hub._set_client(client)
        latched = False
        commands = []

        def guard(action):
            if latched:
                raise HTTPException(423, "Safety latched")

        def publish(_topic, command, **kwargs):
            nonlocal latched
            commands.append(command)
            with hub._ack_condition:
                hub._ack_seq += 1
                hub._last_ack = ({"command": command, "ok": True}, time.time())
            if command == "on":
                latched = True
            return SimpleNamespace(rc=0)

        client.publish.side_effect = publish
        with (
            patch.multiple(
                controlhub1,
                create=True,
                state=state,
                state_lock=threading.Lock(),
                CONTROLHUB1_STALE_SECONDS=10.0,
                CONTROLHUB1_ACK_TIMEOUT_SECONDS=0.1,
                CONTROLHUB1_COMMAND_TOPIC="synthetic/aircon/command",
                mqtt=SimpleNamespace(MQTT_ERR_SUCCESS=0),
                log_event=Mock(),
                safety_allows=guard,
            ),
            patch.object(hub, "_wait_for_ir_guard"),
        ):
            with self.assertRaises(HTTPException) as raised:
                hub.publish_sequence_and_wait(["on", "temp 18", "swing_on"])
            self.assertEqual(raised.exception.status_code, 423)
            self.assertEqual(commands, ["on"])
            self.assertFalse(state["aircon"]["command_pending"])
            hub.publish_and_wait("off")
            hub.publish_and_wait("status")
            self.assertEqual(commands, ["on", "off", "status"])


class BedMotionServiceTests(unittest.TestCase):
    def setUp(self):
        self.timers = []
        self.published = []
        self.state = {}
        self.stop = Mock(
            side_effect=lambda reason: self.published.append("stop") or True
        )

        def timer_factory(interval, callback):
            timer = FakeTimer(interval, callback)
            self.timers.append(timer)
            return timer

        self.service = BedMotionService(
            duration_seconds=2.0,
            publish_stop=self.stop,
            update_state=self.state.update,
            log_event=Mock(),
            clock=lambda: 100.0,
            timer_factory=timer_factory,
        )

    def tearDown(self):
        self.service.close()

    def move(self, command="head_up"):
        self.service.publish(command, lambda: self.published.append(command))

    def test_deadline_starts_at_publication_not_ack(self):
        self.move()
        self.assertEqual(self.state["auto_stop_at"], 102.0)
        self.assertTrue(self.timers[0].started)
        self.assertEqual(self.timers[0].interval, 2.0)
        self.timers[0].callback()
        self.assertEqual(self.published, ["head_up", "stop"])
        self.assertFalse(self.state["auto_stop_pending"])

    def test_cancelled_old_timer_cannot_stop_new_motion(self):
        self.move()
        self.move("foot_down")
        self.assertTrue(self.timers[0].cancelled)
        self.timers[0].callback()
        self.assertEqual(self.published, ["head_up", "foot_down"])
        self.assertTrue(self.state["auto_stop_pending"])
        self.timers[1].callback()
        self.assertEqual(self.published, ["head_up", "foot_down", "stop"])

    def test_new_motion_cannot_overtake_timer_stop_after_generation_check(self):
        stop_entered = threading.Event()
        release_stop = threading.Event()
        movement_attempted = threading.Event()

        def blocking_stop(reason):
            self.published.append("stop_enter")
            stop_entered.set()
            if not release_stop.wait(2):
                raise RuntimeError("test failed to release stop")
            self.published.append("stop_done")
            return True

        def new_movement():
            movement_attempted.set()
            self.move("foot_down")

        self.stop.side_effect = blocking_stop
        self.move()
        old_worker = threading.Thread(target=self.timers[0].callback)
        new_worker = threading.Thread(target=new_movement)
        old_worker.start()
        try:
            self.assertTrue(stop_entered.wait(1))
            self.assertFalse(self.service._lock.acquire(blocking=False))
            new_worker.start()
            self.assertTrue(movement_attempted.wait(1))
            self.assertEqual(self.published, ["head_up", "stop_enter"])
        finally:
            release_stop.set()
            old_worker.join(2)
            if new_worker.ident is not None:
                new_worker.join(2)
        self.assertFalse(old_worker.is_alive())
        self.assertFalse(new_worker.is_alive())
        self.assertEqual(
            self.published, ["head_up", "stop_enter", "stop_done", "foot_down"]
        )

    def test_explicit_stop_cancels_timer_but_publish_failure_does_not(self):
        self.move()
        with self.assertRaises(OSError):
            self.service.publish("bed_stop", Mock(side_effect=OSError("offline")))
        self.assertFalse(self.timers[0].cancelled)
        self.assertTrue(self.state["auto_stop_pending"])
        self.move("bed_stop")
        self.assertTrue(self.timers[0].cancelled)
        self.timers[0].callback()
        self.stop.assert_not_called()

    def test_failed_movement_publish_preserves_previous_deadline(self):
        self.move()
        with self.assertRaises(OSError):
            self.service.publish("foot_down", Mock(side_effect=OSError("offline")))
        self.assertEqual(len(self.timers), 1)
        self.timers[0].callback()
        self.assertEqual(self.published, ["head_up", "stop"])

    def test_timer_start_failure_stops_immediately(self):
        timer = FakeTimer(2, lambda: None)
        timer.start = Mock(side_effect=RuntimeError("no threads"))
        self.service._timer_factory = Mock(return_value=timer)
        with self.assertRaisesRegex(RuntimeError, "no threads"):
            self.move()
        self.assertEqual(self.published, ["head_up", "stop"])
        self.assertFalse(self.state["auto_stop_pending"])

    def test_stop_failure_is_visible_and_not_silently_retried(self):
        self.stop.side_effect = None
        self.stop.return_value = False
        self.move()
        self.timers[0].callback()
        self.assertEqual(self.state["auto_stop_error"], "publish_failed")
        self.stop.assert_called_once()

    def test_shutdown_stops_pending_motion_once_and_rejects_new_movement(self):
        self.move()
        self.service.close()
        self.service.close()
        self.assertEqual(self.published, ["head_up", "stop"])
        self.timers[0].callback()
        self.stop.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, "shutting down"):
            self.move("foot_down")

    def test_constructor_and_idle_shutdown_do_not_touch_hardware(self):
        self.service.close()
        self.stop.assert_not_called()
        self.assertEqual(self.timers, [])


if __name__ == "__main__":
    unittest.main()
