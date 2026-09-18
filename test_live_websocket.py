"""Regression tests for graceful live WebSocket disconnect handling."""

from __future__ import annotations

import asyncio
import unittest

from api.live_websocket import _notice_or_disconnect, _wait_for_client_event


class FakeWebSocket:
    def __init__(self, messages=None) -> None:
        self.messages = list(messages or [])

    async def receive(self):
        if self.messages:
            return self.messages.pop(0)
        await asyncio.Event().wait()


class LiveWebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_event_ends_loop_immediately(self) -> None:
        socket = FakeWebSocket([{"type": "websocket.disconnect"}])
        self.assertTrue(await _wait_for_client_event(socket, 0.01))

    async def test_idle_client_returns_to_snapshot_cadence(self) -> None:
        socket = FakeWebSocket()
        self.assertFalse(await _wait_for_client_event(socket, 0.001))

    async def test_disconnect_cancels_pending_report_wait(self) -> None:
        cancelled = asyncio.Event()

        async def pending_notice(subject):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        socket = FakeWebSocket([{"type": "websocket.disconnect", "code": 1012}])
        result = await asyncio.wait_for(
            _notice_or_disconnect(socket, pending_notice, "synthetic"), 0.1
        )
        self.assertEqual(result, (None, True))
        self.assertTrue(cancelled.is_set())

    async def test_ready_report_is_delivered_without_waiting_for_disconnect(self) -> None:
        async def ready_notice(subject):
            return {"ready": True}

        result = await asyncio.wait_for(
            _notice_or_disconnect(FakeWebSocket(), ready_notice, "synthetic"), 0.1
        )
        self.assertEqual(result, ({"ready": True}, False))


if __name__ == "__main__":
    unittest.main()
