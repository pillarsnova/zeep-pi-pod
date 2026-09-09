import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from testing_support import configure_app_test_environment

configure_app_test_environment()
import app
from database import DatabaseManager
import sensor_contracts as contracts


NOW = 1_000.0


def hub1(**overrides):
    payload = {
        "connected": True,
        "last_update": NOW - 0.4,
        "temperature": 24.2,
        "humidity": 51.3,
        "lux": 2.1,
        "sound_dba_est": 31.4,
        "sound_measurement_valid": True,
        "sensor_status": {
            "sht31": True,
            "opt3001": True,
            "sph0645": True,
        },
    }
    payload.update(overrides)
    return payload


def hub2(**overrides):
    payload = {
        "connected": True,
        "last_update": NOW - 1.2,
        "co2_ppm": 750,
        "pm1_0_ug_m3": 3,
        "pm2_5_ug_m3": 5,
        "pm10_ug_m3": 5,
        "voc_index": 84,
        "sgp40_raw": 30_527,
        "sensor_status": {
            "mhz19c": True,
            "pms7003": True,
            "sgp40": True,
        },
    }
    payload.update(overrides)
    return payload


class EnvironmentContractTests(unittest.TestCase):
    def test_sph0645_blocks_legacy_and_uncalibrated_firmware_laeq(self):
        legacy = app.normalize_esp32_sensor({"sound_dbfs": -39.69})
        valid = app.normalize_esp32_sensor({
            "sound_dbfs": -39.69,
            "sound_laeq_dba": 54.0,
            "sound_valid": True,
            "sound_weighting": "A",
            "sound_metric": "LAeq",
            "sound_window_ms": 10_000,
        })

        self.assertEqual(legacy["sound_dbfs"], -39.69)
        self.assertNotIn("sound_dba_est", legacy)
        self.assertEqual(legacy["sound_invalid_reason"], "legacy_dbfs_only")
        self.assertNotIn("sound_dba_est", valid)
        self.assertFalse(valid["sound_measurement_valid"])
        self.assertEqual(
            valid["sound_invalid_reason"],
            "cem_calibration_required",
        )

    def test_six_live_sensors_are_merged_from_two_hubs(self):
        result = app.build_environment_snapshot(hub1(), hub2(), NOW)

        self.assertEqual(result["status"], "live")
        self.assertEqual(result["live_count"], 6)
        self.assertEqual(result["temperature_c"], 24.4)
        self.assertEqual(result["humidity_rh"], 44.3)
        self.assertEqual(result["co2_ppm"], 750.0)
        self.assertEqual(result["devices"]["sht3x_dis"]["source"], "hub1")
        self.assertEqual(result["devices"]["mhz19c"]["source"], "hub2")

    def test_stale_hub2_values_are_never_reported_as_live(self):
        result = app.build_environment_snapshot(
            hub1(), hub2(last_update=NOW - app.SENSORHUB2_STALE_SECONDS - 1), NOW
        )

        self.assertEqual(result["live_count"], 3)
        self.assertEqual(result["devices"]["mhz19c"]["status"], "stale")
        self.assertEqual(result["devices"]["pms7003"]["status"], "stale")
        self.assertEqual(result["devices"]["sgp40"]["status"], "stale")

    def test_out_of_range_co2_is_rejected(self):
        result = app.build_environment_snapshot(hub1(), hub2(co2_ppm=0), NOW)

        self.assertIsNone(result["co2_ppm"])
        self.assertEqual(result["devices"]["mhz19c"]["status"], "invalid")
        self.assertEqual(
            result["devices"]["mhz19c"]["invalid_values"]["co2_ppm"], 0.0
        )

    def test_mhz19c_can_fall_back_to_live_hub1_payload(self):
        result = app.build_environment_snapshot(
            hub1(co2_ppm=820, sensor_status={
                "sht31": True,
                "opt3001": True,
                "sph0645": True,
                "mhz19c": True,
            }),
            {},
            NOW,
        )

        self.assertEqual(result["co2_ppm"], 820.0)
        self.assertEqual(result["devices"]["mhz19c"]["status"], "live")
        self.assertEqual(result["devices"]["mhz19c"]["source"], "hub1")

    def test_invalid_sound_is_not_visible_or_counted_as_live(self):
        result = app.build_environment_snapshot(
            hub1(
                sound_dba_est=None,
                sound_measurement_valid=False,
                sound_invalid_reason="legacy_dbfs_only",
            ),
            hub2(),
            NOW,
        )

        self.assertIsNone(result["sound_dba_est"])
        self.assertEqual(result["devices"]["sph0645"]["status"], "invalid")
        self.assertEqual(result["live_count"], 5)

        assessment = app.assess_environment_values(
            result,
            require_live_devices=True,
        )
        self.assertNotEqual(assessment["key"], "unknown")
        self.assertEqual(assessment["assessment_quality"], "degraded_optional")
        self.assertEqual(assessment["optional_unavailable_count"], 1)
        self.assertEqual(assessment["blocking_unavailable_count"], 0)

    def test_sound_outside_reference_meter_range_is_not_visible(self):
        for level in (-39.69, 29.9, 130.1):
            with self.subTest(level=level):
                result = app.build_environment_snapshot(
                    hub1(sound_dba_est=level),
                    hub2(),
                    NOW,
                )
                self.assertIsNone(result["sound_dba_est"])
                self.assertEqual(
                    result["devices"]["sph0645"]["status"],
                    "invalid",
                )
                self.assertEqual(result["live_count"], 5)

    def test_session_sample_keeps_live_pm25_and_voc_for_the_final_report(self):
        environment = app.build_environment_snapshot(hub1(), hub2(), NOW)
        fake_snapshot = {
            "sensor": {
                "environment": environment,
                "bcg": {"connected": False},
            },
            "sleep": {},
            "analysis_frame": {},
        }
        with patch.object(app, "snapshot", return_value=fake_snapshot):
            sample = app.take_session_sample()

        self.assertEqual(sample["pm2_5"], 5.0)
        self.assertEqual(sample["voc"], 84.0)


