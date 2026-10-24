"""Real-layout coverage for shared skill/tool/integration selection rows."""

import pytest
from playwright.sync_api import expect

from tests.e2e.pages import AgentsPage, SettingsPage


def test_tool_grid_overflow_and_mcp_titles(page):
    """Real editor layout with a synthetic catalog; no MCP model prose leaks."""
    page.set_viewport_size({"width": 1440, "height": 1000})
    profile_id = "tool-grid-agent"
    long_title = "Search across every connected workspace and shared project document " * 3
    native_description = "Find messages matching a search in the connected account. " * 4
    category = {
        "id": "integration:grid-fixture", "connection_id": "grid-fixture",
        "label": "Grid fixture", "description": "", "connected": True, "tools": [],
        "operations": [
            {"id": "mcp.search", "title": long_title, "description": "MODEL-ONLY INSTRUCTIONS"},
            {"id": "email.messages.search", "title": "Find messages", "description": native_description},
            {"id": "mcp.list", "title": "List projects", "description": "MORE MODEL-ONLY INSTRUCTIONS"},
        ],
    }
    page.route("**/api/tool-categories", lambda route: route.fulfill(json=[category]))
    try:
        response = page.request.post("/api/profiles", data={
            "id": profile_id, "name": "Tool grid agent", "model": "", "system_prompt": "",
            "skills": [], "tool_categories": [category["id"]],
        })
        assert response.ok, response.text()
        agents = AgentsPage(page).goto()
        agents.profiles.select(profile_id)
        row = page.get_by_test_id("selected-tool:integration:grid-fixture")
        row.get_by_role("button", name="Grid fixture", exact=True).click()
        grid = row.get_by_role("list", name="Grid fixture tools")
        labels = grid.get_by_role("button")
        expect(labels).to_have_count(3)
        first, second = labels.nth(0), labels.nth(1)
        a, b = first.bounding_box(), second.bounding_box()
        assert abs(a["y"] - b["y"]) < 1 and b["x"] > a["x"], "wide layout must use columns"
        assert first.locator("span").evaluate("el => el.scrollWidth > el.clientWidth")
        first.hover()
        tooltip = page.get_by_role("tooltip")
        expect(tooltip).to_be_visible()
        expect(tooltip).to_have_text(long_title.strip())
        page.keyboard.press("Escape")
        expect(tooltip).to_have_count(0)
        second.focus()
        expect(tooltip).to_contain_text(native_description.strip())
        page.keyboard.press("Escape")
        expect(tooltip).to_have_count(0)
        # Click is also available on touch devices, without a separate info control.
        first.click()
        expect(tooltip).to_be_visible()
        expect(page.get_by_text("MODEL-ONLY INSTRUCTIONS", exact=False)).to_have_count(0)
        expect(row.locator("details")).to_have_count(0)
        page.keyboard.press("Escape")
        assert page.request.get(f"/api/profiles/{profile_id}").json()["tool_categories"] == [category["id"]]
    finally:
        page.unroute("**/api/tool-categories")
        page.request.delete(f"/api/profiles/{profile_id}")


def _assert_actions_aligned(row):
    expand = row.locator('[data-selection-action="expand"]')
    remove = row.locator('[data-selection-action="remove"]')
    for left, right in ((expand, remove), (expand.locator("i"), remove.locator("i"))):
        a, b = left.bounding_box(), right.bounding_box()
        assert a is not None and b is not None
        assert abs(a["y"] + a["height"] / 2 - b["y"] - b["height"] / 2) < 1
        assert abs(a["width"] - b["width"]) < 1
        assert abs(a["height"] - b["height"]) < 1


@pytest.mark.parametrize("width", [880, 1440])
def test_selection_row_actions_align_when_wrapped_and_expanded(page, width):
    """Both editors use the same centered actions; removal only edits the draft."""
    page.set_viewport_size({"width": width, "height": 900})
    skill_id, profile_id = "row-layout-skill", "row-layout-agent"
    connection_id = None
    try:
        response = page.request.post("/api/integrations", data={
            "slug": "test", "label": "Row layout integration", "auth_blob": {"token": "omnideck-test-token"},
            "operation_grants": [],
        })
        assert response.ok, response.text()
        connection_id = response.json()["id"]
        category_id = f"integration:{connection_id}"
        response = page.request.post("/api/skills", data={
            "id": skill_id, "name": "Research", "description": "Find and summarize sources for the weekly report. " * 12,
            "prompt": "Research the requested topic.", "tool_categories": ["memory", category_id],
        })
        assert response.ok, response.text()
        response = page.request.post("/api/profiles", data={
            "id": profile_id, "name": "Row layout agent", "model": "", "system_prompt": "",
            "skills": [skill_id], "tool_categories": ["memory", category_id],
        })
        assert response.ok, response.text()
        agents = AgentsPage(page).goto()
        agents.profiles.select(profile_id)
        for key, label in ((f"skill:{skill_id}", "Research"), ("tool:memory", "Memory"), (f"tool:{category_id}", "Row layout integration")):
            row = page.get_by_test_id(f"selected-{key}")
            toggle = row.get_by_role("button", name=label, exact=True)
            expect(toggle).to_be_visible()
            row.scroll_into_view_if_needed()
            _assert_actions_aligned(row)
            if label == "Research":
                description = row.locator(f'[id="{toggle.get_attribute("aria-describedby")}"]')
                assert description.bounding_box()["height"] > 30, "fixture must wrap the description"
            toggle.focus()
            toggle.press("Enter")
            expect(toggle).to_have_attribute("aria-expanded", "true")
            _assert_actions_aligned(row)
            toggle.press("Space")
            expect(toggle).to_have_attribute("aria-expanded", "false")
            _assert_actions_aligned(row)
        page.get_by_role("button", name="Remove Memory", exact=True).click()
        expect(page.get_by_test_id("selected-tool:memory")).to_have_count(0)
        expect(page.get_by_test_id(f"selected-skill:{skill_id}")).to_be_visible()
        expect(page.get_by_role("button", name="Add", exact=True)).to_be_focused()
        assert "memory" in page.request.get(f"/api/profiles/{profile_id}").json()["tool_categories"]

        # Navigate afresh to discard that unsaved profile draft, then exercise
        # the same row in the skill editor without changing saved selections.
        skills = SettingsPage(page).goto_skills().skills
        skills.select(skill_id)
        for key, label in (("memory", "Memory"), (category_id, "Row layout integration")):
            row = page.get_by_test_id(f"selected-tool:{key}")
            toggle = row.get_by_role("button", name=label, exact=True)
            row.scroll_into_view_if_needed()
            _assert_actions_aligned(row)
            toggle.click()
            expect(toggle).to_have_attribute("aria-expanded", "true")
            _assert_actions_aligned(row)
        page.get_by_role("button", name="Remove Memory", exact=True).click()
        expect(page.get_by_test_id("selected-tool:memory")).to_have_count(0)
        assert "memory" in page.request.get(f"/api/skills/{skill_id}").json()["tool_categories"]
    finally:
        page.request.delete(f"/api/profiles/{profile_id}")
        page.request.delete(f"/api/skills/{skill_id}")
        if connection_id:
            page.request.delete(f"/api/integrations/{connection_id}")
