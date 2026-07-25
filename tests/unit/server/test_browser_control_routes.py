"""Unit tests for the browser control-channel pure logic.

The WebSocket round-trip is covered end-to-end by the e2e suite; here we pin the
translation/parsing/guard functions in isolation: the Origin check (CSWSH
defense), the input-primitive -> CDP translation, and the message dataclasses.
"""

from types import SimpleNamespace

import pytest

from server._browser_control_routes import (
    _FRAME_HEADER,
    FrameMetadata,
    HostFile,
    InputEvent,
    _ControlSession,
    _dispatch_input,
    _is_multiple,
    _same_origin,
    _virtual_key,
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
async def test_dispatch_named_key_maps_virtual_key_code():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="keydown", key="Enter", code="Enter"))
    method, params = cdp.calls[0]
    assert method == "Input.dispatchKeyEvent"
    assert params["type"] == "keyDown"
    assert params["windowsVirtualKeyCode"] == 13
    # Enter carries text, or it moves focus without inserting a newline.
    assert params["text"] == "\r"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_printable_keydown_carries_its_own_text():
    # One keystroke, one round trip: the keydown types the character itself
    # rather than needing a second insertText that can arrive out of order.
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="keydown", key="a", code="KeyA"))
    assert len(cdp.calls) == 1
    _, params = cdp.calls[0]
    assert params["text"] == "a"
    assert params["unmodifiedText"] == "a"
    # Pages read event.keyCode for shortcuts, so letters need a real code.
    assert params["windowsVirtualKeyCode"] == ord("A")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_shifted_letter_reports_unshifted_text():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="keydown", key="A", code="KeyA", mods=8))
    _, params = cdp.calls[0]
    assert params["text"] == "A"
    assert params["unmodifiedText"] == "a"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_modifier_chord_sends_raw_keydown_without_text():
    # Ctrl+A must select all, not type an "a", so the keystroke carries no text.
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="keydown", key="a", code="KeyA", mods=2))
    _, params = cdp.calls[0]
    assert params["type"] == "rawKeyDown"
    assert "text" not in params
    assert params["windowsVirtualKeyCode"] == ord("A")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_keyup_carries_key_code_but_no_text():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="keyup", key="a"))
    _, params = cdp.calls[0]
    assert params["type"] == "keyUp"
    assert params["windowsVirtualKeyCode"] == ord("A")
    assert "text" not in params


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dispatch_paste_inserts_text():
    cdp = _FakeCDP()
    await _dispatch_input(cdp, InputEvent(type="paste", text="hi"))
    assert cdp.calls[0] == ("Input.insertText", {"text": "hi"})


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
def test_input_event_coerces_numbers_from_the_wire():
    # The values arrive as decoded JSON, so a coordinate could be any type. It
    # must not reach CDP, or the cursor probe's script, as-is.
    ev = InputEvent.from_message({
        "type": "mousemove", "x": "12.5", "y": None,
        "buttons": "3", "clickCount": 2.9, "mods": None,
    })
    assert ev.x == 12.5
    assert ev.y == 0.0
    assert ev.buttons == 3
    assert ev.click_count == 2
    assert ev.mods == 0


@pytest.mark.unit
def test_input_event_rejects_a_coordinate_that_is_not_a_number():
    ev = InputEvent.from_message({"type": "mousemove", "x": "1); alert(1); (", "y": "nope"})
    assert (ev.x, ev.y) == (0.0, 0.0)


@pytest.mark.unit
def test_input_event_rejects_non_finite_coordinates():
    # NaN and the infinities survive float() and are neither usable coordinates
    # nor safe to render into a script.
    ev = InputEvent.from_message({"type": "mousemove", "x": "NaN", "y": "Infinity"})
    assert (ev.x, ev.y) == (0.0, 0.0)


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


# ── _virtual_key ────────────────────────────────────────────────────


