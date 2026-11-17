"""Viewport regression coverage for the Agent skill picker."""

from playwright.sync_api import Page

from tests.e2e.pages import AgentsPage


def test_skill_picker_stays_inside_minimum_viewport(page: Page):
    """Keep every skill-picker row reachable at the minimum supported size."""
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
        selection = agents.builder.tools.open()

        trigger_box = selection.trigger.bounding_box()
        popover = selection.picker
        box = popover.bounding_box()
        assert trigger_box is not None
        assert box is not None
        assert box["y"] >= 8
        assert box["y"] + box["height"] <= 612
        # The shared popover may flip above the trigger to keep all options reachable.
        assert (box["y"] >= trigger_box["y"] + trigger_box["height"]
                or box["y"] + box["height"] <= trigger_box["y"])
        assert box["x"] + box["width"] <= 872
        assert popover.evaluate("(node) => node.parentElement === document.body")
    finally:
        page.request.delete(f"/api/profiles/{profile_id}")
