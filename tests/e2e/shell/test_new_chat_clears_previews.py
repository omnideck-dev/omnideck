"""E2E test: starting a new chat clears the previous conversation's previews.

Regression: opening a new conversation used to leave the previous
conversation's preview tabs (browser, files, terminal) visible in the
preview panel. The fix dispatches AGENT_STATE RESET + preview.reset()
on the new-chat path.

Driven by the fake LLM (MOCK_LLM): the agent really writes a file and
sends it, producing a genuine file_output the preview panel can open —
the same code path the app uses, no canned SSE.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._protocol import send_file, write_file
from tests.e2e.pages import ChatView, PreviewPanel, Sidebar

LLM_TIMEOUT = 180_000


@pytest.mark.e2e
def test_new_chat_clears_open_preview_tabs(page: Page):
    chat = ChatView(page).goto().new_conversation()
    # Agent writes a previewable HTML file and sends it to the user.
    # send_file only accepts absolute paths under the home directory
    # (/home/computron), so write there.
    report = "/home/computron/report.html"
    chat.send(
        write_file(report, "<html><body>hello</body></html>")
        + send_file(report)
    ).wait_streaming(timeout=LLM_TIMEOUT)

    # Open the file as a preview tab.
    preview_btn = page.get_by_test_id("file-preview-btn").first
    expect(preview_btn).to_be_visible(timeout=5_000)
    preview_btn.click()

    panel = PreviewPanel(page)
    expect(panel.file_tab("report.html")).to_be_visible(timeout=5_000)

    # Click "New chat" — preview panel should be empty afterward.
    Sidebar(page).new_chat.click()
    page.wait_for_timeout(500)

    expect(panel.file_tabs).to_have_count(0)
    expect(panel.root).to_have_count(0)
