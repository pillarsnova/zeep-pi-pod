"""Serialized GPIO pulse operations for door and accessory outputs."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Collection

from fastapi import HTTPException


class PulseControlService:
    """Own pulse concurrency and cooldown state independently from HTTP."""

    def __init__(
        self,
        *,
        gpio,
        pulse_outputs: Collection[str],
        door_pulse_seconds: float,
        accessory_pulse_seconds: float,
        cooldown_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.gpio = gpio
        self.pulse_outputs = frozenset(pulse_outputs)
        self.door_pulse_seconds = door_pulse_seconds
        self.accessory_pulse_seconds = accessory_pulse_seconds
        self.cooldown_seconds = cooldown_seconds
        self.sleep = sleep
        self.door_lock = asyncio.Lock()
        self.pulse_locks = {name: asyncio.Lock() for name in self.pulse_outputs}
        self.pulse_last_end = {name: 0.0 for name in self.pulse_outputs}

    async def pulse_door(self, name: str) -> None:
        self.gpio.require_ready()
        if self.door_lock.locked():
            raise HTTPException(429, "Door command already in progress")
        async with self.door_lock:
            other = "door_close" if name == "door_open" else "door_open"
            self.gpio.set(other, False)
            self.gpio.set(name, True)
            try:
                await self.sleep(self.door_pulse_seconds)
            finally:
                self.gpio.set(name, False)

    async def pulse_accessory(self, name: str) -> None:
        if name not in self.pulse_outputs:
            raise HTTPException(404, "Unknown pulse output")
        self.gpio.require_ready()
        lock = self.pulse_locks[name]
        if lock.locked():
            raise HTTPException(429, f"{name} pulse already active")
        async with lock:
            if time.monotonic() - self.pulse_last_end[name] < self.cooldown_seconds:
                raise HTTPException(429, f"{name} is cooling down")
            self.gpio.set(name, True)
            try:
                await self.sleep(self.accessory_pulse_seconds)
            finally:
                self.gpio.set(name, False)
                self.pulse_last_end[name] = time.monotonic()
