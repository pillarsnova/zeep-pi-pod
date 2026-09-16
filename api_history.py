"""Compatibility facade for Admin history routes moved into ``api``."""

from api.history import create_history_router

__all__ = ("create_history_router",)
