"""E2E coverage for durable artifact tabs across a new conversation.

Browser and Terminal workspace-resource views are conversation-bound and covered in the
conversation lifecycle suite. An artifact opened by the user is durable desktop
state and remains until the user closes it.
"""

import time

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import container_exec
from tests.e2e._protocol import send_file, write_file
from tests.e2e.pages import ChatView, DesktopLayout, PreviewTabGroup, Sidebar


@pytest.mark.e2e
def test_new_chat_keeps_open_artifact_until_user_closes_it(page: Page):
    chat = ChatView(page).goto().new_conversation()
    name = f"durable_{time.time_ns()}.html"
    report = f"/home/computron/{name}"
    try:
        chat.send(
            write_file(report, "<html><body>hello</body></html>")
            + send_file(report)
        ).wait_streaming()

        preview_btn = page.get_by_test_id("file-preview-btn").first
        expect(preview_btn).to_be_visible(timeout=5_000)
        preview_btn.click()

        panel = PreviewTabGroup(page)
        tab = panel.file_tab(name)
        expect(tab).to_be_visible(timeout=5_000)

        Sidebar(page).new_chat.click()
        expect(tab).to_be_visible()
        expect(
            page.locator("[data-view-type='artifact-file']")
        ).to_have_count(1)

        DesktopLayout(page).choose_tab_action(f"artifact:{name}", "close")
        expect(tab).to_have_count(0)
        expect(page.locator("[data-view-type='artifact-file']")).to_have_count(0)
    finally:
        container_exec(
            "import pathlib\n"
            f"pathlib.Path({report!r}).unlink(missing_ok=True)\n"
        )
