"""Shared errors for the Pod snapshot workflow."""


class PodDataSyncError(RuntimeError):
    """Raised when a Pod snapshot cannot be obtained or verified."""
