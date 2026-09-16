"""Bounded thread registry for audio subprocess watchers."""

from __future__ import annotations

import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

ProcessWatcher = Callable[[Any], None]


def terminate_audio_process(process: Any, timeout: float = 1.0) -> str | None:
    """Terminate, escalate to kill, and always reap an audio subprocess."""
    error: Exception | None = None
    try:
        process.terminate()
    except Exception as exc:
        error = exc
    try:
        process.wait(timeout=timeout)
        return str(error) if error else None
    except subprocess.TimeoutExpired:
        pass
    except Exception as exc:
        error = exc
    try:
        process.kill()
        process.wait(timeout=timeout)
    except Exception as exc:
        error = exc
    return str(error) if error else None


class AudioWatcherRegistry:
    """Register watchers before start and drain them to one deadline."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._threads: set[threading.Thread] = set()

    def start(self, process: Any, watcher: ProcessWatcher) -> None:
        """Start one named watcher with rollback when thread start fails."""
        thread = threading.Thread(
            target=self._run,
            args=(process, watcher),
            name=f"zeep-audio-watch-{getattr(process, 'pid', 'unknown')}",
            daemon=True,
        )
        with self._lock:
            self._threads.add(thread)
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._threads.discard(thread)
            raise

    def _run(self, process: Any, watcher: ProcessWatcher) -> None:
        try:
            watcher(process)
        finally:
            with self._lock:
                self._threads.discard(threading.current_thread())

    def drain(self, timeout: float) -> tuple[str, ...]:
        """Join current watchers and return names still alive at the deadline."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._lock:
            watchers = tuple(self._threads)
        current = threading.current_thread()
        for watcher in watchers:
            if watcher is not current:
                watcher.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            return tuple(
                watcher.name for watcher in self._threads if watcher.is_alive()
            )

    @property
    def active_count(self) -> int:
        """Return the number of registered live or draining watchers."""
        with self._lock:
            return len(self._threads)
