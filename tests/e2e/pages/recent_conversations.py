"""POM for the inline recent-conversations list in the sidebar."""

from __future__ import annotations

from playwright.sync_api import Locator, Page


class RecentConversationItem:
    """A single row in the recent-conversations list.

    Management actions (pin, rename, delete) live behind the row's 3-dot
    menu, which portals its dropdown to <body> — so menu items are looked
    up at the page level, not inside the row.
    """

    def __init__(self, locator: Locator, page: Page):
        self._loc = locator
        self._page = page

    @property
    def title(self) -> str:
        return self._loc.locator("[class*='itemTitle']").text_content() or ""

    def open(self) -> None:
        """Click the row to load that conversation into the chat view."""
        self._loc.click()

    def open_menu(self) -> None:
        """Reveal and click the row's 3-dot menu, opening the dropdown."""
        self._loc.hover()
        self._loc.get_by_test_id("recent-menu-trigger").click()
        self._page.get_by_test_id("recent-menu").wait_for(state="visible")

    def delete(self) -> None:
        """Delete via the menu's click-twice-to-confirm Delete action."""
        self.open_menu()
        delete = self._page.get_by_test_id("recent-menu-delete")
        delete.click()  # arms
        delete.click()  # confirms

    def toggle_pin(self) -> None:
        """Pin or unpin the conversation via the menu."""
        self.open_menu()
        self._page.get_by_test_id("recent-menu-pin").click()

    def rename(self, new_name: str) -> None:
        """Rename the conversation via the menu's inline edit-in-place."""
        self.open_menu()
        self._page.get_by_test_id("recent-menu-rename").click()
        field = self._page.get_by_test_id("recent-rename-input")
        field.wait_for(state="visible")
        field.fill(new_name)
        self._page.get_by_test_id("recent-rename-save").click()


class RecentConversations:
    """The sidebar's inline recent-conversations list — search + day groups.

    Always visible while the sidebar is expanded (the default); there is
    no open/close, unlike the old flyout.
    """

    def __init__(self, page: Page):
        self.page = page

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id("recent-conversations")

    @property
    def items(self) -> Locator:
        return self.page.get_by_test_id("recent-item")

    @property
    def search(self) -> Locator:
        return self.page.get_by_test_id("recent-search")

    @property
    def search_clear(self) -> Locator:
        return self.page.get_by_test_id("recent-search-clear")

    @property
    def pinned_label(self) -> Locator:
        """The 'Pinned' section header, present only when a chat is pinned."""
        return self.page.get_by_text("Pinned", exact=True)

    def item(self, index: int) -> RecentConversationItem:
        return RecentConversationItem(self.items.nth(index), self.page)

    def open_top(self) -> "RecentConversations":
        """Load the most recent conversation."""
        self.items.first.click()
        return self
