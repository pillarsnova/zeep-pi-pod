"""Unit contracts for side-effect-free Sensor and Shadow services."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from sensor_calibration import (
    SENSOR_CALIBRATION_SPECS,
    apply_additive_bias,
    load_calibration,
    persist_calibration,
    resolve_biases,
    sound_inspector_channel,
)
from sensor_contracts import (
    ENVIRONMENT_DEVICE_SPECS,
    SOUND_DBA_DISPLAY_MAX,
    SOUND_DBA_DISPLAY_MIN,
    SOUND_SENSOR_MODEL,
    classify_hub_payload,
)
from sensor_runtime import (
    compose_environment_snapshot,
    energy_average_db,
    hold_last_valid_sound,
    normalize_hub1_sensor,
    source_freshness,
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
            humidity_bias=0.0,
            humidity_source="calibration.json",
        )
        self.assertEqual(SENSOR_CALIBRATION_SPECS["pm10_ug_m3"]["config_key"], "pm10_bias")
        self.assertEqual(biases["pm10_ug_m3"], -2.5)
        self.assertNotIn("sound_dba_est", sources)

    def test_additive_bias_is_bounded_and_unknown_metric_passes_through(self) -> None:
        biases = {"humidity_rh": 5.0}
        self.assertEqual(apply_additive_bias("humidity_rh", 99.0, biases=biases), 100.0)
        self.assertEqual(apply_additive_bias("unknown", 12.3, biases=biases), 12.3)
        self.assertIsNone(apply_additive_bias("humidity_rh", None, biases=biases))

    def test_approved_sht3x_field_biases_match_reference_pair(self) -> None:
        document = load_calibration(Path(__file__).with_name("calibration.json"))
        self.assertEqual(document["temperature_c_bias"], 0.2)
        self.assertEqual(document["humidity_rh_bias"], -7.0)
        self.assertEqual(
            document["sound_processing"]["status"],
            "active_direct_passthrough",
        )
        self.assertEqual(
            document["sound_processing"]["source_field"],
            "sound_dba",
        )
        self.assertEqual(document["sound_processing"]["pi_transform"], "none")
        self.assertEqual(
            document["sound_processing"]["calibration_status"],
            "not_applied_on_pi",
        )
        self.assertNotIn(
            "historical_provisional_display", document["sound_processing"],
        )
        self.assertNotIn("historical_sound_photo_audit", document)
        biases, _ = resolve_biases(
            document,
            humidity_bias=float(document["humidity_rh_bias"]),
            humidity_source="calibration.json",
        )
        self.assertEqual(
            apply_additive_bias("temperature_c", 18.2, biases=biases),
            18.4,
        )
        self.assertEqual(
            apply_additive_bias("humidity_rh", 68.0, biases=biases),
            61.0,
        )

    def test_sound_inspector_reports_direct_pipeline_without_calibration_gate(
        self,
    ) -> None:
        channel = sound_inspector_channel(
            {
                "sound_dba": 39.8,
                "sound_measurement_valid": True,
            },
            {"sound_dba_est": 39.8},
            {
                "status": "live",
                "source_label": "Hub 1 · USB",
                "data_age_s": 1.0,
            },
        )

        self.assertEqual(channel["device"], SOUND_SENSOR_MODEL)
        self.assertEqual(channel["raw"], 39.8)
        self.assertEqual(channel["calibrated"], 39.8)
        self.assertEqual(channel["bias"], 0.0)
        self.assertFalse(channel["editable"])
        self.assertEqual(channel["pipeline_state"], "direct")
        self.assertEqual(channel["formula"], "ESP32 sound_dba → Pi โดยตรง")
        self.assertNotIn("engineering", channel)
        self.assertNotIn("calibration_state", channel)


class SensorRuntimeTests(unittest.TestCase):
    def test_ten_second_hub_cadence_has_explicit_stale_boundary(self) -> None:
        at_boundary = source_freshness(
            {"connected": True, "last_update": NOW - 25.0},
            25.0,
            NOW,
        )
        missed_boundary = source_freshness(
            {"connected": True, "last_update": NOW - 25.001},
            25.0,
            NOW,
        )
        self.assertTrue(at_boundary["live"])
        self.assertFalse(missed_boundary["live"])

    def test_legacy_dbfs_is_kept_raw_and_marked_invalid(self) -> None:
        normalized = normalize_hub1_sensor(
            {"sound_dbfs": -39.69},
            sound_display_min=SOUND_DBA_DISPLAY_MIN,
            sound_display_max=SOUND_DBA_DISPLAY_MAX,
        )
        self.assertEqual(normalized["sound_dbfs"], -39.69)
        self.assertNotIn("sound_dba_est", normalized)
        self.assertFalse(normalized["sound_measurement_valid"])
        self.assertEqual(normalized["sound_invalid_reason"], "legacy_dbfs_only")

    def test_direct_sound_dba_is_canonical_without_metadata_gates(self) -> None:
        packet = {
            "event": "environment",
            "hub_id": "sensorhub1",
            "profile": "any-firmware-profile",
            "sound_dba": 53.86,
            "sound_window_ms": 1_000,
            "sound_weighting": "Z",
            "sound_metric": "PEAK",
            "sound_valid": False,
            "mic_capture_ok": False,
            "mic_signal_valid": False,
        }
        disposition, _ = classify_hub_payload(
            packet,
            expected_hub="sensorhub1",
        )
        self.assertEqual(disposition, "telemetry")
        normalized = normalize_hub1_sensor(
            packet,
            sound_display_min=SOUND_DBA_DISPLAY_MIN,
            sound_display_max=SOUND_DBA_DISPLAY_MAX,
        )
        self.assertEqual(normalized["sound_dba"], 53.86)
        self.assertEqual(normalized["sound_dba_est"], 53.86)
        self.assertTrue(normalized["sound_measurement_valid"])
        self.assertNotIn("sound_invalid_reason", normalized)
        self.assertEqual(
            normalized["sound_processing_source"],
            "esp32_sound_dba_direct",
        )
        self.assertNotIn("sound_dba_firmware_est", normalized)
        self.assertNotIn("sound_preview_evidence_count", normalized)

    def test_sound_energy_average_remains_energy_domain(self) -> None:
        self.assertEqual(
            energy_average_db(
                [40.0, 50.0],
                display_min=SOUND_DBA_DISPLAY_MIN,
                display_max=SOUND_DBA_DISPLAY_MAX,
            ),
            47.4,
        )

    def test_sound_reference_range_boundaries_are_inclusive(self) -> None:
        for level in (SOUND_DBA_DISPLAY_MIN, SOUND_DBA_DISPLAY_MAX):
            with self.subTest(level=level):
                normalized = normalize_hub1_sensor(
                    {"sound_dba": level},
                    sound_display_min=SOUND_DBA_DISPLAY_MIN,
                    sound_display_max=SOUND_DBA_DISPLAY_MAX,
                )
                self.assertEqual(normalized["sound_dba_est"], level)
                self.assertTrue(normalized["sound_measurement_valid"])

    def test_sound_dba_rejects_missing_bool_nonfinite_and_out_of_range(
        self,
    ) -> None:
        cases = (
            ({}, "missing_sound_dba"),
            ({"sound_dba": True}, "invalid_sound_dba_type"),
            ({"sound_dba": float("nan")}, "non_finite_sound_dba"),
            ({"sound_dba": float("inf")}, "non_finite_sound_dba"),
            ({"sound_dba": 29.9}, "sound_dba_out_of_range"),
            ({"sound_dba": 130.1}, "sound_dba_out_of_range"),
        )
        for packet, reason in cases:
            with self.subTest(reason=reason):
                normalized = normalize_hub1_sensor(
                    packet,
                    sound_display_min=SOUND_DBA_DISPLAY_MIN,
                    sound_display_max=SOUND_DBA_DISPLAY_MAX,
                )
                self.assertNotIn("sound_dba_est", normalized)
                self.assertFalse(normalized["sound_measurement_valid"])
                self.assertEqual(normalized["sound_invalid_reason"], reason)

    def test_dbfs_or_laeq_without_sound_dba_never_becomes_canonical(self) -> None:
        cases = (
            ({"sound_dbfs": -39.69}, "legacy_dbfs_only"),
            ({"sound_laeq_dba": 54.2}, "missing_sound_dba"),
            (
                {"sound_dbfs": -39.69, "sound_laeq_dba": 54.2},
                "legacy_dbfs_only",
            ),
        )
        for packet, reason in cases:
            with self.subTest(packet=packet):
                normalized = normalize_hub1_sensor(
                    packet,
                    sound_display_min=SOUND_DBA_DISPLAY_MIN,
                    sound_display_max=SOUND_DBA_DISPLAY_MAX,
                )
                self.assertNotIn("sound_dba_est", normalized)
                self.assertFalse(normalized["sound_measurement_valid"])
                self.assertEqual(normalized["sound_invalid_reason"], reason)

    def test_invalid_sound_never_holds_previous_value_as_current(self) -> None:
        current = {"sound_dbfs": float("nan")}
        held = hold_last_valid_sound(
            current,
            {"sound_dba_est": 38.2},
            display_min=SOUND_DBA_DISPLAY_MIN,
            display_max=SOUND_DBA_DISPLAY_MAX,
        )
        self.assertNotIn("sound_dba_est", held)
        self.assertEqual(held["sound_last_valid_dba"], 38.2)
        self.assertFalse(held["sound_measurement_valid"])

    def test_invalid_sound_inspector_has_no_calibration_or_engineering_gate(
        self,
    ) -> None:
        channel = sound_inspector_channel(
            {
                "sound_dbfs": -39.69,
                "sound_measurement_valid": False,
                "sound_invalid_reason": "legacy_dbfs_only",
            },
            {},
            {"status": "invalid", "source_label": "Hub 1 · USB"},
        )

        self.assertIsNone(channel["raw"])
        self.assertIsNone(channel["calibrated"])
        self.assertEqual(channel["pipeline_state"], "invalid")
        self.assertEqual(channel["invalid_reason"], "legacy_dbfs_only")
        self.assertNotIn("engineering", channel)
        self.assertNotIn("calibration_state", channel)

    def test_sound_inspector_never_coerces_or_displays_invalid_source(self) -> None:
        for value in ("54.0", 29.9, 130.1, float("nan")):
            with self.subTest(value=value):
                channel = sound_inspector_channel(
                    {
                        "sound_dba": value,
                        "sound_measurement_valid": False,
                        "sound_invalid_reason": "invalid_sound_dba",
                    },
                    {},
                    {"status": "invalid", "source_label": "Hub 1 · USB"},
                )
                self.assertIsNone(channel["raw"])
                self.assertIsNone(channel["firmware_value"])
                self.assertFalse(channel["measurement_valid"])

    def test_invalid_sound_state_is_strict_json_serializable(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                normalized = normalize_hub1_sensor(
                    {"sound_dba": value, "sound_dbfs": value},
                    sound_display_min=SOUND_DBA_DISPLAY_MIN,
                    sound_display_max=SOUND_DBA_DISPLAY_MAX,
                )
                json.dumps(normalized, allow_nan=False)
                self.assertNotIn("sound_dba", normalized)
                self.assertNotIn("sound_dbfs", normalized)
                self.assertNotIn("sound_invalid_value", normalized)

    def test_huge_sound_integer_is_packet_local_invalid_data(self) -> None:
        normalized = normalize_hub1_sensor(
            {"sound_dba": 10 ** 10_000, "temperature_c": 24.0},
            sound_display_min=SOUND_DBA_DISPLAY_MIN,
            sound_display_max=SOUND_DBA_DISPLAY_MAX,
        )
        self.assertEqual(normalized["temperature"], 24.0)
        self.assertFalse(normalized["sound_measurement_valid"])
        self.assertEqual(
            normalized["sound_invalid_reason"],
            "sound_dba_out_of_range",
        )
        self.assertNotIn("sound_invalid_value", normalized)

    def test_two_hub_composition_has_one_canonical_value_per_metric(self) -> None:
        hub1 = {
            "connected": True,
            "last_update": NOW,
            "temperature": 24.0,
            "humidity": 50.0,
            "lux": 2.0,
            "sound_dba_est": 35.0,
            "sound_measurement_valid": True,
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

    def test_invalid_sph_does_not_hide_live_sht3x_or_opt3001(self) -> None:
        hub1 = normalize_hub1_sensor(
            {
                "connected": True,
                "last_update": NOW,
                "temperature_c": 23.0,
                "humidity_rh": 52.0,
                "lux": 0.8,
                "sound_valid": False,
                "sound_weighting": "A",
                "sound_metric": "LAeq",
                "sound_window_ms": 10_000,
                "sound_invalid_reason": "pcm_all_zero",
                "sensor_status": {
                    "sht3x_dis": True,
                    "opt3001": True,
                    "sph0645": False,
                },
            },
            sound_display_min=SOUND_DBA_DISPLAY_MIN,
            sound_display_max=SOUND_DBA_DISPLAY_MAX,
        )
        biases = {metric: 0.0 for metric in SENSOR_CALIBRATION_SPECS}
        result = compose_environment_snapshot(
            hub1,
            {},
            now=NOW,
            hub1_stale_s=25.0,
            hub2_stale_s=20.0,
            device_specs=ENVIRONMENT_DEVICE_SPECS,
            calibration_metrics=tuple(SENSOR_CALIBRATION_SPECS),
            apply_bias=lambda metric, value: apply_additive_bias(
                metric, value, biases=biases),
            bias_value=lambda metric: biases[metric],
            bias_sources={metric: "default" for metric in biases},
        )

        self.assertEqual(result["temperature_c"], 23.0)
        self.assertEqual(result["humidity_rh"], 52.0)
        self.assertEqual(result["lux"], 0.8)
        self.assertIsNone(result["sound_dba_est"])
        self.assertEqual(result["devices"]["sht3x_dis"]["status"], "live")
        self.assertEqual(result["devices"]["opt3001"]["status"], "live")
        self.assertEqual(result["devices"]["sph0645"]["status"], "invalid")
        self.assertEqual(result["live_count"], 2)

    def test_direct_sound_is_canonical_and_live_in_composition(self) -> None:
        hub1 = normalize_hub1_sensor(
            {
                "connected": True,
                "last_update": NOW,
                "temperature_c": 23.0,
                "humidity_rh": 52.0,
                "lux": 0.8,
                "sound_dba": 53.86,
                "sensor_status": {
                    "sht3x_dis": True,
                    "opt3001": True,
                    "sph0645": True,
                },
            },
            sound_display_min=SOUND_DBA_DISPLAY_MIN,
            sound_display_max=SOUND_DBA_DISPLAY_MAX,
        )
        biases = {metric: 0.0 for metric in SENSOR_CALIBRATION_SPECS}
        result = compose_environment_snapshot(
            hub1,
            {},
            now=NOW,
            hub1_stale_s=25.0,
            hub2_stale_s=20.0,
            device_specs=ENVIRONMENT_DEVICE_SPECS,
            calibration_metrics=tuple(SENSOR_CALIBRATION_SPECS),
            apply_bias=lambda metric, value: apply_additive_bias(
                metric,
                value,
                biases=biases,
            ),
            bias_value=lambda metric: biases[metric],
            bias_sources={metric: "default" for metric in biases},
        )

        self.assertEqual(result["sound_dba_est"], 53.86)
        self.assertEqual(result["raw_values"]["sound_dba_est"], 53.86)
        self.assertEqual(result["devices"]["sph0645"]["status"], "live")
        self.assertNotIn("sound_dba_firmware_est", result)
        self.assertNotIn("sound_preview_evidence_count", result)
        self.assertEqual(result["live_count"], 3)

    def test_fresh_cached_environment_value_is_explicitly_degraded(self) -> None:
        hub1 = {
            "connected": True,
            "last_update": NOW,
            "temperature_c": 23.0,
            "humidity_rh": 52.0,
            "sensor_status": {"sht3x_dis": True},
            "sensor_diagnostics": {
                "sht3x_dis": {
                    "status": "degraded",
                    "reason": "sht_crc_failed",
                    "age_ms": 2_100,
                },
            },
        }
        biases = {metric: 0.0 for metric in SENSOR_CALIBRATION_SPECS}
        result = compose_environment_snapshot(
            hub1,
            {},
            now=NOW,
            hub1_stale_s=25.0,
            hub2_stale_s=20.0,
            device_specs=ENVIRONMENT_DEVICE_SPECS,
            calibration_metrics=tuple(SENSOR_CALIBRATION_SPECS),
            apply_bias=lambda metric, value: apply_additive_bias(
                metric, value, biases=biases),
            bias_value=lambda metric: biases[metric],
            bias_sources={metric: "default" for metric in biases},
        )

        self.assertEqual(result["temperature_c"], 23.0)
        self.assertEqual(result["devices"]["sht3x_dis"]["status"], "degraded")
        self.assertEqual(
            result["devices"]["sht3x_dis"]["reason"], "sht_crc_failed")
        self.assertEqual(result["status"], "degraded")

    def test_legacy_dbfs_is_exposed_only_as_raw_display_diagnostic(self) -> None:
        hub1 = {
            "connected": True,
            "last_update": NOW,
            "temperature": 24.0,
            "humidity": 50.0,
            "lux": 2.0,
            "sound_dbfs": -19.39,
            "sound_measurement_valid": False,
            "sound_invalid_reason": "legacy_dbfs_only",
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
            apply_bias=lambda metric, value: apply_additive_bias(
                metric, value, biases=biases
            ),
            bias_value=lambda metric: biases[metric],
            bias_sources={metric: "default" for metric in biases},
        )
        self.assertEqual(result["sound_dbfs_raw"], -19.39)
        self.assertIsNone(result["sound_dba_est"])
        self.assertEqual(result["devices"]["sph0645"]["status"], "invalid")

        hub1["last_update"] = NOW - 21.0
        stale_result = compose_environment_snapshot(
            hub1,
            hub2,
            now=NOW,
            hub1_stale_s=20.0,
            hub2_stale_s=20.0,
            device_specs=ENVIRONMENT_DEVICE_SPECS,
            calibration_metrics=tuple(SENSOR_CALIBRATION_SPECS),
            apply_bias=lambda metric, value: apply_additive_bias(
                metric, value, biases=biases
            ),
            bias_value=lambda metric: biases[metric],
            bias_sources={metric: "default" for metric in biases},
        )
        self.assertIsNone(stale_result["sound_dbfs_raw"])


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
