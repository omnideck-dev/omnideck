"""WebSocket side channel for live browser view + interactive takeover.

A single CDP session per selected tab carries both directions: screencast
frames out, and (when the user takes control) Input-domain primitives in.

The screencast follows the user's tab **selection**: a ``select`` message
brings that tab to the foreground and starts streaming it. The stream keeps
delivering frames even after that tab is backgrounded — a newly opened tab
(agent- or page-spawned) is free to take the foreground — so the selected view
stays live without pinning the selected tab in front. Input forwarded during
takeover likewise reaches the selected tab regardless of which tab is in front.

Both directions are decoupled from the socket read loop, because Chromium acks
input and screencast frames on its compositor cadence. Awaiting those acks
inline caps interaction at the display refresh rate and puts a 60Hz pointer
stream permanently behind. Instead the read loop only enqueues: one pump task
drains input in order (collapsing superseded pointer moves), and one writer task
ships the newest frame. Coordinates travel with the frame metadata Chromium
reports, so page scale and top-offset are never guessed from the image size.

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
import math
import struct
import time
from collections import deque
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

from tools.browser.core.browser import Browser
from tools.browser.core.pool import get_browser_by_conversation_id
from tools.browser.core.tab import Tab

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Coroutine

    from aiohttp.web_request import Request
    from playwright.async_api import CDPSession, FileChooser, FilePayload

logger = logging.getLogger(__name__)

# Named keys the CDP Input domain needs virtual-key codes for. Letters and
# digits are derived instead, so this only covers the non-printable set.
_NAMED_VK: dict[str, int] = {
    "Enter": 13, "Backspace": 8, "Tab": 9, "Escape": 27, "Delete": 46,
    "ArrowLeft": 37, "ArrowUp": 38, "ArrowRight": 39, "ArrowDown": 40,
    "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34,
    "Shift": 16, "Control": 17, "Alt": 18, "Meta": 91, "CapsLock": 20,
    "Insert": 45, "ContextMenu": 93, " ": 32,
}
_NAMED_VK.update({("F" + str(n)): 111 + n for n in range(1, 13)})

# Keys that carry text even though they are not printable characters. Without
# this an Enter press moves focus but never inserts a newline in a textarea.
_KEY_TEXT: dict[str, str] = {"Enter": "\r", "Tab": "\t"}

# Punctuation virtual-key codes. Pages that read event.keyCode for shortcuts
# (and Chromium's own find/zoom handling) need these to be right.
_PUNCT_VK: dict[str, int] = {
    ";": 186, ":": 186, "=": 187, "+": 187, ",": 188, "<": 188,
    "-": 189, "_": 189, ".": 190, ">": 190, "/": 191, "?": 191,
    "`": 192, "~": 192, "[": 219, "{": 219, "\\": 220, "|": 220,
    "]": 221, "}": 221, "'": 222, '"': 222,
}

_MOUSE_TYPE: dict[str, str] = {
    "mousedown": "mousePressed",
    "mouseup": "mouseReleased",
    "mousemove": "mouseMoved",
}

# Pointer moves and wheel ticks are positional samples, not discrete actions: a
# superseded one carries no information, so the queue collapses runs of them.
_COALESCING = frozenset({"mousemove", "wheel"})

# Binary frame header: signed tab id, then the four frame-metadata numbers the
# client needs to turn a click on the image back into a page coordinate.
_FRAME_HEADER = struct.Struct(">iffff")

# How often to ask the page what cursor is under the pointer. The screencast
# image carries no cursor, so without this the pointer stays an arrow over links
# and text fields, which is the single most obvious "not a real browser" tell.
_CURSOR_PROBE_INTERVAL = 0.066

# Coalescing window for the tab-list push. Every tracked page fires navigate and
# load events, and each push reads a title per tab, so one navigation in a
# five-tab window would otherwise trigger ten round trips.
_TABS_DEBOUNCE = 0.2

# Returns the streamed tab's current selection text, covering both input/textarea
# fields and ordinary document selection. Used for copy-to-host-clipboard.
_SELECTION_JS = """() => {
  const a = document.activeElement;
  if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA') && a.selectionStart != null) {
    return a.value.substring(a.selectionStart, a.selectionEnd);
  }
  return (window.getSelection ? window.getSelection().toString() : '') || '';
}"""


def _as_float(value: Any, default: float = 0.0) -> float:
    """Coerce one decoded JSON field to a finite float."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    # NaN and the infinities survive float() and would reach CDP, where they are
    # neither a usable coordinate nor a safe thing to render into a script.
    return number if math.isfinite(number) else default


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce one decoded JSON field to an int."""
    try:
        return int(_as_float(value, default))
    except (TypeError, ValueError, OverflowError):
        return default


def _cursor_js(x: float, y: float) -> str:
    """Expression returning the cursor the page would show at *x*, *y*.

    ``cursor: auto`` has to be resolved here rather than passed through. Chromium
    picks the real shape from the element, so a link reports ``auto`` and would
    otherwise mirror as a plain arrow — the exact case the mirroring is for.
    """
    return (
        "(() => {"
        " const e = document.elementFromPoint(" + str(x) + ", " + str(y) + ");"
        " if (!e) return 'default';"
        " const c = getComputedStyle(e).cursor;"
        " if (c && c !== 'auto') return c;"
        " if (e.closest('a[href], button, summary, label, [role=button], [role=link]'))"
        "   return 'pointer';"
        " const t = e.tagName;"
        " if (t === 'INPUT' || t === 'TEXTAREA' || e.isContentEditable) return 'text';"
        " for (const n of e.childNodes)"
        "   if (n.nodeType === 3 && n.textContent.trim()) return 'text';"
        " return 'default';"
        "})()"
    )


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
    repeat: bool = False

    @classmethod
    def from_message(cls, raw: dict[str, Any]) -> InputEvent:
        """Build an InputEvent from one decoded client message.

        Numbers are coerced rather than trusted. The values arrive as decoded
        JSON, so a non-numeric coordinate would otherwise reach CDP as-is and be
        interpolated into the cursor probe's script.
        """
        return cls(
            type=str(raw.get("type", "")),
            x=_as_float(raw.get("x")),
            y=_as_float(raw.get("y")),
            button=str(raw.get("button", "left")),
            buttons=_as_int(raw.get("buttons")),
            click_count=_as_int(raw.get("clickCount"), 1),
            mods=_as_int(raw.get("mods")),
            dx=_as_float(raw.get("dx")),
            dy=_as_float(raw.get("dy")),
            text=str(raw.get("text", "")),
            key=str(raw.get("key", "")),
            code=str(raw.get("code", "")),
            repeat=bool(raw.get("repeat", False)),
        )

    def merged_with(self, newer: InputEvent) -> InputEvent:
        """Fold a newer same-type sample into this one.

        A move is replaced outright: only the latest position matters. Wheel
        deltas accumulate, so collapsing a burst still scrolls the same distance.
        """
        if self.type == "wheel":
            return replace(newer, dx=self.dx + newer.dx, dy=self.dy + newer.dy)
        return newer


@dataclass(frozen=True)
class FrameMetadata:
    """Geometry Chromium reports with a screencast frame.

    The client cannot derive these from the JPEG. Page scale and top offset are
    what make a click land where it looks like it should, on pages where the
    frame's pixel size is not the CSS viewport size.
    """

    device_width: float = 0.0
    device_height: float = 0.0
    page_scale: float = 1.0
    offset_top: float = 0.0

    @classmethod
    def from_params(cls, raw: dict[str, Any]) -> FrameMetadata:
        """Read the metadata block off one screencastFrame event."""
        meta = raw.get("metadata") or {}
        return cls(
            device_width=float(meta.get("deviceWidth", 0.0) or 0.0),
            device_height=float(meta.get("deviceHeight", 0.0) or 0.0),
            page_scale=float(meta.get("pageScaleFactor", 1.0) or 1.0),
            offset_top=float(meta.get("offsetTop", 0.0) or 0.0),
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
    screencast, foreground the new tab, start a new one. The stream keeps running
    if the selected tab is later backgrounded by a newly opened tab, so no
    foreground guard is needed.
    """

    def __init__(self, ws: web.WebSocketResponse, browser: Browser) -> None:
        """Bind the session to one WebSocket and the conversation's browser."""
        self._ws = ws
        self._browser = browser
        self._cdp: CDPSession | None = None
        self._tab: Tab | None = None
        self._engaged = False
        self._pending_chooser: FileChooser | None = None  # awaiting host files
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._selected_unsubscribe: Callable[[], None] | None = None
        self._new_tabs_unsubscribe: Callable[[], None] | None = None
        self._watched_tab_unsubscribers: list[Callable[[], None]] = []

        # Input side: the read loop appends here and the pump drains it, so a
        # slow CDP ack never stalls reading the next message off the socket.
        self._input_q: deque[InputEvent] = deque()
        self._input_ready = asyncio.Event()
        self._pump_task: asyncio.Task[None] | None = None

        # Frame side: the newest un-sent frame, replaced rather than queued.
        # The ack id rides along so it can never be paired with another frame.
        self._frame: tuple[bytes, FrameMetadata, str | None] | None = None
        self._frame_ready = asyncio.Event()
        self._writer_task: asyncio.Task[None] | None = None

        # Cursor mirroring and tab-list coalescing state.
        self._last_cursor = ""
        self._cursor_probe_at = 0.0
        self._tabs_task: asyncio.Task[None] | None = None

        # Capture width, tracked so a resize can restart the stream at the width
        # actually on screen instead of the full window's.
        self._max_width = 0

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        # Keep a strong reference until the task finishes: asyncio holds only a
        # weak one, so a fire-and-forget task can be garbage-collected mid-flight.
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    # ---- selection + screencast --------------------------------------------

    async def select(self, tab_id: int) -> None:
        """Foreground *tab_id* and stream it; report ``tab_gone`` if it's gone."""
        await self._stop_screencast()
        self._unsubscribe_selected_tab()
        try:
            tab = self._browser.get_tab(tab_id)
        except ValueError:
            await self._ws.send_json({"type": "tab_gone", "tab_id": tab_id})
            self._tab = None
            return
        self._tab = tab
        self._subscribe_selected_tab()
        with contextlib.suppress(Exception):
            await tab.activate()
        cdp = await tab.devtools_session()
        cdp.on("Page.screencastFrame", self._on_frame)
        self._cdp = cdp
        self._last_cursor = ""
        await self._start_screencast()
        await self._send_nav()  # initial url/title for the newly selected tab
        self.request_tabs()  # and the current tab list

    async def _start_screencast(self) -> None:
        """Begin streaming the selected tab at the client's display size."""
        cdp = self._cdp
        if cdp is None:
            return
        params: dict[str, Any] = {
            "format": "jpeg",
            "quality": 60,
            "everyNthFrame": 1,
        }
        # Capping capture at the width it is displayed at is the difference
        # between a full-resolution frame and one the client can decode per
        # frame. Only the width is capped: the frame is shown at the view's full
        # width, so that alone fixes the scale. Capping the height as well would
        # shrink the whole frame to fit a short view, which then has to be scaled
        # back up to that same width, costing sharpness for nothing.
        if self._max_width > 0:
            params["maxWidth"] = self._max_width
        with contextlib.suppress(Exception):
            await cdp.send("Page.startScreencast", params)

    async def resize(self, width: int) -> None:
        """Re-capture at *width* when the view's width changes."""
        w = max(0, int(width))
        # Sub-pixel-ish churn during a drag is not worth a stream restart.
        if abs(w - self._max_width) < 16:
            return
        self._max_width = w
        cdp = self._cdp
        if cdp is None:
            return
        with contextlib.suppress(Exception):
            await cdp.send("Page.stopScreencast")
        await self._start_screencast()

    def _on_frame(self, params: dict[str, Any]) -> None:
        """Keep only the newest frame; the writer task ships and acks it.

        Chromium allows one un-acked frame at a time, so acking before the
        socket write (rather than after) is what lets capture run at the page's
        own repaint rate instead of at the client's download rate.
        """
        try:
            data = base64.b64decode(params["data"])
        except Exception:  # noqa: BLE001 - malformed frame, nothing to show
            return
        self._frame = (data, FrameMetadata.from_params(params), params.get("sessionId"))
        self._frame_ready.set()

    async def _frame_writer(self) -> None:
        """Ack and forward the newest frame, dropping any it superseded."""
        while True:
            await self._frame_ready.wait()
            self._frame_ready.clear()
            pending, self._frame = self._frame, None
            cdp = self._cdp
            if pending is None or cdp is None:
                continue
            data, meta, session_id = pending
            tid = self._tab.id if self._tab else None
            header = _FRAME_HEADER.pack(
                tid if tid is not None else -1,
                meta.device_width, meta.device_height, meta.page_scale, meta.offset_top,
            )
            try:
                await self._ws.send_bytes(header + data)
            except Exception:  # noqa: BLE001 - socket closed mid-frame
                logger.debug("Dropped screencast frame", exc_info=True)
                return
            # Ack without waiting for its reply. Capture is gated on Chromium
            # receiving the ack, so blocking on the reply would put a compositor
            # tick between every frame. If the client falls behind, the newest
            # frame replaces the unsent one rather than a queue building up.
            if session_id is not None:
                self._spawn(self._ack_frame(cdp, session_id))

    async def _ack_frame(self, cdp: CDPSession, session_id: str) -> None:
        """Tell Chromium it may capture the next frame."""
        with contextlib.suppress(Exception):
            await cdp.send("Page.screencastFrameAck", {"sessionId": session_id})

    async def _stop_screencast(self) -> None:
        """Stop the current screencast and detach its CDP session, if any."""
        cdp, self._cdp = self._cdp, None
        self._frame = None
        if cdp is not None:
            with contextlib.suppress(Exception):
                await cdp.send("Page.stopScreencast")
            with contextlib.suppress(Exception):
                await cdp.detach()

    # ---- input -------------------------------------------------------------

    def enqueue_input(self, event: InputEvent) -> None:
        """Queue one input primitive for the pump.

        Returns immediately. Order is preserved, but a run of pointer moves or
        wheel ticks collapses into its newest sample so a burst cannot build a
        backlog the human then has to wait out.
        """
        if event.type in _COALESCING and self._input_q and self._input_q[-1].type == event.type:
            self._input_q[-1] = self._input_q[-1].merged_with(event)
        else:
            self._input_q.append(event)
        self._input_ready.set()

    async def _input_pump(self) -> None:
        """Drain queued input onto the page, in order."""
        while True:
            await self._input_ready.wait()
            self._input_ready.clear()
            while self._input_q:
                event = self._input_q.popleft()
                cdp = self._cdp
                if cdp is None:
                    continue
                try:
                    await _dispatch_input(cdp, event)
                except Exception:  # noqa: BLE001 - a bad primitive must not kill the pump
                    logger.debug("Dropped input primitive", exc_info=True)
                    continue
                if event.type == "mousemove":
                    await self._maybe_probe_cursor(event.x, event.y)

    async def _maybe_probe_cursor(self, x: float, y: float) -> None:
        """Mirror the page's cursor for this position, at most ~15x a second."""
        now = time.monotonic()
        if now - self._cursor_probe_at < _CURSOR_PROBE_INTERVAL:
            return
        self._cursor_probe_at = now
        cdp = self._cdp
        if cdp is None:
            return
        try:
            res = await cdp.send("Runtime.evaluate", {
                "expression": _cursor_js(x, y),
                "returnByValue": True,
            })
        except Exception:  # noqa: BLE001 - cursor mirroring is cosmetic
            return
        cursor = (res.get("result") or {}).get("value") or ""
        if cursor and cursor != self._last_cursor:
            self._last_cursor = cursor
            with contextlib.suppress(Exception):
                await self._ws.send_json({"type": "cursor", "cursor": cursor})

    # ---- nav + tab list ----------------------------------------------------

    def _on_navigated(self) -> None:
        """Push fresh url/title when the selected tab's main frame navigates.

        Covers history nav, link clicks, and same-document (SPA) navigations —
        and works whether the agent or a human drives, since the agent's
        screenshot events (which otherwise carry url/title) don't fire during
        takeover.
        """
        if self._tab is not None:
            self._spawn(self._send_nav())
            # A navigation resets page scale, so the next frame's metadata is
            # the authority again; drop the stale cursor so it re-probes.
            self._last_cursor = ""

    async def _send_nav(self) -> None:
        """Push the streamed tab's current url/title to the client."""
        tab = self._tab
        if tab is None:
            return
        title = await tab.title()
        with contextlib.suppress(Exception):
            await self._ws.send_json(
                {
                    "type": "nav",
                    "tab_id": tab.id,
                    "url": tab.url,
                    "title": title,
                }
            )

    def _unsubscribe_selected_tab(self) -> None:
        # Remove the listeners select() attached (nav + filechooser) so
        # the previously-selected tab stops emitting once we switch away or close.
        unsubscribe, self._selected_unsubscribe = self._selected_unsubscribe, None
        if unsubscribe is not None:
            with contextlib.suppress(Exception):
                unsubscribe()

    def _subscribe_selected_tab(self) -> None:
        """Attach the listeners needed only for the currently streamed tab."""
        tab = self._tab
        if tab is None:
            return
        self._selected_unsubscribe = tab.subscribe(
            on_navigated=self._on_navigated,
            on_file_chooser=self._on_filechooser if self._engaged else None,
        )

    def set_engaged(self, on: bool) -> None:
        """Track control state and arm the file-dialog interceptor.

        The interceptor is attached only while engaged, so the agent's own
        file-input clicks aren't intercepted.
        """
        self._engaged = on
        if self._tab is None:
            return
        # Re-subscribe so file chooser interception follows engagement without
        # exposing Playwright's event emitter outside Tab.
        self._unsubscribe_selected_tab()
        self._subscribe_selected_tab()
        if not on:
            self._pending_chooser = None

    def _on_filechooser(self, chooser: FileChooser) -> None:
        """When the page opens a file dialog during takeover, ask the host to pick.

        Only acts while engaged — otherwise the dialog isn't a human action and we
        leave it to the agent's own (set_input_files) upload path.
        """
        if not self._engaged:
            return
        self._pending_chooser = chooser
        self._spawn(
            self._ws.send_json(
                {
                    "type": "filechooser",
                    "multiple": _is_multiple(chooser),
                }
            )
        )

    async def provide_files(self, files: list[HostFile]) -> None:
        """Fulfil a pending file dialog with files picked on the host."""
        chooser, self._pending_chooser = self._pending_chooser, None
        if chooser is None:
            return
        payloads: list[FilePayload] = [
            {
                "name": file.name,
                "mimeType": file.mime,
                "buffer": base64.b64decode(file.data),
            }
            for file in files
        ]
        with contextlib.suppress(Exception):
            await chooser.set_files(payloads)

    def on_new_tab(self, tab: Tab) -> None:
        """Handle a newly opened tab: watch it and refresh the client's tab list.

        No foreground guard is needed. The live screencast and input are pinned
        to the selected page and keep working no matter which tab the window
        shows, so an agent-opened tab coming to the front can't steal the view.
        Forcing the selected tab back to the front only stole the new tab's
        foreground before its first screenshot, stalling the agent on a capture
        timeout.
        """
        self._watch_tab(tab)
        self.request_tabs()

    def _watch_tab(self, tab: Tab) -> None:
        """Refresh the client's tab list when *tab* navigates or closes.

        A tab's url/title in the rail would otherwise freeze at open time (when
        a fresh tab is still ``about:blank``): the nav push only tracks the
        streamed tab, and there's no context-level navigate/close event, so each
        tracked page needs its own listeners.
        """
        self._watched_tab_unsubscribers.append(
            tab.subscribe(
                on_navigated=self.request_tabs,
                on_loaded=self.request_tabs,
                on_closed=self.request_tabs,
            )
        )

    def request_tabs(self) -> None:
        """Schedule one tab-list push, collapsing any already pending."""
        if self._tabs_task is not None and not self._tabs_task.done():
            return
        self._tabs_task = asyncio.create_task(self._send_tabs_soon())

    async def _send_tabs_soon(self) -> None:
        await asyncio.sleep(_TABS_DEBOUNCE)
        await self._send_tabs()

    async def _send_tabs(self) -> None:
        """Push the live open-tab list (ids + url + title) to the client.

        This is the takeover-time source of truth for the thumbnail rail, since
        the agent's screenshot events (which otherwise carry the tab list) don't
        fire while the agent is idle.
        """
        tabs = []
        for tab in self._browser.tabs():
            try:
                title = await tab.title()
            except Exception:  # noqa: BLE001 - best-effort
                title = ""
            tabs.append(
                {
                    "id": tab.id,
                    "url": tab.url,
                    "title": title,
                }
            )
        with contextlib.suppress(Exception):
            await self._ws.send_json({"type": "tabs", "tabs": tabs})

    async def new_tab(self) -> None:
        """Open a blank tab. The engaged client auto-selects it on the tab push."""
        with contextlib.suppress(Exception):
            await self._browser.new_tab()

    async def close_tab(self, tab_id: int) -> None:
        """Close the tab with *tab_id*; the close listener pushes the new list."""
        try:
            tab = self._browser.get_tab(tab_id)
        except ValueError:
            return
        with contextlib.suppress(Exception):
            await tab.close()

    async def copy(self) -> None:
        """Read the streamed tab's selection and send it back for the host clipboard."""
        tab = self._tab
        if tab is None:
            return
        try:
            text = await tab.evaluate(_SELECTION_JS)
        except Exception:  # noqa: BLE001 - selection read is best-effort
            text = ""
        if text:
            with contextlib.suppress(Exception):
                await self._ws.send_json({"type": "clipboard", "text": text})

    async def navigate(self, direction: str) -> None:
        """History navigation / reload on the streamed tab."""
        tab = self._tab
        if tab is None:
            return
        with contextlib.suppress(Exception):
            if direction == "back":
                await self._browser.navigate_back(tab)
            elif direction == "forward":
                await tab.go_forward()
            elif direction == "reload":
                await tab.reload()

    async def goto(self, url: str) -> None:
        """Navigate the streamed tab to *url* (address-bar entry)."""
        tab = self._tab
        if tab is None or not url:
            return
        if "://" not in url:
            url = "https://" + url
        with contextlib.suppress(Exception):
            await self._browser.navigate(url, tab=tab)

    async def __aenter__(self) -> _ControlSession:
        """Start tracking the browser: new-tab guard + watch existing tabs."""
        self._new_tabs_unsubscribe = self._browser.subscribe_to_new_tabs(
            self.on_new_tab,
        )
        for existing in self._browser.tabs():
            self._watch_tab(existing)
        self._pump_task = asyncio.create_task(self._input_pump())
        self._writer_task = asyncio.create_task(self._frame_writer())
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Tear the session down: drop all listeners and stop the screencast."""
        with contextlib.suppress(Exception):
            if self._new_tabs_unsubscribe is not None:
                self._new_tabs_unsubscribe()
                self._new_tabs_unsubscribe = None
            for unsubscribe in self._watched_tab_unsubscribers:
                unsubscribe()
            self._watched_tab_unsubscribers.clear()
        for task in (self._pump_task, self._writer_task, self._tabs_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._unsubscribe_selected_tab()
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


async def browser_control_handler(request: Request) -> web.StreamResponse:
    """Bridge a control WebSocket to the conversation's root browser."""
    if not _same_origin(request):
        return web.Response(status=403, text="Forbidden origin")

    # Screencast frames are JPEG, so permessage-deflate spends a compress pass
    # (and, above 1KiB, a thread hop) per frame to save nothing.
    ws = web.WebSocketResponse(compress=False)
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
                elif t == "resize":
                    await session.resize(event.get("width", 0))
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
                    # Input (including paste) goes through the pump so it stays
                    # ordered against keystrokes without blocking this loop.
                    session.enqueue_input(InputEvent.from_message(event))
    except Exception:  # noqa: BLE001 - never crash the server on a bad client
        logger.warning("Browser control session error", exc_info=True)
    return ws


