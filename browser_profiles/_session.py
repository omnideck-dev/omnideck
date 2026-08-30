"""Application-level operations for Browser working sessions and snapshots."""

from __future__ import annotations

import asyncio
from typing import Any

from browser_profiles._models import BrowserProfile
from browser_profiles._store import (
    DEFAULT_BROWSER_PROFILE_ID,
    BrowserProfileStore,
    get_browser_profile_store,
)
from tools.browser.core.browser import Browser
from tools.browser.core.pool import (
    get_user_browser,
    get_user_browser_source_profile_id,
    replace_user_browser,
    set_user_browser_source_profile_id,
)


async def ensure_user_browser() -> Browser:
    """Open the user's Browser from Default on its first use this process."""
    store = get_browser_profile_store()
    await asyncio.to_thread(store.ensure_default)
    state = await asyncio.to_thread(store.load_state, DEFAULT_BROWSER_PROFILE_ID)
    return await get_user_browser(
        initial_storage_state=state,
        source_profile_id=DEFAULT_BROWSER_PROFILE_ID,
    )


async def load_user_browser_profile(profile_id: str) -> Browser:
    """Replace the working Browser with an isolated copy of a saved profile."""
    store = get_browser_profile_store()
    state = await asyncio.to_thread(store.load_state, profile_id)
    return await replace_user_browser(storage_state=state, source_profile_id=profile_id)


async def start_user_browser_fresh() -> Browser:
    """Replace the working Browser with an empty session."""
    return await replace_user_browser(storage_state=None, source_profile_id=None)


async def save_user_browser_to_existing(
    profile_id: str,
    *,
    storage_state: dict[str, Any] | None = None,
) -> BrowserProfile:
    """Explicitly overwrite a saved profile with the current Browser state."""
    browser = await ensure_user_browser()
    captured = storage_state if storage_state is not None else await browser.capture_storage_state()
    profile = await asyncio.to_thread(
        get_browser_profile_store().save_state,
        profile_id,
        captured,
    )
    set_user_browser_source_profile_id(profile.id)
    return profile


async def save_user_browser_as_new(
    *,
    name: str,
    icon: str,
    storage_state: dict[str, Any] | None = None,
) -> BrowserProfile:
    """Explicitly create a profile from the current Browser state."""
    browser = await ensure_user_browser()
    captured = storage_state if storage_state is not None else await browser.capture_storage_state()
    profile = await asyncio.to_thread(
        get_browser_profile_store().create,
        name=name,
        icon=icon,
        storage_state=captured,
    )
    set_user_browser_source_profile_id(profile.id)
    return profile


async def save_browser_context_to_existing(
    browser: Browser,
    profile_id: str,
    *,
    storage_state: dict[str, Any] | None = None,
) -> BrowserProfile:
    """Save a takeover context into an existing profile."""
    captured = storage_state if storage_state is not None else await browser.capture_storage_state()
    return await asyncio.to_thread(
        get_browser_profile_store().save_state,
        profile_id,
        captured,
    )


async def save_browser_context_as_new(
    browser: Browser,
    *,
    name: str,
    icon: str,
    storage_state: dict[str, Any] | None = None,
) -> BrowserProfile:
    """Create a saved profile from a takeover context."""
    captured = storage_state if storage_state is not None else await browser.capture_storage_state()
    return await asyncio.to_thread(
        get_browser_profile_store().create,
        name=name,
        icon=icon,
        storage_state=captured,
    )


def browser_session_summary(store: BrowserProfileStore | None = None) -> dict[str, Any]:
    """Return the current working source and available saved profiles."""
    selected_store = store or get_browser_profile_store()
    profiles = selected_store.list()
    return {
        "source_profile_id": get_user_browser_source_profile_id(),
        "profiles": [profile.model_dump(mode="json") for profile in profiles],
    }


__all__ = [
    "browser_session_summary",
    "ensure_user_browser",
    "load_user_browser_profile",
    "save_browser_context_as_new",
    "save_browser_context_to_existing",
    "save_user_browser_as_new",
    "save_user_browser_to_existing",
    "start_user_browser_fresh",
]
