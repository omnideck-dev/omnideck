"""WebSocket side channel for live browser view + interactive takeover.

A single CDP session per selected tab carries both directions: screencast
frames out, and (when the user takes control) Input-domain primitives in.

The screencast follows the user's tab **selection**: a ``select`` message
brings that tab to the foreground (only a foreground tab composites, so only it
can be screencast) and starts streaming it. A foreground-ownership guard snaps
the selected tab back to front whenever a newly opened tab (agent- or
page-spawned) tries to foreground itself, so new tabs stay in the background and
the user's chosen view never wanders.

Scope is enforced by ``get_browser_by_conversation_id``: the channel can only reach
the depth-0 conversation context. Sub-agent contexts and the persistent profile
template are unreachable, and CDP targets a page rather than the display — there
is no path from here to the OS. The handshake's ``Origin`` is checked because the
app's HTTP CSRF guard (an ``X-Requested-With`` header) cannot apply to a GET
WebSocket upgrade.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from tools.browser.core import Browser, get_browser_by_conversation_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Coroutine

    from aiohttp.web_request import Request
    from playwright.async_api import CDPSession, FileChooser, Frame, Page

logger = logging.getLogger(__name__)

# Non-text keys the CDP Input domain needs virtual-key codes for. Printable
# characters go through Input.insertText instead and need no entry here.
_VK: dict[str, int] = {
    "Enter": 13, "Backspace": 8, "Tab": 9, "Escape": 27, "Delete": 46,
    "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
    "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34,
}

_MOUSE_TYPE: dict[str, str] = {
    "mousedown": "mousePressed",
    "mouseup": "mouseReleased",
    "mousemove": "mouseMoved",
}

# Returns the streamed tab's current selection text, covering both input/textarea
# fields and ordinary document selection. Used for copy-to-host-clipboard.
_SELECTION_JS = """() => {
  const a = document.activeElement;
  if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA') && a.selectionStart != null) {
    return a.value.substring(a.selectionStart, a.selectionEnd);
  }
  return (window.getSelection ? window.getSelection().toString() : '') || '';
}"""


@dataclass(frozen=True)
class InputEvent:
    """One input primitive the frontend forwards during takeover.

    A single shape covers every variant (mouse, wheel, text, key); ``type`` is
    the discriminator and only the fields that variant uses are read. Defaults
    stand in for fields a given variant omits.
    """

    type: str
    x: float = 0.0
    y: float = 0.0
    button: str = "left"
    buttons: int = 0
    click_count: int = 1
    mods: int = 0
    dx: float = 0.0
    dy: float = 0.0
    text: str = ""
    key: str = ""
    code: str = ""

    @classmethod
    def from_message(cls, raw: dict[str, Any]) -> InputEvent:
        """Build an InputEvent from one decoded client message."""
        return cls(
            type=raw.get("type", ""),
            x=raw.get("x", 0.0),
            y=raw.get("y", 0.0),
            button=raw.get("button", "left"),
            buttons=raw.get("buttons", 0),
            click_count=raw.get("clickCount", 1),
            mods=raw.get("mods", 0),
            dx=raw.get("dx", 0),
            dy=raw.get("dy", 0),
            text=raw.get("text", ""),
            key=raw.get("key", ""),
            code=raw.get("code", ""),
        )


@dataclass(frozen=True)
class HostFile:
    """A file the host picked, to satisfy a page's file dialog during takeover."""

    name: str
    mime: str
    data: str  # base64-encoded contents

    @classmethod
    def from_message(cls, raw: dict[str, Any]) -> HostFile | None:
        """Build a HostFile from one client file entry, or None if it has no data."""
        # No data means nothing to upload — caller drops these.
        data = raw.get("data")
        if not data:
            return None
        return cls(
            name=raw.get("name", "file"),
            mime=raw.get("mime") or "application/octet-stream",
            data=data,
        )


