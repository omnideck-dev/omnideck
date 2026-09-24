"""Application-owned browser service shared by agent execution and HTTP controls."""

from aiohttp import web
from browser.runtime import BrowserRuntime

BROWSER_RUNTIME_KEY: web.AppKey[BrowserRuntime] = web.AppKey("browser_runtime", BrowserRuntime)
