"""Regression tests for the versioned, speaker-compatible Sound Lab."""
from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from brainwave_audio import (
    BRAINWAVE_AUDIO_VERSION,
    CHANNELS,
    MIN_PREVIEW_SECONDS,
    PEAK_LIMIT,
    PRESETS,
    SAMPLE_RATE,
    SAMPLE_WIDTH_BYTES,
    _pcm_chunks,
    public_presets,
    render_preview,
)


class BrainwaveAudioTests(unittest.TestCase):
    def test_catalog_is_versioned_and_includes_an_ab_control(self) -> None:
        catalog = public_presets()
        self.assertEqual(catalog["version"], BRAINWAVE_AUDIO_VERSION)
        ids = [item["id"] for item in catalog["presets"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("control-pink", ids)
        control = next(item for item in catalog["presets"] if item["id"] == "control-pink")
        self.assertTrue(all(p["modulation_hz"] == 0 for p in control["phases"]))
        self.assertTrue(catalog["limits"]["physical_spl_requires_meter"])

    def test_pcm_generation_is_deterministic(self) -> None:
        preset = PRESETS["relax-alpha"]
        first = next(iter(_pcm_chunks(preset, MIN_PREVIEW_SECONDS))).tobytes()
        second = next(iter(_pcm_chunks(preset, MIN_PREVIEW_SECONDS))).tobytes()
        self.assertEqual(first, second)

    def test_rendered_preview_is_valid_stereo_pcm_without_clipping(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = render_preview(
                "nap-theta-alpha", MIN_PREVIEW_SECONDS, Path(temp_dir)
            )
            with wave.open(str(result["path"]), "rb") as audio:
                self.assertEqual(audio.getnchannels(), CHANNELS)
                self.assertEqual(audio.getsampwidth(), SAMPLE_WIDTH_BYTES)
                self.assertEqual(audio.getframerate(), SAMPLE_RATE)
                self.assertEqual(
                    audio.getnframes(), MIN_PREVIEW_SECONDS * SAMPLE_RATE
                )
            self.assertLessEqual(result["peak"], PEAK_LIMIT + 0.001)
            self.assertGreater(result["rms"], 0.01)
            self.assertEqual(len(result["pcm_sha256"]), 64)

    def test_invalid_preset_and_duration_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unknown_preset"):
                render_preview("unknown", 30, Path(temp_dir))
            with self.assertRaisesRegex(ValueError, "duration_out_of_range"):
                render_preview("control-pink", 2, Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
