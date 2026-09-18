"""Regression tests for graceful live WebSocket disconnect handling."""

from __future__ import annotations

import asyncio
import unittest

from api.live_websocket import _wait_for_client_event


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


if __name__ == "__main__":
    unittest.main()

