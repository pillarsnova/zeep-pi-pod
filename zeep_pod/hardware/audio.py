"""Audio playback adapter with persistent MPV IPC control."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


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
    ) -> None:
        self.music_dir = music_dir
        self.max_volume = max_volume
        self.state = state
        self.state_lock = state_lock
        self.proc: subprocess.Popen[str] | None = None
        self.sock_path = os.path.join(
            tempfile.gettempdir(),
            "pi5_local_mpv.sock",
        )
        self.lock = threading.Lock()
        self.backend = next(
            (
                backend
                for backend in ("mpv", "afplay", "ffplay")
                if shutil.which(backend)
            ),
            None,
        )
        self.audio_device = os.getenv("MPV_AUDIO_DEVICE", "").strip() or None
        if self.backend == "mpv" and not self.audio_device:
            if Path("/proc/asound/Device").exists():
                self.audio_device = "alsa/plughw:CARD=Device,DEV=0"
        self.loop = False
        self.current_path: Path | None = None
        self.queue_paths: list[Path] = []
        self.queue_index = 0
        with self.state_lock:
            self.state["system"]["player"] = self.backend
            self.state["system"]["audio_device"] = self.audio_device

    def _cleanup_socket(self) -> None:
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass

    def _send(self, command: list[Any]) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(self.sock_path)
                payload = json.dumps({"command": command}) + "\n"
                sock.sendall(payload.encode())
            return True
        except Exception:
            return False

    def _send_commands(self, commands: list[list[Any]]) -> bool:
        """Send ordered MPV commands through one short-lived socket."""
        try:
            payload = "".join(
                json.dumps({"command": command}) + "\n" for command in commands
            ).encode()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                sock.connect(self.sock_path)
                sock.sendall(payload)
            return True
        except Exception:
            return False

    def _send_retry(
        self,
        command: list[Any],
        attempts: int = 5,
        delay: float = 0.2,
    ) -> bool:
        for _ in range(attempts):
            if self._send(command):
                return True
            time.sleep(delay)
        return False

    def _spawn(
        self,
        file_path: Path,
        volume: int,
    ) -> subprocess.Popen[str]:
        if self.backend == "mpv":
            command = [
                "mpv",
                "--no-config",
                "--no-video",
                "--really-quiet",
                f"--volume={volume}",
                f"--loop-file={'inf' if self.loop else 'no'}",
                f"--input-ipc-server={self.sock_path}",
            ]
            if self.audio_device:
                command.append(f"--audio-device={self.audio_device}")
            command.append(str(file_path))
        elif self.backend == "afplay":
            bounded_volume = max(0, min(100, volume)) / 100
            command = [
                "afplay",
                "-v",
                f"{bounded_volume:.2f}",
                str(file_path),
            ]
        elif self.backend == "ffplay":
            command = [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(max(0, min(100, volume))),
            ]
            if self.loop:
                command.extend(["-loop", "0"])
            command.append(str(file_path))
        else:
            raise RuntimeError(
                "ไม่พบโปรแกรมเล่นเสียง — Pi/Linux: sudo apt install -y mpv · "
                "macOS: brew install mpv · Windows: ติดตั้ง ffmpeg"
            )
        return subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    @staticmethod
    def _process_error(proc: subprocess.Popen[str]) -> str:
        try:
            detail = (proc.stderr.read() if proc.stderr else "").strip()
        except Exception:
            detail = ""
        return detail[-1000:] or f"player exited with code {proc.returncode}"

    def play(
        self,
        file_path: Path,
        loop: bool = False,
        queue: bool = False,
    ) -> None:
        """Start or replace playback and update the authoritative state."""
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
        threading.Thread(
            target=self._watch,
            args=(proc,),
            daemon=True,
        ).start()

    def _queue_for(self, file_path: Path, queue: bool) -> list[Path]:
        if not queue or self.loop:
            return [file_path]
        extensions = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
        ordered = sorted(
            path
            for path in self.music_dir.iterdir()
            if path.is_file() and path.suffix.lower() in extensions
        )
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
                    "loop": False,
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
                self.state["music"].update(
                    {
                        "playing": False,
                        "paused": False,
                        "track": None,
                        "loop": False,
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
        threading.Thread(
            target=self._watch,
            args=(self.proc,),
            daemon=True,
        ).start()
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
        threading.Thread(
            target=self._watch,
            args=(next_proc,),
            daemon=True,
        ).start()
        return True

    def _stop_locked(self) -> None:
        self.loop = False
        self.current_path = None
        self.queue_paths = []
        self.queue_index = 0
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self._cleanup_socket()
        with self.state_lock:
            self.state["music"].update(
                {
                    "playing": False,
                    "paused": False,
                    "track": None,
                    "loop": False,
                    "queue_position": 0,
                    "queue_length": 0,
                }
            )

    def stop(self) -> None:
        """Stop playback and clear its queue."""
        with self.lock:
            self._stop_locked()

    def pause_toggle(self) -> bool:
        """Toggle MPV pause and report whether the command was accepted."""
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
        with self.lock:
            if self.backend == "mpv":
                self._send(["set_property", "volume", bounded])
        with self.state_lock:
            self.state["music"]["volume"] = bounded
