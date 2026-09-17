"""Static gates for the compatibility-first Smart Ear firmware layout."""

from __future__ import annotations

import pathlib
import unittest


FIRMWARE_ROOT = pathlib.Path(__file__).parents[1]


class FirmwareArchitectureTests(unittest.TestCase):
    def test_production_partition_layout_is_preserved(self) -> None:
        table = (
            FIRMWARE_ROOT / "partitions" / "zeep_production_16mb.csv"
        ).read_text(encoding="utf-8")
        for required in (
            "nvs,      data, nvs,     0x9000,   0x5000",
            "app0,     app,  ota_0,   0x10000,  0x300000",
            "app1,     app,  ota_1,   0x310000, 0x300000",
            "ffat,     data, fat,     0x610000, 0x9e0000",
            "coredump, data, coredump,0xff0000, 0x10000",
        ):
            self.assertIn(required, table)

    def test_usb_jsonl_has_sdk_debug_disabled(self) -> None:
        configuration = (FIRMWARE_ROOT / "platformio.ini").read_text(
            encoding="utf-8"
        )
        self.assertIn("CORE_DEBUG_LEVEL=0", configuration)
        self.assertNotIn("CORE_DEBUG_LEVEL=1", configuration)

    def test_meter_and_dsp_windows_are_independent(self) -> None:
        source = (FIRMWARE_ROOT / "src" / "audio_meter.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "kMeterWindowSamples = kSampleRateHz;",
            source,
        )
        self.assertIn(
            "kAcousticWindowSamples = kSampleRateHz * 10;",
            source,
        )
        self.assertNotIn("acoustic_classifier_.reset();\n}", source.split(
            "void AudioMeter::resetWindowAccumulator()", 1
        )[1].split("void AudioMeter::resetAcousticAccumulator()", 1)[0])

    def test_i2c_devices_are_identified_across_datasheet_addresses(self) -> None:
        board = (FIRMWARE_ROOT / "include" / "board_config.h").read_text(
            encoding="utf-8"
        )
        self.assertIn("kSht3xAddresses[] = {0x44, 0x45}", board)
        self.assertIn(
            "kOpt3001Addresses[] = {0x44, 0x45, 0x46, 0x47}",
            board,
        )

    def test_telemetry_exposes_feature_window_provenance(self) -> None:
        source = (
            FIRMWARE_ROOT / "src" / "telemetry_publisher.cpp"
        ).read_text(encoding="utf-8")
        for field in (
            "sound_feature_window_ms",
            "sound_feature_sequence",
            "sound_feature_age_ms",
            "sound_alignment_errors",
        ):
            self.assertIn(field, source)

    def test_production_dma_preserves_complete_24_bit_word(self) -> None:
        source = (FIRMWARE_ROOT / "src" / "audio_meter.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn("raw_sample >> kPcmTransportPaddingBits", source)
        self.assertIn("kPcmTransportPaddingBits = 8", source)
        self.assertNotIn('invalid_reason = "pcm_alignment_error"', source)

    def test_production_microphone_uses_observed_right_slot(self) -> None:
        meter = (FIRMWARE_ROOT / "src" / "audio_meter.cpp").read_text(
            encoding="utf-8"
        )
        telemetry = (
            FIRMWARE_ROOT / "src" / "telemetry_publisher.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn("I2S_CHANNEL_FMT_ONLY_RIGHT", meter)
        self.assertIn('detail["i2s_slot"] = "right"', telemetry)


if __name__ == "__main__":
    unittest.main()
