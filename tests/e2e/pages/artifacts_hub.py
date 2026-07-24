"""POM for the Artifacts Hub — the global grid/table of produced files."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class ArtifactsHub:
    """Global artifacts view, reached from the sidebar 'Artifacts' nav item.

    Cards (grid) and rows (table) are matched by filename substring; tests
    stamp a per-run nonce into filenames so the match is unambiguous even
    though the hub shows every artifact across all conversations.
    """

    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> "ArtifactsHub":
        self.page.goto("/", timeout=15_000)
        self.page.get_by_role("button", name="Artifacts", exact=True).click()
        self.page.get_by_test_id("artifacts-hub").wait_for(state="visible")
        return self

    # ── layout / filter ──

    def show_grid(self) -> "ArtifactsHub":
        self.page.get_by_test_id("layout-grid").click()
        return self

    def show_table(self) -> "ArtifactsHub":
        self.page.get_by_test_id("layout-table").click()
        return self

    def search(self, text: str) -> "ArtifactsHub":
        self.page.get_by_test_id("artifacts-search").fill(text)
        return self

    # ── items ──

    def card(self, filename: str) -> Locator:
        return self.page.get_by_test_id("artifact-card").filter(has_text=filename)

    def row(self, filename: str) -> Locator:
        return self.page.get_by_test_id("artifact-row").filter(has_text=filename)

    def select(self, filename: str) -> "ArtifactsHub":
        self.card(filename).click()
        return self

    @property
    def preview(self) -> Locator:
        """The artifact file surface opened from the selected card."""
        return self.page.locator(
            "[data-surface-kind='artifact-file'][data-active='true']"
        )

    # ── delete ──

    def request_delete(self, filename: str) -> "ArtifactsHub":
        # The card's delete button only fades in on hover; hover first so the
        # click lands on a settled, visible target.
        card = self.card(filename)
        card.hover()
        card.get_by_test_id("artifact-delete").click()
        return self

    @property
    def delete_dialog(self) -> Locator:
        return self.page.get_by_test_id("delete-artifact-dialog")

    def confirm_delete(self, *, delete_file: bool = False) -> "ArtifactsHub":
        if delete_file:
            self.delete_dialog.get_by_test_id("delete-file-checkbox").check()
        self.delete_dialog.get_by_test_id("confirm-delete").click()
        return self

    # ── prune ──

    @property
    def prune_button(self) -> Locator:
        return self.page.get_by_test_id("prune-missing")

    def prune_missing(self) -> "ArtifactsHub":
        self.prune_button.click()
        return self
