"""Unit tests for the browser control-channel pure logic.

The WebSocket round-trip is covered end-to-end by the e2e suite; here we pin the
translation/parsing/guard functions in isolation: the Origin check (CSWSH
defense), the input-primitive -> CDP translation, and the message dataclasses.
"""

from types import SimpleNamespace

import pytest

from server._browser_control_routes import (
    HostFile,
    InputEvent,
    _dispatch_input,
    _is_multiple,
    _same_origin,
)


class _FakeCDP:
    """Records cdp.send(method, params) calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def send(self, method: str, params: dict) -> None:
        self.calls.append((method, params))


def _req(origin: str | None, host: str = "localhost:8080") -> SimpleNamespace:
    headers = {"Origin": origin} if origin is not None else {}
    return SimpleNamespace(headers=headers, host=host)


# ── _same_origin (CSWSH guard) ──────────────────────────────────────


@pytest.mark.unit
def test_same_origin_missing_is_allowed():
    # A non-browser client sends no Origin; allowed (it can't be CSWSH'd).
    assert _same_origin(_req(None)) is True


@pytest.mark.unit
def test_same_origin_matching_host_is_allowed():
    assert _same_origin(_req("http://localhost:8080")) is True


@pytest.mark.unit
def test_same_origin_mismatched_host_is_rejected():
    assert _same_origin(_req("http://evil.com")) is False


@pytest.mark.unit
def test_same_origin_compares_host_and_port_not_scheme():
    # netloc (host:port) is compared, not scheme — https origin, same host:port.
    assert _same_origin(_req("https://localhost:8080")) is True
    assert _same_origin(_req("http://localhost:9999")) is False


# ── _dispatch_input (primitive -> CDP) ──────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_mousedown():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="mousedown", x=10, y=20, button="left",
                                          buttons=1, click_count=2, mods=2))
    method, params = cdp.calls[0]
    assert method == "Input.dispatchMouseEvent"
    assert params == {"type": "mousePressed", "x": 10, "y": 20, "button": "left",
                      "buttons": 1, "clickCount": 2, "modifiers": 2}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_mousemove_has_zero_clickcount():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="mousemove", x=1, y=2, click_count=3))
    _, params = cdp.calls[0]
    assert params["type"] == "mouseMoved"
    assert params["clickCount"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_wheel():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="wheel", x=5, y=6, dx=10, dy=-20, mods=8))
    method, params = cdp.calls[0]
    assert method == "Input.dispatchMouseEvent"
    assert params == {"type": "mouseWheel", "x": 5, "y": 6,
                      "deltaX": 10, "deltaY": -20, "modifiers": 8}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_text_uses_insert_text():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="text", text="hi"))
    assert cdp.calls[0] == ("Input.insertText", {"text": "hi"})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_keydown_maps_virtual_key_code():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="keydown", key="Enter", code="Enter", mods=2))
    method, params = cdp.calls[0]
    assert method == "Input.dispatchKeyEvent"
    assert params == {"type": "keyDown", "key": "Enter", "code": "Enter",
                      "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13,
                      "modifiers": 2}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_keyup_and_unknown_key_code_zero():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="keyup", key="a"))
    _, params = cdp.calls[0]
    assert params["type"] == "keyUp"
    # 'a' isn't in the virtual-key table (printable chars go via insertText).
    assert params["windowsVirtualKeyCode"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_unknown_type_is_ignored():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="bogus"))
    assert cdp.calls == []


# ── InputEvent / HostFile parsing ───────────────────────────────────


@pytest.mark.unit
def test_input_event_from_message_maps_fields():
    ev = InputEvent.from_message(
        {"type": "mousedown", "x": 3, "y": 4, "button": "right",
         "buttons": 2, "clickCount": 1, "mods": 4, "key": "k", "code": "KeyK"},
    )
    assert ev.type == "mousedown"
    assert (ev.x, ev.y, ev.button, ev.buttons) == (3, 4, "right", 2)
    assert ev.click_count == 1  # clickCount -> click_count
    assert (ev.mods, ev.key, ev.code) == (4, "k", "KeyK")


@pytest.mark.unit
def test_input_event_from_message_defaults():
    ev = InputEvent.from_message({})
    assert ev.type == ""
    assert ev.button == "left"
    assert ev.click_count == 1
    assert (ev.x, ev.y, ev.dx, ev.dy, ev.mods) == (0.0, 0.0, 0, 0, 0)


@pytest.mark.unit
def test_host_file_from_message():
    hf = HostFile.from_message({"name": "a.txt", "mime": "text/plain", "data": "QQ=="})
    assert (hf.name, hf.mime, hf.data) == ("a.txt", "text/plain", "QQ==")


@pytest.mark.unit
def test_host_file_from_message_defaults():
    hf = HostFile.from_message({"data": "QQ=="})
    assert hf.name == "file"
    assert hf.mime == "application/octet-stream"


@pytest.mark.unit
def test_host_file_from_message_none_without_data():
    assert HostFile.from_message({"name": "a.txt"}) is None
    assert HostFile.from_message({"data": ""}) is None


# ── _is_multiple (FileChooser property-vs-method) ───────────────────


@pytest.mark.unit
def test_is_multiple_property():
    assert _is_multiple(SimpleNamespace(is_multiple=True)) is True
    assert _is_multiple(SimpleNamespace(is_multiple=False)) is False


@pytest.mark.unit
def test_is_multiple_method():
    assert _is_multiple(SimpleNamespace(is_multiple=lambda: True)) is True


@pytest.mark.unit
def test_is_multiple_absent_defaults_false():
    assert _is_multiple(SimpleNamespace()) is False
