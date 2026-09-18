"""Regression tests for the fleet-ready embedded-device contract."""

from __future__ import annotations

import unittest

from adaptive.control_policy import advisory_control_policy, enforce_advisory
from hardware.device_contract import device_health_contract
from hardware.fleet_health import local_pod_health


class DeviceContractTests(unittest.TestCase):
    def test_common_contract_exposes_identity_provenance_and_quality(self) -> None:
        result = device_health_contract(
            {
                "device_id": "hub-1",
                "connected": True,
                "last_update": 95.0,
                "firmware_version": "1.2.3",
                "firmware_sha256": "abc",
                "boot_id": "boot-a",
                "seq": 12,
                "wifi_rssi": -42,
            },
            pod_id="pod-a",
            device_id="fallback",
            device_type="sensor_hub",
            transport="mqtt",
            stale_seconds=10,
            now=100.0,
        )
        self.assertEqual(result["device_id"], "hub-1")
        self.assertEqual(result["firmware"]["sha256"], "abc")
        self.assertEqual(result["runtime"]["boot_id"], "boot-a")
        self.assertTrue(result["quality"]["valid"])

    def test_stale_device_fails_closed_without_erasing_identity(self) -> None:
        result = device_health_contract(
            {"connected": True, "last_update": 1.0, "firmware_version": "1.0"},
            pod_id="pod-a",
            device_id="hub-a",
            device_type="sensor_hub",
            transport="mqtt",
            stale_seconds=10,
            now=100.0,
        )
        self.assertFalse(result["quality"]["valid"])
        self.assertEqual(result["quality"]["reason"], "stale")
        self.assertEqual(result["firmware"]["version"], "1.0")

    def test_local_fleet_contains_all_embedded_boundaries(self) -> None:
        current = 100.0
        live = {"connected": True, "last_update": 99.0}
        result = local_pod_health(
            {
                "sensor": {"esp32": live, "sensorhub2": live, "bcg": live},
                "aircon": live,
                "bed_control": live,
            },
            pod_id="pod-a",
            stale_seconds={
                "sensorhub1": 10,
                "sensorhub2": 10,
                "bcg": 10,
                "controlhub1": 10,
                "controlhub2": 10,
            },
            now=current,
        )
        pod = result["pods"][0]
        self.assertEqual(pod["summary"]["devices_live"], 5)
        self.assertEqual(pod["summary"]["state"], "healthy")


class AdaptiveControlPolicyTests(unittest.TestCase):
    def test_ai_output_cannot_carry_executable_command(self) -> None:
        guarded = enforce_advisory(
            [{"candidate": "ลดแอร์", "executable": True, "command": "AC 18"}]
        )[0]
        self.assertFalse(guarded["executable"])
        self.assertTrue(guarded["requires_user_confirmation"])
        self.assertNotIn("command", guarded)
        self.assertIsNone(advisory_control_policy()["command_endpoint"])


if __name__ == "__main__":
    unittest.main()

