"""E2E tests for the chat title bar (replaces the old app header)."""

from playwright.sync_api import Page, expect

from tests.e2e._protocol import say
from tests.e2e.pages import ChatView


def test_title_bar_is_present(page: Page):
    """The chat view shows a title bar with a title."""
    ChatView(page).goto()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    expect(page.get_by_test_id("chat-title")).to_be_visible()


def test_turn_count_appears_after_a_turn(page: Page):
    """Turn count lives in Details > Advanced, leaving the header compact."""
    chat = ChatView(page).goto().new_conversation()

    # No turns yet — the count is hidden.
    expect(page.get_by_test_id("chat-turns")).to_have_count(0)

    chat.send(say("hello")).wait_streaming()

    expect(page.get_by_test_id("chat-turns")).to_have_count(0)
    page.get_by_role("button", name="Details", exact=False).click()
    page.locator("summary").filter(has_text="Advanced").click()
    expect(page.get_by_test_id("chat-turns")).to_be_visible()
    expect(page.get_by_test_id("chat-turns")).to_have_text("1")
