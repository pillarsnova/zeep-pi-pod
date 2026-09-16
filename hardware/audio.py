"""Audio playback adapter with persistent MPV IPC control."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from hardware.audio_library import (
    DEFAULT_AUDIO_MODE,
    DEFAULT_AUDIO_VOLUME_PERCENT,
    contained_audio_paths,
    default_music_state,
)
from hardware.audio_process import AudioProcessAdapter
from hardware.audio_runtime import (
    AudioRuntimeDiscovery,
    AudioRuntimeSelection,
    SystemAudioRuntimeAdapter,
)
from hardware.audio_watchers import AudioWatcherRegistry, terminate_audio_process

__all__ = (
    "AudioPlayer",
    "DEFAULT_AUDIO_MODE",
    "DEFAULT_AUDIO_VOLUME_PERCENT",
    "contained_audio_paths",
    "default_music_state",
)


class AudioPlayer:
    """Play local ZEEP audio without reopening the device per track.

    MPV is preferred on the Pi. ``afplay`` and ``ffplay`` are development
    fallbacks with fewer live-control capabilities.
    """

    def __init__(
        self,
        *,
        music_dir: Path,
        max_volume: int,
        state: dict[str, Any],
        state_lock: threading.Lock,
        runtime_discovery: AudioRuntimeDiscovery | None = None,
        process_adapter: AudioProcessAdapter | None = None,
    ) -> None:
        self.music_dir = music_dir
        self.max_volume = max_volume
        self.state = state
        self.state_lock = state_lock
        self.proc: subprocess.Popen[str] | None = None
        self.sock_path: str | None = None
        self.lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._watchers = AudioWatcherRegistry()
        self._runtime_discovery = runtime_discovery or SystemAudioRuntimeAdapter()
        self._process_adapter = process_adapter or AudioProcessAdapter()
        self._initialized = False
        self._closing = False
        self._closed = False
        self.backend: str | None = None
        self.audio_device: str | None = None
        self.loop = False
        self.current_path: Path | None = None
        self.queue_paths: list[Path] = []
        self.queue_index = 0

    def initialize(self) -> AudioRuntimeSelection:
        """Discover and publish audio capabilities once per active lifecycle."""
        with self._lifecycle_lock:
            if self._closing:
                raise RuntimeError("Audio runtime is closing")
            was_closed = self._closed
            self._closed = False
            try:
                return self._initialize_locked()
            except Exception:
                self._closed = was_closed
                raise

    def _initialize_locked(self) -> AudioRuntimeSelection:
        """Initialize while the caller owns the lifecycle lock."""
        if self._initialized:
            return AudioRuntimeSelection(self.backend, self.audio_device)
        self.music_dir.mkdir(parents=True, exist_ok=True)
        selected = self._runtime_discovery.discover()
        socket_path = self._process_adapter.resolve_socket_path()
        self._publish_runtime(selected.backend, selected.audio_device)
        self.sock_path = socket_path
        self.backend = selected.backend
        self.audio_device = selected.audio_device
        self._initialized = True
        return selected

    def _ensure_runtime_locked(self) -> AudioRuntimeSelection:
        """Lazy-start only a new runtime; shutdown requires explicit reopen."""
        if self._closing or self._closed:
            raise RuntimeError("Audio runtime is closed")
        return self._initialize_locked()

    def _publish_runtime(
        self,
        backend: str | None,
        audio_device: str | None,
    ) -> None:
        """Expose only the selected capability through synchronized state."""
        with self.state_lock:
            system = self.state.setdefault("system", {})
            system["player"] = backend
            system["audio_device"] = audio_device

    @property
    def initialized(self) -> bool:
        """Return whether runtime discovery completed for this lifecycle."""
        with self._lifecycle_lock:
            return self._initialized

    def _cleanup_socket(self) -> None:
        self._process_adapter.cleanup_socket(self.sock_path)

    def _send(self, command: list[Any]) -> bool:
        return self._process_adapter.send(self.sock_path, command)

    def _send_commands(self, commands: list[list[Any]]) -> bool:
        """Send ordered MPV commands through one short-lived socket."""
        return self._process_adapter.send_commands(self.sock_path, commands)

    def _send_retry(
        self,
        command: list[Any],
        attempts: int = 5,
        delay: float = 0.2,
    ) -> bool:
        return self._process_adapter.send_retry(
            self.sock_path,
            command,
            attempts,
            delay,
        )

    def _spawn(
        self,
        file_path: Path,
        volume: int,
    ) -> subprocess.Popen[str]:
        return self._process_adapter.spawn(
            backend=self.backend,
            audio_device=self.audio_device,
            socket_path=self.sock_path,
            file_path=file_path,
            volume=volume,
            loop=self.loop,
        )

    def _process_error(self, proc: subprocess.Popen[str]) -> str:
        return self._process_adapter.process_error(proc)

    def play(
        self,
        file_path: Path,
        loop: bool = False,
        queue: bool = False,
    ) -> None:
        """Start or replace playback and update the authoritative state."""
        with self._lifecycle_lock:
            self._ensure_runtime_locked()
            with self.lock:
                self.loop = bool(loop)
                queue_paths = self._queue_for(file_path, queue)
                if self._replace_active_mpv(file_path, queue_paths, queue):
                    return

                self._stop_locked()
                self._cleanup_socket()
                self.loop = bool(loop)
                self.current_path = file_path
                self.queue_paths = queue_paths
                self.queue_index = 0
                with self.state_lock:
                    volume = int(self.state["music"]["volume"])
                self.proc = self._spawn(file_path, volume)
                proc = self.proc
                time.sleep(0.2)
                if proc.poll() is not None:
                    error = self._publish_spawn_error(proc)
                    raise RuntimeError(error)
                self._publish_playing(file_path, queue)
                self._start_watcher_locked(proc)

    def _start_watcher_locked(self, proc: subprocess.Popen[str]) -> None:
        """Register a spawned process or roll it back while holding player lock."""
        try:
            self._watchers.start(proc, self._watch)
        except Exception:
            if self.proc is proc:
                self._stop_locked()
            raise

    def _queue_for(self, file_path: Path, queue: bool) -> list[Path]:
        if not queue or self.loop:
            return [file_path]
        ordered = contained_audio_paths(self.music_dir)
        if file_path in ordered:
            return ordered[ordered.index(file_path) :]
        return [file_path]

    def _replace_active_mpv(
        self,
        file_path: Path,
        queue_paths: list[Path],
        queue: bool,
    ) -> bool:
        active = (
            self.backend == "mpv" and self.proc is not None and self.proc.poll() is None
        )
        commands = [
            ["loadfile", str(file_path), "replace"],
            ["set_property", "loop-file", "inf" if self.loop else "no"],
            ["set_property", "pause", False],
        ]
        if not active or not self._send_commands(commands):
            return False
        self.current_path = file_path
        self.queue_paths = queue_paths
        self.queue_index = 0
        self._publish_playing(file_path, queue)
        return True

    def _publish_playing(self, file_path: Path, queue: bool) -> None:
        mode = "repeat_one" if self.loop else "queue" if queue else "single"
        with self.state_lock:
            self.state["music"].update(
                {
                    "playing": True,
                    "paused": False,
                    "track": file_path.name,
                    "loop": self.loop,
                    "mode": mode,
                    "queue_position": 1,
                    "queue_length": len(self.queue_paths),
                    "error": None,
                }
            )

    def _publish_spawn_error(self, proc: subprocess.Popen[str]) -> str:
        error = self._process_error(proc)
        self.proc = None
        self.current_path = None
        with self.state_lock:
            self.state["music"].update(
                {
                    "playing": False,
                    "paused": False,
                    "track": None,
                    "loop": True,
                    "mode": DEFAULT_AUDIO_MODE,
                    "queue_position": 0,
                    "queue_length": 0,
                    "error": error,
                }
            )
        return error

    def _watch(self, proc: subprocess.Popen[str]) -> None:
        """Advance a queue or clear playback state when a process exits."""
        proc.wait()
        error = self._process_error(proc) if proc.returncode else None
        with self.lock:
            if self.proc is not proc:
                return
            if self._restart_afplay_loop(proc):
                return
            if not error and self._start_next_queue_track():
                return
            self.proc = None
            self._cleanup_socket()
            with self.state_lock:
                mode = self.state["music"].get("mode", DEFAULT_AUDIO_MODE)
                if mode not in {"repeat_one", "queue"}:
                    mode = DEFAULT_AUDIO_MODE
                self.state["music"].update(
                    {
                        "playing": False,
                        "paused": False,
                        "track": None,
                        "loop": mode == "repeat_one",
                        "mode": mode,
                        "queue_position": 0,
                        "queue_length": 0,
                        "error": error,
                    }
                )
            if error:
                print(f"[MUSIC] player failed: {error}")

    def _restart_afplay_loop(self, proc: subprocess.Popen[str]) -> bool:
        if not (
            self.backend == "afplay"
            and self.loop
            and self.current_path is not None
            and proc.returncode == 0
        ):
            return False
        with self.state_lock:
            volume = int(self.state["music"]["volume"])
        self.proc = self._spawn(self.current_path, volume)
        self._start_watcher_locked(self.proc)
        return True

    def _start_next_queue_track(self) -> bool:
        if self.loop or self.queue_index + 1 >= len(self.queue_paths):
            return False
        self.queue_index += 1
        self.current_path = self.queue_paths[self.queue_index]
        self._cleanup_socket()
        with self.state_lock:
            volume = int(self.state["music"]["volume"])
        self.proc = self._spawn(self.current_path, volume)
        next_proc = self.proc
        with self.state_lock:
            self.state["music"].update(
                {
                    "playing": True,
                    "paused": False,
                    "track": self.current_path.name,
                    "loop": False,
                    "mode": "queue",
                    "queue_position": self.queue_index + 1,
                    "queue_length": len(self.queue_paths),
                    "error": None,
                }
            )
        self._start_watcher_locked(next_proc)
        return True

    def _stop_locked(self) -> None:
        with self.state_lock:
            mode = self.state["music"].get("mode", DEFAULT_AUDIO_MODE)
        if mode not in {"repeat_one", "queue"}:
            mode = DEFAULT_AUDIO_MODE
        self.loop = False
        self.current_path = None
        self.queue_paths = []
        self.queue_index = 0
        if self.proc and self.proc.poll() is None:
            error = terminate_audio_process(self.proc)
            if error:
                print(f"[MUSIC] process cleanup failed: {error}")
        self.proc = None
        self._cleanup_socket()
        with self.state_lock:
            self.state["music"].update(
                {
                    "playing": False,
                    "paused": False,
                    "track": None,
                    "loop": mode == "repeat_one",
                    "mode": mode,
                    "queue_position": 0,
                    "queue_length": 0,
                }
            )

    def stop(self) -> None:
        """Stop playback and clear its queue."""
        with self.lock:
            self._stop_locked()

    def shutdown(self, watcher_timeout: float = 2.0) -> None:
        """Stop playback, drain watcher threads and release runtime selection."""
        with self._lifecycle_lock:
            self._closing = True
            errors: list[str] = []
            survivors: tuple[str, ...] = ()
            try:
                try:
                    self.stop()
                except Exception as exc:
                    errors.append(f"stop failed: {exc}")
                try:
                    survivors = self._watchers.drain(watcher_timeout)
                except Exception as exc:
                    errors.append(f"watcher drain failed: {exc}")
            finally:
                self.backend = None
                self.audio_device = None
                self._initialized = False
                self._closed = True
                try:
                    self._publish_runtime(None, None)
                except Exception as exc:
                    errors.append(f"status publication failed: {exc}")
                finally:
                    self._closing = False
            if survivors:
                errors.append(f"watchers still draining: {', '.join(survivors)}")
            if errors:
                print(f"[MUSIC] shutdown incomplete: {'; '.join(errors)}")

    def pause_toggle(self) -> bool:
        """Toggle MPV pause and report whether the command was accepted."""
        with self._lifecycle_lock:
            self._ensure_runtime_locked()
            with self.lock:
                with self.state_lock:
                    if not self.state["music"]["playing"]:
                        return True
                    paused = not bool(self.state["music"]["paused"])
                if self.backend != "mpv":
                    return False
                if not self._send_retry(["set_property", "pause", paused]):
                    return False
                with self.state_lock:
                    self.state["music"]["paused"] = paused
                return True

    def set_volume(self, volume: int) -> None:
        """Apply a bounded volume to MPV and the authoritative state."""
        bounded = max(0, min(self.max_volume, int(volume)))
        with self._lifecycle_lock:
            self._ensure_runtime_locked()
            with self.lock:
                if self.backend == "mpv":
                    self._send(["set_property", "volume", bounded])
            with self.state_lock:
                self.state["music"]["volume"] = bounded

    def snapshot(self) -> dict[str, Any]:
        """Return a detached music-only state without building a Pod snapshot."""
        with self.state_lock:
            return dict(self.state["music"])
