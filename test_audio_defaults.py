"""Regression tests for the bedside audio defaults and idle policy."""

from __future__ import annotations

import threading
import unittest

from api_models import TrackCommand
from zeep_pod.hardware.audio import (
    DEFAULT_AUDIO_MODE,
    DEFAULT_AUDIO_VOLUME_PERCENT,
    AudioPlayer,
    default_music_state,
)


class AudioDefaultTests(unittest.TestCase):
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
        player = object.__new__(AudioPlayer)
        player.lock = threading.Lock()
        player.state_lock = threading.Lock()
        player.state = state
        player.loop = False
        player.current_path = None
        player.queue_paths = []
        player.queue_index = 0
        player.proc = None
        player.sock_path = "/tmp/zeep-audio-default-test.sock"

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
        player = object.__new__(AudioPlayer)
        player.lock = threading.Lock()
        player.state_lock = threading.Lock()
        player.state = state
        player.loop = False
        player.current_path = None
        player.queue_paths = []
        player.queue_index = 0
        player.proc = None
        player.sock_path = "/tmp/zeep-audio-default-test.sock"

        player.stop()

        self.assertEqual(state["music"]["mode"], "repeat_one")
        self.assertTrue(state["music"]["loop"])


if __name__ == "__main__":
    unittest.main()
