"""Stored browser-profile metadata and API-facing summaries."""

from __future__ import annotations

from pydantic import BaseModel, Field


class BrowserProfileSite(BaseModel):
    """A site represented in a browser profile's saved storage state."""

    domain: str
    cookies: int = 0
    local_storage: bool = False
    indexed_db: bool = False


class BrowserProfile(BaseModel):
    """Metadata for an explicitly saved browser-state snapshot."""

    id: str
    name: str
    icon: str = "bi-globe2"
    created_at: str
    updated_at: str
    sites: list[BrowserProfileSite] = Field(default_factory=list)


__all__ = ["BrowserProfile", "BrowserProfileSite"]
