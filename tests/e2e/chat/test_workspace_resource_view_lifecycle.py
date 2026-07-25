"""E2E coverage for conversation-bound Browser and Terminal tabs."""

import time

from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, say
from tests.e2e.pages import ChatView, DesktopLayout, RecentConversations


def _latest_conversation_id(page: Page) -> str:
    sessions = page.request.get("/api/conversations/sessions").json()
    assert sessions
    return sessions[0]["conversation_id"]


def test_root_terminal_opens_beside_chat_without_stealing_chat(page: Page):
    """Root output appears automatically while Chat remains the primary view."""
    marker = f"root-terminal-{time.time_ns()}"
    chat = ChatView(page).goto().new_conversation()
    chat.send(bash(f'echo "{marker}"')).wait_streaming()

    expect(page.get_by_test_id("view-tab-terminal")).to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    expect(
        page.locator("[data-view-id='destination:conversation']")
    ).to_have_attribute("data-tab-group-id", "left")
    expect(
        page.locator("[data-view-resource-id='terminal']")
    ).to_have_attribute("data-tab-group-id", "right")


def test_closed_execution_view_stays_closed_until_a_new_conversation(page: Page):
    """Closing an auto-opened tab dismisses it for the current conversation."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(bash('echo "first-output"')).wait_streaming()
    DesktopLayout(page).choose_tab_action("terminal", "close")
    expect(page.get_by_test_id("view-tab-terminal")).to_have_count(0)

    chat.send(bash('echo "second-output"')).wait_streaming()
    expect(page.get_by_test_id("view-tab-terminal")).to_have_count(0)

    chat.new_conversation()
    chat.send(bash('echo "fresh-conversation"')).wait_streaming()
    expect(page.get_by_test_id("view-tab-terminal")).to_be_visible()


def test_switching_conversations_closes_views_and_history_opens_none(page: Page):
    """Execution tabs close on a switch and do not return on historical reopen."""
    marker = f"historical-terminal-{time.time_ns()}"
    chat = ChatView(page).goto().new_conversation()
    chat.send(bash(f'echo "{marker}"')).wait_streaming()
    conversation_id = _latest_conversation_id(page)
    expect(page.get_by_test_id("view-tab-terminal")).to_be_visible()

    chat.new_conversation().send(say("second conversation")).wait_streaming()
    expect(page.get_by_test_id("view-tab-terminal")).to_have_count(0)

    RecentConversations(page).open_by_id(conversation_id)
    expect(page.get_by_test_id("view-tab-terminal")).to_have_count(0)
    expect(page.get_by_test_id("message-assistant").last).to_be_visible()


def test_refresh_restores_the_current_execution_view(page: Page):
    """A page refresh resumes the current desktop rather than acting as a switch."""
    marker = f"refresh-terminal-{time.time_ns()}"
    chat = ChatView(page).goto().new_conversation()
    chat.send(bash(f'echo "{marker}"')).wait_streaming()
    expect(page.get_by_test_id("view-tab-terminal")).to_be_visible()

    page.reload()

    terminal_tab = page.get_by_test_id("view-tab-terminal")
    expect(terminal_tab).to_be_visible(timeout=10_000)
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible(timeout=10_000)
    terminal_tab.click()
    expect(
        page.locator(
            "[data-view-resource-id='terminal'][data-active='true']"
        )
    ).to_contain_text(marker)
