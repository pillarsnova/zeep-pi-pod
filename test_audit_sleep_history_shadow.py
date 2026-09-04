import unittest
import stat
import tempfile
from pathlib import Path

from audit_sleep_history_shadow import ShadowPath, private_write_bytes


class ShadowPathParityTests(unittest.TestCase):
    def test_pending_allowed_transition_holds_previous_confirmed_state(self):
        path = ShadowPath()
        path.last = "wake"
        path.stage_since = 0.0

        held, metadata = path.step("n1", 100.0, False)

        self.assertEqual(held, "wake")
        self.assertEqual(metadata["confirmed_state"], "wake")
        self.assertEqual(metadata["decision"], "confirming")

    def test_initial_state_is_not_published_before_confirmation(self):
        path = ShadowPath()

        first, _ = path.step("wake", 30.0, False)
        second, metadata = path.step("wake", 60.0, False)

        self.assertIsNone(first)
        self.assertEqual(second, "wake")
        self.assertEqual(metadata["decision"], "confirmed")

    def test_health_artifact_is_owner_only_even_when_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.json"
            path.write_bytes(b"old")
            path.chmod(0o644)

            private_write_bytes(path, b"reviewed")

            self.assertEqual(path.read_bytes(), b"reviewed")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
