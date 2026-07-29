"""Viewport regression coverage for the Agent skill picker."""

from playwright.sync_api import Page

from tests.e2e.pages import AgentsPage


def test_skill_picker_stays_inside_small_electron_viewport(page: Page):
    """Keep every skill-picker row reachable at Electron's minimum size."""
    profile_id = "test_skill_picker_viewport"
    page.request.post(
        "/api/profiles",
        data={
            "id": profile_id,
            "name": "Skill Picker Viewport",
            "description": "",
            "model": "",
            "system_prompt": "",
            "skills": [],
        },
    )
    page.set_viewport_size({"width": 880, "height": 620})

    try:
        agents = AgentsPage(page).goto()
        agents.profiles.select(profile_id)
        agents.builder.open_skill_picker()

        popover = page.get_by_test_id("profile-skill-picker")
        box = popover.bounding_box()
        assert box is not None
        assert box["y"] >= 8
        assert box["y"] + box["height"] <= 612
        assert popover.get_attribute("data-placement") == "top"
        assert popover.evaluate("(node) => node.parentElement === document.body")
    finally:
        page.request.delete(f"/api/profiles/{profile_id}")
