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
    def root(self) -> Locator:
        """The row element locator (for attribute / visibility assertions)."""
        return self._loc

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

    def open_by_title(self, query: str) -> "RecentConversations":
        """Search by title fragment, then click the first match.

        Using search keeps tests robust to recency ordering — seeded
        conversations don't have to sort to the top.
        """
        self.search.fill(query)
        self.items.first.click()
        return self

    def item_by_id(self, conversation_id: str) -> RecentConversationItem:
        """Return a row by its conversation id — independent of list position.

        Each row carries a ``data-conversation-id`` attribute, so tests can
        target the conversation they created without assuming it sorts to a
        particular spot (a pinned conversation, for instance, sits above the
        recency-ordered rows).
        """
        loc = self.page.locator(f'[data-conversation-id="{conversation_id}"]')
        return RecentConversationItem(loc, self.page)

    def open_by_id(self, conversation_id: str) -> "RecentConversations":
        """Load a conversation by id, regardless of its position in the list."""
        self.item_by_id(conversation_id).open()
        return self

    def order(self) -> list[str]:
        """Return the conversation ids in the order they appear in the list."""
        return self.items.evaluate_all(
            "els => els.map(e => e.getAttribute('data-conversation-id'))"
        )