@pytest.mark.unit
def test_virtual_key_covers_letters_digits_named_and_punctuation():
    assert _virtual_key("a") == _virtual_key("A") == ord("A")
    assert _virtual_key("7") == ord("7")
    assert _virtual_key("Escape") == 27
    assert _virtual_key("F5") == 116
    assert _virtual_key("/") == 191
    assert _virtual_key("Unrecognised") == 0


# ── input queue coalescing ──────────────────────────────────────────


def _session() -> _ControlSession:
    """A session with no real socket: the queue logic touches neither."""
    return _ControlSession(SimpleNamespace(), SimpleNamespace())


@pytest.mark.unit
def test_enqueue_collapses_a_run_of_pointer_moves():
    # Only the newest position carries information, so a hover burst must not
    # build a backlog the human then waits out.
    session = _session()
    for x in (1, 2, 3):
        session.enqueue_input(InputEvent(type="mousemove", x=x, y=0))
    assert len(session._input_q) == 1
    assert session._input_q[0].x == 3


@pytest.mark.unit
def test_enqueue_sums_wheel_deltas_when_collapsing():
    # Collapsing must still scroll the same distance.
    session = _session()
    session.enqueue_input(InputEvent(type="wheel", dx=1, dy=10))
    session.enqueue_input(InputEvent(type="wheel", dx=2, dy=20))
    assert len(session._input_q) == 1
    assert (session._input_q[0].dx, session._input_q[0].dy) == (3, 30)


@pytest.mark.unit
def test_enqueue_keeps_discrete_events_and_their_order():
    # A press must stay behind the move that positioned it, and two presses are
    # two separate actions however fast they arrive.
    session = _session()
    session.enqueue_input(InputEvent(type="mousemove", x=5))
    session.enqueue_input(InputEvent(type="mousedown", x=5))
    session.enqueue_input(InputEvent(type="mouseup", x=5))
    session.enqueue_input(InputEvent(type="mousedown", x=5))
    assert [e.type for e in session._input_q] == [
        "mousemove", "mousedown", "mouseup", "mousedown",
    ]


@pytest.mark.unit
def test_enqueue_does_not_merge_moves_across_a_press():
    session = _session()
    session.enqueue_input(InputEvent(type="mousemove", x=1))
    session.enqueue_input(InputEvent(type="mousedown", x=1))
    session.enqueue_input(InputEvent(type="mousemove", x=9))
    assert [e.type for e in session._input_q] == ["mousemove", "mousedown", "mousemove"]
    assert session._input_q[0].x == 1
    assert session._input_q[2].x == 9


# ── frame metadata + wire header ────────────────────────────────────


@pytest.mark.unit
def test_frame_metadata_reads_geometry_from_params():
    meta = FrameMetadata.from_params({"metadata": {
        "deviceWidth": 1440, "deviceHeight": 900,
        "pageScaleFactor": 2, "offsetTop": 56,
    }})
    assert (meta.device_width, meta.device_height) == (1440.0, 900.0)
    assert (meta.page_scale, meta.offset_top) == (2.0, 56.0)


@pytest.mark.unit
def test_frame_metadata_defaults_page_scale_to_one():
    # A missing or zero scale must not divide client coordinates by nothing.
    assert FrameMetadata.from_params({}).page_scale == 1.0
    assert FrameMetadata.from_params({"metadata": {"pageScaleFactor": 0}}).page_scale == 1.0


@pytest.mark.unit
def test_frame_header_round_trips_tab_id_and_geometry():
    packed = _FRAME_HEADER.pack(7, 1440.0, 900.0, 1.0, 0.0)
    assert len(packed) == 20
    assert _FRAME_HEADER.unpack(packed) == (7, 1440.0, 900.0, 1.0, 0.0)


@pytest.mark.unit
def test_frame_header_carries_negative_tab_id_for_an_unknown_tab():
    tab_id, *_ = _FRAME_HEADER.unpack(_FRAME_HEADER.pack(-1, 0.0, 0.0, 1.0, 0.0))
    assert tab_id == -1


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
