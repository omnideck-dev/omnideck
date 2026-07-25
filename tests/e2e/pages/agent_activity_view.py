"""POM for the Agent Activity view — a single sub-agent's activity stream."""

from __future__ import annotations

from typing import TYPE_CHECKING

from playwright.sync_api import Locator, Page

from .preview_panel import PreviewTabGroup

if TYPE_CHECKING:
    from .network_view import NetworkView


class AgentActivityView:
    """Single agent's activity log and its explicit output-opening commands."""

    def __init__(self, page: Page, agent_id: str | None = None):
        self.page = page
        self.agent_id = agent_id
        self.preview = PreviewTabGroup(page)

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id("agent-activity-view")

    @property
    def file_preview_btns(self) -> Locator:
        """Preview buttons on file outputs inside this agent's activity stream."""
        return self.root.get_by_test_id("file-preview-btn")

    def open_first_file_preview(self) -> AgentActivityView:
        btn = self.file_preview_btns.first
        btn.scroll_into_view_if_needed()
        btn.click(force=True)
        self.page.wait_for_timeout(300)
        return self

    @property
    def browser_action(self) -> Locator:
        return self.root.get_by_test_id("open-agent-browser")

    @property
    def terminal_action(self) -> Locator:
        return self.root.get_by_test_id("open-agent-terminal")

    def open_browser(self) -> AgentActivityView:
        self.browser_action.click()
        self.page.wait_for_timeout(300)
        return self

    def open_terminal(self) -> AgentActivityView:
        self.terminal_action.click()
        self.page.wait_for_timeout(300)
        return self

    def execution_tab(self, resource_id: str) -> Locator:
        assert self.agent_id, "agent_id is required to locate an agent-bound tab"
        return self.page.get_by_test_id(
            f"view-tab-{self.agent_id}:{resource_id}"
        )

    def execution_view(self, resource_id: str) -> Locator:
        assert self.agent_id, "agent_id is required to locate an agent-bound view"
        return self.page.locator(
            "[data-view-type='workspace-resource']"
            f"[data-view-owner-id='{self.agent_id}']"
            f"[data-view-resource-id='{resource_id}']"
        )

    def back_to_network(self) -> NetworkView:
        from .network_view import NetworkView as _NetworkView

        self.page.get_by_test_id("back-btn-agents").click()
        self.page.wait_for_timeout(500)
        return _NetworkView(self.page)
