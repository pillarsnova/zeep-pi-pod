from __future__ import annotations

import pathlib
import sys
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from sensor_contracts import classify_hub_payload, decode_hub_payload  # noqa: E402
from sensor_runtime import normalize_hub1_sensor  # noqa: E402


class PiContractTests(unittest.TestCase):
    @staticmethod
    def canonical_packet(
        *, sht_live: bool, opt_live: bool, sph_live: bool,
    ) -> dict:
        return {
            "schema": "zeep.sensor.telemetry",
            "version": "1.0",
            "event": "environment",
            "source": "sensorhub1_firmware",
            "hub_id": "sensorhub1",
            "firmware_version": "sensorhub1-integrated-v2.0.0-rc1",
            "boot_id": 91,
            "sequence": 7,
            "monotonic_ms": 70_000,
            "sensors": {
                "sht3x_dis": {
                    "status": "live" if sht_live else "invalid",
                    "reason": "ok" if sht_live else "sht_crc_failed",
                    "values": {
                        "temperature_c": 24.3 if sht_live else None,
                        "humidity_rh": 51.2 if sht_live else None,
                    },
                },
                "opt3001": {
                    "status": "live" if opt_live else "invalid",
                    "reason": "ok" if opt_live else "opt_identity_mismatch",
                    "values": {"lux": 0.3 if opt_live else None},
                },
                "sph0645": {
                    "status": "live" if sph_live else "invalid",
                    "reason": "ok" if sph_live else "digital_silence",
                    "values": {
                        "sound_dbfs": -68.0 if sph_live else None,
                        "sound_laeq_dba": 55.0 if sph_live else None,
                        "sound_valid": sph_live,
                        "sound_weighting": "A",
                        "sound_metric": "LAeq",
                        "sound_window_ms": 10_000,
                        "sound_window_sequence": 7,
                    },
                },
            },
        }

    def test_replacement_firmware_packet_is_accepted(self) -> None:
        packet = {
            "schema_version": 1,
            "event": "environment",
            "source": "sensorhub1_firmware",
            "hub_id": "sensorhub1",
            "firmware_version": "sensorhub1-sph0645-laeq-v1.0.0",
            "temperature_c": 24.3,
            "humidity_rh": 51.2,
            "lux": 0.3,
            "sound_dbfs": -68.0,
            "sound_laeq_dba": 55.0,
            "sound_valid": True,
            "sound_weighting": "A",
            "sound_metric": "LAeq",
            "sound_window_ms": 10_000,
            "sound_samples": 480_000,
            "sensor_status": {
                "sht3x_dis": True,
                "opt3001": True,
                "sph0645": True,
            },
        }
        normalized = normalize_hub1_sensor(
            packet,
            sound_display_min=30.0,
            sound_display_max=130.0,
            sound_required_window_ms=10_000,
            sound_calibration_verified=True,
        )
        self.assertTrue(normalized["sound_measurement_valid"])
        self.assertEqual(normalized["sound_dba_est"], 55.0)
        self.assertEqual(normalized["temperature"], 24.3)
        self.assertEqual(normalized["humidity"], 51.2)

    def test_control_plane_events_never_replace_measurements(self) -> None:
        self.assertEqual(
            classify_hub_payload(
                {"event": "boot", "hub_id": "sensorhub1"},
                expected_hub="sensorhub1",
            ),
            ("ignored", "boot"),
        )
        self.assertEqual(
            classify_hub_payload(
                {"event": "calibration_response", "hub_id": "sensorhub1"},
                expected_hub="sensorhub1",
            ),
            ("ignored", "calibration_response"),
        )

    def test_legacy_flat_packet_is_accepted_for_rollback(self) -> None:
        self.assertEqual(
            classify_hub_payload(
                {"temperature_c": 24.0, "humidity_rh": 50.0},
                expected_hub="sensorhub1",
            ),
            ("telemetry", "legacy_environment"),
        )

    def test_all_three_sensor_fault_combinations_remain_independent(self) -> None:
        # Eight combinations prove that no individual sensor can make the
        # other two disappear from the Pi-side state.
        for mask in range(8):
            live = {
                "sht3x_dis": bool(mask & 0b001),
                "opt3001": bool(mask & 0b010),
                "sph0645": bool(mask & 0b100),
            }
            with self.subTest(live=live):
                packet = self.canonical_packet(
                    sht_live=live["sht3x_dis"],
                    opt_live=live["opt3001"],
                    sph_live=live["sph0645"],
                )
                self.assertEqual(
                    classify_hub_payload(
                        packet, expected_hub="sensorhub1"),
                    ("telemetry", "environment"),
                )
                decoded = decode_hub_payload(
                    packet, expected_hub="sensorhub1")
                self.assertEqual(decoded["boot_id"], 91)
                self.assertEqual(decoded["sound_window_sequence"], 7)
                self.assertEqual(decoded["sensor_status"], live)
                self.assertEqual(
                    set(decoded["sensor_diagnostics"]), set(live))
                normalized = normalize_hub1_sensor(
                    decoded,
                    sound_display_min=30.0,
                    sound_display_max=130.0,
                    sound_required_window_ms=10_000,
                    sound_calibration_verified=True,
                )
                self.assertEqual(
                    normalized["sound_measurement_valid"],
                    live["sph0645"],
                )
                self.assertEqual(
                    normalized.get("temperature") is not None,
                    live["sht3x_dis"],
                )
                self.assertEqual(
                    normalized.get("lux") is not None,
                    live["opt3001"],
                )


if __name__ == "__main__":
    unittest.main()
