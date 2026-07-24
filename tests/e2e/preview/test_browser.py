"""E2E test for the agent's browser tool.

Asks the agent to navigate to example.com and asserts the browser
preview tab renders — proving Chrome successfully launched under the
computron user (regression guard for the entrypoint chown bug). The
assistant's reply text is intentionally not checked; this is an infra
test, not a model-quality test.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import call_tool, open_url
from tests.e2e.pages import BrowserControl, ChatView
from tests.e2e.preview._browser_fixture import fixture_url, install_fixture, open_fixture


@pytest.fixture(scope="module", autouse=True)
def _fixture_page():
    install_fixture()


def test_browser_snapshot_appears(page: Page):
    """Browsing opens a companion tab without replacing the root Chat view."""
    chat = ChatView(page).goto().new_conversation()
    # A cold Chromium launch in the container is the slow path here, well
    # beyond the default turn budget.
    chat.send(open_url("https://example.com")).wait_streaming(timeout=30_000)
    expect(chat.preview.browser_tab).to_be_visible(timeout=10_000)
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()
    expect(
        page.locator("[data-surface-resource-id='browser']")
    ).to_have_attribute("data-pane-id", "right")


def test_agent_close_tab_reflected_in_ui(page: Page):
    """A tab the agent closes is pruned from the preview rail (open_tab_ids)."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(open_fixture("idle") + open_fixture("idle")).wait_streaming(timeout=30_000)
    chat.preview.browser_tab.wait_for(state="visible", timeout=10_000)
    chat.preview.select_tab(chat.preview.browser_tab)
    bc = BrowserControl(page).wait_loaded()
    expect(bc.tab(1)).to_be_visible()
    expect(bc.tab(2)).to_be_visible()

    # Agent closes tab 2, then re-navigates tab 1 so a screenshot carrying the
    # reduced open-tab set is emitted (close_tab alone emits no screenshot).
    chat.send(
        call_tool("close_tab", tab="2")
        + call_tool("goto", url=fixture_url("idle") + "&x=1", tab="1")
    ).wait_streaming(timeout=20_000)
    expect(bc.tab(2)).not_to_be_visible()


def test_agent_close_last_tab_clears_content_but_keeps_desktop_tab(page: Page):
    """Remote tab closure clears Browser data, not user-owned window placement."""
    chat = ChatView(page).goto().new_conversation()
    chat.send(open_fixture("idle")).wait_streaming(timeout=30_000)
    chat.preview.browser_tab.wait_for(state="visible", timeout=10_000)
    chat.preview.select_tab(chat.preview.browser_tab)
    BrowserControl(page).wait_loaded()
    expect(page.get_by_test_id("browser-preview")).to_be_visible()

    chat.send(call_tool("close_tab", tab="1")).wait_streaming(timeout=20_000)
    expect(page.get_by_test_id("browser-preview")).not_to_be_visible()
    expect(chat.preview.browser_tab).to_be_visible()

    page.get_by_test_id("close-surface-tab-browser").click()
    expect(chat.preview.browser_tab).to_have_count(0)
