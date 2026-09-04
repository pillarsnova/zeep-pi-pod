"""Fail-closed GPIO output adapter for physical ZEEP hardware."""

from __future__ import annotations

import os
import time
from threading import Lock
from typing import Any

from fastapi import HTTPException

try:
    from gpiozero import OutputDevice
    from gpiozero.pins.lgpio import LGPIOFactory

    GPIO_AVAILABLE = True
except Exception:
    OutputDevice = None
    LGPIOFactory = None
    GPIO_AVAILABLE = False


class GPIOManager:
    """Drive real outputs and fail closed when GPIO is unavailable."""

    def __init__(
        self,
        pins: dict[str, int],
        state: dict[str, Any],
        state_lock: Lock,
    ) -> None:
        self._pins = dict(pins)
        self._state = state
        self._state_lock = state_lock
        self.devices: dict[str, Any] = {}
        self.factory: Any = None
        self.error: str | None = None
        if not GPIO_AVAILABLE:
            self.error = "GPIO เชื่อมต่อไม่ได้ (ไม่พบ gpiozero/lgpio ในเครื่องนี้)"
            print(f"[GPIO] {self.error}")
            return

        attempts = max(1, int(os.getenv("GPIO_INIT_ATTEMPTS", "10")))
        delay = max(
            0.1,
            float(os.getenv("GPIO_INIT_RETRY_SECONDS", "0.5")),
        )
        for attempt in range(1, attempts + 1):
            try:
                self.factory = LGPIOFactory(chip=0)
                for name, pin in self._pins.items():
                    self.devices[name] = OutputDevice(
                        pin,
                        active_high=True,
                        initial_value=False,
                        pin_factory=self.factory,
                    )
                self.error = None
                print(f"[GPIO] connected: chip=0, outputs={len(self.devices)}")
                return
            except Exception as exc:
                self.close()
                self.error = f"GPIO เชื่อมต่อไม่ได้: {exc}"
                is_busy = "busy" in str(exc).lower()
                if attempt < attempts and is_busy:
                    print(f"[GPIO] busy; retry {attempt}/{attempts} in {delay}s")
                    time.sleep(delay)
                    continue
                print(f"[GPIO] {self.error}")
                return

    def close(self) -> None:
        """Release output devices and the lgpio factory."""
        for device in self.devices.values():
            try:
                device.close()
            except Exception:
                pass
        self.devices = {}
        if self.factory is not None:
            try:
                self.factory.close()
            except Exception:
                pass
        self.factory = None

    @property
    def ready(self) -> bool:
        """Return whether every configured output is available."""
        return len(self.devices) == len(self._pins)

    def require_ready(self) -> None:
        """Reject a control request unless all outputs initialized."""
        if not self.ready:
            raise HTTPException(
                503,
                self.error or "GPIO เชื่อมต่อไม่ได้",
            )

    def set(self, name: str, on: bool) -> None:
        """Set one configured output and update the shared state."""
        if name not in self._pins:
            raise KeyError(name)
        if not self.ready:
            raise RuntimeError(self.error or "GPIO เชื่อมต่อไม่ได้")
        device = self.devices[name]
        if on:
            device.on()
        else:
            device.off()
        with self._state_lock:
            self._state["gpio"][name] = bool(on)

    def all_off(self) -> None:
        """Best-effort shutdown of every configured output."""
        for name in self._pins:
            try:
                self.set(name, False)
            except Exception:
                pass

    def shutdown(self) -> None:
        """Turn outputs off and release all GPIO resources."""
        self.all_off()
        self.close()
