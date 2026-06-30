"""POM for the Goals split-panel view."""

from playwright.sync_api import Locator, Page


class GoalsView:
    """Goals sidebar panel — list on the left, detail on the right."""

    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> "GoalsView":
        self.page.goto("/")
        self.page.get_by_role("button", name="Goals", exact=True).click()
        self.page.get_by_test_id("goals-list").wait_for(state="visible")
        return self

    def goto_empty(self) -> "GoalsView":
        """Navigate to Goals when no goals exist (the full-screen empty state)."""
        self.page.goto("/")
        self.page.get_by_role("button", name="Goals", exact=True).click()
        self.page.get_by_test_id("goals-empty").wait_for(state="visible")
        return self

    def empty_example(self) -> Locator:
        """First suggestion card in the empty state."""
        return self.page.get_by_test_id("starter-prompt").first

    def select_by_name(self, description: str) -> None:
        self.page.get_by_test_id("goals-list").get_by_text(description, exact=True).first.click()

    def pause_button(self) -> Locator:
        return self.page.get_by_role("button", name="Pause")

    def resume_button(self) -> Locator:
        return self.page.get_by_role("button", name="Resume")

    def run_now_button(self) -> Locator:
        return self.page.get_by_role("button", name="Run now")

    def delete_button(self) -> Locator:
        return self.page.get_by_title("Delete this goal")

    def confirm_button(self) -> Locator:
        return self.page.get_by_role("button", name="Confirm?")

    def status_label(self) -> Locator:
        return self.page.locator("[class*='activeLabel']")

    def empty_message(self) -> Locator:
        return self.page.locator("[class*='empty']")
