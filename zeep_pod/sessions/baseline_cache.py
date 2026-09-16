"""Import-safe lifecycle for the derived Personal Baseline JSON cache."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any


class BaselineCacheLifecycle:
    """Load one normalized JSON object explicitly or on guarded first use."""

    def __init__(
        self,
        path: Path,
        normalize: Callable[[Any], dict[str, Any]],
    ) -> None:
        self.path = path
        self.lock = threading.RLock()
        self._normalize_cache = normalize
        self._data: dict[str, Any] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Load the cache at most once per process and fail soft if invalid."""
        with self.lock:
            if self._initialized:
                return
            loaded: dict[str, Any] = {}
            try:
                with self.path.open("r", encoding="utf-8") as file:
                    loaded = self._normalize_cache(json.load(file))
            except FileNotFoundError:
                pass
            except Exception as exc:
                print(f"[BASELINE] ignoring invalid baselines.json: {exc}")
            self._data = loaded
            self._initialized = True

    @property
    def initialized(self) -> bool:
        """Report whether this process has loaded the cache."""
        with self.lock:
            return self._initialized

    @property
    def data(self) -> dict[str, Any]:
        """Return loaded data while preserving the legacy direct-access API."""
        self.initialize()
        return self._data

    @data.setter
    def data(self, value: dict[str, Any]) -> None:
        """Replace data for compatibility with guarded offline tooling."""
        with self.lock:
            self._data = value
            self._initialized = True
