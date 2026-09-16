"""Characterization tests for display-only live API state projection."""

from __future__ import annotations

import unittest

from api_state_projection import (
    LiveDeviceProjectionPolicy,
    project_aircon_status,
    project_live_device_statuses,
    project_transport_status,
)


class TransportStatusProjectionTests(unittest.TestCase):
    def test_fresh_connected_source_retains_transport_and_reports_age(self) -> None:
        source = {
            "connected": True,
            "last_update": 98.04,
            "transport": "serial",
        }

        result = project_transport_status(
            source,
            now=100.0,
            stale_after_s=5.0,
            disconnected_reason="serial_disconnected",
        )

        self.assertIs(result, source)
        self.assertTrue(result["connected"])
        self.assertEqual(result["data_age_s"], 2.0)
        self.assertFalse(result["fallback_active"])
        self.assertNotIn("stale", result)

    def test_stale_connected_source_uses_stale_fallback(self) -> None:
        result = project_transport_status(
            {"connected": True, "last_update": 80.0},
            now=100.0,
            stale_after_s=15.0,
            disconnected_reason="mqtt_disconnected",
        )

        self.assertFalse(result["connected"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["data_age_s"], 20.0)
        self.assertTrue(result["fallback_active"])
        self.assertEqual(result["fallback_reason"], "stale")

    def test_quiet_disconnected_source_uses_transport_fallback_reason(self) -> None:
        result = project_transport_status(
            {"connected": False, "last_update": 99.0},
            now=100.0,
            stale_after_s=15.0,
            disconnected_reason="serial_disconnected",
        )

        self.assertTrue(result["fallback_active"])
        self.assertEqual(result["fallback_reason"], "serial_disconnected")

    def test_control_hub_projection_does_not_add_sensor_fallback_fields(self) -> None:
        result = project_transport_status(
            {"connected": True, "last_update": None},
            now=100.0,
            stale_after_s=70.0,
        )

        self.assertFalse(result["connected"])
        self.assertTrue(result["stale"])
        self.assertIsNone(result["data_age_s"])
        self.assertNotIn("fallback_active", result)
        self.assertNotIn("fallback_reason", result)


class AirconStatusProjectionTests(unittest.TestCase):
    policy = LiveDeviceProjectionPolicy(
        esp32_stale_s=25.0,
        sensorhub2_stale_s=15.0,
        bcg_stale_s=60.0,
        controlhub1_stale_s=70.0,
        controlhub2_stale_s=70.0,
        aircon_power_on_default_c=18,
        aircon_temperature_min_c=15,
        aircon_temperature_max_c=28,
    )

    def project(self, state: dict) -> dict:
        return project_aircon_status(
            state,
            now=100.0,
            policy=self.policy,
        )

    def test_aircon_contract_publishes_direct_in_range_setpoint(self) -> None:
        result = self.project(
            {
                "connected": True,
                "last_update": 99.0,
                "temperature_c": 28,
                "temperature_bias_c": -2,
            }
        )

        self.assertEqual(result["desired_temperature_c"], 28)
        self.assertEqual(result["temperature_mapping"], "direct_1_to_1")
        self.assertEqual(result["power_on_default_temperature_c"], 18)
        self.assertEqual(result["desired_temperature_min_c"], 15)
        self.assertEqual(result["desired_temperature_max_c"], 28)
        self.assertNotIn("temperature_bias_c", result)

    def test_aircon_contract_rejects_invalid_display_setpoints(self) -> None:
        for value in (True, None, 14, 29):
            with self.subTest(value=value):
                result = self.project(
                    {
                        "connected": True,
                        "last_update": 99.0,
                        "temperature_c": value,
                    }
                )
                self.assertIsNone(result["desired_temperature_c"])


class LiveDeviceStatusProjectionTests(unittest.TestCase):
    def test_all_live_device_contracts_are_composed_together(self) -> None:
        result = {
            "sensor": {
                "esp32": {"connected": True, "last_update": 90.0},
                "sensorhub2": {"connected": False, "last_update": 95.0},
                "bcg": {"connected": True, "last_update": 0.0},
            },
            "aircon": {
                "connected": True,
                "last_update": 99.0,
                "temperature_c": 24,
            },
            "bed_control": {"connected": True, "last_update": 99.0},
        }
        policy = LiveDeviceProjectionPolicy(
            esp32_stale_s=25.0,
            sensorhub2_stale_s=15.0,
            bcg_stale_s=60.0,
            controlhub1_stale_s=70.0,
            controlhub2_stale_s=70.0,
            aircon_power_on_default_c=18,
            aircon_temperature_min_c=15,
            aircon_temperature_max_c=28,
        )

        esp32, sensorhub2, bcg = project_live_device_statuses(
            result,
            now=100.0,
            policy=policy,
        )

        self.assertTrue(esp32["connected"])
        self.assertEqual(esp32["data_age_s"], 10.0)
        self.assertEqual(sensorhub2["fallback_reason"], "mqtt_disconnected")
        self.assertFalse(bcg["connected"])
        self.assertEqual(bcg["fallback_reason"], "stale")
        self.assertEqual(result["aircon"]["desired_temperature_c"], 24)
        self.assertEqual(result["bed_control"]["data_age_s"], 1.0)


if __name__ == "__main__":
    unittest.main()
