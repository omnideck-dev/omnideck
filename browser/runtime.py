"""Profile-aware lifecycle for user and agent Browser sessions."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from browser.core.browser import Browser
from browser.profile_store import (
    DEFAULT_BROWSER_PROFILE_ID,
    EMPTY_BROWSER_PROFILE_ID,
    BrowserProfileStore,
    summarize_browser_sites,
)
from browser.profiles import BrowserProfile, BrowserProfileSite
from browser.session_pool import BrowserSessionPool, BrowserStorageStateLoader
from config import load_config
from sdk.events import get_current_agent_id, get_current_depth
from sdk.turn import get_conversation_id

logger = logging.getLogger(__name__)

_USER_BROWSER_KEY = "user"
_CONVERSATION_BROWSER_PREFIX = "conversation:"


@dataclass(frozen=True, slots=True)
class AgentBrowserBinding:
    """The agent and Browser profile represented by one runtime session."""

    agent_profile_id: str
    browser_profile_id: str | None

    @property
    def browser_access_enabled(self) -> bool:
        return self.browser_profile_id is not None


class BrowserRuntime:
    """Coordinate saved profiles with live Browser sessions."""

    def __init__(
        self,
        profiles: BrowserProfileStore,
        sessions: BrowserSessionPool,
    ) -> None:
        self.profiles = profiles
        self.sessions = sessions
        self._agent_bindings: dict[str, AgentBrowserBinding] = {}
        self._user_browser_profile_id: str | None = None
        self._lock = asyncio.Lock()

    async def prepare_current_agent_browser(
        self,
        *,
        agent_profile_id: str,
        browser_profile_id: str | None,
    ) -> AgentBrowserBinding:
        """Prepare the current agent's Browser, replacing incompatible state."""
        key = self._current_agent_browser_key()
        resolved_profile_id = await self._resolve_profile_id(
            browser_profile_id,
            agent_profile_id=agent_profile_id,
        )
        next_binding = AgentBrowserBinding(
            agent_profile_id=agent_profile_id,
            browser_profile_id=resolved_profile_id,
        )

        async with self._lock:
            current = self._agent_bindings.get(key)
            changed = current != next_binding
            if changed:
                self._agent_bindings[key] = next_binding

        if changed and current is not None:
            await self.sessions.release(key)
        await self.sessions.prepare(key, self._state_loader(resolved_profile_id))
        return next_binding

    async def get_current_agent_browser(self) -> Browser:
        """Return the Browser prepared for the current agent execution."""
        key = self._current_agent_browser_key()
        async with self._lock:
            binding = self._agent_bindings.get(key)
        if binding is None:
            raise RuntimeError("Browser session was not prepared for this agent")
        if not binding.browser_access_enabled:
            raise RuntimeError("Browser access is disabled for this agent")
        return await self.sessions.get_or_create(key)

    async def get_conversation_browser(self, conversation_id: str) -> Browser | None:
        """Return a live root-agent Browser without creating one."""
        return await self.sessions.get(self._conversation_key(conversation_id))

    async def get_conversation_binding(
        self,
        conversation_id: str,
    ) -> AgentBrowserBinding | None:
        """Return the Browser binding for a root-agent conversation."""
        async with self._lock:
            return self._agent_bindings.get(self._conversation_key(conversation_id))

    async def assign_profile_to_live_conversation(
        self,
        conversation_id: str,
        browser_profile_id: str,
    ) -> None:
        """Associate an explicitly assigned snapshot with its unchanged session."""
        await asyncio.to_thread(self.profiles.get, browser_profile_id)
        key = self._conversation_key(conversation_id)
        async with self._lock:
            current = self._agent_bindings.get(key)
            if current is None or not current.browser_access_enabled:
                return
            self._agent_bindings[key] = replace(
                current,
                browser_profile_id=browser_profile_id,
            )

    async def agent_profiles_using_live_profile(self, browser_profile_id: str) -> set[str]:
        """Return agent-profile IDs whose live sessions use a saved profile."""
        async with self._lock:
            matching = [
                (key, binding.agent_profile_id)
                for key, binding in self._agent_bindings.items()
                if binding.browser_profile_id == browser_profile_id
            ]
        live_agent_profile_ids: set[str] = set()
        for key, agent_profile_id in matching:
            if await self.sessions.get(key) is not None:
                live_agent_profile_ids.add(agent_profile_id)
        return live_agent_profile_ids

    async def close_agent(self, runtime_agent_id: str) -> None:
        """Release an ephemeral sub-agent Browser at agent-span exit."""
        async with self._lock:
            self._agent_bindings.pop(runtime_agent_id, None)
        await self.sessions.release(runtime_agent_id)

    async def close_conversation(self, conversation_id: str) -> None:
        """Release a root-agent Browser and its binding."""
        key = self._conversation_key(conversation_id)
        async with self._lock:
            self._agent_bindings.pop(key, None)
        await self.sessions.release(key)

    async def ensure_user_browser(self) -> Browser:
        """Open the user's Browser from Default on first use this process."""
        existing = await self.sessions.get(_USER_BROWSER_KEY)
        if existing is not None:
            return existing
        await asyncio.to_thread(self.profiles.ensure_default)
        state = await asyncio.to_thread(
            self.profiles.load_state,
            DEFAULT_BROWSER_PROFILE_ID,
        )
        browser = await self.sessions.replace(
            _USER_BROWSER_KEY,
            storage_state=state,
            open_initial_tab=True,
        )
        self._user_browser_profile_id = DEFAULT_BROWSER_PROFILE_ID
        return browser

    async def load_user_browser_profile(self, browser_profile_id: str) -> Browser:
        """Replace the user's Browser with a saved profile or Empty."""
        if browser_profile_id == EMPTY_BROWSER_PROFILE_ID:
            state = None
        else:
            state = await asyncio.to_thread(
                self.profiles.load_state,
                browser_profile_id,
            )
        browser = await self.sessions.replace(
            _USER_BROWSER_KEY,
            storage_state=state,
            open_initial_tab=True,
        )
        self._user_browser_profile_id = browser_profile_id
        return browser

    @property
    def user_browser_profile_id(self) -> str | None:
        """The profile loaded into the user's Browser, if it has been opened."""
        return self._user_browser_profile_id

    async def save_user_browser_to_existing(self, browser_profile_id: str) -> BrowserProfile:
        """Overwrite a saved profile with the user's current Browser state."""
        browser = await self.ensure_user_browser()
        profile = await self.save_browser_to_existing(browser, browser_profile_id)
        self._user_browser_profile_id = profile.id
        return profile

    async def save_user_browser_as_new(self, *, name: str, icon: str) -> BrowserProfile:
        """Create a saved profile from the user's current Browser state."""
        browser = await self.ensure_user_browser()
        profile = await self.save_browser_as_new(browser, name=name, icon=icon)
        self._user_browser_profile_id = profile.id
        return profile

    async def save_browser_to_existing(
        self,
        browser: Browser,
        browser_profile_id: str,
    ) -> BrowserProfile:
        """Overwrite a saved profile from any live Browser session."""
        captured = await browser.capture_storage_state()
        return await asyncio.to_thread(
            self.profiles.save_state,
            browser_profile_id,
            captured,
        )

    async def save_browser_as_new(
        self,
        browser: Browser,
        *,
        name: str,
        icon: str,
    ) -> BrowserProfile:
        """Create a saved profile from any live Browser session."""
        captured = await browser.capture_storage_state()
        return await asyncio.to_thread(
            self.profiles.create,
            name=name,
            icon=icon,
            storage_state=captured,
        )

    async def summarize_user_browser(self) -> dict[str, Any]:
        """Return the user's loaded profile and all saved profiles."""
        profiles = await asyncio.to_thread(self.profiles.list)
        return {
            "browser_profile_id": self._user_browser_profile_id,
            "profiles": [profile.model_dump(mode="json") for profile in profiles],
        }

    async def preview_user_browser(self) -> list[BrowserProfileSite]:
        """Summarize the transferable state currently in the user's Browser."""
        browser = await self.ensure_user_browser()
        return summarize_browser_sites(await browser.capture_storage_state())

    async def close(self) -> None:
        """Close every Browser session and forget all runtime bindings."""
        async with self._lock:
            self._agent_bindings.clear()
            self._user_browser_profile_id = None
        await self.sessions.close()

    async def _resolve_profile_id(
        self,
        browser_profile_id: str | None,
        *,
        agent_profile_id: str,
    ) -> str | None:
        if browser_profile_id is None or browser_profile_id == EMPTY_BROWSER_PROFILE_ID:
            return browser_profile_id
        try:
            await asyncio.to_thread(self.profiles.get, browser_profile_id)
        except (KeyError, OSError, ValueError):
            logger.warning(
                "agent profile %r references unavailable browser profile %r; using Empty",
                agent_profile_id,
                browser_profile_id,
            )
            return EMPTY_BROWSER_PROFILE_ID
        return browser_profile_id

    def _state_loader(
        self,
        browser_profile_id: str | None,
    ) -> BrowserStorageStateLoader | None:
        if browser_profile_id is None or browser_profile_id == EMPTY_BROWSER_PROFILE_ID:
            return None

        async def load_storage_state() -> dict[str, Any] | None:
            try:
                return await asyncio.to_thread(
                    self.profiles.load_state,
                    browser_profile_id,
                )
            except (KeyError, OSError, ValueError):
                logger.warning(
                    "browser profile %r became unavailable before session creation; using Empty",
                    browser_profile_id,
                )
                return None

        return load_storage_state

    @staticmethod
    def _conversation_key(conversation_id: str) -> str:
        return f"{_CONVERSATION_BROWSER_PREFIX}{conversation_id}"

    @classmethod
    def _current_agent_browser_key(cls) -> str:
        conversation_id = get_conversation_id()
        if get_current_depth() == 0 and conversation_id:
            return cls._conversation_key(conversation_id)
        runtime_agent_id = get_current_agent_id()
        if runtime_agent_id is None:
            raise RuntimeError("Browser requested outside an agent execution")
        return runtime_agent_id


_runtime: BrowserRuntime | None = None


def get_browser_runtime() -> BrowserRuntime:
    """Return the process-owned Browser runtime."""
    global _runtime
    if _runtime is None:
        profiles_dir = Path(load_config().settings.home_dir) / "browser" / "profiles"
        _runtime = BrowserRuntime(
            BrowserProfileStore(profiles_dir),
            BrowserSessionPool(),
        )
    return _runtime


async def get_browser() -> Browser:
    """Return the Browser prepared for the current agent execution."""
    return await get_browser_runtime().get_current_agent_browser()


async def close_browser() -> None:
    """Close the process-owned Browser runtime."""
    await get_browser_runtime().close()


__all__ = [
    "AgentBrowserBinding",
    "BrowserRuntime",
    "close_browser",
    "get_browser",
    "get_browser_runtime",
]