def _virtual_key(key: str) -> int:
    """Virtual-key code for *key*, or 0 when it has none.

    Pages read ``event.keyCode`` for shortcuts, and Chromium itself needs the
    code to turn Ctrl+A into select-all rather than a plain keypress.
    """
    if len(key) == 1:
        if key.isalpha():
            return ord(key.upper())
        if key.isdigit():
            return ord(key)
        if key in _PUNCT_VK:
            return _PUNCT_VK[key]
    return _NAMED_VK.get(key, 0)


def _key_payload(event: InputEvent, *, down: bool) -> dict[str, Any]:
    """Build one Input.dispatchKeyEvent payload.

    A printable key carries its own ``text``, so the keystroke both fires the
    page's handlers and inserts the character. Sending the character separately
    costs a second round trip and lets the two arrive out of order.
    """
    vk = _virtual_key(event.key)
    payload: dict[str, Any] = {
        "type": "keyDown" if down else "keyUp",
        "key": event.key,
        "code": event.code,
        "windowsVirtualKeyCode": vk,
        "nativeVirtualKeyCode": vk,
        "modifiers": event.mods,
        "autoRepeat": event.repeat,
    }
    if not down:
        return payload
    text = _KEY_TEXT.get(event.key, event.key if len(event.key) == 1 else "")
    # A modifier other than Shift turns the keystroke into a command, and
    # Chromium expects no text on those (Ctrl+C must not type a "c").
    if text and not (event.mods & ~8):
        payload["text"] = text
        payload["unmodifiedText"] = text.lower() if event.mods & 8 else text
    elif text:
        payload["type"] = "rawKeyDown"
    return payload


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
    elif t in ("text", "paste"):
        if event.text:
            await cdp.send("Input.insertText", {"text": event.text})
    elif t in ("keydown", "keyup"):
        await cdp.send("Input.dispatchKeyEvent", _key_payload(event, down=t == "keydown"))


def register_browser_control_routes(app: web.Application) -> None:
    """Register the browser control WebSocket route."""
    app.router.add_route("GET", "/api/browser/control", browser_control_handler)


__all__ = ["register_browser_control_routes"]
