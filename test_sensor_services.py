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
    sound_inspector_channel,
)
from sensor_contracts import (
    ENVIRONMENT_DEVICE_SPECS,
    SOUND_DBA_DISPLAY_MAX,
    SOUND_DBA_DISPLAY_MIN,
    classify_hub_payload,
    decode_hub_payload,
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
            document["sound_processing"]["calibration_status"],
            "pending_cem_recalibration_after_sensor_replacement",
        )
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

    def test_sound_calibration_trust_is_exact_and_fail_closed(self) -> None:
        healthy_hub = {
            "sound_measurement_valid": True,
            "sound_laeq_dba": 40.0,
        }
        device = {"status": "live", "source_label": "Hub 1 · USB"}

        for rejected_status in (
            "unverified",
            "not_approved",
            "calibration_not_current",
        ):
            with self.subTest(status=rejected_status):
                channel = sound_inspector_channel(
                    healthy_hub,
                    {"sound_dba_est": 40.0},
                    device,
                    {"calibration_status": rejected_status},
                )
                self.assertEqual(channel["calibration_state"], "unknown")

        verified = sound_inspector_channel(
            healthy_hub,
            {"sound_dba_est": 40.0},
            device,
            {"calibration_status": "cem_dt_8852_verified"},
        )
        self.assertEqual(verified["calibration_state"], "verified")


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

    def test_valid_firmware_laeq_is_published_without_pi_transform(self) -> None:
        normalized = normalize_hub1_sensor(
            {
                "sound_dbfs": -39.69,
                "sound_laeq_dba": 54.2,
                "sound_valid": True,
                "sound_weighting": "A",
                "sound_metric": "LAeq",
                "sound_window_ms": 10_000,
                "sound_invalid_reason": "old_window_error",
            },
            sound_display_min=SOUND_DBA_DISPLAY_MIN,
            sound_display_max=SOUND_DBA_DISPLAY_MAX,
        )
        self.assertEqual(normalized["sound_dbfs"], -39.69)
        self.assertEqual(normalized["sound_dba_est"], 54.2)
        self.assertTrue(normalized["sound_measurement_valid"])
        self.assertNotIn("sound_invalid_reason", normalized)
        self.assertEqual(
            energy_average_db(
                [40.0, 50.0],
                display_min=SOUND_DBA_DISPLAY_MIN,
                display_max=SOUND_DBA_DISPLAY_MAX,
            ),
            47.4,
        )

    def test_sound_reference_range_boundaries_are_inclusive(self) -> None:
        base = {
            "sound_valid": True,
            "sound_weighting": "A",
            "sound_metric": "LAeq",
            "sound_window_ms": 10_000,
        }
        for level in (SOUND_DBA_DISPLAY_MIN, SOUND_DBA_DISPLAY_MAX):
            with self.subTest(level=level):
                normalized = normalize_hub1_sensor(
                    {**base, "sound_laeq_dba": level},
                    sound_display_min=SOUND_DBA_DISPLAY_MIN,
                    sound_display_max=SOUND_DBA_DISPLAY_MAX,
                )
                self.assertEqual(normalized["sound_dba_est"], level)
                self.assertTrue(normalized["sound_measurement_valid"])

    def test_incomplete_or_untrusted_firmware_laeq_is_invalid(self) -> None:
        base = {
            "sound_laeq_dba": 54.2,
            "sound_valid": True,
            "sound_weighting": "A",
            "sound_metric": "LAeq",
            "sound_window_ms": 10_000,
        }
        cases = (
            ({"sound_valid": False}, "firmware_invalid"),
            ({"sound_weighting": "Z"}, "weighting_must_be_A"),
            ({"sound_metric": "SPL"}, "metric_must_be_LAeq"),
            ({"sound_window_ms": 0}, "invalid_integration_window"),
            ({"sound_laeq_dba": -1}, "laeq_out_of_range"),
            ({"sound_laeq_dba": 29.9}, "laeq_out_of_range"),
            ({"sound_laeq_dba": 130.1}, "laeq_out_of_range"),
        )
        for override, reason in cases:
            with self.subTest(reason=reason):
                normalized = normalize_hub1_sensor(
                    {**base, **override},
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

    def test_admin_sound_card_separates_laeq_from_signed_raw_diagnostics(self) -> None:
        channel = sound_inspector_channel(
            {
                "sound_dbfs": -39.69,
                "sound_dbfs_a": -46.2,
                "sound_rms": 0.002864,
                "sound_rms_a": 0.001235,
                "sound_sample_rate_hz": 32_000,
                "sound_samples": 32_000,
                "mic_zero_ratio": 0.0,
                "mic_change_ratio": 0.9711,
                "raw_clip_count": 0,
                "mic_read_errors": 0,
                "mic_capture_ok": True,
                "mic_signal_valid": True,
                "sound_laeq_dba": 39.8,
                "sound_measurement_valid": True,
            },
            {"sound_dba_est": 39.8},
            {"status": "live", "source_label": "Hub 1 · USB"},
        )
        self.assertEqual(channel["raw"], 39.8)
        self.assertEqual(channel["raw_unit"], "dBA est.")
        fields = {
            item["key"]: item
            for item in channel["engineering"]["fields"]
        }
        self.assertEqual(fields["sound_dbfs"]["value"], -39.69)
        self.assertEqual(fields["sound_dbfs"]["unit"], "dBFS")
        self.assertEqual(fields["sound_dbfs_a"]["value"], -46.2)
        self.assertEqual(fields["mic_zero_ratio"]["value"], 0.0)
        self.assertEqual(channel["pipeline_state"], "valid")
        self.assertEqual(channel["calibration_state"], "unknown")

        invalid = sound_inspector_channel(
            {
                "sound_dbfs": -39.69,
                "mic_capture_ok": True,
                "mic_signal_valid": True,
                "mic_stuck_zero": False,
                "mic_stuck_constant": False,
                # The old firmware flag is diagnostic only.  The Pi contract
                # remains authoritative and keeps this health value invalid.
                "sound_dba_calibrated": True,
                "sound_measurement_valid": False,
                "sound_invalid_reason": "legacy_dbfs_only",
            },
            {},
            {"status": "invalid", "source_label": "Hub 1 · USB"},
        )
        self.assertIsNone(invalid["raw"])
        self.assertIsNone(invalid["calibrated"])
        self.assertEqual(invalid["pipeline_state"], "raw_ok_output_blocked")
        self.assertTrue(
            invalid["engineering"]["firmware_dba_calibrated"]
        )
        flag_health = {
            item["key"]: item["healthy"]
            for item in invalid["engineering"]["flags"]
        }
        self.assertTrue(flag_health["capture_ok"])
        self.assertTrue(flag_health["signal_valid"])
        self.assertTrue(flag_health["stuck_zero"])
        self.assertTrue(flag_health["stuck_constant"])
        self.assertEqual(
            invalid["engineering"]["fields"][0]["value"],
            -39.69,
        )

    def test_sound_engineering_accepts_candidate_firmware_aliases(self) -> None:
        channel = sound_inspector_channel(
            {
                "sound_dbfs": -50.86,
                "sound_a_weighted_dbfs": -58.17,
                "sound_clipped_samples": 0,
                "sound_zero_samples": 0,
                "sound_repeated_samples": 120,
                "sound_read_errors": 0,
                "sound_valid": True,
                "mic_stuck_zero": True,
                "sound_measurement_valid": False,
            },
            {},
            {
                "status": "invalid",
                "source_label": "Hub 1 · USB",
                "diagnostics": {
                    "stream_active": True,
                    "measurement_valid": True,
                },
            },
        )
        fields = {
            item["key"]: item["value"]
            for item in channel["engineering"]["fields"]
        }
        flags = {
            item["key"]: item
            for item in channel["engineering"]["flags"]
        }
        self.assertEqual(fields["sound_dbfs_a"], -58.17)
        self.assertEqual(fields["raw_clip_count"], 0.0)
        self.assertEqual(fields["sound_repeated_samples"], 120.0)
        self.assertEqual(fields["mic_read_errors"], 0.0)
        self.assertTrue(flags["capture_ok"]["value"])
        self.assertTrue(flags["signal_valid"]["value"])
        self.assertTrue(flags["stuck_zero"]["value"])
        self.assertFalse(flags["stuck_zero"]["healthy"])
        self.assertEqual(channel["pipeline_state"], "invalid")

    def test_released_golden_packet_keeps_raw_but_blocks_old_dba_offset(self) -> None:
        packet = {
            "schema_version": 1,
            "profile": "3sensor_v3_4_1",
            "event": "environment",
            "seq": 5042,
            "lux": 2.85,
            "temperature_c": 30.18,
            "humidity_rh": 67.15,
            "sound_rms": 0.0028643,
            "sound_peak": 0.0096518,
            "sound_dbfs": -50.86,
            "sound_rms_a": 0.0012351,
            "sound_peak_a": 0.0059108,
            "sound_dbfs_a": -58.17,
            "sound_laeq_dba": 53.76,
            "sound_dba_calibrated": True,
            "sound_calibration_offset_db": 111.93,
            "sound_samples": 32_000,
            "sound_window_ms": 1_000,
            "sound_sample_rate_hz": 32_000.0,
            "raw_clip_count": 0,
            "mic_read_errors": 0,
            "mic_zero_samples": 0,
            "mic_nonzero_samples": 32_000,
            "mic_raw_changes": 31_076,
            "mic_zero_ratio": 0.0,
            "mic_change_ratio": 0.971125,
            "mic_capture_ok": True,
            "mic_signal_valid": True,
            "mic_stuck_zero": False,
            "mic_stuck_constant": False,
            "sensor_status": {
                "opt3001": True,
                "sht31": True,
                "sph0645": True,
            },
        }
        disposition, _ = classify_hub_payload(
            packet,
            expected_hub="sensorhub1",
        )
        self.assertEqual(disposition, "telemetry")
        decoded = decode_hub_payload(packet, expected_hub="sensorhub1")
        normalized = normalize_hub1_sensor(
            decoded,
            sound_display_min=SOUND_DBA_DISPLAY_MIN,
            sound_display_max=SOUND_DBA_DISPLAY_MAX,
        )
        self.assertFalse(normalized["sound_measurement_valid"])
        self.assertNotIn("sound_dba_est", normalized)
        self.assertEqual(normalized["sound_invalid_reason"], "firmware_invalid")

        channel = sound_inspector_channel(
            normalized,
            {},
            {"status": "invalid", "source_label": "Hub 1 · USB"},
            {"calibration_status": "pending_cem_recalibration"},
        )
        fields = {
            item["key"]: item["value"]
            for item in channel["engineering"]["fields"]
        }
        self.assertEqual(fields["sound_dbfs"], -50.86)
        self.assertEqual(fields["sound_dbfs_a"], -58.17)
        self.assertEqual(fields["sound_laeq_dba"], 53.76)
        self.assertEqual(fields["sound_calibration_offset_db"], 111.93)
        self.assertEqual(channel["pipeline_state"], "raw_ok_output_blocked")
        self.assertEqual(channel["calibration_state"], "pending")
        self.assertIsNone(channel["raw"])

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
