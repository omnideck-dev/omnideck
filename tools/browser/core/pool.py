"""User- and agent-scoped Browser lifecycle management.

This module owns Chromium contexts only. It accepts prepared Playwright storage
state and deliberately has no knowledge of saved profiles or access policy.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import os
import signal
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar
from typing import Any

from playwright.async_api import Error as PlaywrightError

from config import load_config
from sdk.events import (
    get_current_agent_id,
    get_current_depth,
    register_agent_span_exit_hook,
    register_conversation_exit_hook,
)
from sdk.turn._turn import get_conversation_id
from tools.browser.core.browser import Browser
from tools.browser.core.host import BrowserHost

logger = logging.getLogger(__name__)

_browser_host: BrowserHost | None = None
_user_browser: Browser | None = None
_user_browser_source_profile_id: str | None = None
_scoped_browsers: dict[str, Browser] = {}
_pool_lock = asyncio.Lock()

BrowserStorageStateLoader = Callable[[], Awaitable[dict[str, Any] | None]]
_browser_storage_state_loader: ContextVar[BrowserStorageStateLoader | None] = ContextVar(
    "browser_storage_state_loader",
    default=None,
)


@contextlib.contextmanager
def browser_storage_state_scope(
    loader: BrowserStorageStateLoader | None,
) -> Iterator[None]:
    """Bind a lazy, profile-agnostic storage seed to the current agent scope."""
    token = _browser_storage_state_loader.set(loader)
    try:
        yield
    finally:
        _browser_storage_state_loader.reset(token)


def _kill_driver_tree(pid: int) -> None:
    """Terminate the Playwright driver process group as a last resort."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    except OSError:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGTERM)


def _cleanup_browser_host_at_exit() -> None:
    """Kill a browser host that outlived the asynchronous shutdown path."""
    if _browser_host is None or _browser_host.closed:
        return
    pid = _browser_host.driver_pid
    if pid is None:
        return
    logger.debug("atexit: killing browser driver tree (pid %d)", pid)
    _kill_driver_tree(pid)


async def _get_browser_host() -> BrowserHost:
    """Return the process owner used to create isolated Browser sessions."""
    global _browser_host
    async with _pool_lock:
        if _browser_host is None:
            config = load_config()
            downloads_dir = f"{config.virtual_computer.home_dir}/downloads"
            _browser_host = await BrowserHost.start(
                headless=config.tools.browser.headless,
                downloads_path=downloads_dir,
            )
            atexit.register(_cleanup_browser_host_at_exit)
        return _browser_host


async def get_user_browser(
    *,
    initial_storage_state: dict[str, Any] | None = None,
    source_profile_id: str | None = None,
) -> Browser:
    """Return the user's temporary working Browser session.

    ``initial_storage_state`` is used only when the session is first created.
    The session never writes itself to disk.
    """
    global _user_browser, _user_browser_source_profile_id
    host = await _get_browser_host()
    async with _pool_lock:
        if _user_browser is None:
            _user_browser = await host.create_session(storage_state=initial_storage_state)
            await _user_browser.new_tab()
            _user_browser_source_profile_id = source_profile_id
        return _user_browser


async def replace_user_browser(
    *,
    storage_state: dict[str, Any] | None,
    source_profile_id: str | None,
) -> Browser:
    """Replace the user's working session with a saved or empty state."""
    global _user_browser, _user_browser_source_profile_id
    host = await _get_browser_host()
    async with _pool_lock:
        previous = _user_browser
        _user_browser = await host.create_session(storage_state=storage_state)
        await _user_browser.new_tab()
        _user_browser_source_profile_id = source_profile_id
    if previous is not None:
        await previous.close_session()
    return _user_browser


def get_user_browser_source_profile_id() -> str | None:
    """Return the saved profile loaded into the user's working session."""
    return _user_browser_source_profile_id


def set_user_browser_source_profile_id(profile_id: str | None) -> None:
    """Associate the current working state with an explicitly saved profile."""
    global _user_browser_source_profile_id
    _user_browser_source_profile_id = profile_id


async def get_browser() -> Browser:
    """Return the Browser scoped to the current conversation or sub-agent.

    Each agent gets an isolated context seeded from application-prepared
    browser state. Changes never write back to a saved profile.
    """
    host = await _get_browser_host()
    depth = get_current_depth()
    conversation_id = get_conversation_id()

    if depth == 0 and conversation_id:
        key = f"conv:{conversation_id}"
    else:
        agent_id = get_current_agent_id()
        if agent_id is None:
            raise RuntimeError("get_browser() called outside an agent span")
        key = agent_id

    async with _pool_lock:
        existing = _scoped_browsers.get(key)
        if existing is not None:
            return existing

        loader = _browser_storage_state_loader.get()
        storage_state = await loader() if loader is not None else None
        browser = await host.create_session(storage_state=storage_state)
        _scoped_browsers[key] = browser
        logger.info("Created isolated browser context for key '%s'", key)
        return browser


async def get_browser_by_conversation_id(conversation_id: str) -> Browser | None:
    """Return the live root-agent Browser for a conversation, if any."""
    async with _pool_lock:
        return _scoped_browsers.get(f"conv:{conversation_id}")


async def release_agent_browser(key: str) -> None:
    """Close and remove an isolated Browser by its storage key."""
    async with _pool_lock:
        browser = _scoped_browsers.pop(key, None)
    if browser is None:
        return
    try:
        await browser.close_session()
        logger.info("Released browser context for '%s'", key)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to release browser context for '%s'", key)


async def release_conversation_browser(conversation_id: str) -> None:
    """Release the Browser bound to a root-agent conversation."""
    await release_agent_browser(f"conv:{conversation_id}")


async def close_browser() -> None:
    """Close all Browser contexts and the shared Chromium process."""
    global _browser_host, _user_browser, _user_browser_source_profile_id

    async with _pool_lock:
        scoped = list(_scoped_browsers.items())
        _scoped_browsers.clear()
        user_browser = _user_browser
        _user_browser = None
        _user_browser_source_profile_id = None
    for key, browser in scoped:
        try:
            await browser.close_session()
        except Exception:  # noqa: BLE001
            logger.warning("Failed to close scoped browser for '%s'", key)
    if user_browser is not None:
        await user_browser.close_session()

    if _browser_host is None:
        logger.debug("close_browser called but no browser host exists")
        return
    try:
        await _browser_host.close()
    except PlaywrightError as exc:  # pragma: no cover - defensive
        logger.warning("Suppressed browser shutdown error: %s", exc)
    except Exception as exc:  # noqa: BLE001  pragma: no cover
        logger.warning("Suppressed unexpected browser shutdown error: %s", exc)
    finally:
        _browser_host = None
        logger.debug("Browser host cleared")


register_agent_span_exit_hook(release_agent_browser)
register_conversation_exit_hook(release_conversation_browser)


__all__ = [
    "BrowserStorageStateLoader",
    "browser_storage_state_scope",
    "close_browser",
    "get_browser",
    "get_browser_by_conversation_id",
    "get_user_browser",
    "get_user_browser_source_profile_id",
    "release_agent_browser",
    "replace_user_browser",
    "set_user_browser_source_profile_id",
]
