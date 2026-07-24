"""POM for the Routines split-panel view."""

from playwright.sync_api import Locator, Page


class RoutinesView:
    """Routines sidebar panel — list on the left, detail on the right."""

    def __init__(self, page: Page):
        self.page = page

    def goto(self) -> "RoutinesView":
        self.page.goto("/")
        self.page.get_by_role("button", name="Routines", exact=True).click()
        self.page.get_by_test_id("routines-list").wait_for(state="visible")
        return self

    def goto_empty(self) -> "RoutinesView":
        """Navigate to Routines when no routines exist (the full-screen empty state)."""
        self.page.goto("/")
        self.page.get_by_role("button", name="Routines", exact=True).click()
        self.page.get_by_test_id("routines-empty").wait_for(state="visible")
        return self

    def empty_example(self) -> Locator:
        """First suggestion card in the empty state."""
        return self.page.get_by_test_id("routines-empty").get_by_test_id(
            "starter-prompt"
        ).first

    def select_by_name(self, description: str) -> None:
        self.page.get_by_test_id("routines-list").get_by_text(description, exact=True).first.click()

    def delete_from_list(self, description: str) -> None:
        """Inline two-click delete from the list row (no navigation)."""
        row = (self.page.get_by_test_id("routines-list")
               .get_by_text(description, exact=True).first
               .locator("xpath=ancestor::tr"))
        btn = row.get_by_test_id("routine-delete")
        btn.click()  # arm
        btn.click()  # confirm

    def pause_button(self) -> Locator:
        return self.page.get_by_role("button", name="Pause")

    def resume_button(self) -> Locator:
        return self.page.get_by_role("button", name="Resume")

    def run_now_button(self) -> Locator:
        return self.page.get_by_role("button", name="Run now")

    def delete_button(self) -> Locator:
        return self.page.get_by_title("Delete this routine")

    def confirm_button(self) -> Locator:
        return self.page.get_by_role("button", name="Confirm?")

    def status_label(self) -> Locator:
        return self.page.locator("[class*='activeLabel']")

    def empty_message(self) -> Locator:
        return self.page.locator("[class*='empty']")
