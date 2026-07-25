"""E2E coverage for conversation-bound Browser and Terminal tabs."""

import time

from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, open_url, say
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

    # Seeing the React tree commit does not guarantee its following persistence
    # effect has written localStorage. Wait for the actual restore precondition
    # so this test measures restoration instead of racing the snapshot write.
    page.wait_for_function(
        """() => {
            const raw = localStorage.getItem('omnideck_desktop_window_v1');
            if (!raw) return false;
            try {
                return JSON.parse(raw).layout.views.some(
                    (view) => view.id.endsWith(':root:terminal')
                );
            } catch {
                return false;
            }
        }"""
    )
    page.reload()

    desktop = DesktopLayout(page)
    # `testid` is runtime-only and deliberately absent from the durable View
    # core. Assert the user-facing tab identity and stable resource metadata
    # rather than coupling restoration to that convenience selector.
    terminal_tab = desktop.tab_group("right").locator(
        '[role="tab"][title="Terminal"]'
    )
    expect(terminal_tab).to_be_visible(timeout=10_000)
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible(timeout=10_000)
    terminal_view = page.locator(
        "[data-view-resource-id='terminal'][data-active='true']"
    )
    expect(terminal_view).to_be_visible()
    expect(terminal_view).to_contain_text(marker)


def test_floating_workspace_views_close_with_their_conversation(page: Page):
    """Browser and Terminal keep rendering when floated, then cascade closed."""
    marker = f"floating-terminal-{time.time_ns()}"
    chat = ChatView(page).goto().new_conversation()
    chat.send(
        open_url("https://example.com")
        + bash(f'echo "{marker}"')
    ).wait_streaming(timeout=30_000)

    desktop = DesktopLayout(page)
    browser_tab = page.get_by_test_id("view-tab-browser")
    terminal_tab = page.get_by_test_id("view-tab-terminal")
    expect(browser_tab).to_be_visible(timeout=10_000)
    expect(terminal_tab).to_be_visible()

    # Workspace resources use the same generic placement commands as every
    # other View. Floating each one also proves the host keeps rendering its
    # domain content outside a docked tab group.
    browser_tab.click()
    desktop.float("browser")
    browser_view = page.locator("[data-view-resource-id='browser']")
    expect(browser_view).to_have_attribute("data-floating", "true")
    expect(browser_view.get_by_test_id("browser-frame")).to_be_visible(
        timeout=10_000
    )

    terminal_tab.click()
    desktop.float("terminal")
    terminal_view = page.locator("[data-view-resource-id='terminal']")
    expect(terminal_view).to_have_attribute("data-floating", "true")
    expect(terminal_view).to_contain_text(marker)

    # Closing the Conversation is one domain lifecycle event. It must remove
    # all of its Workspace Views regardless of their current placement.
    desktop.choose_tab_action("destination:conversation", "close")
    expect(browser_view).to_have_count(0)
    expect(terminal_view).to_have_count(0)