class _ControlSession:
    """Owns the single live screencast for one WebSocket connection.

    Exactly one tab is streamed at a time. ``select`` switches it: stop the old
    screencast, foreground the new tab, start a new one. A page-open guard keeps
    the selected tab in front when the agent (or a page) opens another tab.
    """

    def __init__(self, ws: web.WebSocketResponse, browser: Browser) -> None:
        """Bind the session to one WebSocket and the conversation's browser."""
        self._ws = ws
        self._browser = browser
        self._cdp: CDPSession | None = None
        self._page: Page | None = None
        self._engaged = False
        self._pending_chooser: FileChooser | None = None  # awaiting host files
        self._bg_tasks: set[asyncio.Task[None]] = set()

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        # Keep a strong reference until the task finishes: asyncio holds only a
        # weak one, so a fire-and-forget task can be garbage-collected mid-flight.
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def select(self, tab_id: int) -> None:
        """Foreground *tab_id* and stream it; report ``tab_gone`` if it's gone."""
        await self._stop_screencast()
        self._detach_page_listeners()
        try:
            page = self._browser.resolve_tab(tab_id)
        except ValueError:
            await self._ws.send_json({"type": "tab_gone", "tab_id": tab_id})
            self._page = None
            return
        self._page = page
        page.on("framenavigated", self._on_navigated)
        if self._engaged:  # only intercept file dialogs while the human drives
            page.on("filechooser", self._on_filechooser)
        with contextlib.suppress(Exception):
            await page.bring_to_front()
        cdp = await page.context.new_cdp_session(page)
        cdp.on("Page.screencastFrame", lambda p: self._spawn(self._on_frame(p)))
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 60})
        self._cdp = cdp
        await self._send_nav()   # initial url/title for the newly selected tab
        await self._send_tabs()  # and the current tab list

    def _on_navigated(self, frame: Frame) -> None:
        """Push fresh url/title when the selected tab's main frame navigates.

        Covers history nav, link clicks, and same-document (SPA) navigations —
        and works whether the agent or a human drives, since the agent's
        screenshot events (which otherwise carry url/title) don't fire during
        takeover.
        """
        page = self._page
        if page is not None and frame == page.main_frame:
            self._spawn(self._send_nav())

    async def _send_nav(self) -> None:
        """Push the streamed tab's current url/title to the client."""
        page = self._page
        if page is None:
            return
        url = getattr(page, "url", "")
        try:
            title = await page.title()
        except Exception:  # noqa: BLE001 - title read is best-effort
            title = ""
        with contextlib.suppress(Exception):
            await self._ws.send_json({
                "type": "nav",
                "tab_id": self._browser.tab_id_of(page),
                "url": url,
                "title": title,
            })

    def _detach_page_listeners(self) -> None:
        # Remove the per-page listeners select() attached (nav + filechooser) so
        # the previously-selected tab stops emitting once we switch away or close.
        page = self._page
        if page is not None:
            with contextlib.suppress(Exception):
                page.remove_listener("framenavigated", self._on_navigated)
            with contextlib.suppress(Exception):
                page.remove_listener("filechooser", self._on_filechooser)

    def set_engaged(self, on: bool) -> None:
        """Track control state and arm the file-dialog interceptor.

        The interceptor is attached only while engaged, so the agent's own
        file-input clicks aren't intercepted.
        """
        self._engaged = on
        page = self._page
        if page is None:
            return
        # Remove-then-(re)add so repeated engage messages don't stack listeners.
        with contextlib.suppress(Exception):
            page.remove_listener("filechooser", self._on_filechooser)
        if on:
            with contextlib.suppress(Exception):
                page.on("filechooser", self._on_filechooser)
        else:
            self._pending_chooser = None

    def _on_filechooser(self, chooser: FileChooser) -> None:
        """When the page opens a file dialog during takeover, ask the host to pick.

        Only acts while engaged — otherwise the dialog isn't a human action and we
        leave it to the agent's own (set_input_files) upload path.
        """
        if not self._engaged:
            return
        self._pending_chooser = chooser
        self._spawn(self._ws.send_json({
            "type": "filechooser",
            "multiple": _is_multiple(chooser),
        }))

    async def provide_files(self, files: list[HostFile]) -> None:
        """Fulfil a pending file dialog with files picked on the host."""
        chooser, self._pending_chooser = self._pending_chooser, None
        if chooser is None:
            return
        payloads = [
            {"name": f.name, "mimeType": f.mime, "buffer": base64.b64decode(f.data)}
            for f in files
        ]
        with contextlib.suppress(Exception):
            await chooser.set_files(payloads)

    async def _on_frame(self, params: dict[str, Any]) -> None:
        # Every frame must be acked or Chromium stops the screencast.
        cdp = self._cdp
        if cdp is None:
            return
        try:
            tid = self._browser.tab_id_of(self._page) if self._page else None
            # Binary frame: 4-byte signed tab-id header + raw JPEG. Avoids base64's
            # ~33% inflation and the client JSON.parse per frame; the client drops
            # frames whose header doesn't match the selected tab.
            header = (tid if tid is not None else -1).to_bytes(4, "big", signed=True)
            await self._ws.send_bytes(header + base64.b64decode(params["data"]))
            await cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
        except Exception:  # noqa: BLE001 - socket closed mid-frame
            logger.debug("Dropped screencast frame", exc_info=True)

    async def _stop_screencast(self) -> None:
        """Stop the current screencast and detach its CDP session, if any."""
        cdp, self._cdp = self._cdp, None
        if cdp is not None:
            with contextlib.suppress(Exception):
                await cdp.send("Page.stopScreencast")
            with contextlib.suppress(Exception):
                await cdp.detach()

    def on_new_page(self, page: Page) -> None:
        """Handle a newly opened tab: re-assert selection, refresh tabs, watch close.

        Re-asserting the selected tab keeps agent-opened tabs from stealing the
        view. An *engaged* client re-selects the new tab itself (during takeover
        any new tab is human-initiated), which overrides the re-assert.
        """
        sel = self._page
        if sel is not None and not sel.is_closed():
            self._spawn(self._reassert_front(sel))
        self._watch_tab(page)
        self._spawn(self._send_tabs())

    def _watch_tab(self, page: Page) -> None:
        """Refresh the client's tab list when *page* navigates or closes.

        A tab's url/title in the rail would otherwise freeze at open time (when
        a fresh tab is still ``about:blank``): the nav push only tracks the
        streamed tab, and there's no context-level navigate/close event, so each
        tracked page needs its own listeners.
        """
        def _on_nav(frame: Frame) -> None:
            if frame == page.main_frame:
                self._spawn(self._send_tabs())

        # framenavigated commits the url (fast, and covers same-document nav);
        # load lands the final title, which isn't parsed yet at commit.
        page.on("framenavigated", _on_nav)
        page.on("load", lambda _p: self._spawn(self._send_tabs()))
        page.on("close", lambda _p: self._spawn(self._send_tabs()))

    async def _reassert_front(self, page: Page) -> None:
        """Bring *page* back to the foreground (the selection-ownership guard)."""
        with contextlib.suppress(Exception):
            await page.bring_to_front()

    async def _send_tabs(self) -> None:
        """Push the live open-tab list (ids + url + title) to the client.

        This is the takeover-time source of truth for the thumbnail rail, since
        the agent's screenshot events (which otherwise carry the tab list) don't
        fire while the agent is idle.
        """
        tabs = []
        for page in self._browser.open_tabs():
            tid = self._browser.tab_id_of(page)
            if tid is None:
                continue
            try:
                title = await page.title()
            except Exception:  # noqa: BLE001 - best-effort
                title = ""
            tabs.append({"id": tid, "url": getattr(page, "url", ""), "title": title})
        with contextlib.suppress(Exception):
            await self._ws.send_json({"type": "tabs", "tabs": tabs})

    async def new_tab(self) -> None:
        """Open a blank tab. The engaged client auto-selects it on the tab push."""
        with contextlib.suppress(Exception):
            await self._browser.new_page()

    async def close_tab(self, tab_id: int) -> None:
        """Close the tab with *tab_id*; the close listener pushes the new list."""
        try:
            page = self._browser.resolve_tab(tab_id)
        except ValueError:
            return
        with contextlib.suppress(Exception):
            await page.close()

    async def handle_input(self, event: InputEvent) -> None:
        """Replay one input primitive onto the streamed tab, if any."""
        if self._cdp is not None:
            await _dispatch_input(self._cdp, event)

    async def paste(self, text: str) -> None:
        """Insert host-clipboard *text* into the focused field of the streamed tab."""
        if self._cdp is not None and text:
            with contextlib.suppress(Exception):
                await self._cdp.send("Input.insertText", {"text": text})

    async def copy(self) -> None:
        """Read the streamed tab's selection and send it back for the host clipboard."""
        page = self._page
        if page is None:
            return
        try:
            text = await page.evaluate(_SELECTION_JS)
        except Exception:  # noqa: BLE001 - selection read is best-effort
            text = ""
        if text:
            with contextlib.suppress(Exception):
                await self._ws.send_json({"type": "clipboard", "text": text})

    async def navigate(self, direction: str) -> None:
        """History navigation / reload on the streamed tab."""
        page = self._page
        if page is None:
            return
        with contextlib.suppress(Exception):
            if direction == "back":
                await page.go_back()
            elif direction == "forward":
                await page.go_forward()
            elif direction == "reload":
                await page.reload()

    async def goto(self, url: str) -> None:
        """Navigate the streamed tab to *url* (address-bar entry)."""
        page = self._page
        if page is None or not url:
            return
        if "://" not in url:
            url = "https://" + url
        with contextlib.suppress(Exception):
            await page.goto(url)

    async def __aenter__(self) -> _ControlSession:
        """Start tracking the browser: new-tab guard + watch existing tabs."""
        self._browser.add_new_page_listener(self.on_new_page)
        for existing in self._browser.open_tabs():
            self._watch_tab(existing)
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Tear the session down: drop all listeners and stop the screencast."""
        with contextlib.suppress(Exception):
            self._browser.remove_new_page_listener(self.on_new_page)
        self._detach_page_listeners()
        await self._stop_screencast()


def _same_origin(request: Request) -> bool:
    """Whether the WS handshake's Origin matches the server host.

    A missing Origin (non-browser client) is allowed; a present-but-mismatched
    one is rejected — the WebSocket-shaped equivalent of the app's HTTP CSRF
    guard, which can't apply to a GET upgrade.
    """
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc == request.host


def _is_multiple(chooser: FileChooser) -> bool:
    """Read ``FileChooser.is_multiple`` across Playwright versions.

    It is a property in some builds and a method in others.
    """
    val = getattr(chooser, "is_multiple", False)
    return val() if callable(val) else bool(val)


async def browser_control_handler(request: Request) -> web.WebSocketResponse:
    """Bridge a control WebSocket to the conversation's root browser."""
    if not _same_origin(request):
        return web.Response(status=403, text="Forbidden origin")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    conversation_id = request.query.get("conversation_id", "")
    browser = await get_browser_by_conversation_id(conversation_id) if conversation_id else None
    if browser is None:
        await ws.send_json({"type": "error", "reason": "no_active_browser"})
        await ws.close()
        return ws

    try:
        async with _ControlSession(ws, browser) as session:
            async for msg in ws:
                if msg.type is not WSMsgType.TEXT:
                    continue
                event = json.loads(msg.data)
                t = event.get("type")
                if t == "select":
                    await session.select(event["tab_id"])
                elif t == "paste":
                    await session.paste(event.get("text", ""))
                elif t == "copy":
                    await session.copy()
                elif t in ("back", "forward", "reload"):
                    await session.navigate(t)
                elif t == "goto":
                    await session.goto(event.get("url", ""))
                elif t == "new_tab":
                    await session.new_tab()
                elif t == "close_tab":
                    await session.close_tab(event["tab_id"])
                elif t == "engage":
                    session.set_engaged(bool(event.get("on")))
                elif t == "file":
                    files = [hf for raw in event.get("files", []) if (hf := HostFile.from_message(raw))]
                    await session.provide_files(files)
                else:
                    await session.handle_input(InputEvent.from_message(event))
    except Exception:  # noqa: BLE001 - never crash the server on a bad client
        logger.warning("Browser control session error", exc_info=True)
    return ws


