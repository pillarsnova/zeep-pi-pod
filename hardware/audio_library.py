"""Pure values and filesystem-safe listing helpers for bedside audio."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_AUDIO_MODE = "repeat_one"
DEFAULT_AUDIO_VOLUME_PERCENT = 60
SUPPORTED_AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
)


def default_music_state() -> dict[str, Any]:
    """Return a fresh, stopped player state with safe bedside defaults."""
    return {
        "playing": False,
        "paused": False,
        "track": None,
        "volume": DEFAULT_AUDIO_VOLUME_PERCENT,
        "loop": True,
        "mode": DEFAULT_AUDIO_MODE,
        "queue_position": 0,
        "queue_length": 0,
        "error": None,
    }


def contained_audio_paths(music_dir: Path) -> list[Path]:
    """List playable files whose resolved targets remain under ``music_dir``."""
    if not music_dir.is_dir():
        return []
    root = music_dir.resolve()
    paths: list[Path] = []
    for entry in music_dir.iterdir():
        if (
            not entry.is_file()
            or entry.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS
        ):
            continue
        resolved = entry.resolve()
        if root in resolved.parents:
            paths.append(resolved)
    return sorted(set(paths))
