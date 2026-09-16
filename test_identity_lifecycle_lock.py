"""Concurrency regression for local identity lifecycle serialization."""

from __future__ import annotations

import threading
import unittest

from identity.lifecycle_lock import synchronized_by


class IdentityLifecycleLockTests(unittest.TestCase):
    def test_second_operation_waits_for_first_operation(self) -> None:
        lock = threading.RLock()
        first_entered = threading.Event()
        release_first = threading.Event()
        second_done = threading.Event()
        order = []

        @synchronized_by(lock)
        def first_operation() -> None:
            first_entered.set()
            release_first.wait(timeout=1)
            order.append("first")

        @synchronized_by(lock)
        def second_operation() -> None:
            order.append("second")
            second_done.set()

        first_thread = threading.Thread(target=first_operation)
        second_thread = threading.Thread(target=second_operation)
        first_thread.start()
        self.assertTrue(first_entered.wait(timeout=1))
        second_thread.start()
        self.assertFalse(second_done.wait(timeout=0.05))

        release_first.set()
        first_thread.join(timeout=1)
        second_thread.join(timeout=1)

        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(order, ["first", "second"])


if __name__ == "__main__":
    unittest.main()
