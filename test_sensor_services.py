"""Unit contracts for side-effect-free Sensor and Shadow services."""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sensor_calibration import (
    SENSOR_CALIBRATION_SPECS,
    apply_additive_bias,
    load_calibration,
    persist_calibration,
    resolve_biases,
)
from sensor_contracts import ENVIRONMENT_DEVICE_SPECS
from sensor_runtime import (
    compose_environment_snapshot,
    energy_average_db,
    hold_last_valid_sound,
    normalize_hub1_sensor,
)
from smart_response import SmartResponsePolicy, evaluate_smart_response


NOW = 1_800_000_000.0


class CalibrationServiceTests(unittest.TestCase):
    def test_round_trip_and_resolution_preserve_existing_config_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "calibration.json"
            persist_calibration(path, {"pm10_bias": -2.5, "humidity_rh_bias": 0.0})
            document = load_calibration(path)
        biases, sources = resolve_biases(
            document,
            sound_error_percent=0.0,
            sound_source="calibration.json",
            humidity_bias=0.0,
            humidity_source="calibration.json",
        )
        self.assertEqual(SENSOR_CALIBRATION_SPECS["pm10_ug_m3"]["config_key"], "pm10_bias")
        self.assertEqual(biases["pm10_ug_m3"], -2.5)
        self.assertEqual(sources["sound_dba_est"], "calibration.json")

    def test_additive_bias_is_bounded_and_unknown_metric_passes_through(self) -> None:
        biases = {"humidity_rh": 5.0}
        self.assertEqual(apply_additive_bias("humidity_rh", 99.0, biases=biases), 100.0)
        self.assertEqual(apply_additive_bias("unknown", 12.3, biases=biases), 12.3)
        self.assertIsNone(apply_additive_bias("humidity_rh", None, biases=biases))


class SensorRuntimeTests(unittest.TestCase):
    def test_sound_pipeline_keeps_raw_and_uses_zero_percent_transform(self) -> None:
        normalized = normalize_hub1_sensor(
            {"sound_dbfs": -39.69},
            sound_error_percent=0.0,
            sound_display_max=120.0,
        )
        self.assertEqual(normalized["sound_dbfs"], -39.69)
        self.assertEqual(normalized["sound_dbfs_magnitude"], 39.7)
        self.assertEqual(normalized["sound_dba_est"], 39.7)
        self.assertEqual(normalized["sound_error_percent"], 0.0)
        self.assertEqual(
            energy_average_db([40.0, 50.0], display_min=0.0, display_max=120.0),
            47.4,
        )

    def test_missing_sound_holds_last_valid_value_without_touching_raw(self) -> None:
        current = {"sound_dbfs": float("nan")}
        held = hold_last_valid_sound(
            current,
            {"sound_dba_est": 38.2},
            display_min=0.0,
            display_max=120.0,
        )
        self.assertEqual(held["sound_dba_est"], 38.2)
        self.assertTrue(held["sound_value_held"])

    def test_two_hub_composition_has_one_canonical_value_per_metric(self) -> None:
        hub1 = {
            "connected": True,
            "last_update": NOW,
            "temperature": 24.0,
            "humidity": 50.0,
            "lux": 2.0,
            "sound_dba_est": 35.0,
            "sensor_status": {"sht3x_dis": True, "opt3001": True, "sph0645": True},
        }
        hub2 = {
            "connected": True,
            "last_update": NOW,
            "co2_ppm": 700.0,
            "pm1_0_ug_m3": 1.0,
            "pm2_5_ug_m3": 2.0,
            "pm10_ug_m3": 3.0,
            "voc_index": 100.0,
            "sgp40_raw": 30_000.0,
            "sensor_status": {"mhz19c": True, "pms7003": True, "sgp40": True},
        }
        biases = {metric: 0.0 for metric in SENSOR_CALIBRATION_SPECS}
        result = compose_environment_snapshot(
            hub1,
            hub2,
            now=NOW,
            hub1_stale_s=20.0,
            hub2_stale_s=20.0,
            device_specs=ENVIRONMENT_DEVICE_SPECS,
            calibration_metrics=tuple(SENSOR_CALIBRATION_SPECS),
            apply_bias=lambda metric, value: apply_additive_bias(metric, value, biases=biases),
            bias_value=lambda metric: biases[metric],
            bias_sources={metric: "default" for metric in biases},
        )
        self.assertEqual(result["status"], "live")
        self.assertEqual(result["live_count"], 6)
        self.assertEqual(result["temperature_c"], 24.0)
        self.assertEqual(result["co2_ppm"], 700.0)


class SmartResponseServiceTests(unittest.TestCase):
    def test_shadow_evaluator_reports_critical_air_without_actuation(self) -> None:
        policy = SmartResponsePolicy(
            version="test-policy",
            temperature_min_c=18.0,
            temperature_max_c=27.0,
            co2_warn_ppm=1000.0,
            co2_critical_ppm=1300.0,
            sound_sleep_target_dba=35.0,
        )
        devices = {
            key: {"model": key, "status": "live"}
            for key in ("mhz19c", "pms7003", "sgp40")
        }
        result = evaluate_smart_response({
            "sensor": {"environment": {
                "devices": devices,
                "temperature_c": 24.0,
                "humidity_rh": 50.0,
                "co2_ppm": 1400.0,
                "pm2_5_ug_m3": 2.0,
                "voc_index": 100.0,
                "sound_dba_est": 33.0,
                "lux": 0.2,
            }},
            "safety": {"ready": True, "armed": True},
            "aircon": {"connected": True, "stale": False},
            "session": {"active": True, "recording": True},
        }, policy, now=NOW)
        air = next(item for item in result["recommendations"] if item["domain"] == "air")
        self.assertEqual(air["level"], "critical")
        self.assertFalse(result["automatic_actuation"])
        self.assertFalse(result["sleep_stage_used"])


if __name__ == "__main__":
    unittest.main()
