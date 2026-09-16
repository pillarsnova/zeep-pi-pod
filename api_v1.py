"""Compatibility facade for the versioned API package.

New code should import route factories from :mod:`api.v1` and response
helpers from :mod:`api.responses`.
"""

from api.responses import API_SCHEMA, API_VERSION, response_envelope
from api.v1 import create_api_v1_router

__all__ = (
    "API_SCHEMA",
    "API_VERSION",
    "create_api_v1_router",
    "response_envelope",
)
