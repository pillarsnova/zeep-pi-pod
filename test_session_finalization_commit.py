"""Focused regressions for the atomic Session finalization boundary."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, call

from sessions.finalization_commit import (
    FinalizationPorts,
    build_session_finalize_payload,
    commit_live_session_finalization,
)


class SessionFinalizationCommitTests(unittest.TestCase):
    @staticmethod
    def active_session() -> dict[str, Any]:
        return {
            "record": {
                "session_id": "session-1",
                "ended_at_utc": "2026-09-16T03:00:00+00:00",
                "duration_s": 3_600.0,
                "note": "completed",
                "end_reason": "logout",
                "started_monotonic": 123.0,
            }
        }

    def test_payload_preserves_final_summary_and_terminal_wake_contract(self) -> None:
        active = self.active_session()
        final_summary = {"sleep_score": 91, "nested": {"state": "n2"}}
        terminal_wake = {
            "start_time": "2026-09-16T02:59:30+00:00",
            "state": "wake",
        }

        payload = build_session_finalize_payload(
            active["record"],
            final_summary,
            terminal_wake,
        )

        self.assertEqual(
            payload,
            {
                "session_id": "session-1",
                "end_time": "2026-09-16T03:00:00+00:00",
                "duration": 3_600.0,
                "note": "completed",
                "end_reason": "logout",
                "terminal_wake": {
                    "timestamp": "2026-09-16T02:59:30+00:00",
                    "value": terminal_wake,
                },
                "final_summary": final_summary,
            },
        )
        self.assertIs(payload["final_summary"], final_summary)
        self.assertIs(payload["terminal_wake"]["value"], terminal_wake)

    def test_payload_keeps_absent_terminal_wake_as_none(self) -> None:
        payload = build_session_finalize_payload(
            self.active_session()["record"],
            {"sleep_score": 91},
            None,
        )

        self.assertIsNone(payload["terminal_wake"])

    def test_success_flushes_before_removing_retry_state_and_checkpoint(self) -> None:
        active = self.active_session()
        final_summary = {"sleep_score": 91}
        events: list[str] = []
        captured: dict[str, Any] = {}

        def enqueue(store: str, action: str, payload: dict[str, Any]) -> None:
            events.append("enqueue")
            captured.update({"store": store, "action": action, "payload": payload})
            self.assertIn("started_monotonic", active["record"])

        def flush(timeout: float) -> bool:
            events.append("flush")
            self.assertEqual(timeout, 30)
            self.assertIn("started_monotonic", active["record"])
            return True

        def clear_checkpoint() -> None:
            events.append("clear_checkpoint")
            self.assertNotIn("started_monotonic", active["record"])

        recover_active = MagicMock()
        commit_live_session_finalization(
            active,
            final_summary,
            None,
            ports=FinalizationPorts(
                enqueue=enqueue,
                flush=flush,
                flush_failure=MagicMock(),
                recover_active=recover_active,
                clear_checkpoint=clear_checkpoint,
            ),
        )

        self.assertEqual(events, ["enqueue", "flush", "clear_checkpoint"])
        self.assertEqual(captured["store"], "sessions")
        self.assertEqual(captured["action"], "session_finalize")
        self.assertIs(captured["payload"]["final_summary"], final_summary)
        recover_active.assert_not_called()

    def test_enqueue_failure_recovers_without_clearing_retry_state(self) -> None:
        active = self.active_session()
        failure = RuntimeError("enqueue failed")
        enqueue = MagicMock(side_effect=failure)
        flush = MagicMock()
        recover_active = MagicMock()
        clear_checkpoint = MagicMock()

        with self.assertRaises(RuntimeError) as raised:
            commit_live_session_finalization(
                active,
                {},
                None,
                ports=FinalizationPorts(
                    enqueue=enqueue,
                    flush=flush,
                    flush_failure=MagicMock(),
                    recover_active=recover_active,
                    clear_checkpoint=clear_checkpoint,
                ),
            )

        self.assertIs(raised.exception, failure)
        flush.assert_not_called()
        recover_active.assert_called_once_with(active)
        clear_checkpoint.assert_not_called()
        self.assertEqual(active["record"]["started_monotonic"], 123.0)

    def test_false_flush_uses_existing_failure_factory_and_recovers(self) -> None:
        active = self.active_session()
        failure = RuntimeError("writer did not flush")
        flush_failure = MagicMock(return_value=failure)
        recover_active = MagicMock()
        clear_checkpoint = MagicMock()

        with self.assertRaises(RuntimeError) as raised:
            commit_live_session_finalization(
                active,
                {},
                None,
                ports=FinalizationPorts(
                    enqueue=MagicMock(),
                    flush=MagicMock(return_value=False),
                    flush_failure=flush_failure,
                    recover_active=recover_active,
                    clear_checkpoint=clear_checkpoint,
                ),
            )

        self.assertIs(raised.exception, failure)
        self.assertEqual(
            flush_failure.call_args_list,
            [call("before Session finalization")],
        )
        recover_active.assert_called_once_with(active)
        clear_checkpoint.assert_not_called()
        self.assertEqual(active["record"]["started_monotonic"], 123.0)

    def test_raised_flush_failure_recovers_and_propagates_original_error(self) -> None:
        active = self.active_session()
        failure = OSError("writer unavailable")
        recover_active = MagicMock()
        clear_checkpoint = MagicMock()
        flush_failure = MagicMock()

        with self.assertRaises(OSError) as raised:
            commit_live_session_finalization(
                active,
                {},
                None,
                ports=FinalizationPorts(
                    enqueue=MagicMock(),
                    flush=MagicMock(side_effect=failure),
                    flush_failure=flush_failure,
                    recover_active=recover_active,
                    clear_checkpoint=clear_checkpoint,
                ),
            )

        self.assertIs(raised.exception, failure)
        flush_failure.assert_not_called()
        recover_active.assert_called_once_with(active)
        clear_checkpoint.assert_not_called()
        self.assertEqual(active["record"]["started_monotonic"], 123.0)

    def test_checkpoint_failure_after_commit_does_not_recover_live_session(
        self,
    ) -> None:
        active = self.active_session()
        failure = OSError("checkpoint unlink failed")
        recover_active = MagicMock()

        with self.assertRaises(OSError) as raised:
            commit_live_session_finalization(
                active,
                {},
                None,
                ports=FinalizationPorts(
                    enqueue=MagicMock(),
                    flush=MagicMock(return_value=True),
                    flush_failure=MagicMock(),
                    recover_active=recover_active,
                    clear_checkpoint=MagicMock(side_effect=failure),
                ),
            )

        self.assertIs(raised.exception, failure)
        recover_active.assert_not_called()
        self.assertNotIn("started_monotonic", active["record"])

    def test_invalid_terminal_wake_fails_before_persistence_or_recovery(self) -> None:
        active = self.active_session()
        enqueue = MagicMock()
        recover_active = MagicMock()
        clear_checkpoint = MagicMock()

        with self.assertRaises(KeyError):
            commit_live_session_finalization(
                active,
                {},
                {},
                ports=FinalizationPorts(
                    enqueue=enqueue,
                    flush=MagicMock(return_value=True),
                    flush_failure=MagicMock(),
                    recover_active=recover_active,
                    clear_checkpoint=clear_checkpoint,
                ),
            )

        enqueue.assert_not_called()
        recover_active.assert_not_called()
        clear_checkpoint.assert_not_called()
        self.assertEqual(active["record"]["started_monotonic"], 123.0)


if __name__ == "__main__":
    unittest.main()
