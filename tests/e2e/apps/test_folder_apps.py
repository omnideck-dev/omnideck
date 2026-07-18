"""End-to-end coverage for the file-based app spike."""

import re

from playwright.sync_api import Page, expect

from tests.e2e.pages import ChatView


def test_sample_folder_app_opens_and_invokes_python(page: Page) -> None:
    """The shell lists the sample, opens its frame, and bridges an action."""
    page.request.put("/api/settings", data={"custom_apps_enabled": False})
    ChatView(page).goto()

    # Custom Apps is a user setting, not an environment-level feature flag.
    expect(page.get_by_test_id("sidebar-nav-apps")).not_to_be_visible()
    page.get_by_test_id("sidebar-settings").click()
    page.get_by_test_id("settings-tab-system").click()
    custom_apps_toggle = page.get_by_role("switch", name="Custom Apps")
    expect(custom_apps_toggle).not_to_be_checked()
    page.get_by_test_id("custom-apps-toggle").click()
    expect(custom_apps_toggle).to_be_checked()
    expect(page.get_by_test_id("sidebar-nav-apps")).to_be_visible()

    page.get_by_test_id("sidebar-nav-apps").click()
    expect(page.get_by_test_id("apps-view")).to_be_visible()
    expect(page.get_by_text("Text Lab", exact=True)).to_be_visible()

    page.get_by_test_id("folder-app-card").click()
    frame = page.frame_locator('[data-testid="folder-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()
    frame.get_by_role("button", name="Analyze").click()

    expect(frame.get_by_text("Analysis complete")).to_be_visible()
    expect(frame.get_by_text("Words", exact=True)).to_be_visible()
    expect(frame.get_by_text("12", exact=True)).to_be_visible()

    # The app can explicitly open the existing chat and seed its composer.
    working_text = "This state should survive full, split, and a new conversation."
    frame.locator("#text").fill(working_text)
    frame.get_by_role("button", name="Ask agent about this").click()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).to_be_visible()
    expect(page.locator("textarea").first).to_have_value(re.compile(re.escape(working_text)))
    expect(frame.locator("#text")).to_have_value(working_text)

    # A new conversation clears conversation previews, not the shell-scoped app.
    page.get_by_test_id("sidebar-new-chat").click()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).to_be_visible()
    expect(frame.locator("#text")).to_have_value(working_text)

    # Closing the app removes its global tab and leaves Chat full-space.
    page.get_by_test_id("close-tab-app:text-lab").click()
    expect(page.get_by_test_id("preview-tab-app:text-lab")).not_to_be_visible()
    expect(page.get_by_test_id("chat-title-bar")).to_be_visible()

    # Reopen full-space before assigning it as Home.
    page.get_by_test_id("sidebar-nav-apps").click()
    page.get_by_test_id("folder-app-card").click()
    frame = page.frame_locator('[data-testid="folder-app-frame"]')
    expect(frame.get_by_role("heading", name="Text Lab")).to_be_visible()

    # Docking persists the app as Home; a full reload should land there.
    page.get_by_test_id("folder-app-home-toggle").click()
    expect(page.get_by_test_id("folder-app-home-toggle")).to_contain_text("Remove from Home")
    page.reload()

    expect(page.get_by_test_id("home-view")).to_be_visible()
    home_frame = page.frame_locator('[data-testid="folder-app-frame"]')
    expect(home_frame.get_by_role("heading", name="Text Lab")).to_be_visible()

    # Clear persisted state so this spike remains isolated from the rest of the suite.
    page.get_by_test_id("home-app-remove").click()
    expect(page.get_by_test_id("apps-view")).to_be_visible()

    # Turning the setting back off removes app navigation immediately.
    page.get_by_test_id("sidebar-settings").click()
    page.get_by_test_id("settings-tab-system").click()
    custom_apps_toggle = page.get_by_role("switch", name="Custom Apps")
    page.get_by_test_id("custom-apps-toggle").click()
    expect(custom_apps_toggle).not_to_be_checked()
    expect(page.get_by_test_id("sidebar-nav-apps")).not_to_be_visible()
