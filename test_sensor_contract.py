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
    def test_sph0645_display_uses_rounded_absolute_dbfs_minus_three_percent(self):
        with patch.object(app, "SOUND_DBFS_ERROR_PERCENT", 3.0):
            negative = app.normalize_esp32_sensor({"sound_dbfs": -39.69})
            positive = app.normalize_esp32_sensor({"sound_dbfs": 39.69})

        self.assertEqual(negative["sound_dbfs"], -39.69)
        self.assertEqual(negative["sound_dbfs_magnitude"], 39.7)
        self.assertEqual(negative["sound_dba_est"], 38.51)
        self.assertEqual(positive["sound_dba_est"], 38.51)
        self.assertEqual(negative["sound_error_percent"], 3.0)

    def test_six_live_sensors_are_merged_from_two_hubs(self):
        result = app.build_environment_snapshot(hub1(), hub2(), NOW)

        self.assertEqual(result["status"], "live")
        self.assertEqual(result["live_count"], 6)
        self.assertEqual(result["temperature_c"], 24.2)
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

    def test_held_sound_is_visible_but_not_counted_as_live(self):
        result = app.build_environment_snapshot(
            hub1(sound_value_held=True), hub2(), NOW
        )

        self.assertEqual(result["sound_dba_est"], 31.4)
        self.assertEqual(result["devices"]["sph0645"]["status"], "held")
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
    def test_legacy_flat_payload_remains_backward_compatible(self):
        decoded = contracts.decode_hub_payload(
            {"temperature_c": 24.5, "humidity_rh": 52.0},
            expected_hub="sensorhub1",
        )
        self.assertEqual(decoded["temperature_c"], 24.5)
        self.assertEqual(decoded["contract"]["schema"], "legacy.flat")

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
