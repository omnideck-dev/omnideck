"""Common models for agent message streaming and agent configuration."""

import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


__all__ = [
    "Data",
]


class Data(BaseModel):
    """Represents binary or non-text data sent with a user message.

    Attributes:
        base64_encoded: The base64-encoded data payload.
        content_type: The MIME type of the data (e.g., 'image/png').
        filename: Original filename from the browser upload, if available.
    """

    base64_encoded: str
    content_type: str
    filename: str | None = None