async def _dispatch_input(cdp: CDPSession, event: InputEvent) -> None:
    """Replay one frontend input primitive onto the page via CDP Input.

    Coordinates arrive in page CSS pixels (the frontend maps them from the
    displayed frame). Forwards low-level primitives — mousedown/move/up, wheel,
    keydown/up, and committed text — so Chromium reconstructs clicks, drags, and
    selection itself.
    """
    t = event.type
    if t in _MOUSE_TYPE:
        await cdp.send("Input.dispatchMouseEvent", {
            "type": _MOUSE_TYPE[t],
            "x": event.x, "y": event.y,
            "button": event.button,
            "buttons": event.buttons,
            "clickCount": 0 if t == "mousemove" else event.click_count,
            "modifiers": event.mods,
        })
    elif t == "wheel":
        await cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel",
            "x": event.x, "y": event.y,
            "deltaX": event.dx, "deltaY": event.dy,
            "modifiers": event.mods,
        })
    elif t == "text":
        await cdp.send("Input.insertText", {"text": event.text})
    elif t in ("keydown", "keyup"):
        vk = _VK.get(event.key, 0)
        await cdp.send("Input.dispatchKeyEvent", {
            "type": "keyDown" if t == "keydown" else "keyUp",
            "key": event.key,
            "code": event.code,
            "windowsVirtualKeyCode": vk,
            "nativeVirtualKeyCode": vk,
            "modifiers": event.mods,
        })


def register_browser_control_routes(app: web.Application) -> None:
    """Register the browser control WebSocket route."""
    app.router.add_route("GET", "/api/browser/control", browser_control_handler)


__all__ = ["register_browser_control_routes"]
