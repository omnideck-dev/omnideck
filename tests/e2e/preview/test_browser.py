"""E2E test for the agent's browser tool.

Asks the agent to navigate to example.com and asserts the browser
preview tab renders — proving Chrome successfully launched under the
computron user (regression guard for the entrypoint chown bug). The
assistant's reply text is intentionally not checked; this is an infra
test, not a model-quality test.
"""

from playwright.sync_api import Page, expect

from tests.e2e._protocol import open_url
from tests.e2e.pages import ChatView


def test_browser_snapshot_appears(page: Page):
    """Browsing produces a browser preview tab — Chrome launched successfully."""
    chat = ChatView(page).goto().new_conversation()
    # A cold Chromium launch in the container is the slow path here, well
    # beyond the default turn budget.
    chat.send(open_url("https://example.com")).wait_streaming(timeout=30_000)
    expect(chat.preview.browser_tab).to_be_visible(timeout=10_000)
