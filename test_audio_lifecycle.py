"""Regression tests for import-safe and deterministic audio lifecycle."""

from __future__ import annotations

import ast
import io
import subprocess
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from hardware.audio import AudioPlayer, default_music_state
from hardware.audio_process import AudioProcessAdapter
from hardware.audio_runtime import (
    AudioRuntimeSelection,
    SystemAudioRuntimeAdapter,
    select_audio_runtime,
)


class StubDiscovery:
    """Count discovery calls while returning one fixed contract."""

    def __init__(self, selection: AudioRuntimeSelection) -> None:
        self.selection = selection
        self.calls = 0

    def discover(self) -> AudioRuntimeSelection:
        self.calls += 1
        return self.selection


class FailOnceDiscovery(StubDiscovery):
    """Expose a retryable first-start failure."""

    def discover(self) -> AudioRuntimeSelection:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("probe failed")
        return self.selection


class FailOnceLock:
    """Context lock that rejects its first publication attempt."""

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def __enter__(self) -> FailOnceLock:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("publish failed")
        self._lock.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self._lock.release()


class FakeProcess:
    """Small terminating process double for watcher shutdown tests."""

    pid = 321
    stderr = None

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.waiting = threading.Event()
        self.finished = threading.Event()
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15
        self.finished.set()

    def kill(self) -> None:
        self.returncode = -9
        self.finished.set()

    def wait(self, timeout: float | None = None) -> int:
        self.waiting.set()
        if not self.finished.wait(timeout=timeout):
            raise subprocess.TimeoutExpired("fake-player", timeout)
        return int(self.returncode or 0)


class AudioRuntimeSelectionTests(unittest.TestCase):
    def test_pure_selector_preserves_backend_order_and_requested_device(self) -> None:
        selected = select_audio_runtime(
            {"ffplay", "mpv", "afplay"},
            requested_device="  alsa/custom  ",
            default_alsa_device_present=True,
        )

        self.assertEqual(selected.backend, "mpv")
        self.assertEqual(selected.audio_device, "alsa/custom")

    def test_system_adapter_uses_default_usb_device_only_for_mpv(self) -> None:
        probed: list[Path] = []
        adapter = SystemAudioRuntimeAdapter(
            executable_lookup=lambda name: f"/bin/{name}" if name == "mpv" else None,
            environment_lookup=lambda _name: "",
            path_probe=lambda path: probed.append(path) or True,
        )

        selected = adapter.discover()

        self.assertEqual(selected.backend, "mpv")
        self.assertEqual(
            selected.audio_device,
            "alsa/plughw:CARD=Device,DEV=0",
        )
        self.assertEqual(probed, [Path("/proc/asound/Device")])

    def test_system_adapter_skips_alsa_probe_without_mpv(self) -> None:
        adapter = SystemAudioRuntimeAdapter(
            executable_lookup=lambda name: "/bin/ffplay" if name == "ffplay" else None,
            environment_lookup=lambda _name: None,
            path_probe=lambda _path: self.fail("unexpected ALSA probe"),
        )

        self.assertEqual(
            adapter.discover(),
            AudioRuntimeSelection("ffplay", None),
        )


class AudioProcessAdapterTests(unittest.TestCase):
    def test_socket_path_factory_is_lazy_and_missing_socket_is_unavailable(
        self,
    ) -> None:
        calls: list[str] = []
        adapter = AudioProcessAdapter(
            socket_path_factory=lambda: calls.append("resolve") or "/tmp/audio.sock"
        )

        self.assertEqual(calls, [])
        self.assertFalse(adapter.send(None, ["get_property", "pause"]))
        self.assertFalse(adapter.send_commands(None, [["get_property", "pause"]]))
        self.assertEqual(adapter.resolve_socket_path(), "/tmp/audio.sock")
        self.assertEqual(calls, ["resolve"])

    def test_mpv_spawn_preserves_device_loop_volume_and_ipc_contract(self) -> None:
        adapter = AudioProcessAdapter()
        track = Path("/music/Sleep.wav")

        with patch("hardware.audio_process.subprocess.Popen") as popen:
            adapter.spawn(
                backend="mpv",
                audio_device="alsa/test",
                socket_path="/tmp/mpv.sock",
                file_path=track,
                volume=60,
                loop=True,
            )

        command = popen.call_args.args[0]
        self.assertEqual(command[0], "mpv")
        self.assertIn("--volume=60", command)
        self.assertIn("--loop-file=inf", command)
        self.assertIn("--input-ipc-server=/tmp/mpv.sock", command)
        self.assertIn("--audio-device=alsa/test", command)
        self.assertEqual(command[-1], str(track))

    def test_fallback_spawn_preserves_volume_and_loop_contracts(self) -> None:
        adapter = AudioProcessAdapter()
        track = Path("/music/Sleep.wav")

        with patch("hardware.audio_process.subprocess.Popen") as popen:
            adapter.spawn(
                backend="afplay",
                audio_device=None,
                socket_path=None,
                file_path=track,
                volume=125,
                loop=False,
            )
            afplay = popen.call_args.args[0]
            adapter.spawn(
                backend="ffplay",
                audio_device=None,
                socket_path=None,
                file_path=track,
                volume=-5,
                loop=True,
            )
            ffplay = popen.call_args.args[0]

        self.assertEqual(afplay, ["afplay", "-v", "1.00", str(track)])
        self.assertIn("-volume", ffplay)
        self.assertEqual(ffplay[ffplay.index("-volume") + 1], "0")
        self.assertIn("-loop", ffplay)
        self.assertEqual(ffplay[-1], str(track))

    def test_process_error_is_bounded_to_the_latest_thousand_characters(self) -> None:
        detail = "prefix-" + ("x" * 1100) + "-tail"
        process = SimpleNamespace(
            stderr=io.StringIO(detail),
            returncode=2,
        )

        result = AudioProcessAdapter.process_error(process)

        self.assertEqual(len(result), 1000)
        self.assertTrue(result.endswith("-tail"))


class AudioPlayerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.state = {
            "music": default_music_state(),
            "system": {"player": None},
        }
        self.discovery = StubDiscovery(AudioRuntimeSelection("mpv", "alsa/test"))
        self.player = AudioPlayer(
            music_dir=Path(self.temporary.name),
            max_volume=100,
            state=self.state,
            state_lock=threading.Lock(),
            runtime_discovery=self.discovery,
        )

    def tearDown(self) -> None:
        self.player.shutdown()
        self.temporary.cleanup()

    def test_constructor_does_not_discover_or_publish_runtime(self) -> None:
        self.assertEqual(self.discovery.calls, 0)
        self.assertFalse(self.player.initialized)
        self.assertIsNone(self.player.backend)
        self.assertIsNone(self.player.sock_path)
        self.assertNotIn("audio_device", self.state["system"])

    def test_constructor_does_not_resolve_host_socket_path(self) -> None:
        calls: list[str] = []
        adapter = AudioProcessAdapter(
            socket_path_factory=lambda: calls.append("resolve") or "/tmp/audio.sock"
        )
        player = AudioPlayer(
            music_dir=Path(self.temporary.name),
            max_volume=100,
            state=self.state,
            state_lock=threading.Lock(),
            runtime_discovery=self.discovery,
            process_adapter=adapter,
        )

        self.assertEqual(calls, [])
        self.assertIsNone(player.sock_path)

        player.initialize()

        self.assertEqual(calls, ["resolve"])
        self.assertEqual(player.sock_path, "/tmp/audio.sock")
        player.shutdown()

    def test_initialize_is_idempotent_and_publishes_contract(self) -> None:
        first = self.player.initialize()
        second = self.player.initialize()

        self.assertEqual(first, AudioRuntimeSelection("mpv", "alsa/test"))
        self.assertEqual(second, first)
        self.assertEqual(self.discovery.calls, 1)
        self.assertTrue(self.player.initialized)
        self.assertEqual(self.state["system"]["player"], "mpv")
        self.assertEqual(self.state["system"]["audio_device"], "alsa/test")

    def test_concurrent_initialize_discovers_once(self) -> None:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(lambda _index: self.player.initialize(), range(8))
            )

        self.assertEqual(self.discovery.calls, 1)
        self.assertTrue(all(result.backend == "mpv" for result in results))

    def test_failed_discovery_can_retry_without_partial_publication(self) -> None:
        discovery = FailOnceDiscovery(AudioRuntimeSelection("afplay", None))
        player = AudioPlayer(
            music_dir=Path(self.temporary.name),
            max_volume=100,
            state=self.state,
            state_lock=threading.Lock(),
            runtime_discovery=discovery,
        )

        with self.assertRaisesRegex(RuntimeError, "probe failed"):
            player.initialize()
        self.assertFalse(player.initialized)
        self.assertIsNone(self.state["system"]["player"])

        self.assertEqual(player.initialize().backend, "afplay")
        self.assertEqual(discovery.calls, 2)
        player.shutdown()

    def test_failed_publication_can_retry_without_partial_runtime(self) -> None:
        discovery = StubDiscovery(AudioRuntimeSelection("mpv", "alsa/test"))
        player = AudioPlayer(
            music_dir=Path(self.temporary.name),
            max_volume=100,
            state=self.state,
            state_lock=FailOnceLock(),
            runtime_discovery=discovery,
        )

        with self.assertRaisesRegex(RuntimeError, "publish failed"):
            player.initialize()
        self.assertFalse(player.initialized)
        self.assertIsNone(player.backend)
        self.assertIsNone(player.audio_device)

        self.assertEqual(player.initialize().backend, "mpv")
        self.assertEqual(discovery.calls, 2)
        player.shutdown()

    def test_shutdown_stops_process_drains_watcher_and_clears_runtime(self) -> None:
        self.player.initialize()
        process = FakeProcess()
        self.player.proc = process
        self.player.current_path = Path(self.temporary.name) / "sleep.wav"
        self.player._watchers.start(process, self.player._watch)
        self.assertTrue(process.waiting.wait(timeout=1))

        self.player.shutdown()

        self.assertTrue(process.terminated)
        self.assertFalse(self.player.initialized)
        self.assertIsNone(self.state["system"]["player"])
        self.assertIsNone(self.state["system"]["audio_device"])
        self.assertEqual(self.player._watchers.active_count, 0)

    def test_shutdown_failure_is_reported_without_escaping_teardown(self) -> None:
        self.player.initialize()

        def fail_drain(_timeout: float) -> tuple[str, ...]:
            raise RuntimeError("drain failed")

        output = io.StringIO()

        with (
            patch.object(self.player._watchers, "drain", side_effect=fail_drain),
            redirect_stdout(output),
        ):
            self.player.shutdown()

        self.assertIn("shutdown incomplete", output.getvalue())
        self.assertIn("watcher drain failed", output.getvalue())
        self.assertFalse(self.player.initialized)
        self.assertIsNone(self.state["system"]["player"])

    def test_watcher_start_failure_rolls_back_spawned_process(self) -> None:
        process = FakeProcess()
        self.player._spawn = lambda _path, _volume: process

        def fail_start(*_args: object) -> None:
            raise RuntimeError("thread start failed")

        self.player._watchers.start = fail_start

        with self.assertRaisesRegex(RuntimeError, "thread start failed"):
            self.player.play(Path(self.temporary.name) / "sleep.wav")

        self.assertTrue(process.terminated)
        self.assertIsNone(self.player.proc)
        self.assertFalse(self.state["music"]["playing"])

    def test_shutdown_waits_for_starting_play_and_stops_its_process(self) -> None:
        entered_spawn = threading.Event()
        release_spawn = threading.Event()
        shutdown_done = threading.Event()
        process = FakeProcess()
        errors: list[Exception] = []

        def slow_spawn(_path: Path, _volume: int) -> FakeProcess:
            entered_spawn.set()
            release_spawn.wait(timeout=2)
            return process

        def play() -> None:
            try:
                self.player.play(Path(self.temporary.name) / "sleep.wav")
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        def shutdown() -> None:
            self.player.shutdown()
            shutdown_done.set()

        self.player._spawn = slow_spawn
        play_thread = threading.Thread(target=play)
        shutdown_thread = threading.Thread(target=shutdown)
        play_thread.start()
        self.assertTrue(entered_spawn.wait(timeout=1))
        shutdown_thread.start()
        time.sleep(0.05)
        self.assertFalse(shutdown_done.is_set())

        release_spawn.set()
        play_thread.join(timeout=2)
        shutdown_thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertFalse(play_thread.is_alive())
        self.assertFalse(shutdown_thread.is_alive())
        self.assertTrue(process.terminated)
        self.assertFalse(self.player.initialized)

    def test_closed_runtime_rejects_lazy_play_until_explicit_initialize(self) -> None:
        self.player.shutdown()

        with self.assertRaisesRegex(RuntimeError, "closed"):
            self.player.play(Path(self.temporary.name) / "sleep.wav")

        self.player.initialize()
        self.assertTrue(self.player.initialized)


