"""E2E test: new profile appears in the chat panel's profile dropdown."""

from playwright.sync_api import Page, expect

from tests.e2e.pages import AgentsPage


def test_new_profile_appears_in_chat_dropdown(page: Page):
    """Create a profile via settings, verify it shows up in the chat selector."""
    agents = AgentsPage(page).goto()
    agents.profiles.new()

    agents.builder.name_input.fill("")
    agents.builder.name_input.fill("Dropdown Test Agent")

    # A model is required before the profile can be saved.
    picker = agents.builder.model_picker
    picker.open()
    picker.items().first.wait_for(state="visible", timeout=10_000)
    picker.items().first.click()

    agents.builder.save()
    page.wait_for_timeout(500)

    # Leave the Agents view and check the chat panel's profile dropdown
    agents.close()
    chat_selector = page.get_by_label("Agent profile")
    expect(chat_selector).to_be_visible()
    chat_selector.click()
    option = page.get_by_role("option", name="Dropdown Test Agent", exact=True)
    expect(option).to_be_visible()

    # Clean up
    profiles = page.request.get("/api/profiles").json()
    created = next(p for p in profiles if p["name"] == "Dropdown Test Agent")
    page.request.delete(f"/api/profiles/{created['id']}")
