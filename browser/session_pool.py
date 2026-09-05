"""Process-owned Browser session pool.

The pool owns Chromium resources and nothing about saved profiles, agents, or
permissions. Callers identify sessions with opaque keys and may register a
lazy Playwright storage-state initializer before the first use of a key.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from typing import Any

from playwright.async_api import Error as PlaywrightError

from browser.core.browser import Browser
from browser.core.host import BrowserHost
from config import load_config

logger = logging.getLogger(__name__)

BrowserStorageState = dict[str, Any]
BrowserStorageStateLoader = Callable[[], Awaitable[BrowserStorageState | None]]


class BrowserSessionPool:
    """Own live Browser sessions and their lazy initial state."""

    def __init__(self) -> None:
        self._host: BrowserHost | None = None
        self._sessions: dict[str, Browser] = {}
        self._initializers: dict[str, BrowserStorageStateLoader] = {}
        self._lock = asyncio.Lock()
        self._atexit_registered = False

    async def prepare(
        self,
        key: str,
        state_loader: BrowserStorageStateLoader | None,
    ) -> None:
        """Set the state used if ``key`` needs a new Browser session.

        Preparing an already-live session never replaces or reseeds it. The
        profile-aware runtime explicitly releases incompatible sessions first.
        """
        async with self._lock:
            if key in self._sessions:
                return
            if state_loader is None:
                self._initializers.pop(key, None)
            else:
                self._initializers[key] = state_loader

    async def get_or_create(self, key: str) -> Browser:
        """Return the session for ``key``, creating it from prepared state."""
        host = await self._get_host()
        async with self._lock:
            existing = self._sessions.get(key)
            if existing is not None:
                return existing

            loader = self._initializers.pop(key, None)
            storage_state = await loader() if loader is not None else None
            browser = await host.create_session(storage_state=storage_state)
            self._sessions[key] = browser
            logger.info("Created isolated browser context for key '%s'", key)
            return browser

    async def get(self, key: str) -> Browser | None:
        """Return a live session without creating it."""
        async with self._lock:
            return self._sessions.get(key)

    async def replace(
        self,
        key: str,
        *,
        storage_state: BrowserStorageState | None,
        open_initial_tab: bool = False,
    ) -> Browser:
        """Replace ``key`` with a newly created Browser session."""
        host = await self._get_host()
        replacement = await host.create_session(storage_state=storage_state)
        if open_initial_tab:
            await replacement.new_tab()

        async with self._lock:
            previous = self._sessions.get(key)
            self._sessions[key] = replacement
            self._initializers.pop(key, None)
        if previous is not None:
            await previous.close_session()
        return replacement

    async def release(self, key: str) -> None:
        """Close a session and discard any unused initializer for ``key``."""
        async with self._lock:
            browser = self._sessions.pop(key, None)
            self._initializers.pop(key, None)
        if browser is None:
            return
        try:
            await browser.close_session()
            logger.info("Released browser context for '%s'", key)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to release browser context for '%s'", key)

    async def close(self) -> None:
        """Close every Browser session and the shared Chromium process."""
        async with self._lock:
            sessions = list(self._sessions.items())
            self._sessions.clear()
            self._initializers.clear()
        for key, browser in sessions:
            try:
                await browser.close_session()
            except Exception:  # noqa: BLE001
                logger.warning("Failed to close scoped browser for '%s'", key)

        if self._host is None:
            logger.debug("BrowserSessionPool.close called without a browser host")
            return
        try:
            await self._host.close()
        except PlaywrightError as exc:  # pragma: no cover - defensive
            logger.warning("Suppressed browser shutdown error: %s", exc)
        except Exception as exc:  # noqa: BLE001  pragma: no cover
            logger.warning("Suppressed unexpected browser shutdown error: %s", exc)
        finally:
            self._host = None
            logger.debug("Browser host cleared")

    async def _get_host(self) -> BrowserHost:
        async with self._lock:
            if self._host is None:
                config = load_config()
                downloads_dir = f"{config.virtual_computer.home_dir}/downloads"
                self._host = await BrowserHost.start(
                    headless=config.tools.browser.headless,
                    downloads_path=downloads_dir,
                )
                if not self._atexit_registered:
                    atexit.register(self._cleanup_at_exit)
                    self._atexit_registered = True
            return self._host

    def _cleanup_at_exit(self) -> None:
        """Terminate a driver that outlived asynchronous application cleanup."""
        if self._host is None or self._host.closed:
            return
        pid = self._host.driver_pid
        if pid is None:
            return
        logger.debug("atexit: killing browser driver tree (pid %d)", pid)
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        except OSError:
            with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                os.kill(pid, signal.SIGTERM)


__all__ = [
    "BrowserSessionPool",
    "BrowserStorageState",
    "BrowserStorageStateLoader",
]
