"""Publication-scoped deadlines for bounded bed movement.

All movement and timed-stop publications share one lock. A deadline does not
depend on a browser connection or on the hardware acknowledging the command.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

MOVEMENT_COMMANDS = frozenset(
    {"head_up", "head_down", "foot_up", "foot_down", "flat", "center_all"}
)


class BedMotionService:
    """Serialize movement publications with generation-scoped fail-safe stops."""

    def __init__(
        self,
        *,
        duration_seconds: float,
        publish_stop: Callable[[str], bool],
        update_state: Callable[[dict[str, Any]], None],
        log_event: Callable[..., None],
        clock: Callable[[], float] = time.time,
        timer_factory: Callable[..., Any] = threading.Timer,
    ) -> None:
        self.duration_seconds = duration_seconds
        self._publish_stop = publish_stop
        self._update_state = update_state
        self._log_event = log_event
        self._clock = clock
        self._timer_factory = timer_factory
        self._lock = threading.RLock()
        self._generation = 0
        self._timer: Any = None
        self._closed = False

    def publish(self, command: str, send: Callable[[], None]) -> None:
        """Send a command and arm/cancel its deadline before releasing the lock."""
        with self._lock:
            if self._closed and command in MOVEMENT_COMMANDS:
                raise RuntimeError("Bed motion service is shutting down")
            send()
            if command in MOVEMENT_COMMANDS:
                self._schedule_locked(command)
            elif command == "bed_stop":
                self._cancel_locked("explicit_stop")

    def _schedule_locked(self, command: str) -> None:
        self._generation += 1
        generation = self._generation
        if self._timer is not None:
            self._timer.cancel()
        try:
            timer = self._timer_factory(
                self.duration_seconds,
                lambda: self._expire(generation, command),
            )
            timer.daemon = True
            self._timer = timer
            self._update_state(
                {
                    "motion_duration_s": self.duration_seconds,
                    "auto_stop_at": self._clock() + self.duration_seconds,
                    "auto_stop_pending": True,
                    "auto_stop_error": None,
                }
            )
            timer.start()
        except Exception:
            self._cancel_locked("schedule_failed")
            self._stop_locked("schedule_failed", command)
            raise

    def _cancel_locked(self, reason: str) -> None:
        self._generation += 1
        if self._timer is not None:
            self._timer.cancel()
        self._timer = None
        self._update_state({"auto_stop_at": None, "auto_stop_pending": False})
        self._log_event("controlhub2_bed", "auto_stop_cancelled", reason=reason)

    def _expire(self, generation: int, command: str) -> None:
        with self._lock:
            if self._closed or generation != self._generation:
                return
            # Keep the lock through the publication: a new movement must not
            # overtake this stop after its generation has been checked.
            self._timer = None
            self._stop_locked(f"auto_{self.duration_seconds:g}s", command)

    def _stop_locked(self, reason: str, command: str) -> None:
        published = self._publish_stop(f"{reason}:{command}")
        self._update_state(
            {
                "auto_stop_at": None,
                "auto_stop_pending": False,
                "auto_stop_error": None if published else "publish_failed",
            }
        )
        self._log_event(
            "controlhub2_bed",
            "auto_stop_completed" if published else "auto_stop_publish_failed",
            source_command=command,
            duration_s=self.duration_seconds,
            reason=reason,
        )

    def close(self) -> None:
        """Cancel pending work and stop movement when the service shuts down."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            timer = self._timer
            if timer is not None:
                self._cancel_locked("shutdown")
                self._stop_locked("shutdown", "pending_motion")
        if timer is not None and timer is not threading.current_thread():
            timer.join(timeout=1.0)
