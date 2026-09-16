"""Direct tests for audio policy without importing the Pi application."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi import HTTPException

from api_models import BrainwavePreviewCommand, TrackCommand, VolumeCommand
from hardware.audio_api import AudioControlService, create_audio_router


class FakePlayer:
    def __init__(self, music: dict[str, object], backend: str = "mpv") -> None:
        self.music = music
        self.backend = backend
        self.play_calls: list[tuple[Path, bool, bool]] = []
        self.pause_result = True

    def play(self, path: Path, loop: bool = False, queue: bool = False) -> None:
        self.play_calls.append((path, loop, queue))
        self.music.update(
            {
                "playing": True,
                "paused": False,
                "track": path.name,
                "loop": loop,
            }
        )

    def stop(self) -> None:
        self.music.update(
            {
                "playing": False,
                "paused": False,
                "track": None,
                "loop": False,
            }
        )

    def pause_toggle(self) -> bool:
        if self.pause_result:
            self.music["paused"] = not bool(self.music.get("paused"))
        return self.pause_result

    def set_volume(self, volume: int) -> None:
        self.music["volume"] = volume


class AudioControlServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.music_dir = self.root / "music"
        self.preview_dir = self.root / "preview"
        self.music_dir.mkdir()
        self.clock = [100.0]
        self.music: dict[str, object] = {
            "playing": False,
            "paused": False,
            "track": None,
            "volume": 60,
            "loop": True,
        }
        self.player = FakePlayer(self.music)
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.activities: list[tuple[str, object]] = []
        self.occupancy_token: str | None = None
        self.rendered = {
            "path": self.preview_dir / "preview.wav",
            "file": "preview.wav",
            "preset_id": "control-pink",
            "version": "test-v1",
            "duration_seconds": 30,
        }
        self.service = self._service()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _service(self, *, backend: str = "mpv") -> AudioControlService:
        self.player.backend = backend
        return AudioControlService(
            player=self.player,
            music_dir=self.music_dir,
            preview_dir=self.preview_dir,
            command_lock=threading.Lock(),
            stop_guard_seconds=4.0,
            occupancy_token=lambda: self.occupancy_token,
            safety_guard=lambda action: self.events.append(((action,), {})),
            snapshot_music=lambda: dict(self.music),
            note_activity=lambda kind, value: self.activities.append((kind, value)),
            logger=lambda *args, **kwargs: self.events.append((args, kwargs)),
            presets=lambda: {"version": "catalog-v1", "presets": []},
            render_preview=lambda *_args: dict(self.rendered),
            monotonic=lambda: self.clock[0],
        )

    def test_play_preserves_repeat_queue_rules_and_stop_guard(self) -> None:
        track = self.music_dir / "Sleep.wav"
        track.write_bytes(b"audio")

        with self.assertRaises(HTTPException) as blocked:
            self.service.play(TrackCommand(track=track.name))
        self.assertEqual(blocked.exception.status_code, 409)

        repeated = self.service.play(
            TrackCommand(track=track.name, user_initiated=True)
        )
        queued = self.service.play(
            TrackCommand(track=track.name, queue=True, user_initiated=True)
        )
        self.assertEqual(
            [(loop, queue) for _, loop, queue in self.player.play_calls],
            [(True, False), (False, True)],
        )
        self.assertEqual((repeated["loop"], repeated["queue"]), (True, False))
        self.assertEqual((queued["loop"], queued["queue"]), (False, True))

        stopped = self.service.stop()
        self.assertFalse(stopped["state"]["playing"])
        self.assertEqual(self.service.stop_guard_until, 104.0)
        self.clock[0] = 104.1
        self.service.play(TrackCommand(track=track.name))

    def test_track_must_be_a_contained_existing_file(self) -> None:
        outside = self.root / "outside.wav"
        outside.write_bytes(b"audio")
        for track in ("../outside.wav", "missing.wav"):
            with self.subTest(track=track):
                with self.assertRaises(HTTPException) as raised:
                    self.service.play(TrackCommand(track=track, user_initiated=True))
                self.assertEqual(raised.exception.status_code, 404)

    def test_music_list_filters_extensions_and_volume_uses_player_state(self) -> None:
        (self.music_dir / "B.WAV").write_bytes(b"audio")
        (self.music_dir / "a.mp3").write_bytes(b"audio")
        (self.music_dir / "notes.txt").write_text("ignore", encoding="utf-8")
        outside = self.root / "outside.wav"
        outside.write_bytes(b"outside")
        (self.music_dir / "escape.wav").symlink_to(outside)

        result = self.service.list_music()
        self.assertEqual(result["tracks"], ["B.WAV", "a.mp3"])
        self.assertEqual(result["player"], "mpv")
        self.assertEqual(
            self.service.set_volume(VolumeCommand(volume=42))["volume"], 42
        )

    def test_brainwave_requires_confirmation_and_hides_local_path(self) -> None:
        self.occupancy_token = "session-a"
        command = BrainwavePreviewCommand(preset_id="control-pink")
        with self.assertRaises(HTTPException) as blocked:
            self.service.brainwave_preview(
                command,
                SimpleNamespace(username="admin"),
            )
        self.assertEqual(blocked.exception.status_code, 409)

        command.confirm_occupied = True
        result = self.service.brainwave_preview(
            command,
            SimpleNamespace(username="admin"),
        )
        self.assertNotIn("path", result["render"])
        self.assertTrue(result["occupied"])
        self.assertEqual(
            self.player.play_calls[-1], (self.rendered["path"], False, False)
        )
        self.assertEqual(self.activities[-1][0], "music")

    def test_preview_rejects_an_occupant_change_during_render(self) -> None:
        def render_then_change(*_args):
            self.occupancy_token = "session-b"
            return dict(self.rendered)

        self.service.render_preview = render_then_change

        with self.assertRaises(HTTPException) as changed:
            self.service.brainwave_preview(
                BrainwavePreviewCommand(preset_id="control-pink"),
                SimpleNamespace(username="admin"),
            )

        self.assertEqual(changed.exception.status_code, 409)
        self.assertEqual(self.player.play_calls, [])

    def test_preview_render_is_single_flight(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        errors: list[Exception] = []

        def slow_render(*_args):
            entered.set()
            release.wait(timeout=2)
            return dict(self.rendered)

        def first_request() -> None:
            try:
                self.service.brainwave_preview(
                    BrainwavePreviewCommand(preset_id="control-pink"),
                    SimpleNamespace(username="admin"),
                )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        self.service.render_preview = slow_render
        worker = threading.Thread(target=first_request)
        worker.start()
        self.assertTrue(entered.wait(timeout=1))
        try:
            with self.assertRaises(HTTPException) as busy:
                self.service.brainwave_preview(
                    BrainwavePreviewCommand(preset_id="control-pink"),
                    SimpleNamespace(username="admin"),
                )
            self.assertEqual(busy.exception.status_code, 429)
        finally:
            release.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(self.player.play_calls), 1)

    def test_brainwave_maps_renderer_and_volume_errors(self) -> None:
        def invalid_preset(*_args):
            raise ValueError("unknown_preset")

        self.service.render_preview = invalid_preset
        with self.assertRaises(HTTPException) as missing:
            self.service.brainwave_preview(
                BrainwavePreviewCommand(preset_id="missing"),
                SimpleNamespace(username="admin"),
            )
        self.assertEqual(missing.exception.status_code, 404)

        with self.assertRaises(HTTPException) as volume:
            self.service.brainwave_preview(
                BrainwavePreviewCommand(preset_id="control-pink", volume=61),
                SimpleNamespace(username="admin"),
            )
        self.assertEqual(volume.exception.status_code, 422)

    def test_pause_distinguishes_fallback_from_unready_mpv(self) -> None:
        self.player.pause_result = False
        fallback = self._service(backend="afplay")
        with self.assertRaises(HTTPException) as unsupported:
            fallback.pause()
        self.assertEqual(unsupported.exception.status_code, 501)

        mpv = self._service(backend="mpv")
        with self.assertRaises(HTTPException) as unavailable:
            mpv.pause()
        self.assertEqual(unavailable.exception.status_code, 503)

    def test_router_preserves_all_existing_endpoint_methods(self) -> None:
        def authenticated():
            return SimpleNamespace(username="tester")

        router = create_audio_router(
            self.service,
            require_admin=authenticated,
            require_pod_operator=authenticated,
        )
        contracts = {
            (route.path, method) for route in router.routes for method in route.methods
        }
        self.assertEqual(
            contracts,
            {
                ("/api/admin/brainwave/presets", "GET"),
                ("/api/admin/brainwave/preview", "POST"),
                ("/api/music", "GET"),
                ("/api/music/play", "POST"),
                ("/api/music/stop", "POST"),
                ("/api/music/pause", "POST"),
                ("/api/music/volume", "POST"),
            },
        )


if __name__ == "__main__":
    unittest.main()
