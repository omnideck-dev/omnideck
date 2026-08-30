"""Resolve agent Browser assignments without coupling them to SDK skill state."""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator

from browser_profiles._store import get_browser_profile_store
from tools.browser.core.pool import BrowserStorageStateLoader, browser_storage_state_scope

if TYPE_CHECKING:
    from agents import AgentProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BrowserProfileAssignment:
    """Validated profile provenance plus a state loader used only on context creation."""

    source_profile_id: str | None
    storage_state_loader: BrowserStorageStateLoader | None


async def resolve_browser_profile_assignment(
    profile: AgentProfile,
) -> BrowserProfileAssignment:
    """Resolve one agent's Browser assignment while leaving its saved state lazy."""
    profile_id = profile.browser_profile_id if profile.browser_access else None
    if profile_id is None:
        return BrowserProfileAssignment(source_profile_id=None, storage_state_loader=None)

    store = get_browser_profile_store()
    try:
        await asyncio.to_thread(store.get, profile_id)
    except (KeyError, OSError, ValueError):
        logger.warning(
            "agent profile %r references unavailable browser profile %r; using Empty",
            profile.id,
            profile_id,
        )
        return BrowserProfileAssignment(source_profile_id=None, storage_state_loader=None)

    async def load_storage_state() -> dict[str, Any] | None:
        try:
            return await asyncio.to_thread(store.load_state, profile_id)
        except (KeyError, OSError, ValueError):
            logger.warning(
                "browser profile %r became unavailable before context creation; using Empty",
                profile_id,
            )
            return None

    return BrowserProfileAssignment(
        source_profile_id=profile_id,
        storage_state_loader=load_storage_state,
    )


@contextmanager
def browser_profile_assignment_scope(
    assignment: BrowserProfileAssignment,
) -> Iterator[None]:
    """Activate an assignment's neutral storage seed for the current agent scope."""
    with browser_storage_state_scope(assignment.storage_state_loader):
        yield


__all__ = [
    "BrowserProfileAssignment",
    "browser_profile_assignment_scope",
    "resolve_browser_profile_assignment",
]
