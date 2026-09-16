"""Regression tests for the bedside audio defaults and idle policy."""

from __future__ import annotations

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from api_models import TrackCommand
from hardware.audio import (
    DEFAULT_AUDIO_MODE,
    DEFAULT_AUDIO_VOLUME_PERCENT,
    AudioPlayer,
    default_music_state,
)


class AudioDefaultTests(unittest.TestCase):
    @staticmethod
    def _player(state, music_dir):
        return AudioPlayer(
            music_dir=music_dir,
            max_volume=100,
            state=state,
            state_lock=threading.Lock(),
        )

    def test_default_contract_is_manual_play_repeat_one_at_sixty_percent(self):
        command = TrackCommand(track="test.wav")

        self.assertEqual(DEFAULT_AUDIO_MODE, "repeat_one")
        self.assertEqual(DEFAULT_AUDIO_VOLUME_PERCENT, 60)
        self.assertTrue(command.loop)
        self.assertTrue(command.resolved_loop)
        self.assertFalse(command.queue)
        self.assertEqual(default_music_state()["volume"], 60)
        self.assertEqual(default_music_state()["mode"], "repeat_one")

    def test_stop_preserves_the_selected_mode_and_volume(self):
        state = {
            "music": {
                "playing": True,
                "paused": False,
                "track": "test.wav",
                "volume": 42,
                "loop": False,
                "mode": "queue",
                "queue_position": 2,
                "queue_length": 3,
            }
        }
        with TemporaryDirectory() as temporary:
            player = self._player(state, Path(temporary))
            player.stop()

        self.assertFalse(state["music"]["playing"])
        self.assertEqual(state["music"]["volume"], 42)
        self.assertEqual(state["music"]["mode"], "queue")
        self.assertFalse(state["music"]["loop"])

    def test_stop_repairs_an_unknown_idle_mode_to_repeat_one(self):
        state = {
            "music": {
                "playing": True,
                "paused": False,
                "track": "test.wav",
                "volume": DEFAULT_AUDIO_VOLUME_PERCENT,
                "loop": False,
                "mode": "single",
            }
        }
        with TemporaryDirectory() as temporary:
            player = self._player(state, Path(temporary))
            player.stop()

        self.assertEqual(state["music"]["mode"], "repeat_one")
        self.assertTrue(state["music"]["loop"])

    def test_snapshot_is_music_only_and_detached(self):
        state = {"music": default_music_state(), "system": {"private": True}}
        with TemporaryDirectory() as temporary:
            player = self._player(state, Path(temporary))

            result = player.snapshot()

        self.assertNotIn("system", result)
        result["volume"] = 1
        self.assertEqual(state["music"]["volume"], DEFAULT_AUDIO_VOLUME_PERCENT)


if __name__ == "__main__":
    unittest.main()
