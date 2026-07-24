"""E2E for the conversation-scoped Artifacts surface.

Produces a file through the real pipeline (fake provider), then opens the
shared Artifacts hub from Chat and selects the file into its own tab.
"""

import time

from playwright.sync_api import Page, expect

from tests.e2e.artifacts._helpers import VC_HOME, delete_file, produce, purge


def test_chat_opens_scoped_artifacts_and_artifact_tab(page: Page):
    """Chat opens the scoped hub; selecting a file opens a stable surface."""
    nonce = time.time_ns()
    name = f"conversation_{nonce}.md"
    # Produce in a conversation and stay in it so the scoped query is active.
    produce(page, (f"{VC_HOME}/{name}", "# conversation artifact\n\nhello"))
    try:
        page.get_by_test_id("conversation-artifacts-trigger").click()
        hub = page.get_by_test_id("artifacts-hub")
        expect(hub).to_be_visible()
        expect(hub).not_to_have_attribute("data-conversation-id", "")

        card = hub.get_by_test_id("artifact-card").filter(has_text=name)
        expect(card).to_be_visible(timeout=5_000)

        card.click()
        expect(
            page.get_by_test_id(f"surface-tab-artifact:{name}")
        ).to_be_visible(timeout=5_000)
        expect(
            page.locator(
                "[data-surface-kind='artifact-file'][data-active='true']"
            )
        ).to_contain_text(name)
    finally:
        purge(page, name)
        delete_file(name)