class SessionTimelineSchemaTests(unittest.TestCase):
    def test_v4_migration_adds_and_writes_pm25_and_voc_columns(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = Path(root)
            legacy = sqlite3.connect(data_dir / "sessions.db")
            legacy.execute("""
                CREATE TABLE timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    temperature REAL, humidity REAL, co2 REAL, lux REAL,
                    sound REAL, heart_rate REAL, respiration_rate REAL,
                    bed_status TEXT
                )
            """)
            legacy.commit()
            legacy.close()

            manager = DatabaseManager(data_dir)
            manager.initialize()
            inspect = sqlite3.connect(data_dir / "sessions.db")
            columns = {
                row[1] for row in inspect.execute("PRAGMA table_info(timeline)")
            }
            inspect.close()
            self.assertIn("pm2_5", columns)
            self.assertIn("voc_index", columns)

            manager.start()
            manager.enqueue("sessions", "timeline", {
                "session_id": "session-air-1",
                "timestamp": "2026-08-29T00:00:00+00:00",
                "pm2_5": 7.0,
                "voc_index": 103.0,
            })
            self.assertTrue(manager.flush())
            manager.stop()

            verify = sqlite3.connect(data_dir / "sessions.db")
            stored = verify.execute(
                "SELECT pm2_5,voc_index FROM timeline"
            ).fetchone()
            verify.close()
            self.assertEqual(stored, (7.0, 103.0))


class VersionedTelemetryContractTests(unittest.TestCase):
    def test_reader_gate_accepts_only_expected_environment_event(self):
        expected = {"event": "environment", "hub_id": "sensorhub1"}
        boot = {"event": "boot", "hub_id": "sensorhub1"}
        calibration = {"event": "calibration_response"}
        wrong_hub = {"event": "environment", "hub_id": "sensorhub2"}

        self.assertEqual(
            contracts.classify_hub_payload(
                expected, expected_hub="sensorhub1"),
            ("telemetry", "environment"),
        )
        self.assertEqual(
            contracts.classify_hub_payload(
                boot, expected_hub="sensorhub1"),
            ("ignored", "boot"),
        )
        self.assertEqual(
            contracts.classify_hub_payload(
                calibration, expected_hub="sensorhub1"),
            ("ignored", "calibration_response"),
        )
        self.assertEqual(
            contracts.classify_hub_payload(
                wrong_hub, expected_hub="sensorhub1"),
            ("rejected", "unexpected_hub:sensorhub2"),
        )

    def test_legacy_flat_payload_remains_backward_compatible(self):
        decoded = contracts.decode_hub_payload(
            {"temperature_c": 24.5, "humidity_rh": 52.0},
            expected_hub="sensorhub1",
        )
        self.assertEqual(decoded["temperature_c"], 24.5)
        self.assertEqual(decoded["contract"]["schema"], "legacy.flat")

    def test_released_golden_environment_packet_is_accepted(self):
        payload = {
            "event": "environment",
            "temperature": 24.5,
            "humidity": 52.0,
            "light": 1.2,
            "sound_dbfs": -55.0,
        }

        self.assertEqual(
            contracts.classify_hub_payload(
                payload,
                expected_hub="sensorhub1",
            ),
            ("telemetry", "legacy_environment"),
        )

    def test_canonical_environment_packet_without_hub_id_is_rejected(self):
        payload = {
            "event": "environment",
            "sensors": {
                "sht3x_dis": {
                    "status": "live",
                    "values": {"temperature_c": 24.5},
                },
            },
        }

        self.assertEqual(
            contracts.classify_hub_payload(
                payload,
                expected_hub="sensorhub1",
            ),
            ("rejected", "unexpected_hub:missing"),
        )

    def test_explicit_wrong_hub_is_rejected_even_for_flat_payload(self):
        payload = {
            "event": "environment",
            "hub_id": "sensorhub2",
            "temperature": 24.5,
        }

        self.assertEqual(
            contracts.classify_hub_payload(
                payload,
                expected_hub="sensorhub1",
            ),
            ("rejected", "unexpected_hub:sensorhub2"),
        )

    def test_v1_envelope_normalises_to_current_internal_fields(self):
        decoded = contracts.decode_hub_payload({
            "schema": contracts.TELEMETRY_SCHEMA,
            "version": contracts.TELEMETRY_SCHEMA_VERSION,
            "hub_id": "sensorhub2",
            "sequence": 42,
            "captured_at": "2026-08-28T00:00:00Z",
            "sensors": {
                "mhz19c": {"status": "live", "values": {"co2_ppm": 775}},
                "sgp40": {"status": "live", "values": {"voc_index": 96}},
            },
        }, expected_hub="sensorhub2")
        self.assertEqual(decoded["co2_ppm"], 775)
        self.assertEqual(decoded["voc_index"], 96)
        self.assertEqual(decoded["sequence"], 42)
        self.assertTrue(decoded["sensor_status"]["mhz19c"])

    def test_canonical_hub1_packet_preserves_three_sensor_diagnostics(self):
        decoded = contracts.decode_hub_payload({
            "schema": contracts.TELEMETRY_SCHEMA,
            "version": contracts.TELEMETRY_SCHEMA_VERSION,
            "event": "environment",
            "source": "sensorhub1_firmware",
            "hub_id": "sensorhub1",
            "firmware_version": "sensorhub1-v2.0",
            "sequence": 81,
            "monotonic_ms": 810_000,
            "diagnostics": {"publish_period_ms": 10_000},
            "sensors": {
                "sht3x_dis": {
                    "status": "live",
                    "age_ms": 120,
                    "values": {
                        "temperature_c": 23.4,
                        "humidity_rh": 51.2,
                    },
                },
                "opt3001": {
                    "status": "live",
                    "values": {"lux": 1.7},
                },
                "sph0645": {
                    "status": "invalid",
                    "reason": "pcm_all_zero",
                    "diagnostics": {"zero_ratio": 1.0},
                    "values": {
                        "sound_valid": False,
                        "sound_weighting": "A",
                        "sound_metric": "LAeq",
                        "sound_window_ms": 10_000,
                    },
                },
            },
        }, expected_hub="sensorhub1")

        self.assertEqual(decoded["event"], "environment")
        self.assertEqual(decoded["source"], "sensorhub1_firmware")
        self.assertEqual(decoded["hub_id"], "sensorhub1")
        self.assertEqual(decoded["firmware_version"], "sensorhub1-v2.0")
        self.assertEqual(decoded["hub_diagnostics"]["publish_period_ms"], 10_000)
        self.assertTrue(decoded["sensor_status"]["sht3x_dis"])
        self.assertTrue(decoded["sensor_status"]["opt3001"])
        self.assertFalse(decoded["sensor_status"]["sph0645"])
        self.assertEqual(decoded["sound_invalid_reason"], "pcm_all_zero")
        self.assertEqual(
            decoded["sensor_diagnostics"]["sph0645"]["reason"],
            "pcm_all_zero",
        )

        normalized = app.normalize_esp32_sensor(decoded)
        self.assertEqual(normalized["sound_invalid_reason"], "pcm_all_zero")
        self.assertIsNone(normalized.get("sound_dba_est"))
        normalized.update({"connected": True, "last_update": NOW})
        environment = app.build_environment_snapshot(normalized, {}, NOW)
        self.assertEqual(
            environment["devices"]["sht3x_dis"]["status"], "live")
        self.assertEqual(
            environment["devices"]["opt3001"]["status"], "live")
        self.assertEqual(
            environment["devices"]["sph0645"]["status"], "invalid")
        self.assertEqual(
            environment["devices"]["sph0645"]["reason"], "pcm_all_zero")
        self.assertEqual(environment["live_count"], 2)

    def test_hub1_default_stale_window_covers_two_ten_second_packets(self):
        self.assertEqual(app.ESP32_STALE_SECONDS, 25.0)

    def test_wrong_hub_or_schema_version_is_rejected(self):
        base = {
            "schema": contracts.TELEMETRY_SCHEMA,
            "version": contracts.TELEMETRY_SCHEMA_VERSION,
            "hub_id": "sensorhub1",
            "sensors": {},
        }
        with self.assertRaises(ValueError):
            contracts.decode_hub_payload(base, expected_hub="sensorhub2")
        with self.assertRaises(ValueError):
            contracts.decode_hub_payload(
                {**base, "version": "99"}, expected_hub="sensorhub1"
            )

    def test_lsm800t_parser_matches_deployed_66_byte_layout(self):
        import struct

        samples = list(range(-12, 13))
        frame = (
            b"Odata" + struct.pack("<25h", *samples) + b"\x00\x00"
            + b"Bdata" + bytes([7, 2, 68, 143])
        )
        parsed = contracts.parse_lsm800t_frame(frame)
        self.assertEqual(len(frame), 66)
        self.assertEqual(parsed["samples"], samples)
        self.assertEqual(parsed["sensor_packet_id"], 7)
        self.assertEqual(parsed["status_code"], 2)
        self.assertEqual(parsed["heart_rate_bpm"], 68)
        self.assertEqual(parsed["respiration_rate"], 14.3)

    def test_runtime_environment_specs_are_the_contract_objects(self):
        self.assertIs(app.ENVIRONMENT_DEVICE_SPECS, contracts.ENVIRONMENT_DEVICE_SPECS)
        self.assertEqual(
            set(contracts.sensor_contract_snapshot()["devices"]),
            {"sht3x_dis", "opt3001", "sph0645", "mhz19c", "pms7003", "sgp40", "lsm800t"},
        )


class SoundAnalysisTests(unittest.TestCase):
    def setUp(self):
        with app.sound_history_lock:
            self.previous = list(app.sound_level_history)
            app.sound_level_history.clear()

    def tearDown(self):
        with app.sound_history_lock:
            app.sound_level_history.clear()
            app.sound_level_history.extend(self.previous)

    def test_energy_average_is_not_arithmetic_db_average(self):
        self.assertEqual(app.sound_energy_average_db([40.0, 50.0]), 47.4)
        self.assertEqual(app.sound_energy_average_db([42.5, 42.5]), 42.5)

    def test_window_keeps_low_transient_visible_but_flags_dynamic_span(self):
        with app.sound_history_lock:
            app.sound_level_history.extend([
                {"t": 1.0, "dba": 48.0},
                {"t": 2.0, "dba": 4.0},
                {"t": 3.0, "dba": 48.0},
            ])

        result = app.sound_window_summary(0.0, 5.0)

        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["min_dba"], 4.0)
        self.assertTrue(result["large_step_detected"])
        self.assertEqual(result["status"], "dynamic")
        self.assertGreater(result["leq_dba"], 46.0)


if __name__ == "__main__":
    unittest.main()
