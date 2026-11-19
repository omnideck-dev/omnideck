"""Look up one model's details in a client's model list."""

from __future__ import annotations

import logging

from ._client import ModelClient
from ._types import ModelInfo

logger = logging.getLogger(__name__)


async def find_model(client: ModelClient, model: str) -> ModelInfo | None:
    """Return the client's listing for *model*, or None if it is unavailable."""
    try:
        models = await client.list_models()
    except Exception:
        logger.debug("Could not list models while looking up %s", model, exc_info=True)
        return None
    return next((candidate for candidate in models if candidate.name == model), None)


__all__ = ["find_model"]
