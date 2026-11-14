"""E2E tests for conversation details in the single header."""

from playwright.sync_api import Page, expect

from tests.e2e._protocol import say
from tests.e2e.pages import ChatView


def test_conversation_details_opens_from_header(page: Page):
    """Conversation metadata stays available without crowding the header."""
    ChatView(page).goto()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    page.get_by_role("button", name="Conversation details", exact=True).click()
    expect(page.get_by_test_id("chat-title")).to_be_visible()


def test_turn_count_appears_after_a_turn(page: Page):
    """Conversation details shows the current turn count."""
    chat = ChatView(page).goto().new_conversation()

    # No turns yet — the count is hidden.
    expect(page.get_by_test_id("chat-turns")).to_have_count(0)

    chat.send(say("hello")).wait_streaming()

    page.get_by_role("button", name="Conversation details", exact=True).click()
    expect(page.get_by_test_id("chat-turns")).to_be_visible()
    expect(page.get_by_test_id("chat-turns")).to_contain_text("1 turn")
