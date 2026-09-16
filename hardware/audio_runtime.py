"""Import-safe contracts and adapters for audio runtime discovery."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

AUDIO_BACKEND_PREFERENCE = ("mpv", "afplay", "ffplay")
DEFAULT_ALSA_DEVICE_PATH = Path("/proc/asound/Device")
DEFAULT_MPV_AUDIO_DEVICE = "alsa/plughw:CARD=Device,DEV=0"

ExecutableLookup = Callable[[str], str | None]
EnvironmentLookup = Callable[[str], str | None]
PathProbe = Callable[[Path], bool]


@dataclass(frozen=True)
class AudioRuntimeSelection:
    """Resolved player backend and optional device passed to MPV."""

    backend: str | None
    audio_device: str | None


class AudioRuntimeDiscovery(Protocol):
    """Port used by the player facade to discover its runtime dependencies."""

    def discover(self) -> AudioRuntimeSelection:
        """Return one deterministic runtime selection."""


def select_audio_runtime(
    available_backends: set[str],
    *,
    requested_device: str | None,
    default_alsa_device_present: bool,
) -> AudioRuntimeSelection:
    """Select a backend without reading the process or host environment."""
    backend = next(
        (
            candidate
            for candidate in AUDIO_BACKEND_PREFERENCE
            if candidate in available_backends
        ),
        None,
    )
    audio_device = (requested_device or "").strip() or None
    if backend == "mpv" and not audio_device and default_alsa_device_present:
        audio_device = DEFAULT_MPV_AUDIO_DEVICE
    return AudioRuntimeSelection(
        backend=backend,
        audio_device=audio_device,
    )


class SystemAudioRuntimeAdapter:
    """Read executable, environment and ALSA availability at startup only."""

    def __init__(
        self,
        *,
        executable_lookup: ExecutableLookup | None = None,
        environment_lookup: EnvironmentLookup | None = None,
        path_probe: PathProbe | None = None,
    ) -> None:
        self._executable_lookup = executable_lookup or shutil.which
        self._environment_lookup = environment_lookup or os.getenv
        self._path_probe = path_probe or (lambda path: path.exists())

    def discover(self) -> AudioRuntimeSelection:
        """Probe the current host and delegate policy to the pure selector."""
        available = {
            backend
            for backend in AUDIO_BACKEND_PREFERENCE
            if self._executable_lookup(backend)
        }
        requested_device = self._environment_lookup("MPV_AUDIO_DEVICE")
        default_device_present = bool(
            "mpv" in available
            and not (requested_device or "").strip()
            and self._path_probe(DEFAULT_ALSA_DEVICE_PATH)
        )
        return select_audio_runtime(
            available,
            requested_device=requested_device,
            default_alsa_device_present=default_device_present,
        )
