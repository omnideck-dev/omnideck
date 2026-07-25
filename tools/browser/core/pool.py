"""Conversation- and agent-scoped Browser lifecycle management."""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import os
import signal
from pathlib import Path

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

logger = logging.getLogger(__name__)

_root_browser: Browser | None = None
_scoped_browsers: dict[str, Browser] = {}
_pool_lock = asyncio.Lock()


def _kill_driver_tree(pid: int) -> None:
    """Terminate the Playwright driver process group as a last resort."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    except OSError:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, signal.SIGTERM)


def _cleanup_root_browser_at_exit() -> None:
    """Kill a root browser that outlived the asynchronous shutdown path."""
    if _root_browser is None or _root_browser._closed:
        return
    pid = _root_browser._driver_pid
    if pid is None:
        return
    logger.debug("atexit: killing browser driver tree (pid %d)", pid)
    _kill_driver_tree(pid)


async def _get_root_browser() -> Browser:
    """Return the persistent profile browser, launching it once."""
    global _root_browser
    async with _pool_lock:
        if _root_browser is None:
            config = load_config()
            profile_path = Path(config.settings.home_dir) / "browser" / "profiles" / "default"
            downloads_dir = str(Path(config.virtual_computer.home_dir) / "downloads")
            _root_browser = await Browser.start(
                str(profile_path),
                headless=config.tools.browser.headless,
                downloads_path=downloads_dir,
            )
            atexit.register(_cleanup_root_browser_at_exit)
        return _root_browser


async def get_browser() -> Browser:
    """Return the Browser scoped to the current conversation or sub-agent.

    The persistent root browser owns the Chrome process and profile. Each
    conversation or sub-agent gets an isolated ephemeral context seeded from
    that profile's current storage state.
    """
    root = await _get_root_browser()
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

        state = await root._context.storage_state()
        browser = await Browser._start_ephemeral(root, storage_state=state)
        _scoped_browsers[key] = browser
        logger.info("Created ephemeral browser context for key '%s'", key)
        return browser


async def get_browser_by_conversation_id(
    conversation_id: str,
) -> Browser | None:
    """Return the live root-agent Browser for a conversation, if any."""
    async with _pool_lock:
        return _scoped_browsers.get(f"conv:{conversation_id}")


async def release_agent_browser(key: str) -> None:
    """Close and remove an ephemeral Browser by its storage key."""
    async with _pool_lock:
        browser = _scoped_browsers.pop(key, None)
    if browser is None:
        return
    try:
        await browser._close_context()
        logger.info("Released browser context for '%s'", key)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to release browser context for '%s'", key)


async def release_conversation_browser(conversation_id: str) -> None:
    """Release the Browser bound to a root-agent conversation."""
    await release_agent_browser(f"conv:{conversation_id}")


async def close_browser() -> None:
    """Close all scoped contexts and the persistent root Browser."""
    global _root_browser

    async with _pool_lock:
        scoped = list(_scoped_browsers.items())
        _scoped_browsers.clear()
    for key, browser in scoped:
        try:
            await browser._close_context()
        except Exception:  # noqa: BLE001
            logger.warning("Failed to close scoped browser for '%s'", key)

    if _root_browser is None:
        logger.debug("close_browser called but no root browser exists")
        return
    try:
        await _root_browser.close()
    except PlaywrightError as exc:  # pragma: no cover - defensive
        logger.warning("Suppressed browser shutdown error: %s", exc)
    except Exception as exc:  # noqa: BLE001  pragma: no cover
        logger.warning("Suppressed unexpected browser shutdown error: %s", exc)
    finally:
        _root_browser = None
        logger.debug("Root browser cleared")


register_agent_span_exit_hook(release_agent_browser)
register_conversation_exit_hook(release_conversation_browser)


__all__ = [
    "close_browser",
    "get_browser",
    "get_browser_by_conversation_id",
    "release_agent_browser",
]
