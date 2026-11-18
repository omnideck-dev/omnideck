"""Configured provider selection for the OmniDeck application."""

from ._registry import get_provider, normalize_base_url, reset_provider
from ._role_options import ROLE_OUTPUT_CAPS, RoleRequest, resolve_role_options
from ._vision import vision_generate

__all__ = [
    "ROLE_OUTPUT_CAPS",
    "RoleRequest",
    "get_provider",
    "normalize_base_url",
    "reset_provider",
    "resolve_role_options",
    "vision_generate",
]
