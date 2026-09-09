from __future__ import annotations

import pathlib
import sys
import unittest


REPOSITORY_ROOT = pathlib.Path(__file__).parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))

from sensor_runtime import normalize_hub1_sensor  # noqa: E402


class PiContractTests(unittest.TestCase):
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
        )
        self.assertTrue(normalized["sound_measurement_valid"])
        self.assertEqual(normalized["sound_dba_est"], 55.0)
        self.assertEqual(normalized["temperature"], 24.3)
        self.assertEqual(normalized["humidity"], 51.2)


if __name__ == "__main__":
    unittest.main()
