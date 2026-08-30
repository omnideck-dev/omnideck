"""Shared Playwright process host for isolated Browser sessions."""

from __future__ import annotations

import asyncio
import logging
import platform
from pathlib import Path
from typing import TYPE_CHECKING, Any

from playwright.async_api import Browser as PlaywrightBrowser
from playwright.async_api import Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from tools.browser.core.launch import (
    _ANTI_BOT_SCRIPT,
    _OPEN_SHADOW_DOM_SCRIPT,
    _apply_ua_override,
    _chrome_args,
    _chrome_ua_metadata,
    _launch_options,
)

if TYPE_CHECKING:
    from playwright.async_api import Geolocation, ProxySettings

    from tools.browser.core.browser import Browser

logger = logging.getLogger(__name__)


class BrowserHost:
    """Own one Playwright driver and Chromium process, but no browsing state."""

    _CLOSE_TIMEOUT_S = 5.0

    def __init__(
        self,
        *,
        pw: Playwright,
        browser: PlaywrightBrowser,
        locale: str,
        timezone_id: str,
        accept_downloads: bool,
        downloads_dir: str,
        geolocation: Geolocation | None,
        permissions: list[str],
        proxy: ProxySettings | None,
        headers: dict[str, str],
        ua_string: str | None,
        ua_metadata: dict[str, Any] | None,
    ) -> None:
        self._pw = pw
        self._browser = browser
        self._locale = locale
        self._timezone_id = timezone_id
        self._accept_downloads = accept_downloads
        self._downloads_dir = downloads_dir
        self._geolocation = geolocation
        self._permissions = permissions
        self._proxy = proxy
        self._headers = headers
        self._ua_string = ua_string
        self._ua_metadata = ua_metadata
        self._closed = False
        self._driver_pid: int | None = None
        try:
            transport = pw._impl_obj._connection._transport
            process = getattr(transport, "_proc", None)
            if process is not None:
                self._driver_pid = process.pid
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    async def start(
        cls,
        *,
        headless: bool = False,
        locale: str = "en-US",
        timezone_id: str = "America/Chicago",
        proxy: ProxySettings | None = None,
        accept_downloads: bool = True,
        downloads_path: str | None = None,
        geolocation: Geolocation | None = None,
        permissions: list[str] | None = None,
        extra_headers: dict[str, str] | None = None,
        args: list[str] | None = None,
    ) -> BrowserHost:
        """Launch Chromium without creating a state-bearing context."""
        resolved_downloads_path = ""
        if downloads_path:
            path = Path(downloads_path).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
            resolved_downloads_path = str(path)

        launch_kwargs = _launch_options(
            headless=headless,
            chrome_args=_chrome_args(args),
            downloads_path=resolved_downloads_path or None,
        )
        pw = await async_playwright().start()
        try:
            browser = await pw.chromium.launch(**launch_kwargs)
        except Exception:  # noqa: BLE001 - restart the driver after any launch failure
            try:
                await asyncio.wait_for(pw.stop(), timeout=cls._CLOSE_TIMEOUT_S)
            except Exception:  # noqa: BLE001
                pass
            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.launch(**launch_kwargs)
            except Exception:
                await pw.stop()
                raise

        ua_string: str | None = None
        ua_metadata: dict[str, Any] | None = None
        if platform.machine() != "x86_64":
            ua_string, ua_metadata = _chrome_ua_metadata(browser.version)

        return cls(
            pw=pw,
            browser=browser,
            locale=locale,
            timezone_id=timezone_id,
            accept_downloads=accept_downloads,
            downloads_dir=resolved_downloads_path,
            geolocation=geolocation,
            permissions=permissions or [],
            proxy=proxy,
            headers={"Accept-Language": f"{locale},en;q=0.9", **(extra_headers or {})},
            ua_string=ua_string,
            ua_metadata=ua_metadata,
        )

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def driver_pid(self) -> int | None:
        return self._driver_pid

    async def create_session(
        self,
        *,
        storage_state: dict[str, Any] | str | None = None,
    ) -> Browser:
        """Create an isolated, non-persistent Browser context."""
        if self._closed:
            raise RuntimeError("Browser host is closed")
        context_kwargs: dict[str, Any] = {
            "no_viewport": True,
            "locale": self._locale,
            "timezone_id": self._timezone_id,
            "accept_downloads": self._accept_downloads,
            "geolocation": self._geolocation,
            "permissions": self._permissions,
            "java_script_enabled": True,
            "storage_state": storage_state,
        }
        if self._proxy:
            context_kwargs["proxy"] = self._proxy
        if self._ua_string is not None:
            context_kwargs["user_agent"] = self._ua_string

        context = await self._browser.new_context(**context_kwargs)
        await context.set_extra_http_headers(self._headers)
        await context.add_init_script(_ANTI_BOT_SCRIPT)
        await context.add_init_script(_OPEN_SHADOW_DOM_SCRIPT)
        if self._ua_string is not None and self._ua_metadata is not None:
            await _apply_ua_override(context, self._ua_string, self._ua_metadata)

        from tools.browser.core.browser import Browser

        return Browser(
            context=context,
            extra_headers=self._headers,
            downloads_dir=self._downloads_dir,
        )

    async def close(self) -> None:
        """Close Chromium and its Playwright driver, once."""
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.wait_for(self._browser.close(), timeout=self._CLOSE_TIMEOUT_S)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to close Playwright Browser")
        try:
            await asyncio.wait_for(self._pw.stop(), timeout=self._CLOSE_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning("Timed out stopping Playwright driver")
        except PlaywrightError as exc:  # pragma: no cover - defensive
            logger.warning("Suppressed exception while stopping Playwright driver: %s", exc)
        except Exception as exc:  # noqa: BLE001  pragma: no cover - defensive
            logger.warning("Suppressed unexpected exception while stopping Playwright driver: %s", exc)


__all__ = ["BrowserHost"]
