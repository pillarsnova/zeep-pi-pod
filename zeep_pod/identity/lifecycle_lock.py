"""Small synchronization helper for identity lifecycle operations."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from threading import RLock
from typing import Any, TypeVar, cast

_Return = TypeVar("_Return")


def synchronized_by(
    lock: RLock,
) -> Callable[[Callable[..., _Return]], Callable[..., _Return]]:
    """Serialize decorated operations on the supplied re-entrant lock."""

    def decorate(function: Callable[..., _Return]) -> Callable[..., _Return]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> _Return:
            with lock:
                return function(*args, **kwargs)

        wrapped.__serialized_lock__ = lock  # type: ignore[attr-defined]
        return cast(Callable[..., _Return], wrapped)

    return decorate
