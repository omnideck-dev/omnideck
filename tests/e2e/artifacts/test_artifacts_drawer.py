"""E2E for the in-conversation artifacts drawer.

Produces a file through the real pipeline (fake provider), then opens the
drawer from the chat title bar and selects the file into the preview.
"""

import time

from playwright.sync_api import Page, expect

from tests.e2e.artifacts._helpers import VC_HOME, delete_file, produce, purge
from tests.e2e.pages import PreviewPanel


def test_drawer_lists_and_opens_artifact(page: Page):
    """The title-bar trigger opens the drawer; selecting a file previews it and closes."""
    nonce = time.time_ns()
    name = f"draw_{nonce}.md"
    # Produce in a conversation and stay in it (active) so the drawer opens the
    # file into the current preview without a reload.
    produce(page, (f"{VC_HOME}/{name}", "# drawer file\n\nhello"))
    try:
        page.get_by_test_id("artifacts-drawer-trigger").click()
        drawer = page.get_by_test_id("artifacts-drawer")
        expect(drawer).to_be_visible()

        row = drawer.get_by_test_id("artifact-drawer-row").filter(has_text=name)
        expect(row).to_be_visible(timeout=5_000)

        row.click()
        # Opens in the existing preview panel and closes the drawer.
        expect(PreviewPanel(page).file_tab(name)).to_be_visible(timeout=5_000)
        expect(page.get_by_test_id("artifacts-drawer")).to_have_count(0)
    finally:
        purge(page, name)
        delete_file(name)
