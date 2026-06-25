"""E2E coverage for stopping generation mid-stream.

Uses the fake provider's slow-streaming marker so the reply streams over
several seconds, giving the test a real window to click Stop while tokens
are arriving — then verifies the partial output survives the stop instead
of vanishing.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e._protocol import say, slow
from tests.e2e.pages import ChatView

# Long enough to stream for ~7s at the fake's slow pace. The tail marker
# must never appear in the chat: the stop lands long before the end.
_BODY = ("streaming word salad " * 120).strip()
_TAIL = "ZZZTAIL-NEVER-REACHED"


def test_stop_mid_stream_keeps_partial_text(page: Page):
    chat = ChatView(page).goto().new_conversation()

    chat.send(slow() + say(f"{_BODY} {_TAIL}"))

    # Wait until real streamed text is visible, then stop.
    content = page.get_by_test_id("entry-content").last
    expect(content).to_contain_text("streaming word salad", timeout=10_000)
    chat.stop_button.click()

    chat.wait_streaming()

    # The partial the user watched stream is still there, the tail never
    # arrived, and the composer is back to its idle state.
    expect(content).to_contain_text("streaming word salad")
    expect(content).not_to_contain_text(_TAIL)
    expect(chat.stop_button).not_to_be_visible()
