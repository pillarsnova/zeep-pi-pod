"""Regression tests for explicit, import-safe GPIO initialization."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from hardware import gpio as gpio_module


class FakeFactory:
    """Minimal lgpio factory double that records lifecycle operations."""

    calls: list[tuple[object, ...]] = []

    def __init__(self, *, chip: int) -> None:
        self.calls.append(("factory", chip))

    def close(self) -> None:
        self.calls.append(("factory_close",))


class FakeOutputDevice:
    """Minimal gpiozero output double used by the manager tests."""

    calls: list[tuple[object, ...]] = FakeFactory.calls

    def __init__(
        self,
        pin: int,
        *,
        active_high: bool,
        initial_value: bool,
        pin_factory: FakeFactory,
    ) -> None:
        del pin_factory
        self.pin = pin
        self.calls.append(("output", pin, active_high, initial_value))

    def on(self) -> None:
        self.calls.append(("on", self.pin))

    def off(self) -> None:
        self.calls.append(("off", self.pin))

    def close(self) -> None:
        self.calls.append(("output_close", self.pin))


class SlowFactory(FakeFactory):
    """Widen a potential concurrent initialization race deterministically."""

    def __init__(self, *, chip: int) -> None:
        time.sleep(0.02)
        super().__init__(chip=chip)


class GPIOManagerLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeFactory.calls.clear()
        self.state = {
            "gpio": {"led": False, "door": False},
            "system": {"gpio_available": False, "gpio_error": None},
        }
        self.manager = gpio_module.GPIOManager(
            {"led": 22, "door": 17},
            self.state,
            threading.Lock(),
        )

    def test_constructor_does_not_acquire_hardware(self) -> None:
        self.assertEqual(FakeFactory.calls, [])
        self.assertFalse(self.manager.ready)
        self.assertIsNone(self.manager.error)

    def test_initialize_acquires_outputs_once_and_keeps_existing_contract(self) -> None:
        environment = {
            "ZEEP_GPIO_ENABLED": "1",
            "GPIO_INIT_ATTEMPTS": "1",
        }
        with (
            patch.dict(os.environ, environment),
            patch.object(gpio_module, "GPIO_AVAILABLE", True),
            patch.object(gpio_module, "LGPIOFactory", FakeFactory),
            patch.object(gpio_module, "OutputDevice", FakeOutputDevice),
        ):
            self.assertTrue(self.manager.initialize())
            self.assertTrue(self.manager.initialize())

        self.assertTrue(self.manager.ready)
        self.assertTrue(self.state["system"]["gpio_available"])
        self.assertIsNone(self.state["system"]["gpio_error"])
        self.assertEqual(
            FakeFactory.calls,
            [
                ("factory", 0),
                ("output", 22, True, False),
                ("output", 17, True, False),
            ],
        )

    def test_disabled_environment_never_acquires_hardware(self) -> None:
        with (
            patch.dict(os.environ, {"ZEEP_GPIO_ENABLED": "0"}),
            patch.object(gpio_module, "GPIO_AVAILABLE", True),
            patch.object(gpio_module, "LGPIOFactory", FakeFactory),
            patch.object(gpio_module, "OutputDevice", FakeOutputDevice),
        ):
            self.assertFalse(self.manager.initialize())

        self.assertEqual(FakeFactory.calls, [])
        self.assertFalse(self.manager.ready)
        self.assertIn("ZEEP_GPIO_ENABLED=0", self.manager.error or "")
        self.assertFalse(self.state["system"]["gpio_available"])
        self.assertIn(
            "ZEEP_GPIO_ENABLED=0",
            self.state["system"]["gpio_error"],
        )

    def test_concurrent_initialize_acquires_one_factory(self) -> None:
        environment = {
            "ZEEP_GPIO_ENABLED": "1",
            "GPIO_INIT_ATTEMPTS": "1",
        }
        with (
            patch.dict(os.environ, environment),
            patch.object(gpio_module, "GPIO_AVAILABLE", True),
            patch.object(gpio_module, "LGPIOFactory", SlowFactory),
            patch.object(gpio_module, "OutputDevice", FakeOutputDevice),
            ThreadPoolExecutor(max_workers=8) as executor,
        ):
            results = list(
                executor.map(lambda _index: self.manager.initialize(), range(8))
            )

        self.assertTrue(all(results))
        self.assertEqual(FakeFactory.calls.count(("factory", 0)), 1)

    def test_shutdown_releases_hardware_and_publishes_unavailable(self) -> None:
        environment = {
            "ZEEP_GPIO_ENABLED": "1",
            "GPIO_INIT_ATTEMPTS": "1",
        }
        with (
            patch.dict(os.environ, environment),
            patch.object(gpio_module, "GPIO_AVAILABLE", True),
            patch.object(gpio_module, "LGPIOFactory", FakeFactory),
            patch.object(gpio_module, "OutputDevice", FakeOutputDevice),
        ):
            self.assertTrue(self.manager.initialize())
            self.manager.shutdown()

        self.assertFalse(self.manager.ready)
        self.assertFalse(self.state["system"]["gpio_available"])
        self.assertIn(("factory_close",), FakeFactory.calls)


class AppGPIOImportSafetyTests(unittest.TestCase):
    def test_persistent_stores_initialize_before_gpio_acquisition(self) -> None:
        source = (Path(__file__).resolve().parent / "app.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        lifespan = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        )
        calls = {
            node.func.value.id: node.lineno
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "initialize"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id
            in {
                "database",
                "auth_sessions",
                "occupancy_store",
                "baselines",
                "gpio",
            }
        }

        self.assertEqual(
            sorted(calls, key=calls.get),
            [
                "database",
                "auth_sessions",
                "occupancy_store",
                "baselines",
                "gpio",
            ],
        )

    def test_app_import_is_hardware_quiet_until_explicit_startup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="zeep-gpio-import-") as raw_root:
            root = Path(raw_root)
            marker = root / "gpio-calls.txt"
            invalid_admin_file = root / "invalid-local-admins.json"
            invalid_admin_file.write_text("{not-json", encoding="utf-8")
            script = textwrap.dedent(
                """
                import os
                from pathlib import Path

                import hardware.gpio as gpio_module

                marker = Path(os.environ["GPIO_TEST_MARKER"])

                def record(value):
                    with marker.open("a", encoding="utf-8") as output:
                        output.write(value + "\\n")

                class Factory:
                    def __init__(self, *, chip):
                        record(f"factory:{chip}")

                    def close(self):
                        record("factory:close")

                class Output:
                    def __init__(
                        self,
                        pin,
                        *,
                        active_high,
                        initial_value,
                        pin_factory,
                    ):
                        del active_high, initial_value, pin_factory
                        self.pin = pin
                        record(f"output:{pin}")

                    def on(self):
                        record(f"on:{self.pin}")

                    def off(self):
                        record(f"off:{self.pin}")

                    def close(self):
                        record(f"close:{self.pin}")

                gpio_module.GPIO_AVAILABLE = True
                gpio_module.LGPIOFactory = Factory
                gpio_module.OutputDevice = Output

                import app

                assert not marker.exists(), "app import touched GPIO hardware"
                data_dir = Path(os.environ["DATA_DIR"])
                assert not (data_dir / "auth.db").exists()
                assert not (data_dir / "occupancy.db").exists()
                assert app.auth_sessions.initialized is False
                assert app.occupancy_store.initialized is False
                assert app.baselines.initialized is False
                assert app.state["system"]["gpio_available"] is False
                assert app.state["system"]["gpio_error"] is None
                assert app.gpio.initialize() is True
                assert app.state["system"]["gpio_available"] is True
                assert marker.read_text(encoding="utf-8").startswith("factory:0\\n")
                app.gpio.shutdown()
                """
            )
            environment = os.environ.copy()
            environment.update(
                {
                    "PYTHONPATH": str(Path(__file__).resolve().parent),
                    "DATA_DIR": str(root / "data"),
                    "BACKUP_DIR": str(root / "backup"),
                    "MUSIC_DIR": str(root / "music"),
                    "EVENT_LOG_PATH": str(root / "events.jsonl"),
                    "EVENT_LOG_FILE_ENABLED": "0",
                    "EVENT_LOG_STDOUT_ENABLED": "0",
                    "GPIO_TEST_MARKER": str(marker),
                    "LOCAL_ADMIN_ACCOUNTS_FILE": str(invalid_admin_file),
                    "ZEEP_GPIO_ENABLED": "1",
                    "GPIO_INIT_ATTEMPTS": "1",
                }
            )
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=Path(__file__).resolve().parent,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
