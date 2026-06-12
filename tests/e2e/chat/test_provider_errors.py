"""E2E coverage for provider failures surfacing in the chat.

Both paths run the app with the in-process fake provider (``MOCK_LLM=1``)
and use the ``provider_fail`` directive to make the provider itself raise a
ProviderError — once before any output streams, once partway through the
stream. In both cases the turn must end with a visible error in the chat
rather than failing silently.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e._protocol import provider_fail
from tests.e2e.pages import ChatView


def test_provider_error_before_turn_shows_error(page: Page):
    """A provider error before any output streams surfaces as a chat error."""
    chat = ChatView(page).goto().new_conversation()

    chat.send(provider_fail("usage limit reached")).wait_streaming()

    error = page.get_by_test_id("turn-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("usage limit reached")


def test_provider_error_mid_stream_shows_error(page: Page):
    """A provider error partway through the stream still surfaces as an error."""
    chat = ChatView(page).goto().new_conversation()

    chat.send(provider_fail("connection dropped", mid=True)).wait_streaming()

    error = page.get_by_test_id("turn-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text("connection dropped")
