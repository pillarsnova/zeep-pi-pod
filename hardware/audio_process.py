"""Subprocess and MPV IPC adapter for bedside audio playback."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

SocketPathFactory = Callable[[], str]


class AudioProcessAdapter:
    """Translate player intent into local process and Unix-socket operations."""

    def __init__(self, socket_path_factory: SocketPathFactory | None = None) -> None:
        self._socket_path_factory = socket_path_factory or self._default_socket_path

    @staticmethod
    def _default_socket_path() -> str:
        return os.path.join(tempfile.gettempdir(), "pi5_local_mpv.sock")

    def resolve_socket_path(self) -> str:
        """Resolve the host-specific IPC path during explicit initialization."""
        return self._socket_path_factory()

    @staticmethod
    def cleanup_socket(socket_path: str | None) -> None:
        """Remove a stale MPV socket without touching an uninitialized runtime."""
        if not socket_path:
            return
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass

    @staticmethod
    def send(socket_path: str | None, command: list[Any]) -> bool:
        """Send one MPV JSON IPC command."""
        if not socket_path:
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(0.5)
                connection.connect(socket_path)
                payload = json.dumps({"command": command}) + "\n"
                connection.sendall(payload.encode())
            return True
        except Exception:
            return False

    @staticmethod
    def send_commands(
        socket_path: str | None,
        commands: list[list[Any]],
    ) -> bool:
        """Send ordered MPV commands through one short-lived socket."""
        if not socket_path:
            return False
        try:
            payload = "".join(
                json.dumps({"command": command}) + "\n" for command in commands
            ).encode()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(0.5)
                connection.connect(socket_path)
                connection.sendall(payload)
            return True
        except Exception:
            return False

    def send_retry(
        self,
        socket_path: str | None,
        command: list[Any],
        attempts: int = 5,
        delay: float = 0.2,
    ) -> bool:
        """Retry an MPV command while its IPC socket becomes ready."""
        for _ in range(attempts):
            if self.send(socket_path, command):
                return True
            time.sleep(delay)
        return False

    @staticmethod
    def spawn(
        *,
        backend: str | None,
        audio_device: str | None,
        socket_path: str | None,
        file_path: Path,
        volume: int,
        loop: bool,
    ) -> subprocess.Popen[str]:
        """Start the selected backend with the existing ZEEP command contract."""
        if backend == "mpv":
            command = [
                "mpv",
                "--no-config",
                "--no-video",
                "--really-quiet",
                f"--volume={volume}",
                f"--loop-file={'inf' if loop else 'no'}",
                f"--input-ipc-server={socket_path}",
            ]
            if audio_device:
                command.append(f"--audio-device={audio_device}")
            command.append(str(file_path))
        elif backend == "afplay":
            bounded_volume = max(0, min(100, volume)) / 100
            command = ["afplay", "-v", f"{bounded_volume:.2f}", str(file_path)]
        elif backend == "ffplay":
            command = [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(max(0, min(100, volume))),
            ]
            if loop:
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
    def process_error(process: subprocess.Popen[str]) -> str:
        """Return a bounded diagnostic from a completed player process."""
        try:
            detail = (process.stderr.read() if process.stderr else "").strip()
        except Exception:
            detail = ""
        return detail[-1000:] or f"player exited with code {process.returncode}"
