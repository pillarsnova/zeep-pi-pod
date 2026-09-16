"""Regression tests for explicit, import-safe occupancy initialization."""

from __future__ import annotations

import ast
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pod_occupancy import OccupancyStore


class OccupancyStoreLifecycleTests(unittest.TestCase):
    def test_constructor_does_not_touch_filesystem_or_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            with patch("pod_occupancy.sqlite3.connect") as connect:
                store = OccupancyStore(data_dir, ttl_seconds=45)

            connect.assert_not_called()
            self.assertFalse(data_dir.exists())
            self.assertFalse(store.path.exists())
            self.assertFalse(store.initialized)

    def test_initialize_creates_existing_schema_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OccupancyStore(Path(tmp) / "data", ttl_seconds=45)
            real_connect = sqlite3.connect

            with patch(
                "pod_occupancy.sqlite3.connect",
                wraps=real_connect,
            ) as connect:
                store.initialize()
                store.initialize()

            self.assertEqual(connect.call_count, 1)
            self.assertTrue(store.initialized)
            with closing(sqlite3.connect(store.path)) as connection:
                table = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='occupancy_leases'"
                ).fetchone()
                index = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='index' AND name='idx_occupancy_expiry'"
                ).fetchone()
            self.assertEqual(table, ("occupancy_leases",))
            self.assertEqual(index, ("idx_occupancy_expiry",))

    def test_read_before_explicit_startup_preserves_previous_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OccupancyStore(Path(tmp) / "data", ttl_seconds=45)

            self.assertEqual(store.list_active(), [])
            self.assertTrue(store.path.exists())
            self.assertTrue(store.initialized)

    def test_failed_schema_open_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OccupancyStore(Path(tmp) / "data", ttl_seconds=45)

            with patch.object(
                store,
                "_open_connection",
                side_effect=sqlite3.OperationalError("busy"),
            ):
                with self.assertRaisesRegex(sqlite3.OperationalError, "busy"):
                    store.initialize()
            self.assertFalse(store.initialized)

            store.initialize()

            self.assertTrue(store.initialized)
            self.assertTrue(store.path.exists())

    def test_explicit_startup_keeps_acquire_and_read_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = OccupancyStore(Path(tmp) / "data", ttl_seconds=45)
            store.initialize()

            lease = store.acquire(
                subject="zeep:user-1",
                pod_id="pod-01",
                pod_session_id="session-1",
                username="tester",
            )
            active = store.list_active()

            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["lease_id"], lease.lease_id)
            self.assertEqual(active[0]["subject"], "zeep:user-1")
            self.assertEqual(active[0]["pod_id"], "pod-01")

    def test_app_lifespan_initializes_store_before_first_health_read(self) -> None:
        source = (Path(__file__).resolve().parent / "app.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        lifespan = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan"
        )
        initialize_line = next(
            node.lineno
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "occupancy_store"
            and node.func.attr == "initialize"
        )
        health_line = next(
            node.lineno
            for node in ast.walk(lifespan)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "occupancy_client"
            and node.func.attr == "health"
        )

        self.assertLess(initialize_line, health_line)


if __name__ == "__main__":
    unittest.main()
