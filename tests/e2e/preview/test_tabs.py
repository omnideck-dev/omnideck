"""E2E tests for preview panel tab lifecycle.

Verifies that preview tabs appear when content arrives, can be switched
between, and close cleanly.

Uses a single conversation to avoid redundant LLM calls.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import bash, send_file, write_file
from tests.e2e.pages import ChatView

LLM_TIMEOUT = 20_000


@pytest.fixture(scope="module")
def preview_page(browser, browser_context_args):
    """Set up a conversation that produces terminal and file tabs.

    Sends a single directive prompt that triggers multiple preview types,
    then clicks Preview on a file output to open a file tab.
    """
    context = browser.new_context(**browser_context_args)
    page = context.new_page()
    chat = ChatView(page).goto().new_conversation()

    # send_file only accepts absolute paths under the home directory
    # (/home/computron), so write there.
    hello = "/home/computron/hello.txt"
    chat.send(
        bash('echo "hello"')
        + write_file(hello, "hello")
        + send_file(hello)
    ).wait_streaming(timeout=LLM_TIMEOUT)

    has_terminal = chat.preview.terminal_tab.is_visible()
    has_file_btn = chat.file_preview_btns.first.is_visible()

    assert has_terminal or has_file_btn, (
        "Agent did not produce any preview content"
    )

    if has_file_btn:
        chat.file_preview_btns.first.click()
        chat.preview.file_tabs.first.wait_for(state="visible", timeout=5_000)

    yield page

    page.close()
    context.close()


# ── Tab appearance ──────────────────────────────────────────────────


def test_preview_panel_visible(preview_page: Page):
    """Preview panel should be mounted when tabs exist."""
    expect(ChatView(preview_page).preview.root).to_be_visible()


def test_split_handle_visible(preview_page: Page):
    """Split handle should be visible when preview panel is open."""
    expect(ChatView(preview_page).preview.split_handle).to_be_visible()


def test_at_least_one_tab_visible(preview_page: Page):
    """At least one preview tab should be visible."""
    assert ChatView(preview_page).preview.tabs.count() >= 1


# ── Tab switching ───────────────────────────────────────────────────


def test_clicking_tab_shows_content(preview_page: Page):
    """Clicking a tab should show content in the preview area."""
    preview = ChatView(preview_page).preview
    preview.select_tab(preview.tabs.first)
    expect(preview.content).to_be_visible()


def test_switch_between_tabs(preview_page: Page):
    """Switching between tabs shows different content."""
    preview = ChatView(preview_page).preview
    assert preview.tabs.count() >= 2, "Expected at least 2 preview tabs"

    preview.select_tab(preview.tabs.nth(1))
    expect(preview.content).to_be_visible()

    preview.select_tab(preview.tabs.nth(0))
    expect(preview.content).to_be_visible()


# ── Tab closing ─────────────────────────────────────────────────────


def test_close_tab(preview_page: Page):
    """Closing a tab removes it from the tab bar."""
    preview = ChatView(preview_page).preview
    initial_count = preview.tabs.count()

    preview.close_first_tab()

    assert preview.tabs.count() == initial_count - 1


def test_close_all_tabs_hides_preview(preview_page: Page):
    """After closing all tabs, the preview panel and split handle vanish."""
    preview = ChatView(preview_page).preview
    preview.close_all_tabs()

    expect(preview.split_handle).not_to_be_visible()
    expect(preview.root).not_to_be_visible()
