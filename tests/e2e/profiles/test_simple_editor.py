"""Single-page agent editing against the real container app."""

import pytest
from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage


@pytest.mark.parametrize("width", [480, 1440])
def test_simple_agent_editor_discard_save_and_reload(page, width):
    """Visible settings, collapsed tuning, draft rollback and durable saves."""
    page.set_viewport_size({"width": width, "height": 960})
    profile_id = f"simple-editor-{width}"
    response = page.request.post("/api/profiles", data={
        "id": profile_id, "name": "Workday helper", "description": "Plan the day",
        "model": "", "system_prompt": "Keep it brief.", "skills": [],
        "browser_profile_id": None, "allow_spawn": True, "allow_load_skills": True,
        "max_iterations": 25,
    })
    assert response.ok, response.text()
    try:
        agents = AgentsPage(page).goto()
        agents.profiles.select(profile_id)
        detail = page.get_by_test_id("agent-detail")
        expect(detail.get_by_role("navigation")).to_have_count(0)
        save = detail.get_by_role("button", name="Save", exact=True)
        more = detail.get_by_role("button", name="More actions")
        save_x = save.bounding_box()["x"]
        more_x = more.bounding_box()["x"]
        expect(save).to_be_disabled()
        tuning = detail.locator("details").filter(has=page.get_by_text("Model settings", exact=True))
        assert tuning.get_attribute("open") is None
        expect(page.get_by_test_id("field-max_iterations")).to_be_visible()
        expect(page.get_by_test_id("field-max_iterations")).to_have_count(1)
        agents.builder.name_input.fill("Changed draft")
        assert abs(save.bounding_box()["x"] - save_x) < 1
        assert abs(more.bounding_box()["x"] - more_x) < 1
        agents.builder.system_prompt.fill("Find the priorities first.")
        detail.get_by_text("Delegate tasks to other agents", exact=True).click()
        detail.get_by_role("button", name="Discard", exact=True).click()
        expect(agents.builder.name_input).to_have_value("Workday helper")
        expect(agents.builder.system_prompt).to_have_value("Keep it brief.")
        expect(detail.get_by_role("switch", name="Delegate tasks to other agents")).to_be_checked()
        expect(save).to_be_disabled()
        assert page.request.get(f"/api/profiles/{profile_id}").json()["name"] == "Workday helper"

        agents.builder.name_input.fill("Day planner")
        agents.builder.system_prompt.fill("Find the priorities first.")
        detail.get_by_text("Let this agent open websites", exact=True).click()
        page.get_by_test_id("agent-browser-profile-select").click()
        page.get_by_role("option", name="Empty", exact=True).click()
        detail.get_by_text("Delegate tasks to other agents", exact=True).click()
        detail.get_by_role("spinbutton", name="Tool steps per message").fill("12")
        tuning.locator("summary").click()
        # Thinking owns a full row; inputs cannot overflow adjacent columns.
        thinking = page.get_by_test_id("field-think")
        grid_box = thinking.locator("..").bounding_box()
        thinking_box = thinking.bounding_box()
        assert abs(thinking_box["width"] - grid_box["width"]) < 1
        for control in tuning.locator("input[type=number]").all():
            assert control.evaluate("el => el.getBoundingClientRect().right <= el.parentElement.getBoundingClientRect().right + 1")
        page.get_by_test_id("field-temperature").fill("0.4")
        save.click()
        expect(save).to_be_disabled()
        expect(detail.get_by_role("status")).to_have_text("Changes saved")
        expect(detail.get_by_role("status", include_hidden=True)).to_be_empty(timeout=5000)
        stored = page.request.get(f"/api/profiles/{profile_id}").json()
        assert stored["name"] == "Day planner"
        assert stored["browser_profile_id"] == "empty"
        assert stored["allow_spawn"] is False
        assert stored["allow_load_skills"] is True
        assert stored["max_iterations"] == 12
        assert stored["temperature"] == 0.4

        agents.back()
        agents.profiles.select(profile_id)
        expect(agents.builder.name_input).to_have_value("Day planner")
        expect(page.get_by_test_id("agent-browser-profile-select")).to_have_attribute("data-value", "empty")
        expect(detail.get_by_role("switch", name="Delegate tasks to other agents")).not_to_be_checked()
        assert tuning.get_attribute("open") is None
        # Content and toolbar stay within the editor on phone and desktop widths.
        assert detail.evaluate("el => el.scrollWidth <= el.clientWidth")
        detail.get_by_role("button", name="Change agent icon").click()
        picker = page.get_by_role("menu", name="Choose agent icon")
        expect(picker).to_be_visible()
        assert picker.evaluate("el => getComputedStyle(el).backgroundColor") not in (
            "transparent", "rgba(0, 0, 0, 0)",
        )
        expect(picker).to_have_css("border-top-style", "solid")
        picker.get_by_role("menuitemradio", name="bookshelf", exact=True).click()
        expect(detail.get_by_role("button", name="Change agent icon").locator("i")).to_have_class("bi bi-bookshelf")
        save.click()
        expect(save).to_be_disabled()
        assert page.request.get(f"/api/profiles/{profile_id}").json()["icon"] == "bi-bookshelf"
        detail.get_by_role("button", name="More actions").click()
        actions = page.get_by_role("menu", name="Agent actions")
        expect(actions).to_be_visible()
        assert actions.evaluate("el => getComputedStyle(el).backgroundColor") not in (
            "transparent", "rgba(0, 0, 0, 0)",
        )
        expect(actions.get_by_role("menuitem", name="Duplicate", exact=True)).to_be_focused()
        page.keyboard.press("ArrowDown")
        expect(actions.get_by_role("menuitem", name="Export…", exact=True)).to_be_focused()
        page.keyboard.press("End")
        delete = actions.get_by_role("menuitem", name="Delete agent", exact=True)
        expect(delete).to_be_focused()
        expect(delete).to_have_css("background-color", "rgba(0, 0, 0, 0)")
        page.keyboard.press("Escape")
        expect(detail.get_by_role("button", name="More actions")).to_be_focused()
    finally:
        page.request.delete(f"/api/profiles/{profile_id}")
