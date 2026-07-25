"""Chrome launch configuration and browser-context initialization policy."""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)


_MAKE_NATIVE_JS = r"""
const _makeNative = (fn, nativeName) => {
  const toStr = `function ${nativeName}() { [native code] }`;
  const toString = () => toStr;
  Object.defineProperty(toString, 'toString', {
    value: () => 'function toString() { [native code] }',
    configurable: true, writable: false,
  });
  Object.defineProperty(fn, 'toString', {
    value: toString, configurable: true, writable: false,
  });
  return fn;
};
"""

_ANTI_BOT_SCRIPT = (
    "// --- Stealth patches to reduce automation detection ---\n"
    + _MAKE_NATIVE_JS
    + r"""
delete Navigator.prototype.webdriver;
delete navigator.webdriver;
"""
)

_OPEN_SHADOW_DOM_SCRIPT = r"""
(function() {
  const _origAttachShadow = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function(opts) {
    return _origAttachShadow.call(this, { ...opts, mode: 'open' });
  };
})();
"""


def _chrome_ua_metadata(version: str) -> tuple[str, dict]:
    """Build internally consistent Chrome UA and Client Hints metadata."""
    major = version.split(".")[0]
    ua_string = f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{version} Safari/537.36"
    metadata = {
        "brands": [
            {"brand": "Google Chrome", "version": major},
            {"brand": "Chromium", "version": major},
            {"brand": "Not_A Brand", "version": "24"},
        ],
        "fullVersionList": [
            {"brand": "Google Chrome", "version": version},
            {"brand": "Chromium", "version": version},
            {"brand": "Not_A Brand", "version": "24.0.0.0"},
        ],
        "platform": "Linux",
        "platformVersion": "6.5.0",
        "architecture": "x86",
        "model": "",
        "mobile": False,
        "bitness": "64",
        "wow64": False,
    }
    return ua_string, metadata


async def _apply_ua_override(
    context: BrowserContext,
    ua_string: str,
    ua_metadata: dict,
) -> None:
    """Patch every page's UA and Client Hints through DevTools."""

    async def _override(page: Page) -> None:
        try:
            client = await context.new_cdp_session(page)
            await client.send(
                "Network.setUserAgentOverride",
                {"userAgent": ua_string, "userAgentMetadata": ua_metadata},
            )
        except Exception:  # noqa: BLE001 - CDP support is best-effort
            logger.warning("Failed to apply CDP UA override", exc_info=True)

    for page in context.pages:
        await _override(page)
    context.on("page", lambda page: asyncio.create_task(_override(page)))


def _chrome_args(extra_args: list[str] | None = None) -> list[str]:
    """Return the Chromium flags applied to every root browser."""
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-features=AutomationControlled",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--window-size=1920,1080",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--disable-pdf-viewer",
    ]
    if extra_args:
        args.extend(extra_args)
    return args


def _launch_options(
    *,
    headless: bool,
    chrome_args: list[str],
    downloads_path: str | None,
) -> dict[str, Any]:
    """Build Chromium launch options for the persistent root browser."""
    options: dict[str, Any] = {
        "headless": headless,
        "args": chrome_args,
        "ignore_default_args": ["--enable-automation"],
    }
    if platform.machine() == "x86_64":
        options["channel"] = "chrome"
    if downloads_path:
        options["downloads_path"] = downloads_path
    return options


__all__ = [
    "_ANTI_BOT_SCRIPT",
    "_OPEN_SHADOW_DOM_SCRIPT",
    "_apply_ua_override",
    "_chrome_args",
    "_chrome_ua_metadata",
    "_launch_options",
]