class AppAudioLifecycleWiringTests(unittest.TestCase):
    @staticmethod
    def _app_tree() -> ast.Module:
        source = (Path(__file__).resolve().parent / "app.py").read_text(
            encoding="utf-8"
        )
        return ast.parse(source)

    def test_gpio_and_audio_initialize_only_in_ordered_lifespan(self) -> None:
        tree = self._app_tree()
        lifespan = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        )
        calls = {
            node.func.value.id: node.lineno
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "initialize"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"gpio", "player"}
        }

        self.assertEqual(sorted(calls, key=calls.get), ["gpio", "player"])
        global_calls = [
            node
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "initialize"
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "player"
        ]
        self.assertEqual(global_calls, [])

    def test_lifespan_and_poweroff_use_final_audio_shutdown(self) -> None:
        tree = self._app_tree()
        lifespan = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        )
        guarded = [
            node
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Try)
            and any(
                isinstance(child, ast.Yield)
                for item in node.body
                for child in ast.walk(item)
            )
            and any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "shutdown"
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "player"
                for item in node.finalbody
                for child in ast.walk(item)
            )
        ]
        self.assertEqual(len(guarded), 1)
        finalbody = guarded[0].finalbody
        shutdown_line = next(
            child.lineno
            for item in finalbody
            for child in ast.walk(item)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "shutdown"
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "player"
        )
        flush_line = next(
            child.lineno
            for item in finalbody
            for child in ast.walk(item)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "flush"
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "database"
        )
        self.assertLess(flush_line, shutdown_line)

        poweroff = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_graceful_poweroff"
        )
        player_calls = {
            child.func.attr
            for child in ast.walk(poweroff)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "player"
        }
        self.assertIn("shutdown", player_calls)
        self.assertNotIn("stop", player_calls)


if __name__ == "__main__":
    unittest.main()
